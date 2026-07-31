# JAEA特許・報告書検索システム

JAEAの特許データと報告書データをDuckDBに取り込み、CodexまたはClaude Codeから `jaea-search "検索キーワード"` で関連資料を探すためのローカルRAG検索システムです。

現状は、DuckDB上の統合文書テーブル `rag_documents` をchunk化し、各chunkにローカルembeddingを付与して、上位chunkを根拠として提示するRAG構成です。embeddingは外部APIやモデルダウンロードに依存しない `local-hashed-ngram-v1` で、日本語・英語混在テキストを扱えるよう文字n-gramと英数字tokenをベクトル化します。

## デモ

![デモ](assets/demo.gif)

[MP4で見る](assets/demo.mp4)

## できること

- JAEA特許データと報告書データを横断検索する。
- 研究アイディアや技術キーワードに関連する特許・報告書を提示する。
- 関連理由、技術分類、詳細URL、PDFリンクをMarkdownまたはJSONで出力する。
- 上位chunkを根拠として、どの本文断片に反応したかを提示する。
- 画像処理、Computer vision、AR mapping、3Dモデル生成、空間マッピング、線量マッピング、遠隔ロボット系の資料を探す。
- DuckDBが未作成の場合は、検索スクリプトから自動構築する。

## システムの仕組み

このシステムは、JAEAの既存データを次の流れで検索可能にします。

1. `jaea/output` のCSV/JSONLを入力データとして使う。
2. `jaea/scripts/build_duckdb.py` がDuckDBに各データを取り込む。
3. 特許と報告書を横断検索するための `rag_documents` テーブルを作る。
4. `rag_documents` から `rag_chunks` を作り、タイトル、概要、根拠文、キーワード、PDF由来テキストを検索単位に分割する。
5. 各chunkに固定長embeddingを付与し、DuckDB内のベクトル列に保存する。
6. `jaea/scripts/search_rag.py` が検索キーワードを受け取り、クエリembeddingとchunk embeddingの類似度、キーワード一致、既存スコアを組み合わせて検索する。
7. 上位chunkを文書単位に集約し、特許と報告書に分け、根拠chunk、詳細URL、PDFリンク付きで返す。

短い検索語では偶然一致を避けるためキーワード一致を重視し、複数語や長い研究アイディアではembedding類似度も使います。

DuckDBは以下の役割を持ちます。

- 特許・報告書データのローカルDB
- 全件データと抽出候補の統合
- `rag_documents` による横断検索用の文書テーブル
- `rag_chunks` によるchunk単位の根拠テーブル
- `embedding` 列によるローカルベクトル検索用データ

検索CLIはDuckDBを読む実行プログラムで、スキルはCodex / Claude Codeにその使い方と返答形式を教える指示ファイルです。

## 対応エージェント

このリポジトリはCodexとClaude Codeの両方に対応しています。

- Codex向け指示: [AGENTS.md](AGENTS.md)
- Claude Code向け指示: [CLAUDE.md](CLAUDE.md)
- 共通skill仕様: [skills/jaea-search/SKILL.md](skills/jaea-search/SKILL.md)
- Claude Codeショートカット: [.claude/commands/jaea-search.md](.claude/commands/jaea-search.md)

## スキルの呼び方

Codex / Claude Code共通の標準呼び出しは次です。

```text
jaea-search "検索キーワード"
```

例:

```text
jaea-search "3Dモデル生成"
jaea-search "カメラ画像 三次元図面"
jaea-search "線量マッピング 遠隔ロボット"
jaea-search "AR"
```

Claude Codeでは補助的なショートカットも使えます。

```text
/jaea-search 検索キーワード
```

## スキルと検索CLIの違い

検索CLIは、実際にDuckDBを検索するプログラムです。

```text
jaea/scripts/search_rag.py
```

検索CLIは次を行います。

- `jaea/jaea.duckdb` を読む。
- DuckDBがなければ `jaea/output` から自動構築する。
- 特許・報告書を横断検索する。
- chunk embeddingから関連chunkを探す。
- MarkdownまたはJSONで結果を出力する。

スキルは、Codex / Claude Codeに「検索CLIをどう使うか」と「結果をどう説明するか」を教える説明書です。

```text
skills/jaea-search/SKILL.md
```

スキルは次を行います。

- `jaea-search "検索キーワード"` をJAEA特許・報告書検索として認識させる。
- 検索CLIを実行するよう案内する。
- 結果を「関連特許」「関連報告書」「技術的接点」に整理して返す。
- 上位chunkをLLM回答の根拠として使う。
- DuckDBや検索CLIが使えない場合のフォールバック先を示す。

