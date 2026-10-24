"""用音量包络修正停顿两侧的边界。

CTC 只在一个字最像的那一两帧发尖峰：句中字与字首尾相接没关系，但停顿前的最后一个字（拖长的尾音、ね〜）
终点会早 0.3–1 秒，停顿后的第一个字起点也常晚几十毫秒。这里只动停顿两侧：

- 终点：从 CTC 终点往后，一直延到音量连续 ``hang`` 秒低于阈值为止（最多 ``max_tail`` 秒，不超过下一个字）。
- 起点：从 CTC 起点往前，退到音量开始低于阈值的地方（最多 ``max_head`` 秒，不早于上一个字的终点）。

阈值按局部（前后 15 秒）的底噪和语音音量算：floor + ratio × (speech − floor)（dB）。
"""
from __future__ import annotations

import numpy as np

SR = 16000
HOP = 0.01          # 包络 10ms 一帧
WIN = 0.025


def envelope(audio: np.ndarray) -> np.ndarray:
    """每 10ms 一帧的 RMS（dB）。"""
    hop, win = int(HOP * SR), int(WIN * SR)
    n = max(1, 1 + (len(audio) - win) // hop) if len(audio) >= win else 1
    x = np.asarray(audio, dtype=np.float32)
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    sq = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    idx = np.arange(n) * hop
    e = (sq[idx + win] - sq[idx]) / win
    return 10 * np.log10(e + 1e-10)


def threshold(env: np.ndarray, ratio: float, ctx: float = 15.0, block: float = 5.0) -> np.ndarray:
    """每帧的阈值（dB）：每 block 秒一组，用前后 ctx 秒的 10% / 95% 分位数当底噪 / 语音音量。"""
    n = len(env)
    b, c = max(1, int(block / HOP)), int(ctx / HOP)
    out = np.empty(n, dtype=np.float64)
    for a in range(0, n, b):
        seg = env[max(0, a - c):min(n, a + b + c)]
        lo, hi = np.percentile(seg, 10), np.percentile(seg, 95)
        out[a:a + b] = lo + ratio * max(hi - lo, 0.0)
    return out


def refine(units: list[dict], audio: np.ndarray, offset: float, *, ratio: float = 0.2, hang: float = 0.05,
           max_tail: float = 1.0, max_head: float = 0.15, min_gap: float = 0.1) -> None:
    """就地修改 units 的 start / end（秒，文件绝对时间；audio 从 offset 秒开始）。

    只处理「和下一个字之间有 ≥ min_gap 秒空隙」的终点、「和上一个字之间有 ≥ min_gap 秒空隙」的起点。
    """
    if not units:
        return
    env = envelope(audio)
    thr = threshold(env, ratio)
    loud = env > thr
    n = len(env)
    hang_f = max(1, int(round(hang / HOP)))

    def fr(t: float) -> int:
        return min(n - 1, max(0, int(round((t - offset) / HOP))))

    for k, u in enumerate(units):
        nxt = units[k + 1]["start"] if k + 1 < len(units) else None
        if nxt is None or nxt - u["end"] >= min_gap:
            lim = u["end"] + max_tail if nxt is None else min(u["end"] + max_tail, nxt - 0.02)
            f, stop, quiet = fr(u["end"]), fr(lim), 0
            last = f
            while f < stop:
                if loud[f]:
                    quiet, last = 0, f + 1
                else:
                    quiet += 1
                    if quiet >= hang_f:
                        break
                f += 1
            u["end"] = max(u["end"], min(lim, offset + last * HOP))
        prv = units[k - 1]["end"] if k else None
        if prv is None or u["start"] - prv >= min_gap:
            lim = u["start"] - max_head if prv is None else max(u["start"] - max_head, prv + 0.02)
            f, stop = fr(u["start"]) - 1, fr(lim)
            while f >= stop and loud[f]:
                f -= 1
            u["start"] = min(u["start"], max(lim, offset + (f + 1) * HOP))
