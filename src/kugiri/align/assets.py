"""模型文件：第一次用时下载到本地缓存，之后离线可用。

- omniASR CTC 300M v2 权重和字表（Apache-2.0，facebookresearch/omnilingual-asr）：Meta 官方地址 →
  ``KUGIRI_MODEL_DIR``（默认 ``~/.cache/kugiri/models``）。``KUGIRI_MODEL_URL`` 可换成镜像地址。
  中断后再运行从断点续传（``.part`` 文件 + HTTP Range）。
- Qwen3-ASR（识别模式）：Hugging Face Hub → HF 缓存（``HF_HOME``），用 ``fetch_hf`` 先整个下载好再加载。

下载进度：CLI（``quiet=False``）打到 stderr；网页 / MCP 读 ``current()``（同一时间只有一个下载，模型由
``Engine.lock`` 串行加载）。下载失败统一抛 ``OSError``，信息写清楚下什么、从哪下、怎么办。
"""
from __future__ import annotations

import contextlib
import errno
import http.client
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

BASE = "https://dl.fbaipublicfiles.com/mms/"
FILES = {
    "300M": "omniASR-CTC-300M-v2.pt",
    "vocab": "omniASR_tokenizer_written_v2.model",
}
LABELS = {"300M": "omniASR CTC 300M alignment model", "vocab": "omniASR vocabulary"}
_MARGIN = 200 * 1024 ** 2          # 下载前要求多留的磁盘空间

_current: dict | None = None
_lock = threading.Lock()


def model_dir() -> Path:
    d = os.environ.get("KUGIRI_MODEL_DIR")
    return Path(d).expanduser() if d else Path.home() / ".cache" / "kugiri" / "models"


def current() -> dict | None:
    """正在下载的模型：``{"name", "done", "total"}``（字节；total 不知道时 0），没在下载时 None。"""
    with _lock:
        return dict(_current) if _current else None


def _set(name: str | None, done: int = 0, total: int = 0) -> None:
    global _current
    with _lock:
        _current = {"name": name, "done": done, "total": total} if name else None


def size_text(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


class _Printer:
    """CLI 的下载进度：终端里同一行刷新，重定向到文件时每 10%（不知道总大小时每 100 MB）一行。"""

    def __init__(self, quiet: bool):
        self.quiet, self.tty = quiet, sys.stderr.isatty()
        self.last, self.shown, self.t0, self.first = None, None, time.time(), None

    def __call__(self, done: int, total: int, end: bool = False) -> None:
        if self.quiet:
            return
        if self.first is None:            # 续传时已有的字节不算进速度
            self.first, self.t0 = done, time.time()
        pct = int(100 * done / total) if total else None
        step = pct // 10 if pct is not None else done // 100_000_000
        if not self.tty and (step == self.last if not end else (pct, done) == self.shown):
            return
        self.last, self.shown = step, (pct, done)
        rate = (done - self.first) / max(time.time() - self.t0, 1e-3)
        msg = f"  {size_text(done)} / {size_text(total)} ({pct}%)" if total else f"  {size_text(done)}"
        msg += f"  {rate / 1e6:.1f} MB/s"
        print(("\r" if self.tty else "") + msg.ljust(48), end="\n" if end or not self.tty else "",
              file=sys.stderr, flush=True)


class _SpaceError(OSError):
    pass


def _check_space(where: Path, need: int, what: str) -> None:
    free = shutil.disk_usage(where).free
    if need and free < need + _MARGIN:
        raise _SpaceError(f"Not enough disk space to download the {what}: needs {size_text(need)}, "
                          f"{size_text(free)} free in {where}.")


@contextlib.contextmanager
def _file_lock(path: Path):
    """同一个文件同一时间只让一个进程下载（网页和 CLI 同时第一次运行时）。Windows 上不加锁。"""
    try:
        import fcntl
    except ImportError:
        yield
        return
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _range_total(cr: str | None) -> tuple[int | None, int | None]:
    """``Content-Range: bytes a-b/N`` 或 ``bytes */N`` → (a, N)。"""
    try:
        unit, spec = (cr or "").split(" ", 1)
        rng, size = spec.split("/")
        start = None if rng == "*" else int(rng.split("-")[0])
        return start, None if size == "*" else int(size)
    except ValueError:
        return None, None


def fetch(key: str, quiet: bool = False) -> Path:
    """omniASR 的文件（``300M`` / ``vocab``）→ 本地路径；不在缓存里时下载。"""
    name, label = FILES[key], LABELS[key]
    path = model_dir() / name
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path.with_suffix(path.suffix + ".lock")):
        if not path.exists():             # 等锁的时候别的进程可能已经下完了
            _download(name, label, path, quiet)
    return path


def _disk_full(e: BaseException) -> bool:
    while e is not None:
        if isinstance(e, OSError) and e.errno == errno.ENOSPC:
            return True
        e = e.__cause__ or e.__context__
    return False


def _full_msg(label: str, where: Path, env: str) -> str:
    return (f"The disk filled up while downloading the {label} to {where}. Free some space, or set {env} to a "
            f"folder on a disk with more room, then run again (the download resumes where it stopped).")


