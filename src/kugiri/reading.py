"""读音与振假名：pyopenjtalk-plus（MIT；OpenJTalk 修改版 / naist-jdic 都是 BSD），用户词典可以覆盖。

- ``tokens(text)``：按 OpenJTalk 分词，每个词带 text 里的下标、读音形（``read``，トウキョウ / ハ）
  和发音形（``pron``，トーキョー / ワ）。数字会被 OpenJTalk 改写成汉数字，这里把整个数字串合成一个词。
- ``ruby_spans(text)``：给含汉字的词标振假名（平假名），送假名不标（静か → 静[しず]か）。
- ``ruby_doc(texts)``：整份字幕的振假名；``once`` 时同一个词只在第一次出现时标（Netflix 规则）。
- ``hard`` 模式只给难读的词标：含常用漢字表外的字、或用了表外读法（``grade`` 给 1–6 时，
  小学该年级还没学的字也算难读）。数据是 ``data/kanji.tsv``（常用漢字表 + 学年別漢字配当表，
  由 ``tools/build_kanji.py`` 从文化庁 / 文科省的告示生成）。
振假名必须用读音形 ``read``（M0 结论），发音形会把 東京 标成 とーきょー。
"""
from __future__ import annotations

import contextlib
import io
import re
import unicodedata
from dataclasses import dataclass, replace
from functools import cache, lru_cache
from importlib.resources import files

from .timeline import Ruby
from .userdict import UserDict, to_hiragana, to_katakana

_KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿々〆ヶ]")
_NUMK = set("〇一二三四五六七八九十百千万億兆零.・点0123456789")
_KANA = re.compile(r"[ァ-ヶー]")
_NUM = re.compile(r"[0-9０-９][0-9０-９,，.．]*")


@dataclass
class Token:
    cs: int
    ce: int
    surface: str
    read: str          # 读音形（片假名）
    pron: str          # 发音形（片假名，去掉重音符号）
    user: bool = False


@lru_cache(maxsize=1)
def _ojt():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import pyopenjtalk  # 没装 onnxruntime 时会打印一行提示，屏蔽掉
    return pyopenjtalk


