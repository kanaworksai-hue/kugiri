"""kugiri align：CTC Viterbi、对齐串（读音替换）、时间修正、质检、音频读取、台本切 cue、CLI。

模型相关的测试只在本地有模型文件时跑（KUGIRI_MODEL_DIR 里有 omniASR-CTC-300M-v2.pt），其余用假的发射概率。
"""
from __future__ import annotations

import itertools
import json
import math
import os
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("torch")

from kugiri.align import quality  # noqa: E402
from kugiri.align.aligner import AlignResult, Timing, _units  # noqa: E402
from kugiri.align.audio import load_audio, resample  # noqa: E402
from kugiri.align.ctc import Emissions, emissions, greedy, viterbi  # noqa: E402
from kugiri.align.pipeline import align_script, read_script  # noqa: E402
from kugiri.align.refine import refine  # noqa: E402
from kugiri.align.targets import Targets, build_targets, is_speech_char  # noqa: E402
from kugiri.timeline import Document  # noqa: E402
from kugiri.userdict import UserDict  # noqa: E402


# ---------------------------------------------------------------- Viterbi
def _brute(lp, tok):
    """枚举所有合法 CTC 路径，返回最优路径的每 token 帧区间。"""
    T, L = lp.shape[0], len(tok)
    best, arg = -math.inf, None
    for lab in itertools.product(range(2 * L + 1), repeat=T):
        if lab[0] > 1 or lab[-1] < 2 * L - 1:
            continue
        ok = True
        for a, b in zip(lab, lab[1:]):
            d = b - a
            if d < 0 or d > 2 or (d == 2 and (b % 2 == 0 or tok[b // 2] == tok[b // 2 - 1])):
                ok = False
                break
        if not ok:
            continue
        sc = sum(lp[t, 0 if s % 2 == 0 else tok[s // 2]] for t, s in enumerate(lab))
        if sc > best:
            best, arg = sc, lab
    spans = [[-1, -1] for _ in tok]
    for t, s in enumerate(arg):
        if s % 2:
            j = s // 2
            spans[j][0] = t if spans[j][0] < 0 else spans[j][0]
            spans[j][1] = t + 1
    return [tuple(x) for x in spans]


@pytest.mark.parametrize("seed", range(6))
def test_viterbi_matches_brute_force(seed):
    rng = np.random.default_rng(seed)
    T, K = 7, 3
    lp = np.log(rng.dirichlet(np.ones(K), size=T)).astype(np.float32)
    tok = [1, 2, 2] if seed % 2 else [2, 1]
    assert viterbi(lp, tok, 0, ckpt=2) == _brute(lp, tok)


def test_viterbi_checkpoint_independent():
    rng = np.random.default_rng(1)
    lp = np.log(rng.dirichlet(np.ones(20) * 0.3, size=900)).astype(np.float32)
    tok = list(rng.integers(1, 20, size=250))
    a = viterbi(lp, tok, 0, ckpt=7)
    assert a == viterbi(lp, tok, 0, ckpt=10_000)
    assert all(f0 < f1 for f0, f1 in a) and all(x[1] <= y[0] for x, y in zip(a, a[1:]))


def test_viterbi_too_short():
    lp = np.zeros((2, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        viterbi(lp, [1, 1], 0)      # 相同 token 之间要隔 blank：至少 3 帧


def test_emissions_windowing_keeps_columns_and_length():
    calls = []

    def fwd(x):
        calls.append(len(x))
        T = int(math.ceil(len(x) / 320))
        out = np.full((T, 6), -5.0, dtype=np.float32)
        out[:, 3] = -0.1
        return out

    audio = np.zeros(16000 * 100, dtype=np.float32)     # 100 秒 → 4 窗
    em = emissions(audio, fwd, [3, 5], win=30, ctx=4)
    assert em.cols == [0, 3, 5] and em.logp.shape == (5000, 3)
    assert len(calls) == 4 and max(calls) <= 16000 * 38
    assert (em.argmax == 3).all()


def test_greedy_merges_repeats():
    am = np.array([0, 4, 4, 0, 4, 7, 7, 0])
    em = Emissions(np.zeros((8, 1), np.float32), [0], am, np.zeros(8, np.float32))
    assert [(x, a, b) for x, a, b, _ in greedy(em)] == [(4, 1, 3), (4, 4, 5), (7, 5, 7)]


# ---------------------------------------------------------------- 对齐串
def _vocab(c):
    return c not in "儚"


def test_targets_plain_chars_skip_punct():
    t = build_targets("東京、です。", _vocab)
    assert t.chars == "東京です" and t.spans == [(0, 1), (1, 2), (3, 4), (4, 5)]


def test_targets_readings_for_digits_latin_oov():
    t = build_targets("2026年にAIで儚い", _vocab)
    assert t.readings[(0, 4)] == "ニセンニジュウロク"
    assert t.readings[(6, 8)] == "エーアイ"          # 拉丁字母读成片假名
    assert "儚" in t.oov and any(r.startswith("ハカナ") for (a, b), r in t.readings.items() if a == 9)
    assert t.chars == "にせんにじゅうろく年にエーアイではかない"
    assert all(sp == (0, 4) for sp in t.spans[:9])
    t2 = build_targets("2026年", _vocab, spell="oov")
    assert t2.chars == "2026年" and not t2.readings


def test_targets_spoken_symbols_and_decimals():
    t = build_targets("100%です。1.05倍", _vocab)
    assert t.readings[(0, 3)] == "ヒャク" and t.readings[(3, 4)] == "パーセント"
    assert t.readings[(7, 11)] == "イチテンゼロゴ"
    assert t.chars == "ひゃくぱーせんとですいちてんぜろご倍"


def test_targets_userdict_reading(tmp_path):
    p = tmp_path / "d.tsv"
    p.write_text("推しの子\tオシノコ\n", encoding="utf-8")
    t = build_targets("推しの子です", _vocab, UserDict.load(p))
    assert t.readings[(0, 4)] == "オシノコ" and t.chars == "おしのこです"


def test_targets_long_text_is_chunked():
    text = "\n".join(["今日は2026年の10月です、天気がいいですね"] * 400)
    t = build_targets(text, _vocab)
    assert len(t.readings) == 800 and t.n_dropped == 0


# ---------------------------------------------------------------- 时间修正 / 质检
def _tg(n):
    return Targets("あ" * n, [(k, k + 1) for k in range(n)], n_speech=n)


def test_units_fill_and_shift_never_zero_or_backwards():
    spans = [(0, 1), (1, 2), (5, 6), (30, 31)]
    us = _units(_tg(4), spans, [0.9] * 4, 0.0, Timing(start_shift=-0.04, fill=0.2, vad=False))
    assert us[0]["start"] == 0.0 and us[0]["end"] > us[0]["start"]
    assert us[1]["end"] <= us[2]["start"]                    # 补偿不超过下一个字
    assert us[2]["end"] == pytest.approx(0.12 + 0.2)
    assert all(u["end"] > u["start"] for u in us)
    assert all(a["start"] < b["start"] for a, b in zip(us, us[1:]))


def test_refine_extends_tail_into_voiced_audio():
    sr = 16000
    t = np.arange(sr * 3) / sr
    audio = 0.001 * np.random.default_rng(0).standard_normal(len(t))
    audio[int(0.5 * sr):int(1.5 * sr)] += 0.3 * np.sin(2 * np.pi * 220 * t[int(0.5 * sr):int(1.5 * sr)])
    units = [{"cs": 0, "ce": 1, "start": 0.5, "end": 1.0}, {"cs": 1, "ce": 2, "start": 2.5, "end": 2.6}]
    refine(units, audio.astype(np.float32), 0.0, ratio=0.2, max_tail=0.8)
    assert units[0]["end"] == pytest.approx(1.5, abs=0.04)   # 延到声音结束，不进静音
    units = [{"cs": 0, "ce": 1, "start": 0.5, "end": 1.0}, {"cs": 1, "ce": 2, "start": 1.2, "end": 1.4}]
    refine(units, audio.astype(np.float32), 0.0, ratio=0.2, max_tail=0.8)
    assert units[0]["end"] <= 1.2 - 0.02 + 1e-9               # 不超过下一个字


def test_quality_flags_low_confidence_and_squeeze():
    good = [{"cs": k, "ce": k + 1, "start": k * 0.15, "end": k * 0.15 + 0.1, "conf": 0.9} for k in range(30)]
    assert quality.check(good) == []
    bad = [dict(u) for u in good]
    for u in bad[10:20]:
        u["conf"] = 0.01
    regs = quality.check(bad)
    assert len(regs) == 1 and "low_confidence" in regs[0]["reason"] and regs[0]["cs"] <= 10 and regs[0]["ce"] >= 20
    sq = [dict(u) for u in good]
    for k, u in enumerate(sq[10:20]):
        u["start"], u["end"] = 1.5 + k * 0.02, 1.5 + k * 0.02 + 0.02
    for u in sq[20:]:
        u["start"] += 1.0
        u["end"] += 1.0
    assert any("squeezed" in r["reason"] for r in quality.check(sq))


# ---------------------------------------------------------------- 音频
def _write_wav(path, x, sr, ch=1):
    data = (np.clip(x, -1, 1) * 32767).astype("<i2")
    if ch == 2:
        data = np.stack([data, data], 1).reshape(-1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def test_load_wav_resamples_and_downmixes(tmp_path):
    sr = 44100
    t = np.arange(sr) / sr
    _write_wav(tmp_path / "a.wav", 0.5 * np.sin(2 * np.pi * 440 * t), sr, ch=2)
    x = load_audio(tmp_path / "a.wav")
    assert x.dtype == np.float32 and abs(len(x) - 16000) <= 1
    spec = np.abs(np.fft.rfft(x[2000:14000]))
    assert abs(np.argmax(spec) * 16000 / 12000 - 440) < 3
    assert abs(np.sqrt(np.mean(x[2000:14000] ** 2)) - 0.5 / math.sqrt(2)) < 0.01


@pytest.mark.parametrize("fmt", ["s24", "f32", "ext"])
def test_load_wav_variants(tmp_path, fmt):
    """24 位、浮点、WAVE_FORMAT_EXTENSIBLE（Python 3.11 的 wave 读不了）都自己解析。"""
    import struct
    x = (0.25 * np.sin(np.arange(16000) / 16000 * 2 * np.pi * 300)).astype(np.float32)
    if fmt == "s24":
        v = np.round(x * 8388607).astype(np.int32)
        data = np.stack([v & 255, (v >> 8) & 255, (v >> 16) & 255], 1).astype(np.uint8).tobytes()
        tag, bits, fmt_body = 1, 24, None
    elif fmt == "f32":
        data, tag, bits, fmt_body = x.astype("<f4").tobytes(), 3, 32, None
    else:
        data, tag, bits = (x * 32767).astype("<i2").tobytes(), 0xFFFE, 16
        fmt_body = struct.pack("<HHIIHHHHI", tag, 1, 16000, 32000, 2, 16, 22, 16, 4) + \
            struct.pack("<H", 1) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    if fmt_body is None:
        fmt_body = struct.pack("<HHIIHH", tag, 1, 16000, 16000 * bits // 8, bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt_body)) + fmt_body + b"data" + struct.pack("<I", len(data)) + data
    (tmp_path / "a.wav").write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    y = load_audio(tmp_path / "a.wav")
    assert len(y) == 16000 and np.abs(y - x).max() < 1e-3


def test_resample_identity_length():
    x = np.random.default_rng(0).standard_normal(48000).astype(np.float32)
    assert len(resample(x, 48000, 16000)) == 16000


def test_load_audio_missing(tmp_path):
    with pytest.raises(OSError):
        load_audio(tmp_path / "nope.wav")


# ---------------------------------------------------------------- 台本 → cue
def test_read_script_speakers_and_blank_lines():
    s = "田中：こんにちは。\n\n>> 佐藤 どうも\n午前10:30に集合\nURL: https://x.jp\n"
    got = read_script(s, speakers=True)
    assert got[:2] == [("こんにちは。", "田中"), ("どうも", "佐藤")]
    assert got[2:] == [("午前10:30に集合", None), ("URL: https://x.jp", None)]
    assert read_script(s)[0] == ("田中：こんにちは。", None)


class _FakeAligner:
    device = "cpu"

    def align(self, audio, text, **kw):
        units, t = [], 0.0
        for k, c in enumerate(text):
            if is_speech_char(c):
                units.append({"cs": k, "ce": k + 1, "start": round(t, 3), "end": round(t + 0.1, 3), "conf": 0.9})
                t += 0.15
            elif c == "\n":
                t += 1.0
        return AlignResult(units, text, {"n_speech": len(units), "n_aligned": len(units), "oov": ""})


def test_align_script_keeps_unalignable_lines():
    class Partial(_FakeAligner):
        def align(self, audio, text, **kw):
            r = super().align(audio, text)
            r.units = [u for u in r.units if text[u["cs"]] not in "ゐゑ"]
            return r

    lines = [("今日は", None), ("ゐゑ", None), ("晴れ", None)]
    doc = align_script(Partial(), np.zeros(16000 * 10, np.float32), lines)
    assert [c.text for c in doc.cues] == ["今日は", "ゐゑ", "晴れ"]
    mid = doc.cues[1]
    assert "unaligned" in mid.flags and doc.cues[0].end <= mid.start < doc.cues[2].start
    assert any(w["reason"] == "unaligned" for w in doc.meta["align"]["warnings"])


def test_quality_empty_and_errors():
    assert quality.check([]) == []
    from kugiri.align.aligner import _check_len
    with pytest.raises(ValueError):
        _check_len(np.zeros(100, np.float32))


def test_align_script_splits_lines_into_cues():
    lines = [("今日は晴れ。", None), ("……", None), ("abc", "A"), ("def", "A")]
    doc = align_script(_FakeAligner(), np.zeros(16000 * 10, np.float32), lines)
    assert [c.text for c in doc.cues] == ["今日は晴れ。", "abc ", "def"]   # 只有符号的行丢掉，英数字之间补空格
    assert doc.cues[0].units[0].cs == 0 and doc.cues[1].units[0].start > doc.cues[0].end
    assert doc.cues[1].speaker == "A"
    assert doc.meta["align"]["warnings"] == []
    back = Document.from_dict(json.loads(doc.dumps()))
    assert back.meta == doc.meta and back.cues[1].units[0].conf == 0.9


# ---------------------------------------------------------------- 真模型（本地有模型时）
MODEL_DIR = Path(os.environ.get("KUGIRI_MODEL_DIR", Path.home() / ".cache/kugiri/models"))
HAS_MODEL = (MODEL_DIR / "omniASR-CTC-300M-v2.pt").exists()


@pytest.mark.skipif(not HAS_MODEL, reason="没有本地模型文件")
def test_model_vocab_has_japanese():
    from kugiri.align.model import read_vocab
    v = read_vocab(MODEL_DIR / "omniASR_tokenizer_written_v2.model")
    assert len(v) == 10288 and v[0] == "" and {"東", "京", "あ", "ア", "ー"} <= set(v)


@pytest.mark.skipif(not HAS_MODEL, reason="没有本地模型文件")
def test_cli_align_end_to_end(tmp_path, capsys):
    """无声音频 + 台本：能跑完、输出合法、时间单调、整段都被标成「可能对不上」。"""
    from kugiri.cli import main
    _write_wav(tmp_path / "s.wav", np.zeros(16000 * 6), 16000)
    (tmp_path / "s.txt").write_text("今日はいい天気ですね。\n散歩に行きましょう。\n", encoding="utf-8")
    out = tmp_path / "o.json"
    assert main(["align", str(tmp_path / "s.wav"), "--script", str(tmp_path / "s.txt"), "--device", "cpu",
                 "-q", "-o", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["meta"]["align"]["warnings"] and all("low_confidence" in c["flags"] for c in d["cues"])
    us = [u for c in d["cues"] for u in c["units"]]
    assert all(u["end"] > u["start"] for u in us)