要するに、検索CLIは検索エンジン本体で、スキルはエージェント用の操作説明です。ユーザは通常、次の形式だけ覚えれば十分です。

```text
jaea-search "ドローン"
```

## 初回セットアップ

依存管理はすべて `uv` を使います。`pip install ...` は直接使いません。

依存関係を同期します。

```bash
uv sync
```

初回セットアップは次の1コマンドで完了します。

```bash
uv run python jaea/scripts/setup_jaea_search.py
```

このスクリプトは次をまとめて実行します。

- `jaea/output` の入力データ確認
- DuckDBへのデータ登録
- `rag_documents` の作成
- `rag_chunks` へのchunk化
- ローカルembeddingの作成
- 検索スモークテスト

生成されるDB:

```text
jaea/jaea.duckdb
```

`jaea/jaea.duckdb` は元データから再生成できるため、git管理対象外です。

データを更新した後にDBを作り直す場合は、次を実行します。

```bash
uv run python jaea/scripts/setup_jaea_search.py --force
```

## 検索CLI

Markdownで検索します。

```bash
uv run python jaea/scripts/search_rag.py jaea-search "3Dモデル生成"
```

件数を指定します。

```bash
uv run python jaea/scripts/search_rag.py jaea-search "三次元図面" --limit 5
```

JSONで出力します。

```bash
uv run python jaea/scripts/search_rag.py jaea-search "カメラ画像" --format json
```

DBが存在しない場合、`search_rag.py` が `jaea/output` のデータから自動でDuckDBを構築します。

## データ

主な入力データは [jaea/output](jaea/output) にあります。

- 特許全件: `jaea_patents_all.csv`
- AI/ML特許候補: `jaea_patents_ai_candidates.csv`
- AI/ML特許ピックアップ: `jaea_patents_ai_curated.csv`
- 報告書全件: `jaea_reports_all.jsonl`
- CV/AR/空間マッピング系報告書候補: `jaea_reports_cv_ar_candidates.csv`
- 高信頼報告書候補: `jaea_reports_cv_ar_high_confidence.csv`

DuckDB構築後の主なテーブル:

- `patents_all`
- `patents_ai_candidates`
- `patents_ai_curated`
- `reports_all`
- `reports_cv_ar_candidates`
- `reports_cv_ar_high_confidence`
- `rag_documents`
- `rag_chunks`

`rag_chunks` には、文書ID、chunk番号、chunk種別、chunk本文、embedding、参照URL、PDFリンクが入ります。

## テスト

単体テストはリポジトリ直下の [tests](tests) にあります。

```bash
uv run pytest
```

現在のテストでは、入力形式、DuckDB構築、chunk/embedding生成、検索ランキング、根拠chunk出力、`AR` と `Ar`/`argon` の誤一致回避を確認します。

## 注意

- 検索結果は関連候補であり、法的な特許侵害判断ではありません。
- `AR` はアルゴンの `Ar` と誤一致しやすいため、検索スクリプト側で文脈フィルタを入れています。
- `3D` や `三次元` は数値解析にも出るため、画像、カメラ、マッピング、点群、ロボット、可視化などの文脈を重視してランキングします。

## RAG実装

実装済み:

- `rag_documents` のchunk化
- タイトル、概要、根拠文、キーワード、PDF由来テキストの検索単位化
- 各chunkへの `local-hashed-ngram-v1` embedding付与
- DuckDBの `rag_chunks.embedding` 列への固定長ベクトル保存
- chunk類似度、キーワード一致、既存スコアを組み合わせたハイブリッド検索
- 上位chunkを根拠としてMarkdown/JSONに出力
- 参照元、該当chunk、詳細URL、PDFリンクの提示
- `sentence-transformers`（`intfloat/multilingual-e5-small` など）による意味embeddingモデルへの差し替え（`--embedding-model` フラグで切り替え）
- DuckDB VSS拡張 + HNSWインデックスによるANN検索（FLOAT[]スキーマ時に自動有効化）
- `janome` による日本語形態素解析でクエリを展開（部分文字列の誤マッチを自動フィルタ）
- `--expand-with-llm` フラグで Claude Haiku による関連キーワード自動生成
- `jaea/scripts/fetch_pdf_text.py` によるPDF本文抽出パイプライン（`pypdf` + `httpx`、`--rechunk` でchunk再作成）
