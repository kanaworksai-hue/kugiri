"""用户词典（TSV，UTF-8）。

每行一个词，Tab 分隔：``表記<TAB>読み<TAB>禁止分割``

- 表記：必填，原文里出现的写法（规范化后比较，见 ``textutil.normalize``）。
- 読み：可空。平假名或片假名都行，会覆盖 pyopenjtalk 的读音，也用于振假名。
- 禁止分割：可空，默认 ``1``（这个词内部不换行、不切 cue）；写 ``0`` / ``no`` / ``false`` 表示可以拆。
- ``#`` 开头的行是注释；第一行若是 ``表記`` / ``surface`` 开头则当表头跳过。
- 没有 Tab 的行：第二段是假名时按空格分列（网页的文本框里打不出 Tab），否则整行当表記。
- 读音不是假名、禁止分割不是 1/0 之类、列太多时报错（带行号），不悄悄跳过。

例::

    # 表記	読み	禁止分割
    東京AI映像	とうきょうえーあいえいぞう	1
    VRChat	ぶいあーるちゃっと
    明日	あす	0
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .textutil import normalize

_FALSE = {"0", "no", "false", "n", "split", "可"}
_TRUE = {"", "1", "yes", "true", "y", "nosplit", "不可"}
_KANA = re.compile(r"^[ぁ-ゖァ-ヺー・゛゜]+$")
_SPACES = re.compile(r"[ \u3000]+")


@dataclass(frozen=True)
class Entry:
    surface: str
    reading: str | None = None   # 片假名
    nosplit: bool = True


@dataclass
class UserDict:
    entries: list[Entry] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "UserDict":
        from .service import read_text
        text = read_text(path, "user dictionary")
        try:
            return cls.parse(text)
        except ValueError as e:
            raise ValueError(f"{path}: {e}") from None

    @classmethod
    def parse(cls, tsv: str) -> "UserDict":
        out: list[Entry] = []
        bad: list[str] = []
        for no, raw in enumerate(tsv.splitlines(), 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if "\t" in raw:
                cols = [c.strip() for c in raw.split("\t")]
            else:
                cols = _SPACES.split(raw.strip())
                looks_tsv = len(cols) == 3 and cols[2].lower() in _FALSE | _TRUE   # 「銀座 ginza 1」：按列检查并报错
                if not looks_tsv and (len(cols) == 1 or len(cols) > 3 or not _KANA.match(cols[1])):
                    cols = [raw.strip()]
            if no == 1 and cols[0].lower() in ("表記", "surface"):
                continue
            while len(cols) > 1 and not cols[-1]:
                cols.pop()
            surface = normalize(cols[0])
            if not surface:
                bad.append(f"line {no}: the first column (surface) is empty")
                continue
            if len(cols) > 3:
                bad.append(f"line {no}: {len(cols)} columns; expected surface, reading, no-split")
                continue
            reading = cols[1] if len(cols) > 1 and cols[1] else None
            if reading and not _KANA.match(reading):
                bad.append(f"line {no}: the reading {reading!r} must be hiragana or katakana")
                continue
            flag = cols[2].lower() if len(cols) > 2 else ""
            if flag not in _FALSE | _TRUE:
                bad.append(f"line {no}: the no-split column must be 1 or 0 (got {cols[2]!r})")
                continue
            out.append(Entry(surface, to_katakana(reading) if reading else None, nosplit=flag not in _FALSE))
        if bad:
            more = f" (and {len(bad) - 5} more)" if len(bad) > 5 else ""
            raise ValueError("user dictionary: " + "; ".join(bad[:5]) + more +
                             ". Format: surface<TAB>reading<TAB>no-split (1/0), one word per line")
        return cls(out)

    def find(self, text: str) -> list[tuple[int, int, Entry]]:
        """在 text 里找词典词，最长优先、从左到右、互不重叠。"""
        if not self.entries:
            return []
        by_len = sorted(self.entries, key=lambda e: -len(e.surface))
        taken = [False] * len(text)
        hits = []
        for e in by_len:
            start = 0
            while (i := text.find(e.surface, start)) >= 0:
                j = i + len(e.surface)
                if not any(taken[i:j]):
                    hits.append((i, j, e))
                    for k in range(i, j):
                        taken[k] = True
                start = i + 1
        return sorted(hits, key=lambda h: h[0])


def to_katakana(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def to_hiragana(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)
