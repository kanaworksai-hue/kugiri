"""对齐质检：找出「台本和音频对不上」的地方。

强制对齐一定会给每个字一个时间，哪怕这段音频里根本没说这句话（台本多了一段、音频多了一段、多人重叠、噪声）。
这时 CTC 在这些字上的峰值概率很低，或者一堆字被挤在很短的时间里 / 摊在很长的时间里。

- ``units`` 每个带 ``conf``（这个字所在帧的模型峰值概率，0–1）。
- 连续 ``window`` 个字的置信度中位数 < ``low`` → 「置信度低」区间。
- 连续 ``window`` 个字的语速 > ``max_cps`` 字/秒 → 「挤压」区间（台本比音频多）。
- 单个字（不含停顿后的补偿）时长 > ``max_unit`` 秒 → 「拉长」（音频比台本多）。
重叠的区间合并，输出 ``[{"start", "end", "cs", "ce", "reason"}]``。
"""
from __future__ import annotations

import statistics

LOW = 0.05
WINDOW = 8
MAX_CPS = 25.0
MAX_UNIT = 2.0


def check(units: list[dict], *, low: float = LOW, window: int = WINDOW, max_cps: float = MAX_CPS,
          max_unit: float = MAX_UNIT) -> list[dict]:
    us = [u for u in units if u.get("conf") is not None]
    if not us:
        return []
    bad: list[tuple[int, int, str]] = []
    n = len(us)
    w = min(window, n)
    for k in range(0, max(0, n - w + 1)):
        seg = us[k:k + w]
        if statistics.median(u["conf"] for u in seg) < low:
            bad.append((k, k + w, "low_confidence"))
        dur = seg[-1]["end"] - seg[0]["start"]
        if w >= 3 and dur > 0 and (w / dur) > max_cps:
            bad.append((k, k + w, "squeezed"))
    for k, u in enumerate(us):
        if u["end"] - u["start"] > max_unit:
            bad.append((k, k + 1, "stretched"))
    bad.sort()
    merged: list[list] = []
    for a, b, why in bad:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
            if why not in merged[-1][2]:
                merged[-1][2].append(why)
        else:
            merged.append([a, b, [why]])
    return [{"start": us[a]["start"], "end": us[b - 1]["end"], "cs": us[a]["cs"], "ce": us[b - 1]["ce"],
             "reason": ",".join(why)} for a, b, why in merged]


def flag_cues(cues, regions: list[dict]) -> None:
    """时间上和问题区间重叠的 cue 打上 ``low_confidence`` 标记（就地修改）。"""
    for c in cues:
        if any(r["start"] < c.end and c.start < r["end"] for r in regions) and "low_confidence" not in c.flags:
            c.flags.append("low_confidence")
