"""ja-core：规范化、渲染、读音、振假名、用户词典、文件格式、时间轴 JSON、CLI。"""
from __future__ import annotations

import json

import pytest

from kugiri import formats
from kugiri.cli import main
from kugiri.reading import reading, ruby_spans, split_ruby, tokens
from kugiri.textutil import display_width, normalize, render_line
from kugiri.timeline import Cue, Document, Ruby, Unit
from kugiri.userdict import UserDict


# ---------------------------------------------------------------- 文本
@pytest.mark.parametrize("src,exp", [
    ("ｶﾞｲﾄﾞﾌﾞｯｸ", "ガイドブック"),
    ("Ｇ５で１２３円", "G5で123円"),
    ("１，０００円", "1,000円"),
    ("えーと...そうですね・・・", "えーと…そうですね…"),
    ("本当!?　すごい", "本当！？ すごい"),
    ("OK!", "OK!"),
    ("a​b", "ab"),
])
def test_normalize(src, exp):
    assert normalize(src) == exp


def test_render_netflix():
    assert render_line("はい、そうです。でも") == "はい そうです　でも"
    assert render_line("終わりです。") == "終わりです"
    assert render_line("終わりです。", "keep") == "終わりです。"
    assert display_width("ABCあい") == 3.5


# ---------------------------------------------------------------- 读音
def test_tokens_numbers_and_units():
    toks = {t.surface: t.read for t in tokens("参加費は1,500円で3日間、2.5GBです")}
    assert toks["1,500"] == "センゴヒャク"
    assert toks["円"] == "エン"
    assert toks["2.5"] == "ニテンゴ"


def test_reading_pron_vs_read():
    assert reading("東京は") == "トウキョウハ"
    assert reading("東京は", pron=True) == "トーキョーワ"


@pytest.mark.parametrize("surface,read,exp", [
    ("静か", "シズカ", [(0, 1, "しず")]),
    ("取り扱い", "トリアツカイ", [(0, 1, "と"), (2, 3, "あつか")]),
    ("東京", "トウキョウ", [(0, 2, "とうきょう")]),
    ("お茶", "オチャ", [(1, 2, "ちゃ")]),
    ("ひらがな", "ヒラガナ", []),
])
def test_split_ruby(surface, read, exp):
    assert split_ruby(surface, read) == exp


def test_counter_ruby_sandhi():
    # 数字后的量词按实际发音标（「30分」曾标成「ふん」）
    t = "3時30分、3本、6杯、5分、2本"
    got = [(t[r.cs:r.ce], r.text) for r in ruby_spans(t, None, "all")]
    assert got == [("時", "じ"), ("分", "ぷん"), ("本", "ぼん"), ("杯", "ぱい"), ("分", "ふん"), ("本", "ほん")]


def test_userdict_reading_override():
    d = UserDict.parse("表記\t読み\t禁止分割\n明日\tあす\t0\nVRChat\tぶいあーるちゃっと\n")
    assert [e.nosplit for e in d.entries] == [False, True]
    assert reading("明日VRChatで", d) == "アスブイアールチャットデ"
    rb = {("明日VRChatで")[r.cs:r.ce]: r.text for r in ruby_spans("明日VRChatで", d, "user")}
    assert rb == {"明日": "あす", "VRChat": "ぶいあーるちゃっと"}


def test_userdict_spaces_and_errors():
    d = UserDict.parse("喫茶店 きっさてん 1\nOpen AI\nABC\t\t1\n")       # 网页里打不出 Tab：空格分列
    assert [(e.surface, e.reading) for e in d.entries] == [("喫茶店", "キッサテン"), ("Open AI", None), ("ABC", None)]
    for bad in ("東京\tTokyo\n", "東京\tとうきょう\tx\n", "a\tb\tc\td\n"):
        with pytest.raises(ValueError, match="line 1"):
            UserDict.parse(bad)


def test_read_rejects_empty_and_foreign_json(tmp_path):
    (tmp_path / "e.srt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "l.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="no subtitles"):
        formats.read(tmp_path / "e.srt")
    with pytest.raises(ValueError, match="not a kugiri timeline"):
        formats.read(tmp_path / "l.json")


def test_userdict_longest_match():
    d = UserDict.parse("東京\tとうきょう\n東京駅\tとうきょうえき\n")
    assert [(a, b) for a, b, _ in d.find("東京駅と東京")] == [(0, 3), (4, 6)]


# ---------------------------------------------------------------- 文件格式
SRT = """1
00:00:01,000 --> 00:00:02,500
<i>こんにちは</i>
{\\an8}世界

2
00:00:03,000 --> 00:00:04,000
Hello
world
"""


def test_srt_roundtrip():
    doc = formats.loads(SRT, "srt")
    assert [c.text for c in doc.cues] == ["こんにちは世界", "Hello world"]
    out = formats.dumps(doc, "srt")
    assert "00:00:01,000 --> 00:00:02,500\nこんにちは世界" in out
    assert formats.loads(out, "srt").cues[1].text == "Hello world"


def test_vtt_parse():
    vtt = """WEBVTT
Kind: captions

NOTE 注释

c1
00:01.000 --> 00:02.000 align:start
<v 田中><ruby>東京<rt>とうきょう</rt></ruby>です

00:00:03.000 --> 00:00:04.000
&gt;&gt; 佐藤
はい
"""
    doc = formats.loads(vtt, "vtt")
    assert [(c.text, c.speaker) for c in doc.cues] == [("東京です", "田中"), ("はい", "佐藤")]


