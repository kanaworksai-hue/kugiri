"""Advanced SubStation Alpha（.ass）。

没有振假名的 cue：一条 Dialogue，行间用 ``\\N``，底部居中。
有振假名的 cue：每行一条 ``\\an7\\pos`` 定位的 Dialogue，每个振假名一条 ``\\an2\\pos`` 定位到汉字正上方
（Aegisub 卡拉OK 的 ``|<`` 语法播放器不认，必须自己算位置，M0 已用 libass 验证）。
字宽默认按全角 1 em / 半角 0.5 em 估算；给 ``font_file`` 时用 fontTools 读真实字宽（``pip install kugiri[fonts]``）。
"""
from __future__ import annotations

import re

from ..textutil import is_half
from ..timeline import Document
from .common import clean_line, make_cue, rendered_lines

_DRAWING = re.compile(r"\{[^}]*\\p[1-9]")
_POS = re.compile(r"\{[^}]*\\pos\(")


def _parse_ts(s: str) -> float:
    h, m, sec = s.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def parse(text: str) -> Document:
    """读 ASS / SSA 的 [Events] 里的 Dialogue（Comment、绘图、振假名样式 ``Ruby`` 的行跳过）。
    ``\\N`` 是换行；同一时间、同一说话人、都用 ``\\pos`` 定位的几条 Dialogue（kugiri 带振假名的输出每行一条）合成一条 cue。"""
    fields: list[str] | None = None
    section = ""
    raw: list[tuple[float, float, list[str], str, bool]] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("["):
            section = line.lower()
            continue
        if section != "[events]":
            continue
        if line.lower().startswith("format:"):
            fields = [x.strip().lower() for x in line.split(":", 1)[1].split(",")]
            continue
        if not line.startswith("Dialogue:"):
            continue
        f = fields or ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
        vals = line.split(":", 1)[1].split(",", len(f) - 1)
        if len(vals) < len(f):
            continue
        ev = dict(zip(f, (v.strip() if k != "text" else v for k, v in zip(f, vals))))
        body = ev.get("text", "")
        if ev.get("style", "").lower() == "ruby" or _DRAWING.search(body):
            continue
        try:
            s, e = _parse_ts(ev["start"]), _parse_ts(ev["end"])
        except (KeyError, ValueError):
            continue
        lines = [clean_line(x.replace("\\h", " ")) for x in re.split(r"\\[Nn]", body)]
        name = ev.get("name", "").strip()
        pos = bool(_POS.search(body))
        if raw and pos and raw[-1][4] and raw[-1][:2] == (s, e) and raw[-1][3] == name:
            raw[-1][2].extend(lines)          # 定位好的逐行 Dialogue（kugiri 带振假名的输出）合回一条
        else:
            raw.append((s, e, lines, name, pos))
    cues = [c for s, e, lines, name, _ in sorted(raw, key=lambda r: r[0])
            if (c := make_cue(s, e, lines, name or None))]
    cues.sort(key=lambda c: c.start)
    return Document(cues)


