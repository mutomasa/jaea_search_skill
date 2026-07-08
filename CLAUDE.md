# JAEA特許・報告書RAGシステム仕様書

## 目的

`jaea/output` フォルダに蓄積したJAEAの特許データと報告書データを、DuckDBで検索・分析できる形に統合する。さらに、Codex/Claude向けのskillを作成し、ユーザが入力した研究アイディアや技術テーマに対して、関連する特許や報告書をRAGとして提示できるシステムを構築する。

## 背景

現在、`jaea/output` には以下のデータが存在する。

- 特許データ
  - `jaea_patents_all.csv`
  - `jaea_patents_all.json`
  - `jaea_patents_ai_candidates.csv`
  - `jaea_patents_ai_candidates.md`
  - `jaea_patents_ai_curated.csv`
  - `jaea_patents_ai_curated.md`
  - `jaea_patents_summary.json`
- 報告書データ
  - `jaea_reports_all.jsonl`
  - `jaea_reports_cv_ar_candidates.csv`
  - `jaea_reports_cv_ar_candidates.md`
  - `jaea_reports_cv_ar_high_confidence.csv`
  - `jaea_reports_cv_ar_high_confidence.md`
  - `jaea_reports_cv_ar_summary.json`
  - `jaea_reports_cv_ar_errors.jsonl`

特許データにはAI/ML関連の抽出結果があり、報告書データにはComputer vision / AR mapping / 画像処理・空間マッピング寄りの抽出結果がある。これらを横断検索できるようにし、ユーザのアイディアに対して既存技術・関連資料・参考になる報告書を提示する。

## ゴール

1. DuckDBをインストールし、`jaea/output` のCSV/JSON/JSONLを取り込める状態にする。
2. 特許データと報告書データを統一的に検索できるDuckDBスキーマを作る。
3. ユーザのアイディア文から関連しそうな特許・報告書を検索するRAG用skillを作る。
4. skillは検索結果をそのまま返すだけでなく、関連理由、技術分類、活用可能性、詳細URL、PDFリンクを整理して提示する。
5. まずはローカル完結のシステムとして実装し、将来的に埋め込みベクトル検索やWeb UIに拡張できる設計にする。

## 依存管理

必要なPythonライブラリと実行環境の管理は、すべて `uv` を使う。

- `pip install ...` を直接使わない。
- Python依存関係は `pyproject.toml` に記録する。
- ライブラリ追加は `uv add ...` を使う。
- スクリプト実行は原則として `uv run ...` を使う。
- DuckDBのPythonパッケージも `uv add duckdb` で導入する。
- 依存関係の再現性を保つため、`uv.lock` をコミット対象にする。

## 対象データ

### 特許

主な入力ファイル:

- `jaea/output/jaea_patents_all.csv`
- `jaea/output/jaea_patents_ai_candidates.csv`
- `jaea/output/jaea_patents_ai_curated.csv`

主な項目:

- `patent_id`
- `title`
- `authors`
- `abstract`
- `detail_url`
- `application_no`
- `publication_no`
- `registration_no`
- `application_date`
- `publication_date`
- `registration_date`
- `ipc`
- `pdf_links`
- `score`
- `matched_keywords`
- `category`
- `reason`

### 報告書

主な入力ファイル:

- `jaea/output/jaea_reports_all.jsonl`
- `jaea/output/jaea_reports_cv_ar_candidates.csv`
- `jaea/output/jaea_reports_cv_ar_high_confidence.csv`

主な項目:

- `report_id`
- `report_no`
- `title_ja`
- `title_en`
- `authors_ja`
- `authors_en`
- `abstract_ja`
- `abstract_en`
- `language`
- `pages`
- `publication_date`
- `keywords`
- `facilities`
- `doi_url`
- `categories`
- `score`
- `matched_keywords`
- `evidence_text`
- `detail_url`
- `pdf_links`

