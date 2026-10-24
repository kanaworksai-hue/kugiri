"""模型下载（align/assets.py）：本地 HTTP 服务器上测完整下载、断点续传、失败时的错误信息。不联网。"""
import http.server
import socket
import threading

import pytest

pytest.importorskip("numpy")
from kugiri.align import assets  # noqa: E402

DATA = bytes(range(256)) * 4096          # 1 MB
NAME = assets.FILES["vocab"]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path != "/mms/" + NAME:
            self.send_error(404)
            return
        start = 0
        if rng := self.headers.get("Range"):
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(DATA):
                self.server.ranges.append(start)
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(DATA)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
        else:
            self.send_response(200)
        self.server.ranges.append(start)
        if not self.server.no_length:
            self.send_header("Content-Length", str(len(DATA) - start))
        else:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(DATA[start:])

    def log_message(self, *a):
        pass


@pytest.fixture
def server(monkeypatch, tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.ranges, srv.no_length = [], False
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("KUGIRI_MODEL_URL", f"http://127.0.0.1:{srv.server_port}/mms/")
    monkeypatch.setenv("KUGIRI_MODEL_DIR", str(tmp_path / "models"))
    yield srv
    srv.shutdown()


def test_download_and_cache(server, capsys):
    path = assets.fetch("vocab")
    assert path.read_bytes() == DATA
    err = capsys.readouterr().err
    assert "Downloading the omniASR vocabulary (1 MB, first run only)" in err
    assert assets.current() is None
    assert assets.fetch("vocab", quiet=True) == path and server.ranges == [0]     # 第二次不下载


def test_resume(server, tmp_path):
    part = tmp_path / "models" / (NAME + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(DATA[:300_000])
    assert assets.fetch("vocab", quiet=True).read_bytes() == DATA
    assert server.ranges == [300_000] and not part.exists()


def _part(tmp_path, data):
    part = tmp_path / "models" / (NAME + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(data)
    return part


def test_resume_without_content_length(server, tmp_path):
    server.no_length = True                  # 只有 Content-Range：总大小从那里取
    _part(tmp_path, DATA[:100_000])
    assert assets.fetch("vocab", quiet=True).read_bytes() == DATA


def test_part_already_complete(server, tmp_path):
    _part(tmp_path, DATA)                    # 上次下完了但没改名：416 + Content-Range 总大小相同
    assert assets.fetch("vocab", quiet=True).read_bytes() == DATA


def test_part_larger_than_remote_is_dropped(server, tmp_path):
    part = _part(tmp_path, DATA + b"x" * 10)
    with pytest.raises(OSError, match="did not match"):
        assets.fetch("vocab", quiet=True)
    assert not part.exists()
    assert assets.fetch("vocab", quiet=True).read_bytes() == DATA


def test_http_error(server, monkeypatch):
    monkeypatch.setenv("KUGIRI_MODEL_URL", f"http://127.0.0.1:{server.server_port}/missing/")
    with pytest.raises(OSError, match="HTTP 404.*KUGIRI_MODEL_URL"):
        assets.fetch("vocab", quiet=True)


def test_unreachable(monkeypatch, tmp_path):
    with socket.socket() as s:                # 一个没人监听的端口
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("KUGIRI_MODEL_URL", f"http://127.0.0.1:{port}/")
    monkeypatch.setenv("KUGIRI_MODEL_DIR", str(tmp_path))
    with pytest.raises(OSError, match="Could not download the omniASR vocabulary .*run again"):
        assets.fetch("vocab", quiet=True)
    assert assets.current() is None


def test_hf_offline_message(monkeypatch, tmp_path):
    constants = pytest.importorskip("huggingface_hub.constants")
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True)
    with pytest.raises(OSError, match="not in the Hugging Face cache.*HF_HUB_OFFLINE"):
        assets.fetch_hf("Qwen/Qwen3-ASR-0.6B-hf", "Qwen3-ASR 0.6B speech recognition model", quiet=True)


def _snapshot(cache, repo, files):
    d = cache / ("models--" + repo.replace("/", "--"))
    (d / "refs").mkdir(parents=True)
    (d / "refs" / "main").write_text("abc")
    snap = d / "snapshots" / "abc"
    snap.mkdir(parents=True)
    for f in files:
        (snap / f).write_text("{}")
    return snap


def test_hf_cached_snapshot_offline(monkeypatch, tmp_path):
    constants = pytest.importorskip("huggingface_hub.constants")
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True)
    snap = _snapshot(tmp_path, "a/full", ["config.json", "tokenizer_config.json", "model.safetensors"])
    assert assets.fetch_hf("a/full", "test model", quiet=True) == str(snap)
    _snapshot(tmp_path, "a/partial", ["config.json", "tokenizer_config.json"])     # 权重没下完
    with pytest.raises(OSError, match="not in the Hugging Face cache"):
        assets.fetch_hf("a/partial", "test model", quiet=True)


def test_size_text():
    assert assets.size_text(1_304_065_508) == "1.3 GB" and assets.size_text(91_481) == "91 KB"
