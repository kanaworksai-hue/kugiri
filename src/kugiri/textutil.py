"""日语字幕的字符规则：字符类、禁则、显示宽度、规范化、显示渲染。

宽度按 Netflix 日语字幕指南计数：全角 1、半角 0.5。
句读点渲染（``punct``）：
- ``netflix``：、→半角空格，。→全角空格，行首行尾的空白和句读点去掉（日语指南 I.17）。
- ``keep``：原样保留，只去掉行首行尾空白。
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 字符类
NO_HEAD = set("、。，．,.:;：；)）]］}｝」』】〕〉》〙〗’”?？!！ー〜～…‥・"
              "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿ々ゝゞヽヾ%％")
"""行首禁则：不能出现在行首（也不能出现在 cue 开头）。"""
NO_TAIL = set("(（[［{｛「『【〔〈《〘〖‘“￥＄$#＃")
"""行尾禁则：不能出现在行尾。"""
BRACKETS = {"（": "）", "(": ")", "「": "」", "『": "』", "【": "】", "〈": "〉", "《": "》",
            "[": "]", "［": "］", "〔": "〕"}
SENT_END = set("。！？!?…‥")
COMMA = set("、，,")
SPACES = set(" 　")
PUNCT_STYLES = ("netflix", "keep")

_DIGIT = r"[0-9０-９]"
_UNIT = (r"(?:円|点|人|名|%|％|年|ヶ月|か月|カ月|月|日|時|分|秒|台|個|回|歳|才|万|億|千|兆|本|枚|件|倍|位|番|号|度|℃|機|階|"
         r"週|代|割|部|章|話|杯|匹|頭|冊|曲|両|km|kg|mm|cm|m|g|ps|PS|cc|GB|MB|KB|TB|fps|Hz|kHz|ms|px)")
NUM_SPAN = re.compile(rf"(?:第)?(?:{_DIGIT}+(?:[,.:/／：]{_DIGIT}+)*{_UNIT}?)+(?:目|間|後|前|頃|ごろ)?")
"""数字+单位（可连写：2010年12月3日、4,505mm、12:30、第3回、1/2）——内部不能断开。"""
ALNUM_WORD = re.compile(r"[A-Za-z0-9Ａ-Ｚａ-ｚ０-９][A-Za-z0-9Ａ-Ｚａ-ｚ０-９'._\-]+")


def is_half(c: str) -> bool:
    return unicodedata.east_asian_width(c) in ("Na", "H")


def char_width(c: str, punct: str = "netflix") -> float:
    """排版时一个原文字符占的宽度。netflix 风格下读点渲染成半角空格。"""
    if punct == "netflix" and (c in COMMA or c == " "):
        return 0.5
    return 0.5 if is_half(c) else 1.0


def display_width(s: str) -> float:
    """已渲染文本的显示宽度。"""
    return sum(0.5 if is_half(c) else 1.0 for c in s)


def is_speech(c: str) -> bool:
    """会被读出来的字符（用于字级时间插值）：空白以外都算，标点占时极短但不影响插值的位置。"""
    return c not in SPACES and not c.isspace()


# ---------------------------------------------------------------- 渲染
def render_map(s: str, punct: str = "netflix") -> tuple[str, list[int]]:
    """把一行原文渲染成显示文本，同时返回每个显示字符对应的原文下标（振假名定位用）。"""
    chars = list(enumerate(s))
    while chars and chars[0][1].isspace():
        chars.pop(0)
    if punct == "netflix":
        while chars and (chars[-1][1].isspace() or chars[-1][1] in "、。，,"):
            chars.pop()
    else:
        while chars and chars[-1][1].isspace():
            chars.pop()
    out: list[tuple[int, str]] = []
    for i, c in chars:
        if punct == "netflix":
            if c in "、，":
                c = " "
            elif c == "。":
                c = "　"
        if c == " " and out and out[-1][1] == " ":
            continue
        out.append((i, c))
    while out and out[0][1] in SPACES:
        out.pop(0)
    while out and out[-1][1] in SPACES:
        out.pop()
    return "".join(c for _, c in out), [i for i, _ in out]


def render_line(s: str, punct: str = "netflix") -> str:
    return render_map(s, punct)[0]


def line_width(s: str, punct: str = "netflix") -> float:
    return display_width(render_line(s, punct))


# ---------------------------------------------------------------- 规范化
_HALF_KANA = re.compile(r"[｡-ﾟ]+")
_FULL_ALNUM = re.compile(r"[０-９Ａ-Ｚａ-ｚ]")
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
_JA = r"[぀-ヿ㐀-鿿！-｠々〆〇ー]"


def normalize(text: str) -> str:
    """字幕文本规范化（不改变语言内容）：

    - 半角片假名 → 全角（ｶﾞ → ガ）；全角英数字 → 半角（Ｇ５ → G5），数字间的全角逗号/点 → 半角。
    - 「...」「・・・」「‥‥」→「…」；零宽字符去掉；全角空格、连续空白 → 1 个半角空格。
    - 紧跟日文的半角 ! ? → 全角 ！？。
    """
    s = unicodedata.normalize("NFC", text)
    s = _ZERO_WIDTH.sub("", s)
    s = _HALF_KANA.sub(lambda m: unicodedata.normalize("NFKC", m.group()), s)
    s = _FULL_ALNUM.sub(lambda m: unicodedata.normalize("NFKC", m.group()), s)
    s = re.sub(r"(?<=[0-9])[，．](?=[0-9])", lambda m: "," if m.group() == "，" else ".", s)
    s = re.sub(r"・{3,}|\.{3,}|‥{2,}", "…", s)
    s = re.sub(rf"(?<={_JA})!", "！", s)
    s = re.sub(rf"(?<={_JA})\?", "？", s)
    s = re.sub(r"[\s　]+", " ", s).strip()
    return s


_JA_SPACE = re.compile(rf"(?<={_JA})[ 　]+(?={_JA})")
_JA_CHAR = re.compile(_JA)


def word_spaced(texts: list[str]) -> bool:
    """整份字幕是不是「词和词之间用空格隔开」的日语（部分识别 / 翻译工具的输出：今日 は 天気 が いい）。

    Netflix 式字幕也用空格代替句读点（、→半角 。→全角），但那是每句一两个；按词隔开时日文字符间的空格
    大约每 2–4 个字一个。日文字符两侧的空格数 ≥ 日文字符数的 1/6 才算按词隔开。"""
    ja = sum(len(_JA_CHAR.findall(t)) for t in texts)
    sp = sum(len(_JA_SPACE.findall(t)) for t in texts)
    if ja < 20 or sp * 6 < ja:
        return False
    # Netflix 式短对话（うん わかった / えっ 何？）一条只有一两个空格；按词隔开时 8 字以上的一条一般有 3 个以上
    per = sorted(len(_JA_SPACE.findall(t)) for t in texts if len(_JA_CHAR.findall(t)) >= 8)
    return bool(per) and per[len(per) // 2] >= 3


_ANY_SPACE = re.compile(r"(?<=\S)[ 　]+(?=\S)")


def strip_word_spaces(text: str) -> str:
    """去掉词间空格（日文和日文、日文和英数字之间：12 時間 → 12時間），两边都是半角英数字的保留（iPhone 15）。"""
    def keep(m: re.Match) -> str:
        a, b = text[m.start() - 1], text[m.end()]
        return " " if is_half(a) and a.isalnum() and is_half(b) and b.isalnum() else ""
    return _ANY_SPACE.sub(keep, text)


SOUND_TAG = re.compile(r"^\s*(?:[\[［(（【〈《][^\]］)）】〉》]{1,10}[\]］)）】〉》]|[♪♫♬～〜 　]+)\s*$")
"""整条只有音效 / 说明的 cue：[音楽]、（拍手）、【笑】、♪～。"""
DASHES = "-－‐‑"


def is_dialogue(lines: list[str] | None) -> bool:
    """Netflix 式「一条两个人说」：两行以上，每行以连字符开头（-行こう / -うん）。"""
    return (bool(lines) and len(lines) >= 2
            and all(x[:1] in DASHES and len(x) > 1 and not x[1].isdigit() and x[1] not in DASHES for x in lines))


def join_texts(parts: list[str]) -> str:
    """把几行 / 几条 cue 的文字接成一串：两边都是半角英数字时补一个空格，否则直接相连（日语不用空格）。"""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and is_half(out[-1]) and out[-1].isalnum() and is_half(p[0]) and p[0].isalnum():
            out += " "
        out += p
    return out
