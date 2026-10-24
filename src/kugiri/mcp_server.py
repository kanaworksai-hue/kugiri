"""MCP server ``kugiri mcp``（官方 Python SDK，stdio）：给 AI agent 用的字幕工具。

工具：``align``（音频 + 可选台本 → 字幕文件）、``transcribe``（只出识别稿）、``job_status``（查后台任务）、
``reflow``（已有字幕重新断行，可带 agent 标的句界）、``break_candidates``（带编号的候选断点，见 ``hints``）、
``reading``（读音）、``presets``（预设参数）。
处理走 ``service`` / ``jobs``（和 CLI、网页同一套代码）；模型第一次用到时加载、之后常驻，同一时间只跑一个任务。
长任务：默认等到完成，期间发 MCP progress 通知；``wait=false`` 立刻返回 job_id，再用 ``job_status`` 查。
输入输出都是本机文件路径；返回结构化结果（输出路径、cue 数、警告列表）。
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import __version__, formats, hints, service
from .jobs import Job, Runner

INSTRUCTIONS = """kugiri makes Japanese subtitles with accurate timing and natural line breaks, on this machine.
Use absolute file paths (relative paths resolve against the server's working directory); `~` is expanded.

- align: audio/video file (+ optional script: one paragraph per line) → subtitle files (SRT / VTT / ASS /
  JSON), by default `<name>.kugiri.srt` next to the audio (an explicit `output` path is overwritten).
  Without a script it transcribes first (Qwen3-ASR, with punctuation) and also writes the transcript
  (`<output name>.script.txt`). Returns output
  paths, cue count and a quality report: `warnings` lists time ranges where the script and the audio
  seem to disagree (missing / extra words, crosstalk) — check those.
- transcribe: speech → text only (one sentence per line, written to a .txt). Fix it, then call align with
  `script` set to that file for the best subtitles.
- reflow: re-segment and re-wrap an existing SRT / VTT / ASS / kugiri JSON / WhisperX JSON file (no audio
  needed). Also the way to fix subtitles made by other tools (Vrew, CapCut, Premiere, YouTube auto-captions…).
- break_candidates → reflow with hints: you can improve the line breaks with your own reading of the text.
  Spoken Japanese often has no punctuation, so the rules alone cannot see where sentences end.
  break_candidates lists the allowed break points with numbers; pass the numbers of the sentence ends (and any
  break that would split a unit) to reflow as `sentence` / `keep` with the returned `key`. For audio, run align
  with output `.json` first and use that JSON as the reflow input (it keeps the word timings).
- reading: kana reading of Japanese text (to check how a user dictionary changes it).
- presets: line width, lines per cue, reading speed and duration limits of each preset
  (youtube = landscape 16 chars/line, vertical = Shorts/TikTok 10 chars/line, netflix = 13 chars/line).

Long files: align/transcribe wait until done (about 0.1-0.2x real time on Apple Silicon after the models
are loaded) and send progress notifications. The very first call downloads the models once (alignment 1.3 GB;
speech recognition without a script 4.1 GB, or 1.6 GB with asr_model qwen3-0.6b), which can take several
minutes; the progress message shows the download. If your client times
out on long calls, pass wait=false and poll job_status. Only one job runs at a time; others queue.
A job keeps running (and writes its files) even if the waiting call is cancelled — check job_status."""

mcp = MCPServer("kugiri", instructions=INSTRUCTIONS, version=__version__, log_level="WARNING")
_runner: Runner | None = None

Preset = Annotated[Literal["youtube", "vertical", "netflix"],
                   Field(description="youtube (landscape, default) / vertical (Shorts, TikTok) / netflix")]
Ruby = Annotated[Literal["none", "all", "hard", "user"],
                 Field(description="Furigana (ASS and VTT): none / all kanji words / hard = only words that are hard "
                                   "to read (kanji or readings outside the Jōyō kanji list, plus user-dictionary "
                                   "words) / user = only user-dictionary words")]
RubyGrade = Annotated[int | None, Field(ge=1, le=6, description="With ruby=hard: also treat kanji not yet learned by "
                                                                "this elementary-school grade (1-6) as hard, for "
                                                                "children's content. Omit for the Jōyō list.")]
RubyOnce = Annotated[bool, Field(description="Furigana only on the first occurrence of each word (Netflix style).")]
AsrModel = Annotated[Literal["qwen3-1.7b", "qwen3-0.6b", "omni"],
                     Field(description="Speech recognition model when there is no script: qwen3-1.7b (default, "
                                       "punctuated) / qwen3-0.6b (faster, less memory) / omni (no punctuation)")]
Fmt = Literal["srt", "vtt", "ass", "json"]


def runner() -> Runner:
    global _runner
    if _runner is None:
        _runner = Runner(service.Engine(os.environ.get("KUGIRI_DEVICE", "auto"), keep=True))
    return _runner


def _path(p: str | None, *, must_exist: bool = True, what: str = "file") -> Path | None:
    if p is None or not str(p).strip():
        return None
    q = Path(p).expanduser()
    if not q.is_absolute():
        q = Path.cwd() / q
    if must_exist and not q.exists():
        raise ValueError(f"No such {what}: {p} (relative paths resolve against the server's working directory "
                         f"{os.getcwd()}; pass an absolute path)")
    return q


def _tool(fn=None, *, description: str | None = None):
    """注册工具；错误变成 agent 能读懂的一行 ToolError。``description`` 省略时用 docstring。"""
    if fn is None:
        return functools.partial(_tool, description=description)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, OSError, KeyError) as e:
            raise ToolError(str(e)) from e
    return mcp.tool(description=description)(wrapper)


async def _wait(job: Job, ctx: Context | None) -> None:
    """等任务结束，期间按 0–100 发 progress 通知（客户端没要求时 SDK 自己忽略）。"""
    last = None
    while not job.done.is_set():
        st = runner().status(job)
        dl = st.get("download") or (runner().download() if job.state == "queued" else None)
        cur = (round(job.frac * 100, 1), job.stage, dl and dl["done"] // 50_000_000)
        if ctx is not None and cur != last:
            msg = f"{job.stage} {job.stage_frac * 100:.0f}%" if job.state == "running" and job.stage else job.state
            if job.state == "queued":
                msg = f"queued ({runner().position(job)} ahead)"
            if dl:
                msg = (f"downloading the {dl['name']} (first run only): {dl['done'] / 1e9:.1f}"
                       + (f" / {dl['total'] / 1e9:.1f} GB" if dl["total"] else " GB"))
            try:
                await ctx.report_progress(cur[0], 100, msg)
            except Exception:       # 通知发不出去（客户端断开等）不影响任务
                ctx = None
            last = cur
        await anyio.sleep(0.5)


def _result(job: Job, raise_error: bool = False) -> dict[str, Any]:
    if raise_error and job.state in ("error", "cancelled"):
        raise ToolError(f"Job {job.id} failed: {job.error}")
    d: dict[str, Any] = runner().status(job)
    if job.state == "done":
        d.update(job.meta.get("result", {}))
    return d


def _write_align(job: Job, out_path: Path, extra: list[str], script_path: Path | None) -> None:
    opt, udict = job.opt, job.udict
    fmt0 = formats.detect(out_path)
    outputs = {fmt0: str(out_path)}
    for f in extra:
        if f not in outputs:
            outputs[f] = str(out_path.with_suffix("." + f))
    for f, p in outputs.items():
        Path(p).write_text(service.render(job.out, f, opt, udict), encoding="utf-8")
    res: dict[str, Any] = {"outputs": outputs}
    if script_path is not None and job.lines:
        script_path.write_text(service.script_text(job.lines), encoding="utf-8")
        res["script"] = str(script_path)
    s = service.summary(job.raw, job.out)
    s["warnings_total"] = len(s["warnings"])
    s["warnings"] = s["warnings"][:50]
    res.update(s)
    job.meta["result"] = res


@_tool
async def align(
    audio: Annotated[str, Field(description="Audio or video file (absolute path). WAV is read directly; "
                                            "other formats need ffmpeg.")],
    script: Annotated[str | None, Field(description="Script text file (UTF-8, one paragraph per line). "
                                                    "Omit to transcribe the audio first.")] = None,
    script_text: Annotated[str | None, Field(description="Script given inline instead of a file.")] = None,
    output: Annotated[str | None, Field(description="Main output file; its extension (.srt/.vtt/.ass/.json) "
                                                    "picks the format. Default: <audio name>.kugiri.srt next "
                                                    "to the audio (never your own <name>.srt). An explicit path is "
                                                    "overwritten.")] = None,
    also: Annotated[list[Fmt], Field(description="Extra formats written next to `output` with the same name, "
                                                 "e.g. [\"vtt\", \"ass\"].")] = [],   # noqa: B006
    preset: Preset = "youtube",
    ruby: Ruby = "none",
    ruby_grade: RubyGrade = None,
    ruby_once: RubyOnce = False,
    asr_model: AsrModel = "qwen3-1.7b",
    speakers: Annotated[bool, Field(description="Script lines starting with 「名前：」 or `>> 名前` set the "
                                                "speaker.")] = False,
    user_dict: Annotated[str | None, Field(description="User dictionary TSV: surface<TAB>reading<TAB>no-split(1/0)."
                                      )] = None,
    wait: Annotated[bool, Field(description="Wait until done (default). false: return a job_id at once and "
                                            "poll job_status.")] = True,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Audio/video (+ optional script) → Japanese subtitle files with accurate timing and line breaks.
    Returns output paths, cue count and the quality report (time ranges where script and audio disagree)."""
    a = _path(audio)
    opt = service.Options(preset=preset, ruby=ruby, ruby_grade=ruby_grade, ruby_once=ruby_once, asr_model=asr_model,
                          speakers=speakers)
    if script and script_text:
        raise ValueError("Give either script (a file) or script_text, not both")
    text = _path(script).read_text(encoding="utf-8-sig") if script else script_text
    lines = service.read_script(text, speakers) if text is not None else None
    out = _path(output, must_exist=False) if output else a.with_name(a.stem + ".kugiri.srt")
    formats.detect(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    script_out = out.with_name(out.stem + ".script.txt") if lines is None else None
    udict = service.load_dict(_path(user_dict)) if user_dict else None
    job = Job(kind="align", audio=str(a), opt=opt, script=lines, udict=udict, name=a.name,
              after=lambda j: _write_align(j, out, list(also), script_out))
    runner().submit(job)
    if not wait:
        return _result(job)
    await _wait(job, ctx)
    return _result(job, raise_error=True)


@_tool
async def transcribe(
    audio: Annotated[str, Field(description="Audio or video file (absolute path).")],
    output: Annotated[str | None, Field(description="Text file to write (one sentence per line). Default: "
                                                    "<audio name>.kugiri.script.txt next to the audio.")] = None,
    asr_model: AsrModel = "qwen3-1.7b",
    wait: Annotated[bool, Field(description="Wait until done (default); false returns a job_id.")] = True,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Speech → Japanese text only (punctuated, one sentence per line), written to a .txt file. Edit it and pass
    it to align as `script` for the best subtitles."""
    a = _path(audio)
    out = _path(output, must_exist=False) if output else a.with_name(a.stem + ".kugiri.script.txt")
    out.parent.mkdir(parents=True, exist_ok=True)

    def after(j: Job) -> None:
        text = service.script_text(j.lines)
        out.write_text(text, encoding="utf-8")
        j.meta["result"] = {"script": str(out), "lines": len(j.lines), "audio_s": j.info.get("audio_s"),
                            "wall_s": j.info.get("wall_s"), "model": j.info.get("asr", {}).get("model"),
                            "text": text if len(text) <= 4000 else text[:4000] + "…（truncated; read the file）"}

    job = Job(kind="transcribe", audio=str(a), opt=service.Options(asr_model=asr_model), name=a.name, after=after)
    runner().submit(job)
    if not wait:
        return _result(job)
    await _wait(job, ctx)
    return _result(job, raise_error=True)


@_tool
async def job_status(job_id: Annotated[str, Field(description="job_id returned by align / transcribe")]
                     ) -> dict[str, Any]:
    """State of a background align / transcribe job: queued / running (stage, progress 0-1) / done (with the
    same result align / transcribe return) / error."""
    job = runner().get(job_id)
    if job is None:
        raise ValueError(f"No job {job_id} (jobs are kept only while this server runs)")
    return _result(job)


@_tool
async def reflow(
    input: Annotated[str, Field(description="Existing subtitles (absolute path): .srt / .vtt / .ass / kugiri .json, "
                                                "or WhisperX / Whisper .json. Files from other tools (Vrew, CapCut, "
                                                "Premiere, DaVinci Resolve, Subtitle Edit, YouTube auto-captions) work "
                                                "as they are.")],
    output: Annotated[str | None, Field(description="Output file; extension picks the format. Default: "
                                                    "<input name>.kugiri.<ext> next to the input (.srt for "
                                                    "Whisper .json input).")] = None,
    preset: Preset = "youtube",
    mode: Annotated[Literal["resegment", "wrap"],
                    Field(description="resegment (default): join neighbouring cues and cut them again; wrap: keep "
                                      "every cue and its timing, only re-wrap lines")] = "resegment",
    ruby: Ruby = "none",
    ruby_grade: RubyGrade = None,
    ruby_once: RubyOnce = False,
    user_dict: Annotated[str | None, Field(description="User dictionary TSV.")] = None,
    hints_key: Annotated[str | None, Field(description="`key` from break_candidates (same input, preset, mode and "
                                                       "user_dict). Required with sentence / keep.")] = None,
    sentence: Annotated[list[int], Field(description="break_candidates numbers where a sentence / utterance ends "
                                                     "(list every one in the file).")] = [],   # noqa: B006
    keep: Annotated[list[int], Field(description="break_candidates numbers that must not be broken.")] = [],  # noqa: B006
) -> dict[str, Any]:
    """Re-segment and re-wrap existing Japanese subtitles (kinsoku rules, numbers kept whole, timing rules).
    Use it to turn subtitles from other tools (Vrew, CapCut, Premiere, DaVinci Resolve, Subtitle Edit, WhisperX,
    YouTube auto-captions) into properly broken Japanese subtitles. No audio or model needed.
    For better breaks in unpunctuated speech, call break_candidates first and pass hints_key + sentence (+ keep)."""
    src = _path(input)
    opt = service.Options(preset=preset, ruby=ruby, ruby_grade=ruby_grade, ruby_once=ruby_once)
    udict = service.load_dict(_path(user_dict)) if user_dict else None
    if (sentence or keep) and not hints_key:
        raise ValueError("sentence / keep need hints_key (the key returned by break_candidates)")
    hints = {"key": hints_key, "sentence": sentence, "keep": keep} if hints_key else None

    def work() -> dict[str, Any]:
        doc = formats.read(src)
        if output:
            out = _path(output, must_exist=False)
        else:
            ext = ".srt" if formats.detect(src) == "json" and not formats.is_timeline(src) else src.suffix
            ext = ".ass" if ext.lower() == ".ssa" else ext
            out = src.with_name(src.stem + ".kugiri" + ext)
        fmt = formats.detect(out)
        res = service.reflow_doc(doc, opt, udict, mode=mode, hints=hints)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(service.render(res, fmt, opt, udict), encoding="utf-8")
        d = {"output": str(out), "cues_in": len(doc.cues), "cues": len(res.cues)}
        if hints:
            d["hints"] = {"sentence": len(set(sentence)), "keep": len(set(keep))}
        return d
    return await anyio.to_thread.run_sync(work)


@_tool(description="Numbered break points of a subtitle file, for you to mark sentence ends by meaning before "
                   "calling reflow. Returns `text` (format below), `key` (pass it to reflow as hints_key), and "
                   "`pages` (call again with page=1, 2… for long files).\n\n" + hints.GUIDE)
async def break_candidates(
    input: Annotated[str, Field(description="Subtitle file (absolute path), same as for reflow. For audio, run align "
                                            "with a .json output first and pass that file.")],
    preset: Preset = "youtube",
    mode: Annotated[Literal["resegment", "wrap"], Field(description="Same mode you will pass to reflow.")] = "resegment",
    user_dict: Annotated[str | None, Field(description="User dictionary TSV (same as for reflow).")] = None,
    page: Annotated[int, Field(ge=0, description="Page number (long files are split into pages of about "
                                                 f"{hints.PAGE_CHARS} characters).")] = 0,
) -> dict[str, Any]:
    src = _path(input)
    opt = service.Options(preset=preset)
    udict = service.load_dict(_path(user_dict)) if user_dict else None

    def work() -> dict[str, Any]:
        view = service.break_candidates(formats.read(src), opt, udict, mode=mode)
        d = view.page(page)
        d["numbers"] = len(view.ids)
        d["next"] = (f"note the sentence ends on this page, then call break_candidates with page={page + 1}"
                     if page + 1 < d["pages"] else
                     "call reflow with hints_key=key and sentence=[…] (keep=[…] if any) — the numbers from all pages")
        return d
    return await anyio.to_thread.run_sync(work)



@_tool
async def reading(
    text: Annotated[str, Field(description="Japanese text")],
    user_dict: Annotated[str | None, Field(description="User dictionary TSV (optional).")] = None,
    pron: Annotated[bool, Field(description="Pronunciation form (は→ワ, long vowels as ー) instead of "
                                            "the reading form.")] = False,
) -> dict[str, Any]:
    """Katakana reading of Japanese text, with per-word tokens (pyopenjtalk-plus + user dictionary). `hard` marks
    words that ruby=hard would give furigana (kanji or reading outside the Jōyō kanji list, or a user-dictionary
    word with a reading)."""
    from .reading import is_hard, tokens
    from .reading import reading as rd
    udict = service.load_dict(_path(user_dict)) if user_dict else None
    return {"text": text, "reading": rd(text, udict, pron=pron),
            "tokens": [{"surface": t.surface, "reading": t.read, "pron": t.pron, "user": t.user,
                        "hard": t.user or is_hard(t.surface, t.read)}
                       for t in tokens(text, udict)]}


@_tool
async def presets() -> dict[str, Any]:
    """Presets and their parameters (max_width = full-width chars per line, max_lines, cps = reading speed,
    min/max duration in seconds, fps)."""
    return service.presets()


def run() -> None:
    mcp.run("stdio")
