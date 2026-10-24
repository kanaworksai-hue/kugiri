"""台本 → CTC 对齐串。

- 只对齐「发音字符」（字母类、数字、ー）；标点、括号、空白不占时间，交给 reflow 贴到相邻字。
- 汉字、假名逐字对齐（omniASR 字表 1 万多字，绝大多数汉字直接在表里）。
- 下面几种词整词换成读音假名再对齐，整词输出一个 unit（带 ``reading``）：
  字表外的字（儚、碁 …）、数字（2026 → にせんにじゅうろく）、拉丁字母（AI → エーアイ；日语里读成片假名）、
  用户词典里给了读音的词。读音来自 ja-core（pyopenjtalk-plus + 用户词典）。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..reading import tokens
from ..userdict import UserDict

_LATIN_OR_DIGIT = re.compile(r"[0-9A-Za-z０-９Ａ-Ｚａ-ｚ]")
_SYMBOL = re.compile(r"[%％&＆+＋℃°＄$€£¥￥#＃@＠]")


def is_speech_char(ch: str) -> bool:
    """会发音的字符：字母类（汉字、假名、拉丁字母）、数字、长音。"""
    if ch in "ー〜～":
        return ch == "ー"
    cat = unicodedata.category(ch)
    return cat.startswith("L") or cat in ("Nd", "No", "Nl")


def hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


@dataclass
class Targets:
    chars: str                                  # 对齐串（模型字符）
    spans: list[tuple[int, int]]                # 对齐串每个字对应的原文 [cs, ce)
    readings: dict[tuple[int, int], str] = field(default_factory=dict)   # 整词换读音的区间 → 片假名读音
    n_speech: int = 0                           # 原文发音字符数
    n_dropped: int = 0                          # 没法对齐（读音也拼不出来）的发音字符数
    oov: str = ""                               # 字表外的字


def build_targets(text: str, in_vocab, udict: UserDict | None = None, spell: str = "auto") -> Targets:
    """``in_vocab(c) -> bool``。``spell``：``auto``（数字/字母/字表外/词典读音 → 读音）或 ``oov``（只换字表外）。"""
    speech = [i for i, c in enumerate(text) if is_speech_char(c)]
    t = Targets("", [], n_speech=len(speech))
    norm = {i: _char(text[i]) for i in speech}
    oov = {i for i in speech if not in_vocab(norm[i])}
    t.oov = "".join(sorted({text[i] for i in oov}))
    need_reading = bool(oov) or (spell == "auto" and (_LATIN_OR_DIGIT.search(text) or _SYMBOL.search(text)
                                                      or udict is not None))
    toks = _tokens(text, udict) if need_reading else []

    replace: dict[int, tuple[int, int, str]] = {}      # 原文下标 → (ws, we, 读音)
    for tk in toks:
        rng = range(tk.cs, tk.ce)
        if not tk.read or not any(_is_kana(c) for c in tk.read):
            continue
        if not any(i in norm for i in rng):
            # 会读出来的符号（% → パーセント、℃ → ド、& → アンド）：auto 模式下也按读音对齐
            if spell == "auto" and _SYMBOL.search(tk.surface):
                for i in rng:
                    replace[i] = (tk.cs, tk.ce, tk.read)
            continue
        if any(i in oov for i in rng) or (spell == "auto" and (tk.user or _LATIN_OR_DIGIT.search(tk.surface))):
            for i in rng:
                replace[i] = (tk.cs, tk.ce, tk.read)

    out: list[tuple[str, int, int]] = []
    done: set[tuple[int, int]] = set()
    for i in sorted(set(speech) | set(replace)):
        if i in replace:
            ws, we, read = replace[i]
            if (ws, we) in done:
                continue
            done.add((ws, we))
            latin = bool(re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ'’.\-]+", text[ws:we]))
            kana = read if latin else hira(read)
            got = [(c, ws, we) for c in kana if _is_kana(c) and in_vocab(c)]
            if got:
                out += got
                t.readings[(ws, we)] = read
            else:
                t.n_dropped += sum(1 for j in range(ws, we) if j in norm)
            continue
        if i in oov:
            t.n_dropped += 1
            continue
        out.append((norm[i], i, i + 1))
    t.chars = "".join(c for c, _, _ in out)
    t.spans = [(a, b) for _, a, b in out]
    return t


def _tokens(text: str, udict: UserDict | None, limit: int = 300):
    """分块调用 ja-core 的 tokens（OpenJTalk 一次处理不了太长的文本）：按换行切，太长的行再按句读点/空白切。"""
    out = []
    for m in re.finditer(r"[^\n]+", text):
        a, b = m.start(), m.end()
        while a < b:
            e = b
            if e - a > limit:
                cut = max((k for k in range(a + limit // 2, a + limit) if text[k] in "。！？!?、, 　"), default=None)
                if cut is None:      # 没有标点：至少别切在数字/英文单词中间
                    cut = max((k for k in range(a + limit // 2, a + limit)
                               if not (text[k].isascii() and text[k].isalnum())
                               and not (text[k + 1].isascii() and text[k + 1].isalnum())), default=a + limit - 1)
                e = cut + 1
            for t in tokens(text[a:e], udict):
                t.cs += a
                t.ce += a
                out.append(t)
            a = e
    return out


def _char(c: str) -> str:
    n = unicodedata.normalize("NFKC", c)
    return n if len(n) == 1 else c


def _is_kana(c: str) -> bool:
    return "ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" or c == "ー"