def test_vtt_ruby_and_ass_ruby():
    c = Cue(1.0, 2.0, "東京の夜", ["東京の夜"], ruby=[Ruby(0, 2, "とうきょう"), Ruby(3, 4, "よる")])
    doc = Document([c])
    assert "<ruby>東京<rt>とうきょう</rt></ruby>" not in formats.dumps(doc, "vtt")
    assert "<ruby>東京<rt>とうきょう</rt></ruby>の<ruby>夜<rt>よる</rt></ruby>" in formats.dumps(doc, "vtt", ruby=True)
    ass = formats.dumps(doc, "ass", ruby=True)
    assert ass.count(",Ruby,") == 2 and "\\an2\\pos(" in ass and "\\an7\\pos(" in ass
    plain = formats.dumps(doc, "ass")
    assert ",Ruby," not in plain.split("[Events]")[1]


def test_ass_escape():
    doc = Document([Cue(0, 1, "a{b}\\c", ["a{b}\\c"])])
    assert "a｛b｝＼c" in formats.dumps(doc, "ass")


def test_srt_escapes_player_markup():
    # 播放器会把 SRT 里的 <…> / {…} / \N 当标签和换行（用 ffmpeg 读回时发现）
    doc = Document([Cue(0, 1, "x<y>z{a}\\N", ["x<y>z{a}\\N"])])
    assert "x＜y＞z｛a｝＼N" in formats.dumps(doc, "srt")


def test_ass_speaker_comma_and_vtt_speaker_entities():
    doc = formats.loads("WEBVTT\n\n00:00.000 --> 00:01.000\n<v 田中, 太郎 &amp; R&amp;D>はい\n", "vtt")
    assert doc.cues[0].speaker == "田中, 太郎 & R&D"
    assert "<v 田中, 太郎 &amp; R&amp;D>はい" in formats.dumps(doc, "vtt")
    row = next(x for x in formats.dumps(doc, "ass").splitlines() if x.startswith("Dialogue:"))
    assert row.split(",", 9)[4] == "田中， 太郎 & R&D" and row.split(",", 9)[9] == "はい"


def test_ass_ruby_position_uses_rendered_width():
    from kugiri.formats.ass import Metrics
    m = Metrics(None, "Noto Sans JP")
    assert m.width("東京", 100) == pytest.approx(200 * 1000 / 1448)        # libass：em = fs × 1000 / (winAsc+winDesc)
    assert m.width("1.5", 100) == pytest.approx((555 + 278 + 555) / 1448 * 100)
    # 「\」会被转义成全角「＼」显示，振假名位置要按全角算
    doc = Document([Cue(0, 1, "\\東京", ["\\東京"], ruby=[Ruby(1, 3, "とうきょう")])])
    ass = formats.dumps(doc, "ass", ruby=True, font_size=100)
    import re
    x0 = int(re.search(r"\\an7\\pos\((\d+),", ass).group(1))
    xr = int(re.search(r"\\an2\\pos\((\d+),", ass).group(1))
    assert xr == pytest.approx(x0 + m.width("＼", 100) + m.width("東京", 100) / 2, abs=1)


def test_timeline_json_roundtrip():
    doc = Document([Cue(1.0, 2.0, "東京", ["東京"], [Unit(0, 2, 1.0, 1.5, "トウキョウ", 0.9)],
                        [Ruby(0, 2, "とうきょう")], "A")], fps=30.0)
    back = Document.from_dict(json.loads(doc.dumps()))
    assert back == doc


@pytest.mark.parametrize("bad", [
    {"format": "x", "version": 1, "cues": []},
    {"format": "kugiri-timeline", "version": 2, "cues": []},
    {"format": "kugiri-timeline", "version": 1, "cues": [{"start": 0, "end": 1, "text": "ab", "lines": ["a"]}]},
    {"format": "kugiri-timeline", "version": 1,
     "cues": [{"start": 0, "end": 1, "text": "ab", "units": [{"cs": 0, "ce": 5, "start": 0, "end": 1}]}]},
])
def test_timeline_validation(bad):
    with pytest.raises(ValueError):
        Document.from_dict(bad)


def test_timeline_units_drive_segmentation(tmp_path):
    """有字级时间（M2 对齐输出）时用真实时间切分：长停顿处断开，文字不规范化。"""
    text = "今日はいい天気ですね散歩に行きましょう"
    units = [Unit(i, i + 1, 0.2 * i, 0.2 * i + 0.18) for i in range(10)]
    units += [Unit(i, i + 1, 3.0 + 0.2 * (i - 10), 3.0 + 0.2 * (i - 10) + 0.18) for i in range(10, len(text))]
    doc = Document([Cue(0.0, units[-1].end, text, units=units)])
    path = tmp_path / "in.json"
    path.write_text(doc.dumps(), encoding="utf-8")
    out = tmp_path / "out.json"
    assert main(["reflow", str(path), "-o", str(out), "--preset", "youtube"]) == 0
    res = Document.load(out)
    assert [c.text for c in res.cues] == ["今日はいい天気ですね", "散歩に行きましょう"]
    assert res.cues[1].units[0].cs == 0 and res.cues[1].start == pytest.approx(3.0)


def test_cli_stdout_and_errors(tmp_path, capsys):
    src = tmp_path / "a.srt"
    src.write_text(SRT, encoding="utf-8")
    assert main(["reflow", str(src), "--format", "vtt"]) == 0
    assert capsys.readouterr().out.startswith("WEBVTT")
    assert main(["reflow", str(tmp_path / "missing.srt")]) == 1
    assert main(["reflow", str(src), "-o", str(tmp_path / "x.txt")]) == 1
