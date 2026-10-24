"""生成振假名「只标难读字」用的包内数据 ``src/kugiri/data/kanji.tsv`` / ``kanji_words.tsv``。

来源（都是告示，著作権法第 13 条第 2 号：告示不是著作权的对象）：
- 常用漢字表（平成 22 年内閣告示第 2 号）：文化庁 PDF
  https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kijun/naikaku/pdf/joyokanjihyo_20101130.pdf
  → 2136 字、每个字的音訓、備考里的特殊读法（「愛媛（えひめ）」等）和付表（熟字訓 / 当て字）。
- 学年別漢字配当表（小学校学習指導要領 平成 29 年文部科学省告示第 63 号 別表，2020 年施行，1026 字）：
  https://www.mext.go.jp/content/20230120-mxt_kyoiku02-100002604_01.pdf 第 42–45 页。
  PDF 里这几页是轮廓线没有文字层，字表按 ja.wiktionary「付録:教育漢字の一覧」（同一告示的转录）读入，
  再和 PDF 页面图逐行核对过（每学年字数 80/160/200/202/193/191 一致，且全部在常用漢字表里）。

    uv run --with pypdf python tools/build_kanji.py joyokanjihyo_20101130.pdf wikt_kyoiku.txt
"""
from __future__ import annotations

import itertools
import re
import sys
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src/kugiri/data"
KANJI = re.compile(r"^[㐀-䶿一-鿿豈-﫿\U00020000-\U0002FFFF]$")
KANA = re.compile(r"^[ぁ-んァ-ヶー]+$")
# 常用漢字表「（付）第 2 の 3」：这几个字的通用字体（JIS 第 1・2 水準）和表里的字形码位不同，两个都认
ALIAS = {"𠮟": "叱", "塡": "填", "剝": "剥", "頰": "頬"}
# 付表里一格写了两个词的
FUHYO_SPLIT = {"海女海士": ["海女", "海士"], "河原川原": ["河原", "川原"], "叔父伯父": ["叔父", "伯父"],
               "叔母伯母": ["叔母", "伯母"], "母屋母家": ["母屋", "母家"], "二十二十歳": ["二十", "二十歳"],
               "数寄屋数奇屋": ["数寄屋", "数奇屋"]}
# 表里没有、但谁都会读的读法（常用漢字表只收了「明日（あす）」，「日本」按字只能读成ニッポン，
# 「達」只有タツ（友達在付表），「来」的訓只有くる / きたる / きたす（来ない / 来ます 的 こ / き 是活用）
EXTRA_WORDS = [("日本", "にほん"), ("明日", "あした"), ("文字", "もじ"), ("達", "たち"), ("来", "こ"), ("来", "き"),
               # 備考里跨行写的（解析不到）：雨「春雨」「小雨」「霧雨」、位「三位一体」「従三位」
               ("春雨", "はるさめ"), ("小雨", "こさめ"), ("霧雨", "きりさめ"), ("三位一体", "さんみいったい"),
               ("従三位", "じゅさんみ")]
GRADE_COUNTS = {1: 80, 2: 160, 3: 200, 4: 202, 5: 193, 6: 191}


def hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def okuri_stem(k: str, read: str, examples: str) -> str:
    """訓 → 「语干.送假名」（あわ.れむ）：在例里找这个字后面紧跟的平假名，是读音的后缀就是送假名。找不到原样返回。"""
    for ex in examples.split(","):
        for m in re.finditer(re.escape(k) + r"([ぁ-ん]+)", ex):
            ok = m.group(1)
            for n in range(len(ok), 0, -1):         # 例是活用形时（哀れみ）取能对上的最长部分
                if read.endswith(ok[:n]) and len(ok[:n]) < len(read) and read[: -n] and read[-n:] == ok[:n]:
                    return read[:-n] + "." + read[-n:]
    return read


