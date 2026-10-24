"""agent 参与断行（hints）：候选断点一览、号 → 位置、标记对断行的作用、CLI / MCP 一致。"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from kugiri import formats, hints, service
from kugiri.analysis import INF
from kugiri.cli import main
from kugiri.reflow import _analyze, prepare, preset, reflow
from kugiri.textutil import NO_HEAD, NO_TAIL
from kugiri.timeline import Cue, Document

GOLD = Path(__file__).parent / "golden" / "input"
TEXT = "これもはいれないですねじゃああきらめてこれ入りますか右からもクッパのファイヤガがほらみーよ"
LINE = re.compile(r"^(\d+|end) (.*?)(?: \(pause [\d.]+s\))?$")
MARK = re.compile(r"^(\d+) ", re.M)


def _doc(text=TEXT, dur=8.0):
    return Document([Cue(0.0, dur, text, None, [], [], None)])


def _bounds(doc):
    return ["".join(c.lines) for c in doc.cues]


def test_view_numbers_only_allowed_breaks():
    p = preset("youtube")
    for name in ("spoken.vtt", "kinsoku.srt", "numbers.srt", "fragments.srt"):
        doc = formats.read(GOLD / name)
        v = hints.candidates(doc, p)
        blks = prepare(doc, p)
        assert len(v.blocks) == len(blks)
        seen = 0
        for bi, (line, blk) in enumerate(zip(v.blocks, blks)):
            if blk.text is None:
                continue
            head, *rows = line.split("\n")
            assert head.startswith(f"#{bi} ")
            ms = [LINE.match(x) for x in rows]
            assert "".join(m.group(2) for m in ms) == blk.text           # 去掉号就是原文
            assert ms[-1].group(1) == "end" and all(m.group(1) != "end" for m in ms[:-1])
            br = _analyze(blk.text, p, None)
            for m in ms[:-1]:
                b, k = v.ids[int(m.group(1))]
                assert b == bi and br.cost[k] < INF and br.kind[k] in hints.SHOWN
                assert blk.text[:k].endswith(m.group(2))                # 号 = 这一行后面的断点
                assert int(m.group(1)) == seen                         # 全局连续编号
                seen += 1
        assert seen == len(v.ids)


def test_view_shows_pauses():
    from kugiri.timeline import Unit
    text = "今日はいい天気ですねじゃあ行こう"
    us = [Unit(i, i + 1, 0.1 * i + (1.0 if i >= 10 else 0.0), 0.1 * i + 0.1 + (1.0 if i >= 10 else 0.0))
          for i in range(len(text))]
    v = hints.candidates(Document([Cue(0, 3, text, None, us, [], None)]), preset("youtube"), norm=False)
    row = next(x for x in v.text().split("\n") if "ですね" in x)
    assert row.endswith("ですね (pause 1.0s)") and "pause" not in v.text().replace(row, "")


def test_view_key_and_pages():
    doc = formats.read(GOLD / "spoken.vtt")
    a = hints.candidates(doc, preset("youtube"))
    assert a.key == hints.candidates(doc, preset("youtube")).key
    assert a.key != hints.candidates(doc, preset("vertical")).key
    assert a.key != hints.candidates(doc, preset("youtube"), mode="wrap").key
    for size in (20, 60, 10000):
        pages = a.pages(size)
        assert [n for _, ns in pages for n in ns] == list(range(len(a.ids)))     # 每个号正好一页
        got = [a.page(k, size) for k in range(len(pages))]
        assert all(g["key"] == a.key and g["pages"] == len(pages) for g in got)
        body = [x for g in got for x in g["text"].split("\n") if not x.startswith("#")]
        assert body == [x for x in a.text().split("\n") if not x.startswith("#")]  # 去掉块头后和整份一样
        for g in got:                                  # 每页都以块头开始，续页写 continued
            assert g["text"].startswith("#")
        if size == 20:
            assert len(pages) > len(a.rows) and any("(continued)" in g["text"] for g in got)
        if size == 10000:
            assert len(pages) == 1
    with pytest.raises(ValueError):
        a.page(99, 20)


def test_labels_validate():
    v = hints.candidates(_doc(), preset("youtube"))
    with pytest.raises(ValueError, match="does not match"):
        hints.labels(v, [0], key="nope")
    for bad in ([-1], [len(v.ids)], ["x"]):
        with pytest.raises(ValueError, match="unknown break numbers"):
            hints.labels(v, bad, key=v.key)
    for bad in ("12", 3, None):
        with pytest.raises(ValueError, match="must be a list"):
            hints.labels(v, bad, key=v.key)
    for bad in ([True], [1.5], ["1x"]):
        with pytest.raises(ValueError, match="unknown break numbers"):
            hints.labels(v, bad, key=v.key)
    assert hints.labels(v, ["1"], key=v.key) == hints.labels(v, [1], key=v.key)
    opt = service.Options()
    for bad in ({"sentence": [0]}, [0], {"key": "", "sentence": [0]}):    # key 必须给（防止选项变了号对不上）
        with pytest.raises(ValueError, match="key"):
            service.reflow_doc(_doc(), opt, hints=bad)
    lab = hints.labels(v, [0], [0], key=v.key)                     # 两边都给：算句界
    assert list(lab[0].values()) == ["sent"]


def test_sentence_and_keep_change_breaks():
    p = preset("youtube")
    doc = _doc()
    v = hints.candidates(doc, p)
    num = {TEXT[:k]: i for i, (_, k) in enumerate(v.ids)}
    base = _bounds(reflow(doc, p))
    assert reflow(doc, p, hints=None).cues[0].text == reflow(doc, p).cues[0].text
    # 「ですね|じゃあ」「入りますか|右からも」「ファイヤガが|ほら」是句界
    sents = [num[TEXT[:TEXT.index(x)]] for x in ("じゃあ", "右から", "ほら")]
    out = _bounds(reflow(doc, p, hints=hints.labels(v, sents, key=v.key)))
    assert out != base
    starts = {TEXT.index(x) for x in ("じゃあ", "右から", "ほら")}
    pos, cut = 0, set()
    for c in out:
        pos += len(c)
        cut.add(pos)
    assert starts & cut                          # 至少一个句界成了 cue 边界
    for c in reflow(doc, p, hints=hints.labels(v, sents, key=v.key)).cues:
        assert not any(c.text.find(x) > 0 for x in ("右から", "ほら"))   # 句界不在 cue 中间
    # keep：在 M1 原来的某个 cue 边界上标 keep，它就不再是边界
    k0 = len(base[0])
    kid = next(i for i, (_, k) in enumerate(v.ids) if k == k0)
    out2 = _bounds(reflow(doc, p, hints=hints.labels(v, [], [kid], key=v.key)))
    assert len(out2[0]) != k0


def test_hints_never_break_hard_rules():
    """号只在允许的位置，所以不管 agent 怎么标，禁则 / 数字都不会被拆开。"""
    p = preset("vertical")
    for name in ("kinsoku.srt", "numbers.srt"):
        doc = formats.read(GOLD / name)
        v = hints.candidates(doc, p)
        allids = list(range(len(v.ids)))
        for lab in (hints.labels(v, allids, key=v.key), hints.labels(v, [], allids, key=v.key)):
            out = reflow(doc, p, hints=lab)
            src = "".join(c.text for c in reflow(doc, p).cues)
            assert re.sub(r"\s", "", "".join(c.text for c in out.cues)) == re.sub(r"\s", "", src)
            for c in out.cues:
                for ln in c.lines:
                    assert ln.strip()[0] not in NO_HEAD and ln.strip()[-1] not in NO_TAIL
                assert not re.search(r"\d$", c.lines[-1].strip()) or c is out.cues[-1] or \
                    not re.match(r"\d", out.cues[out.cues.index(c) + 1].text)


def test_cli_show_breaks_and_hints(tmp_path, capsys):
    src = GOLD / "spoken.vtt"
    assert main(["reflow", str(src), "--show-breaks"]) == 0
    out = capsys.readouterr().out
    key = out.splitlines()[0].split(": ")[1]
    nums = [int(x) for x in MARK.findall(out)]
    h = tmp_path / "h.json"
    h.write_text(json.dumps({"key": key, "sentence": nums[::3], "keep": nums[1::5]}), encoding="utf-8")
    o = tmp_path / "o.srt"
    assert main(["reflow", str(src), "--hints", str(h), "-o", str(o)]) == 0
    opt = service.Options()
    doc = formats.read(src)
    want = service.render(service.reflow_doc(doc, opt, hints=json.loads(h.read_text())), "srt", opt)
    assert o.read_text(encoding="utf-8") == want
    assert main(["reflow", str(src), "--hints", str(h), "--preset", "vertical"]) == 1   # key 对不上
    h.write_text(json.dumps({"sentence": "12"}), encoding="utf-8")
    assert main(["reflow", str(src), "--hints", str(h)]) == 1                          # 格式不对：报错不崩
    assert main(["reflow", str(src), "--show-breaks", "-o", str(tmp_path / "b.txt")]) == 0
    assert (tmp_path / "b.txt").read_text(encoding="utf-8").startswith(f"key: {key}\n")


def test_mcp_break_candidates_and_reflow(tmp_path):
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from kugiri import mcp_server as m
    src = GOLD / "spoken.vtt"
    pg = asyncio.run(m.break_candidates(input=str(src), preset="netflix"))
    assert pg["page"] == 0 and pg["pages"] >= 1 and pg["numbers"] > 0 and "reflow" in pg["next"]
    nums = [int(x) for x in MARK.findall(pg["text"])]
    r = asyncio.run(m.reflow(input=str(src), output=str(tmp_path / "a.srt"), preset="netflix",
                             hints_key=pg["key"], sentence=nums[::2]))
    assert r["hints"] == {"sentence": len(nums[::2]), "keep": 0}
    opt = service.Options(preset="netflix")
    want = service.reflow_doc(formats.read(src), opt, hints={"key": pg["key"], "sentence": nums[::2]})
    assert Path(r["output"]).read_text(encoding="utf-8") == service.render(want, "srt", opt)
    with pytest.raises(ToolError, match="hints_key"):
        asyncio.run(m.reflow(input=str(src), sentence=[0]))
    with pytest.raises(ToolError, match="does not match"):
        asyncio.run(m.reflow(input=str(src), output=str(tmp_path / "b.srt"), preset="youtube",
                             hints_key=pg["key"], sentence=[0]))
