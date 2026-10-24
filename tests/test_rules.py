"""规则不变量：禁则、数字单位、用户词典、行宽、时间规则——对所有黄金输入 × 所有预设检查。"""
from __future__ import annotations

from pathlib import Path

import pytest

from kugiri import formats
from kugiri.analysis import is_violation
from kugiri.reflow import PRESETS, Params, preset, reflow, retime, wrap
from kugiri.textutil import NO_HEAD, NO_TAIL, line_width
from kugiri.timeline import Cue, Document
from kugiri.userdict import UserDict

IN = Path(__file__).parent / "golden" / "input"
INPUTS = ["kinsoku.srt", "numbers.srt", "userdict.srt", "spoken.vtt", "stress.vtt",
          "longline.srt", "fragments.srt", "wordspaced.sjis.srt", "youtube_auto.vtt", "whisperx.json", "highlight.srt",
          "conventions.srt", "aegisub.ass"]
UDICT = UserDict.load(IN / "userdict.tsv")


def _runs():
    for name in INPUTS:
        for pre in PRESETS:
            for mode in ("resegment", "wrap"):
                yield name, pre, mode


@pytest.mark.parametrize("name,pre,mode", list(_runs()))
def test_invariants(name, pre, mode):
    p = preset(pre)
    doc = formats.read(IN / name)
    out = reflow(doc, p, mode=mode, udict=UDICT)
    assert out.cues
    for c in out.cues:
        assert "".join(c.lines) == c.text
        assert 1 <= len(c.lines) <= p.max_lines
        for ln in c.lines:
            s = ln.strip()
            assert s, c.lines
            assert s[0] not in NO_HEAD, f"行首禁则：{c.lines}"
            assert s[-1] not in NO_TAIL, f"行尾禁则：{c.lines}"
            assert line_width(ln) <= p.max_width, f"超宽：{ln}"
        pos = 0
        for ln in c.lines[:-1]:
            pos += len(ln)
            assert not is_violation(c.text, pos), f"断开了数字/禁则：{c.lines}"
        for a, b, e in UDICT.find(c.text):
            if e.nosplit:
                assert not any(a < k < b for k in _cuts(c)), f"拆开了词典词 {e.surface}：{c.lines}"
    # cue 边界本身也不能违反禁则 / 拆开词典词和数字
    for x, y in zip(out.cues, out.cues[1:]):
        joined = x.text + y.text
        assert not is_violation(joined, len(x.text)), f"cue 边界违反禁则：{x.text}|{y.text}"
        for a, b, e in UDICT.find(joined):
            assert not (e.nosplit and a < len(x.text) < b), f"cue 边界拆开了 {e.surface}"
    if mode == "resegment":
        _check_timing(out.cues, p)
    else:
        src = sorted(doc.cues, key=lambda c: c.start)
        assert out.cues[0].start == src[0].start and out.cues[-1].end == src[-1].end


def _cuts(c: Cue) -> list[int]:
    return [b for _, b in c.line_spans()[:-1]]


def _check_timing(cues, p: Params):
    f = p.fps
    for c, n in zip(cues, cues[1:] + [None]):
        assert c.end > c.start
        assert abs(c.start * f - round(c.start * f)) < 1e-6, "没有吸附到整帧"
        assert abs(c.end * f - round(c.end * f)) < 1e-6
        assert c.end - c.start <= p.max_dur + 1e-6
        if n is not None:
            gap = round((n.start - c.end) * f)
            assert gap >= p.gap_frames, f"间隔 {gap} 帧"
            assert not (p.gap_frames < gap < round(p.merge_gap * f)), f"{gap} 帧的空隙应该合并"
            if gap > p.gap_frames:
                assert c.end - c.start >= p.min_dur - 1e-6


# ---------------------------------------------------------------- 具体规则
@pytest.mark.parametrize("text,unbroken", [
    ("2026年10月20日の午後3時30分から第3回の勉強会を開催します", ["2026年10月20日", "3時30分", "第3回"]),
    ("参加費は1,500円で定員は先着40名になりますのでお早めに", ["1,500円", "40名"]),
    ("ファイルは1本あたり約2.5GBで、4K・60fpsで撮影しています", ["2.5GB", "60fps"]),
    ("これは「とても大事な話」なので最後まで聞いてくださいね", ["「とても大事な話」"]),
])
def test_protected_spans(text, unbroken):
    for w in (8.0, 10.0, 13.0):
        lines = wrap(text, Params(max_width=w))
        for u in unbroken:
            assert any(u in ln for ln in lines), (w, lines)


