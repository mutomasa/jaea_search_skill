# JAEA特許・報告書RAG

JAEAの特許データと報告書データをDuckDBに取り込み、CodexまたはClaude Codeから `jaea-rag "検索キーワード"` で関連資料を探すためのローカルRAGシステムです。

## できること

- JAEA特許データと報告書データを横断検索する。
- 研究アイディアや技術キーワードに関連する特許・報告書を提示する。
- 関連理由、技術分類、詳細URL、PDFリンクをMarkdownまたはJSONで出力する。
- 画像処理、Computer vision、AR mapping、3Dモデル生成、空間マッピング、線量マッピング、遠隔ロボット系の資料を探す。
- DuckDBが未作成の場合は、検索スクリプトから自動構築する。

## 対応エージェント

このリポジトリはCodexとClaude Codeの両方に対応しています。

- Codex向け指示: [AGENTS.md](/Users/masa/eques/AGENTS.md)
- Claude Code向け指示: [CLAUDE.md](/Users/masa/eques/CLAUDE.md)
- 共通skill仕様: [skills/jaea-rag/SKILL.md](/Users/masa/eques/skills/jaea-rag/SKILL.md)
- Claude Codeショートカット: [.claude/commands/jaea-rag.md](/Users/masa/eques/.claude/commands/jaea-rag.md)

## スキルの呼び方

Codex / Claude Code共通の標準呼び出しは次です。

```text
jaea-rag "検索キーワード"
```

例:

```text
jaea-rag "3Dモデル生成"
jaea-rag "カメラ画像 三次元図面"
jaea-rag "線量マッピング 遠隔ロボット"
jaea-rag "AR"
```

Claude Codeでは補助的なショートカットも使えます。

```text
/jaea-rag 検索キーワード
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
- MarkdownまたはJSONで結果を出力する。

スキルは、Codex / Claude Codeに「検索CLIをどう使うか」と「結果をどう説明するか」を教える説明書です。

```text
skills/jaea-rag/SKILL.md
```

スキルは次を行います。

- `jaea-rag "検索キーワード"` をJAEA RAG検索として認識させる。
- 検索CLIを実行するよう案内する。
- 結果を「関連特許」「関連報告書」「技術的接点」に整理して返す。
- DuckDBや検索CLIが使えない場合のフォールバック先を示す。

要するに、検索CLIは検索エンジン本体で、スキルはエージェント用の操作説明です。ユーザは通常、次の形式だけ覚えれば十分です。

```text
jaea-rag "ドローン"
```

## 初回セットアップ

依存管理はすべて `uv` を使います。`pip install ...` は直接使いません。

依存関係を同期します。

```bash
uv sync
```

DuckDBを初めて構築する場合は、次を実行します。

```bash
uv run python jaea/scripts/build_duckdb.py
```

生成されるDB:

```text
jaea/jaea.duckdb
```

`jaea/jaea.duckdb` は元データから再生成できるため、git管理対象外です。

## 検索CLI

Markdownで検索します。

```bash
uv run python jaea/scripts/search_rag.py jaea-rag "3Dモデル生成"
```

件数を指定します。

```bash
uv run python jaea/scripts/search_rag.py jaea-rag "三次元図面" --limit 5
```

JSONで出力します。

```bash
uv run python jaea/scripts/search_rag.py jaea-rag "カメラ画像" --format json
```

DBが存在しない場合、`search_rag.py` が `jaea/output` のデータから自動でDuckDBを構築します。

## データ

主な入力データは [jaea/output](/Users/masa/eques/jaea/output) にあります。

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

## テスト

単体テストはリポジトリ直下の [tests](/Users/masa/eques/tests) にあります。

```bash
uv run pytest
```

現在のテストでは、入力形式、DuckDB構築、検索ランキング、`AR` と `Ar`/`argon` の誤一致回避を確認します。

## 注意

- 検索結果は関連候補であり、法的な特許侵害判断ではありません。
- `AR` はアルゴンの `Ar` と誤一致しやすいため、検索スクリプト側で文脈フィルタを入れています。
- `3D` や `三次元` は数値解析にも出るため、画像、カメラ、マッピング、点群、ロボット、可視化などの文脈を重視してランキングします。
