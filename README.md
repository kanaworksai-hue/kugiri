<div align="center">

<img src="docs/assets/banner-ja.jpg" alt="kugiri：どんな動画からでも、台本があってもなくても、日本語として自然な位置で区切られた字幕を" width="820">

<p>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-6b4dff?style=flat-square"></a>
  <img alt="macOS Apple Silicon" src="https://img.shields.io/badge/macOS-Apple_Silicon-111?style=flat-square&logo=apple">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white">
  <a href="#-aiエージェントから使うmcp"><img alt="MCP server" src="https://img.shields.io/badge/MCP-server-19b8d6?style=flat-square"></a>
  <a href="#-aiエージェントから使うmcp"><img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude_Code-plugin-d97757?style=flat-square"></a>
  <img alt="Output: SRT, VTT, ASS" src="https://img.shields.io/badge/output-SRT_·_VTT_·_ASS-e5484d?style=flat-square">
  <a href="https://github.com/kanaworksai-hue/kugiri/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/kanaworksai-hue/kugiri?style=flat-square&logo=github&label=stars&color=f5c518"></a>
</p>

<p><a href="https://github.com/kanaworksai-hue"><img src="docs/brand/kanaworks-mark.png" height="22" alt="" align="absmiddle"></a>&nbsp;<a href="https://github.com/kanaworksai-hue"><b>A KanaWorks_AI project</b></a></p>

**日本語** | [English](README.en.md) | [简体中文](README.zh-CN.md)

