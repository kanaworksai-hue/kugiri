"""别家工具出的字幕当 reflow 的输入：编码、滚动字幕、逐词高亮、词间空格、Whisper 系 JSON、ASS、
人工字幕的约定（两人对话、音效）。

黄金素材（tests/golden/input）都是自编文字，按各工具的输出特征做的：
- longline.srt：一条一行、很长、没有标点、行尾多余空格（Premiere 的已知 bug）、CRLF + UTF-8 BOM（Subtitle Edit 默认）
- fragments.srt：几个字一条、没有标点（CapCut / Vrew 的短 cue）
- wordspaced.sjis.srt：词间有空格、Shift_JIS 编码
- youtube_auto.vtt：YouTube 自动字幕（yt-dlp --write-auto-subs）：滚动两行、``<c>`` 词级时间、10ms 过渡 cue、[音楽]
- whisperx.json：WhisperX JSON（日语一个字一个 word、数字没有时间、speaker）
- highlight.srt：WhisperX --highlight_words（同一句按词拆成多条，当前词 ``<u>``）
- conventions.srt：两人对话（-）、（拍手）、♪～、>> 说话人
- aegisub.ass：ASS（\\N、覆盖标签、Comment 行、Name 字段）
"""
from __future__ import annotations

import json
from pathlib import Path

from kugiri import formats
from kugiri.formats.common import decode, dedupe
from kugiri.reflow import preset, reflow
from kugiri.textutil import strip_word_spaces, word_spaced
from kugiri.timeline import Cue, Document

IN = Path(__file__).parent / "golden" / "input"


def _texts(doc: Document) -> list[str]:
    return [c.text for c in doc.cues]


# ---------------------------------------------------------------- 编码
def test_decode_encodings():
    s = "字幕のテスト"
    assert decode(b"\xef\xbb\xbf" + s.encode("utf-8")) == s
    assert decode(s.encode("utf-8")) == s
    assert decode(s.encode("utf-16")) == s            # 带 BOM
    assert decode(s.encode("cp932")) == s
    srt = "1\n00:00:01,000 --> 00:00:02,000\n字幕のテスト\n"
    assert decode(srt.encode("utf-16-le")) == srt     # 没有 BOM 的 UTF-16（时间行的 ASCII 带 NUL 字节）
    assert decode(srt.encode("utf-16-be")) == srt
    assert formats.read(IN / "wordspaced.sjis.srt").cues[0].text.startswith("この 動画")


def test_bom_crlf_trailing_spaces():
    doc = formats.read(IN / "longline.srt")
    assert len(doc.cues) == 5
    assert all(not c.text.endswith(" ") and not c.text.startswith("﻿") for c in doc.cues)


# ---------------------------------------------------------------- 滚动字幕 / 逐词高亮
def test_youtube_auto_rolling_and_word_times():
    doc = formats.read(IN / "youtube_auto.vtt")
    assert _texts(doc) == ["[音楽]", "どうもこんにちは今日は週末に行った", "キャンプの話をしたいと思います",
                           "場所は山梨の湖の近くで", "夜は気温が5度まで下がりました", "でも焚き火を囲んで食べたカレーが",
                           "本当においしかったですね"]
    c = doc.cues[1]
    assert c.start == 2.0
    u = {c.text[x.cs:x.ce]: x for x in c.units}
    assert u["こんにちは"].start == 2.4 and u["今日"].start == 3.1
    assert u["どうも"].start == 2.0 and u["どうも"].end <= 2.4
    # 只给开始时间：词的结束最多按每字 0.2 秒（至少 0.3 秒），不一直拖到下一个词
    assert doc.cues[3].units[-1].end - doc.cues[3].units[-1].start <= 0.3 + 1e-9


def test_rolling_srt_without_tags():
    """yt-dlp 把自动字幕转成 SRT 后没有词级时间，只剩重复的行。"""
    raw = [(0.0, 2.0, ["", "今日は晴れ"]), (2.0, 2.01, ["今日は晴れ", ""]),
           (2.01, 4.0, ["今日は晴れ", "明日は雨"]), (4.0, 4.01, ["明日は雨", ""]),
           (4.01, 6.0, ["明日は雨", "週末は曇り"]), (6.0, 6.01, ["週末は曇り", ""]),
           (6.01, 8.0, ["週末は曇り", "来週は晴れ"])]
    assert [r[2] for r in dedupe(raw)] == [["今日は晴れ"], ["明日は雨"], ["週末は曇り"], ["来週は晴れ"]]


