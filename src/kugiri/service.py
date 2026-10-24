"""CLI / 网页 / MCP 共用的处理流程：同样的输入和参数一定出同样的字幕（三个入口只负责收参数和交付结果）。

- ``Options``：断行 / 输出 / 对齐的参数（CLI 的选项一一对应）。
- ``Engine``：持有模型。``keep=True``（网页、MCP）对齐模型和识别模型常驻，第二个文件起不用再加载；
  ``keep=False``（CLI，一次一个文件）识别模型用完就释放，对齐时峰值内存小。
- ``Engine.align`` 音频 (+ 台本) → 断行后的文档；``Engine.transcribe`` 只出识别稿。
- ``reflow_doc`` 已有字幕重新断行；``render`` 文档 → SRT / VTT / ASS / JSON 文本。
进度回调统一是 ``progress(stage, fraction)``，stage ∈ ``STAGES``。
"""
from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import formats
from .reflow import PRESETS, preset, reflow
from .timeline import Document
from .userdict import UserDict

ASR_MODELS = ("qwen3-1.7b", "qwen3-0.6b", "omni")
RUBY_MODES = ("none", "all", "hard", "user")
RUBY_GRADES = (1, 2, 3, 4, 5, 6)
STAGES = ("load", "transcribe", "align", "reflow")
Progress = Callable[[str, float], None]

Line = tuple[str, "str | None"]


@dataclass
class Options:
    preset: str = "youtube"
    max_width: float | None = None
    max_lines: int | None = None
    fps: float | None = None
    punct: str | None = None
    ruby: str = "none"
    ruby_grade: int | None = None      # 只对 ruby="hard"：按小学几年级的学习范围算难读字（省略 = 常用漢字表）
    ruby_once: bool = False            # 同一个词只在第一次出现时标振假名
    font: str = "Noto Sans JP"
    font_size: int | None = None
    font_file: str | None = None
    # 只有 align 用
    asr_model: str = "qwen3-1.7b"
    asr_batch: int = 16
    spell: str = "auto"
    speakers: bool = False
    raw: bool = False
    vad: bool = True
    fill: float | None = None
    start_shift: float | None = None

    def __post_init__(self) -> None:
        if self.preset not in PRESETS:
            raise ValueError(f"unknown preset {self.preset!r} (choose from {', '.join(PRESETS)})")
        if self.ruby not in RUBY_MODES:
            raise ValueError(f"unknown furigana mode {self.ruby!r} (choose from {', '.join(RUBY_MODES)})")
        if self.ruby_grade is not None:
            if self.ruby_grade not in RUBY_GRADES:
                raise ValueError(f"school grade must be 1-6 (got {self.ruby_grade})")
            if self.ruby != "hard":
                raise ValueError("the school grade (ruby_grade / --ruby-grade) only works with furigana mode hard")
        if self.asr_model not in ASR_MODELS:
            raise ValueError(f"unknown recognition model {self.asr_model!r} (choose from {', '.join(ASR_MODELS)})")
        for name, v in (("max_width", self.max_width), ("max_lines", self.max_lines), ("fps", self.fps),
                        ("font_size", self.font_size)):
            if v is not None and not v > 0:
                raise ValueError(f"{name} must be greater than 0 (got {v})")
        if self.max_width is not None and self.max_width < 4:
            raise ValueError(f"max_width must be at least 4 characters (got {self.max_width})")
        if self.max_lines is not None and self.max_lines > 4:
            raise ValueError(f"max_lines must be 1-4 (got {self.max_lines})")
        if self.asr_batch < 1:
            raise ValueError(f"--asr-batch must be at least 1 (got {self.asr_batch})")

    def params(self):
        return preset(self.preset, max_width=self.max_width, max_lines=self.max_lines, fps=self.fps, punct=self.punct)

    def timing(self):
        from .align.aligner import Timing
        tm = Timing(vad=self.vad)
        if self.fill is not None:
            tm.fill = self.fill
        if self.start_shift is not None:
            tm.start_shift = self.start_shift
        return tm


def presets() -> dict[str, dict]:
    out = {}
    for name in PRESETS:
        p = asdict(preset(name))
        p.pop("kind_cost")
        out[name] = p
    return out


def install_hint(extra: str) -> str:
    """缺可选依赖时告诉用户装什么（pip / uv 两种写法）。"""
    return (f"install kugiri with it, e.g. uv tool install 'kugiri[{extra}]' or pip install 'kugiri[{extra}]' "
            "('kugiri[all]' installs everything)")


def read_text(path: str | Path, what: str) -> str:
    """读用户给的 UTF-8 文本（台本、词典）；读不了时报错里带文件名。"""
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path}: the {what} must be UTF-8 text ({e.reason} at byte {e.start})") from e
    except FileNotFoundError as e:
        raise ValueError(f"{what} not found: {path}") from e


