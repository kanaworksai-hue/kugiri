"""service / jobs / 网页 / MCP：用假引擎（不加载模型）测流程、队列、接口；三个入口共用 service，输出一致。"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from kugiri import formats, service
from kugiri.jobs import Job, Runner
from kugiri.timeline import Cue, Document

GOLD = Path(__file__).parent / "golden" / "input"
WARN = {"start": 0.0, "end": 1.0, "reason": "low_confidence", "text": "こんにちは"}


class FakeEngine(service.Engine):
    """台本一行一条 cue、每行 2 秒（没有字级时间，reflow 按 cue 内线性插值）；没有台本时「识别」出固定文字。"""

    def __init__(self, gate: threading.Event | None = None):
        super().__init__(keep=True)
        self.gate = gate
        self.calls: list[str] = []

    def align(self, audio, script, opt, udict=None, *, progress=None, on_script=None):
        if self.gate is not None:
            self.gate.wait(5)
        self.calls.append(audio)
        lines = service.read_script(script, opt.speakers) if isinstance(script, str) else script
        if lines is None:
            lines = [("こんにちは。", None), ("今日は新しいマイクを試してみたいと思います。", None)]
        if on_script:
            on_script(lines)
        for s in ("load", "align", "reflow"):
            if progress:
                progress(s, 0.5)
                progress(s, 1.0)
        if "失败" in audio:
            raise ValueError("模型运行失败：测试")
        cues = [Cue(2.0 * i, 2.0 * i + 1.8, t, None, [], [], s) for i, (t, s) in enumerate(lines)]
        raw = Document(cues, "ja", None, {"align": {"audio_s": 2.0 * len(lines), "warnings": [WARN]}})
        return raw, service.finish_align(raw, opt, udict)

    def transcribe(self, audio, opt, *, progress=None):
        return [("こんにちは。", None)], {"asr": {"model": opt.asr_model}, "audio_s": 2.0, "wall_s": 0.1}


# ------------------------------------------------------------------ service
def test_options_validate():
    with pytest.raises(ValueError):
        service.Options(preset="tiktok")
    with pytest.raises(ValueError):
        service.Options(ruby="some")
    with pytest.raises(ValueError):
        service.Options(asr_model="whisper")
    with pytest.raises(ValueError):
        service.Options(asr_batch=0)


def test_render_does_not_mutate_and_matches_cli(tmp_path):
    from kugiri import cli
    doc = formats.read(GOLD / "userdict.srt")
    opt = service.Options(preset="netflix", ruby="all")
    out = service.reflow_doc(doc, opt)
    text = service.render(out, "ass", opt)
    assert all(not c.ruby for c in out.cues)          # 振假名加在副本上
    assert "\\pos" in text
    p = tmp_path / "x.ass"
    assert cli.main([ "reflow", str(GOLD / "userdict.srt"), "--preset", "netflix", "--ruby", "all", "-o", str(p)]) == 0
    assert p.read_text(encoding="utf-8") == text


def test_script_text_roundtrip():
    pytest.importorskip("torch")          # 台本解析在 align.pipeline 里（可选依赖 [align]）
    lines = [("こんにちは。", "司会"), ("よろしく", None)]
    assert service.read_script(service.script_text(lines), speakers=True) == lines
    with pytest.raises(ValueError):
        service.read_script("\n \n")


def test_finish_align_flags_and_clamps():
    raw = Document([Cue(0.0, 1.8, "こんにちは。"), Cue(2.0, 3.0, "さようなら。")], "ja", None,
                   {"align": {"audio_s": 3.0, "warnings": [WARN]}})
    out = service.finish_align(raw, service.Options())
    assert out.meta is raw.meta
    assert out.cues[-1].end <= 3.0                    # linger 不超过音频长度
    assert "low_confidence" in out.cues[0].flags
    assert service.finish_align(raw, service.Options(raw=True)) is raw
    s = service.summary(raw)
    assert s["cues"] == 2 and s["warnings"][0]["reason"] == "low_confidence"


def test_analysis_is_thread_safe():
    from kugiri.analysis import analyze
    errs: list[str] = []

    def f():
        try:
            for _ in range(20):
                analyze("今日は新しいマイクを試してみたいと思います。東京の夜は静かです。" * 3)
        except Exception as e:          # noqa: BLE001
            errs.append(repr(e))
    ts = [threading.Thread(target=f) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs


# ------------------------------------------------------------------ jobs
def test_runner_queue_progress_and_errors():
    pytest.importorskip("torch")          # 台本解析在 align.pipeline 里（可选依赖 [align]）
    gate = threading.Event()
    r = Runner(FakeEngine(gate))
    seen: list[float] = []
    j1 = Job("align", "a.wav", service.Options(), script="こんにちは。")
    orig = j1.progress

    def spy(stage, x):
        orig(stage, x)
        seen.append(j1.frac)
    j1.progress = spy
    j2 = r.submit(Job("align", "失败.wav", service.Options()))
    r.submit(j1)
    j3 = r.submit(Job("transcribe", "c.wav", service.Options(asr_model="qwen3-0.6b"),
                      after=lambda j: j.meta.setdefault("written", True)))
    assert r.status(j3)["state"] == "queued" and r.position(j3) >= 2
    gate.set()
    for j in (j1, j2, j3):
        assert j.done.wait(5)
    assert j2.state == "error" and "测试" in j2.error
    assert j1.state == "done" and j1.frac == 1.0 and seen == sorted(seen)    # 进度只增不减
    assert j1.lines == [("こんにちは。", None)] and j1.out.cues
    assert j3.state == "done" and j3.lines and j3.meta["written"]
    assert r.engine.calls == ["失败.wav", "a.wav"]                          # 按提交顺序、一次一个


def test_runner_cancel_queued_and_running():
    pytest.importorskip("torch")
    from kugiri.jobs import CANCELLED
    gate = threading.Event()
    r = Runner(FakeEngine(gate))
    j1 = r.submit(Job("align", "a.wav", service.Options(), script="こんにちは。"))
    j2 = r.submit(Job("align", "b.wav", service.Options(), script="こんにちは。"))
    deadline = time.time() + 5
    while j1.state != "running" and time.time() < deadline:
        time.sleep(0.01)
    assert r.cancel(j2) and j2.state == CANCELLED      # 排队中的马上取消
    assert r.cancel(j1)                                                        # 跑着的：下一次进度回调时停
    gate.set()
    assert j1.done.wait(5) and j1.state == CANCELLED and j1.out is None
    assert not r.cancel(j1)
    assert r.engine.calls == ["a.wav"]


# ------------------------------------------------------------------ 网页
@pytest.fixture()
def web(tmp_path):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient

    from kugiri.web import create_app
    runner = Runner(FakeEngine())
    with TestClient(create_app(runner, tmp_path)) as c:
        yield c, runner


def _wait_job(runner, jid):
    assert runner.get(jid).done.wait(5)


def test_web_flow(web):
    c, runner = web
    assert c.get("/").status_code == 200
    cfg = c.get("/api/config").json()
    assert set(cfg["presets"]) == {"netflix", "youtube", "vertical"} and "txt" in cfg["formats"]
    assert c.post("/api/jobs", data={"script": "x"}).status_code == 400          # 没有文件
    r = c.post("/api/jobs", files={"media": ("talk.mp4", b"fake-media", "video/mp4")},
               data={"script": "司会：こんにちは。\nゲスト：今日は新しいマイクを試してみたいと思います。", "speakers": "1",
                     "preset": "netflix", "ruby": "all"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    _wait_job(runner, jid)
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["state"] == "done" and j["options"]["preset"] == "netflix" and j["has_script"]
    assert j["summary"]["warnings"][0]["reason"] == "low_confidence"
    assert j["cues"][0]["speaker"] == "司会" and j["cues"][0]["display"]
    assert any(rt for line in j["cues"][-1]["display"] for _, rt in line)       # ruby=all 有振假名
    assert c.get(f"/api/jobs/{jid}/media").content == b"fake-media"

    # 下载和 service.render 一致（CLI 也走 render）
    job = runner.get(jid)
    srt = c.get(f"/api/jobs/{jid}/download/srt")
    assert srt.text == service.render(job.out, "srt", job.opt, job.udict)
    assert "talk.srt" in srt.headers["content-disposition"]
    for fmt in ("vtt", "ass", "json"):
        assert c.get(f"/api/jobs/{jid}/download/{fmt}").status_code == 200
    assert "司会：こんにちは。" in c.get(f"/api/jobs/{jid}/download/txt").text
    assert json.loads(c.get(f"/api/jobs/{jid}/download/json").text)["meta"]["align"]["warnings"]

    # 没改字 + 换预设：等于从对齐结果重新断行
    r = c.post(f"/api/jobs/{jid}/reflow", json={"cues": [{"i": k, "text": x["text"]} for k, x in enumerate(j["cues"])],
                                                "options": {"preset": "vertical", "ruby": "none"}})
    assert r.status_code == 200
    expect = service.finish_align(job.raw, service.Options(preset="vertical"))
    assert [x["text"] for x in r.json()["cues"]] == [x.text for x in expect.cues]
    # 改字：改过的条用新文字
    cues = r.json()["cues"]
    edit = [{"i": k, "start": x["start"], "end": x["end"], "text": x["text"], "speaker": x["speaker"]}
            for k, x in enumerate(cues)]
    edit[0]["text"] = "こんばんは。"
    r = c.post(f"/api/jobs/{jid}/reflow", json={"cues": edit})
    assert r.json()["cues"][0]["text"].startswith("こんばんは")

    # 重新对齐：新任务，父任务记下来，同一个媒体
    r = c.post(f"/api/jobs/{jid}/realign", json={"cues": edit})
    new = r.json()
    assert new["parent"] == jid and new["id"] != jid
    _wait_job(runner, new["id"])
    assert c.get(f"/api/jobs/{new['id']}").json()["cues"][0]["text"].startswith("こんばんは")
    r = c.post(f"/api/jobs/{jid}/realign", json={"script": "台本を直しました。"})
    _wait_job(runner, r.json()["id"])
    assert runner.engine.calls[-1] == runner.get(jid).audio

    # 改过字并应用后，再只换预设：修改不能丢
    r = c.post(f"/api/jobs/{jid}/reflow", json={"cues": edit, "options": {"preset": "youtube"}})
    cur = r.json()["cues"]
    r = c.post(f"/api/jobs/{jid}/reflow", json={"cues": [{"i": k, "text": x["text"]} for k, x in enumerate(cur)],
                                                "options": {"preset": "netflix", "ruby": "all"}})
    assert r.json()["cues"][0]["text"].startswith("こんばんは") and r.json()["options"]["ruby"] == "all"
    assert c.post(f"/api/jobs/{jid}/reflow", json={"cues": [1, 2]}).status_code == 400
    assert c.post(f"/api/jobs/{jid}/reflow", json={"options": [1]}).status_code == 400
    assert c.post(f"/api/jobs/{jid}/reflow", json=[1]).status_code == 400
    assert c.post(f"/api/jobs/{jid}/reflow", json={"cues": [{"i": 0, "text": "あ", "start": None}]}).status_code == 200

    assert c.get("/api/jobs/0123456789ab").status_code == 404
    assert c.get("/api/jobs/../../etc").status_code == 404
    assert c.get(f"/api/jobs/{jid}/download/exe").status_code == 400


def test_web_rejects_foreign_origin_and_host_and_html_media(web):
    c, runner = web
    up = {"files": {"media": ("x.html", b"<script>alert(1)</script>", "text/html")}}
    assert c.post("/api/jobs", headers={"origin": "https://evil.example"}, **up).status_code == 403
    assert c.get("/api/config", headers={"host": "evil.example"}).status_code == 403
    r = c.post("/api/jobs", headers={"origin": "http://testserver"}, **up)
    assert r.status_code == 200
    m = c.get(r.json()["media"])
    assert m.headers["content-type"] == "application/octet-stream" and m.headers["x-content-type-options"] == "nosniff"


def test_web_asr_job_and_dict(web):
    c, runner = web
    jid = c.post("/api/jobs", files={"media": ("a.wav", b"RIFF", "audio/wav")}).json()["id"]
    _wait_job(runner, jid)
    j = c.get(f"/api/jobs/{jid}").json()
    assert not j["has_script"] and j["script"].startswith("こんにちは。")
    assert c.get("/api/dict").text == ""
    r = c.put("/api/dict", content="表記\t読み\t禁止分割\n喫茶店\tきっさてん\t1\n".encode())
    assert r.json() == {"entries": 1}
    assert "喫茶店" in c.get("/api/dict").text
    assert c.get("/api/reading", params={"text": "喫茶店"}).json()["reading"] == "キッサテン"


# ------------------------------------------------------------------ MCP
@pytest.fixture()
def mcp(monkeypatch):
    pytest.importorskip("mcp")
    from kugiri import mcp_server
    monkeypatch.setattr(mcp_server, "_runner", Runner(FakeEngine()))
    return mcp_server


def test_mcp_tools(mcp, tmp_path):
    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"RIFF")
    script = tmp_path / "talk.txt"
    script.write_text("こんにちは。\n今日は新しいマイクを試してみたいと思います。\n", encoding="utf-8")
    res = asyncio.run(mcp.align(audio=str(audio), script=str(script), also=["vtt", "json"], preset="netflix"))
    assert res["state"] == "done" and res["cues"] >= 2 and res["warnings_total"] == 1
    assert set(res["outputs"]) == {"srt", "vtt", "json"}
    srt = Path(res["outputs"]["srt"])
    assert srt == tmp_path / "talk.kugiri.srt"         # 默认不覆盖用户自己的 talk.srt
    job = next(j for j in mcp.runner().jobs.values() if j.audio == str(audio))
    assert srt.read_text(encoding="utf-8") == service.render(job.out, "srt", job.opt)

    # 没台本：识别稿也写出来；wait=false + job_status
    res = asyncio.run(mcp.align(audio=str(audio), output=str(tmp_path / "out" / "x.vtt"), wait=False))
    assert res["state"] in ("queued", "running", "done")
    mcp.runner().get(res["id"]).done.wait(5)
    st = asyncio.run(mcp.job_status(job_id=res["id"]))
    assert st["state"] == "done" and Path(st["script"]).read_text(encoding="utf-8").startswith("こんにちは。")
    assert Path(st["outputs"]["vtt"]).exists()

    tr = asyncio.run(mcp.transcribe(audio=str(audio)))
    assert tr["script"] == str(tmp_path / "talk.kugiri.script.txt") and tr["lines"] == 1

    rf = asyncio.run(mcp.reflow(input=str(GOLD / "spoken.vtt"), output=str(tmp_path / "r.srt"), preset="vertical"))
    assert rf["cues"] > 0 and Path(rf["output"]).exists()
    rd = asyncio.run(mcp.reading(text="東京"))
    assert rd["reading"] == "トウキョウ" and rd["tokens"][0]["surface"] == "東京"
    assert set(asyncio.run(mcp.presets())) == {"netflix", "youtube", "vertical"}

    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="No such file"):
        asyncio.run(mcp.align(audio=str(tmp_path / "missing.wav")))
    with pytest.raises(ToolError, match="No job"):
        asyncio.run(mcp.job_status(job_id="nope"))
    bad = tmp_path / "失败.wav"
    bad.write_bytes(b"RIFF")
    with pytest.raises(ToolError, match="failed"):                       # 任务失败 = 工具报错，不是「成功」
        asyncio.run(mcp.align(audio=str(bad), script_text="こんにちは。"))


def test_mcp_schema_lists_all_tools(mcp):
    tools = {t.name: t for t in asyncio.run(mcp.mcp.list_tools())}
    assert set(tools) == {"align", "transcribe", "job_status", "reflow", "break_candidates", "reading", "presets"}
    props = tools["align"].input_schema["properties"]
    assert "ctx" not in props and {"audio", "script", "output", "also", "preset", "wait"} <= set(props)


def test_mcp_stdio_stdout_is_protocol_only(tmp_path):
    """真的启动 ``kugiri mcp``（stdio）：读音工具会导入 pyopenjtalk（可能打印提示），stdout 上只能有 JSON-RPC。"""
    pytest.importorskip("mcp")
    import shutil
    import sys

    from mcp import ClientSession, StdioServerParameters, stdio_client
    exe = shutil.which("kugiri", path=str(Path(sys.executable).parent))
    if exe is None:
        pytest.skip("kugiri 没装进当前环境")

    async def run():
        params = StdioServerParameters(command=exe, args=["mcp"], cwd=str(tmp_path))
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("reading", {"text": "東京"})
            assert not res.is_error
            assert res.structured_content["reading"] == "トウキョウ"
    asyncio.run(run())


FURI = "薔薇の煎餅を食べた。\n明日も薔薇の煎餅を食べよう。"


def test_hard_ruby_same_in_cli_web_mcp(web, mcp, tmp_path):
    """振假名 hard + 学年 + 只标第一次：网页下载、MCP 文件、CLI 和 service.render 逐字节一致。"""
    from kugiri import cli
    c, runner = web
    assert c.get("/api/config").json()["ruby_grades"] == [1, 2, 3, 4, 5, 6]
    r = c.post("/api/jobs", files={"media": ("f.mp4", b"x", "video/mp4")},
               data={"script": FURI, "ruby": "hard", "ruby_grade": "3", "ruby_once": "1"})
    jid = r.json()["id"]
    _wait_job(runner, jid)
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["options"] == {**j["options"], "ruby": "hard", "ruby_grade": 3, "ruby_once": True}
    rts = [rt for cue in j["cues"] for line in cue["display"] for _, rt in line if rt]
    assert rts.count("ばら") == 1 and rts.count("せんべい") == 1           # 只标第一次；煎餅 在 3 年级算难读
    job = runner.get(jid)
    opt = service.Options(ruby="hard", ruby_grade=3, ruby_once=True)
    web_ass = c.get(f"/api/jobs/{jid}/download/ass").text
    assert web_ass == service.render(job.out, "ass", opt)

    # 换回常用漢字表（ruby_grade=0）：煎餅 是常用汉字，不再标
    r = c.post(f"/api/jobs/{jid}/reflow", json={"cues": [{"i": k, "text": x["text"]} for k, x in enumerate(j["cues"])],
                                                "options": {"ruby": "hard", "ruby_grade": 0, "ruby_once": False}})
    rts = [rt for cue in r.json()["cues"] for line in cue["display"] for _, rt in line if rt]
    assert "せんべい" not in rts and rts.count("ばら") == 2 and r.json()["options"]["ruby_grade"] is None
    for bad in ("x", 7, True):
        assert c.post(f"/api/jobs/{jid}/reflow", json={"options": {"ruby": "hard", "ruby_grade": bad}}).status_code == 400
    # 换成 all 时学年自动丢掉（不报错）
    assert c.post(f"/api/jobs/{jid}/reflow", json={"options": {"ruby": "all"}}).json()["options"]["ruby_grade"] is None

    # 同一份字幕：CLI 和 MCP reflow
    src = tmp_path / "in.json"
    src.write_text(formats.dumps(job.out, "json"), encoding="utf-8")
    p = tmp_path / "cli.vtt"
    args = ["--ruby", "hard", "--ruby-grade", "3", "--ruby-once"]
    assert cli.main(["reflow", str(src), "-o", str(p), *args]) == 0
    res = asyncio.run(mcp.reflow(input=str(src), output=str(tmp_path / "mcp.vtt"), ruby="hard", ruby_grade=3,
                                 ruby_once=True))
    assert Path(res["output"]).read_text(encoding="utf-8") == p.read_text(encoding="utf-8")
    assert p.read_text(encoding="utf-8").count("<rt>ばら</rt>") == 1
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="hard"):
        asyncio.run(mcp.reflow(input=str(src), output=str(tmp_path / "x.vtt"), ruby="all", ruby_grade=3))
    rd = asyncio.run(mcp.reading(text="薔薇と東京"))
    assert [t["hard"] for t in rd["tokens"]] == [True, False, False]
    d = tmp_path / "d.tsv"
    d.write_text("東京\tとうきょう\t1\n", encoding="utf-8")
    rd = asyncio.run(mcp.reading(text="薔薇と東京", user_dict=str(d)))
    assert [t["hard"] for t in rd["tokens"]] == [True, False, True]       # 词典里有读音的词 hard 模式也标

    # align 也带这几个参数，和 render 一致
    audio = tmp_path / "f.wav"
    audio.write_bytes(b"RIFF")
    res = asyncio.run(mcp.align(audio=str(audio), script_text=FURI, output=str(tmp_path / "f.vtt"), ruby="hard",
                                ruby_grade=3, ruby_once=True))
    job = next(j for j in mcp.runner().jobs.values() if j.audio == str(audio))
    assert job.opt.ruby_grade == 3 and job.opt.ruby_once
    assert Path(res["outputs"]["vtt"]).read_text(encoding="utf-8") == service.render(job.out, "vtt", opt)
