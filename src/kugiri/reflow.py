"""断行引擎：候选断点 + 代价函数 + 两层动态规划（cue 分段 × cue 内换行）。

- ``wrap(text, p)``：一条 cue 内换行（1–``max_lines`` 行）。
- ``segment(text, units, p)``：把一段连续台词重新切成 cue，每条 cue 再换行。``units`` 是字/词级时间
  （``[{cs, ce, start, end}]``，cs/ce 是 text 的字符下标），来自对齐器；只有字幕文件时用 cue 内线性插值。
- ``retime(cues, p)``：时间规则——最短/最长显示时长、字幕间隔 2 帧、短空隙合并、整帧吸附。
- ``reflow(doc, p)``：整份文档的入口（``kugiri reflow``）。

规则来源：Netflix 日语字幕指南（每行 13 全角字、最多 2 行、4 字/秒、最短 0.5 秒）、通用指南（最长 7 秒）、
Timing Guidelines（间隔 2 帧，3–11 帧@24fps 的空隙合并成 2 帧）。
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace

from .analysis import INF, KIND_COST, Breaks, analyze
from .textutil import (SOUND_TAG, SPACES, is_dialogue, is_speech, join_texts, line_width, normalize, strip_word_spaces,
                       word_spaced)
from .timeline import Cue, Document, Unit
from .userdict import UserDict


@dataclass
class Params:
    # 版面
    max_width: float = 13.0      # 每行宽度（全角 1、半角 0.5）
    max_lines: int = 2
    punct: str = "netflix"       # 句读点渲染风格，见 textutil
    # 时间
    cps: float = 4.0             # 阅读速度（字/秒，软约束）
    min_dur: float = 0.5
    max_dur: float = 7.0
    fps: float = 30.0
    gap_frames: int = 2          # 相邻字幕至少隔几帧
    merge_gap: float = 0.5       # 比这短的空隙合并到 gap_frames（Netflix：3–11 帧@24fps）
    snap: bool = True            # 起止时间吸附到整帧
    linger: bool = True          # 字幕在下一条出现之前多留一会儿：留够按 cps 读完的时间、至少 pref_dur（不超过 max_dur）
    linger_max: float = 1.5      # 最多比说话结束晚这么多秒（后面是长静音时不一直挂着）
    # 断点分析
    sudachi_mode: str = "C"
    kind_cost: dict = field(default_factory=lambda: dict(KIND_COST))
    bracket_max: float = 13.0    # 不超过这个宽度的括号整体不拆
    # 换行
    w_balance: float = 2.0       # 行宽差 / max_width 的权重
    w_over: float = 100.0        # 每超出 1 字的代价（放得下时几乎不会超宽；M0 原型 20）
    w_extra_line: float = 3.0    # 第 3 行起每多一行的代价（max_lines > 2 时）
    # 分段
    block_gap: float = 2.0       # 输入字幕间隔超过这个秒数就分开处理（不跨长静音合并）
    w_cue_break: float = 1.5     # cue 边界相对行内换行的权重
    c_cue: float = 1.0           # 每条 cue 的固定代价（越大 cue 越少越满；M0 原型 5.0）
    w_sent_inside: float = 6.0   # 「一句一条」：cue 中间每含一个句末（。！？…）的代价
    w_final_inside: float = 6.0  # 同上，终助词之后（口语常没有句号：〜ね|、〜よ|）
    w_sent_line: float | None = None  # 句末正好在 cue 内换行处时用这个代价代替上面两个（None = 不区分）
    pause_min: float = 0.25      # 视为停顿的最短间隔（秒）
    pause_max_cost: float = 4.0  # 停顿只在代价不超过这个（文节边界）的断点上生效（补助动词前 / 词内的停顿多是犹豫或对齐误差）
    pause_hard: float = 1.2      # cue 内含超过这个长度的停顿时加重罚
    w_inner_pause: float = 8.0
    w_cps: float = 0.6
    w_over_dur: float = 30.0
    w_short: float = 3.0         # 宽度 < 3 字的 cue
    w_short_dur: float = 10.0    # 可显示时间不到 min_dur 时，每缺 1 秒的代价
    pref_dur: float = 1.0        # linger 时每条至少留这么久（0.5 秒的字幕读不完）
    # agent 标记（hints）
    hint_kind: str = "sent"      # 标成句界的位置当哪种断点（sent：代价 0、cue 中间有它重罚 w_sent_inside）
    hint_demote: bool = False    # 没被标成句界的「无句号句末」（final）降成普通接续处（clause）；盲评上不降略好

    @property
    def gap_s(self) -> float:
        return self.gap_frames / self.fps


PRESETS: dict[str, dict] = {
    # Netflix 日语字幕指南：13 字 × 2 行，4 字/秒，0.5–7 秒，24fps 素材常见
    "netflix": dict(max_width=13.0, max_lines=2, cps=4.0, min_dur=0.5, max_dur=7.0, fps=24.0),
    # 横屏网络视频：口语快（4.5–8 字/秒），行可以稍长
    "youtube": dict(max_width=16.0, max_lines=2, cps=6.0, min_dur=0.7, max_dur=7.0, fps=30.0,
                    bracket_max=16.0),
    # 竖屏短视频（Shorts / TikTok / Reels）：字大、行短、一条更短
    "vertical": dict(max_width=10.0, max_lines=2, cps=6.0, min_dur=0.5, max_dur=5.0, fps=30.0,
                     bracket_max=10.0),
}


def preset(name: str, **overrides) -> Params:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r} (choose from {', '.join(PRESETS)})")
    return replace(Params(), **{**PRESETS[name], **{k: v for k, v in overrides.items() if v is not None}})


def _analyze(text: str, p: Params, udict: UserDict | None) -> Breaks:
    return analyze(text, sudachi_mode=p.sudachi_mode, kind_cost=p.kind_cost, bracket_max=p.bracket_max,
                   udict=udict, punct=p.punct)


# ---------------------------------------------------------------- cue 内换行
def layout(br: Breaks, a: int, b: int, p: Params) -> tuple[float, list[int]]:
    """把 text[a:b] 排成 1–max_lines 行；返回 (代价, 换行位置列表)。放得下一行就不换。"""
    W = p.max_width
    w = br.width(a, b)
    if w <= W or p.max_lines < 2:
        return (max(0.0, w - W) * p.w_over, [])
    best = (max(0.0, w - W) * p.w_over + 2 * p.w_over, [])   # 硬塞一行（兜底）
    best_over = INF
    ks = [k for k in range(a + 1, b) if br.cost[k] < INF]
    for k in ks:
        w1, w2 = br.width(a, k), br.width(k, b)
        if w1 == 0 or w2 == 0:
            continue
        over = max(0.0, w1 - W) + max(0.0, w2 - W)
        total = br.cost[k] + over * p.w_over + p.w_balance * abs(w1 - w2) / W
        if total < best[0]:
            best, best_over = (total, [k]), over
    if p.max_lines >= 3 and best_over > 0:
        for x, k1 in enumerate(ks):
            w1 = br.width(a, k1)
            if w1 == 0 or w1 > W:
                continue
            for k2 in ks[x + 1:]:
                w2, w3 = br.width(k1, k2), br.width(k2, b)
                if w2 == 0 or w3 == 0:
                    continue
                if w2 > W:
                    break
                over = max(0.0, w3 - W)
                total = (br.cost[k1] + br.cost[k2] + over * p.w_over + p.w_extra_line
                         + p.w_balance * (max(w1, w2, w3) - min(w1, w2, w3)) / W)
                if total < best[0]:
                    best = (total, [k1, k2])
    return best


def wrap(text: str, p: Params | None = None, udict: UserDict | None = None,
         br: Breaks | None = None) -> list[str]:
    """一条 cue 内换行，返回各行原文子串（拼起来等于 text）。"""
    p = p or Params()
    br = br or _analyze(text, p, udict)
    _, ks = layout(br, 0, len(text), p)
    cuts = [0, *ks, len(text)]
    return [text[x:y] for x, y in zip(cuts, cuts[1:])]


# ---------------------------------------------------------------- 字级时间
def char_times(text: str, units: list[dict]) -> tuple[list[float], list[float]]:
    """把 units 展开成每个字符的 (start, end)；没覆盖到的字符贴到相邻字符。"""
    n = len(text)
    st: list[float | None] = [None] * n
    en: list[float | None] = [None] * n
    for u in units:
        cs, ce = u["cs"], u["ce"]
        span = max(1, ce - cs)
        for i in range(cs, min(ce, n)):
            st[i] = u["start"] + (u["end"] - u["start"]) * (i - cs) / span
            en[i] = u["start"] + (u["end"] - u["start"]) * (i - cs + 1) / span
    last = None
    for i in range(n):
        if st[i] is None:
            st[i] = en[i] = last
        else:
            last = en[i]
    nxt = None
    for i in range(n - 1, -1, -1):
        if st[i] is None:
            st[i] = en[i] = nxt
        else:
            nxt = st[i]
    if any(x is None for x in st):
        raise ValueError("no units: character timings are missing")
    return st, en  # type: ignore[return-value]


def linear_units(text: str, spans: list[tuple[int, int, float, float]]) -> list[dict]:
    """每个 (cs, ce, start, end) 区间内按发音字符线性插值，生成字级 units（空白不占时间）。"""
    out = []
    for cs, ce, t0, t1 in spans:
        idx = [i for i in range(cs, ce) if is_speech(text[i])]
        step = (t1 - t0) / max(1, len(idx))
        for j, i in enumerate(idx):
            out.append({"cs": i, "ce": i + 1, "start": t0 + j * step, "end": t0 + (j + 1) * step})
    return out


# ---------------------------------------------------------------- 分段
@dataclass
class OutCue:
    cs: int
    ce: int
    start: float
    end: float
    cuts: list[int]          # cue 内换行位置（text 绝对下标）


def segment(text: str, units: list[dict], p: Params | None = None, udict: UserDict | None = None,
            br: Breaks | None = None) -> list[OutCue]:
    """全局 DP：在候选断点里选 cue 边界，使 (边界代价 + 换行代价 + 时长/阅读速度罚) 最小。"""
    p = p or Params()
    br = br or _analyze(text, p, udict)
    st, en = char_times(text, units)
    n = len(text)
    speech = [i for i in range(n) if is_speech(text[i])]
    if not speech:
        return []
    # 停顿：位置 k 之前最后一个发音字符的结束 → k 之后第一个发音字符的开始
    gap = [0.0] * (n + 1)
    for x, y in zip(speech, speech[1:]):
        g = max(0.0, st[y] - en[x])
        for k in range(x + 1, y + 1):
            gap[k] = g
    cut_cost = [INF] * (n + 1)
    for k in range(1, n):
        c = br.cost[k]
        if c == INF:
            continue
        if gap[k] >= p.pause_min and c <= p.pause_max_cost:
            c = min(c, p.kind_cost["pause"]) - min(gap[k], 2.0)
        cut_cost[k] = c * p.w_cue_break
    cut_cost[0] = cut_cost[n] = 0.0
    cands = [k for k in range(n + 1) if cut_cost[k] < INF]
    cap = p.max_width * p.max_lines
    sent_pos = [k for k in range(1, n) if br.kind[k] == "sent"]
    final_pos = [k for k in range(1, n) if br.kind[k] == "final"]
    prefix_speech = [0] * (n + 1)
    for i, c in enumerate(text):
        prefix_speech[i + 1] = prefix_speech[i] + (1 if is_speech(c) else 0)

    def first_speech(a, b):
        j = bisect.bisect_left(speech, a)
        return speech[j] if j < len(speech) and speech[j] < b else None

    def last_speech(a, b):
        j = bisect.bisect_left(speech, b) - 1
        return speech[j] if j >= 0 and speech[j] >= a else None

    def cue_cost(a: int, b: int) -> tuple[float, list[int]]:
        lc, ks = layout(br, a, b, p)
        c = lc + p.c_cue + cut_cost[b]
        fa, la = first_speech(a, b), last_speech(a, b)
        if fa is None:
            return c, ks
        dur = en[la] - st[fa]
        nxt = first_speech(b, n + 1) if b < n else None
        disp = (st[nxt] - p.gap_s if nxt is not None else en[la] + 1.0) - st[fa]
        disp = min(max(disp, dur), p.max_dur)
        c += p.w_short_dur * max(0.0, p.min_dur - disp)
        nch = prefix_speech[b] - prefix_speech[a]
        c += p.w_cps * max(0.0, nch / max(disp, p.min_dur) - p.cps)
        c += p.w_over_dur * max(0.0, dur - p.max_dur)
        inner = max((gap[k] for k in range(a + 1, b)), default=0.0)
        if inner > p.pause_hard:
            c += p.w_inner_pause * (inner - p.pause_hard + 1)
        if br.width(a, b) < 3:
            c += p.w_short
        if p.w_sent_inside:
            c += p.w_sent_inside * (bisect.bisect_left(sent_pos, b) - bisect.bisect_right(sent_pos, a))
        if p.w_final_inside:
            c += p.w_final_inside * (bisect.bisect_left(final_pos, b) - bisect.bisect_right(final_pos, a))
        if p.w_sent_line is not None:
            for k in ks:
                if br.kind[k] == "sent":
                    c += p.w_sent_line - p.w_sent_inside
                elif br.kind[k] == "final":
                    c += p.w_sent_line - p.w_final_inside
        return c, ks

    best: dict[int, tuple[float, int, list[int]]] = {0: (0.0, -1, [])}
    for j in cands[1:]:
        bj: tuple[float, int, list[int]] = (INF, -1, [])
        pos = bisect.bisect_left(cands, j) - 1
        while pos >= 0:   # 往回看，宽度不超过总容量（至少看最近的一个候选，保证可行）
            i = cands[pos]
            c, ks = cue_cost(i, j)
            tot = best[i][0] + c
            if tot < bj[0]:
                bj = (tot, i, ks)
            if br.width(i, j) > cap + 2:
                break
            pos -= 1
        best[j] = bj
    bounds, k = [], n
    while k > 0:
        _, i, ks = best[k]
        bounds.append((i, k, ks))
        k = i
    bounds.reverse()
    out = []
    for a, b, ks in bounds:
        fa, la = first_speech(a, b), last_speech(a, b)
        if fa is None:
            continue
        out.append(OutCue(a, b, st[fa], en[la], ks))
    return out


# ---------------------------------------------------------------- 时间规则
def retime(cues: list[Cue], p: Params) -> list[Cue]:
    """原地调整 cue 的起止时间：最短/最长时长、读完所需时间（linger）、间隔 gap_frames、短空隙合并、整帧吸附。"""
    if not cues:
        return cues
    f = p.fps
    if p.snap:
        conv, back = (lambda t: round(t * f)), (lambda x: x / f)
        min_d, max_d = math.ceil(p.min_dur * f - 1e-6), math.floor(p.max_dur * f + 1e-6)
        gap, merge, one = p.gap_frames, round(p.merge_gap * f), 1
    else:
        conv, back = (lambda t: t), (lambda x: x)
        min_d, max_d, gap, merge, one = p.min_dur, p.max_dur, p.gap_s, p.merge_gap, 1 / f
    S = [conv(c.start) for c in cues]
    E = [conv(c.end) for c in cues]
    for i in range(len(cues)):
        s = S[i]
        e = max(E[i], s + min_d)
        if p.linger and p.cps > 0:
            need = max(sum(is_speech(ch) for ch in cues[i].text) / p.cps, p.pref_dur)
            need = math.ceil(need * f - 1e-6) if p.snap else need
            e = max(e, min(s + need, E[i] + (round(p.linger_max * f) if p.snap else p.linger_max)))
        if i + 1 < len(cues):
            ns = S[i + 1]
            if ns - s - gap < min_d and s + min_d + gap <= E[i + 1] - min_d:
                ns = S[i + 1] = s + min_d + gap   # 太短（「あっ！」紧接着下一句）：下一条晚一点出现，两条都够最短时长
            if ns - e < merge:
                e = ns - gap
            e = min(e, ns - gap)
        e = min(e, s + max_d)
        E[i] = max(e, s + one)
    for c, s, e in zip(cues, S, E):
        c.start, c.end = back(s), back(e)
    return cues


# ---------------------------------------------------------------- 文档
def _fits(br: Breaks, cuts: list[int], p: Params) -> bool:
    return len(cuts) - 1 <= p.max_lines and all(br.width(a, b) <= p.max_width for a, b in zip(cuts, cuts[1:]))


def _make_cue(text: str, a: int, b: int, inner: list[int], start: float, end: float,
              units: list[dict] | None, speaker: str | None) -> Cue | None:
    while a < b and text[a] in SPACES:
        a += 1
    while b > a and text[b - 1] in SPACES:
        b -= 1
    if a >= b:
        return None
    cuts = [a, *[k for k in inner if a < k < b], b]
    lines = [text[x:y] for x, y in zip(cuts, cuts[1:])]
    us = []
    for u in units or []:
        cs, ce = max(u["cs"], a), min(u["ce"], b)
        if cs < ce or (u["cs"] == u["ce"] and a <= u["cs"] < b):
            us.append(Unit(cs - a, ce - a, u["start"], u["end"], u.get("reading"), u.get("conf")))
    return Cue(start, end, text[a:b], lines, us, [], speaker)


def _cue_text(c: Cue, norm: bool, spaced: bool = False) -> str:
    if c.units:            # 有字级时间时不改文字，否则下标对不上
        return c.text
    t = join_texts(c.lines) if c.lines else c.text
    if spaced:
        t = strip_word_spaces(t)
    return normalize(t) if norm else t


def _block_input(cues: list[Cue], norm: bool, spaced: bool = False) -> tuple[str, list[dict], bool]:
    text, spans, units, has_units = "", [], [], False
    for c in cues:
        t = _cue_text(c, norm, spaced)
        if text and t:
            joined = join_texts([text, t])
            if len(joined) > len(text) + len(t):
                text += " "
        off = len(text)
        text += t
        if c.units:
            has_units = True
            units += [{"cs": u.cs + off, "ce": u.ce + off, "start": u.start, "end": u.end,
                       "reading": u.reading, "conf": u.conf} for u in c.units]
        else:
            spans.append((off, off + len(t), c.start, c.end))
    units += linear_units(text, spans)
    units.sort(key=lambda u: u["cs"])
    return text, units, has_units


def _alone(c: Cue) -> bool:
    """不和别的 cue 连起来重切的 cue：整条是音效 / 说明（[音楽]、（拍手）、♪）、两个人一条的对话（-行こう / -うん）。"""
    return is_dialogue(c.lines) or bool(SOUND_TAG.match(c.text))


def _split_dialogue(c: Cue, norm: bool) -> list[Cue]:
    """放不下的两人对话 cue → 每人一条（去掉开头的连字符），时间按字数分。"""
    lines = [x[1:].strip() for x in c.lines or []]
    lines = [normalize(x) if norm else x for x in lines]
    total = sum(len(x) for x in lines) or 1
    out, t = [], c.start
    for x in lines:
        e = t + (c.end - c.start) * len(x) / total
        out.append(Cue(t, e, x, None, [], [], c.speaker))
        t = e
    out[-1].end = c.end
    return out


def blocks(cues: list[Cue], p: Params, alone=None) -> list[list[Cue]]:
    """相邻且间隔不超过 block_gap、说话人相同的 cue 合成一块；音效 / 对话 cue 单独一块（``_alone``）。"""
    alone = alone or _alone
    out: list[list[Cue]] = []
    for c in sorted(cues, key=lambda c: c.start):
        if (out and c.start - out[-1][-1].end <= p.block_gap and c.speaker == out[-1][-1].speaker
                and not alone(c) and not alone(out[-1][-1])):
            out[-1].append(c)
        else:
            out.append([c])
    return out


@dataclass
class Block:
    """``reflow`` 的一个处理单位：连起来重切的一组 cue。``text is None`` = 两人对话 cue，原样保留。"""
    cues: list[Cue]
    text: str | None = None
    units: list[dict] = field(default_factory=list)
    has_units: bool = False


def prepare(doc: Document, p: Params, mode: str = "resegment", norm: bool = True) -> list[Block]:
    """把文档分成 ``reflow`` 的处理块（``hints.candidates`` 也用它，块的编号两边一致）。"""
    if mode not in ("resegment", "wrap"):
        raise ValueError(f"unknown mode {mode!r}")
    cues, split = [], set()
    for c in doc.cues:                     # 两个人一条：放得下就每行原样保留，放不下拆成每人一条
        if is_dialogue(c.lines) and not (len(c.lines) <= p.max_lines and all(
                line_width(normalize(x) if norm else x, p.punct) <= p.max_width for x in c.lines)):
            parts = _split_dialogue(c, norm)
            cues += parts
            split |= {id(x) for x in parts}
        else:
            cues.append(c)
    groups = (blocks(cues, p, lambda c: _alone(c) or id(c) in split) if mode == "resegment"
              else [[c] for c in cues])
    spaced = norm and word_spaced([c.text for c in cues if not c.units])
    out = []
    for g in groups:
        if is_dialogue(g[0].lines):
            out.append(Block(g))
            continue
        text, units, has_units = _block_input(g, norm, spaced)
        if text.strip():
            out.append(Block(g, text, units, has_units))
    return out


def reflow(doc: Document, p: Params | None = None, *, mode: str = "resegment", udict: UserDict | None = None,
           norm: bool = True, timing: bool | None = None, hints: dict[int, dict[int, str]] | None = None) -> Document:
    """重新断行。

    - ``mode="resegment"``：相邻 cue 连成一段重新切 cue + 换行，再套时间规则（cue 边界会移动，
      字级时间不动：来自 units，没有 units 时按原 cue 内线性插值）。
    - ``mode="wrap"``：保留原 cue 和时间，只重新换行；放不下 max_lines 行的 cue 才在内部拆开。
    ``timing``：是否套时间规则，默认 resegment 套、wrap 不套。
    ``hints``：{块编号: {断点位置: "sent" | "keep"}}，agent 按意思标的句界 / 不要断开处（见 ``hints``）。
    没标的位置按规则原样（``Params.hint_demote`` 时没被标成句界的「无句号句末」降成普通接续处）。
    """
    p = p or Params()
    timing = (mode == "resegment") if timing is None else timing
    out: list[Cue] = []
    for bi, blk in enumerate(prepare(doc, p, mode, norm)):
        g = blk.cues
        if blk.text is None:
            lines = [normalize(x) if norm else x for x in g[0].lines]
            out.append(Cue(g[0].start, g[0].end, "".join(lines), lines, [], [], g[0].speaker))
            continue
        text, units, has_units = blk.text, blk.units, blk.has_units
        br = _analyze(text, p, udict)
        if hints is not None:
            apply_hints(br, hints.get(bi, {}), p)
        if mode == "wrap":
            _, ks = layout(br, 0, len(text), p)
            if _fits(br, [0, *ks, len(text)], p):
                c = _make_cue(text, 0, len(text), ks, g[0].start, g[0].end, units if has_units else None,
                              g[0].speaker)
                if c:
                    out.append(c)
                continue
        parts = segment(text, units, p, udict, br)
        sub = []
        for oc in parts:
            c = _make_cue(text, oc.cs, oc.ce, oc.cuts, oc.start, oc.end, units if has_units else None,
                          g[0].speaker)
            if c:
                sub.append(c)
        if mode == "wrap" and sub:        # 拆开的 cue 仍占满原 cue 的时间范围
            sub[0].start = g[0].start
            sub[-1].end = g[-1].end
            for x, y in zip(sub, sub[1:]):
                x.end = y.start
        out += sub
    out.sort(key=lambda c: c.start)
    if timing:
        retime(out, p)
    return Document(out, doc.language, p.fps if timing and p.snap else doc.fps)


def apply_hints(br: Breaks, labels: dict[int, str], p: Params) -> None:
    """把 agent 的标记写进断点代价（原地）。只改本来就能断的位置，禁则等硬约束不变。"""
    if p.hint_kind not in p.kind_cost:
        raise ValueError(f"hint_kind {p.hint_kind!r} is not a break type ({', '.join(p.kind_cost)})")
    for k in range(1, len(br.text)) if p.hint_demote else ():
        if br.kind[k] == "final" and labels.get(k) != "sent":
            br.kind[k] = "clause"                   # agent 没认成句界的「无句号句末」
            br.cost[k] = p.kind_cost["clause"]
    for k, lab in labels.items():
        if not 0 < k < len(br.text) or br.cost[k] == INF:
            continue
        if lab == "sent":
            if br.kind[k] != "sent":                # 句号后的句界本来就是 sent
                br.kind[k] = p.hint_kind
                br.cost[k] = min(br.cost[k], p.kind_cost[p.hint_kind])
        elif lab == "keep":
            br.kind[k] = "keep"
            br.cost[k] = max(br.cost[k], p.kind_cost["attach"])
