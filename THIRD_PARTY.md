# Third-party software, models and data

kugiri itself is MIT-licensed (see [LICENSE](LICENSE)). It bundles no third-party code, fonts or model
weights; the packages and models below are installed or downloaded separately and keep their own licences.

## Models (downloaded on first use)

| model | licence | source |
|---|---|---|
| omniASR CTC 300M v2 + tokenizer (Meta) | Apache-2.0 | [facebookresearch/omnilingual-asr](https://github.com/facebookresearch/omnilingual-asr), files from `dl.fbaipublicfiles.com/mms/` |
| Qwen3-ASR 1.7B / 0.6B (Qwen team, Alibaba Cloud) | Apache-2.0 | [Qwen/Qwen3-ASR-1.7B-hf](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf), [Qwen/Qwen3-ASR-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf) |

kugiri contains its own PyTorch implementation of the omniASR CTC model (no fairseq2) and uses the
`transformers` implementation of Qwen3-ASR (not the `qwen-asr` package).

## Python packages

| package | licence | needed for |
|---|---|---|
| SudachiPy, SudachiDict-core | Apache-2.0 | line breaking (always) |
| pyopenjtalk-plus (OpenJTalk, naist-jdic) | MIT / BSD-3-Clause | readings, furigana (always) |
| PyTorch, NumPy | BSD-3-Clause | `[align]` |
| transformers, huggingface-hub | Apache-2.0 | `[asr]` |
| Starlette, uvicorn | BSD-3-Clause | `[web]` |
| python-multipart | Apache-2.0 | `[web]` |
| mcp (official Python SDK) | MIT | `[mcp]` |
| fontTools | MIT | `[fonts]` |

No dependency is under the GPL, LGPL or AGPL (checked for the whole `kugiri[all]` install tree; the test
`tests/test_licenses.py` keeps it that way).

## Data in `src/kugiri/data/`

- `kanji.tsv`, `kanji_words.tsv`: kanji, readings and special words from the **常用漢字表** (平成22年内閣告示第2号,
  [文化庁 PDF](https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kijun/naikaku/pdf/joyokanjihyo_20101130.pdf)) and the school grade of each
  kanji from the **学年別漢字配当表** (小学校学習指導要領 別表, 平成29年文部科学省告示第63号). Government notices (告示)
  are not subject to copyright in Japan (著作権法 第13条第2号). The grade list was read from the transcription on
  ja.wiktionary (付録:教育漢字の一覧) and checked line by line against the official PDF; the data is a list of facts
  taken from the notice, not the Wiktionary page text. A few common readings that the list does not contain
  (日本 = にほん, 明日 = あした, …) were added by hand. `tools/build_kanji.py` rebuilds the files.

## Other

- The default ASS furigana positions use character-width constants measured from Noto Sans JP (SIL Open Font
  License 1.1); the font itself is not included.
- `docs/reflow-before-after.png` shows our own demo clip (text written by us, synthetic voice).
