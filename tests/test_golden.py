"""黄金文件测试：tests/golden/input 的自编字幕 → kugiri reflow → 和 tests/golden/expected 逐字比较。

规则或参数改动导致输出变化时，确认新输出没问题后重新生成：
    KUGIRI_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from kugiri.cli import main

GOLDEN = Path(__file__).parent / "golden"
IN, EXP = GOLDEN / "input", GOLDEN / "expected"
DICT = str(IN / "userdict.tsv")

CASES = [
    # (输出文件名, 输入, 参数)
    ("kinsoku.netflix.srt", "kinsoku.srt", ["--preset", "netflix"]),
    ("kinsoku.youtube.srt", "kinsoku.srt", ["--preset", "youtube"]),
    ("kinsoku.vertical.srt", "kinsoku.srt", ["--preset", "vertical"]),
    ("kinsoku.netflix-keep.srt", "kinsoku.srt", ["--preset", "netflix", "--punct", "keep"]),
    ("kinsoku.wrap.srt", "kinsoku.srt", ["--preset", "netflix", "--mode", "wrap"]),
    ("numbers.netflix.srt", "numbers.srt", ["--preset", "netflix"]),
    ("numbers.vertical.vtt", "numbers.srt", ["--preset", "vertical"]),
    ("userdict.youtube.srt", "userdict.srt", ["--preset", "youtube", "--dict", DICT]),
    ("userdict.vertical.srt", "userdict.srt", ["--preset", "vertical", "--dict", DICT]),
    ("userdict.netflix-ruby.ass", "userdict.srt", ["--preset", "netflix", "--dict", DICT, "--ruby", "all"]),
    ("userdict.youtube-ruby.vtt", "userdict.srt", ["--preset", "youtube", "--dict", DICT, "--ruby", "user"]),
    ("spoken.youtube.vtt", "spoken.vtt", ["--preset", "youtube"]),
    ("spoken.youtube.ass", "spoken.vtt", ["--preset", "youtube"]),
    ("spoken.youtube.json", "spoken.vtt", ["--preset", "youtube", "--ruby", "all"]),
    # 振假名只标难读字（常用漢字表外 / 学年 / 只标第一次）
    ("furigana.netflix-hard.ass", "furigana.srt", ["--preset", "netflix", "--ruby", "hard", "--ruby-once"]),
    ("furigana.youtube-grade3.vtt", "furigana.srt", ["--preset", "youtube", "--ruby", "hard", "--ruby-grade", "3"]),
    ("furigana.youtube-all-once.vtt", "furigana.srt", ["--preset", "youtube", "--ruby", "all", "--ruby-once"]),
    # 别家工具的字幕（自编文字，按各工具的输出特征做的，见 test_foreign.py）
    ("longline.youtube.srt", "longline.srt", ["--preset", "youtube"]),
    ("longline.vertical.srt", "longline.srt", ["--preset", "vertical"]),
    ("fragments.youtube.srt", "fragments.srt", ["--preset", "youtube"]),
    ("wordspaced.youtube.srt", "wordspaced.sjis.srt", ["--preset", "youtube"]),
    ("youtube_auto.youtube.srt", "youtube_auto.vtt", ["--preset", "youtube"]),
    ("youtube_auto.netflix.vtt", "youtube_auto.vtt", ["--preset", "netflix"]),
    ("whisperx.youtube.vtt", "whisperx.json", ["--preset", "youtube"]),
    ("highlight.youtube.srt", "highlight.srt", ["--preset", "youtube"]),
    ("conventions.youtube.srt", "conventions.srt", ["--preset", "youtube"]),
    ("aegisub.youtube.ass", "aegisub.ass", ["--preset", "youtube"]),
]


@pytest.mark.parametrize("out_name,src,args", CASES, ids=[c[0] for c in CASES])
def test_golden(out_name, src, args, tmp_path):
    out = tmp_path / out_name
    assert main(["reflow", str(IN / src), "-o", str(out), *args]) == 0
    got = out.read_text(encoding="utf-8")
    exp = EXP / out_name
    if os.environ.get("KUGIRI_UPDATE_GOLDEN"):
        exp.write_text(got, encoding="utf-8")
    assert exp.exists(), f"缺少黄金文件 {exp.name}，用 KUGIRI_UPDATE_GOLDEN=1 生成"
    assert got == exp.read_text(encoding="utf-8")
