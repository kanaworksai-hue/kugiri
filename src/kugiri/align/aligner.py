"""omniASR CTC 对齐器：音频 + 文字 → 字级 units；没有文字时贪心解码出文字（识别模式）。"""
from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from ..userdict import UserDict
from . import assets
from .ctc import Emissions, emissions, greedy, min_frames, viterbi
from .model import FRAME_S, OmniCTC, read_vocab
from .targets import Targets, build_targets, is_speech_char

BLANK = 0


@dataclass
class Timing:
    """CTC 时间修正（秒）。CTC 只在一个字「最像」的那一两帧发尖峰：句中的字首尾相接没问题，
    停顿前最后一个字的终点普遍偏早（拖长的尾音），停顿后第一个字的起点略晚。

    - ``start_shift``：起点整体平移（负数 = 提前）。
    - ``fill``：句中（没有停顿）的字终点往后延最多这么多秒，不超过下一个字的起点。
    - ``vad``：停顿两侧用音量包络修正（``refine.py``）；参数 ``ratio`` / ``hang`` / ``max_tail`` / ``max_head`` /
      ``min_gap`` 见那里。``min_tail``：停顿前的字终点至少比 CTC 终点晚这么多。
    默认值在 TEDxJP-10K 人工时间上调出来（一半 talk 调参、另一半验证）。
    """
    start_shift: float = -0.04
    fill: float = 0.2
    vad: bool = True
    ratio: float = 0.1
    hang: float = 0.05
    max_tail: float = 0.4
    max_head: float = 0.0
    min_gap: float = 0.1
    min_tail: float = 0.0


@dataclass
class AlignResult:
    units: list[dict]                   # {"cs", "ce", "start", "end", "conf"[, "reading"]}，cs/ce 是 text 的下标
    text: str
    stats: dict = field(default_factory=dict)


class Aligner:
    def __init__(self, device: str = "auto", model_path: str | None = None, vocab_path: str | None = None,
                 win: float = 30.0, ctx: float = 4.0, threads: int | None = None, quiet: bool = False):
        import torch

        if threads:
            torch.set_num_threads(threads)
        if device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.win, self.ctx = win, ctx
        self.quiet = quiet
        # 进度回调 (阶段, 0–1)：网页 / MCP 用；None 时 quiet=False 才往 stderr 打
        self.progress: Callable[[str, float], None] | None = None
        t = time.time()
        self._model_path = model_path or assets.fetch("300M", quiet)     # 先下载好，模型本身用到时才加载
        self._model = None
        self.vocab = read_vocab(vocab_path or assets.fetch("vocab", quiet))
        self.ids = {p: i for i, p in enumerate(self.vocab) if p and i != BLANK}
        self.load_s = time.time() - t

    @property
    def model(self):
        """第一次用到时才加载（识别模式先跑 Qwen3-ASR，两个模型不同时占内存）。"""
        if self._model is None:
            t = time.time()
            self._model = OmniCTC.load(self._model_path, "300M", self.device)
            self.load_s += time.time() - t
        return self._model

    # ------------------------------------------------------------------ 模型
    def in_vocab(self, c: str) -> bool:
        return c in self.ids

    def forward(self, chunk: np.ndarray) -> np.ndarray:
        import torch

        with torch.inference_mode():
            w = torch.from_numpy(np.ascontiguousarray(chunk, dtype=np.float32)).to(self.device)
            w = torch.nn.functional.layer_norm(w, w.shape).unsqueeze(0)
            lp = torch.log_softmax(self.model(w)[0].float(), -1)
            out = lp.cpu().numpy()
        if self.device == "mps":
            torch.mps.empty_cache()
        return out

    def emissions(self, audio: np.ndarray, ids: list[int], stage: str = "align") -> Emissions:
        if self.progress is not None:
            cb = self.progress
            prog = lambda x: cb(stage, x)      # noqa: E731
        else:
            prog = None if self.quiet else _progress("Aligning" if stage == "align" else "Transcribing")
        return emissions(audio, self.forward, ids, BLANK, self.win, self.ctx, prog)

    # ------------------------------------------------------------------ 对齐
    def align(self, audio: np.ndarray, text: str, *, offset: float = 0.0, udict: UserDict | None = None,
              spell: str = "auto", timing: Timing | None = None, em: Emissions | None = None) -> AlignResult:
        """把 text 整段对齐到 audio（不用切段）。offset 加到所有时间上（audio 是文件里的一段时）。"""
        _check_len(audio)
        tg = build_targets(text, self.in_vocab, udict, spell)
        if not tg.chars:
            raise ValueError("the script has nothing to align (only symbols, or characters the model does not know and that have no reading)")
        ids = [self.ids[c] for c in tg.chars]
        t0 = time.time()
        if em is None:
            em = self.emissions(audio, ids)
        t1 = time.time()
        col = {x: k for k, x in enumerate(em.cols)}
        tok = [col[i] for i in ids]
        if len(tok) and em.logp.shape[0] < min_frames(tok):
            raise ValueError(f"the audio is too short ({len(audio) / 16000:.1f} s) for a script of {len(tok)} characters")
        spans = viterbi(em.logp, tok, 0)
        t2 = time.time()
        peak = [float(np.exp(em.logp[f0:f1, k].max())) for (f0, f1), k in zip(spans, tok)]
        units = _units(tg, spans, peak, offset, timing or Timing(), audio)
        stats = {"n_speech": tg.n_speech, "n_aligned": tg.n_speech - tg.n_dropped, "oov": tg.oov,
                 "emit_s": round(t1 - t0, 2), "viterbi_s": round(t2 - t1, 2), "frames": int(em.logp.shape[0])}
        return AlignResult(units, text, stats)

    # ------------------------------------------------------------------ 识别（没有台本）
    def transcribe(self, audio: np.ndarray, *, offset: float = 0.0, timing: Timing | None = None,
                   pause: float = 0.6) -> AlignResult:
        """omniASR 贪心解码。没有标点：停顿 ≥ pause 秒的地方插一个「。」（作为断句提示，不占时间）。"""
        _check_len(audio)
        t0 = time.time()
        em = self.emissions(audio, [], "transcribe")
        toks = [(self.vocab[x], f0, f1, p) for x, f0, f1, p in greedy(em, BLANK)]
        text, spans, peak, prev_end = "", [], [], None
        for ch, f0, f1, p in toks:
            if not is_speech_char(ch):
                continue
            if prev_end is not None and (f0 - prev_end) * FRAME_S >= pause:
                text += "。"
            spans.append((f0, f1))
            peak.append(p)
            text += ch
            prev_end = f1
        idx = [k for k, c in enumerate(text) if c != "。"]
        tg = Targets("".join(text[k] for k in idx), [(k, k + 1) for k in idx], n_speech=len(idx))
        units = _units(tg, spans, peak, offset, timing or Timing(), audio)
        return AlignResult(units, text, {"n_speech": len(idx), "emit_s": round(time.time() - t0, 2),
                                         "frames": int(em.logp.shape[0])})


