<div align="center">

<img src="docs/assets/banner-zh.jpg" alt="kugiri：按日语自然断句的字幕，任何视频都行，有没有台本都可以" width="820">

<p>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-6b4dff?style=flat-square"></a>
  <img alt="macOS Apple Silicon" src="https://img.shields.io/badge/macOS-Apple_Silicon-111?style=flat-square&logo=apple">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white">
  <a href="#-在-ai-agent-中使用mcp"><img alt="MCP server" src="https://img.shields.io/badge/MCP-server-19b8d6?style=flat-square"></a>
  <a href="#-在-ai-agent-中使用mcp"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude_Code-plugin-d97757?style=flat-square"></a>
  <img alt="Output: SRT, VTT, ASS" src="https://img.shields.io/badge/output-SRT_·_VTT_·_ASS-e5484d?style=flat-square">
  <a href="https://github.com/kanaworksai-hue/kugiri/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/kanaworksai-hue/kugiri?style=flat-square&logo=github&label=stars&color=f5c518"></a>
</p>

<p><a href="https://github.com/kanaworksai-hue"><img src="docs/brand/kanaworks-mark.png" height="22" alt="" align="absmiddle"></a>&nbsp;<a href="https://github.com/kanaworksai-hue"><b>A KanaWorks_AI project</b></a></p>

[日本語](README.md) | [English](README.en.md) | **简体中文**

[快速开始](#-快速开始) · [与其他工具对比](#-与其他工具对比) · [网页界面](#-网页界面web-ui) · [MCP](#-在-ai-agent-中使用mcp) · [修正其他工具的字幕](#-修正其他工具生成的字幕) · [⭐ Star](#-喜欢就点个-star)

</div>

**動画を入れるだけで、日本語として自然な区切りの字幕を。台本がなくても書き起こしから、台本があれば一文字単位でぴったり。**

**只要放进视频，就能得到按日语自然断句的字幕。没有台本就先转写，有台本就逐字精确对齐。**

**kugiri**（区切り，意为“在哪里切开”）从视频或音频文件生成日语字幕，**有没有台本（脚本/稿子）都可以**。
没有台本？它会先做语音识别转写（Qwen3-ASR，带标点），之后你可以再改字。
有台本？台本会和音频逐字对齐。无论哪种，断行都落在日语自然的切分处（文节边界），数字和单位不会被拆开，
输出 SRT / VTT / ASS（可选带振假名）。
全部在你自己的 Mac 上运行：浏览器里、AI agent 里、命令行里都能用。

## ✨ 亮点

<table>
<tr>
<td align="center" width="25%">🎙️<br><b>台本可选</b><br><sub>把日语语音转写成带标点的文字，或把你的台本和音频逐字对齐</sub></td>
<td align="center" width="25%">✂️<br><b>自然断行</b><br><sub>在日语短语边界断行并遵守禁则；数字和单位不拆开</sub></td>
<td align="center" width="25%">🤖<br><b>Web UI + MCP + CLI</b><br><sub>浏览器、Claude Code（plugin）及其他 MCP 客户端、你自己的脚本，用的都是同一个引擎</sub></td>
<td align="center" width="25%">🔒<br><b>本地运行</b><br><sub>在 Apple Silicon 上运行。视频不会上传；不需要 API key，不花钱</sub></td>
</tr>
</table>

- **振假名：** 给所有汉字词标注，或只标难读词（常用漢字表以外的），或按小学年级给儿童内容标注。
- **修正其他工具的字幕：** `kugiri reflow` 可以重新断行 Vrew、CapCut、Premiere、
  DaVinci Resolve、Subtitle Edit、WhisperX 或 YouTube 自动字幕输出的 SRT / VTT / JSON，不需要任何模型。
- **质检：** 台本和音频对不上的地方会连同时间一起列出来。
- **预设：** YouTube、竖屏 Shorts / TikTok、Netflix 日语风格。

状态：beta。**第一版只支持 Apple Silicon 的 macOS**（M1 及以后，macOS 14+）。

## 🚀 快速开始

需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)（`brew install uv`）；处理 WAV 以外的格式
还需要 ffmpeg（`brew install ffmpeg`）。然后：

```sh
uvx --python 3.12 --from 'kugiri[all]' kugiri web     # 在 http://localhost:7790/ 打开网页界面
```

