"""Whisper 系识别工具的 JSON（只读）：WhisperX、openai-whisper、faster-whisper / stable-ts 的导出、whisper.cpp。

- ``{"segments": [{"start", "end", "text", "words": [{"word", "start", "end", ...}], "speaker"?}]}``：
  WhisperX / openai-whisper（``--word_timestamps True``）/ stable-ts。一个 segment 一条 cue，words 当字级时间；
  日语 WhisperX 一个字一个 word，数字和符号常没有时间（贴到相邻的字）。没有 words 时用 segment 的文字和时间。
- ``{"transcription": [{"offsets": {"from", "to"}, "text"}]}``：whisper.cpp（``-oj``，毫秒）。
"""
from __future__ import annotations

import math

from ..timeline import Document
from .common import timed_cue


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def is_whisper(d) -> bool:
    if isinstance(d, list):          # segments 列表直接存成文件（faster-whisper 自己 dump 时常见）
        return bool(d) and all(isinstance(s, dict) and "start" in s and ("text" in s or "words" in s) for s in d)
    return isinstance(d, dict) and (isinstance(d.get("segments"), list) or isinstance(d.get("transcription"), list))


def parse(d: dict | list) -> Document:
    if isinstance(d, list):
        d = {"segments": d}
    cues = []
    if isinstance(d.get("segments"), list):
        for seg in d["segments"]:
            if not isinstance(seg, dict):
                continue
            s, e = _num(seg.get("start")), _num(seg.get("end"))
            words = [w for w in seg.get("words") or [] if isinstance(w, dict) and (w.get("word") or w.get("text"))]
            if words:
                pieces = [(_num(w.get("start")), _num(w.get("end")), w.get("word") or w.get("text")) for w in words]
                times = [t for p in pieces for t in p[:2] if t is not None]
                s = s if s is not None else min(times, default=None)
                e = e if e is not None else max(times, default=None)
            else:
                pieces = [(s, e, seg.get("text") or "")]
            if s is None or e is None:
                continue
            c = timed_cue(s, max(s, e), pieces, seg.get("speaker"))
            if c:
                cues.append(c)
    else:
        for seg in d["transcription"]:
            off = seg.get("offsets") or {}
            s, e = _num(off.get("from")), _num(off.get("to"))
            if s is None or e is None:
                continue
            c = timed_cue(s / 1000, max(s, e) / 1000, [(s / 1000, max(s, e) / 1000, seg.get("text") or "")])
            if c:
                cues.append(c)
    cues.sort(key=lambda c: c.start)
    return Document(cues)
