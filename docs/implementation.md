# JAEA RAGシステム実装計画

## 進捗

- [x] `a8b9877` JAEA特許・報告書スクレイピング成果、出力データ、RAG仕様書を追加
- [x] `9830056` Codex向け `AGENTS.md` と `uv` 依存管理方針を追加
- [x] Codex/Claude Code起動時に `jaea-rag "検索キーワード"` をRAG検索として扱う導線を追加する。
- [x] DuckDB構築、RAG検索CLI、pytest単体テストを実装する。

## Step 1: DuckDB導入

- [x] `uv` 管理のPythonプロジェクトとして初期化する。
- [x] `uv add duckdb` でDuckDB Pythonパッケージをインストールする。
- [x] 必要な追加ライブラリはすべて `uv add ...` で導入する。
- [x] スクリプトは原則 `uv run ...` で実行する。
- [x] `jaea/jaea.duckdb` を作成する。

## Step 2: データ取り込みスクリプト

作成候補:

- `jaea/scripts/build_duckdb.py`

実装項目:

- [x] `jaea/output` のCSV/JSONLをDuckDBに取り込む。
- [x] テーブルを作成または再作成する。
- [x] `rag_documents` を生成する。
- [x] 件数チェックを行う。

## Step 3: 検索スクリプト

作成候補:

- `jaea/scripts/search_rag.py`

実装項目:

- [x] skill名と検索キーワードを受け取る。
- [x] 標準の入力形式は `jaea-rag "検索キーワード"` とする。
- [x] `検索キーワード` をDuckDB検索用のクエリ文字列として扱う。
- [x] DuckDBから関連資料を検索する。
- [x] 結果をMarkdownまたはJSONで返す。
- [x] 関連理由、技術分類、詳細URL、PDFリンクを整形して返す。

## Step 4: skill作成

作成候補:

- `skills/jaea-rag/SKILL.md`
- `.claude/commands/jaea-rag.md`
- 必要に応じて `$CODEX_HOME/skills/jaea-rag/SKILL.md` へ同期する。

skillに含める内容:

- [x] DuckDBの場所
- [x] 検索スクリプトの実行方法
- [x] skill呼び出し形式: `jaea-rag "検索キーワード"`
- [x] Claude Code用の補助ショートカット: `/jaea-rag 検索キーワード`
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
- [x] `jaea-rag "検索キーワード"` と `/jaea-rag 検索キーワード` の入力形式を検証する。
- [x] DuckDB構築と検索結果ランキングを検証する。
- [x] `AR` と `Ar`/`argon` の誤一致回避を検証する。
