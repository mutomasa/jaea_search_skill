# JAEA検索システム実装計画

## 進捗

- [x] `a8b9877` JAEA特許・報告書スクレイピング成果、出力データ、RAG仕様書を追加
- [x] `9830056` Codex向け `AGENTS.md` と `uv` 依存管理方針を追加
- [x] Codex/Claude Code起動時に `jaea-search "検索キーワード"` をJAEA検索として扱う導線を追加する。
- [x] DuckDB構築、検索CLI、pytest単体テストを実装する。
- [x] 初回セットアップ用に、データ登録、chunk化、embedding作成、検索確認までを1コマンドで実行するパイプラインを追加する。

## Step 1: DuckDB導入

- [x] `uv` 管理のPythonプロジェクトとして初期化する。
- [x] `uv add duckdb` でDuckDB Pythonパッケージをインストールする。
- [x] 必要な追加ライブラリはすべて `uv add ...` で導入する。
- [x] スクリプトは原則 `uv run ...` で実行する。
- [x] `jaea/jaea.duckdb` を作成する。

## Step 2: データ取り込みスクリプト

作成候補:

- `jaea/scripts/build_duckdb.py`
- `jaea/scripts/setup_jaea_search.py`

実装項目:

- [x] `jaea/output` のCSV/JSONLをDuckDBに取り込む。
- [x] テーブルを作成または再作成する。
- [x] `rag_documents` を生成する。
- [x] 件数チェックを行う。
- [x] 初回ユーザ向けに入力データ確認、DuckDB登録、chunk embedding作成、検索スモークテストまでを一括実行する。

## Step 3: 検索スクリプト

作成候補:

- `jaea/scripts/search_rag.py`

実装項目:

- [x] skill名と検索キーワードを受け取る。
- [x] 標準の入力形式は `jaea-search "検索キーワード"` とする。
- [x] `検索キーワード` をDuckDB検索用のクエリ文字列として扱う。
- [x] DuckDBから関連資料を検索する。
- [x] 結果をMarkdownまたはJSONで返す。
- [x] 関連理由、技術分類、詳細URL、PDFリンクを整形して返す。

## Step 4: skill作成

作成候補:

- `skills/jaea-search/SKILL.md`
- `.claude/commands/jaea-search.md`
- 必要に応じて `$CODEX_HOME/skills/jaea-search/SKILL.md` へ同期する。

skillに含める内容:

- [x] DuckDBの場所
- [x] 検索スクリプトの実行方法
- [x] skill呼び出し形式: `jaea-search "検索キーワード"`
- [x] Claude Code用の補助ショートカット: `/jaea-search 検索キーワード`
- [x] DuckDB未実装時のMarkdown/CSVフォールバック
- [x] 結果の読み方
- [x] ユーザへの返答フォーマット
- [x] 検索語展開の方針

## Step 5: 検証

最低限確認するクエリ:

- [x] `3Dモデル生成`
- [x] `三次元図面`
- [x] `カメラ画像`
- [x] `セマンティックサーベイマップ`
- [x] `線量マッピング`
- [x] `遠隔ロボット`
- [x] `AR`
- [x] `空間マッピング`

確認項目:

- [x] 特許と報告書が両方検索できること
- [x] 高信頼候補が上位に出ること
- [x] 詳細URL/PDFリンクが出ること
- [x] 関連理由が説明できること

## Step 6: 単体テスト

- [x] 親ディレクトリの `tests/` にpytestテストを作成する。
- [x] `uv run pytest` で単体テストを実行する。
- [x] `jaea-search "検索キーワード"` と `/jaea-search 検索キーワード` の入力形式を検証する。
- [x] DuckDB構築と検索結果ランキングを検証する。
- [x] `AR` と `Ar`/`argon` の誤一致回避を検証する。

## Step 7: RAG実装

DuckDB内にchunkとembeddingを保持し、上位chunkを根拠として返す。

現在のembeddingは、外部APIやモデルダウンロードを使わない `local-hashed-ngram-v1` とする。日本語・英語混在の技術文書を扱うため、文字n-gramと英数字tokenを固定長ベクトル化する。将来的には、このembedding生成部分を `sentence-transformers` などの意味embeddingモデルへ差し替え、検索部分をDuckDB VSS拡張によるANN検索へ置き換えられる構造にする。

