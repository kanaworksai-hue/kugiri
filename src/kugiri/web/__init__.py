"""本地网页界面 ``kugiri web``（Starlette + uvicorn，只监听本机）。

拖入视频 / 音频（台本可选）→ 排队 → 识别 → 对齐 → 断行 → 结果页播放视频叠加字幕、逐条改字、重新对齐 / 重新断行、
质检跳转、下载 SRT / VTT / ASS / JSON / 台本。处理都走 ``service``（和 CLI、MCP 同一套代码，同样的输入出同样的字幕）。

数据目录（上传的媒体、台本）：``KUGIRI_HOME``，默认 ``~/.cache/kugiri/web``；7 天前的任务启动时清掉。
用户词典：``<数据目录>/dict.tsv``（网页里编辑）。
"""
from __future__ import annotations

import copy
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__, formats, service
from ..jobs import Job, Runner
from ..formats.common import rendered_lines
from ..textutil import normalize
from ..timeline import Cue, Document
from ..userdict import UserDict

STATIC = Path(__file__).parent / "static"
KEEP_DAYS = 7
_ID = re.compile(r"^[0-9a-f]{12}$")
# 上传的媒体只按这些扩展名存和回传（别的一律 .bin + octet-stream，免得 .html / .svg 在本站同源下被浏览器执行）
MEDIA_EXT = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".mts", ".ts", ".wav", ".mp3", ".m4a", ".aac", ".flac",
             ".ogg", ".oga", ".opus", ".aif", ".aiff", ".wma"}
DL_TYPES = {"srt": "application/x-subrip", "vtt": "text/vtt", "ass": "text/x-ssa", "json": "application/json",
            "txt": "text/plain"}


def home() -> Path:
    d = os.environ.get("KUGIRI_HOME")
    return Path(d).expanduser() if d else Path.home() / ".cache" / "kugiri" / "web"