[クイックスタート](#-クイックスタート) · [他ツールとの比較](#-他ツールとの比較) · [Web UI](#-web-ui) · [MCP](#-aiエージェントから使うmcp) · [他ツールの字幕を直す](#-他ツールで作った字幕を直す) · [⭐ スター](#-気に入ったらスターを)

</div>

**動画を入れるだけで、日本語として自然な区切りの字幕を。台本がなくても書き起こしから、台本があれば一文字単位でぴったり。**

**kugiri**（区切り）は、動画や音声ファイルから日本語字幕を作るツールです。**台本はあってもなくても構いません。**
台本がなければ、まず音声を書き起こし（Qwen3-ASR、句読点付き）、あとから文言を直せます。
台本があれば、音声に一文字単位で合わせます。どちらの場合も、改行は日本語として自然な位置（文節の切れ目）に入り、
数字と単位は切り離しません。出力は SRT / VTT / ASS（ふりがな付きも可）です。
処理はすべてお使いの Mac の中で完結します。ブラウザからでも、AI エージェントからでも、コマンドラインからでも使えます。

## ✨ 特長

<table>
<tr>
<td align="center" width="25%">🎙️<br><b>台本はなくてもOK</b><br><sub>日本語の音声を句読点付きで書き起こし、台本があれば音声に一文字単位で合わせます</sub></td>
<td align="center" width="25%">✂️<br><b>自然な改行</b><br><sub>日本語の文節の切れ目で、禁則を守って改行。数字と単位は離しません</sub></td>
<td align="center" width="25%">🤖<br><b>Web UI + MCP + CLI</b><br><sub>ブラウザ、Claude Code（プラグイン）などの MCP クライアント、スクリプトから同じエンジンを使えます</sub></td>
<td align="center" width="25%">🔒<br><b>ローカル</b><br><sub>Apple Silicon 上で動作。動画はアップロードされず、API キーも費用も不要です</sub></td>
</tr>
</table>

- **ふりがな：** すべての漢字語に、難しい語（常用漢字表の範囲外）だけに、または子ども向けに学年に合わせて付けられます。
- **他ツールの字幕を整形：** `kugiri reflow` は、Vrew、CapCut、Premiere、DaVinci Resolve、Subtitle Edit、WhisperX、
  YouTube 自動字幕の SRT / VTT / JSON を、モデルを使わずに区切り直します。
- **品質チェック：** 台本と音声が食い違う箇所を、タイムスタンプ付きで一覧にします。
- **プリセット：** YouTube、縦型ショート動画（Shorts / TikTok）、Netflix 日本語スタイル。

ステータス：ベータ版。**最初のリリースは Apple Silicon の macOS のみ対応です**（M1 以降、macOS 14 以上）。

## 🚀 クイックスタート

[uv](https://docs.astral.sh/uv/getting-started/installation/)（`brew install uv`）が必要です。WAV 以外のファイルを扱うには
ffmpeg（`brew install ffmpeg`）も必要です。準備ができたら：

```sh
uvx --python 3.12 --from 'kugiri[all]' kugiri web     # Web UI を http://localhost:7790/ で開く
```

初回起動時は、Python パッケージ（PyTorch）約 1 GB と、続いてモデル（アライメント用 1.3 GB、書き起こし用 4.1 GB）を
ダウンロードするため、数分かかります。進捗はページに表示されます。以降は Mac 上ですべてオフラインで動きます。
動画をドロップし、台本があれば貼り付けて（なければ空欄のままで書き起こしになります）、字幕をダウンロードしてください。

## 📊 他ツールとの比較

多くの字幕ツールは、文字数を数えて日本語の行を折り返します。kugiri は日本語の文節の切れ目で区切ります。
行頭に 、。」 を置かない、数字を単位から切り離さない、できるだけ 1 枚の字幕に 1 文、という具合です。

![The same Japanese clip broken into subtitles by WhisperX, Subtitle Edit, clipwright-wrap and kugiri](docs/compare-line-breaks.png)

*自作のデモ動画（合成音声）で、どのツールも 16 文字 × 2 行に制限し、libass で描画しました。
WhisperX 3.8（large-v3-turbo）：`--max_line_width 16 --max_line_count 2`。Subtitle Edit 5.3：WhisperX の書き起こしに
「長い行を分割/改行」（Split/break long lines）を適用し、行の長さを 16 に設定（既定値は 43）。clipwright-wrap 0.3：既定設定（16 × 2）。
受け取った字幕の中で行を折り返すだけで字幕自体は分割しないため、1 枚に 1 文ずつ渡しています。
kugiri：WhisperX の JSON に `kugiri reflow` を適用。注目してほしい区切り：`12,8｜00円`、`、` で始まる行（WhisperX）、
`思｜います`、`ライ｜ブ配信`（Subtitle Edit）、画面に収まらない長い行（clipwright-wrap）。*

**タイミング。** 台本を音声に合わせた結果を、人手でタイミングを付けた字幕のある日本語 TEDx トーク 24 本（各 1 分）で
測定しました（[TEDxJP-10K](https://github.com/laboroai/TEDxJP-10K)）。各字幕の開始・終了が、人手のタイミングから
どれだけずれているかを示します。

| | 平均誤差 | 開始が 300 ms 以内 | 終了が 300 ms 以内 |
|---|---|---|---|
| kugiri `align` | 149 ms | 96% | 82% |
| WhisperX のアライメント（`wav2vec2-large-xlsr-53-japanese`）、同じテキスト | 324 ms | 91% | 37% |

どちらにも同じ 1 分間のテキストと音声を与えています（WhisperX は 1 つのセグメントとして渡し、Whisper 自身の大まかな
セグメント時刻は使っていません）。人手の字幕は発話の前後に少し無音を含むため、どのツールの誤差にも参照データ側の
ずれが一部含まれます。Subtitle Edit 5 もプレーンテキストの台本を合わせられますが、各行の開始は強制アライメントで決め、
終了は読む速さから設定するため、行の終了時刻は音声から取ったものではありません。

## 🧭 できること

- `kugiri align`：音声・動画 → 自然に区切られた日本語字幕。台本がなければ音声を書き起こし（Qwen3-ASR、句読点付き）、
  台本があればその手順は省きます。どちらのテキストも、音声に一文字単位で合わせます
  （omniASR CTC 300M による強制アライメント。ファイル全体を一度に処理し、手作業での分割は不要）。
- `kugiri reflow`：すでにタイミングのある字幕を対象にした、モデル不要の改行エンジン。他ツールで作った字幕
  （Vrew、CapCut、Premiere、DaVinci Resolve、Subtitle Edit、WhisperX、YouTube）にも使えます。
- SRT / WebVTT / ASS / タイムライン JSON で書き出し。

### アライメント

- ファイル全体を 1 回の Viterbi で合わせるため、長い収録でも台本と音声をブロックごとに対応付ける必要がありません。
  30 分のファイルも 16 GB の Mac に余裕で収まります（チェックポイント付き Viterbi、台本の文字だけを保持）。
- 数字、英単語（`AI`、`iPhone`）、モデルの語彙にない文字、ユーザー辞書の語は、読み（`2026` → にせんにじゅうろく）を
  使って合わせ、`reading` 付きの 1 単位として出力します。
- 句末のタイミングは音量の包絡線で補正します（語尾を伸ばす発話では CTC のピークが早く終わりすぎるため）。
- 品質チェック：台本と音声が食い違う区間（テキストの抜けや余分、話者の重なり、ノイズ）をタイムスタンプ付きで一覧にし、
  該当する字幕には JSON で `low_confidence` フラグを付けます。

### 文字起こし（台本なし）

- Qwen3-ASR 1.7B（Apache-2.0）を Hugging Face `transformers` のネイティブ実装で動かし、句読点（、。？）付きで書き起こします。
  音声は間（ま）で 20 秒以下のチャンクに切り、まとめてバッチでデコードします。
- ハルシネーション対策：チャンクごとのトークン上限、繰り返しと発話速度のチェック。怪しいチャンクは、アライメント
  モデル自身の貪欲デコード結果（CTC モデルは存在しないテキストを作れません）に切り替え、フラグを付けます。
- `--save-script` は書き起こしを 1 行 1 文で書き出します。直してから `--script` で実行し直してください。

### 改行と区切り

- 禁則処理（行頭に 、。っー」 を置かない、行末に 「（ を置かない）、単位付きの数字は分割しない
  （`2026年10月20日`、`1,500円`、`2.5GB`）、短い括弧はまとめて扱う。
- SudachiPy による文節を考慮した区切りコスト、2 段階の動的計画法（字幕の分割 × 行の折り返し）、
  「1 枚に 1 文」を優先。句読点のない話し言葉（〜ました|〜です）にも対応。
- タイミングのルール：最短・最長の表示時間、読み切れるだけの表示時間を確保（発話終了後最大 1.5 秒）、
  2 フレームの間隔、短い隙間の詰め、フレーム単位へのスナップ。
- 読みは pyopenjtalk-plus で取得。ユーザー辞書で読みの上書きや分割禁止を指定できます。
- ふりがな：ASS（位置指定したルビ行。libass 系プレーヤーで表示されます。位置は既定で Noto Sans JP の字幅で計算するので、
  別のフォントでは `--font-file` を指定）、WebVTT の `<ruby>`（オプトイン。ブラウザのみ対応で、ffmpeg 系プレーヤーでは
  漢字の後ろに読みが表示されます）。`--ruby all` はすべての漢字語に、`--ruby hard` は読みにくい語だけ
  （常用漢字表にない漢字や、表にない読み：薔薇、流石、辛い = つらい）に付けます。さらに
  `--ruby-grade N` を付けると、小学 N 年生までに習わない漢字（学年別漢字配当表）にも付けるので、子ども向けや
  学習者向けのコンテンツに使えます。`--ruby-once` は各語の初出だけに付けます（Netflix スタイル）。
- SRT 出力では `< > { } \` を全角に置き換えます。多くのプレーヤーがこれらをタグとして扱うためです。

## 📦 インストール

Apple Silicon の macOS 14 以上と、Python 3.11 以上が必要です。[uv](https://docs.astral.sh/uv/) があれば、
準備なしで 1 行で試せます：

```sh
uvx --python 3.12 --from 'kugiri[all]' kugiri web   # Web UI を http://localhost:7790/ で開く
```

`--python 3.12` を付けると、Mac にシステムの Python 3.9 しかない場合でも uv が自前の Python を取得します（3.11 以上なら何でも可）。
`kugiri` コマンドを常に使えるようにするには：

```sh
uv tool install --python 3.12 'kugiri[all]'   # または Python 3.11 以上の環境で：pip install 'kugiri[all]'
uv tool update-shell                          # uv が ~/.local/bin が PATH にないと言う場合に一度だけ
kugiri --help
```

| インストール | 使える機能 |
|---|---|
| `kugiri` | `kugiri reflow`（既存の字幕を修正・区切り直し）、`reading`、`presets`。モデルなし。ダウンロードは約 110 MB（辞書） |
| `kugiri[align]` | + 台本ありの `kugiri align`（PyTorch） |
| `kugiri[asr]` | + 台本がないときの書き起こし |
| `kugiri[web]` / `kugiri[mcp]` | + Web UI / MCP サーバー（どちらも `asr` を含む） |
| `kugiri[all]` | すべて。ASS のふりがな位置を正確に計算する fonttools も含む |

PyTorch を含めるとパッケージは約 1 GB になり、初回の `uvx` やインストールには数分かかります。Intel Mac には
PyTorch 付きの extras をインストールできません（PyTorch が Intel macOS 向けビルドの提供を終了したため）。素の `kugiri`（`reflow`）は動きます。

**モデルは初回使用時に一度だけダウンロード**され、以降はオフラインで動きます：

| モデル | 用途 | サイズ | 保存先 |
|---|---|---|---|
| omniASR CTC 300M v2（Meta、Apache-2.0） | アライメント（`align`、Web UI、MCP） | 1.3 GB | `~/.cache/kugiri/models`（`KUGIRI_MODEL_DIR`） |
| Qwen3-ASR 1.7B（Apache-2.0） | 台本なしの書き起こし | 4.1 GB | Hugging Face キャッシュ（`HF_HOME`） |
| Qwen3-ASR 0.6B（`--asr-model qwen3-0.6b`） | より速く、メモリが少ない | 1.6 GB | Hugging Face キャッシュ |

ターミナル、Web UI、MCP の進捗メッセージに、何をどこまでダウンロードしたかが表示されます。ダウンロードが
中断しても、もう一度実行すれば続きから再開します。ミラー：`KUGIRI_MODEL_URL`（omniASR のファイルのベース URL）と
`HF_ENDPOINT`。`kugiri web` は起動時に両方のモデルをダウンロードして読み込みます（最初のジョブまで待つなら `--warm none`、
小さい認識モデルを使うなら `--warm qwen3-0.6b`）。

モデルは素の PyTorch（fairseq2 不要）で、Apple の GPU（MPS）上で動きます（`--device cpu` でも動きますが遅くなります）。
16 GB の Apple Silicon Mac で十分で、長い収録にも対応します。WAV は直接読み込みます。それ以外の音声・動画形式には `PATH` 上の `ffmpeg` が必要です（`brew install ffmpeg`、
または `KUGIRI_FFMPEG` で場所を指定）。Linux、Windows、NVIDIA GPU（`--device cuda`）はまだテストしていません。

## 🌐 Web UI

```sh
kugiri web                 # http://localhost:7790/ を開く（このマシンからのみ接続可能）
```

1. 動画または音声ファイルをドロップします。台本は任意です（貼り付けるか `.txt` を読み込み）。台本がなければ、
   まず音声を書き起こします。
2. プリセット（YouTube 横型 / 縦型ショート / Netflix）、認識モデル、ふりがなを選びます。
3. 進捗は工程ごと（書き起こし → アライメント → 改行）に表示されます。ジョブは 1 件ずつ実行され、残りはキューで
   待機します。長いファイルの処理中もページは操作できます。
4. 結果ページでは、字幕を重ねて動画を再生します。一覧のどの行でも編集でき、そのあと **改行し直す**
   （即時）か **修正内容で合わせ直す**（編集したテキストを台本としてタイミングを再計算）を選べます。
5. 「確認箇所」には、台本と音声が食い違っていそうな箇所が並びます。クリックするとその位置に移動します。
6. 書き起こし / 台本タブでは、書き起こしのダウンロード、修正（または `.txt` の読み込み）、それを使った合わせ直しができます。
   ユーザー辞書（読み、分割しない語）はヘッダーで編集します。
7. SRT / VTT / ASS / JSON / 台本 `.txt` をダウンロードします。

モデルはサーバー起動時に読み込まれ、メモリに常駐します（次のファイルはすぐに処理が始まります）。
`--warm qwen3-0.6b` / `--warm none` で、小さい認識モデルだけを読み込む、または何も先に読み込まないようにできます。
アップロードしたファイルとユーザー辞書は `~/.cache/kugiri/web` に保存されます（変更は `KUGIRI_HOME` または `--data-dir`。
7 日より古いジョブは起動時に削除）。UI は日本語と英語に対応しています。サーバーは localhost 宛てのリクエストにだけ応答し、
他のウェブサイトからの変更リクエストは拒否します。`--host 0.0.0.0` でネットワークに公開できます（ログイン機能はありません）。

## 🤖 AIエージェントから使う（MCP）

`kugiri mcp` は MCP サーバーです（stdio、公式 Python SDK）。ツール：

| ツール | 機能 |
|---|---|
| `align` | 音声・動画（+ 任意で台本）→ 字幕ファイル。出力パス、字幕の枚数、品質レポートを返す |
| `transcribe` | 音声 → テキストのみ（1 行 1 文で `.txt` に書き出し） |
| `job_status` | `wait=false` で開始したジョブの状態 |
| `reflow` | 既存の SRT / VTT / JSON 字幕を区切り直し・折り返し直し（エージェントが付けた文末の印も使用可） |
| `break_candidates` | 区切ってよい位置に番号を付けて一覧にし、エージェントが意味から文末を指定できるようにする |
| `reading` | 文の読み（かな）を返す（ユーザー辞書の確認に） |
| `presets` | 各プリセットのパラメータ |

入力と出力はローカルのファイルパスです。既定では、`align` は音声と同じ場所に `<name>.kugiri.srt`（書き起こした場合は
`<name>.kugiri.script.txt` も）を書き出すため、ご自身の `<name>.srt` が上書きされることはありません。
`output` でパスを明示した場合は上書きされます。長いジョブでは MCP の進捗通知を送ります。クライアントが長い呼び出しで
タイムアウトする場合は、`wait=false` を指定して `job_status` で状態を確認してください。モデルは最初の呼び出しで読み込まれ、常駐します。

**先に Python パッケージを一度インストールしてください。** MCP クライアントはサーバーの起動を 30 秒ほどしか待ちませんが、
初回の `uvx` 実行では約 1 GB（PyTorch）をインストールするため、それより時間がかかります：

```sh
uvx --python 3.12 --from 'kugiri[mcp]' kugiri --version
```

モデルは最初の `align` / `transcribe` 呼び出しでダウンロードされます（[インストール](#-インストール)を参照）。その呼び出しは
時間が長くかかるだけで、進捗メッセージが表示されます。

**Claude Code** — プラグインとして（1 ステップ、Claude Code 2.1.275 以降）：

```
/plugin install kugiri --marketplace kanaworksai-hue/kugiri
```

それより古いバージョンでは、`/plugin marketplace add kanaworksai-hue/kugiri` のあと `/plugin install kugiri@kugiri`。
MCP サーバーだけを追加することもできます：

```sh
claude mcp add kugiri -- uvx --python 3.12 --from 'kugiri[mcp]' kugiri mcp
claude mcp add kugiri -- kugiri mcp          # uv tool install / pip でインストールした場合
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

Claude Desktop は環境変数をほとんど渡さずにサーバーを起動します。`uvx` は絶対パス（`which uvx`）で指定し、
WAV 以外を入力する場合は `PATH` に `ffmpeg` が含まれるようにしてください。モデルを別の場所に置いている場合は、
`"HF_HOME"` / `"KUGIRI_MODEL_DIR"` も `env` に追加してください。

**その他の MCP クライアント**（Cursor、VS Code、Codex CLI など）も、同じ stdio コマンド
`uvx --python 3.12 --from 'kugiri[mcp]' kugiri mcp` を実行します。Dock から起動したアプリには `~/.local/bin` が
見えないことがあるので、どのクライアントでも `uvx` の絶対パスを使うのが確実です。Cursor（`.cursor/mcp.json`）は
上の Claude Desktop と同じ形式、VS Code（`.vscode/mcp.json`）は次のとおりです：

```json
{"servers": {"kugiri": {"type": "stdio", "command": "uvx", "args": ["--python", "3.12", "--from", "kugiri[mcp]", "kugiri", "mcp"]}}}
```

Codex CLI（`~/.codex/config.toml`。モデルのダウンロードを伴う初回の `align` や長いファイルは、Codex の既定の
ツールタイムアウトより時間がかかります）：

```toml
[mcp_servers.kugiri]
command = "uvx"
args = ["--python", "3.12", "--from", "kugiri[mcp]", "kugiri", "mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 1800
```

あとは、たとえば「~/Movies/talk.mp4 の YouTube 用字幕を台本 ~/Movies/talk.txt で作って。ふりがな付きの
ASS ファイルもお願い」のように頼むだけです。

### 文の区切りをエージェントに読ませる

話し言葉の日本語には句読点がないことが多く（「〜ですねじゃあ次は〜」）、どこで文が終わり次の文が始まるかは
ルールでは判断できません。MCP を使えば、それをエージェントに任せられます。`break_candidates` がルール上区切ってよい
位置をすべて、1 行に 1 フレーズずつ番号付きで一覧にし、エージェントが文末に印を付けて `reflow` に渡します
（`hints_key`、`sentence`、まれに `keep`）。区切り・折り返し・タイミングはこれまでどおり kugiri が行い、エージェントは
許可された位置からしか選べないので、禁則、単位付きの数字、括弧は崩れません。使うのはエージェント自身のモデルで、
kugiri が LLM API を呼ぶことはありません。音声の場合は、まず `align` で `.json` を出力し、その JSON を reflow してください。
結果はエージェントのモデルによって変わります。Claude Opus のような強力なモデルは、小さいモデルよりも文の境界を
はっきりうまく読み取ります。小さいモデルでは、kugiri のルールだけの場合とほぼ同じ結果になります。たとえば次のように頼みます：
「~/Movies/talk.srt の改行を kugiri で直して。文末は自分で判断して印を付けて」

## 🩹 他ツールで作った字幕を直す

他のツールで作った日本語字幕がすでにあるなら、`kugiri reflow` のコマンド 1 つで、きちんと区切られた日本語字幕に
変換できます。音声認識をやり直すことはなく、字幕の区切り直し、行の折り返し直し、タイミングのルール適用だけを行うので、
モデルは不要で 1 秒ほどで終わります（extras なしの素の `kugiri` で十分です：
`uvx --python 3.12 kugiri reflow …`）。

```sh
kugiri reflow from-vrew.srt --preset youtube -o fixed.srt
kugiri reflow whisperx-output.json --preset vertical -o shorts.srt   # WhisperX JSON：文字ごとの時刻を使用
kugiri reflow video.ja.vtt --preset youtube -o fixed.srt            # YouTube 自動字幕（yt-dlp --write-auto-subs）
```

![WhisperX SRT vs kugiri reflow](docs/reflow-before-after.png)

*自作のデモ動画（合成音声）。左：WhisperX が出力したままの SRT（日本語には既定で行の長さ制限がかからないため、
29 秒の字幕 1 枚になっています）。右：同じファイルに `kugiri reflow --preset youtube` を適用したもの。
認識の誤り（句読点 → 苦闘店）はそのままです。結果の文言を直すか、台本を用意して `kugiri align` を使ってください。*

入力側で対応している内容：

| 入力 | 処理 |
|---|---|
| 1 行がとても長い字幕、数文字だけの字幕、句読点なし（Vrew、CapCut、Premiere、Resolve） | つなげてから日本語の文節の切れ目で切り直し、できるだけ 1 枚に 1 文 |
| YouTube 自動字幕（`.vtt`） | 2 行で流れるスクロール字幕の重複を除去、10 ms の切り替え用字幕を削除、`<c>` の単語タイミングを使用 |
| WhisperX / openai-whisper / stable-ts の JSON、whisper.cpp の JSON | `segments[].words` を文字単位のタイミングに変換（時刻のない数字は前後に合わせる）、`speaker` を保持 |
| 単語ハイライト SRT（WhisperX の `--highlight_words`、カラオケ風の書き出し） | 繰り返される字幕を 1 枚にまとめる |
| 単語の間にスペースが入った日本語（今日 は 天気 が） | スペースを削除（ファイル全体がそうなっている場合のみ。、。の代わりに入る Netflix スタイルのスペースは残す） |
| `.ass` / `.ssa`（Aegisub、Subtitle Edit） | `\N` 改行付きの `Dialogue` イベント。オーバーライドタグ、コメント、図形描画は無視。`Name` = 話者 |
| BOM あり・なしの UTF-8、UTF-16、Shift_JIS、CRLF、行末の余分なスペース | そのまま読み込む |
| `（拍手）` / `[音楽]` / `♪～` の字幕、2 人の会話の字幕（`-行こう` / `-うん`）、`>> 名前` | 独立した字幕として残す。収まらない 2 人の会話の字幕は、話者ごとに 1 枚ずつに分ける |

Vrew、CapCut、Premiere Pro、DaVinci Resolve の形式は実際のファイルを入手できませんでした。これらのテスト用入力
（`tests/golden/input/`）は、公開されている仕様や報告された挙動（句読点のない長すぎる・短すぎる字幕、行末のスペース、
BOM、CRLF）をもとに手作業で作成しています。WhisperX と YouTube 自動字幕は実際の出力で確認済みです。お使いのツールの
ファイルがうまく処理されない場合は、サンプルを添えて Issue を作成してください。

## ⌨️ 使い方

```sh
kugiri align talk.wav --script talk.txt -o talk.srt        # talk.txt は 1 行に 1 段落
kugiri align talk.mp4 --script talk.txt --preset vertical -o talk.ass --ruby all
kugiri align talk.wav --script talk.txt -o talk.json       # 文字ごとの時刻 + 品質レポート付きのタイムライン JSON
kugiri align interview.wav --script script.txt --speakers -o out.vtt   # 行頭の「名前：…」/「>> 名前」
kugiri align talk.wav -o draft.srt --save-script draft.txt # 台本なし：書き起こし（Qwen3-ASR）→ アライメント → 改行
kugiri reflow in.srt --preset youtube -o out.srt          # 区切り直し + 折り返し直し、タイミングのルールを適用
kugiri reflow in.vtt --preset netflix --mode wrap -o out.vtt   # 字幕とタイミングはすべてそのままで、折り返しだけ直す
kugiri reflow in.srt --preset vertical --ruby all --dict words.tsv -o out.ass
kugiri reflow in.srt --ruby hard --ruby-once -o out.ass    # 難しい語だけ、初出だけにふりがな
kugiri reflow in.srt --ruby hard --ruby-grade 3 -o out.vtt # 子ども向け：小学 3 年生がまだ習っていない漢字にも
kugiri reflow in.srt --show-breaks > breaks.txt           # 番号付きの区切り候補（MCP の break_candidates と同じ内容）
kugiri reflow in.srt --hints marks.json -o out.srt        # {"key": …, "sentence": [3, 9, …], "keep": []}
kugiri reading "東京の夜は静かです" --tokens
kugiri presets
kugiri web                                            # ローカルの Web UI
kugiri mcp                                            # MCP サーバー（stdio）
```

プリセット：

| プリセット | 1 行の文字数 | 行数 | 読む速さ | 表示時間 | fps |
|---|---|---|---|---|---|
| `netflix` | 13 | 2 | 4 cps | 0.5–7 s | 24 |
| `youtube` | 16 | 2 | 6 cps | 0.7–7 s | 30 |
| `vertical`（Shorts / TikTok） | 10 | 2 | 6 cps | 0.5–5 s | 30 |

幅は全角を 1、半角を 0.5 として数えます。句読点は既定で Netflix 日本語スタイルに従います
（、→ 半角スペース、。→ 全角スペース）。そのまま残すには `--punct keep` を指定します。

### ユーザー辞書（TSV）

```
# 表記	読み	禁止分割
東京AI映像合同会社	とうきょうえーあいえいぞうごうどうがいしゃ	1
VRChat	ぶいあーるちゃっと
明日	あす	0
```

3 列目の既定値は `1`（この語の途中では分割しない）で、`0` にすると分割を許可します。

台本のコツ：1 行に 1 段落。句読点があると改行がうまくいきますが、なくても構いません。実際には読まれない
ト書き（`（拍手）`）は削除してください。残すと食い違いとして報告されます。内蔵の書き起こしは下書き用の便利機能です。
より良い結果が欲しい場合は、お好みの音声認識で書き起こし、修正したテキストを `--script` で渡してください。

### タイムライン JSON

`kugiri-timeline` v1 は、データ交換用の形式です（字幕、文字・単語ごとのタイミング、読み、信頼度、
ふりがな）。スキーマ：`src/kugiri/schema/timeline.schema.json`。入力 JSON に `units` がある場合
（`kugiri align` の出力など）、字幕内で補間する代わりにそのタイミングを使って区切ります。`kugiri align` は
`meta.align`（モデル、デバイス、リアルタイム係数、`warnings`）と字幕ごとの `flags` も書き出します。

## 🛠️ 開発

```sh
uv sync --all-groups --all-extras
uv run pytest            # モデルが必要なテストは、KUGIRI_MODEL_DIR にモデルがある場合のみ実行
KUGIRI_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py   # 意図した変更のあとでゴールデンファイルを再生成
```

実行時の依存関係はすべて寛容なライセンスです（SudachiPy / SudachiDict：Apache-2.0、
pyopenjtalk-plus：MIT、OpenJTalk / naist-jdic：BSD。オプションの PyTorch：BSD-3-Clause、omniASR の重み：
Apache-2.0、transformers：Apache-2.0、Qwen3-ASR の重み：Apache-2.0。Web UI：Starlette / uvicorn BSD-3-Clause、
python-multipart Apache-2.0。MCP：公式 `mcp` SDK MIT）。GPL の依存関係は使いません
（公式の `qwen-asr` パッケージは GPLv3 の `soynlp` に依存しているため使用していません）。
`src/kugiri/data/` の漢字リストは、常用漢字表（内閣告示、2010 年）と学年別漢字配当表
（文部科学省告示、2017 年）に基づいています。告示は日本の著作権法の保護対象ではありません（著作権法 第13条）。
`tools/build_kanji.py` で公式の PDF から再生成できます。詳細とモデルのライセンスは
[THIRD_PARTY.md](THIRD_PARTY.md) をご覧ください。

## ⭐ 気に入ったらスターを

kugiri で日本語字幕の手間が減ったら、GitHub でスターを付けていただけると、ほかの人にも見つけてもらいやすくなります。
バグ報告や、うまく処理されなかったサンプルファイルは [Issues](https://github.com/kanaworksai-hue/kugiri/issues) で大歓迎です。

<a href="https://github.com/kanaworksai-hue/kugiri/stargazers"><img alt="Star kugiri on GitHub" src="https://img.shields.io/github/stars/kanaworksai-hue/kugiri?style=social"></a>

## 📄 ライセンスとクレジット

コードとドキュメント：[MIT](LICENSE) © 東京AI映像合同会社。モデルとデータの出典：[THIRD_PARTY.md](THIRD_PARTY.md)。
KanaWorks_AI の名称、ロゴ、キャラクター「Kana」（`docs/brand/` 内およびバナー）は MIT ライセンスの対象外です。
詳しくは [docs/brand/README.md](docs/brand/README.md) をご覧ください。

<div align="center">
<br>
<a href="https://github.com/kanaworksai-hue"><img src="docs/brand/kana-wave.png" width="120" alt="KanaWorks_AI のマスコット Kana が手を振っている"></a>
<br>
<sub>Made by <a href="https://github.com/kanaworksai-hue"><b>KanaWorks_AI</b></a> · <a href="https://x.com/KanaWorks_AI">X @KanaWorks_AI</a></sub>
</div>