def load_dict(path: str | Path | None) -> UserDict | None:
    return UserDict.load(path) if path else None


def read_script(text: str, speakers: bool = False) -> list[Line]:
    from .align.pipeline import read_script as rs
    lines = rs(text, speakers)
    if not lines:
        raise ValueError("the script is empty")
    return lines


def script_text(lines: list[Line]) -> str:
    """台本行 → 文本（一句一行，说话人写成「名前：」），``--speakers`` 能原样读回。"""
    return "".join((f"{s}：" if s else "") + t + "\n" for t, s in lines)


def reflow_doc(doc: Document, opt: Options, udict: UserDict | None = None, *, mode: str = "resegment",
               norm: bool = True, timing: bool | None = None, hints: dict | None = None) -> Document:
    """``hints``：agent 标的断点 ``{"key", "sentence": [号…], "keep": [号…]}``（号来自 ``break_candidates``）。"""
    lab = None
    if hints is not None:
        from . import hints as hm
        if not isinstance(hints, dict) or not hints.get("key"):
            raise ValueError('hints must be {"key": ..., "sentence": [numbers], "keep": [numbers]} (key from break_candidates)')
        view = hm.candidates(doc, opt.params(), mode=mode, udict=udict, norm=norm)
        lab = hm.labels(view, hints.get("sentence") or [], hints.get("keep") or [], hints["key"])
    return reflow(doc, opt.params(), mode=mode, udict=udict, norm=norm, timing=timing, hints=lab)


def break_candidates(doc: Document, opt: Options, udict: UserDict | None = None, *, mode: str = "resegment",
                     norm: bool = True):
    """带编号的候选断点（``hints.View``），给 agent 按意思标句界。"""
    from .hints import candidates
    return candidates(doc, opt.params(), mode=mode, udict=udict, norm=norm)


def finish_align(doc: Document, opt: Options, udict: UserDict | None = None) -> Document:
    """对齐结果（台本一行一条 cue）→ 断行。``opt.raw`` 时原样返回。"""
    from .align import quality
    if opt.raw:
        return doc
    p = opt.params()
    out = reflow(doc, p, mode="resegment", udict=udict, norm=False)
    out.meta = doc.meta
    dur = (doc.meta or {}).get("align", {}).get("audio_s")
    for c in out.cues if dur else []:          # linger 不让最后一条拖到音频结尾之后
        c.end = min(c.end, max(dur, c.start + 1 / p.fps))
    quality.flag_cues(out.cues, (doc.meta or {}).get("align", {}).get("warnings", []))
    return out


def add_ruby(doc: Document, opt: Options, udict: UserDict | None = None) -> Document:
    """按 ``opt.ruby`` 给每条加振假名（副本；``none`` 时原样返回）。``ruby_once`` 按 cue 的时间顺序数第一次出现。"""
    if opt.ruby == "none":
        return doc
    from .reading import ruby_doc
    doc = copy.deepcopy(doc)
    order = sorted(range(len(doc.cues)), key=lambda i: (doc.cues[i].start, i))
    spans = ruby_doc([doc.cues[i].text for i in order], udict, opt.ruby, grade=opt.ruby_grade, once=opt.ruby_once)
    for i, r in zip(order, spans):
        doc.cues[i].ruby = r
    return doc


def render(doc: Document, fmt: str, opt: Options, udict: UserDict | None = None) -> str:
    """文档 → 输出文本。不改 ``doc``（振假名加在副本上）。"""
    if fmt not in formats.FORMATS:
        raise ValueError(f"unsupported output format {fmt!r} (choose from {', '.join(formats.FORMATS)})")
    p = opt.params()
    doc = add_ruby(doc, opt, udict)
    play_res = (1080, 1920) if opt.preset == "vertical" else (1920, 1080)
    return formats.dumps(doc, fmt, punct=p.punct, ruby=opt.ruby != "none", play_res=play_res, font=opt.font,
                         font_size=opt.font_size, font_file=opt.font_file, max_width=p.max_width)


def summary(doc: Document, out: Document | None = None) -> dict:
    """质检摘要（MCP / 网页用）：``doc`` 是对齐结果（带 ``meta.align``），``out`` 是断行后的字幕（cue 数、
    被标记的 cue 都按它数；省略时用 ``doc``）。"""
    info = (doc.meta or {}).get("align", {})
    warns = info.get("warnings", [])
    cues = (out or doc).cues
    return {"cues": len(cues), "audio_s": info.get("audio_s"), "wall_s": info.get("wall_s"),
            "device": info.get("device"), "mode": info.get("mode"),
            "flagged_cues": sum("low_confidence" in c.flags or "unaligned" in c.flags for c in cues),
            "warnings": [{"start": w["start"], "end": w["end"], "reason": w["reason"], "text": w.get("text", "")}
                         for w in warns]}