class App:
    def __init__(self, runner: Runner, root: Path):
        self.runner, self.root = runner, root
        self._lock = threading.Lock()      # job.out / job.opt / job.udict / meta["src"] 一起读写（重新断行 vs 下载）
        (root / "jobs").mkdir(parents=True, exist_ok=True)
        self._cleanup()

    @property
    def dict_path(self) -> Path:
        return self.root / "dict.tsv"

    def _cleanup(self) -> None:
        cut = time.time() - KEEP_DAYS * 86400
        for d in (self.root / "jobs").iterdir():
            if d.is_dir() and d.stat().st_mtime < cut:
                shutil.rmtree(d, ignore_errors=True)

    def udict(self) -> UserDict | None:
        p = self.dict_path
        return UserDict.load(p) if p.exists() and p.read_text(encoding="utf-8-sig").strip() else None

    def job(self, req: Request) -> Job:
        jid = req.path_params["id"]
        job = self.runner.get(jid) if _ID.match(jid) else None
        if job is None or "media" not in job.meta:
            raise _NotFound(f"job {jid} not found (jobs are lost when the server restarts)")
        return job

    # ------------------------------------------------------------ 序列化
    def view(self, job: Job) -> tuple[Document | None, service.Options, UserDict | None]:
        with self._lock:
            return job.out, job.opt, job.udict

    def payload(self, job: Job) -> dict:
        d = self.runner.status(job)
        out, opt, udict = self.view(job)
        # 重新对齐的任务用同一个媒体文件：URL 指向最早上传它的任务，前端换任务时不用重新加载视频
        d.update(media=f"/api/jobs/{job.meta.get('media_job', job.id)}/media", media_name=job.meta.get("media_name", ""),
                 parent=job.meta.get("parent"), options=_opts_dict(opt), has_script=job.script is not None)
        if job.state == "done" and out is not None:
            d["cues"] = [_cue(c, opt) for c in service.add_ruby(out, opt, udict).cues]
            d["summary"] = service.summary(job.raw or out, out)
            d["script"] = service.script_text(job.lines) if job.lines else ""
        elif job.lines:
            d["script"] = service.script_text(job.lines)
        return d

    # ------------------------------------------------------------ 路由
    async def config(self, req: Request) -> Response:
        eng = self.runner.engine
        return JSONResponse({
            "version": __version__, "presets": service.presets(), "asr_models": list(service.ASR_MODELS),
            "ruby_modes": list(service.RUBY_MODES), "ruby_grades": list(service.RUBY_GRADES), "formats": [*formats.FORMATS, "txt"],
            "device": eng.device, "warming": self.runner.warming, "warm_error": self.runner.warm_error,
            "download": self.runner.download(),
            "busy": self.runner.busy(), "asr_loaded": getattr(eng._asr, "name", None),
            "jobs": [self.runner.status(j) for j in sorted(self.runner.jobs.values(), key=lambda j: -j.seq)
                     if "media" in j.meta][:20]})

    async def create(self, req: Request) -> Response:
        form = await req.form(max_files=2, max_fields=20, max_part_size=32 << 20)
        media = form.get("media")
        if media is None or isinstance(media, str) or not media.filename:
            return _err("no video or audio file was chosen")
        opt = _options(form)
        script = (form.get("script") or "").strip() or None
        sfile = form.get("script_file")
        if script is None and sfile is not None and not isinstance(sfile, str) and sfile.filename:
            script = (await sfile.read()).decode("utf-8-sig").strip() or None
        lines = service.read_script(script, opt.speakers) if script else None
        jid = uuid.uuid4().hex[:12]
        d = self.root / "jobs" / jid
        d.mkdir(parents=True)
        name = Path(media.filename).name or "media"
        ext = Path(name).suffix.lower()
        dst = d / ("media" + (ext if ext in MEDIA_EXT else ".bin"))
        try:
            with open(dst, "wb") as f:
                await run_in_threadpool(shutil.copyfileobj, media.file, f, 1 << 20)
        except BaseException:                   # 上传中断 / 磁盘满：不留半个文件
            shutil.rmtree(d, ignore_errors=True)
            raise
        if dst.stat().st_size == 0:
            shutil.rmtree(d, ignore_errors=True)
            return _err("the uploaded file is empty")
        job = Job(kind="align", audio=str(dst), opt=opt, script=lines, udict=self.udict(), name=name, id=jid,
                  meta={"media": str(dst), "media_name": name, "media_job": jid})
        self.runner.submit(job)
        return JSONResponse(self.payload(job))

    async def get(self, req: Request) -> Response:
        return JSONResponse(self.payload(self.job(req)))

    async def cancel(self, req: Request) -> Response:
        job = self.job(req)
        self.runner.cancel(job)
        return JSONResponse(self.payload(job))

    async def media(self, req: Request) -> Response:
        job = self.job(req)
        path = job.meta["media"]
        mt = mimetypes.guess_type(path)[0] if Path(path).suffix in MEDIA_EXT else None
        return FileResponse(path, media_type=mt or "application/octet-stream",
                            headers={"X-Content-Type-Options": "nosniff"})

    async def realign(self, req: Request) -> Response:
        """改过的字幕（或台本文本）当台本，同一个媒体重新对齐 → 新任务。"""
        job = self.job(req)
        body = await req.json()
        opt = _options(body.get("options") or {}, base=job.opt)
        if "script" in body:
            lines = service.read_script(str(body["script"]), opt.speakers)
        else:
            lines = [(normalize(str(c.get("text", "")).replace("\n", "")), c.get("speaker") or None)
                     for c in body.get("cues", [])]
            lines = [(t, s) for t, s in lines if t]
            if not lines:
                return _err("the subtitles are empty")
        meta = {k: job.meta[k] for k in ("media", "media_name", "media_job") if k in job.meta}
        new = Job(kind="align", audio=job.audio, opt=opt, script=lines, udict=self.udict(), name=job.name,
                  meta={**meta, "parent": job.id})
        self.runner.submit(new)
        return JSONResponse(self.payload(new))

    async def reflow(self, req: Request) -> Response:
        """重新断行（不跑模型，直接返回）。从没改过字：从对齐结果重切（和 CLI 完全一样）。
        改过字：以当前字幕为准（改过的条没有字级时间，按 cue 内线性插值），改好的字幕记在 ``meta["src"]``，
        之后只换预设 / 振假名也从它重切，已经应用的修改不会丢。"""
        job = self.job(req)
        if job.state != "done" or job.raw is None:
            return _err("the job has not finished yet")
        body = await req.json()
        opt = _options(body.get("options") or {}, base=job.opt)
        udict = self.udict()
        cues = body.get("cues")
        if cues is not None and (not isinstance(cues, list) or not all(isinstance(c, dict) for c in cues)):
            return _err("bad cues")

        def work() -> None:
            out, _, _ = self.view(job)
            edited = cues is not None and (len(cues) != len(out.cues) or any(
                normalize(str(c.get("text", "")).replace("\n", "")) != o.text for c, o in zip(cues, out.cues)))
            src = job.meta.get("src")
            if edited:
                src = Document(_edited_cues(cues, out.cues), "ja", None, job.raw.meta)
            res = service.finish_align(src or job.raw, opt, udict)
            with self._lock:
                job.out, job.opt, job.udict = res, opt, udict
                if src is not None:
                    job.meta["src"] = src

        await run_in_threadpool(work)
        return JSONResponse(self.payload(job))

    async def download(self, req: Request) -> Response:
        job = self.job(req)
        fmt = req.path_params["fmt"]
        if fmt not in DL_TYPES:
            return _err(f"unsupported format {fmt}")
        stem = Path(job.meta.get("media_name") or "subtitles").stem or "subtitles"
        if fmt == "txt":
            if not job.lines:
                return _err("there is no script yet")
            text, name = service.script_text(job.lines), f"{stem}.script.txt"
        else:
            out, opt, udict = self.view(job)
            if job.state != "done" or out is None:
                return _err("the job has not finished yet")
            text, name = await run_in_threadpool(service.render, out, fmt, opt, udict), f"{stem}.{fmt}"
        return Response(text.encode("utf-8"), media_type=DL_TYPES[fmt] + "; charset=utf-8",
                        headers={"Content-Disposition": _disposition(name)})

    async def get_dict(self, req: Request) -> Response:
        p = self.dict_path
        return PlainTextResponse(p.read_text(encoding="utf-8-sig") if p.exists() else "")

    async def put_dict(self, req: Request) -> Response:
        text = (await req.body()).decode("utf-8-sig")
        try:
            d = UserDict.parse(text)
        except ValueError as e:
            return _err(str(e))
        self.dict_path.write_text(text, encoding="utf-8")
        return JSONResponse({"entries": len(d.entries)})

    async def reading(self, req: Request) -> Response:
        from ..reading import reading
        text = req.query_params.get("text", "")
        return JSONResponse({"text": text, "reading": reading(text, self.udict()) if text else ""})


