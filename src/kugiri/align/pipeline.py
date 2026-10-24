"""音频 (+ 台本) → kugiri-timeline 文档（每行台本一条 cue，带字级 units），之后交给 ``reflow`` 断行。"""
from __future__ import annotations

import re
import time
from collections.abc import Callable

import numpy as np

from ..textutil import is_half, normalize
from ..timeline import Cue, Document, Unit
from ..userdict import UserDict
from . import quality
from .aligner import Aligner, Timing
from .model import SR
from .targets import is_speech_char

# 「名前：」/「>> 名前」。名字里不能有数字（10:30）、冒号后面不能是 URL（https://…）
_SPEAKER = re.compile(r"^\s*(?:>>\s*(?P<a>[^\s:：0-9０-９]{1,16})\s*[:：]?|"
                      r"(?P<b>[^\s:：「」（）()0-9０-９]{1,12})\s*[:：](?!\s*(?:[A-Za-z][A-Za-z0-9+.-]*:)?//))\s*(?P<t>.+)$")


def read_script(text: str, speakers: bool = False) -> list[tuple[str, str | None]]:
    """台本：一行一段，空行忽略。``speakers=True`` 时识别行首的「名前：」或「>> 名前」。"""
    out = []
    for line in text.splitlines():
        line = normalize(line)
        if not line:
            continue
        spk = None
        if speakers and (m := _SPEAKER.match(line)):
            spk, line = m.group("a") or m.group("b"), m.group("t").strip()
        out.append((line, spk))
    return out


def align_script(al: Aligner, audio: np.ndarray, lines: list[tuple[str, str | None]], *,
                 udict: UserDict | None = None, spell: str = "auto", timing: Timing | None = None,
                 mode: str = "script") -> Document:
    """整个文件一次对齐（不切段），再按台本行切成 cue。没有发音字符的行（只有符号）丢掉。"""
    t0 = time.time()
    texts = [t for t, _ in lines]
    for k in range(len(texts) - 1):      # 英数字接英数字时补空格，免得 reflow 拼块时粘成一个词
        a, b = texts[k], texts[k + 1]
        if a and b and is_half(a[-1]) and a[-1].isalnum() and is_half(b[0]) and b[0].isalnum():
            texts[k] = a + " "
    full, offs = "", []
    for t in texts:
        offs.append(len(full))
        full += t + "\n"
    res = al.align(audio, full, udict=udict, spell=spell, timing=timing)
    cues: list[Cue] = []
    lost: list[tuple[int, int]] = []          # 有发音字符但一个字都没对上的行（字表外、读音拼不出）
    k = 0
    for i, ((t, spk), off) in enumerate(zip(zip(texts, [s for _, s in lines]), offs)):
        us = []
        while k < len(res.units) and res.units[k]["cs"] < off + len(t):
            u = res.units[k]
            us.append(Unit(u["cs"] - off, u["ce"] - off, u["start"], u["end"], u.get("reading"), u.get("conf")))
            k += 1
        if us:
            cues.append(Cue(us[0].start, us[-1].end, t, None, us, [], spk))
        elif any(is_speech_char(c) for c in t):
            lost.append((len(cues), i))
            cues.append(Cue(0.0, 0.0, t, None, [], [], spk, ["unaligned"]))
        # 只有符号的行（「……」「♪」）不出字幕
    regions = quality.check(res.units)
    for r in regions:
        r["text"] = full[r["cs"]:r["ce"]].replace("\n", " ")
    dur = len(audio) / SR
    for j, i in lost:             # 没对上的行：放在前后两条之间，标 unaligned
        prev = next((c.end for c in reversed(cues[:j]) if c.units), 0.0)
        nxt = next((c.start for c in cues[j + 1:] if c.units), dur)
        c = cues[j]
        c.start, c.end = prev, max(prev + 0.5, min(nxt, prev + 3.0))
        regions.append({"start": c.start, "end": c.end, "cs": offs[i], "ce": offs[i] + len(c.text),
                        "reason": "unaligned", "text": c.text})
    regions.sort(key=lambda r: r["start"])
    meta = _meta(al, audio, res.stats, time.time() - t0, regions, mode)
    doc = Document(cues, "ja", None, meta)
    quality.flag_cues(doc.cues, regions)
    return doc


SENT_END = re.compile(r"(?<=[。！？!?])(?![。！？!?」』）)\]])")    # 「そうです。」と / え？！ 不拆开