def _pipeline():
    """对齐 / 识别的模块（可选依赖 [align]：torch + numpy）。没装时给能读的错误。"""
    try:
        from .align import pipeline
    except ImportError as e:
        raise ValueError(f"alignment needs the [align] extra (and [asr] to transcribe without a script): "
                         f"{install_hint('all')} ({e})") from e
    return pipeline


class Engine:
    """持有模型；同一个 Engine 同一时间只跑一个任务（``lock``）。"""

    def __init__(self, device: str = "auto", *, threads: int | None = None, quiet: bool = True, keep: bool = True):
        self.device_req, self.threads, self.quiet, self.keep = device, threads, quiet, keep
        self._al = None
        self._asr = None           # 常驻的 QwenASR（keep=True 时；换模型时释放旧的）
        self.lock = threading.Lock()

    @property
    def device(self) -> str | None:
        return self._al.device if self._al else None

    def aligner(self):
        from .align.aligner import Aligner
        if self._al is None:
            self._al = Aligner(self.device_req, threads=self.threads, quiet=self.quiet)
        return self._al

    def _recognizer(self, name: str):
        if not self.keep or name == "omni":
            return None
        if self._asr is not None and self._asr.name != name:
            self._asr.close()
            self._asr = None
        if self._asr is None:
            from .align.asr import QwenASR
            self._asr = QwenASR(name, self.aligner().device, quiet=self.quiet)
        return self._asr

    def warm(self, asr_model: str | None = None) -> None:
        """预先加载模型（常驻模式启动时调用，第一个任务就不用等加载）。"""
        al = self.aligner()
        _ = al.model
        if asr_model and asr_model != "omni":
            self._recognizer(asr_model)

    @staticmethod
    def _audio(audio):
        if isinstance(audio, (str, Path)):
            from .align.audio import load_audio
            return load_audio(audio)
        return audio

    def align(self, audio, script: str | list[Line] | None, opt: Options, udict: UserDict | None = None, *,
              progress: Progress | None = None, on_script: Callable[[list[Line]], None] | None = None
              ) -> tuple[Document, Document]:
        """音频 (+ 台本) → (对齐结果（台本一行一条 cue，带字级 units）, 断行后的文档)。
        ``script``：台本文本、已经切好的行，或 None（先识别）。"""
        pipeline = _pipeline()
        lines = read_script(script, opt.speakers) if isinstance(script, str) else script
        if lines is not None and on_script:
            on_script(lines)
        prog = progress or (lambda s, x: None)
        prog("load", 0.0)
        audio = self._audio(audio)
        try:
            al = self.aligner()
            rec = self._recognizer(opt.asr_model) if lines is None else None
            prog("load", 1.0)
            al.progress = progress
            if lines is not None:
                raw = pipeline.align_script(al, audio, lines, udict=udict, spell=opt.spell, timing=opt.timing())
            else:
                raw = pipeline.transcribe(al, audio, model=opt.asr_model, timing=opt.timing(), udict=udict,
                                          batch=opt.asr_batch, recognizer=rec, on_script=on_script,
                                          progress=(lambda x: progress("transcribe", x)) if progress else None)
        except RuntimeError as e:      # torch 的错误（设备不可用、内存不够、模型文件坏了等）
            raise ValueError(f"the model failed: {e}") from e
        finally:
            if self._al is not None:
                self._al.progress = None
        prog("reflow", 0.0)
        out = finish_align(raw, opt, udict)
        prog("reflow", 1.0)
        return raw, out

    def transcribe(self, audio, opt: Options, *, progress: Progress | None = None) -> tuple[list[Line], dict]:
        """只识别：→ (一句一行的台本, 信息)。``omni`` 模型直接贪心解码（没有标点）。"""
        pipeline = _pipeline()
        prog = progress or (lambda s, x: None)
        prog("load", 0.0)
        audio = self._audio(audio)
        t0 = time.time()
        try:
            al = self.aligner()
            if opt.asr_model == "omni":
                prog("load", 1.0)
                al.progress = progress
                res = al.transcribe(audio)
                lines = pipeline.read_script("\n".join(t for t in res.text.split("。")))
                info = {"asr": {"model": "omni"}}
            else:
                rec = self._recognizer(opt.asr_model)
                prog("load", 1.0)
                lines, info = pipeline.recognize(al, audio, model=opt.asr_model, batch=opt.asr_batch, recognizer=rec,
                                                 progress=(lambda x: progress("transcribe", x)) if progress else None)
        except RuntimeError as e:
            raise ValueError(f"the model failed: {e}") from e
        finally:
            if self._al is not None:
                self._al.progress = None
        info["wall_s"] = round(time.time() - t0, 2)
        info["audio_s"] = round(len(audio) / 16000, 2)
        return lines, info
