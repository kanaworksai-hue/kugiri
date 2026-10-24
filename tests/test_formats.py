"""输出格式规范：所有黄金输入 × 预设 × SRT / VTT / ASS（有无振假名）逐条检查公开写明的格式要求。

依据（2026-10-21 查）：
- YouTube 帮助「Supported subtitle and closed caption files」：SRT 必须是纯 UTF-8，不识别样式标签。
- W3C WebVTT：UTF-8（可有 BOM，我们不写）、首行 ``WEBVTT``、时间戳 ``(hh:)mm:ss.ttt``（毫秒正好 3 位）、
  ``-->`` 两边有空格、结束 > 开始、开始时间不递减、正文不含 ``-->`` 和空行、``&`` ``<`` 要写成字符引用、
  ``<v>`` 必须有说话人名（名字里不能有裸 ``&`` ``>``）、``<ruby>``/``<rt>`` 不带注释。
- SubRip 惯例：从 1 连续编号、``HH:MM:SS,mmm --> HH:MM:SS,mmm``、空行分隔。
- ASS v4.00+（libass 文档）：段落顺序 Script Info → V4+ Styles → Events（Events 最后）、``ScriptType: v4.00+``、
  PlayResX/Y、Style 23 个字段、Dialogue 10 个字段（只有最后的 Text 能有逗号）、时间 ``H:MM:SS.cc``、
  正文里的 ``{`` 是覆盖标签开头、``\\N`` 是换行。
Premiere / DaVinci 的公开文档只写了「能导入 SRT（UTF-8）」，已包含在上面；DaVinci 不支持 ASS。
独立解析器读回、libass / Chrome 渲染检查在开发用的评测脚本里（需要 ffmpeg、Chrome，不放进 pytest）。
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

from kugiri.cli import main
from kugiri.reflow import PRESETS, preset

IN = Path(__file__).parent / "golden" / "input"
INPUTS = ["kinsoku.srt", "numbers.srt", "userdict.srt", "spoken.vtt", "stress.vtt"]
VARIANTS = [("srt", "none"), ("vtt", "none"), ("vtt", "all"), ("ass", "none"), ("ass", "all")]
CASES = [(i, p, f, r) for i in INPUTS for p in PRESETS for f, r in VARIANTS]


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    d = tmp_path_factory.mktemp("fmt")
    res = {}
    for inp, pr, fmt, ruby in CASES:
        out = d / f"{Path(inp).stem}.{pr}.{ruby}.{fmt}"
        args = ["reflow", str(IN / inp), "--preset", pr, "--ruby", ruby, "-o", str(out)]
        if inp == "userdict.srt":
            args += ["--dict", str(IN / "userdict.tsv")]
        assert main(args) == 0
        res[(inp, pr, fmt, ruby)] = out.read_bytes()
    return res


def _text(raw: bytes) -> str:
    assert not raw.startswith(b"\xef\xbb\xbf"), "不要写 BOM"
    s = raw.decode("utf-8")                     # 纯 UTF-8（YouTube / Premiere）
    assert "\r" not in s, "换行统一用 LF"
    assert s.endswith("\n")
    return s


SRT_TS = r"(\d{2}):(\d{2}):(\d{2}),(\d{3})"
VTT_TS = r"(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})"


def _sec(m: tuple) -> float:
    h, mi, s, ms = m
    assert int(mi) < 60 and int(s) < 60
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000


def _check_times(times: list[tuple[float, float]]) -> None:
    assert times, "没有字幕"
    for (a, b), (c, _) in zip(times, times[1:] + [(float("inf"), 0)]):
        assert a < b, f"结束时间要大于开始时间：{a} {b}"
        assert a <= c, "开始时间要不递减"
        assert b <= c + 1e-9, "字幕不重叠"


@pytest.mark.parametrize("inp,pr,fmt,ruby", [c for c in CASES if c[2] == "srt"])
def test_srt(outputs, inp, pr, fmt, ruby):
    s = _text(outputs[(inp, pr, fmt, ruby)])
    blocks = s.rstrip("\n").split("\n\n")
    times = []
    for n, b in enumerate(blocks, 1):
        rows = b.split("\n")
        assert rows[0] == str(n), "从 1 连续编号"
        m = re.fullmatch(rf"{SRT_TS} --> {SRT_TS}", rows[1])
        assert m, rows[1]
        times.append((_sec(m.groups()[:4]), _sec(m.groups()[4:])))
        text = rows[2:]
        assert 1 <= len(text) <= preset(pr).max_lines
        for ln in text:
            assert ln.strip(), "不能有空行"
            # 播放器会把 <…> 当标签、{…} 当 ASS 覆盖标签、\N 当换行（YouTube 也不认样式）
            assert not re.search(r"[<>{}\\]", ln), ln
    _check_times(times)


ALLOWED_TAG = re.compile(r"<v [^>]+>|</?ruby>|</?rt>")


@pytest.mark.parametrize("inp,pr,fmt,ruby", [c for c in CASES if c[2] == "vtt"])
def test_vtt(outputs, inp, pr, fmt, ruby):
    s = _text(outputs[(inp, pr, fmt, ruby)])
    head, *blocks = s.rstrip("\n").split("\n\n")
    assert head == "WEBVTT"
    times = []
    for b in blocks:
        rows = b.split("\n")
        m = re.fullmatch(rf"{VTT_TS} --> {VTT_TS}", rows[0])
        assert m, rows[0]
        times.append((_sec(m.groups()[:4]), _sec(m.groups()[4:])))
        text = rows[1:]
        assert 1 <= len(text) <= preset(pr).max_lines
        for k, ln in enumerate(text):
            assert ln.strip() and "-->" not in ln
            for v in re.findall(r"<v ([^>]*)>", ln):
                assert k == 0 and html.unescape(v).strip(), "说话人名不能为空，只放在第一行"
                assert not re.search(r"&(?!amp;|lt;|gt;)", v), f"说话人名里的 & 要转义：{v}"
            bare = ALLOWED_TAG.sub("", ln)
            assert "<" not in bare and ">" not in bare, f"< > 要转义：{ln}"
            assert not re.search(r"&(?!amp;|lt;|gt;|nbsp;|lrm;|rlm;)", bare), f"& 要转义：{ln}"
            if ruby == "none":
                assert "<ruby>" not in ln
            assert ln.count("<ruby>") == ln.count("</ruby>") == ln.count("<rt>") == ln.count("</rt>")
    _check_times(times)


ASS_TS = r"\d:\d{2}:\d{2}\.\d{2}"


def _ass_sec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


@pytest.mark.parametrize("inp,pr,fmt,ruby", [c for c in CASES if c[2] == "ass"])
def test_ass(outputs, inp, pr, fmt, ruby):
    s = _text(outputs[(inp, pr, fmt, ruby)])
    sections = re.findall(r"^\[([^\]]+)\]$", s, re.M)
    assert sections == ["Script Info", "V4+ Styles", "Events"]
    info = dict(re.findall(r"^(\w+): (.*)$", s.split("[V4+ Styles]")[0], re.M))
    assert info["ScriptType"] == "v4.00+"
    W, H = (1080, 1920) if pr == "vertical" else (1920, 1080)
    assert (int(info["PlayResX"]), int(info["PlayResY"])) == (W, H)
    styles = s.split("[V4+ Styles]")[1].split("[Events]")[0]
    fmt_line = re.search(r"^Format: (.*)$", styles, re.M).group(1).split(", ")
    assert len(fmt_line) == 23
    for st in re.findall(r"^Style: (.*)$", styles, re.M):
        assert len(st.split(",")) == 23, st
    events = s.split("[Events]")[1]
    ev_fmt = re.search(r"^Format: (.*)$", events, re.M).group(1).split(", ")
    assert ev_fmt == ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]
    names = set()
    for d in re.findall(r"^Dialogue: (.*)$", events, re.M):
        f = d.split(",", 9)
        assert len(f) == 10
        assert re.fullmatch(ASS_TS, f[1]) and re.fullmatch(ASS_TS, f[2]), (f[1], f[2])
        assert _ass_sec(f[1]) < _ass_sec(f[2])
        assert f[3] in ("Main", "Ruby")
        assert all(x.isdigit() for x in f[5:8]) and f[0].isdigit()
        names.add(f[4])
        body = re.sub(r"\{\\[^}]*\}", "", f[9])           # 去掉我们自己写的覆盖标签
        assert "{" not in body and "}" not in body, f"正文里的花括号会被当成覆盖标签：{f[9]}"
        assert "\\" not in body.replace("\\N", ""), f"正文里不能有别的反斜杠序列：{f[9]}"
    if inp == "stress.vtt":
        assert names == {"田中， 太郎", "R&D"}           # Name 字段里的逗号换成全角，不挤错字段