class _NotFound(Exception):
    pass


def _err(msg: str, code: int = 400) -> Response:
    return JSONResponse({"error": msg}, status_code=code)


def _disposition(name: str) -> str:
    from urllib.parse import quote
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _opts_dict(o: service.Options) -> dict:
    return {"preset": o.preset, "asr_model": o.asr_model, "ruby": o.ruby, "ruby_grade": o.ruby_grade,
            "ruby_once": o.ruby_once, "speakers": o.speakers}


def _options(src, base: service.Options | None = None) -> service.Options:
    """表单 / JSON → Options。只开放网页上有的几个选项，其余用默认值（和 CLI 默认一样）。"""
    b = base or service.Options()

    def get(k, default):
        v = src.get(k)
        return default if v in (None, "") else v

    def flag(v) -> bool:
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")

    ruby = str(get("ruby", b.ruby))
    grade = get("ruby_grade", b.ruby_grade)          # 0 = 常用漢字表（不按学年）
    try:
        if isinstance(grade, bool):
            raise ValueError
        grade = None if ruby != "hard" or grade in (None, 0, "0") else int(grade)
    except (TypeError, ValueError):
        raise ValueError(f"school grade must be 1-6 (got {grade})") from None
    return service.Options(preset=str(get("preset", b.preset)), asr_model=str(get("asr_model", b.asr_model)),
                           ruby=ruby, ruby_grade=grade, ruby_once=flag(get("ruby_once", b.ruby_once)),
                           speakers=flag(get("speakers", b.speakers)))


