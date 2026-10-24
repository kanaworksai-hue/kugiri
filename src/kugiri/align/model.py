"""omniASR CTC（Meta Omnilingual ASR，wav2vec2 编码器 + CTC 头）的纯 PyTorch 实现。

不依赖 fairseq2：模块名和官方 checkpoint（``omniASR-CTC-*-v2.pt``）的 state_dict 键一一对应，直接加载。
结构 = wav2vec2 large（卷积特征 + layer norm、pre-LN Transformer、卷积位置编码），帧移 20ms。
代码和权重都是 Apache-2.0。字表是 sentencepiece 模型文件里的 piece 表（字符级，blank = 0 = ``<s>``）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

SR = 16000
FRAME_S = 0.02   # 320 个采样点一帧


@dataclass(frozen=True)
class Arch:
    dim: int = 1024
    layers: int = 24
    heads: int = 16
    ffn: int = 4096
    vocab: int = 10288


ARCHS = {"300M": Arch()}

_CONVS = [(10, 5)] + [(3, 2)] * 4 + [(2, 2)] * 2


class _ConvLayer(nn.Module):
    def __init__(self, cin: int, k: int, s: int):
        super().__init__()
        self.conv = nn.Conv1d(cin, 512, k, s)
        self.layer_norm = nn.LayerNorm(512)

    def forward(self, x):
        x = self.conv(x)
        return F.gelu(self.layer_norm(x.transpose(1, 2)).transpose(1, 2))


class _FeatureExtractor(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(*[_ConvLayer(1 if i == 0 else 512, k, s) for i, (k, s) in enumerate(_CONVS)])


class _PosConv(nn.Module):
    """权重归一化（weight_norm, dim=2）的分组卷积，参数名 weight_g / weight_v 同官方。"""

    def __init__(self, dim: int):
        super().__init__()
        self.weight_g = nn.Parameter(torch.ones(1, 1, 128))
        self.weight_v = nn.Parameter(torch.zeros(dim, dim // 16, 128))
        self.bias = nn.Parameter(torch.zeros(dim))

    def forward(self, x):
        v = self.weight_v
        w = self.weight_g * v / v.norm(dim=(0, 1), keepdim=True)
        return F.conv1d(x, w, self.bias, padding=64, groups=16)


class _PosEncoder(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.conv = _PosConv(dim)

    def forward(self, x):          # x: (N, T, E)
        e = self.conv(x.transpose(1, 2))[:, :, :-1]
        return x + F.gelu(e).transpose(1, 2)


class _Frontend(nn.Module):
    def __init__(self, a: Arch):
        super().__init__()
        self.feature_extractor = _FeatureExtractor()
        self.post_extract_layer_norm = nn.LayerNorm(512)
        self.model_dim_proj = nn.Linear(512, a.dim)
        self.pos_encoder = _PosEncoder(a.dim)

    def forward(self, wav):        # wav: (N, S)
        x = self.feature_extractor.layers(wav.unsqueeze(1)).transpose(1, 2)
        return self.pos_encoder(self.model_dim_proj(self.post_extract_layer_norm(x)))


class _Attention(nn.Module):
    def __init__(self, a: Arch):
        super().__init__()
        self.h = a.heads
        self.q_proj, self.k_proj, self.v_proj, self.output_proj = (nn.Linear(a.dim, a.dim) for _ in range(4))

    def forward(self, x):
        n, t, e = x.shape

        def split(y):
            return y.view(n, t, self.h, e // self.h).transpose(1, 2)

        y = F.scaled_dot_product_attention(split(self.q_proj(x)), split(self.k_proj(x)), split(self.v_proj(x)))
        return self.output_proj(y.transpose(1, 2).reshape(n, t, e))


class _FFN(nn.Module):
    def __init__(self, a: Arch):
        super().__init__()
        self.inner_proj = nn.Linear(a.dim, a.ffn)
        self.output_proj = nn.Linear(a.ffn, a.dim)

    def forward(self, x):
        return self.output_proj(F.gelu(self.inner_proj(x)))


class _Layer(nn.Module):
    def __init__(self, a: Arch):
        super().__init__()
        self.self_attn_layer_norm = nn.LayerNorm(a.dim)
        self.self_attn = _Attention(a)
        self.ffn_layer_norm = nn.LayerNorm(a.dim)
        self.ffn = _FFN(a)

    def forward(self, x):
        x = x + self.self_attn(self.self_attn_layer_norm(x))
        return x + self.ffn(self.ffn_layer_norm(x))


class _Encoder(nn.Module):
    def __init__(self, a: Arch):
        super().__init__()
        self.layers = nn.ModuleList(_Layer(a) for _ in range(a.layers))
        self.layer_norm = nn.LayerNorm(a.dim)

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return self.layer_norm(x)


class OmniCTC(nn.Module):
    def __init__(self, a: Arch = Arch()):
        super().__init__()
        self.encoder_frontend = _Frontend(a)
        self.encoder = _Encoder(a)
        self.final_proj = nn.Linear(a.dim, a.vocab)

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        """wav: (N, S) 16kHz 采样（已做整段 layer norm）→ logits (N, T, V)。"""
        return self.final_proj(self.encoder(self.encoder_frontend(wav)))

    @classmethod
    def load(cls, path: str | Path, arch: str = "300M", device: str = "cpu") -> "OmniCTC":
        sd = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
        sd = sd.get("model", sd)
        m = cls(ARCHS[arch])
        m.load_state_dict(sd, strict=True)
        return m.eval().to(device)


def read_vocab(path: str | Path) -> list[str]:
    """读 sentencepiece 模型文件（protobuf）里的 piece 表；控制符 / unk 位置返回空串。

    只解析 ModelProto.pieces（字段 1：piece=1, score=2, type=3），免得依赖 sentencepiece 包。
    """
    def varint(b: bytes, i: int) -> tuple[int, int]:
        r = s = 0
        while True:
            x = b[i]
            i += 1
            r |= (x & 0x7F) << s
            s += 7
            if x < 0x80:
                return r, i

    def fields(b: bytes):
        i = 0
        while i < len(b):
            key, i = varint(b, i)
            f, w = key >> 3, key & 7
            if w == 0:
                v, i = varint(b, i)
            elif w == 1:
                v, i = b[i:i + 8], i + 8
            elif w == 5:
                v, i = b[i:i + 4], i + 4
            elif w == 2:
                n, i = varint(b, i)
                v, i = b[i:i + n], i + n
            else:
                raise ValueError(f"unknown protobuf wire type {w}")
            yield f, v

    out = []
    for f, v in fields(Path(path).read_bytes()):
        if f == 1:
            d = dict(fields(v))
            out.append(d[1].decode("utf-8") if d.get(3, 1) == 1 else "")
    return out