def test_one_accidental_repeat_is_not_rolling():
    """多行 cue 只有一条碰巧以上一条的最后一行开头：不当滚动字幕（连续的「はい」「はい」要留着）。"""
    raw = [(0.0, 1.0, ["はい"]), (1.2, 2.0, ["はい", "そうです"]), (2.5, 3.0, ["はい"]), (3.1, 3.5, ["はい"])]
    assert dedupe(raw) == raw


def test_repeated_lines_in_normal_subtitles_are_kept():
    """普通字幕里连续两条一样的话不能当滚动字幕去掉。"""
    raw = [(0.0, 1.0, ["はい"]), (1.5, 2.5, ["はい"]), (3.0, 4.0, ["そうですね", "行きましょう"]),
           (4.5, 5.5, ["行きましょう"])]
    assert dedupe(raw) == raw


def test_highlight_words_merged():
    doc = formats.read(IN / "highlight.srt")
    assert len(doc.cues) == 1
    assert doc.cues[0].text == "夕方から雨が降るらしいので傘を持っていこう"
    assert (doc.cues[0].start, doc.cues[0].end) == (1.0, 4.8)


# ---------------------------------------------------------------- 词间空格
def test_word_spaced_detection():
    spaced = ["この 動画 では 新しい ノート パソコン を", "一 週間 使って みた 感想 を お 話し し ます"]
    netflix = ["今日はいい天気ですね 散歩に行きましょう", "公園でお弁当を食べて　夕方に帰ってきました"]
    short = ["うん わかった", "えっ 何？", "そう だよ", "じゃあ 行こう", "待って まだ", "ほら 早く 早く"] * 3
    assert word_spaced(spaced)
    assert not word_spaced(netflix)
    assert not word_spaced(short)                      # Netflix 式的短对话，空格比例高但一条只有一两个
    assert strip_word_spaces("動画 を 見て も 12 時間 iPhone 15 で OK") == "動画を見ても12時間iPhone 15でOK"


def test_word_spaced_reflow_removes_spaces():
    out = reflow(formats.read(IN / "wordspaced.sjis.srt"), preset("youtube"))
    assert all(" " not in c.text for c in out.cues), _texts(out)
    assert any("12時間" in c.text for c in out.cues)


def test_netflix_spaces_kept():
    doc = Document([Cue(0.0, 3.0, "今日はいい天気ですね 散歩に行きましょう"),
                    Cue(3.5, 6.0, "公園でお弁当を食べて 夕方に帰ってきました")])
    out = reflow(doc, preset("youtube"))
    assert " " in "".join(_texts(out))


# ---------------------------------------------------------------- Whisper 系 JSON
def test_whisperx_json():
    doc = formats.read(IN / "whisperx.json")
    assert [c.speaker for c in doc.cues] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    c = doc.cues[1]
    assert "3品" in c.text
    i = c.text.index("3")
    assert all(not (u.cs <= i < u.ce) for u in c.units)      # 没有时间的字不出 unit
    assert len(c.units) == len(c.text) - 1
    out = reflow(doc, preset("youtube"))
    assert all(c.units for c in out.cues)                     # 字级时间带到输出
    assert {c.speaker for c in out.cues} == {"SPEAKER_00", "SPEAKER_01"}


def test_whisper_variants(tmp_path):
    # openai-whisper / stable-ts：英文词带前导空格，日语一个 token 几个字
    d = {"text": "", "segments": [{"start": 0.0, "end": 2.0, "text": "新しいiPhone 17を", "words": [
        {"word": "新しい", "start": 0.0, "end": 0.5, "probability": 0.9},
        {"word": "iPhone", "start": 0.5, "end": 1.0}, {"word": " 17", "start": 1.0, "end": 1.4},
        {"word": "を", "start": 1.4, "end": 1.6}]},
        {"start": 2.5, "end": 4.0, "text": "買いました"}]}          # 没有 words：用 segment 的文字和时间
    f = tmp_path / "w.json"
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    doc = formats.read(f)
    assert _texts(doc) == ["新しいiPhone 17を", "買いました"]
    assert len(doc.cues[0].units) == 4 and len(doc.cues[1].units) == 1
    # whisper.cpp -oj（毫秒）
    f.write_text(json.dumps({"transcription": [{"offsets": {"from": 1000, "to": 2500}, "text": " こんにちは"}]},
                            ensure_ascii=False), encoding="utf-8")
    doc = formats.read(f)
    assert _texts(doc) == ["こんにちは"] and doc.cues[0].start == 1.0 and doc.cues[0].end == 2.5
    assert not formats.is_timeline(f)
    # segments 列表直接存成文件；NaN 时间（json 接受 NaN）当没有时间
    f.write_text('[{"start": 0.0, "end": 1.0, "text": "あいう", "words": [{"word": "あ", "start": NaN, "end": 0.3},'
                 ' {"word": "い", "start": 0.5, "end": 0.4}, {"word": "う", "start": 0.2, "end": 0.9}]}]',
                 encoding="utf-8")
    doc = formats.read(f)
    assert _texts(doc) == ["あいう"]
    us = doc.cues[0].units
    assert len(us) == 2 and all(u.start <= u.end for u in us) and us[0].start <= us[1].start   # 乱序拉平


