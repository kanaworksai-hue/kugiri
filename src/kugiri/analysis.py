"""断点分析：SudachiPy 文节边界 + 禁则 → 每个位置的断开代价。

位置 k（0 < k < n）表示在 ``text[k]`` 之前断开。代价分级见 ``KIND_COST``（越小越好断），
硬约束（代价 = inf）：行首禁则字符、行尾禁则字符、数字+单位内部、短括号内部、半角英数字词内部、
空格前、用户词典「禁止分割」词内部。
文节边界用 SudachiPy：模式 C 的词内部不断（模式 B 的复合词边界给较高代价，再细只在没办法时断）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
import threading
from functools import lru_cache

from .textutil import (ALNUM_WORD, BRACKETS, COMMA, NO_HEAD, NO_TAIL, NUM_SPAN, SENT_END, SPACES,
                       char_width)
from .userdict import UserDict

INF = math.inf

KIND_COST = {
    "sent": 0.0,      # 句末（。！？…）
    "pause": 0.5,     # 停顿（仅分段时，有时间信息）
    "comma": 1.0,     # 读点、空格
    "final": 1.0,     # 终助词之后（口语字幕常没有句号）
    "clause": 2.0,    # 接续助词之后 / 接续词之前
    "particle": 3.0,  # 格助词、系助词、副助词之后的文节边界
    "bunsetsu": 4.0,  # 其他文节边界
    "aux": 7.0,       # 补助动词/形式名词之前（〜て|しまう、する|こと）
    "compound": 8.0,  # 模式 C 复合词内部、模式 B 边界（特別|支援学校）
    "attach": 15.0,   # 附属语之前（生産|された、行け|そう）
    "inword": 25.0,   # 词内部（只在别无选择时）
}

_SUDACHI_MAX = 4000   # SudachiPy 单次输入有字节上限，长文本按句切开分析


@lru_cache(maxsize=1)
def _dictionary():
    from sudachipy import Dictionary
    return Dictionary()


_local = threading.local()


def _tokenizer():
    """每个线程一个 tokenizer（SudachiPy 的 tokenizer 不能多线程同时用；网页 / MCP 的后台任务和请求线程会并行断行）。"""
    tok = getattr(_local, "tok", None)
    if tok is None:
        tok = _local.tok = _dictionary().tokenizer()
    return tok


def _mode(name: str):
    from sudachipy import SplitMode
    return {"A": SplitMode.A, "B": SplitMode.B, "C": SplitMode.C}[name]


# 只认插话式的短感叹词；こんにちは / ありがとう 在 Sudachi 里也是感動詞，但常接在前面的话后面（皆さんこんにちは）
_EXCLAIM = {"え", "えっ", "ええっ", "あ", "あっ", "ああ", "あぁ", "うわ", "うわっ", "わっ", "おっ", "おお", "おぉ", "へえ", "へぇ",
            "ほら", "よし", "やばっ"}
# 句末之后的接续词，Sudachi 切成两个附属语（でも = で + も、だけど = だ + けど）：〜ました|でも 要能断
_CONJ_SPLIT = {("で", "も"), ("だ", "けど"), ("だ", "けれど"), ("だ", "から"), ("だ", "が"), ("じゃ", "あ"), ("じゃ", "ぁ")}
_INDEPENDENT = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "接頭辞"}


def boundary_kind(prev, m, prev2=None, nxt=None) -> str:
    """SudachiPy morpheme prev 与 m 之间的边界类型（prev2 = prev 前一个词，判断「ました」用；nxt = m 后一个词）。"""
    pp, mp = prev.part_of_speech(), m.part_of_speech()
    ps, ms = prev.surface(), m.surface()
    if ps and ps[-1] in SENT_END:
        return "sent"
    if pp[0] == "空白" or (ps and ps[-1] in COMMA):
        return "comma"
    if ms and ms[0] in BRACKETS:
        return "particle"                     # 开括号之前
    if ps and ps[-1] in BRACKETS.values() and mp[0] not in ("助詞", "助動詞", "補助記号"):
        return "particle"                     # 闭括号之后（后面不是附属语）
    if mp[0] in ("補助記号",) or mp[0] == "空白":
        return "attach"                       # 由禁则/空格规则另行处理
    if pp[0] == "接頭辞" or mp[0] == "接尾辞":
        return "attach"
    if mp[0] == "接続詞":
        return "clause"
    if mp[0] == "感動詞" and ms in _EXCLAIM and pp[0] not in ("感動詞", "補助記号"):
        return "final"                        # 短感叹词开头是新的话（〜やつ|えっ！？、〜だ|あ お母さんだ）
    if m.dictionary_form() in ("いう", "言う") and ps in ("って", "と", "そう", "こう", "ああ", "どう"):
        return "aux"                          # 〜っていう / そういう 不拆
    if pp[0] == "助詞" and pp[1] == "終助詞" and mp[0] != "助詞":
        return "final"
    polite_ta = pp[4] == "助動詞-タ" and prev2 is not None and prev2.part_of_speech()[4] in ("助動詞-マス", "助動詞-デス")
    sent_final = pp[0] == "助動詞" and (pp[5].startswith("終止形") or ((pp[4] in ("助動詞-マス", "助動詞-デス") or polite_ta)
                                                                     and pp[5].startswith("連体形")))
    if sent_final and pp[4] in ("助動詞-マス", "助動詞-デス", "助動詞-タ") and nxt is not None \
            and (ms, nxt.surface()) in _CONJ_SPLIT:
        return "final"                        # 〜ました|でも、〜です|だけど（没有标点的口语）
    if (sent_final
            and mp[0] in _INDEPENDENT and mp[0] != "接頭辞"
            and (mp[1] != "非自立可能" or mp[0] == "動詞") and mp[1] != "助動詞語幹"):
        return "final"                        # 没有句号的句末：〜ました|霊夢です、紹介します|明日は、ありました|ありました
                                              # （ます/です/ました 后接名词时被标成连体形；非自立动词 ある/いる/する 也算新句）
    indep = mp[0] in _INDEPENDENT
    if mp[1] == "非自立可能" or mp[1] == "助動詞語幹":
        if mp[0] == "動詞" and pp[0] == "助詞" and pp[1] == "接続助詞" and ps in ("て", "で"):
            return "aux"
        if mp[0] == "動詞" and pp[0] == "名詞" and m.dictionary_form() in ("する", "できる", "出来る"):
            return "attach"
        if mp[0] == "形容詞" and pp[0] == "助詞":
            return "aux"
        if mp[0] == "名詞":
            return "aux"
        if mp[1] == "助動詞語幹":
            return "attach"
    if not indep:
        return "attach"
    if pp[0] == "助詞":
        return "clause" if pp[1] == "接続助詞" else "particle"
    if pp[0] in ("名詞", "代名詞") and mp[0] == "名詞":
        return "compound"
    return "bunsetsu"


def protected_spans(text: str, bracket_max: float, udict: UserDict | None = None,
                    punct: str = "netflix") -> list[tuple[int, int]]:
    """内部不能断开的区间 [a, b)。"""
    spans = [(m.start(), m.end()) for m in NUM_SPAN.finditer(text) if m.end() - m.start() > 1]
    spans += [(m.start(), m.end()) for m in ALNUM_WORD.finditer(text)]
    stack: list[tuple[str, int]] = []
    for i, c in enumerate(text):
        if c in BRACKETS:
            stack.append((c, i))
        elif stack and c == BRACKETS[stack[-1][0]]:
            _, a = stack.pop()
            if sum(char_width(x, punct) for x in text[a:i + 1]) <= bracket_max:
                spans.append((a, i + 1))
    if udict is not None:
        spans += [(a, b) for a, b, e in udict.find(text) if e.nosplit]
    return spans


@dataclass
class Breaks:
    """text 每个位置 k 的断点代价和类型；``kind[k] == "forbidden"`` 表示不能断。"""
    text: str
    cost: list[float]
    kind: list[str]
    punct: str = "netflix"
    _pw: list[float] = field(default_factory=list)   # 前缀宽度

    def __post_init__(self):
        acc = [0.0]
        for c in self.text:
            acc.append(acc[-1] + char_width(c, self.punct))
        self._pw = acc

    def width(self, a: int, b: int) -> float:
        """text[a:b] 作为一行显示时的宽度（去掉行首行尾空白；netflix 风格再去掉行尾句读点）。"""
        t = self.text
        while a < b and t[a] in SPACES:
            a += 1
        if self.punct == "netflix":
            while b > a and (t[b - 1] in SPACES or t[b - 1] in COMMA or t[b - 1] == "。"):
                b -= 1
        else:
            while b > a and t[b - 1] in SPACES:
                b -= 1
        return self._pw[b] - self._pw[a]


def _chunks(text: str) -> list[tuple[int, int]]:
    if len(text) <= _SUDACHI_MAX:
        return [(0, len(text))]
    out, a = [], 0
    while len(text) - a > _SUDACHI_MAX:
        cut = max((i + 1 for i in range(a, a + _SUDACHI_MAX) if text[i] in SENT_END or text[i] in SPACES),
                  default=a + _SUDACHI_MAX)
        out.append((a, cut))
        a = cut
    out.append((a, len(text)))
    return out


def analyze(text: str, *, sudachi_mode: str = "C", kind_cost: dict | None = None, bracket_max: float = 13.0,
            udict: UserDict | None = None, punct: str = "netflix") -> Breaks:
    kind_cost = kind_cost or KIND_COST
    n = len(text)
    kind = ["inword"] * (n + 1)
    tok = _tokenizer()
    for ca, cb in _chunks(text):
        part = text[ca:cb]
        if not part.strip():
            continue
        morphs = list(tok.tokenize(part, _mode(sudachi_mode)))
        for j in range(1, len(morphs)):
            kind[ca + morphs[j].begin()] = boundary_kind(morphs[j - 1], morphs[j], morphs[j - 2] if j >= 2 else None,
                                                         morphs[j + 1] if j + 1 < len(morphs) else None)
        if sudachi_mode == "C":
            for m in morphs:
                if m.end() - m.begin() > 1:
                    for sub in list(m.split(_mode("B")))[1:]:
                        kind[ca + sub.begin()] = "compound"
        if ca > 0:
            kind[ca] = "sent" if text[ca - 1] in SENT_END else "comma"
    # 字符层面的修正：句末/读点/空格后面一律是好断点
    for k in range(1, n):
        if text[k - 1] in SENT_END and text[k] not in SENT_END:
            kind[k] = "sent"
        elif text[k - 1] in COMMA or text[k - 1] in SPACES:
            kind[k] = "comma" if kind[k] != "sent" else "sent"
    cost = [INF] * (n + 1)
    for k in range(1, n):
        cost[k] = kind_cost[kind[k]]
    forbid = set()
    for k in range(1, n):
        if text[k] in SPACES:
            forbid.add(k)
            continue
        i = k                                    # 断点前最后一个非空白字符
        while i > 0 and text[i - 1] in SPACES:
            i -= 1
        if text[k] in NO_HEAD or (i > 0 and text[i - 1] in NO_TAIL):
            forbid.add(k)
    for a, b in protected_spans(text, bracket_max, udict, punct):
        forbid.update(range(a + 1, b))
    for k in forbid:
        cost[k] = INF
        kind[k] = "forbidden"
    cost[0] = cost[n] = 0.0
    kind[0] = kind[n] = "edge"
    return Breaks(text, cost, kind, punct)


def is_violation(text: str, k: int) -> bool:
    """在 text[k] 之前断开是否违反禁则 / 拆开数字+单位（跳过断点两侧的空白再判断）。测试和评测用。"""
    j = k
    while j < len(text) and text[j].isspace():
        j += 1
    i = k
    while i > 0 and text[i - 1].isspace():
        i -= 1
    if j < len(text) and text[j] in NO_HEAD:
        return True
    if i > 0 and text[i - 1] in NO_TAIL:
        return True
    return any(m.start() < k < m.end() and m.end() - m.start() > 1 for m in NUM_SPAN.finditer(text))