第一次启动会下载约 1 GB 的 Python 包（PyTorch），然后下载模型（对齐 1.3 GB，转写 4.1 GB），
所以要等几分钟；页面上会显示下载进度。之后一切都在你的 Mac 上离线运行。拖入视频，有台本就粘贴进去
（留空则自动转写），然后下载字幕。

## 📊 与其他工具对比

大多数字幕工具按字数给日语断行。kugiri 按日语短语边界断行：
行首不出现 、。」，数字不和单位拆开，尽量一条字幕一句话。

![The same Japanese clip broken into subtitles by WhisperX, Subtitle Edit, clipwright-wrap and kugiri](docs/compare-line-breaks.png)

*自家演示片段（合成语音），所有工具都限制为 16 字 × 2 行，用 libass 渲染。
WhisperX 3.8（large-v3-turbo）：`--max_line_width 16 --max_line_count 2`。Subtitle Edit 5.3：对
WhisperX 的转写稿使用“Split/break long lines”，行长设为 16（默认 43）。clipwright-wrap 0.3：默认设置（16 × 2），
输入为一句一条，因为它只在收到的字幕条内部重新换行，从不拆分字幕条。
kugiri：对 WhisperX 的 JSON 运行 `kugiri reflow`。值得注意的断点：`12,8｜00円`、以 `、` 开头的行（WhisperX）、
`思｜います`、`ライ｜ブ配信`（Subtitle Edit）、超出画面宽度的行（clipwright-wrap）。*