- [x] `rag_documents` をchunk化する。
- [x] タイトル、概要、根拠文、キーワード、PDF由来テキストを検索単位に分割する。
- [x] 各chunkにembeddingを付与する。
- [x] 日本語・英語混在の技術文書に対応したローカルembeddingモデルを使う。
- [x] DuckDBのベクトル列で類似検索用データを保持する。
- [x] キーワード一致だけでなく、embedding類似度も使って近い特許・報告書を拾う。
- [x] 上位chunkをLLM回答の根拠として渡せる形で出力する。
- [x] 回答には参照元、該当chunk、詳細URL、PDFリンクを含める。

今後の改善:

- [x] DuckDB VSS拡張によるANN検索を追加する。
- [x] `sentence-transformers` などの意味embeddingモデルに差し替える。
- [x] PDF本文抽出パイプラインを追加し、PDF由来テキストのカバレッジを増やす。

## Step 8: 意味embedding（sentence-transformers）

外部APIやモデルダウンロードに依存しない `local-hashed-ngram-v1` の代わりに、意味embeddingモデルを使い、「ドローン」→「無人航空機」のような同義語ヒットを可能にする。

- [x] `sentence-transformers` を optional 依存として追加する（`uv add sentence-transformers`）。
- [x] `rag_embeddings.py` に `SentenceTransformerEmbedder` クラスを追加する。
- [x] `get_embedder(model_name)` ファクトリ関数を追加し、ngram/ST を切り替えられるようにする。
- [x] `build_duckdb.py` に `--embedding-model` フラグを追加する（デフォルト: `local-hashed-ngram-v1`）。
- [x] `--embedding-model multilingual-e5-small` 指定時は `intfloat/multilingual-e5-small`（384次元）を使う。
- [x] ST使用時は `embedding` カラムを `FLOAT[384]` に変更し、BLOB→FLOAT[] のスキーマ切り替えを実現する。
- [x] `search_rag.py` でDBスキーマを自動検出し、BLOB（ngram）とFLOAT[]（ST）を両方サポートする。
- [x] `setup_jaea_search.py` に `--embedding-model` フラグを追加する。

## Step 9: DuckDB VSS拡張（ANN検索）

70k超のchunkを高速に検索するため、DuckDB VSS拡張のHNSWインデックスを活用する。

- [x] `FLOAT[dim]` スキーマ時に `vss` 拡張をインストール・ロードし、HNSWインデックスを作成する。
- [x] `search_rag.py` の `rank_chunks` でスキーマを検出し、FLOAT[]時は `array_cosine_similarity` をDuckDB側で計算する。
- [x] VSS不使用（BLOBスキーマ）の場合はPython側cosine similarityにフォールバックする。
- [x] `ensure_database` でBLOBとFLOAT[]の両スキーマを受け入れる。

## Step 10: 日本語形態素解析

クエリを形態素に分解して基本形・活用形の漏れを減らす。

- [x] `janome` を依存に追加する（`uv add janome`、pure Python、システム依存なし）。
- [x] `_tokenize_jp(text)` を実装し、名詞・動詞・形容詞の基本形を抽出する。
- [x] `expand_query` に形態素解析の結果を追加する。
- [x] `janome` 未インストール時は既存の正規表現分割にフォールバックする。

## Step 11: LLMによるクエリ拡張

ユーザの入力から関連キーワードをLLMに自動生成させ、同義語・関連概念でヒット漏れを防ぐ。

- [x] `anthropic` を依存に追加する（`uv add anthropic`）。
- [x] `_expand_with_llm(query)` を実装し、claude-haiku で5語以内のキーワードを生成する。
- [x] `search_rag.py` に `--expand-with-llm` フラグを追加する。
- [x] `ANTHROPIC_API_KEY` 未設定または API エラー時は黙ってスキップする。

## Step 12: PDF本文抽出パイプライン

現状はタイトル・概要・キーワードのみ。PDF全文をchunkに取り込み検索カバレッジを増やす。

- [x] `pypdf` と `httpx` を依存に追加する（`uv add pypdf httpx`）。
- [x] `jaea/scripts/fetch_pdf_text.py` を作成する。
  - `rag_documents.pdf_links` から最初のPDF URLを取得する。
  - PDF本文を `pypdf` で抽出し `rag_documents.pdf_text` を更新する。
  - `--limit` で1回の取得上限を指定できる。
  - `--dry-run` で実際のダウンロードをスキップして確認できる。
- [x] PDF取得後に対象ドキュメントのchunkを再作成するオプションを提供する（`--rechunk`）。