def _ts(t: float) -> str:
    cs = max(0, round(t * 100))
    h, r = divmod(cs, 360000)
    m, r = divmod(r, 6000)
    s, cs = divmod(r, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(s: str) -> str:
    return s.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


class Metrics:
    """字宽（像素）。"""

    def __init__(self, font_file: str | None = None, font_name: str | None = None):
        self.font = None
        key = (font_name or "").lower()
        self.em = next((v for k, v in self.KNOWN_EM.items() if key.startswith(k)), self.EM_PER_FS)
        if font_file:
            try:
                from fontTools.ttLib import TTCollection, TTFont
            except ImportError as e:
                from ..service import install_hint
                raise ValueError(f"--font-file needs the [fonts] extra: {install_hint('fonts')}") from e

            try:
                if font_file.lower().endswith((".ttc", ".otc")):
                    fonts = TTCollection(font_file).fonts
                    self.font = next((f for f in fonts if font_name and f["name"].getDebugName(4) == font_name),
                                     fonts[0])
                else:
                    self.font = TTFont(font_file)
                os2 = self.font["OS/2"]
            except OSError:
                raise
            except Exception as e:          # fontTools 的 TTLibError / KeyError 等：不是能读的字体文件
                raise ValueError(f"cannot read the font file {font_file} ({e})") from e
            self.units = os2.usWinAscent + os2.usWinDescent   # libass / VSFilter 把它缩放到 \fs
            self.cmap = self.font.getBestCmap()
            self.hmtx = self.font["hmtx"]

    # 不给字体文件时的估算：libass 把 (winAscent + winDescent) 缩放到 \fs，所以 1 em = unitsPerEm / (winAscent + winDescent) fs。
    # 常用字体按实测值（用 libass 渲染量过：按 0.72 估算时 Noto Sans JP 的振假名每行往右漂 15px 左右），
    # 其他字体用 0.72；拉丁字母平均约 0.58 em，空格约 0.25 em。
    EM_PER_FS = 0.72
    KNOWN_EM = {"noto sans jp": 1000 / 1448, "noto sans cjk jp": 1000 / 1448, "hiragino sans": 1000 / 1234,
                "ヒラギノ角ゴシック": 1000 / 1234}

    # Noto Sans JP（默认字体）的 ASCII 字宽（U+0020–U+007E，单位 1/1000 em）；其他字体也拿它近似
    _ASCII = [224, 323, 474, 555, 555, 921, 680, 278, 338, 338, 467, 555, 278, 347, 278, 392, 555, 555, 555, 555,
              555, 555, 555, 555, 555, 555, 278, 278, 555, 555, 555, 474, 946, 608, 657, 638, 688, 589, 552, 689,
              728, 293, 535, 646, 543, 812, 723, 742, 633, 742, 635, 596, 599, 721, 575, 878, 573, 531, 603, 338,
              392, 338, 555, 559, 606, 563, 618, 510, 620, 554, 325, 564, 607, 275, 275, 552, 284, 926, 610, 606,
              620, 620, 388, 468, 377, 607, 521, 802, 498, 521, 475, 338, 270, 338, 555]

    @classmethod
    def _est(cls, c: str) -> float:
        if 0x20 <= ord(c) <= 0x7E:
            return cls._ASCII[ord(c) - 0x20] / 1000
        return 0.5 if is_half(c) else 1.0

    def width(self, s: str, fs: float) -> float:
        if self.font is None:
            return sum(self._est(c) for c in s) * fs * self.em
        return sum(self.hmtx[self.cmap[ord(c)]][0] if ord(c) in self.cmap else self.units for c in s) * fs / self.units


def dump(doc: Document, *, punct: str = "netflix", ruby: bool = False, play_res: tuple[int, int] = (1920, 1080),
         font: str = "Noto Sans JP", font_size: int | None = None, font_file: str | None = None,
         max_width: float = 13.0) -> str:
    W, H = play_res
    fs = font_size or int(min(H * 0.065, W * 0.85 / max(max_width, 1)))
    rfs = max(8, round(fs * 0.47))
    margin_v = round(H * 0.06)
    step = fs + round(fs * 0.55)          # 有振假名时的行距（留出振假名的空间）
    M = Metrics(font_file, font)
    head = f"""[Script Info]
; Generated by kugiri
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(2, fs // 24)},0,2,40,40,{margin_v},1
Style: Ruby,{font},{rfs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(1, rfs // 16)},0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for c in doc.cues:
        lines = rendered_lines(c, punct, ruby)
        if not lines:
            continue
        a, b = _ts(c.start), _ts(c.end)
        name = _esc(c.speaker or "").replace(",", "，")     # Name 字段里的逗号会把后面的字段挤错位
        if not any(r for line in lines for _, r in line):
            text = "\\N".join(_esc("".join(t for t, _ in line)) for line in lines)
            ev.append(f"Dialogue: 0,{a},{b},Main,{name},0,0,0,,{text}")
            continue
        n = len(lines)
        for k, line in enumerate(lines):
            top = H - margin_v - fs - (n - 1 - k) * step
            plain = _esc("".join(t for t, _ in line))      # 按转义后真正显示的字量宽度（＼｛｝是全角）
            x = W / 2 - M.width(plain, fs) / 2
            ev.append(f"Dialogue: 0,{a},{b},Main,{name},0,0,0,,{{\\an7\\pos({x:.0f},{top})}}{plain}")
            for t, r in line:
                bw = M.width(_esc(t), fs)
                if r:
                    rw = M.width(_esc(r), rfs)  # 读音比汉字宽时横向压缩（最多压到 50%），避免压到相邻的振假名
                    sx = f"\\fscx{max(50, int(100 * bw / rw))}" if rw > bw else ""
                    ev.append(f"Dialogue: 1,{a},{b},Ruby,{name},0,0,0,,"
                              f"{{\\an2\\pos({x + bw / 2:.0f},{top + round(fs * 0.2)}){sx}}}{_esc(r)}")
                x += bw
    return head + "\n".join(ev) + "\n"
