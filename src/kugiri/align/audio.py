"""读音频 → 16kHz 单声道 float32。

WAV（PCM / 浮点 / EXTENSIBLE）自己解析直接读（采样率不是 16k 时用 torch 做 sinc 重采样）；其他格式（mp3 / m4a / mp4 …）
交给 ffmpeg（PATH 里的 ``ffmpeg``，或环境变量 ``KUGIRI_FFMPEG``）。ffmpeg 只作为外部命令调用，不是 Python 依赖。
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

SR = 16000


def load_audio(path: str | Path) -> np.ndarray:
    path = Path(path)
    if not path.exists():
        raise OSError(f"audio file not found: {path}")
    if path.suffix.lower() == ".wav":
        try:
            return _read_wav(path)
        except ValueError:
            pass  # 压缩编码的 WAV（ADPCM 等）交给 ffmpeg
    return _ffmpeg(path)


def _read_wav(path: Path) -> np.ndarray:
    """自己解析 RIFF：PCM 8/16/24/32 位、浮点 32/64 位、WAVE_FORMAT_EXTENSIBLE（Python 3.11 的 wave 不支持）。"""
    raw = path.read_bytes()
    if len(raw) < 12 or raw[:4] not in (b"RIFF", b"RF64") or raw[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    fmt = data = None
    i = 12
    while i + 8 <= len(raw):
        cid, size = raw[i:i + 4], int.from_bytes(raw[i + 4:i + 8], "little")
        body = raw[i + 8:i + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            data = body if size != 0xFFFFFFFF else raw[i + 8:]
            break
        i += 8 + size + (size & 1)
    if fmt is None or data is None or len(fmt) < 16:
        raise ValueError("the WAV file has no fmt / data chunk")
    tag, ch, sr = int.from_bytes(fmt[0:2], "little"), int.from_bytes(fmt[2:4], "little"), int.from_bytes(fmt[4:8], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if tag == 0xFFFE and len(fmt) >= 26:          # EXTENSIBLE：真正的格式在 SubFormat GUID 的前 2 字节
        tag = int.from_bytes(fmt[24:26], "little")
    width = bits // 8
    if ch < 1 or width < 1 or sr < 1:
        raise ValueError("broken WAV header")
    data = data[:len(data) - len(data) % (width * ch)]
    if tag == 3 and width in (4, 8):
        x = np.frombuffer(data, "<f4" if width == 4 else "<f8").astype(np.float32)
    elif tag == 1 and width == 2:
        x = np.frombuffer(data, "<i2").astype(np.float32) / 32768.0
    elif tag == 1 and width == 4:
        x = (np.frombuffer(data, "<i4").astype(np.float64) / 2147483648.0).astype(np.float32)
    elif tag == 1 and width == 3:
        b = np.frombuffer(data, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float32) / 8388608.0
    elif tag == 1 and width == 1:
        x = (np.frombuffer(data, np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV format (format {tag}, {bits} bit)")
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return resample(x, sr, SR) if sr != SR else np.ascontiguousarray(x)


def _ffmpeg(path: Path) -> np.ndarray:
    exe = os.environ.get("KUGIRI_FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise OSError(f"reading {path.suffix} needs ffmpeg (install it and put it on PATH, or set KUGIRI_FFMPEG), or convert to WAV first")
    r = subprocess.run([exe, "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", "-"], capture_output=True)
    if r.returncode != 0:
        lines = [x for x in r.stderr.decode(errors="replace").replace(str(path), path.name).splitlines() if x.strip()]
        last = re.sub(r"^\[[^\]]*\]\s*", "", lines[-1]) if lines else f"exit code {r.returncode}"
        raise OSError(f"could not read audio from {path.name}: is it a video or audio file? (ffmpeg: {last[:160]})")
    return np.frombuffer(r.stdout, "<f4").copy()


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """带限 sinc 插值重采样（Kaiser 窗，同 torchaudio 的 sinc_interp_kaiser 思路）。"""
    import torch

    g = math.gcd(sr_in, sr_out)
    up, down = sr_out // g, sr_in // g
    width, rolloff, beta = 16, 0.945, 14.769656459379492
    base = min(up, down) * rolloff
    w = math.ceil(width * down / base)
    idx = torch.arange(-w, w + down, dtype=torch.float64)[None, :] / down
    t = (-torch.arange(up, dtype=torch.float64)[:, None] / up + idx) * base
    t = t.clamp(-width, width)
    win = torch.special.i0(beta * torch.sqrt(1 - (t / width) ** 2)) / torch.special.i0(torch.tensor(beta))
    t = t * math.pi
    k = torch.where(t == 0, torch.ones_like(t), torch.sin(t) / t) * win * base / down
    k = k.float()[:, None, :]                                   # (up, 1, K)
    sig = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))[None, None, :]
    sig = torch.nn.functional.pad(sig, (w, w + down))
    y = torch.nn.functional.conv1d(sig, k, stride=down)        # (1, up, L)
    y = y.transpose(1, 2).reshape(-1)
    n_out = math.ceil(sr_out * len(x) / sr_in)
    return y[:n_out].numpy().copy()
