"""任务队列（网页和 MCP 共用）：一个后台线程按顺序跑，同一时间只跑一个任务，其他排队；模型常驻（``Engine(keep=True)``）。

任务有两种：``align``（音频 + 可选台本 → 断行后的字幕）和 ``transcribe``（只出识别稿）。
进度按阶段加权合成一个 0–1 的数（只增不减），另外给出当前阶段和阶段内进度。
"""
from __future__ import annotations

import itertools
import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass, field

from .service import Engine, Line, Options
from .timeline import Document
from .userdict import UserDict

# 各阶段在总进度里的占比（有台本时没有识别阶段）
_WEIGHTS = {
    "script": {"load": 0.05, "align": 0.9, "reflow": 0.05},
    "asr": {"load": 0.05, "transcribe": 0.6, "align": 0.3, "reflow": 0.05},
    "transcribe": {"load": 0.05, "transcribe": 0.95},
}
_seq = itertools.count()
CANCELLED = "cancelled"


class Cancelled(BaseException):
    """用户取消了正在跑的任务（从进度回调里抛出；BaseException，免得被中间的 except Exception 吞掉）。"""


def _download() -> dict | None:
    """正在下载的模型（第一次用时；见 ``align.assets.current``）。没装 [align] 时 None。"""
    try:
        from .align.assets import current
    except ImportError:
        return None
    return current()


@dataclass
class Job:
    kind: str                                  # align / transcribe
    audio: str
    opt: Options
    script: str | list[Line] | None = None
    udict: UserDict | None = None
    name: str = ""                             # 显示用的文件名
    meta: dict = field(default_factory=dict)   # 调用方自己的东西（网页：媒体路径、父任务等）
    after: Callable[[Job], None] | None = field(default=None, repr=False)   # 成功后在后台线程里调（MCP 写文件）
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = "queued"                      # queued / running / done / error / cancelled
    stage: str = ""
    stage_frac: float = 0.0
    frac: float = 0.0
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    lines: list[Line] | None = None            # 用到的台本（识别稿或输入台本）
    raw: Document | None = None                # 对齐结果（台本一行一条 cue）
    out: Document | None = None                # 断行后
    info: dict | None = None                   # transcribe 的信息
    seq: int = field(default_factory=lambda: next(_seq))
    cancel: bool = False                       # 取消请求：下一次进度回调时停下
    done: threading.Event = field(default_factory=threading.Event, repr=False)

    def _plan(self) -> dict[str, float]:
        if self.kind == "transcribe":
            return _WEIGHTS["transcribe"]
        return _WEIGHTS["script" if self.script is not None else "asr"]

    def progress(self, stage: str, x: float) -> None:
        if self.cancel:
            raise Cancelled()
        plan = self._plan()
        if stage not in plan:
            return
        x = min(max(x, 0.0), 1.0)
        before = sum(w for s, w in plan.items() if list(plan).index(s) < list(plan).index(stage))
        self.stage, self.stage_frac = stage, x
        self.frac = max(self.frac, min(1.0, before + plan[stage] * x))

    def status(self) -> dict:
        now = time.time()
        d = {"id": self.id, "kind": self.kind, "name": self.name, "state": self.state, "stage": self.stage,
             "stage_progress": round(self.stage_frac, 3), "progress": round(self.frac, 3),
             "elapsed_s": round((self.finished or now) - (self.started or now), 1) if self.started else 0.0}
        if self.error:
            d["error"] = self.error
        if self.state == "running" and self.stage == "load" and (dl := _download()):
            d["download"] = dl                   # 只读：任务进度由后台线程写，这里只在返回值里换成下载进度
            if dl["total"]:
                d["stage_progress"] = round(dl["done"] / dl["total"], 3)
        return d