def _edited_cues(cues: list[dict], cur: list[Cue]) -> list[Cue]:
    """网页发来的字幕（可能改过字）→ 重新断行的输入。没改的条原样（带字级时间），改过的条只留文字和起止时间。"""
    src = []
    for c in cues:
        text = normalize(str(c.get("text", "")).replace("\n", ""))
        if not text:
            continue
        i = c.get("i")
        o = cur[i] if isinstance(i, int) and 0 <= i < len(cur) else None
        if o is not None and o.text == text:
            src.append(copy.deepcopy(o))
            continue
        start = _num(c.get("start"), o.start if o else 0.0)
        end = _num(c.get("end"), o.end if o else start)
        spk = c.get("speaker")
        src.append(Cue(start, max(end, start + 0.1), text, None, [], [], spk if isinstance(spk, str) and spk else None))
    src.sort(key=lambda c: c.start)
    return src


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _cue(c: Cue, opt: service.Options) -> dict:
    """``display``：和导出文件一样渲染后的每一行（句读点按预设、振假名），``[[文字, 振假名或 null], …]``。
    ``c.ruby`` 已经由 ``service.add_ruby`` 按整份字幕算好（「只标第一次」要看前面的条）。"""
    return {"start": round(c.start, 3), "end": round(c.end, 3), "text": c.text, "lines": c.lines or [c.text],
            "flags": c.flags, "speaker": c.speaker,
            "display": [[list(p) for p in line] for line in rendered_lines(c, opt.params().punct, opt.ruby != "none")]}


class _LocalOnly:
    """只接受发给本机名字的请求（防 DNS rebinding）；改东西的请求带 Origin 时必须和本站同源（防别的网站偷偷 POST）。"""

    def __init__(self, app, hosts: set[str]):
        self.app, self.hosts = app, hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
            host = _hostname(headers.get("host", ""))
            origin = headers.get("origin")
            bad = "*" not in self.hosts and host not in self.hosts
            if scope["method"] not in ("GET", "HEAD") and origin is not None:
                bad = bad or _hostname(origin.split("://", 1)[-1].split("/", 1)[0]) != host
            if bad:
                await PlainTextResponse("forbidden", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _hostname(hostport: str) -> str:
    h = hostport.strip().lower()
    if h.startswith("["):
        return h[1:h.index("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def create_app(runner: Runner | None = None, root: Path | None = None, hosts: set[str] | None = None) -> Starlette:
    hosts = hosts or set(LOCAL_HOSTS)
    app_ = App(runner or Runner(), root or home())

    def wrap(fn):
        async def h(req: Request) -> Response:
            try:
                return await fn(req)
            except _NotFound as e:
                return _err(str(e), 404)
            except (ValueError, OSError, json.JSONDecodeError) as e:
                return _err(str(e))
            except (TypeError, AttributeError, KeyError) as e:    # 请求体的结构不对
                return _err(f"bad request: {e}")
        return h

    routes = [
        Route("/", lambda req: FileResponse(STATIC / "index.html")),
        Route("/api/config", wrap(app_.config)),
        Route("/api/jobs", wrap(app_.create), methods=["POST"]),
        Route("/api/jobs/{id}", wrap(app_.get)),
        Route("/api/jobs/{id}/media", wrap(app_.media)),
        Route("/api/jobs/{id}/cancel", wrap(app_.cancel), methods=["POST"]),
        Route("/api/jobs/{id}/realign", wrap(app_.realign), methods=["POST"]),
        Route("/api/jobs/{id}/reflow", wrap(app_.reflow), methods=["POST"]),
        Route("/api/jobs/{id}/download/{fmt}", wrap(app_.download)),
        Route("/api/dict", wrap(app_.get_dict), methods=["GET"]),
        Route("/api/dict", wrap(app_.put_dict), methods=["PUT"]),
        Route("/api/reading", wrap(app_.reading)),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(_LocalOnly, hosts=hosts)])
    app.state.kugiri = app_
    return app


def run(host: str = "127.0.0.1", port: int = 7790, *, device: str = "auto", warm: str | None = "qwen3-1.7b",
        open_browser: bool = True, root: str | None = None) -> None:
    import threading
    import webbrowser

    import uvicorn

    from ..service import Engine
    runner = Runner(Engine(device, keep=True))
    if warm:
        runner.warm(warm)            # 模型常驻：启动就加载，第一个任务不用等
    hosts = set(LOCAL_HOSTS)
    if host not in ("127.0.0.1", "localhost", "::1"):
        import socket
        hosts |= {host, socket.gethostname().lower(), socket.getfqdn().lower()}
        if host == "0.0.0.0":
            hosts.add("*")
    app = create_app(runner, Path(root).expanduser() if root else None, hosts)
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/"
    print(f"kugiri web: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