**时间精度。** 把台本对齐到语音，在 24 段带人工打轴字幕的日语 TEDx 演讲（每段一分钟）上测量
（[TEDxJP-10K](https://github.com/laboroai/TEDxJP-10K)）：每条字幕的起点和终点与人工时间相差多少。

| | 平均误差 | 起点误差在 300 ms 内 | 终点误差在 300 ms 内 |
|---|---|---|---|
| kugiri `align` | 149 ms | 96% | 82% |
| WhisperX 对齐（`wav2vec2-large-xlsr-53-japanese`），相同文本 | 324 ms | 91% | 37% |

两者拿到的是同样的一分钟文本和音频（WhisperX 作为单个 segment 输入，不使用 Whisper 自己的粗略 segment
时间）。人工字幕在语音前后都留了一点静音，所以每个工具的误差里都有一部分来自参考答案本身。Subtitle Edit 5
也能对齐纯文本台本；它用强制对齐器确定每行的起点，终点按阅读速度推算，所以行的终点并不是从音频里得来的。

## 🧭 功能

- `kugiri align`：音频或视频 → 自然断行的日语字幕。没有台本时先转写语音
  （Qwen3-ASR，带标点）；有台本就跳过这一步。无论哪种文本，都会和音频逐字对齐
  （omniASR CTC 300M 强制对齐，整个文件一次完成，无需手动切分）。
- `kugiri reflow`：不用模型的断行引擎，处理已经有时间轴的字幕——包括其他工具生成的字幕
  （Vrew、CapCut、Premiere、DaVinci Resolve、Subtitle Edit、WhisperX、YouTube）。
- 导出 SRT / WebVTT / ASS / 时间轴 JSON。

### 对齐

- 整个文件用一次 Viterbi 完成对齐，长录音也不需要做台本↔音频的分块匹配。
  30 分钟的文件在 16 GB 的 Mac 上也很轻松（带检查点的 Viterbi，只保留台本里用到的字符）。
- 数字、拉丁字母词（`AI`、`iPhone`）、模型词表外的字符和用户词典里的词，按读音对齐
  （`2026` → にせんにじゅうろく），并作为一个带 `reading` 的单元输出。
- 短语末尾的时间用音频包络修正（拖长的尾音上，CTC 尖峰结束得太早）。
- 质检：台本和音频对不上的片段（漏字 / 多字、多人同时说话、噪音）会连同时间列出来，
  受影响的字幕条在 JSON 里标记为 `low_confidence`。

### 语音识别（无台本）

- Qwen3-ASR 1.7B（Apache-2.0），使用 Hugging Face `transformers` 的原生实现，
  带标点（、。？）。音频在停顿处切成 ≤20 秒的块，分批解码。
- 防幻觉：每块的 token 上限、重复检查和语速检查。可疑的块会回退到对齐模型自己的贪心转写结果
  （CTC 模型编不出文字），并加上标记。
- `--save-script` 把转写稿按一句一行写出：改好后用 `--script` 重新运行。

### 断行

- 禁则（行首不出现 、。っー」，行尾不出现 「（），带单位的数字绝不拆开
  （`2026年10月20日`、`1,500円`、`2.5GB`），短括号保持完整。
- 基于 SudachiPy 的文节感知断点代价，两层动态规划（字幕条切分 × 行内换行），
  偏好“一条字幕一句话”，无标点的口语也一样（〜ました|〜です）。
- 时间规则：最短 / 最长显示时长，字幕停留足够的阅读时间（最多到说话结束后 1.5 秒），
  2 帧间隔，短空隙合并，对齐到整帧。
- 读音用 pyopenjtalk-plus；用户词典可以覆盖读音、禁止在词内断开。
- 振假名：ASS（定位好的振假名行，可在基于 libass 的播放器里显示；位置默认按 Noto Sans JP 的字宽计算，
  用其他字体时请传 `--font-file`）、WebVTT `<ruby>`（需手动开启；只在浏览器里正常显示，基于 ffmpeg 的播放器
  会把读音显示在汉字后面）。`--ruby all` 给所有汉字词标注；`--ruby hard` 只标难读的词——
  常用漢字表以外的汉字或表里没有的读法（薔薇、流石、辛い = つらい）——
  `--ruby-grade N` 再加上小学 N 年级还没学过的汉字（学年別漢字配当表），适合儿童和学习者内容。
  `--ruby-once` 每个词只在第一次出现时标注（Netflix 风格）。
- SRT 输出会把 `< > { } \` 换成全角字符，因为大多数播放器会把它们当成标记。

## 📦 安装

需要 Apple Silicon 上的 macOS 14 或更高版本，以及 Python 3.11 或更高版本。有 [uv](https://docs.astral.sh/uv/) 的话，
一行命令就能试用，无需任何配置：

```sh
uvx --python 3.12 --from 'kugiri[all]' kugiri web   # 在 http://localhost:7790/ 打开网页界面
```

如果 Mac 上只有系统自带的 Python 3.9，`--python 3.12` 会让 uv 自己下载一个 Python（3.11+ 都可以）。
想保留 `kugiri` 命令：

```sh
uv tool install --python 3.12 'kugiri[all]'   # 或者在 Python 3.11+ 环境里：pip install 'kugiri[all]'
uv tool update-shell                          # 只需一次，当 uv 提示 ~/.local/bin 不在 PATH 里时
kugiri --help
```

| 安装 | 包含内容 |
|---|---|
| `kugiri` | `kugiri reflow`（修正 / 重新断行已有字幕）、`reading`、`presets`。不含模型；下载约 110 MB（词典） |
| `kugiri[align]` | + 带台本的 `kugiri align`（PyTorch） |
| `kugiri[asr]` | + 没有台本时的语音识别转写 |
| `kugiri[web]` / `kugiri[mcp]` | + 网页界面 / MCP server（都包含 `asr`） |
| `kugiri[all]` | 全部，外加 fonttools，用于精确计算 ASS 里振假名的位置 |

带 PyTorch 时包大约 1 GB；第一次 `uvx` / 安装需要几分钟。Intel Mac 装不了带 PyTorch 的 extras
（PyTorch 已不再提供 Intel macOS 版本）；只装 `kugiri`（`reflow`）可以用。

**模型在第一次使用时下载，只下载一次**，之后可离线使用：

| 模型 | 用途 | 大小 | 存放位置 |
|---|---|---|---|
| omniASR CTC 300M v2（Meta，Apache-2.0） | 对齐（`align`、网页界面、MCP） | 1.3 GB | `~/.cache/kugiri/models`（`KUGIRI_MODEL_DIR`） |
| Qwen3-ASR 1.7B（Apache-2.0） | 无台本时的转写 | 4.1 GB | Hugging Face 缓存（`HF_HOME`） |
| Qwen3-ASR 0.6B（`--asr-model qwen3-0.6b`） | 更快、更省内存 | 1.6 GB | Hugging Face 缓存 |

终端、网页界面和 MCP 的进度消息会显示正在下载什么、下载到哪里了。下载中断后再次运行会从断点续传。
镜像：`KUGIRI_MODEL_URL`（omniASR 文件的基础 URL）和 `HF_ENDPOINT`。`kugiri web` 启动时就会下载并加载两个模型
（`--warm none` 等到第一个任务再加载，`--warm qwen3-0.6b` 使用较小的识别模型）。

模型用纯 PyTorch 运行（不需要 fairseq2），跑在 Apple GPU 上（MPS；`--device cpu` 也能用，但很慢）。
16 GB 的 Apple Silicon Mac 就够了，长录音也一样。WAV 直接读取；其他音频 / 视频格式需要 `PATH` 里有 `ffmpeg`（`brew install ffmpeg`，
或用 `KUGIRI_FFMPEG` 指定）。Linux、Windows 和 NVIDIA GPU（`--device cuda`）还没有测试过。

## 🌐 网页界面（Web UI）

```sh
kugiri web                 # 打开 http://localhost:7790/（只有本机能连接）
```

1. 拖入视频或音频文件。台本可选（粘贴或载入 `.txt`）；没有台本时先对音频做转写。
2. 选择预设（YouTube 横屏 / 竖屏 Shorts / Netflix）、识别模型和振假名。
3. 按步骤显示进度（转写 → 对齐 → 断行）。任务一次只跑一个，其余排队等待；
   处理长文件时页面仍然可以正常使用。
4. 结果页播放视频并叠加字幕。在列表里修改任意一行，然后点 **重新断行**
   （立即完成）或 **按修改重新对齐**（你的文字作为台本，重新计算时间）。
5. “要检查的地方”列出台本和音频似乎对不上的位置；点击即可跳过去。
6. 在转写稿 / 台本标签页可以下载转写稿、修改它（或载入 `.txt`），再用它重新对齐。
   用户词典（读音、不能拆开的词）在页面顶部编辑。
7. 下载 SRT / VTT / ASS / JSON / 台本 `.txt`。

模型在服务器启动时加载并常驻内存（下一个文件可以立刻开始）。
`--warm qwen3-0.6b` / `--warm none` 启动时只加载较小的识别模型，或什么都不加载。上传的文件和
用户词典存放在 `~/.cache/kugiri/web`（用 `KUGIRI_HOME` 或 `--data-dir` 修改；超过 7 天的任务
在启动时删除）。界面有日语和英语。服务器只响应发给 localhost 的请求，并拒绝来自其他网站的修改请求；
`--host 0.0.0.0` 会向你的局域网开放（没有登录）。

## 🤖 在 AI agent 中使用（MCP）

`kugiri mcp` 是一个 MCP server（stdio，官方 Python SDK）。工具：

| 工具 | 作用 |
|---|---|
| `align` | 音频 / 视频（+ 可选台本）→ 字幕文件；返回输出路径、字幕条数和质检报告 |
| `transcribe` | 语音 → 只输出文字（一句一行，写入 `.txt`） |
| `job_status` | 用 `wait=false` 启动的任务的状态 |
| `reflow` | 对已有的 SRT / VTT / JSON 字幕重新切分 / 重新换行（可附带 agent 标的句界） |
| `break_candidates` | 允许的断点，带编号，让 agent 按意思标出句末 |
| `reading` | 句子的假名读音（会查用户词典） |
| `presets` | 各预设的参数 |

输入和输出都是本地文件路径。默认情况下 `align` 会在音频旁边写出 `<name>.kugiri.srt`（转写时还有
`<name>.kugiri.script.txt`），所以你自己的 `<name>.srt` 不会被覆盖；显式指定的 `output` 路径会被覆盖。
长任务会发送 MCP 进度通知；如果你的客户端在长调用上超时，就传 `wait=false` 并轮询 `job_status`。
模型在第一次调用时加载，之后常驻。

**请先安装一次 Python 包。** MCP 客户端只会等 server 启动约 30 秒，
而第一次 `uvx` 运行要安装约 1 GB（PyTorch），用时更长：

```sh
uvx --python 3.12 --from 'kugiri[mcp]' kugiri --version
```

模型在第一次调用 `align` / `transcribe` 时下载（见[安装](#-安装)）；那次调用只是会慢一些，
并带有进度消息。

**Claude Code** —— 作为 plugin 安装（一步完成，需要 Claude Code 2.1.275 或更高版本）：

```
/plugin install kugiri --marketplace kanaworksai-hue/kugiri
```

旧版本：先 `/plugin marketplace add kanaworksai-hue/kugiri`，再 `/plugin install kugiri@kugiri`。
或者只添加 MCP server：

```sh
claude mcp add kugiri -- uvx --python 3.12 --from 'kugiri[mcp]' kugiri mcp
claude mcp add kugiri -- kugiri mcp          # 如果你是用 uv tool install / pip 安装的
```

**Claude Desktop**（`~/Library/Application Support/Claude/claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "kugiri": {
      "command": "/absolute/path/to/uvx",
      "args": ["--python", "3.12", "--from", "kugiri[mcp]", "kugiri", "mcp"],
      "env": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
    }
  }
}
```

Claude Desktop 启动 server 时几乎不带环境变量：请使用 `uvx` 的绝对路径（`which uvx`），
并确保 `PATH` 里有 `ffmpeg`（用于非 WAV 输入）。如果模型放在别处，也要在 `env` 里加上
`"HF_HOME"` / `"KUGIRI_MODEL_DIR"`。

**其他 MCP 客户端**（Cursor、VS Code、Codex CLI 等）运行同样的 stdio 命令：
`uvx --python 3.12 --from 'kugiri[mcp]' kugiri mcp`。从 Dock 启动的应用可能看不到 `~/.local/bin`，
所以无论在哪里，用 `uvx` 的绝对路径最保险。Cursor（`.cursor/mcp.json`）使用上面 Claude Desktop 的格式；
VS Code（`.vscode/mcp.json`）：

```json
{"servers": {"kugiri": {"type": "stdio", "command": "uvx", "args": ["--python", "3.12", "--from", "kugiri[mcp]", "kugiri", "mcp"]}}}
```

Codex CLI（`~/.codex/config.toml`；第一次带模型下载的 `align` 或长文件，用时会超过
Codex 默认的工具超时）：

```toml
[mcp_servers.kugiri]
command = "uvx"
args = ["--python", "3.12", "--from", "kugiri[mcp]", "kugiri", "mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 1800
```

然后就可以这样说：“用台本 ~/Movies/talk.txt 给 ~/Movies/talk.mp4 做 YouTube 字幕，再出一份
带振假名的 ASS 文件。”

### 让 agent 按意思判断句界

日语口语经常没有标点（「〜ですねじゃあ次は〜」），一句话在哪里结束、下一句从哪里开始，没有规则能判断。
用 MCP 时 agent 可以：`break_candidates` 列出规则允许的所有断点，一行一个短语并带编号；
agent 标出句末，传给 `reflow`（`hints_key`、`sentence`，很少用到 `keep`）。切分、换行和时间仍由 kugiri 完成，
agent 只能在允许的位置里选，所以禁则、带单位的数字和括号都不会被破坏。它用的是 agent 自己的模型；
kugiri 不调用任何 LLM API。处理音频时，先用 `align` 输出 `.json`，再对这个 JSON 做 reflow。效果取决于
agent 的模型：Claude Opus 这类强模型判断句界明显比小模型好，小模型的结果和只用 kugiri 规则差不多。
比如可以这样说：
“用 kugiri 修正 ~/Movies/talk.srt 的断行，句末由你自己来标。”

## 🩹 修正其他工具生成的字幕

已经有其他工具做好的日语字幕？`kugiri reflow` 一条命令就能把它们变成断行规范的日语字幕。
它不会重新识别语音：只重新切分字幕条、重新换行并应用时间规则，所以不需要模型，一秒钟就完成
（不带 extras 的 `kugiri` 就够了：`uvx --python 3.12 kugiri reflow …`）。

```sh
kugiri reflow from-vrew.srt --preset youtube -o fixed.srt
kugiri reflow whisperx-output.json --preset vertical -o shorts.srt   # WhisperX JSON：使用其中的逐字时间
kugiri reflow video.ja.vtt --preset youtube -o fixed.srt            # YouTube 自动字幕（yt-dlp --write-auto-subs）
```

![WhisperX SRT vs kugiri reflow](docs/reflow-before-after.png)

*自家演示片段（合成语音）。左：WhisperX 原样输出的 SRT（日语默认没有行长限制，所以这是一整条
29 秒的字幕）。右：同一个文件经过 `kugiri reflow --preset youtube` 之后。
识别错误（句読点 被识别成 苦闘店）不会被改动——请在结果里改字，或者带台本使用 `kugiri align`。*

输入端能处理的情况：

| 输入 | 处理方式 |
|---|---|
| 很长的单行字幕条、只有几个字的字幕条、没有标点（Vrew、CapCut、Premiere、Resolve） | 合并后按日语短语边界重新切分，尽量一条字幕一句话 |
| YouTube 自动字幕（`.vtt`） | 滚动的两行字幕去重，丢掉 10 ms 的过渡字幕条，使用 `<c>` 里的词级时间 |
| WhisperX / openai-whisper / stable-ts JSON、whisper.cpp JSON | `segments[].words` 转成逐字时间（没有时间的数字跟随相邻字符），保留 `speaker` |
| 逐词高亮的 SRT（WhisperX `--highlight_words`、卡拉 OK 式导出） | 重复的字幕条合并成一条 |
| 词之间有空格的日语（今日 は 天気 が） | 去掉空格（仅当整个文件都是这种写法时；代替 、。 的 Netflix 式空格会保留） |
| `.ass` / `.ssa`（Aegisub、Subtitle Edit） | 读取带 `\N` 换行的 `Dialogue` 事件；忽略特效标签、注释和绘图；`Name` = 说话人 |
| 带或不带 BOM 的 UTF-8、UTF-16、Shift_JIS；CRLF；行尾多余空格 | 原样读取 |
| `（拍手）` / `[音楽]` / `♪～` 字幕条、两人对话字幕条（`-行こう` / `-うん`）、`>> 名前` | 保持为单独的字幕条；放不下的两人对话字幕条拆成每人一条 |

Vrew、CapCut、Premiere Pro 和 DaVinci Resolve 的格式我们拿不到真实文件；它们的测试输入
（`tests/golden/input/`）是根据公开文档 / 用户反馈的行为手写的（很长或很短、没有标点的字幕条，
行尾空格、BOM、CRLF）。WhisperX 和 YouTube 自动字幕用真实输出验证过。如果你的工具导出的文件
处理结果不对，欢迎附上样本提 issue。

## ⌨️ 用法

```sh
kugiri align talk.wav --script talk.txt -o talk.srt        # talk.txt 中一行一个段落
kugiri align talk.mp4 --script talk.txt --preset vertical -o talk.ass --ruby all
kugiri align talk.wav --script talk.txt -o talk.json       # 带逐字时间和质检报告的时间轴 JSON
kugiri align interview.wav --script script.txt --speakers -o out.vtt   # 行首的“名前：…” / “>> 名前”
kugiri align talk.wav -o draft.srt --save-script draft.txt # 无台本：转写（Qwen3-ASR）→ 对齐 → 断行
kugiri reflow in.srt --preset youtube -o out.srt          # 重新切分 + 重新换行，应用时间规则
kugiri reflow in.vtt --preset netflix --mode wrap -o out.vtt   # 保留每条字幕及其时间，只重新换行
kugiri reflow in.srt --preset vertical --ruby all --dict words.tsv -o out.ass
kugiri reflow in.srt --ruby hard --ruby-once -o out.ass    # 只给难读词标振假名，且只标第一次
kugiri reflow in.srt --ruby hard --ruby-grade 3 -o out.vtt # 儿童：小学三年级还没学过的汉字
kugiri reflow in.srt --show-breaks > breaks.txt           # 带编号的断点（即 MCP break_candidates 显示的内容）
kugiri reflow in.srt --hints marks.json -o out.srt        # {"key": …, "sentence": [3, 9, …], "keep": []}
kugiri reading "東京の夜は静かです" --tokens
kugiri presets
kugiri web                                            # 本地网页界面
kugiri mcp                                            # MCP server（stdio）
```

预设：

| 预设 | 每行字数 | 行数 | 阅读速度 | 显示时长 | fps |
|---|---|---|---|---|---|
| `netflix` | 13 | 2 | 4 cps | 0.5–7 s | 24 |
| `youtube` | 16 | 2 | 6 cps | 0.7–7 s | 30 |
| `vertical`（Shorts / TikTok） | 10 | 2 | 6 cps | 0.5–5 s | 30 |

宽度按全角 1、半角 0.5 计算。标点默认按 Netflix 日语风格处理
（、 → 半角空格，。 → 全角空格）；用 `--punct keep` 保留原样。

### 用户词典（TSV）

```
# 表記	読み	禁止分割
東京AI映像合同会社	とうきょうえーあいえいぞうごうどうがいしゃ	1
VRChat	ぶいあーるちゃっと
明日	あす	0
```

第 3 列默认为 `1`（不在这个词内部断开）；`0` 表示允许断开。

台本小贴士：一行一个段落；标点有助于断行，但不是必需的。不念出来的舞台说明
（`（拍手）`）应删掉，否则会被报告为不一致。内置转写只是为了方便出初稿；想要更好的结果，
可以用你喜欢的 ASR 转写，把改好的文字通过 `--script` 传入。

### 时间轴 JSON

`kugiri-timeline` v1 是交换格式（字幕条、逐字 / 逐词时间、读音、置信度、
振假名）。Schema：`src/kugiri/schema/timeline.schema.json`。当输入 JSON 带有 `units`
（例如来自 `kugiri align`）时，切分会使用这些时间，而不是在字幕条内部插值。`kugiri align`
还会写出 `meta.align`（模型、设备、实时率、`warnings`）和每条字幕的 `flags`。

## 🛠️ 开发

```sh
uv sync --all-groups --all-extras
uv run pytest            # 需要模型的测试只在模型位于 KUGIRI_MODEL_DIR 时运行
KUGIRI_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py   # 有意修改后重新生成黄金文件
```

所有运行时依赖都是宽松许可（SudachiPy / SudachiDict：Apache-2.0，
pyopenjtalk-plus：MIT，OpenJTalk / naist-jdic：BSD；可选的 PyTorch：BSD-3-Clause，omniASR 权重：
Apache-2.0，transformers：Apache-2.0，Qwen3-ASR 权重：Apache-2.0；网页界面：Starlette / uvicorn BSD-3-Clause，
python-multipart Apache-2.0；MCP：官方 `mcp` SDK MIT）。不允许使用 GPL 依赖
（没有使用官方的 `qwen-asr` 包，因为它依赖 GPLv3 的 `soynlp`）。
`src/kugiri/data/` 里的汉字表来自常用漢字表（内閣告示，2010）和学年別漢字配当表
（文部科学省告示，2017）；在日本，政府告示不受著作权保护（著作権法 第13条）。
`tools/build_kanji.py` 可从官方 PDF 重新生成这些数据。详细信息和模型许可见
[THIRD_PARTY.md](THIRD_PARTY.md)。

## ⭐ 喜欢就点个 Star

如果 kugiri 帮你在日语字幕上省了时间，在 GitHub 上点个 star 能让更多人找到它。非常欢迎在
[Issues](https://github.com/kanaworksai-hue/kugiri/issues) 里报告 bug、提交处理结果不对的样本文件。

<a href="https://github.com/kanaworksai-hue/kugiri/stargazers"><img alt="Star kugiri on GitHub" src="https://img.shields.io/github/stars/kanaworksai-hue/kugiri?style=social"></a>

## 📄 许可与致谢

代码和文档：[MIT](LICENSE) © 東京AI映像合同会社。模型和数据来源：[THIRD_PARTY.md](THIRD_PARTY.md)。
KanaWorks_AI 的名称、标志和角色 Kana（`docs/brand/` 中及横幅图里的）不在 MIT 许可范围内；
详见 [docs/brand/README.md](docs/brand/README.md)。

<div align="center">
<br>
<a href="https://github.com/kanaworksai-hue"><img src="docs/brand/kana-wave.png" width="120" alt="KanaWorks_AI 的吉祥物 Kana 在挥手"></a>
<br>
<sub>由 <a href="https://github.com/kanaworksai-hue"><b>KanaWorks_AI</b></a> 制作 · <a href="https://x.com/KanaWorks_AI">X @KanaWorks_AI</a></sub>
</div>
