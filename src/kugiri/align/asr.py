"""识别模式（没有台本）：Qwen3-ASR 出文字（带「、。」），时间仍交给 omniASR CTC 整段对齐。

- 模型：Qwen3-ASR 1.7B / 0.6B（Apache-2.0），用 transformers 原生实现（``Qwen3ASRForConditionalGeneration``，
  transformers ≥ 5.15）。不用官方 ``qwen-asr`` 包：它依赖 GPLv3 的 soynlp。权重第一次用时从 Hugging Face 下载
  （HF 缓存，``HF_HOME`` 可改）。
- 切块：按音量包络在停顿处切成 ≤ ``max_len`` 秒的块，按长度排序后成批解码（M1 上解码受内存带宽限制，
  一次 8 块比逐块快 2–3 倍）。
- 防幻觉：每块的输出 token 数按时长封顶；输出里同一片段连续重复太多次、或字数快得不像人说话 → 这一块
  改用 omniASR 贪心（CTC 不会凭空编字），并在 warnings 里标 ``asr_fallback``。
"""
from __future__ import annotations

import gc
import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .refine import HOP, envelope

# transformers 会 import torch.distributed.elastic，macOS 上每次都打一行和用户无关的「Redirects are currently not
# supported in MacOs」。torch 的 logger 每次 setLevel，所以用 filter（filter 不会被覆盖）。
logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").addFilter(
    lambda r: "Redirects are currently not supported" not in r.getMessage())
from .targets import is_speech_char

SR = 16000
MODELS = {"qwen3-1.7b": "Qwen/Qwen3-ASR-1.7B-hf", "qwen3-0.6b": "Qwen/Qwen3-ASR-0.6B-hf"}
LABELS = {"qwen3-1.7b": "Qwen3-ASR 1.7B speech recognition model", "qwen3-0.6b": "Qwen3-ASR 0.6B speech recognition model"}
DEFAULT_MODEL = "qwen3-1.7b"

TOK_PER_S = 12.0          # 日语快语速约 8 字/秒 ≈ 6–7 token/秒；上限给到约 2 倍
TOK_EXTRA = 24
MAX_CPS = 14.0            # 每秒发音字符数超过这个就不像人话（快语速约 8–10）
REPEAT_MIN = 4            # 同一片段连续出现 ≥ 这么多次、且重复部分 ≥ REPEAT_CHARS 字 → 当成重复幻觉
REPEAT_CHARS = 16


def token_limit(dur: float) -> int:
    return int(TOK_PER_S * dur + TOK_EXTRA)


class _RowLimit:
    """generate 的停止条件：每一行按自己那块的时长封顶（不然一块陷入重复会拖着整批跑到最长那块的上限）。"""

    def __init__(self, start: int, limits):
        self.start, self.limits = start, limits

    def __call__(self, input_ids, scores, **kwargs):
        return (input_ids.shape[1] - self.start) >= self.limits


@dataclass
class Chunk:
    a: int                    # 采样点区间 [a, b)
    b: int
    text: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def dur(self) -> float:
        return (self.b - self.a) / SR


def split_chunks(audio: np.ndarray, max_len: float = 20.0, min_len: float = 5.0, quiet_win: float = 0.3,
                 silence_db: float = -55.0) -> list[Chunk]:
    """在停顿处把音频切成 ≤ max_len 秒的块：每次在 [min_len, max_len] 里找平均音量最低的 quiet_win 秒窗，
    从窗中间切开。整块音量都低于 silence_db 的（静音）丢掉。"""
    env = envelope(audio)
    n = len(env)
    w = max(1, int(quiet_win / HOP))
    sm = np.convolve(env, np.ones(w) / w, mode="same") if n >= w else env
    lo_f, hi_f = int(min_len / HOP), int(max_len / HOP)
    cuts, a = [0], 0
    while n - a > hi_f:
        seg = sm[a + lo_f:a + hi_f]
        # 同样安静时取靠后的，块长一些（argmin 取第一个，所以倒过来找）
        k = len(seg) - 1 - int(np.argmin(seg[::-1]))
        a = a + lo_f + k
        cuts.append(a)
    cuts.append(n)
    out = []
    hop = int(HOP * SR)
    for f0, f1 in zip(cuts, cuts[1:]):
        if f1 > f0 and env[f0:f1].max() > silence_db:
            # 最后一块包住包络最后一帧之后不足一帧的采样点（静音的结尾块被丢掉时不往后拉长）
            out.append(Chunk(min(len(audio), f0 * hop), len(audio) if f1 == n else min(len(audio), f1 * hop)))
    return [c for c in out if c.b - c.a >= int(0.1 * SR)]


