"""agent 参与断行：把候选断点交给调用方的模型按意思挑，kugiri 再用这些标记跑断行 DP。

流程（MCP 工具 ``break_candidates`` → ``reflow(hints)``，CLI ``kugiri reflow --show-breaks`` / ``--hints``）：

1. ``candidates(doc, p)``：和 ``reflow`` 同样分块、同样分析断点；规则允许、且至少是文节边界的位置
   编上全局号，在这些位置把文字切成一行一个短语，号写在行首，指这一行**后面**的断点（``4 いい天気だね (pause 0.6s)``，
   块的最后一行写 ``end``）。号插在文字中间（``今日は|3|いい天気``）时 sonnet 常标成相邻的号（40 段里 404 个标记
   约 60 个错一位）；号指「这一行前面」时模型常按「这一行是句末」去标，也错一位。
2. 模型读文字，给出 ``sentence``（这里是句子 / 话语的分界）和 ``keep``（这里断开会拆散一个意思单位）两组号。
3. ``labels(view, sentence, keep)`` → {块编号: {位置: "sent" | "keep"}} → ``reflow(hints=…)``。

模型只能从编了号的位置里挑，禁则 / 数字单位 / 括号 / 词典禁止分割等硬约束没有号，改不了。
``key`` 是候选集的哈希：文件、预设或词典变了号就对不上，要重新取候选。
"""
from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass, field

from .reflow import Params, _analyze, char_times, prepare
from .textutil import is_speech
from .timeline import Document
from .userdict import UserDict

# 给编号的断点类型（文节边界及更好的位置；复合词内部、补助动词前、附属语前不给）
SHOWN = ("sent", "comma", "final", "clause", "particle", "bunsetsu")
PAUSE_SHOW = 0.3
PAGE_CHARS = 1500

GUIDE = """The text is split at every break point allowed by the Japanese line-breaking rules, one phrase per line.
The number at the start of a line names the break point right AFTER that phrase (`end` = end of the block);
`(pause 0.6s)` means the speaker pauses there. A block (`#3 0:01:02.5–0:01:20.0`) is a stretch of continuous
speech. Spoken subtitles often have no punctuation, so the rules cannot tell where one sentence ends and the next
begins — that is your job. Read the text for meaning, line by line, and return:
- sentence: the number of EVERY line that ends a sentence or utterance (the next line starts a new one: a new
  topic, a reply, a change of speaker, an interjection like えっ/あ/うわ that starts a new remark). In casual
  speech a sentence usually ends every few lines. Lines ending with 。？！ are sentence ends anyway; you need not
  list them.
- keep: rarely needed — only a line that must not be separated from the next one because the break would split a
  single word or a stutter (す、|すごい). Most files need none.
Unlisted numbers keep what the rules see in them. Hard rules (kinsoku, numbers with units, brackets) cannot be
overridden. Do not rewrite the text."""


@dataclass
class View:
    """候选断点一览。``ids[i] = (块编号, 位置)``；``rows[b]`` = 第 b 块的 [(一行文字, 号 | None)]，第一行是块头。"""
    key: str
    ids: list[tuple[int, int]] = field(default_factory=list)
    rows: list[list[tuple[str, int | None]]] = field(default_factory=list)

    @property
    def blocks(self) -> list[str]:
        return ["\n".join(t for t, _ in r) for r in self.rows]

    def pages(self, page_chars: int = PAGE_CHARS) -> list[tuple[str, list[int]]]:
        """按字数分页（长块可以在行之间拆开，续页写「(continued)」块头）；返回 [(文字, 这页的号)]。"""
        out, cur, nums, size = [], [], [], 0
        for b, rows in enumerate(self.rows):
            head, body = rows[0][0], rows[1:] or [rows[0]]
            for j, (t, n) in enumerate(body):
                if cur and size + len(t) > page_chars:
                    out.append(("\n".join(cur), nums))
                    cur, nums, size = [], [], 0
                if rows[1:] and (j == 0 or not cur):
                    cur.append(head if j == 0 else f"#{b} (continued)")
                cur.append(t)
                size += len(t)
                if n is not None:
                    nums.append(n)
        if cur or not out:
            out.append(("\n".join(cur), nums))
        return out

    def page(self, k: int = 0, page_chars: int = PAGE_CHARS) -> dict:
        ps = self.pages(page_chars)
        if not 0 <= k < len(ps):
            raise ValueError(f"page {k} out of range (0–{len(ps) - 1})")
        text, nums = ps[k]
        return {"key": self.key, "page": k, "pages": len(ps), "ids": [nums[0], nums[-1]] if nums else [],
                "text": text}

    def text(self) -> str:
        return "\n".join(self.blocks)


