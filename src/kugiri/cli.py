"""命令行 ``kugiri``。

    kugiri align audio.wav --script script.txt -o out.srt   # 音频 + 台本 → 字幕（omniASR CTC 对齐 + 断行）
    kugiri align audio.wav -o out.srt --save-script s.txt  # 没有台本：Qwen3-ASR 识别 → 对齐 → 断行（识别稿另存）
    kugiri reflow in.srt --preset youtube -o out.srt     # 重新断行（不做音频对齐）
    kugiri reflow in.srt --show-breaks                   # 带编号的候选断点 → 标句界 → --hints h.json
    kugiri reading "東京の夜は静かです"                    # 读音（调试用户词典）
    kugiri presets                                        # 列出预设参数
    kugiri web                                            # 本地网页界面
    kugiri mcp                                            # MCP server（stdio）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, formats, service
from .reflow import PRESETS
from .textutil import PUNCT_STYLES


def _opts(a: argparse.Namespace, **kw) -> service.Options:
    return service.Options(preset=a.preset, max_width=a.max_width, max_lines=a.max_lines, fps=a.fps, punct=a.punct,
                           ruby=a.ruby, ruby_grade=a.ruby_grade, ruby_once=a.ruby_once, font=a.font, font_size=a.font_size, font_file=a.font_file, **kw)


def _check_output(a: argparse.Namespace) -> None:
    """长时间处理之前先查输出位置和字体文件，免得对齐跑完才报错。"""
    if a.output:
        parent = Path(a.output).resolve().parent
        if not parent.is_dir():
            raise ValueError(f"output folder does not exist: {parent}")
        if Path(a.output).is_dir():
            raise ValueError(f"{a.output} is a folder; give a file name such as {Path(a.output) / 'out.srt'}")
    if a.font_file and not Path(a.font_file).is_file():
        raise ValueError(f"font file not found: {a.font_file}")


def _write(out, a: argparse.Namespace, opt: service.Options, udict, out_fmt: str, n_in: int) -> None:
    if opt.ruby != "none" and out_fmt == "srt":
        print("Note: SRT cannot show furigana, so --ruby is ignored (use .ass or .vtt output)", file=sys.stderr)
    text = service.render(out, out_fmt, opt, udict)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"{_n(n_in)} → {_n(len(out.cues))}: {a.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def _n(k: int) -> str:
    return f"{k} cue" + ("" if k == 1 else "s")


def _read_json(path: str, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ValueError(f"{path}: not a valid {what} JSON file ({e})") from e


def _reflow(a: argparse.Namespace) -> int:
    in_fmt = a.input_format or formats.detect(a.input)
    opt = _opts(a)
    udict = service.load_dict(a.dict)
    _check_output(a)
    doc = formats.read(a.input, in_fmt)
    norm = not a.no_normalize
    if a.show_breaks:
        view = service.break_candidates(doc, opt, udict, mode=a.mode, norm=norm)
        text = f"key: {view.key}\n{view.text()}\n"
        if a.output:
            Path(a.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    out_fmt = a.format or (formats.detect(a.output) if a.output else in_fmt)
    hints = _read_json(a.hints, "hints") if a.hints else None
    out = service.reflow_doc(doc, opt, udict, mode=a.mode, norm=norm, timing=a.timing, hints=hints)
    _write(out, a, opt, udict, out_fmt, len(doc.cues))
    return 0


def _align(a: argparse.Namespace) -> int:
    out_fmt = a.format or (formats.detect(a.output) if a.output else "json")
    opt = _opts(a, asr_model=a.asr_model, asr_batch=a.asr_batch, spell=a.spell, speakers=a.speakers, raw=a.raw,
                vad=not a.no_vad, fill=a.fill, start_shift=a.start_shift)
    udict = service.load_dict(a.dict)
    _check_output(a)
    script = service.read_text(a.script, "script") if a.script else None

    def save(ls) -> None:
        if a.save_script:
            Path(a.save_script).write_text(service.script_text(ls), encoding="utf-8")

    eng = service.Engine(a.device, threads=a.threads, quiet=a.quiet, keep=False)
    raw, out = eng.align(a.audio, script, opt, udict, on_script=save)
    info = raw.meta["align"]
    warns = info["warnings"]
    if not a.quiet:
        print(f"Aligned {info['audio_s']:.0f} s of audio in {info['wall_s']:.0f} s ({eng.device}); "
              f"{len(warns)} place(s) where script and audio may disagree", file=sys.stderr)
        for w in warns[:20]:
            print(f"  {_ts(w['start'])}–{_ts(w['end'])} [{w['reason']}] {w['text'][:40]}", file=sys.stderr)
        if len(warns) > 20:
            print(f"  … ({len(warns)} in total; the full list is in meta.align.warnings of the JSON output)", file=sys.stderr)
    _write(out, a, opt, udict, out_fmt, len(raw.cues))
    return 0


def _ts(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m // 60)}:{int(m % 60):02d}:{s:05.2f}"


def _reading(a: argparse.Namespace) -> int:
    from .reading import is_hard, reading, tokens
    udict = service.load_dict(a.dict)
    if a.tokens:
        for t in tokens(a.text, udict):
            tags = ["user"] * t.user + ["hard"] * (t.user or is_hard(t.surface, t.read))   # 和 --ruby hard 一样
            print(f"{t.surface}\t{t.read}\t{t.pron}" + "".join(f"\t({x})" for x in tags))
    else:
        print(reading(a.text, udict, pron=a.pron))
    return 0


def _presets(a: argparse.Namespace) -> int:
    for name, p in service.presets().items():
        print(f"[{name}]")
        for k, v in p.items():
            print(f"  {k} = {v}")
    return 0


def _web(a: argparse.Namespace) -> int:
    try:
        from . import web
    except ImportError as e:
        raise ValueError(f"the Web UI needs the [web] extra: {service.install_hint('web')} ({e})") from e
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Note: listening on {a.host}; other devices on the network can open it (there is no login)", file=sys.stderr)
    web.run(a.host, a.port, device=a.device, warm=None if a.warm == "none" else a.warm, open_browser=not a.no_open,
            root=a.data_dir)
    return 0


def _mcp(a: argparse.Namespace) -> int:
    try:
        from . import mcp_server
    except ImportError as e:
        raise ValueError(f"the MCP server needs the [mcp] extra: {service.install_hint('mcp')} ({e})") from e
    mcp_server.run()
    return 0


def _positive(kind):
    def conv(v: str):
        x = kind(v)
        if x <= 0:
            raise argparse.ArgumentTypeError(f"must be greater than 0 (got {v})")
        return x
    return conv


def _output_args(r: argparse.ArgumentParser, fmt_default: str) -> None:
    r.add_argument("-o", "--output", help="output file (the extension picks the format); stdout if omitted")
    r.add_argument("--format", choices=formats.FORMATS, help="output format" + fmt_default)
    r.add_argument("--preset", default="youtube", choices=list(PRESETS), help="preset (default: youtube)")
    r.add_argument("--max-width", type=_positive(float), help="max characters per line (full-width = 1, half-width = 0.5)")
    r.add_argument("--max-lines", type=_positive(int), help="max lines per cue")
    r.add_argument("--fps", type=_positive(float), help="frame rate (frame snapping, gaps in frames)")
    r.add_argument("--punct", choices=PUNCT_STYLES, help="punctuation: netflix (、→ half-width space, 。→ full-width space) / keep")
    r.add_argument("--dict", help="user dictionary TSV (surface / reading / no-split)")
    r.add_argument("--ruby", default="none", choices=service.RUBY_MODES,
                   help="furigana: none (default) / all (every kanji word) / hard (only hard words: kanji or readings "
                        "outside the Joyo list, plus dictionary words with a reading) / user (dictionary words only). "
                        "ASS: positioned lines, VTT: <ruby>, SRT: not supported")
    r.add_argument("--ruby-grade", type=int, choices=service.RUBY_GRADES, metavar="N",
                   help="with --ruby hard: kanji not yet learned by elementary-school grade N (1-6) also count as hard (for children)")
    r.add_argument("--ruby-once", action="store_true", help="furigana only the first time a word appears (Netflix style)")
    r.add_argument("--font", default="Noto Sans JP", help="ASS font name")
    r.add_argument("--font-size", type=_positive(int), help="ASS font size (default: from the frame size and characters per line)")
    r.add_argument("--font-file", help="font file used to position ASS furigana (needs fonttools); default: Noto Sans JP metrics")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kugiri", description="Japanese subtitle timing: alignment, line breaks, readings, SRT / VTT / ASS")
    ap.add_argument("--version", action="version", version=f"kugiri {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    r = sub.add_parser("reflow", help="re-break subtitles that already have timings (no audio needed)",
                       description="Re-break existing subtitles (kugiri's own or from other tools) with the Japanese "
                                   "line-break rules; timings come from the input cues. No audio and no models needed.")
    r.add_argument("input", help="input subtitles: .srt / .vtt / .ass / .json (kugiri-timeline or WhisperX / Whisper JSON); "
                                 "files from other tools (Vrew, CapCut, Premiere, DaVinci, Subtitle Edit, YouTube auto-captions) work as they are")
    r.add_argument("--input-format", choices=("srt", "vtt", "ass", "json"), help="input format (default: from the extension)")
    r.add_argument("--mode", default="resegment", choices=("resegment", "wrap"),
                   help="resegment: join neighbouring cues and cut them again (default); wrap: keep every cue and its timing, only re-wrap")
    r.add_argument("--timing", action=argparse.BooleanOptionalAction, default=None,
                   help="apply the timing rules (min/max duration, 2-frame gap, frame snapping); default: on for resegment, off for wrap")
    r.add_argument("--no-normalize", action="store_true", help="do not normalise the text (full/half width, ellipses, ...)")
    r.add_argument("--show-breaks", action="store_true",
                   help="only list the numbered break points (to mark sentence ends by meaning), no subtitles")
    r.add_argument("--hints", help='sentence marks JSON: {"key": ..., "sentence": [numbers], "keep": [numbers]} '
                                   "(numbers and key from --show-breaks, run with the same options)")
    _output_args(r, " (default: from -o, else same as the input)")
    r.set_defaults(func=_reflow)

    al = sub.add_parser("align", help="audio + script (optional) -> character timings -> subtitles",
                        description="Forced alignment of the whole file with omniASR CTC 300M, then line breaking. "
                                    "The first run downloads the alignment model (1.3 GB) to ~/.cache/kugiri/models "
                                    "(KUGIRI_MODEL_DIR to change); without a script also Qwen3-ASR (1.7B: 4.1 GB, "
                                    "0.6B: 1.6 GB) into the Hugging Face cache (HF_HOME).")
    al.add_argument("audio", help="audio / video file (WAV is read directly, other formats need ffmpeg)")
    al.add_argument("--script", help="script, UTF-8 text, one paragraph per line; transcribed first if omitted (see --asr-model)")
    al.add_argument("--asr-model", default="qwen3-1.7b", choices=("qwen3-1.7b", "qwen3-0.6b", "omni"),
                    help="speech recognition without a script: qwen3-1.7b (default, with punctuation, needs [asr]) / "
                         "qwen3-0.6b (faster, less memory, a few more errors) / omni (the alignment model's own greedy "
                         "transcript: no punctuation, many errors)")
    al.add_argument("--asr-batch", type=_positive(int), default=16, help="chunks decoded at once during recognition (default 16; lower it on small GPUs)")
    al.add_argument("--save-script", help="save the script (transcript or --script, one sentence per line); fix it and re-run with --script")
    al.add_argument("--speakers", action="store_true", help="treat a leading 「名前：」 / 「>> 名前」 in script lines as the speaker")
    al.add_argument("--raw", action="store_true", help="no line breaking: one cue per script line (to inspect the alignment or reflow yourself)")
    al.add_argument("--spell", default="auto", choices=("auto", "oov"),
                    help="words aligned through their reading: auto (numbers, Latin letters, characters outside the model's "
                         "vocabulary, dictionary words with a reading; default) / oov (only characters outside the vocabulary)")
    al.add_argument("--device", default="auto", help="auto (default: mps -> cuda -> cpu) / cpu / mps / cuda")
    al.add_argument("--threads", type=int, help="CPU threads")
    al.add_argument("--no-vad", action="store_true", help="do not correct boundaries next to pauses with the audio envelope")
    al.add_argument("--fill", type=float, help="how far character ends inside a phrase may be extended, in seconds (default 0.2)")
    al.add_argument("--start-shift", type=float, help="shift all start times by this many seconds (default -0.04)")
    al.add_argument("-q", "--quiet", action="store_true", help="no progress or quality summary")
    _output_args(al, " (default: from -o, else json)")
    al.set_defaults(func=_align)

    g = sub.add_parser("reading", help="show the kana reading (pyopenjtalk-plus + user dictionary)")
    g.add_argument("text", help="Japanese text")
    g.add_argument("--dict", help="user dictionary TSV")
    g.add_argument("--pron", action="store_true", help="pronunciation form (は→ワ, long vowels → ー); default: reading form")
    g.add_argument("--tokens", action="store_true", help="one word per line")
    g.set_defaults(func=_reading)

    s = sub.add_parser("presets", help="list the preset parameters")
    s.set_defaults(func=_presets)

    w = sub.add_parser("web", help="local Web UI (opens localhost in the browser)",
                       description="Start the local Web UI (needs the [web] extra). Models are loaded at start-up and stay "
                                   "in memory; one job runs at a time. The first start downloads the models.")
    w.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this machine only, 127.0.0.1)")
    w.add_argument("--port", type=int, default=7790, help="port (default 7790)")
    w.add_argument("--device", default="auto", help="auto / cpu / mps / cuda")
    w.add_argument("--warm", default="qwen3-1.7b", choices=("qwen3-1.7b", "qwen3-0.6b", "omni", "none"),
                   help="recognition model loaded at start-up (default qwen3-1.7b; none = load with the first job)")
    w.add_argument("--no-open", action="store_true", help="do not open the browser")
    w.add_argument("--data-dir", help="folder for uploads and the user dictionary (default: KUGIRI_HOME or ~/.cache/kugiri/web)")
    w.set_defaults(func=_web)

    m = sub.add_parser("mcp", help="MCP server for AI agents (stdio)",
                       description="MCP server (stdio). Tools: align / transcribe / job_status / reflow / break_candidates / "
                                   "reading / presets. Needs the [mcp] extra.")
    m.set_defaults(func=_mcp)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help(sys.stderr)
        return 2
    try:
        return a.func(a)
    except KeyboardInterrupt:
        print("\nkugiri: interrupted (a model download continues where it stopped next time)", file=sys.stderr)
        return 130
    except (ValueError, OSError) as e:
        print(f"kugiri: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
