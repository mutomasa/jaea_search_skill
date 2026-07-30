#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from jaea.scripts.build_duckdb import DEFAULT_DB_PATH, OUTPUT_DIR, SOURCE_FILES, build_database, quote_identifier  # noqa: E402
from jaea.scripts.search_rag import SearchResult, search_database  # noqa: E402

REQUIRED_RUNTIME_TABLES = [*SOURCE_FILES.keys(), "rag_documents", "rag_chunks"]
DEFAULT_SMOKE_QUERY = "3Dモデル生成"


def validate_source_files(output_dir: Path = OUTPUT_DIR) -> None:
    missing = []
    for source_path in SOURCE_FILES.values():
        path = output_dir / source_path.name
        if not path.exists():
            missing.append(path)
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"JAEA入力データが不足しています。\n{formatted}")


def database_table_counts(db_path: Path) -> dict[str, int]:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        counts: dict[str, int] = {}
        for table in REQUIRED_RUNTIME_TABLES:
            counts[table] = int(conn.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0])
        return counts
    finally:
        conn.close()


def validate_database(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDBがありません: {db_path}")

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        schema = dict(
            conn.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'rag_chunks'
                """
            ).fetchall()
        )
    finally:
        conn.close()

    if schema.get("embedding") != "BLOB" or schema.get("embedding_dim") != "INTEGER":
        raise RuntimeError("rag_chunksのembeddingスキーマが不正です。")

    counts = database_table_counts(db_path)
    if counts.get("rag_documents", 0) <= 0:
        raise RuntimeError("rag_documentsが空です。")
    if counts.get("rag_chunks", 0) <= 0:
        raise RuntimeError("rag_chunksが空です。embedding作成が完了していません。")
    return counts


def database_is_ready(db_path: Path) -> bool:
    try:
        validate_database(db_path)
    except (duckdb.Error, FileNotFoundError, RuntimeError):
        return False
    return True


def smoke_search(db_path: Path, query: str, limit: int) -> list[SearchResult]:
    results = search_database(db_path, query, limit=limit)
    if not results:
        raise RuntimeError(f"検索スモークテストで結果が0件でした: {query}")
    return results


def setup_database(
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = OUTPUT_DIR,
    *,
    force: bool = False,
    smoke_query: str = DEFAULT_SMOKE_QUERY,
    smoke_limit: int = 3,
    skip_smoke_test: bool = False,
) -> dict[str, object]:
    validate_source_files(output_dir)

    built = False
    if force or not database_is_ready(db_path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        build_database(db_path, output_dir)
        built = True

    counts = validate_database(db_path)
    smoke_results = [] if skip_smoke_test else smoke_search(db_path, smoke_query, smoke_limit)
    return {
        "db_path": str(db_path),
        "built": built,
        "counts": counts,
        "smoke_query": None if skip_smoke_test else smoke_query,
        "smoke_result_count": len(smoke_results),
        "smoke_top_results": [result.to_dict() for result in smoke_results[:smoke_limit]],
    }


def print_summary(summary: dict[str, object]) -> None:
    action = "作成/更新しました" if summary["built"] else "既存DBを利用しました"
    print(f"DuckDB: {summary['db_path']} ({action})")
    print("登録件数:")
    for table, count in (summary["counts"] or {}).items():
        print(f"- {table}: {count}")
    if summary["smoke_query"]:
        print(f"検索スモークテスト: {summary['smoke_query']} ({summary['smoke_result_count']}件)")
        for result in summary["smoke_top_results"][:3]:
            print(f"- {result['doc_type']}: {result['title']}")
    print("初回セットアップが完了しました。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JAEA検索用DuckDBのデータ登録、chunk化、embedding作成、検索確認をまとめて実行します。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="作成または検証するDuckDBファイル")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="JAEA入力データのディレクトリ")
    parser.add_argument("--force", action="store_true", help="既存DBが有効でも再構築する")
    parser.add_argument("--smoke-query", default=DEFAULT_SMOKE_QUERY, help="セットアップ後に確認する検索語")
    parser.add_argument("--smoke-limit", type=int, default=3, help="検索スモークテストの表示件数")
    parser.add_argument("--skip-smoke-test", action="store_true", help="検索スモークテストを省略する")
    parser.add_argument("--json", action="store_true", help="結果をJSONで出力する")
    args = parser.parse_args()

    try:
        summary = setup_database(
            args.db,
            args.output_dir,
            force=args.force,
            smoke_query=args.smoke_query,
            smoke_limit=args.smoke_limit,
            skip_smoke_test=args.skip_smoke_test,
        )
    except Exception as exc:  # noqa: BLE001
        parser.exit(2, f"{exc}\n")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