def _check_len(audio: np.ndarray) -> None:
    if len(audio) < 1600:
        raise ValueError(f"the audio is too short ({len(audio) / 16000:.2f} s); it needs at least 0.1 s")


def _units(tg: Targets, spans: list[tuple[int, int]], peak: list[float], offset: float, tm: Timing,
           audio: np.ndarray | None = None) -> list[dict]:
    """token 帧区间 → 原文区间的 unit（同一区间的读音 token 合并成一个 unit），再做终点补偿。"""
    units: list[dict] = []
    confs: list[list[float]] = []
    for (cs, ce), (f0, f1), p in zip(tg.spans, spans, peak):
        if units and units[-1]["cs"] == cs and units[-1]["ce"] == ce:
            units[-1]["_f1"] = f1
            confs[-1].append(p)
            continue
        units.append({"cs": cs, "ce": ce, "_f0": f0, "_f1": f1})
        confs.append([p])
    for u, c in zip(units, confs):
        u["start"] = max(offset, offset + u.pop("_f0") * FRAME_S + tm.start_shift)
        u["end"] = offset + u.pop("_f1") * FRAME_S
        u["conf"] = round(float(np.mean(c)), 3)
        r = tg.readings.get((u["cs"], u["ce"]))
        if r:
            u["reading"] = r
    for k in range(1, len(units)):          # 平移后也不能早于上一个字
        units[k]["start"] = max(units[k]["start"], units[k - 1]["start"] + FRAME_S / 2)
    raw_end = [u["end"] for u in units]
    pause = [k + 1 == len(units) or units[k + 1]["start"] - u["end"] >= tm.min_gap for k, u in enumerate(units)]
    if tm.vad and audio is not None:
        from .refine import refine
        for k, u in enumerate(units):
            if pause[k]:
                u["end"] = u["end"] + tm.min_tail
        refine(units, audio, offset, ratio=tm.ratio, hang=tm.hang, max_tail=tm.max_tail, max_head=tm.max_head,
               min_gap=tm.min_gap)
    for k, u in enumerate(units):
        if tm.vad and audio is not None and pause[k]:
            lim = u["end"]
        else:
            lim = raw_end[k] + tm.fill
        if k + 1 < len(units):
            lim = min(lim, units[k + 1]["start"])
        u["end"] = max(lim, u["start"] + FRAME_S / 2)
    for u in units:
        u["start"] = round(u["start"], 3)
        u["end"] = max(round(u["end"], 3), round(u["start"] + 0.01, 3))
    return units


def _progress(label: str) -> Callable[[float], None]:
    t0 = time.time()
    tty = sys.stderr.isatty()

    def f(x: float) -> None:
        if not tty and x < 1:
            return
        print(f"\r{label} {x * 100:3.0f}%  {time.time() - t0:.0f}s", end="" if x < 1 else "\n", file=sys.stderr)
    return f