def find_repeat(text: str, min_count: int = REPEAT_MIN, min_chars: int = REPEAT_CHARS) -> tuple[int, int, int] | None:
    """最长的「同一片段（1–30 字）连续重复」：返回 (起点, 片段长, 次数)，不够格返回 None。"""
    best = None
    for n in range(1, 31):
        for m in re.finditer(r"(.{%d})\1{%d,}" % (n, min_count - 1), text, flags=re.S):
            cnt = len(m.group(0)) // n
            if cnt * n >= min_chars and (best is None or cnt * n > best[1] * best[2]):
                best = (m.start(), n, cnt)
    return best


def suspicious(text: str, dur: float, hit_limit: bool) -> str | None:
    """这一块的识别结果像不像幻觉：返回原因或 None。"""
    if hit_limit:
        return "token_limit"
    if find_repeat(text):
        return "repetition"
    n = sum(is_speech_char(c) for c in text)
    if n > MAX_CPS * max(dur, 1.0):
        return "too_fast"
    return None


_CONT = ("助詞", "助動詞", "接尾辞")     # 句子不会从这些词开始


def _ends_with_final_particle(text: str) -> bool:
    """「〜からね」「〜ですよ」：以终助词结尾的句子是完整的，后面的「。」保留。"""
    from ..analysis import _tokenizer
    ms = [m for m in _tokenizer().tokenize(text) if m.part_of_speech()[0] not in ("補助記号", "空白")]
    return bool(ms) and ms[-1].part_of_speech()[:2] == ("助詞", "終助詞")


def join_chunks(texts: list[str]) -> str:
    """把各块的识别结果拼起来。块是在句中停顿处切开的时候，模型常在块尾补一个「。」；
    下一块如果以助词 / 助动词 / 接尾辞开头（「ですけど」「ね」「って」），或者「〜て。」后面接补助动词，
    说明句子没完，去掉这个「。」。"""
    from ..analysis import _tokenizer
    out = ""
    for t in texts:
        if out.endswith("。") and t and not _ends_with_final_particle(out[-12:-1]):
            first = next((m for m in _tokenizer().tokenize(t[:20]) if m.part_of_speech()[0] not in ("補助記号", "空白")),
                         None)
            pos = first.part_of_speech()[:2] if first is not None else ("",)
            # 「生きて。」+「いるんですけど」：て形后面接补助动词（いる・ある・しまう…）也是同一句
            if pos[0] in _CONT or (pos == ("動詞", "非自立可能") and out[-2:-1] in ("て", "で")):
                out = out[:-1]
        out += t
    return out


