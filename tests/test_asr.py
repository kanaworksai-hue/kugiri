"""识别模式（Qwen3-ASR + CTC 对齐）：切块、重复幻觉检测、回退到 omniASR、句末切 cue。不需要模型文件。"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("torch")

from kugiri.align import asr, pipeline  # noqa: E402
from kugiri.align.aligner import AlignResult  # noqa: E402
from kugiri.align.targets import is_speech_char  # noqa: E402

SR = 16000


def _speechy(pattern: list[tuple[float, bool]], seed: int = 0) -> np.ndarray:
    """(秒数, 有没有声音) 拼成的测试音频：有声段是噪声，无声段是很小的底噪。"""
    rng = np.random.default_rng(seed)
    parts = [rng.normal(0, 0.2 if loud else 0.0005, int(s * SR)).astype(np.float32) for s, loud in pattern]
    return np.concatenate(parts)


def test_split_chunks_cuts_in_pauses_and_respects_max_len():
    pat = [(6, True), (0.6, False), (7, True), (0.5, False), (9, True), (0.8, False), (4, True)]
    audio = _speechy(pat)
    chunks = asr.split_chunks(audio, max_len=15, min_len=3)
    assert chunks[0].a == 0 and chunks[-1].b == len(audio)
    assert all(c.dur <= 15.01 for c in chunks)
    assert all(a.b == b.a for a, b in zip(chunks, chunks[1:]))       # 连续不重叠
    pauses = [(6, 6.6), (13.6, 14.1), (23.1, 23.9)]
    for c in chunks[:-1]:                                            # 每个切点都在某个停顿里
        t = c.b / SR
        assert any(p0 <= t <= p1 for p0, p1 in pauses), t


def test_split_chunks_drops_silence_and_keeps_short_audio():
    assert asr.split_chunks(np.zeros(SR * 30, np.float32)) == []
    short = _speechy([(2, True)])
    (c,) = asr.split_chunks(short)
    assert (c.a, c.b) == (0, len(short))


def test_find_repeat_and_suspicious():
    assert asr.find_repeat("今日はいい天気ですね。散歩に行きましょう。") is None
    assert asr.find_repeat("ありがとうございます。" * 2) is None                       # 两次是正常的
    r = asr.find_repeat("はい" + "そうですね、" * 8 + "おわり")
    assert r is not None and r[1] == len("そうですね、") and r[2] == 8
    assert asr.suspicious("あ" * 40, 10.0, False) == "repetition"
    assert asr.suspicious("今日はいい天気ですね", 1.0, False) is None
    assert asr.suspicious("今日はいい天気ですね散歩に行きましょう" * 3, 2.0, False) == "too_fast"
    assert asr.suspicious("普通", 5.0, True) == "token_limit"


def test_join_chunks_drops_period_before_particle_or_auxiliary():
    assert asr.join_chunks(["一応定員6人にしてる。", "ですけども、まだ余裕あります。", "ね。", "次の話です。"]) == \
        "一応定員6人にしてるですけども、まだ余裕ありますね。次の話です。"
    assert asr.join_chunks(["終わりました。", "まあ、これは", ""]) == "終わりました。まあ、これは"
    assert asr.join_chunks(["冒険家として生きて。", "いるんです。"]) == "冒険家として生きているんです。"
    assert asr.join_chunks(["本を読んで。", "いました。"]) == "本を読んでいました。"
    assert asr.join_chunks(["本を読む。", "いい本です。"]) == "本を読む。いい本です。"
    assert asr.join_chunks(["余裕ありますからね。", "はそんなこともやってます。"]) == \
        "余裕ありますからね。はそんなこともやってます。"


class _FakeAligner:
    device, quiet = "cpu", True

    def align(self, audio, text, **kw):
        """发音字符均匀摊满整段音频。"""
        units, t = [], 0.0
        step = len(audio) / SR / sum(map(is_speech_char, text))
        for k, c in enumerate(text):
            if is_speech_char(c):
                units.append({"cs": k, "ce": k + 1, "start": round(t, 3), "end": round(t + step / 2, 3), "conf": 0.9})
                t += step
        return AlignResult(units, text, {"n_speech": len(units), "n_aligned": len(units), "oov": ""})

    def transcribe(self, audio, **kw):
        return AlignResult([], "ふつうのこえ", {})


def test_transcribe_splits_sentences_and_falls_back_on_hallucination(monkeypatch):
    outputs = ["今日はいい天気ですね。散歩に", "行きましょう！", "あ" * 60]

    class FakeQwen:
        def __init__(self, name, device, quiet=False):
            assert name == "qwen3-1.7b"
            self.name = name

        def run(self, audio, chunks, batch=8, progress=None):
            for c, t in zip(chunks, outputs):
                c.text = t
                why = asr.suspicious(t, c.dur, False)
                if why:
                    c.flags.append(why)

        def close(self):
            pass

    monkeypatch.setattr(asr, "QwenASR", FakeQwen)
    audio = _speechy([(8, True), (0.8, False), (8, True), (0.8, False), (8, True)])
    doc = pipeline.transcribe(_FakeAligner(), audio, max_len=10)
    assert [c.text for c in doc.cues] == ["今日はいい天気ですね。", "散歩に行きましょう！", "ふつうのこえ"]
    info = doc.meta["align"]
    assert info["mode"] == "asr" and info["asr"]["fallback"] == 1 and info["asr"]["chunks"] == 3
    (w,) = [w for w in info["warnings"] if w["reason"].startswith("asr_fallback")]
    assert w["reason"] == "asr_fallback:repetition" and w["start"] > 16
    assert "low_confidence" in doc.cues[-1].flags


def test_transcribe_rejects_silence():
    with pytest.raises(ValueError):
        pipeline.transcribe(_FakeAligner(), np.zeros(SR * 5, np.float32))


def test_split_chunks_silent_tail_is_not_glued_to_last_chunk():
    audio = _speechy([(8, True), (60, False)])
    chunks = asr.split_chunks(audio, max_len=20)
    assert len(chunks) == 1 and chunks[0].dur <= 20.01


def test_sentence_split_keeps_closing_brackets_and_stacked_marks():
    lines = pipeline.read_script("\n".join(pipeline.SENT_END.split("「そうです。」と言った。え？！本当？")))
    assert [t for t, _ in lines] == ["「そうです。」と言った。", "え？！", "本当？"]


def test_row_limit_stops_each_row_at_its_own_limit():
    import torch
    stop = asr._RowLimit(3, torch.tensor([2, 5]))
    assert stop(torch.zeros(2, 4, dtype=torch.long), None).tolist() == [False, False]
    assert stop(torch.zeros(2, 5, dtype=torch.long), None).tolist() == [True, False]


def _cached_processor():
    os = pytest.importorskip("os")
    pytest.importorskip("transformers")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoProcessor
    try:
        return AutoProcessor.from_pretrained(asr.MODELS["qwen3-0.6b"])
    except Exception:
        pytest.skip("本地没有 Qwen3-ASR 的 processor 文件")


def test_run_flags_repetition_through_real_tokenizer(monkeypatch):
    """模型输出用真的 tokenizer 解码（processor.decode 会把 20 次以上的重复折叠掉，幻觉就漏了）。"""
    import torch
    proc = _cached_processor()
    long = "".join(chr(0x4E00 + 37 * i) for i in range(150))         # 不重复、但超过 token 上限
    outs = ["今日はいい天気ですね。", "あ" * 80, long]

    class FakeModel:
        def generate(self, input_ids, max_new_tokens, stopping_criteria, **kw):
            rows = [proc.tokenizer.encode(t, add_special_tokens=False) + [proc.tokenizer.pad_token_id] for t in outs]
            new = max(len(r) for r in rows)
            for t in range(1, new + 1):                       # 按停止条件逐行截断，后面补 pad
                done = stopping_criteria[0](torch.zeros(len(rows), input_ids.shape[1] + t), None).tolist()
                for r, d in zip(rows, done):
                    if d and len(r) > t:
                        del r[t:]
            rows = [r + [proc.tokenizer.pad_token_id] * (new - len(r)) for r in rows]
            return torch.cat([input_ids, torch.tensor(rows)], 1)

    q = object.__new__(asr.QwenASR)
    q.torch, q.proc, q.model, q.device, q.quiet = torch, proc, FakeModel(), "cpu", True
    q.eos = {proc.tokenizer.pad_token_id}
    monkeypatch.setattr(q, "_embed", lambda inp, eb: None)
    audio = _speechy([(5, True), (0.8, False), (5, True), (0.8, False), (5, True)])
    chunks = asr.split_chunks(audio, max_len=6, min_len=3)
    assert len(chunks) == 3
    monkeypatch.setattr(asr, "token_limit", lambda dur: 100)
    q.run(audio, chunks, batch=3)
    ok, rep, lim = sorted(chunks, key=lambda c: outs.index(next(o for o in outs if o.startswith(c.text[:3]))))
    assert ok.text == outs[0] and ok.flags == []
    assert rep.flags == ["repetition"] and rep.text == outs[1]          # 没被折叠
    assert lim.flags == ["token_limit"] and long.startswith(lim.text) and len(lim.text) < len(long)
