"""CTC 发射概率（分窗）+ 省内存的全局 Viterbi 强制对齐。

- 发射：音频按 ``win`` 秒分窗、两侧各加 ``ctx`` 秒上下文送模型，只保留窗中间的帧。log_softmax 在全字表上算，
  但只留下台本用到的几列（30 分钟音频全字表要 3.7GB，留几千列只要几百 MB）。
- Viterbi：对整个文件一次对齐，文本不用切。回溯指针不存整张 T×S 表，而是每 ``CKPT`` 帧存一份 alpha，
  回溯时逐段重算（时间约 2 倍，内存从 T×S 字节降到 (T/CKPT + CKPT)×S）。结果和全表 Viterbi 完全相同。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .model import FRAME_S, SR

CKPT = 512


@dataclass
class Emissions:
    logp: np.ndarray        # [T, K] float32：所选列的 log 概率（第 0 列是 blank）
    cols: list[int]         # 每列对应的模型 token id
    argmax: np.ndarray      # [T] 每帧全字表 argmax（识别模式 / 诊断用）
    maxlp: np.ndarray       # [T] 每帧 argmax 的 log 概率


def emissions(audio: np.ndarray, forward: Callable[[np.ndarray], np.ndarray], ids: list[int], blank: int = 0,
              win: float = 30.0, ctx: float = 4.0, progress: Callable[[float], None] | None = None) -> Emissions:
    """forward(audio_chunk) -> 全字表 log 概率 [T', V]（torch 或 numpy 都行，这里转成 numpy）。"""
    cols = [blank] + sorted(set(ids) - {blank})
    col_idx = np.asarray(cols)
    total = max(1, int(np.ceil(len(audio) / SR / FRAME_S)))
    parts, am, mx = [], [], []
    step = int(win * SR)
    c = int(ctx * SR)
    n = len(audio)
    starts = [0] if n <= (win + 2 * ctx) * SR else list(range(0, n, step))
    for k, a in enumerate(starts):
        if len(starts) == 1:
            a0, b0, b = 0, n, n
        else:
            b = min(n, a + step)
            a0, b0 = max(0, a - c), min(n, b + c)
        lp = forward(audio[a0:b0])
        fa = int(round((a - a0) / SR / FRAME_S))
        fb = fa + int(round((b - a) / SR / FRAME_S))
        lp = _fit(lp, fb)[fa:fb]
        parts.append(lp[:, col_idx].astype(np.float32))
        am.append(lp.argmax(-1).astype(np.int32))
        mx.append(lp.max(-1).astype(np.float32))
        if progress:
            progress((k + 1) / len(starts))
    return Emissions(_fit(np.concatenate(parts), total), cols, _fit(np.concatenate(am), total),
                     _fit(np.concatenate(mx), total))


def _fit(x: np.ndarray, T: int) -> np.ndarray:
    if x.shape[0] >= T:
        return x[:T]
    return np.concatenate([x, np.repeat(x[-1:], T - x.shape[0], axis=0)])


def min_frames(tok: list[int]) -> int:
    """对齐 tok 至少要几帧（相邻相同 token 之间必须隔一个 blank）。"""
    t = np.asarray(tok)
    return len(tok) + int(np.sum(t[1:] == t[:-1])) if len(tok) else 0


def viterbi(logp: np.ndarray, tok: list[int], blank: int = 0, ckpt: int = CKPT) -> list[tuple[int, int]]:
    """标准 CTC Viterbi 强制对齐。logp: [T, K]，tok 是列下标。返回每个 token 占的帧区间 [f0, f1)。"""
    T, L = logp.shape[0], len(tok)
    if L == 0:
        return []
    if T < min_frames(tok):
        raise ValueError(f"the audio is too short for the script: {T} frames < {min_frames(tok)} characters")
    S = 2 * L + 1
    ext = np.full(S, blank, dtype=np.int64)
    ext[1::2] = tok
    no_skip = np.ones(S, dtype=bool)                   # 能否从 s-2 跳过来
    no_skip[3::2] = ext[3::2] == ext[1:-2:2]
    no_skip[:3] = True
    no_skip[0::2] = True
    NEG = -1e30

    def step(alpha: np.ndarray, t: int, bp: np.ndarray | None) -> np.ndarray:
        a1 = np.empty_like(alpha)
        a1[0] = NEG
        a1[1:] = alpha[:-1]
        a2 = np.empty_like(alpha)
        a2[:2] = NEG
        a2[2:] = alpha[:-2]
        a2[no_skip] = NEG
        best = np.maximum(alpha, a1)
        nxt = np.maximum(best, a2)
        if bp is not None:
            k = (a1 > alpha).astype(np.int8)
            k[a2 > best] = 2
            bp[:] = k
        return nxt + logp[t, ext]

    alpha = np.full(S, NEG, dtype=np.float64)
    alpha[0] = logp[0, ext[0]]
    alpha[1] = logp[0, ext[1]]
    saved = {0: alpha.copy()}
    for t in range(1, T):
        alpha = step(alpha, t, None)
        if t % ckpt == 0:
            saved[t] = alpha.copy()
    s = S - 1 if S == 1 or alpha[S - 1] >= alpha[S - 2] else S - 2
    path = np.empty(T, dtype=np.int64)
    path[T - 1] = s
    # 逐段（倒序）重算回溯指针：段 [c+1, e] 从 saved[c] 出发
    for c in sorted(saved, reverse=True):
        e = min(c + ckpt, T - 1)
        if e <= c:
            continue
        bp = np.empty((e - c, S), dtype=np.int8)
        a = saved[c].copy()
        for t in range(c + 1, e + 1):
            a = step(a, t, bp[t - c - 1])
        for t in range(e, c, -1):
            path[t] = s
            s -= int(bp[t - c - 1, s])
        path[c] = s
    spans = [[-1, -1] for _ in range(L)]
    for t in np.nonzero(path % 2 == 1)[0]:
        j = path[t] // 2
        if spans[j][0] < 0:
            spans[j][0] = int(t)
        spans[j][1] = int(t) + 1
    return [(a, b) for a, b in spans]


def greedy(em: Emissions, blank: int = 0) -> list[tuple[int, int, int, float]]:
    """贪心 CTC 解码：[(token id, f0, f1, 峰值概率)]，连续相同 token 合并、去掉 blank。"""
    out: list[tuple[int, int, int, float]] = []
    prev = -1
    for t, (x, lp) in enumerate(zip(em.argmax.tolist(), em.maxlp.tolist())):
        if x != blank:
            if x == prev and out and out[-1][2] == t:
                out[-1] = (x, out[-1][1], t + 1, max(out[-1][3], float(np.exp(lp))))
            else:
                out.append((x, t, t + 1, float(np.exp(lp))))
        prev = x
    return out