def test_kugiri_json_still_read(tmp_path):
    f = tmp_path / "k.json"
    f.write_text(Document([Cue(0.0, 1.0, "テスト")]).dumps(), encoding="utf-8")
    assert formats.is_timeline(f) and _texts(formats.read(f)) == ["テスト"]


# ---------------------------------------------------------------- ASS
def test_ass_input():
    doc = formats.read(IN / "aegisub.ass")
    assert _texts(doc) == ["この橋は百年以上前に作られたそうです",
                           "当時は町と町をつなぐ大事な道で毎日たくさんの人が行き来していました", "今は観光名所です"]
    assert {c.speaker for c in doc.cues} == {"佐藤"}


def test_ass_same_time_events_kept_apart():
    """同一时间的两条普通 Dialogue（不同说话人、或画面上的说明文字）不合并，说话人各自保留。"""
    text = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,A,0,0,0,,行こうか
Dialogue: 0,0:00:01.00,0:00:03.00,Default,B,0,0,0,,うん
Dialogue: 0,0:00:01.00,0:00:03.00,Sign,,0,0,0,,{\\an8}駅前
"""
    doc = formats.loads(text, "ass")
    assert sorted((c.speaker or "", c.text) for c in doc.cues) == [("", "駅前"), ("A", "行こうか"), ("B", "うん")]

def test_ass_roundtrip_with_ruby():
    """kugiri 自己带振假名的 ASS（每行一条定位 Dialogue + Ruby 样式行）读回来还是原来的 cue。"""
    src = reflow(formats.read(IN / "kinsoku.srt"), preset("netflix"))
    back = formats.loads(formats.dumps(src, "ass", ruby=True), "ass")

    def bare(t: str) -> str:
        return "".join(ch for ch in t if ch not in " 　、。")
    assert [bare(c.text) for c in back.cues] == [bare(c.text) for c in src.cues]
    assert [(c.start, c.end) for c in back.cues] == [(round(c.start, 2), round(c.end, 2)) for c in src.cues]


# ---------------------------------------------------------------- 人工字幕的约定
def test_dialogue_and_sound_tags_stand_alone():
    out = reflow(formats.read(IN / "conventions.srt"), preset("youtube"))
    texts = _texts(out)
    assert texts[0] == "（拍手）"
    assert out.cues[1].lines == ["-もう始まってる？", "-うん 始まってるよ"]
    assert "♪～" in texts
    assert not any("（拍手）" in t and t != "（拍手）" for t in texts)
    assert not any("♪" in t and t != "♪～" for t in texts)


def test_dash_lines_that_are_not_dialogue():
    from kugiri.textutil import is_dialogue
    assert is_dialogue(["-行こう", "-うん"])
    assert not is_dialogue(["-5度", "-10度"])          # 负数
    assert not is_dialogue(["――そして", "――夜が来た"])  # 破折号开头的旁白


def test_dialogue_too_wide_is_split():
    """放不下的两人对话：拆成每人一条（按字数分时间），不把两个人的话接在一起。"""
    doc = formats.loads("1\n00:00:00,000 --> 00:00:03,000\n-今日はどこに行こうか迷っているんだけど\n-海がいいな\n", "srt")
    out = reflow(doc, preset("vertical"))
    texts = _texts(out)
    assert texts[-1] == "海がいいな", texts
    assert not any("-" in t for t in texts)
    assert out.cues[-1].start > 2.0          # 时间按字数分：后一个人的话从后面开始