def _nf(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _frontend(text: str) -> list[dict]:
    if not text.strip():
        return []
    # 千位分隔符会被读成「イチ、ゼロゼロゼロ」，送进 OpenJTalk 前去掉（对齐时数字串整体处理）
    text = re.sub(r"(?<=[0-9０-９])[,，](?=[0-9０-９]{3})", "", text)
    ojt = _ojt()
    with contextlib.redirect_stdout(io.StringIO()):
        return ojt.run_frontend(text)


def _align(text: str, feats: list[dict]) -> list[Token]:
    """把 OpenJTalk 的词序列对回 text 的下标。对不上的词（数字改写等）合并到相应的原文区间。"""
    out: list[Token] = []
    norm = [_nf(c) for c in text]
    pos, i = 0, 0

    def match_at(p: int, s: str) -> int | None:
        s = _nf(s)
        q, acc = p, ""
        while q < len(text) and len(acc) < len(s):
            acc += norm[q]
            q += 1
        return q if acc == s else None

    while i < len(feats) and pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        f = feats[i]
        s = f["string"]
        end = match_at(pos, s)
        if end is not None:
            out.append(Token(pos, end, text[pos:end], f["read"], f["pron"].replace("’", "")))
            pos, i = end, i + 1
            continue
        m = _NUM.match(text, pos)
        if m:   # 数字串：OpenJTalk 把它改写成了汉数字词（可能带后缀：3日 → 三日）
            r_end = m.end()
            while r_end > pos and text[r_end - 1] in ",，.．":
                r_end -= 1
            read = pron = ""
            j = i
            while j < len(feats):
                fs = _nf(feats[j]["string"])
                k = 0
                while k < len(fs) and fs[k] in _NUMK:
                    k += 1
                if k == 0:
                    break
                read += feats[j]["read"]
                pron += feats[j]["pron"].replace("’", "")
                j += 1
                if k < len(fs):          # 汉数字 + 后缀：后缀也对上原文时一起吞掉
                    e = match_at(r_end, fs[k:])
                    if e is not None:
                        r_end = e
                    break
            out.append(Token(pos, r_end, text[pos:r_end], read, pron))
            pos, i = r_end, j
            continue
        # 其他对不上的情况：在后面几个字符里找这个词，找到就把中间的字符当成无读音的符号
        found = next((q for q in range(pos + 1, min(len(text), pos + 8)) if match_at(q, s) is not None), None)
        if found is None:
            i += 1                       # 丢掉这个词
        else:
            out.append(Token(pos, found, text[pos:found], "", ""))
            pos = found
    return out


def tokens(text: str, udict: UserDict | None = None) -> list[Token]:
    """text 的分词和读音；用户词典里有读音的词整体覆盖。"""
    hits = [(a, b, e) for a, b, e in (udict.find(text) if udict else []) if e.reading]
    out: list[Token] = []
    pos = 0
    for a, b, e in [*hits, (len(text), len(text), None)]:
        if a > pos:
            out += [Token(t.cs + pos, t.ce + pos, t.surface, t.read, t.pron)
                    for t in _align(text[pos:a], _frontend(text[pos:a]))]
        if e is not None:
            out.append(Token(a, b, text[a:b], e.reading, e.reading, user=True))
        pos = b
    return out


def reading(text: str, udict: UserDict | None = None, *, pron: bool = False) -> str:
    """整句读音（片假名）。``pron=True`` 时给发音形（は→ワ、長音→ー）。"""
    return "".join((t.pron if pron else t.read) for t in tokens(text, udict) if _KANA.search(t.read))


def split_ruby(surface: str, read: str) -> list[tuple[int, int, str]]:
    """把一个词的读音分配给其中的汉字段：送假名/假名部分不标。返回 [(a, b, 平假名)]（词内下标）。

    例：静か/シズカ → [(0, 1, しず)]；取り扱い/トリアツカイ → [(0,1,と), (2,3,あつか)]。
    对不上时整个词标一个振假名。
    """
    if not _KANJI.search(surface) or not read:
        return []
    kata = to_katakana(read)
    parts = re.findall(r"[㐀-䶿一-鿿豈-﫿々〆ヶ]+|[^㐀-䶿一-鿿豈-﫿々〆ヶ]+",
                       surface)
    pat, groups, pos = "", [], 0
    for p in parts:
        if _KANJI.match(p):
            pat += "(.+?)"
            groups.append((pos, pos + len(p)))
        else:
            pat += re.escape(to_katakana(p))
        pos += len(p)
    m = re.fullmatch(pat, kata)
    if not m:
        return [(0, len(surface), to_hiragana(kata))]
    return [(a, b, to_hiragana(m.group(g + 1))) for g, (a, b) in enumerate(groups)]


_NUMERAL = re.compile(r"^[0-9０-９,，.．〇一二三四五六七八九十百千万]+$")


def _counter_sandhi(t: Token, prev: Token | None) -> Token:
    """数字后面的量词用发音形的头一个假名（30分 = さんじゅっ「ぷん」、3本 = さん「ぼん」、6杯 = ろっ「ぱい」）。
    读音形是辞书形（フン / ホン / ハイ）；发音形还会把长音写成ー，所以只在两者只差头一个字时换。"""
    if (prev is None or t.user or not _NUMERAL.match(prev.surface) or not t.read or not t.pron
            or len(t.read) != len(t.pron) or t.read[1:] != t.pron[1:] or t.read[0] == t.pron[0]):
        return t
    return replace(t, read=t.pron[0] + t.read[1:])


RUBY_MODES = ("none", "all", "hard", "user")
GRADES = (1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class _Kanji:
    grade: int                 # 1–6 小学配当学年，7 = 中学以降学的常用漢字
    on: tuple[str, ...]        # 音（平假名）
    kun: tuple[str, ...]       # 訓（平假名；「.」后面是送假名：い.きる）


_VOICED = dict(zip("がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ", "かきくけこさしすせそたちつてとはひふへほはひふへほ"))
_U2I = dict(zip("うくぐすつぬぶむる", "いきぎしちにびみり"))
_O_ROW = set("おこごそぞとどのほぼぽもよろょ")
_LIAISON = dict(zip("あいうえお", "なにぬねの"))


def _unvoice(r: str) -> str:
    """连浊 / 半浊音（ひと → びと、ふん → ぷん）：比较时把第一个假名还原成清音。"""
    return _VOICED.get(r[0], r[0]) + r[1:] if r else r


@lru_cache(maxsize=1)
def _kanji_table() -> dict[str, _Kanji]:
    out = {}
    for line in files("kugiri").joinpath("data/kanji.tsv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        k, g, rs, alts = line.split("\t")
        rs = rs.split() + alts.split()          # 備考里「〜とも」的读法也算表内
        out[k] = _Kanji(int(g), tuple(to_hiragana(r) for r in rs if _KANA.match(r)),
                        tuple(r for r in rs if not _KANA.match(r)))
    return out


@lru_cache(maxsize=1)
def _special_words() -> dict[str, frozenset[str]]:
    """付表（今日 / 大人 …）和本表備考（愛媛 / 浴衣 …）的特别读法，按 ``split_ruby`` 拆成 汉字段 → 读音。"""
    out: dict[str, set[str]] = {}
    for line in files("kugiri").joinpath("data/kanji_words.tsv").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            w, r = line.split("\t")
            for a, b, rr in split_ruby(w, r):
                out.setdefault(w[a:b], set()).add(rr)
    return {k: frozenset(v) for k, v in out.items()}


@cache
def _cands(c: str) -> tuple[frozenset[str], frozenset[str]]:
    """一个常用汉字在词里能有的读音 →（一般的, 只能跟在 ん 后面的）。
    音：原样、末尾く/つ/ち/き 促音化（学校 がっ）；ん 后面あ行变な行（反応 のう、天皇 のう）。
    訓：整个读音、去掉送假名的语干（生きる → い）、动词连用形（場合 あい、受付 うけ）、促音（切符 きっ、生粋 きっ）。
    第一个假名都还原成清音（连浊在比较时处理）。"""
    k = _kanji_table().get(c)
    if k is None:
        return frozenset(), frozenset()
    out = set(k.on)
    out.update(r[:-1] + "っ" for r in k.on if r[-1] in "くつちき")
    liaison = {_LIAISON[r[0]] + r[1:] for r in k.on if r[0] in _LIAISON}
    for r in k.kun:
        stem, _, okuri = r.partition(".")
        full = stem + okuri
        out.add(full)
        if okuri:
            out.add(stem)
        if full[-1] in _U2I:                    # 动词：连用形、促音便
            out.add(full[:-1] + _U2I[full[-1]])
            out.add(full[:-1] + "っ")
        if full[-1] in _U2I:                    # 一段动词的连用形（見る み）；送假名省略写法（向い むか）
            out.add(full[:-1])
        if not okuri:
            out.add(full + "っ")
    return frozenset(_unvoice(x) for x in out if x), frozenset(_unvoice(x) for x in liaison)


def _match(read: str, p: int, cand: str) -> bool:
    """``read[p:]`` 以 ``cand`` 开头：第一个假名不分清浊；お段后面的 う / お 不分（OpenJTalk 的读音形
    偶尔把 ホウ 写成 ホオ）。前一个假名看 ``read`` 本身，所以跨字的边界也对（小売 こうり：小 こ + 売 う）。"""
    if p + len(cand) > len(read):
        return False
    for k, x in enumerate(cand):
        y = read[p + k]
        if k == 0:
            y = _VOICED.get(y, y)
        if x != y and not ({x, y} == {"う", "お"} and p + k > 0 and read[p + k - 1] in _O_ROW):
            return False
    return True


@lru_cache(maxsize=4096)
def _readable(run: str, read: str) -> bool:
    """汉字段 ``run`` 读作 ``read``（平假名）时，能不能拆成每个字的常用音訓（``_cands``，允许连浊），
    或者付表 / 備考里的特别读法（多字的词整段匹配：人達 = 人 + 達[たち]、日本国 = 日本 + 国）。
    々 重复前一个字的读音，ヶ 读 か / が / こ。"""
    special = _special_words()
    todo, done = [(0, 0)], set()   # (run 下标, read 下标)
    while todo:
        i, p = todo.pop()
        if (i, p) in done:
            continue
        done.add((i, p))
        if i == len(run):
            if p == len(read):
                return True
            continue
        c = run[i]
        if c == "々":
            cs, li = _cands(run[i - 1]) if i else (frozenset(), frozenset())
        elif c == "ヶ":
            cs, li = frozenset({"か", "こ"}), frozenset()
        else:
            cs, li = _cands(c)
        if p and read[p - 1] == "ん":
            cs = cs | li
        todo += [(i + 1, p + len(x)) for x in cs if _match(read, p, x)]
        for j in range(i + 1, len(run) + 1):
            todo += [(j, p + len(x)) for x in special.get(run[i:j], ()) if _match(read, p, _unvoice(x))]
    return False


def is_hard(surface: str, read: str, grade: int | None = None) -> bool:
    """一个词（读音形，片假名或平假名）是否难读：含常用漢字表外的字 / 表外读法，
    或（给了 ``grade``）含小学 ``grade`` 年级还没学的字。没有汉字的词不难。"""
    tab = _kanji_table()
    limit = grade or 7
    spans = split_ruby(surface, read)
    if not spans:
        return False
    for a, b, r in spans:
        run = surface[a:b]
        if any(c not in tab or tab[c].grade > limit for c in run if _KANJI.match(c) and c not in "々ヶ〆"):
            return True
        # split_ruby 对不上时整词一个振假名（run 里带假名）：读法没法按字查，只看字
        if not all(_KANJI.match(c) for c in run):
            continue
        if not _readable(run, r):
            return True
    return False


def ruby_spans(text: str, udict: UserDict | None = None, mode: str = "all", *, grade: int | None = None,
               seen: set | None = None) -> list[Ruby]:
    """振假名区间。``mode``：``all`` = 所有含汉字的词；``hard`` = 只给难读的词（见 ``is_hard``，``grade``
    = 按小学几年级的学习范围算）；``user`` = 只给用户词典里有读音的词；``none``。用户词典里有读音的词在
    ``hard`` 模式也标（读法多半特殊）。``seen``：已经标过的（表記, 读音），给了就只标第一次出现，并把新标的加进去。"""
    if mode == "none" or not _KANJI.search(text):
        return []
    out = []
    prev = None
    for t in tokens(text, udict):
        t, prev = _counter_sandhi(t, prev), t
        if mode == "user" and not t.user:
            continue
        if mode == "hard" and not t.user and not is_hard(t.surface, t.read, grade):
            continue
        if t.user and not _KANJI.search(t.surface):     # 词典里的英文名等：整词标读音
            spans = [(0, len(t.surface), to_hiragana(t.read))]
        else:
            spans = split_ruby(t.surface, t.read)
        if not spans:
            continue
        if seen is not None:
            key = (t.surface, to_hiragana(t.read))
            if key in seen:
                continue
            seen.add(key)
        out += [Ruby(t.cs + a, t.cs + b, r) for a, b, r in spans]
    return out


def ruby_doc(texts: list[str], udict: UserDict | None = None, mode: str = "all", *, grade: int | None = None,
             once: bool = False) -> list[list[Ruby]]:
    """整份字幕（按时间顺序的每条文字）的振假名。``once``：同一个词（表記 + 读音）只在第一次出现时标。"""
    seen: set | None = set() if once else None
    return [ruby_spans(t, udict, mode, grade=grade, seen=seen) for t in texts]
