"""SubRip（.srt）。"""
from __future__ import annotations

from ..timeline import Document
from .common import clean_line, dedupe, make_cue, parse_ts, plain_lines, split_blocks, ts


def parse(text: str) -> Document:
    raw = []
    for rows in split_blocks(text):
        for i, r in enumerate(rows):
            if "-->" in r:
                a, z = r.split("-->", 1)
                raw.append((parse_ts(a), parse_ts(z.split()[0]), [clean_line(x) for x in rows[i + 1:]]))
                break
    cues = [c for s, e, lines in dedupe(raw) if (c := make_cue(s, e, lines))]
    cues.sort(key=lambda c: c.start)
    return Document(cues)


# 多数播放器（ffmpeg / libass 系的 mpv、VLC，以及 pysubs2）把 SRT 里的 <…> 当 HTML 标签、{…} 当 ASS 覆盖标签、
# \N 当换行，文字会消失或乱换行（用 ffmpeg 读回时发现）。SRT 没有转义写法，换成全角字符。
_SRT_SAFE = str.maketrans({"<": "＜", ">": "＞", "{": "｛", "}": "｝", "\\": "＼"})


def dump(doc: Document, *, punct: str = "netflix") -> str:
    rows = []
    n = 0
    for c in doc.cues:
        lines = [x.translate(_SRT_SAFE) for x in plain_lines(c, punct)]
        if not lines:
            continue
        n += 1
        rows += [str(n), f"{ts(c.start, ',')} --> {ts(c.end, ',')}", *lines, ""]
    return "\n".join(rows)