class QwenASR:
    def __init__(self, name: str = DEFAULT_MODEL, device: str = "mps", quiet: bool = False):
        try:
            import torch
            from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration
        except ImportError as e:
            from ..service import install_hint
            raise ValueError(f"transcription needs the [asr] extra: {install_hint('asr')}; "
                             f"or give a script / use --asr-model omni ({e})") from e
        if name not in MODELS:
            raise ValueError(f"unknown recognition model {name} (choose from {', '.join(MODELS)}, omni)")
        self.torch = torch
        self.name, self.device, self.quiet = name, device, quiet
        # MPS：M1 没有 bf16 硬件，fp16 快一倍；CUDA：模型按 bf16 训练，fp16 可能溢出，支持就用 bf16
        if device == "cpu":
            self.dtype = torch.float32
        elif device.startswith("cuda") and torch.cuda.is_bf16_supported():
            self.dtype = torch.bfloat16
        else:
            self.dtype = torch.float16
        t = time.time()
        if quiet or not sys.stderr.isatty():    # transformers 加载权重的进度条（网页 / MCP / 重定向到文件时不刷）
            from transformers.utils import logging as hf_logging
            hf_logging.disable_progress_bar()
        from .assets import fetch_hf
        path = fetch_hf(MODELS[name], LABELS[name], quiet)      # 不在缓存里时先下载（带进度、错误可读）
        try:
            self.proc = AutoProcessor.from_pretrained(path)
            self.model = Qwen3ASRForConditionalGeneration.from_pretrained(path, dtype=self.dtype)
            self.model = self.model.to(device).eval()
        except Exception as e:          # 文件坏了、内存不够等：给 CLI 一个能读的错误
            raise ValueError(f"Could not load the {LABELS[name]} ({MODELS[name]}): {type(e).__name__}: {e}") from e
        self.eos = set(self._eos_ids())
        self.load_s = time.time() - t

    def run(self, audio: np.ndarray, chunks: list[Chunk], batch: int = 16, enc_batch: int = 4,
            progress: Callable[[float], None] | None = None) -> None:
        """就地填 chunk.text；可疑的块在 flags 里记原因（调用方决定回退）。

        解码一次 ``batch`` 块（M1 上每步耗时几乎不随批量变，批量越大越快）；音频编码器的卷积激活随批量
        线性涨内存，所以编码器另外按 ``enc_batch`` 块一组算好，拼进文字 embedding 再交给 ``generate``。"""
        torch = self.torch
        if batch < 1:
            raise ValueError(f"batch must be at least 1 (got {batch})")
        order = sorted(range(len(chunks)), key=lambda i: chunks[i].dur, reverse=True)
        t0, done = time.time(), 0
        for k in range(0, len(order), batch):
            idx = order[k:k + batch]
            wav = [np.asarray(audio[chunks[i].a:chunks[i].b], dtype=np.float32) for i in idx]
            limits = [token_limit(chunks[i].dur) for i in idx]
            inp = self.proc.apply_transcription_request(audio=wav, language="ja", return_tensors="pt").to(self.device)
            start = inp["input_ids"].shape[1]
            with torch.inference_mode():
                emb = self._embed(inp, enc_batch)
                stop = _RowLimit(start, torch.tensor(limits, device=self.device))
                out = self.model.generate(input_ids=inp["input_ids"], inputs_embeds=emb,
                                          attention_mask=inp["attention_mask"], max_new_tokens=max(limits),
                                          do_sample=False, stopping_criteria=[stop])
            del emb
            gen = out[:, start:].tolist()
            for j, i in enumerate(idx):
                c = chunks[i]
                toks = gen[j]
                n_real = next((m for m, x in enumerate(toks) if x in self.eos), len(toks))
                # 不用 processor.decode：它会先把 20 次以上的重复折叠成一次，幻觉就看不出来了
                # 在上限处截断时最后一个字可能只解出半个字节（U+FFFD），去掉
                c.text = self.proc.tokenizer.decode(toks[:n_real], skip_special_tokens=True).replace("\ufffd", "").strip()
                why = suspicious(c.text, c.dur, n_real >= limits[j])
                if why:
                    c.flags.append(why)
            done += len(idx)
            if progress is not None:
                progress(done / len(chunks))
            elif not self.quiet:
                print(f"\rTranscribing {100 * done / len(chunks):3.0f}%  {time.time() - t0:.0f}s",
                      end="" if done < len(chunks) else "\n", file=sys.stderr)
            if self.device == "mps":
                torch.mps.empty_cache()

    def _embed(self, inp, enc_batch: int):
        """文字 embedding，音频占位 token 换成音频编码器的输出（同 transformers 的 forward，只是分组算编码器）。"""
        inner = self.model.model
        ids = inp["input_ids"]
        feats, fmask = inp["input_features"].to(self.dtype), inp["input_features_mask"]
        emb = inner.get_input_embeddings()(ids)
        aud = self.torch.cat([inner.get_audio_features(feats[i:i + enc_batch], fmask[i:i + enc_batch],
                                                       return_dict=True).pooler_output
                              for i in range(0, ids.shape[0], enc_batch)])
        mask = (ids == self.model.config.audio_token_id).unsqueeze(-1).expand_as(emb)
        return emb.masked_scatter(mask, aud.to(emb.dtype))

    def _eos_ids(self) -> list[int]:
        ids = self.model.generation_config.eos_token_id
        ids = ids if isinstance(ids, list) else [ids]
        pad = self.proc.tokenizer.pad_token_id      # 提前停下的行后面补的是 pad
        return [i for i in [*ids, pad] if i is not None]

    def close(self) -> None:
        """释放模型（之后还要跑 CTC 对齐，统一内存要腾出来）。"""
        del self.model
        gc.collect()
        if self.device == "mps":
            self.torch.mps.empty_cache()
        elif self.device == "cuda":
            self.torch.cuda.empty_cache()