def _ts(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m // 60)}:{int(m % 60):02d}:{s:04.1f}"


def candidates(doc: Document, p: Params, *, mode: str = "resegment", udict: UserDict | None = None,
               norm: bool = True) -> View:
    """文档 → 带编号的候选断点（编号全局连续，块的划分和 ``reflow`` 一样）。"""
    v = View("")
    h = hashlib.sha1(f"{mode}\n{p.max_width}\n{p.bracket_max}\n{p.punct}\n{p.sudachi_mode}".encode())
    for bi, blk in enumerate(prepare(doc, p, mode, norm)):
        if blk.text is None:            # 两人对话 cue 原样保留，不给候选
            lines = [x.strip() for x in blk.cues[0].lines]
            v.rows.append([(f"#{bi} {_ts(blk.cues[0].start)} (dialogue, kept as is) " + " / ".join(lines), None)])
            h.update(f"\x00{bi}\x00dialogue".encode())
            continue
        text = blk.text
        br = _analyze(text, p, udict)
        st, en = char_times(text, blk.units)
        speech = [i for i in range(len(text)) if is_speech(text[i])]
        rows, a = [], 0
        for k in range(1, len(text)):
            if br.kind[k] not in SHOWN:
                continue
            j = bisect.bisect_left(speech, k)
            pause = st[speech[j]] - en[speech[j - 1]] if 0 < j < len(speech) else 0.0
            nid = len(v.ids)
            v.ids.append((bi, k))
            rows.append((f"{nid} {text[a:k]}" + (f" (pause {pause:.1f}s)" if pause >= PAUSE_SHOW else ""), nid))
            a = k
            h.update(f"\x00{bi}:{k}".encode())
        rows.append((f"end {text[a:]}", None))
        h.update(f"\x00{bi}\x00{text}".encode())
        v.rows.append([(f"#{bi} {_ts(blk.cues[0].start)}–{_ts(blk.cues[-1].end)}", None), *rows])
    v.key = h.hexdigest()[:10]
    return v


def labels(view: View, sentence=(), keep=(), key: str | None = None) -> dict[int, dict[int, str]]:
    """agent 给的号 → ``reflow(hints=…)`` 的 {块编号: {位置: "sent" | "keep"}}。同一个号两边都给时算句界。"""
    if key is not None and key != view.key:
        raise ValueError(f"hints key {key!r} does not match this file and options (now {view.key!r}): the file, "
                         "preset, mode or user dictionary changed — get the break candidates again")
    out: dict[int, dict[int, str]] = {}
    bad = []
    for lab, nums in (("keep", keep), ("sent", sentence)):
        if not isinstance(nums, (list, tuple)):
            raise ValueError(f"{'sentence' if lab == 'sent' else 'keep'} must be a list of numbers, got {nums!r}")
        for n in nums:
            if isinstance(n, str) and n.strip().isdigit():
                n = int(n)
            if type(n) is not int or not 0 <= n < len(view.ids):
                bad.append(n)
                continue
            b, k = view.ids[n]
            out.setdefault(b, {})[k] = lab
    if bad:
        raise ValueError(f"unknown break numbers {bad[:10]} (valid: 0–{len(view.ids) - 1})")
    return out