def _download(name: str, label: str, path: Path, quiet: bool) -> None:
    url = os.environ.get("KUGIRI_MODEL_URL", BASE).rstrip("/") + "/" + name
    tmp = path.with_suffix(path.suffix + ".part")
    have = tmp.stat().st_size if tmp.exists() else 0
    hint = (f"Check the internet connection (or proxy) and run again; the download resumes where it stopped. "
            f"Or download {url} yourself and save it as {path}.")
    show = _Printer(quiet)
    total = got = 0
    try:
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            start, size = _range_total(r.headers.get("Content-Range")) if r.status == 206 else (None, None)
            if have and (r.status != 206 or start != have):     # 服务器不支持续传（或给的不是要的那段）：从头下
                if r.status == 206:
                    tmp.unlink(missing_ok=True)
                    raise OSError(f"the server answered the resume request with bytes from {start}")
                have = 0
            length = int(r.headers.get("Content-Length") or 0)
            total = size or (have + length if length else 0)
            _check_space(path.parent, total - have, label)
            if not quiet:
                print(f"Downloading the {label} ({size_text(total) if total else 'size unknown'}, first run only)"
                      f"\n  {url}\n  → {path}" + (f"\n  resuming at {size_text(have)}" if have else ""),
                      file=sys.stderr, flush=True)
            got = have
            _set(label, got, total)
            with open(tmp, "ab" if have else "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    _set(label, got, total)
                    show(got, total)
            show(got, total, end=True)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:
            _, size = _range_total(e.headers.get("Content-Range"))
            if size == have:              # .part 已经是完整文件（上次写完但没改名）
                tmp.replace(path)
                return
            tmp.unlink(missing_ok=True)   # 比远端文件还大：坏了，下次从头下
            raise OSError(f"The partial download of the {label} did not match the file on the server and was "
                          f"removed. Run again to download it from the start.") from e
        if "KUGIRI_MODEL_URL" in os.environ and e.code in (401, 403, 404):
            hint = f"Check the mirror set in KUGIRI_MODEL_URL (it should serve {name}), or unset it."
        raise OSError(f"Could not download the {label} from {url}: HTTP {e.code} {e.reason}. {hint}") from e
    except _SpaceError:
        raise
    except (OSError, http.client.HTTPException) as e:     # URLError、超时、断线、SSL、磁盘写满等
        if _disk_full(e):
            raise OSError(_full_msg(label, path.parent, "KUGIRI_MODEL_DIR")) from e
        reason = getattr(e, "reason", None) or e
        raise OSError(f"Could not download the {label} from {url}: {type(e).__name__}: {reason}. {hint}") from e
    finally:
        _set(None)
    if total and got != total:
        raise OSError(f"The download of the {label} stopped early ({size_text(got)} of {size_text(total)}). {hint}")
    tmp.replace(path)


def _blob_bytes(d: Path) -> int:
    n = 0
    try:
        with os.scandir(d) as it:
            for e in it:
                try:
                    n += e.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return n


def _complete(snap: Path) -> bool:
    """HF 快照里加载要用的文件都在（中断的下载会留下缺文件的快照目录；老版本 huggingface_hub 不检查）。"""
    if not all((snap / f).exists() for f in ("config.json", "tokenizer_config.json")):
        return False
    idx = snap / "model.safetensors.index.json"
    if idx.exists():
        try:
            shards = set(json.loads(idx.read_text(encoding="utf-8"))["weight_map"].values())
        except (OSError, ValueError, KeyError):
            return False
        return all((snap / f).exists() for f in shards)
    return (snap / "model.safetensors").exists()


def fetch_hf(repo: str, label: str, quiet: bool = False) -> str:
    """Hugging Face 上的模型 → 本地快照目录；已在 HF 缓存里时不联网。下载时报进度（按缓存目录里的字节数）。"""
    from huggingface_hub import HfApi, constants, snapshot_download
    try:
        snap = snapshot_download(repo, local_files_only=True)
        if _complete(Path(snap)):
            return snap
    except Exception:
        pass
    cache = Path(constants.HF_HUB_CACHE)
    hint = (f"Check the internet connection (or proxy) and run again; finished files are kept. "
            f"Models are cached in {cache} (set HF_HOME to use another place; HF_ENDPOINT for a mirror).")
    if constants.HF_HUB_OFFLINE:
        raise OSError(f"The {label} ({repo}) is not in the Hugging Face cache ({cache}) and HF_HUB_OFFLINE is set. "
                      f"Unset HF_HUB_OFFLINE once to download it.")
    try:
        info = HfApi().model_info(repo, files_metadata=True)
    except Exception as e:
        raise OSError(f"Could not reach Hugging Face to download the {label} ({repo}): "
                      f"{type(e).__name__}: {e}. {hint}") from e
    total = sum(s.size or 0 for s in info.siblings or [])
    blobs = cache / ("models--" + repo.replace("/", "--")) / "blobs"
    cache.mkdir(parents=True, exist_ok=True)
    _check_space(cache, max(0, total - _blob_bytes(blobs)), label)
    if not quiet:
        print(f"Downloading the {label} ({size_text(total)}, first run only)\n  https://huggingface.co/{repo}\n"
              f"  → {cache}", file=sys.stderr, flush=True)
    show = _Printer(quiet)
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(0.5):
            got = min(_blob_bytes(blobs), total)
            _set(label, got, total)
            show(got, total)

    from huggingface_hub.utils import are_progress_bars_disabled, disable_progress_bars, enable_progress_bars
    bars_off = are_progress_bars_disabled()
    disable_progress_bars()                  # 自己报进度；HF 的进度条在网页 / MCP 下会刷满 stderr
    _set(label, _blob_bytes(blobs), total)
    th = threading.Thread(target=watch, daemon=True)
    th.start()
    try:
        path = snapshot_download(repo)                     # 不指定 revision：这样才会写 refs/main，之后离线能找到
    except Exception as e:
        if _disk_full(e):
            raise OSError(_full_msg(label, cache, "HF_HOME")) from e
        raise OSError(f"Could not download the {label} ({repo}): {type(e).__name__}: {e}. {hint}") from e
    finally:
        stop.set()
        th.join()
        _set(None)
        if not bars_off:
            enable_progress_bars()
    show(total, total, end=True)
    return path
