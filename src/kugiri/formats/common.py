from __future__ import annotations

import html
import re

from ..textutil import is_dialogue, is_half, join_texts, normalize, render_map
from ..timeline import Cue, Unit

_TAG = re.compile(r"<[^>]*>")
_ASS_OVERRIDE = re.compile(r"\{\\[^}]*\}")


def decode(data: bytes) -> str:
    """字幕文件字节 → 文字：有 BOM 按 BOM（UTF-8 / UTF-16），否则 UTF-8，不是 UTF-8 时按 Shift_JIS（cp932）。

    日本的 Windows 软件（旧版字幕工具、记事本另存）常输出 Shift_JIS 或 UTF-16。
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    head = data[:200]
    if head and head.count(b"\x00") * 4 >= len(head):     # 没有 BOM 的 UTF-16（NUL 字节在 UTF-8 里也合法）
        return data.decode("utf-16-le" if head[1:2] == b"\x00" else "utf-16-be")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp932")
    except UnicodeDecodeError as e:
        raise ValueError("unknown text encoding (UTF-8 / UTF-16 / Shift_JIS are supported); save the file as UTF-8 first") from e


def split_blocks(text: str) -> list[list[str]]:
    """SRT / VTT 按空行分块，每块是行列表。只有空白的行也算空行，但时间行后面紧跟的空白行不算：
    YouTube 自动字幕每段第一条 cue 的第一行是一个空格（`` ``），不能把它当分隔把正文切掉。"""
    out: list[list[str]] = []
    for chunk in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        rows = chunk.strip("\n").split("\n")
        if out and out[-1] and "-->" in out[-1][-1] and not any("-->" in r for r in rows):
            out[-1] += rows
        else:
            out.append(rows)
    return out


def dedupe_rolling(raw: list[tuple[float, float, list[str]]], key=lambda s: s
                   ) -> list[tuple[float, float, list[str]]]:
    """滚动字幕（YouTube 自动字幕、直播字幕）去重：每条 cue 开头重复上一条末尾的行时去掉这些行，
    去完没剩东西的 cue（YouTube 的 10ms 过渡 cue）整条丢掉。

    普通字幕里也会有连续两条一样的话（「はい」「はい」），所以只在整份文件看起来是滚动字幕时才去重：
    多行 cue 里至少一半、且至少 3 条以「上一条的最后一行」开头。``key`` 把原始行变成用来比较的文字（去标签）。
    """
    multi = [(p, c) for p, c in zip(raw, raw[1:]) if len(c[2]) > 1 and p[2]]
    rolling = sum(key(c[2][0]) == key(p[2][-1]) and key(c[2][0]) != "" for p, c in multi)
    if rolling < 3 or rolling * 2 < len(multi):
        return raw
    out, prev = [], []
    for s, e, lines in raw:
        cur = [key(x) for x in lines]
        k = next((k for k in range(min(len(cur), len(prev)), 0, -1) if cur[:k] == prev[-k:]), 0)
        rest = [x for x, y in zip(lines[k:], cur[k:]) if y != ""]
        if any(cur):
            prev = [y for y in cur if y != ""]
        if rest:
            out.append((s, e, rest))
    return out


def merge_repeats(raw: list[tuple[float, float, list[str]]], key=lambda s: s
                  ) -> list[tuple[float, float, list[str]]]:
    """逐词高亮的字幕（WhisperX ``--highlight_words`` 的 ``<u>``、卡拉 OK 式导出）：同一句话按词拆成很多条
    首尾相接、文字一样的 cue → 合成一条。和滚动字幕一样，只在这种 cue 有 3 对以上、占到相邻对的 1/5 以上时才合并。"""
    def same(p, c):
        return [key(x) for x in p[2]] == [key(x) for x in c[2]] and c[0] - p[1] < 0.05
    pairs = list(zip(raw, raw[1:]))
    n = sum(same(p, c) for p, c in pairs)
    if n < 3 or n * 5 < len(pairs):
        return raw
    out = [raw[0]]
    for c in raw[1:]:
        if same(out[-1], c):
            out[-1] = (out[-1][0], max(out[-1][1], c[1]), out[-1][2])
        else:
            out.append(c)
    return out


def dedupe(raw: list[tuple[float, float, list[str]]], key=lambda s: s) -> list[tuple[float, float, list[str]]]:
    """别家字幕的重复：先按开始时间排序，再去滚动字幕的重复行、合并逐词高亮的重复 cue。"""
    raw = sorted(raw, key=lambda r: r[0])
    return merge_repeats(dedupe_rolling(raw, key), key)


def timed_cue(start: float, end: float, pieces: list[tuple[float | None, float | None, str]],
              speaker: str | None = None) -> Cue | None:
    """带词级时间的几段文字（YouTube 自动字幕的 ``<c>``、Whisper 系 JSON 的 words）→ 一条 Cue + units。

    每段文字单独规范化后直接接起来；只有段本身以空白开头、两边又都是半角英数字时才留一个空格
    （Whisper 系的英文词带前导空格，日语 WhisperX 一个字一段、数字也一位一段：2 0 2 6 不能加空格）。
    时间为 None 的段（Whisper 系对数字常不给时间）不出 unit，断行时贴到相邻的字。
    """
    text, units, last = "", [], start
    for t0, t1, raw in pieces:
        raw = html.unescape(raw)
        w = normalize(raw)
        if not w:
            continue
        if text and raw[:1].isspace() and is_half(text[-1]) and text[-1].isalnum() and is_half(w[0]) and w[0].isalnum():
            text += " "
        cs = len(text)
        text += w
        if t0 is not None and t1 is not None:      # 词的时间偶尔乱序：拉成不倒退
            t0 = max(t0, last)
            last = t0
            units.append(Unit(cs, len(text), t0, max(t0, t1)))
    if not text:
        return None
    return Cue(start, end, text, None, units, speaker=speaker)


def clean_line(s: str) -> str:
    """去掉 HTML 风格标签和 ASS 覆盖标签（{\\an8}），反转义实体。"""
    s = _ASS_OVERRIDE.sub("", s)
    s = _TAG.sub("", s)
    return html.unescape(s).replace("​", "").strip()


_SPEAKER_LINE = re.compile(r"^>>\s*(\S{0,20})$")


def make_cue(start: float, end: float, lines: list[str], speaker: str | None = None) -> Cue | None:
    """几行字幕文字 → 一条 Cue（原分行不保留，reflow 会重新断行）。

    YouTube 习惯：单独一行 ``>> 名前`` 是说话人，``>> 台词`` 表示换人说话（去掉 ``>>``）。
    Netflix 式两人对话（每行以 ``-`` 开头）保留分行，见 ``is_dialogue``。
    """
    out = []
    for x in lines:
        m = _SPEAKER_LINE.match(x)
        if m and (len(lines) > 1 or not m.group(1)):
            speaker = speaker or m.group(1) or None
            continue
        if x.startswith(">>"):
            x = x[2:].strip()
        if x:
            out.append(x)
    if not out:
        return None
    if is_dialogue(out):      # 「-行こう / -うん」两个人一条：保留原来的分行（reflow 不动它）
        return Cue(start, end, "".join(out), out, speaker=speaker)
    return Cue(start, end, join_texts(out), None, speaker=speaker)


def ts(t: float, sep: str, hours_min: int = 2) -> str:
    ms = max(0, round(t * 1000))
    h, r = divmod(ms, 3_600_000)
    m, r = divmod(r, 60_000)
    s, ms = divmod(r, 1000)
    return f"{h:0{hours_min}d}:{m:02d}:{s:02d}{sep}{ms:03d}"


_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")


def parse_ts(s: str) -> float:
    m = _TS.match(s.strip())
    if not m:
        raise ValueError(f"bad timestamp: {s!r}")
    h, mi, se, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")) / 1000


def rendered_lines(cue: Cue, punct: str, ruby: bool = False) -> list[list[tuple[str, str | None]]]:
    """cue 的每一行渲染成片段列表 [(文字, 振假名或 None)]；跨行或被渲染改掉的振假名丢弃。"""
    out = []
    rubies = sorted(cue.ruby, key=lambda r: r.cs) if ruby else []
    for a, b in cue.line_spans():
        shown, idx = render_map(cue.text[a:b], punct)
        if not shown:
            continue
        src = [a + i for i in idx]
        pieces: list[tuple[str, str | None]] = []
        k = 0
        while k < len(shown):
            r = next((r for r in rubies if r.cs == src[k] and a <= r.cs and r.ce <= b), None)
            if r is not None:
                n = r.ce - r.cs
                if src[k:k + n] == list(range(r.cs, r.ce)):
                    pieces.append((shown[k:k + n], r.text))
                    k += n
                    continue
            if pieces and pieces[-1][1] is None:
                pieces[-1] = (pieces[-1][0] + shown[k], None)
            else:
                pieces.append((shown[k], None))
            k += 1
        out.append(pieces)
    return out


def plain_lines(cue: Cue, punct: str) -> list[str]:
    return ["".join(t for t, _ in line) for line in rendered_lines(cue, punct)]