def parse_joyo(pdf: Path) -> tuple[dict[str, list[str]], dict[str, list[str]], list[tuple[str, str]]]:
    """→（每个字的音訓（表里的，訓带「.」分送假名）、備考里的别的读法（「ジュッ」とも 等）、特别读法的词）"""
    import pypdf
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(pdf).pages)
    text = unicodedata.normalize("NFKC", text)      # PDF 里用了康熙部首等兼容字符（⽤ → 用）
    lines = text.split("\n")
    start = next(i for i, l in enumerate(lines) if re.sub(r"\s", "", l) == "本表")
    end = next(i for i, l in enumerate(lines) if re.sub(r"\s", "", l) == "付表")
    readings: dict[str, list[str]] = {}
    alts: dict[str, list[str]] = {}
    words: list[tuple[str, str]] = []
    cur = None
    for line in lines[start:end]:
        if "indd" in line:
            continue
        fields = [re.sub(r"\s", "", f) for f in line.split("\t")]
        fields = [f for f in fields if f]
        if not fields:
            continue
        head = KANJI.match(fields[0]) and len(fields) > 1   # 只有一个字的行是上一个字的旧字体（弁：辨 / 瓣 / 辯）
        if head:
            cur = fields[0]
            readings.setdefault(cur, [])
            fields = fields[1:]
        if cur is None:
            continue
        while fields and (fields[0][0] in "([" or KANJI.match(fields[0])):   # （亞）旧字体、[遜] 許容字体
            fields = fields[1:]
        if (head or len(fields) >= 2) and fields and KANA.match(fields[0]):   # 单独一个假名的行是页脚的索引
            r = fields[0]
            readings[cur].append(r if re.match(r"[ァ-ヶ]", r) else okuri_stem(cur, r, fields[1] if len(fields) > 1 else ""))
        # 備考（每格去掉空格再找：「茨城 （いばらき） 県」；格之间留 tab，免得和例的词连起来）
        flat = "\t".join(re.sub(r"\s", "", f) for f in line.split("\t"))
        for w, r in re.findall(r"([㐀-䶿一-鿿々]{2,})\(([ぁ-んァ-ヶ]+)\)", flat):
            if len(r) >= len(w):        # 「一羽（わ）」之类只注了一个字的读音，不是整词
                words.append((w, hira(r)))
        for w, r in re.findall(r"「([^「」]+)」は,「([ぁ-んァ-ヶ]+)」(?:とも|。)", flat):   # 「遺言」は，「イゴン」とも。
            if KANJI.match(w):
                alts.setdefault(w, []).append(r)
            elif re.search(r"[一-鿿]", w) and not re.search(r"[ぁ-んァ-ヶ]", w):
                words.append((w, hira(r)))
        for r in re.findall(r"(?<!は,)「([ぁ-んァ-ヶ]+)」とも。", flat):         # 十：「ジュッ」とも。
            if not re.match(r"[ァ-ヶ]", r) or len(r) <= 3:   # 跨行的「末子」「末弟」は「マッシ」「マッテイ」とも 不是这个字的
                alts.setdefault(cur, []).append(r)
    # 付表：「よみ 語」交替出现
    tail = " ".join(l for l in lines[end:] if "indd" not in l and not re.fullmatch(r"\s*\d*\s*\x0c?", l))
    tail = re.sub(r"\(\s*「[^」]*」とも言う。\s*\)", " ", tail)
    toks = tail.split()
    for a, b in itertools.pairwise(toks):
        if re.fullmatch(r"[ぁ-ん]+", a) and re.search(r"[一-鿿]", b):
            for w in FUHYO_SPLIT.get(b, [b]):
                words.append((w, a))
    return readings, alts, words


def parse_grades(path: Path) -> dict[str, int]:
    raw = path.read_text(encoding="utf-8")
    secs = re.split(r"=== (\d)年生（(\d+)字） ===", raw)
    out = {}
    for i in range(1, len(secs), 3):
        g, n = int(secs[i]), int(secs[i + 1])
        ks = re.findall(r"\[\[(.)\]\]", secs[i + 2].split("==")[0])
        assert len(ks) == n == GRADE_COUNTS[g], (g, n, len(ks))
        for k in ks:
            out[k] = g
    return out


def main() -> None:
    readings, alts, words = parse_joyo(Path(sys.argv[1]))
    grades = parse_grades(Path(sys.argv[2]))
    assert len(readings) == 2136, len(readings)
    n_on = sum(1 for rs in readings.values() for r in rs if re.match(r"[ァ-ヶ]", r))
    n_kun = sum(len(rs) for rs in readings.values()) - n_on
    assert (n_on, n_kun) == (2352, 2036), (n_on, n_kun)      # 常用漢字表：音 2352、訓 2036
    assert not set(grades) - set(readings), set(grades) - set(readings)
    assert all(readings.values())
    OUT.mkdir(parents=True, exist_ok=True)
    head = ("# kugiri: 常用漢字表（平成22年内閣告示第2号）2136字 + 学年別漢字配当表（平成29年文部科学省告示第63号）\n"
            "# 漢字<TAB>配当学年（1–6、7 = 中学以降）<TAB>音訓（音はカタカナ、訓はひらがな、「.」の後は送り仮名）"
            "<TAB>備考の別の読み（「ジュッ」とも 等）\n")
    rows = []
    assert not set(alts) - set(readings), set(alts) - set(readings)
    for k, rs in readings.items():
        g = grades.get(k, 7)
        row = f"\t{g}\t{' '.join(rs)}\t{' '.join(dict.fromkeys(alts.get(k, [])))}"
        rows.append(k + row)
        if k in ALIAS:
            rows.append(ALIAS[k] + row)
    (OUT / "kanji.tsv").write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    seen, wrows = set(), []
    for w, r in words + EXTRA_WORDS:
        if (w, r) not in seen:
            seen.add((w, r))
            wrows.append(f"{w}\t{r}")
    (OUT / "kanji_words.tsv").write_text(
        "# kugiri: 常用漢字表の付表（熟字訓・当て字）と本表備考の特別な読み（＋末尾に kugiri の補足）。語<TAB>読み（ひらがな）\n"
        + "\n".join(wrows) + "\n", encoding="utf-8")
    n_stem = sum(1 for rs in readings.values() for r in rs if "." in r)
    print(f"{len(readings)} 字（音 {n_on} / 訓 {n_kun}，其中有送假名 {n_stem}）、配当 {len(grades)} 字、"
          f"備考の別読み {sum(map(len, alts.values()))}、特別な語 {len(wrows)}")


if __name__ == "__main__":
    main()
