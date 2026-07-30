# Codex Instructions

このリポジトリでは、JAEA特許・報告書検索システムを開発する。

## 参照ドキュメント

- 全体仕様: @CLAUDE.md
- 実装計画: @docs/implementation.md
- 共通skill仕様: @skills/jaea-search/SKILL.md

## 起動時の利用方法

Codexでこのリポジトリを開いた場合は、本ファイルをプロジェクト指示として読み込む。ユーザが `jaea-search "検索キーワード"` と入力した場合は、JAEA特許・報告書検索として扱う。

DuckDB検索スクリプトが未実装または利用不能な場合は、以下の既存成果物をフォールバックとして参照する。

- `jaea/output/jaea_patents_ai_curated.md`
- `jaea/output/jaea_reports_cv_ar_high_confidence.md`
- `jaea/output/jaea_reports_cv_ar_candidates.md`

## 依存管理

必要なPythonライブラリと実行環境の管理は、すべて `uv` を使う。

- `pip install ...` を直接使わない。
- Python依存関係は `pyproject.toml` に記録する。
- ライブラリ追加は `uv add ...` を使う。
- スクリプト実行は原則として `uv run ...` を使う。
- DuckDBのPythonパッケージは `uv add duckdb` で導入する。
- `uv.lock` はコミット対象にする。