def test_small_kana_and_long_vowel_never_start_line():
    text = "ちょっとコーヒーを買ってきますねすぐ戻りますからちょっと待っててください"
    for w in (5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0):
        for ln in wrap(text, Params(max_width=w, max_lines=3)):
            assert ln[0] not in NO_HEAD, (w, ln)


def test_userdict_nosplit():
    text = "東京AI映像合同会社の新しいツールを紹介します"
    with_dict = wrap(text, Params(max_width=8.0), udict=UDICT)
    assert any("東京AI映像合同会社" in ln for ln in with_dict), with_dict


def test_one_sentence_per_cue():
    doc = Document([Cue(0.0, 6.0, "今日はいい天気ですね。散歩に行きましょう。")])
    out = reflow(doc, preset("youtube"))
    assert [c.text for c in out.cues] == ["今日はいい天気ですね。", "散歩に行きましょう。"]


def test_retime_rules():
    p = Params(fps=24.0, min_dur=0.5, max_dur=7.0, gap_frames=2, merge_gap=0.5)
    cues = [Cue(1.0, 1.1, "a"), Cue(1.4, 2.0, "b"),     # 太短 → 延长，但要给下一条留 2 帧
            Cue(2.2, 10.0, "c"),                         # 2.0→2.2 空隙 < 0.5 秒 → 合并到 2 帧；太长 → 截到 7 秒
            Cue(30.0, 31.0, "d")]
    retime(cues, p)
    fr = [(round(c.start * 24), round(c.end * 24)) for c in cues]
    assert fr[0] == (24, round(1.4 * 24) - 2)
    assert fr[1][1] == round(2.2 * 24) - 2
    assert fr[2] == (round(2.2 * 24), round(2.2 * 24) + 168)
    assert fr[3] == (720, 744)


# ---------------------------------------------------------------- LLM 盲评发现的问题
def _kind_at(text: str, after: str) -> str:
    from kugiri.analysis import analyze
    return analyze(text).kind[text.index(after) + len(after)]


@pytest.mark.parametrize("text,after,kind", [
    ("どうも来ました霊夢です", "来ました", "final"),        # ました + 名词：Sudachi 把た标成连体形
    ("ありましたありました", "ありました", "final"),        # 后面是非自立动词 ある 也是新句
    ("そんなやつえっ本当", "やつ", "final"),               # 感叹词开头是新的话
    ("書いたことがある", "書いた", "bunsetsu"),            # 形式名词前不算句末
    ("皆さんこんにちは本当に", "皆さん", "bunsetsu"),       # こんにちは / ありがとう 不算插话式感叹词
    ("本当にありがとう", "本当に", "particle"),
    ("生かしていけたら", "生かして", "aux"),
])
def test_kinds_from_blind_eval(text, after, kind):
    assert _kind_at(text, after) == kind


def test_pause_does_not_split_aux():
    # 「生かして|いけたら」中间有 0.6 秒犹豫停顿，也不能在补助动词前切 cue
    text = "絵の中で生かしていけたらいいなっていう思いで蝶々は描いて取り入れてます"
    k = text.index("いけたら")
    units, t = [], 0.0
    for i, ch in enumerate(text):
        t += 0.6 if i == k else 0.0
        units.append({"cs": i, "ce": i + 1, "start": t, "end": t + 0.12})
        t += 0.12
    from kugiri.reflow import segment
    cuts = [c.ce for c in segment(text, units, preset("youtube"))[:-1]]
    assert k not in cuts


def test_retime_linger():
    p = Params(fps=30.0, cps=4.0, pref_dur=1.0)
    cues = [Cue(1.0, 1.3, "はい"), Cue(5.0, 5.2, "これは長めの字幕です"), Cue(6.0, 7.0, "次")]
    retime(cues, p)
    assert cues[0].end == pytest.approx(2.0)           # 0.3 秒的「はい」至少留 1 秒（后面有空）
    assert cues[1].end == pytest.approx(6.0 - 2 / 30)  # 要 2.5 秒才读得完，但不能压到下一条


def test_break_before_conjunction_after_polite_end():
    # 〜ました|でも、〜でした|だけど：Sudachi 把 でも / だけど 切成附属语，句末之后也要能断
    from kugiri.analysis import analyze
    for text, k in (("雨が降りましたでも楽しかった", 7), ("雨でしただけど寒かった", 4)):
        assert analyze(text).kind[k] == "final", text


def test_retime_min_duration_borrows_from_next():
    from kugiri.reflow import preset, retime
    p = preset("youtube")
    cues = [Cue(1.0, 1.2, "あっ！"), Cue(1.25, 4.0, "なんか手に入れた")]
    retime(cues, p)
    assert cues[0].end - cues[0].start >= p.min_dur - 1e-6 and cues[1].start > cues[0].end
