"""WebVTT（.vtt）。振假名用 ``<ruby>`` 标签，默认关闭：ffmpeg 系播放器会把读音直接接在汉字后面（M0 结论）。"""
from __future__ import annotations

import html
import re

from ..timeline import Document
from .common import clean_line, dedupe, make_cue, parse_ts, rendered_lines, split_blocks, timed_cue, ts

_RT = re.compile(r"<rt>.*?</rt>", re.S)
_VOICE = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>")
_TAG_LEAD = re.compile(r"(?:<[^>]*>)*\s")
_WORD_TS = re.compile(r"<((?:\d+:)?\d{1,2}:\d{1,2}\.\d{1,3})>")   # YouTube 自动字幕的词级时间 <00:00:01.234><c>…</c>


def _key(line: str) -> str:
    return clean_line(_RT.sub("", line))


def _word_end(t0: float, nxt: float, w: str) -> float:
    """词的结束时间：下一个词开始，但最多按每字 0.2 秒（至少 0.3 秒）——YouTube 自动字幕只给词的开始时间，
    停顿时上一个词会一直拖到下一个词，这样停顿才留得下来（分段要用）。"""
    return min(nxt, t0 + max(0.3, 0.2 * len(w.strip())))


def _piece(w: str) -> str:
    """去标签，保留一个前导空格（英文词之间的空格靠它，见 ``timed_cue``）。"""
    t = clean_line(w)
    return " " + t if t and _TAG_LEAD.match(w) else t


def _timed(start: float, end: float, lines: list[str], speaker: str | None):
    """有词级时间标签的 cue：标签之前的文字从 cue 开始算，每个词到下一个词开始（见 ``_word_end``）。"""
    words: list[tuple[float | None, str]] = []
    for i, x in enumerate(lines):
        parts = _WORD_TS.split(_RT.sub("", x))
        words.append((start if i == 0 else None, _piece(parts[0])))
        words += [(parse_ts(t), _piece(w)) for t, w in zip(parts[1::2], parts[2::2])]
    pieces = []
    for j, (t0, w) in enumerate(words):
        nxt = next((t for t, _ in words[j + 1:] if t is not None), end)
        pieces.append((t0, None if t0 is None else _word_end(t0, max(t0, nxt), w), w))
    return timed_cue(start, end, pieces, speaker)


def parse(text: str) -> Document:
    raw = []
    for rows in split_blocks(text):
        if not rows or rows[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")) and not any("-->" in r for r in rows):
            continue
        for i, r in enumerate(rows):
            if "-->" in r:
                a, z = r.split("-->", 1)
                raw.append((parse_ts(a), parse_ts(z.split()[0]), rows[i + 1:]))
                break
    cues = []
    for s, e, body in dedupe(raw, _key):
        speaker = None
        for x in body:
            v = _VOICE.search(x)
            if v:
                speaker = html.unescape(v.group(1)).strip()
                break
        if any(_WORD_TS.search(x) for x in body):
            c = _timed(s, e, body, speaker)
        else:
            c = make_cue(s, e, [_key(x) for x in body], speaker)
        if c:
            cues.append(c)
    cues.sort(key=lambda c: c.start)
    return Document(cues)


def dump(doc: Document, *, punct: str = "netflix", ruby: bool = False) -> str:
    rows = ["WEBVTT", ""]
    for c in doc.cues:
        lines = []
        for pieces in rendered_lines(c, punct, ruby):
            s = ""
            for t, r in pieces:
                t = html.escape(t, quote=False)
                s += f"<ruby>{t}<rt>{html.escape(r, quote=False)}</rt></ruby>" if r else t
            if c.speaker and not lines:
                s = f"<v {html.escape(c.speaker, quote=False)}>{s}"
            lines.append(s)
        if not lines:
            continue
        rows += [f"{ts(c.start, '.')} --> {ts(c.end, '.')}", *lines, ""]
    return "\n".join(rows)
