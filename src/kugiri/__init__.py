"""kugiri（区切り）：日语字幕时间轴——台本对齐、识别、断行、读音，输出 SRT / VTT / ASS / JSON。"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kugiri")
except PackageNotFoundError:        # 没安装、直接从源码跑
    __version__ = "0.0.0"
