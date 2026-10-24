"""时间轴文档（kugiri-timeline v1）：cue / 字级时间 / 读音 / 置信度 / 振假名。

所有命令之间传递的中间格式；M2 的对齐器输出同一格式（填 ``units``）。JSON 结构::

    {
      "format": "kugiri-timeline", "version": 1, "language": "ja", "fps": 30.0,
      "cues": [
        {
          "start": 1.0, "end": 3.2,                 # 秒，文件内绝对时间
          "text": "東京の夜は静かです",               # 原文（未渲染句读点）
          "lines": ["東京の夜は", "静かです"],         # 可省略；有时 "".join(lines) == text
          "units": [                                 # 可省略；字/词级时间，cs/ce 是 text 的字符下标 [cs, ce)
            {"cs": 0, "ce": 2, "start": 1.0, "end": 1.4, "reading": "トウキョウ", "conf": 0.93}
          ],
          "ruby": [{"cs": 0, "ce": 2, "text": "とうきょう"}],   # 可省略；振假名
          "speaker": null,
          "flags": ["low_confidence"]                # 可省略；质检标记
        }
      ],
      "meta": {"align": {...}}                       # 可省略；生成信息 / 质检报告
    }

JSON Schema 见 ``schema/timeline.schema.json``。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = "kugiri-timeline"
VERSION = 1


@dataclass
class Unit:
    cs: int
    ce: int
    start: float
    end: float
    reading: str | None = None
    conf: float | None = None


@dataclass
class Ruby:
    cs: int
    ce: int
    text: str


@dataclass
class Cue:
    start: float
    end: float
    text: str
    lines: list[str] | None = None
    units: list[Unit] = field(default_factory=list)
    ruby: list[Ruby] = field(default_factory=list)
    speaker: str | None = None
    flags: list[str] = field(default_factory=list)   # 质检标记（对齐置信度低等），可省略

    def line_spans(self) -> list[tuple[int, int]]:
        """每行在 text 里的 [a, b)。没有 lines 时整条一行。"""
        if not self.lines:
            return [(0, len(self.text))]
        out, pos = [], 0
        for ln in self.lines:
            out.append((pos, pos + len(ln)))
            pos += len(ln)
        return out


@dataclass
class Document:
    cues: list[Cue] = field(default_factory=list)
    language: str = "ja"
    fps: float | None = None
    meta: dict | None = None      # 生成信息（对齐模型、质检报告等），可省略

    # ------------------------------------------------------------ JSON
    def to_dict(self) -> dict:
        def cue(c: Cue) -> dict:
            d: dict = {"start": round(c.start, 3), "end": round(c.end, 3), "text": c.text}
            if c.lines:
                d["lines"] = c.lines
            if c.units:
                d["units"] = [{k: v for k, v in (("cs", u.cs), ("ce", u.ce), ("start", round(u.start, 3)),
                                                 ("end", round(u.end, 3)), ("reading", u.reading),
                                                 ("conf", u.conf)) if v is not None} for u in c.units]
            if c.ruby:
                d["ruby"] = [{"cs": r.cs, "ce": r.ce, "text": r.text} for r in c.ruby]
            if c.speaker is not None:
                d["speaker"] = c.speaker
            if c.flags:
                d["flags"] = list(c.flags)
            return d

        out: dict = {"format": FORMAT, "version": VERSION, "language": self.language}
        if self.fps:
            out["fps"] = self.fps
        if self.meta:
            out["meta"] = self.meta
        out["cues"] = [cue(c) for c in self.cues]
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        if d.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} file (format = {d.get('format')!r})")
        if d.get("version") != VERSION:
            raise ValueError(f"unsupported version {d.get('version')!r} (supported: {VERSION})")
        cues = []
        for i, c in enumerate(d.get("cues", [])):
            cue = Cue(float(c["start"]), float(c["end"]), c["text"], c.get("lines"),
                      [Unit(**u) for u in c.get("units", [])], [Ruby(**r) for r in c.get("ruby", [])],
                      c.get("speaker"), list(c.get("flags", [])))
            validate_cue(cue, i)
            cues.append(cue)
        return cls(cues, d.get("language", "ja"), d.get("fps"), d.get("meta"))

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n"

    @classmethod
    def load(cls, path: str | Path) -> "Document":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_cue(c: Cue, i: int = 0) -> None:
    n = len(c.text)
    if c.end < c.start:
        raise ValueError(f"cue {i}: end < start")
    if c.lines is not None and "".join(c.lines) != c.text:
        raise ValueError(f"cue {i}: lines joined do not equal text")
    for u in c.units:
        if not (0 <= u.cs <= u.ce <= n):
            raise ValueError(f"cue {i}: unit index out of range {u.cs}-{u.ce}")
    for r in c.ruby:
        if not (0 <= r.cs < r.ce <= n):
            raise ValueError(f"cue {i}: ruby index out of range {r.cs}-{r.ce}")
