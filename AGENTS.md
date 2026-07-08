# Codex Instructions

このリポジトリでは、JAEA特許・報告書RAGシステムを開発する。

## 参照ドキュメント

- 全体仕様: @CLAUDE.md
- 実装計画: @docs/implementation.md

## 依存管理

必要なPythonライブラリと実行環境の管理は、すべて `uv` を使う。

- `pip install ...` を直接使わない。
- Python依存関係は `pyproject.toml` に記録する。
- ライブラリ追加は `uv add ...` を使う。
- スクリプト実行は原則として `uv run ...` を使う。
- DuckDBのPythonパッケージは `uv add duckdb` で導入する。
- `uv.lock` はコミット対象にする。
