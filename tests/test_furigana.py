"""振假名「只标难读字」：包内数据（常用漢字表 / 学年別漢字配当表）、难读判定、只标第一次、三个入口的参数。"""
from __future__ import annotations

from collections import Counter
from importlib.resources import files

import pytest

from kugiri import service
from kugiri.reading import _kanji_table, _special_words, is_hard, ruby_doc, ruby_spans, tokens
from kugiri.timeline import Cue, Document
from kugiri.userdict import UserDict


def test_kanji_data():
    rows = [ln.split("\t") for ln in files("kugiri").joinpath("data/kanji.tsv").read_text(encoding="utf-8").splitlines()
            if not ln.startswith("#")]
    rows = [r for r in rows if r[0] not in "叱填剥頬"]                 # 許容字体的别名
    assert len(rows) == 2136
    rs = [x for r in rows for x in r[2].split()]
    assert sum(1 for x in rs if "ァ" <= x[0] <= "ヶ") == 2352 and sum(1 for x in rs if "ぁ" <= x[0] <= "ん") == 2036
    assert Counter(int(r[1]) for r in rows) == {1: 80, 2: 160, 3: 200, 4: 202, 5: 193, 6: 191, 7: 1110}
    tab = _kanji_table()
    assert "い.きる" in tab["生"].kun and "じゅっ" in tab["十"].on        # 送假名、備考的「ジュッ」とも
    assert tab["叱"] == tab["𠮟"] and tab["剥"] == tab["剝"]
    assert tab["一"].grade == 1 and tab["茨"].grade == 4 and tab["彙"].grade == 7
    assert "きょう" in _special_words()["今日"] and "えひめ" in _special_words()["愛媛"] and "いばらき" in _special_words()["茨城"]


def _hard(text, grade=None):
    return [t.surface for t in tokens(text) if is_hard(t.surface, t.read, grade)]


@pytest.mark.parametrize("text,exp", [
    ("東京の夜は静かです", []),
    ("薔薇が咲いた", ["薔薇"]),                       # 表外字
    ("流石に寒い", ["流石"]),                         # 当て字（表外读法）
    ("今日は大人と一緒に", []),                       # 付表
    ("場合によっては立場が", []),                     # 訓的连用形（あう → あい、たつ → たち）
    ("切符を三枚", []),                               # 訓的促音（きる → きっ）
    ("学校で反応を見る", []),                         # 音的促音、连声（オウ → のう）
    ("人々が時々", []),                               # 々
    ("日本の私達", []),                               # kugiri 补充的常见读法
    ("30分で3本", []),                                # 量词的发音形（ぷん / ぼん）
    ("辛い経験", ["辛い"]),                           # つらい 不在表里（からい 才是）
    ("小売店と大海原と子馬", []),                     # 字界上 お段 + う（こ+うり）不能当成长音
    ("小雨の宮城で三十分", []),                       # 備考：「小雨」こさめ、宮城（みやぎ）、十「ジュッ」とも
    ("生粋の江戸っ子", []),                           # 訓 + 促音（き + っ）；江 え 是表内的訓
    ("最早", ["最早"]),                               # 熟字训：不能拿訓的任意前缀凑（も + はや）
])
def test_is_hard(text, exp):
    assert _hard(text) == exp


def test_grade():
    assert _hard("東京の夜は静かです", 3) == ["静か"]          # 静 是 4 年级
    assert _hard("東京の夜は静かです", 4) == []
    assert _hard("今日は大人と", 1) == ["今日"]       # 付表的词也看字：今 是 2 年级，大 / 人 是 1 年级
    assert _hard("今日は大人と", 2) == []


def test_ruby_hard_whole_word_and_user_dict():
    text = "憂鬱な薔薇"
    got = [(text[r.cs:r.ce], r.text) for r in ruby_spans(text, None, "hard")]
    assert got == [("薔薇", "ばら")]
    d = UserDict.parse("東京\tとうきょう\t1\n")            # 词典里给了读音的词在 hard 模式也标
    got = [r.text for r in ruby_spans("東京の薔薇", d, "hard")]
    assert got == ["とうきょう", "ばら"]


def test_ruby_once():
    texts = ["薔薇と薔薇", "東京の薔薇", "薔薇"]
    assert [len(r) for r in ruby_doc(texts, None, "hard")] == [2, 1, 1]
    assert [len(r) for r in ruby_doc(texts, None, "hard", once=True)] == [1, 0, 0]
    assert [len(r) for r in ruby_doc(texts, None, "all", once=True)] == [1, 1, 0]


def test_add_ruby_once_follows_time_order():
    doc = Document([Cue(5, 6, "薔薇", ["薔薇"]), Cue(1, 2, "薔薇", ["薔薇"])])
    out = service.add_ruby(doc, service.Options(ruby="hard", ruby_once=True))
    assert [bool(c.ruby) for c in out.cues] == [False, True]      # 时间上先出现的那条标
    assert not any(c.ruby for c in doc.cues)


def test_options_validate_grade():
    assert service.Options(ruby="hard", ruby_grade=3).ruby_grade == 3
    with pytest.raises(ValueError):
        service.Options(ruby="hard", ruby_grade=7)
    with pytest.raises(ValueError):
        service.Options(ruby="all", ruby_grade=3)
