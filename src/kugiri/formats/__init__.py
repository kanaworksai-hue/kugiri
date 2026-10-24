"""字幕文件读写：SRT / WebVTT / ASS / kugiri-timeline JSON。"""
from __future__ import annotations

from pathlib import Path

from ..timeline import Document
from .common import decode
from . import ass, srt, vtt, whisper

FORMATS = ("srt", "vtt", "ass", "json")


def detect(path: str | Path) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    if ext in FORMATS:
        return ext
    if ext == "ssa":
        return "ass"
    if Path(path).is_dir():
        raise ValueError(f"{path} is a folder, not a subtitle file")
    raise ValueError(f"unknown subtitle file extension {Path(path).suffix or '(none)'!r}: "
                     f"use .srt, .vtt, .ass or .json")


def loads(text: str, fmt: str) -> Document:
    if fmt == "srt":
        return srt.parse(text)
    if fmt == "vtt":
        return vtt.parse(text)
    if fmt == "ass":
        return ass.parse(text)
    if fmt == "json":
        import json
        d = json.loads(text)
        if whisper.is_whisper(d) and not (isinstance(d, dict) and d.get("format") == "kugiri-timeline"):
            return whisper.parse(d)
        if not isinstance(d, dict):
            raise ValueError("not a kugiri timeline or Whisper / WhisperX JSON")
        try:
            return Document.from_dict(d)
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError(f"broken kugiri timeline JSON ({type(e).__name__}: {e})") from e
    raise ValueError(f"cannot read {fmt} (inputs: srt / vtt / ass / json)")


def read(path: str | Path, fmt: str | None = None) -> Document:
    """读字幕文件。JSON 可以是 kugiri-timeline，也可以是 WhisperX / Whisper 系的识别结果（见 ``whisper``）。
    读不出一条字幕时报错（空文件、纯文本改了扩展名），错误信息带文件名。"""
    fmt = fmt or detect(path)
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}") from None
    try:
        doc = loads(decode(data), fmt)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    if not doc.cues:
        raise ValueError(f"{path}: no subtitles found (check that it is a valid .{fmt} file)")
    return doc


def dumps(doc: Document, fmt: str, *, punct: str = "netflix", ruby: bool = False, **ass_opts) -> str:
    if fmt == "srt":
        return srt.dump(doc, punct=punct)
    if fmt == "vtt":
        return vtt.dump(doc, punct=punct, ruby=ruby)
    if fmt == "ass":
        return ass.dump(doc, punct=punct, ruby=ruby, **ass_opts)
    if fmt == "json":
        return doc.dumps()
    raise ValueError(f"unsupported output format {fmt!r}")


def is_timeline(path: str | Path) -> bool:
    """JSON 文件是不是 kugiri-timeline（不是的话多半是 Whisper 系的识别结果）。"""
    import json
    try:
        d = json.loads(decode(Path(path).read_bytes()))
    except ValueError:
        return False
    return isinstance(d, dict) and d.get("format") == "kugiri-timeline"