def recognize(al: Aligner, audio: np.ndarray, *, model: str = "qwen3-1.7b", batch: int = 16, max_len: float = 20.0,
              recognizer=None, progress: Callable[[float], None] | None = None) -> tuple[list[tuple[str, None]], dict]:
    """只识别、不对齐：Qwen3-ASR（``asr.MODELS``，带标点）→ 一句一行的台本。
    返回 ``(lines, info)``；``info`` 带 ``asr``（模型、块数、耗时、回退块数）和 ``fallback``（回退块的质检区间）。
    ``recognizer``：已经加载好的 ``asr.QwenASR``（常驻 / 批量处理多个文件时复用；这时用完不释放）。"""
    from . import asr
    t0 = time.time()
    chunks = asr.split_chunks(audio, max_len=max_len)
    if not chunks:
        raise ValueError("no speech was recognised (silence or only music?)")
    q = recognizer or asr.QwenASR(model, al.device, quiet=al.quiet)
    try:
        q.run(audio, chunks, batch=batch, progress=progress)
    finally:
        if recognizer is None:
            q.close()
    asr_s = time.time() - t0
    fallback = []
    for c in chunks:              # 像幻觉的块：改用 omniASR 贪心（CTC 不会凭空编字）
        if c.flags:
            seg = audio[c.a:c.b]
            c.text = al.transcribe(seg).text if len(seg) >= 1600 else ""
            fallback.append(c)
    text = asr.join_chunks([c.text for c in chunks])
    lines = read_script("\n".join(SENT_END.split(text)))
    if not lines or not any(is_speech_char(ch) for t, _ in lines for ch in t):
        raise ValueError("no speech was recognised (silence or only music?)")
    info = {"asr": {"model": q.name, "repo": asr.MODELS[q.name], "chunks": len(chunks), "asr_s": round(asr_s, 2),
                    "fallback": len(fallback)},
            "fallback": [{"start": round(c.a / SR, 3), "end": round(c.b / SR, 3), "reason": "asr_fallback:" + c.flags[0],
                          "text": c.text} for c in fallback]}
    return lines, info


def transcribe(al: Aligner, audio: np.ndarray, *, model: str = "qwen3-1.7b", timing: Timing | None = None,
               udict: UserDict | None = None, batch: int = 16, max_len: float = 20.0, recognizer=None,
               on_script: Callable[[list[tuple[str, str | None]]], None] | None = None,
               progress: Callable[[float], None] | None = None) -> Document:
    """识别模式。``model``：Qwen3-ASR 出文字（``recognize``）→ 当台本整段 CTC 对齐；
    ``omni`` 只用 omniASR 贪心（不用额外依赖，没有标点、错字多）。
    ``on_script``：识别出的台本（一句一行）在对齐之前交给它（``--save-script``：对齐失败也能拿到识别稿）。
    ``progress``：识别阶段的进度（0–1）；对齐阶段的进度走 ``al.progress``。"""
    if model == "omni":
        doc = transcribe_ctc(al, audio, timing=timing)
        if on_script:
            on_script([(c.text, None) for c in doc.cues])
        return doc
    t0 = time.time()
    lines, rinfo = recognize(al, audio, model=model, batch=batch, max_len=max_len, recognizer=recognizer,
                             progress=progress)
    if on_script:
        on_script(lines)
    doc = align_script(al, audio, lines, udict=udict, timing=timing, mode="asr")
    info = doc.meta["align"]
    info["asr"] = rinfo["asr"]
    info["wall_s"] = round(time.time() - t0, 2)
    info["rtf"] = round(info["wall_s"] / max(len(audio) / SR, 1e-9), 4)
    extra = rinfo["fallback"]
    if extra:
        info["warnings"] = sorted(info["warnings"] + extra, key=lambda r: r["start"])
        quality.flag_cues(doc.cues, extra)
    return doc


def transcribe_ctc(al: Aligner, audio: np.ndarray, *, timing: Timing | None = None, pause: float = 0.6) -> Document:
    """识别模式：omniASR 贪心解码出文字（没有标点；长停顿处插「。」当断句提示），字级时间直接来自 CTC。"""
    t0 = time.time()
    res = al.transcribe(audio, timing=timing, pause=pause)
    if not res.units:
        raise ValueError("no speech was recognised (silence or only music?)")
    cues: list[Cue] = []
    pos = 0
    for sent in re.split(r"(?<=。)", res.text):
        if not sent:
            continue
        a, b = pos, pos + len(sent)
        pos = b
        us = [Unit(u["cs"] - a, u["ce"] - a, u["start"], u["end"], None, u.get("conf"))
              for u in res.units if a <= u["cs"] < b]
        if us:
            cues.append(Cue(us[0].start, us[-1].end, sent, None, us))
    regions = quality.check(res.units)
    for r in regions:
        r["text"] = res.text[r["cs"]:r["ce"]]
    doc = Document(cues, "ja", None, _meta(al, audio, res.stats, time.time() - t0, regions, "asr"))
    quality.flag_cues(doc.cues, regions)
    return doc


def _meta(al: Aligner, audio: np.ndarray, stats: dict, wall: float, regions: list[dict], mode: str) -> dict:
    dur = len(audio) / SR
    return {"align": {"model": "omniASR_CTC_300M_v2", "mode": mode, "device": al.device,
                      "audio_s": round(dur, 2), "wall_s": round(wall, 2), "rtf": round(wall / max(dur, 1e-9), 4),
                      **{k: v for k, v in stats.items() if k in ("n_speech", "n_aligned", "oov")},
                      "warnings": [{**r, "start": round(r["start"], 3), "end": round(r["end"], 3)} for r in regions]}}
