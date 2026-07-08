# JAEA RAGシステム実装計画

## 進捗

- [x] `a8b9877` JAEA特許・報告書スクレイピング成果、出力データ、RAG仕様書を追加

## Step 1: DuckDB導入

- [ ] DuckDB CLIまたはPythonパッケージをインストールする。
- [ ] PythonからDuckDBを操作できるようにする。
- [ ] `jaea/jaea.duckdb` を作成する。

## Step 2: データ取り込みスクリプト

作成候補:

- `jaea/scripts/build_duckdb.py`

実装項目:

- [ ] `jaea/output` のCSV/JSONLをDuckDBに取り込む。
- [ ] テーブルを作成または再作成する。
- [ ] `rag_documents` を生成する。
- [ ] 件数チェックを行う。

## Step 3: 検索スクリプト

作成候補:

- `jaea/scripts/search_rag.py`

実装項目:

- [ ] ユーザクエリを受け取る。
- [ ] DuckDBから関連資料を検索する。
- [ ] 結果をMarkdownまたはJSONで返す。
- [ ] 関連理由、技術分類、詳細URL、PDFリンクを整形して返す。

## Step 4: skill作成

作成候補:

- `$CODEX_HOME/skills/jaea-rag/SKILL.md`

skillに含める内容:

- [ ] DuckDBの場所
- [ ] 検索スクリプトの実行方法
- [ ] 結果の読み方
- [ ] ユーザへの返答フォーマット
- [ ] 検索語展開の方針

## Step 5: 検証

最低限確認するクエリ:

- [ ] `3Dモデル生成`
- [ ] `三次元図面`
- [ ] `カメラ画像`
- [ ] `セマンティックサーベイマップ`
- [ ] `線量マッピング`
- [ ] `遠隔ロボット`
- [ ] `AR`
- [ ] `空間マッピング`

確認項目:

- [ ] 特許と報告書が両方検索できること
- [ ] 高信頼候補が上位に出ること
- [ ] 詳細URL/PDFリンクが出ること
- [ ] 関連理由が説明できること
