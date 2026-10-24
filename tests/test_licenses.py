"""运行时依赖不能有 GPL（项目规矩：产品依赖只用 MIT / BSD / Apache 等宽松许可）。"""
from __future__ import annotations

import importlib.util
import re
from importlib.metadata import PackageNotFoundError, distribution

from packaging.requirements import Requirement


def _runtime_deps(name: str, seen: set[str], extras: tuple[str, ...] = ("",)) -> None:
    key = re.sub(r"[-_.]+", "-", name).lower()
    if key in seen:
        return
    seen.add(key)
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        return
    for r in dist.requires or []:
        req = Requirement(r)
        if req.marker is None or any(req.marker.evaluate({"extra": e}) for e in extras):
            _runtime_deps(req.name, seen)


# 许可证字段里出现 GPL 字样但本身不是 GPL 的包：numpy < 2.3 把整份 LICENSE 塞进 License 字段，里面提到 wheel 自带的
# libgfortran（GPL-3 + GCC Runtime Library Exception，允许随非 GPL 程序分发）；numpy 本身是 BSD-3-Clause
_OK = {"numpy"}


def test_no_gpl_runtime_dependencies():
    seen: set[str] = set()
    _runtime_deps("kugiri", seen, ("", "align", "asr", "fonts", "web", "mcp"))   # 可选依赖（torch、transformers、mcp 等）也算
    assert "sudachipy" in seen and "pyopenjtalk-plus" in seen
    assert "torch" in seen or importlib.util.find_spec("torch") is None   # 没装 [align] 时不强求
    assert "transformers" in seen or importlib.util.find_spec("transformers") is None
    assert "mcp" in seen or importlib.util.find_spec("mcp") is None
    assert "starlette" in seen or importlib.util.find_spec("starlette") is None
    assert "soynlp" not in seen and "qwen-asr" not in seen
    bad = []
    for name in seen - _OK:
        try:
            meta = distribution(name).metadata
        except PackageNotFoundError:
            continue
        text = " ".join(filter(None, [meta.get("License"), meta.get("License-Expression"),
                                      *meta.get_all("Classifier", [])]))
        if re.search(r"\b(A|L)?GPL\b|GNU (Lesser |Affero )?General Public", text):
            bad.append((name, text[:120]))
    assert not bad, bad