class Runner:
    def __init__(self, engine: Engine | None = None, *, keep_jobs: int = 200):
        self.engine = engine or Engine(keep=True)
        self.jobs: dict[str, Job] = {}
        self._queue: deque[Job] = deque()
        self._cv = threading.Condition()
        self._current: Job | None = None
        self._keep = keep_jobs
        self.warming: str | None = None          # 正在预加载的模型（网页显示「模型加载中」）
        self.warm_error: str | None = None
        self._warm: str | None = None
        self._thread = threading.Thread(target=self._loop, name="kugiri-runner", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ 提交 / 查询
    def submit(self, job: Job) -> Job:
        with self._cv:
            self.jobs[job.id] = job
            self._queue.append(job)
            self._prune()
            self._cv.notify()
        return job

    def cancel(self, job: Job) -> bool:
        """取消排队中的任务（马上）或正在跑的任务（下一次进度回调时停，模型加载中要等加载完）。
        已经结束的任务返回 False。取消后 state = error = CANCELLED。"""
        with self._cv:
            if job.state == "queued" and job in self._queue:
                self._queue.remove(job)
                job.state, job.error, job.finished = CANCELLED, CANCELLED, time.time()
                job.done.set()
                return True
            if job.state == "running":
                job.cancel = True
                return True
        return False

    def warm(self, asr_model: str | None) -> None:
        """后台预加载模型（启动时调用；排在所有任务前面）。"""
        with self._cv:
            self._warm = asr_model or "omni"
            self.warming = self._warm
            self._cv.notify()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def position(self, job: Job) -> int:
        """前面还有几个任务（包括正在跑的）；不在队列里时 0。"""
        with self._cv:
            if job.state != "queued":
                return 0
            ahead = list(self._queue).index(job) if job in self._queue else 0
            return ahead + (1 if self._current is not None or self.warming else 0)

    def status(self, job: Job) -> dict:
        d = job.status()
        if job.state == "queued":
            d["queue_position"] = self.position(job)
        return d

    def download(self) -> dict | None:
        """正在下载的模型（预加载或任务里）。"""
        return _download() if self.warming or self._current is not None else None

    def busy(self) -> bool:
        return self._current is not None or bool(self._queue)

    def _prune(self) -> None:
        done = [j for j in self.jobs.values() if j.state in ("done", "error", CANCELLED)]
        for j in sorted(done, key=lambda j: j.seq)[:max(0, len(done) - self._keep)]:
            self.jobs.pop(j.id, None)

    # ------------------------------------------------------------ 后台线程
    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and self._warm is None:
                    self._cv.wait()
                warm, self._warm = self._warm, None
                job = None if warm is not None else self._queue.popleft()
                self._current = job
            if warm is not None:
                try:
                    with self.engine.lock:
                        self.engine.warm(warm)
                except Exception as e:           # 预加载失败不致命：任务开始时会再试并报错
                    self.warm_error = f"{type(e).__name__}: {e}"
                finally:
                    self.warming = None
                continue
            self._run(job)
            with self._cv:
                self._current = None

    def _run(self, job: Job) -> None:
        job.state, job.started = "running", time.time()
        try:
            with self.engine.lock:
                if job.kind == "align":
                    def keep(ls: list[Line]) -> None:
                        job.lines = ls
                    job.raw, job.out = self.engine.align(job.audio, job.script, job.opt, job.udict,
                                                         progress=job.progress, on_script=keep)
                elif job.kind == "transcribe":
                    job.lines, job.info = self.engine.transcribe(job.audio, job.opt, progress=job.progress)
                else:
                    raise ValueError(f"unknown job type {job.kind!r}")
            if job.after is not None:
                job.after(job)
            job.frac, job.state = 1.0, "done"
        except Cancelled:
            job.state, job.error = CANCELLED, CANCELLED
        except (ValueError, OSError) as e:
            # 报错里用用户看到的文件名（网页上传后存成 media.mp4 之类）
            msg = str(e)
            if job.name:
                msg = msg.replace(job.audio, job.name).replace(Path(job.audio).name, job.name)
            job.state, job.error = "error", msg
        except Exception as e:                   # 不让一个任务的意外错误弄死后台线程
            job.state, job.error = "error", f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            job.finished = time.time()
            job.done.set()