## DuckDB設計

DuckDBファイルは以下を想定する。

- `jaea/jaea.duckdb`

作成する主要テーブル:

- `patents_all`
  - 特許全件
- `patents_ai_candidates`
  - AI/ML関連の特許候補
- `patents_ai_curated`
  - 人手で整理したAI/ML特許ピックアップ
- `reports_all`
  - 報告書全件
- `reports_cv_ar_candidates`
  - Computer vision / AR mapping系の広め候補
- `reports_cv_ar_high_confidence`
  - Computer vision / AR mapping系の高信頼候補
- `rag_documents`
  - 特許・報告書を横断検索するための統合ビューまたは実体テーブル

`rag_documents` の想定カラム:

- `doc_type`
  - `patent` または `report`
- `doc_id`
- `doc_no`
- `title`
- `abstract`
- `authors`
- `categories`
- `keywords`
- `score`
- `evidence`
- `publication_date`
- `detail_url`
- `pdf_links`
- `source_table`
- `search_text`

`search_text` にはタイトル、概要、キーワード、分類、根拠文を連結し、全文検索または類似検索に使う。

## 検索方式

初期実装では、以下の順で実装する。

1. DuckDB SQLによるキーワード検索
   - `LIKE`
   - `regexp_matches`
   - 日本語・英語キーワードのOR検索
2. スコアリング
   - タイトル一致を高く評価
   - 概要一致を中程度に評価
   - キーワード・分類一致を高く評価
   - 既存の `score` や `categories` を補助的に利用
3. 結果整形
   - 上位候補を特許・報告書に分けて提示
   - 関連理由を短く説明
   - 詳細URLとPDFリンクを付ける

将来拡張:

- DuckDB VSS拡張または別途ベクトルDBによる埋め込み検索
- 日本語形態素解析による検索語展開
- LLMによるクエリ拡張
- Streamlit等の簡易UI

## Skill設計

skill名の候補:

- `jaea-rag`

skillの役割:

- ユーザの研究アイディア、技術テーマ、仮説、製品案を受け取る。
- DuckDB内の特許・報告書データを検索する。
- 関連する特許・報告書を根拠付きで提示する。
- 単なる一覧ではなく、以下を整理して返す。
  - 関連資料
  - なぜ関連するか
  - 技術的な接点
  - 既存技術との差分を考えるための観点
  - 参照URL/PDF

想定されるユーザ入力:

- 「炉内の3Dモデル生成に関係する報告書と特許を探して」
- 「カメラ画像から三次元図面を作る技術に近いものはある？」
- 「ロボットと線量マッピングを組み合わせた研究アイディアに関連する既存資料を出して」
- 「このアイディアは既存特許と近いか？」

想定出力:

- 要約
- 関連度の高い特許
- 関連度の高い報告書
- 技術的な接点
- 追加で見るべきキーワード
- 参照リンク

## 実装ステップ

詳細な実装手順と進捗管理は @docs/implementation.md を参照する。

## 注意点

- `jaea/output` の既存データは一次成果物として保持し、DuckDB構築時に破壊しない。
- 低スコアの候補にはノイズが含まれるため、RAG提示では高信頼候補を優先する。
- `AR` は `argon` や `Ar` と誤一致しやすいため、検索時には単語境界や文脈を考慮する。
- `3D` や `三次元` は数値解析・流体解析にも出るため、画像、カメラ、マッピング、点群、ロボット、可視化などの文脈と組み合わせて評価する。
- ユーザには、検索結果が「関連候補」であり、法的な特許侵害判断ではないことを明示する。

## 完了条件

- DuckDBに特許・報告書データが取り込まれている。
- `rag_documents` で横断検索できる。
- skillからユーザのアイディアに関連する特許・報告書を提示できる。
- 少なくとも上記検証クエリで期待する候補が返る。
- 使い方が `CLAUDE.md` またはskill内に記載されている。
