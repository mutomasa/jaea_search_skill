#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from jaea.scripts.rag_embeddings import EMBEDDING_DIM, chunk_text, embed_text, pack_embedding  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "jaea" / "output"
DEFAULT_DB_PATH = REPO_ROOT / "jaea" / "jaea.duckdb"

SOURCE_FILES = {
    "patents_all": OUTPUT_DIR / "jaea_patents_all.csv",
    "patents_ai_candidates": OUTPUT_DIR / "jaea_patents_ai_candidates.csv",
    "patents_ai_curated": OUTPUT_DIR / "jaea_patents_ai_curated.csv",
    "reports_all": OUTPUT_DIR / "jaea_reports_all.jsonl",
    "reports_cv_ar_candidates": OUTPUT_DIR / "jaea_reports_cv_ar_candidates.csv",
    "reports_cv_ar_high_confidence": OUTPUT_DIR / "jaea_reports_cv_ar_high_confidence.csv",
}
INSERT_BATCH_SIZE = 1000

RAG_COLUMNS = [
    "doc_type",
    "doc_id",
    "doc_no",
    "title",
    "abstract",
    "authors",
    "categories",
    "keywords",
    "score",
    "evidence",
    "publication_date",
    "detail_url",
    "pdf_links",
    "source_table",
    "search_text",
    "pdf_text",
]


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def load_jsonl(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def load_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix == ".jsonl":
        return load_jsonl(path)
    return load_csv(path)


def ordered_columns(rows: Iterable[dict[str, str]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def create_text_table(conn: duckdb.DuckDBPyConnection, table_name: str, rows: list[dict[str, str]]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {quote_identifier(table_name)}")
    columns = ordered_columns(rows)
    if not columns:
        conn.execute(f"CREATE TABLE {quote_identifier(table_name)} (empty_marker VARCHAR)")
        return

    column_sql = ", ".join(f"{quote_identifier(column)} VARCHAR" for column in columns)
    conn.execute(f"CREATE TABLE {quote_identifier(table_name)} ({column_sql})")
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"INSERT INTO {quote_identifier(table_name)} VALUES ({placeholders})"
    values = [[stringify(row.get(column, "")) for column in columns] for row in rows]
    conn.executemany(insert_sql, values)


def stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def make_search_text(*parts: str) -> str:
    return " ".join(part for part in parts if part).strip()


def patent_row(row: dict[str, str], source_table: str) -> dict[str, object]:
    title = row.get("title", "")
    abstract = row.get("abstract", "")
    categories = ", ".join(part for part in [row.get("bucket", ""), row.get("category", "")] if part)
    keywords = row.get("matched_keywords", "")
    evidence = row.get("reason", "") or keywords
    pdf_text = row.get("pdf_text", "") or row.get("full_text", "") or row.get("text", "")
    return {
        "doc_type": "patent",
        "doc_id": row.get("patent_id", ""),
        "doc_no": row.get("publication_no", "") or row.get("application_no", "") or row.get("registration_no", ""),
        "title": title,
        "abstract": abstract,
        "authors": row.get("authors", ""),
        "categories": categories,
        "keywords": keywords,
        "score": row.get("score", ""),
        "evidence": evidence,
        "publication_date": row.get("publication_date", ""),
        "detail_url": row.get("detail_url", ""),
        "pdf_links": row.get("pdf_links", ""),
        "source_table": source_table,
        "search_text": make_search_text(title, abstract, categories, keywords, evidence, row.get("ipc", ""), pdf_text),
        "pdf_text": pdf_text,
    }


def report_row(row: dict[str, str], source_table: str) -> dict[str, object]:
    title = row.get("title_ja", "") or row.get("title_en", "")
    abstract = make_search_text(row.get("abstract_ja", ""), row.get("abstract_en", ""))
    categories = row.get("categories", "")
    keywords = row.get("keywords", "") or row.get("matched_keywords", "")
    evidence = row.get("evidence_text", "") or row.get("matched_keywords", "")
    pdf_text = row.get("pdf_text", "") or row.get("full_text", "") or row.get("text", "")
    return {
        "doc_type": "report",
        "doc_id": row.get("report_id", ""),
        "doc_no": row.get("report_no", ""),
        "title": title,
        "abstract": abstract,
        "authors": row.get("authors_ja", "") or row.get("authors_en", ""),
        "categories": categories,
        "keywords": keywords,
        "score": row.get("score", ""),
        "evidence": evidence,
        "publication_date": row.get("publication_date", ""),
        "detail_url": row.get("detail_url", ""),
        "pdf_links": row.get("pdf_links", ""),
        "source_table": source_table,
        "search_text": make_search_text(title, row.get("title_en", ""), abstract, categories, keywords, evidence, pdf_text),
        "pdf_text": pdf_text,
    }


def build_rag_rows(source_rows: dict[str, list[dict[str, str]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, object]) -> None:
        key = (str(row["doc_type"]), str(row["doc_id"]))
        if key in seen or not key[1]:
            return
        seen.add(key)
        rows.append(row)

    for source in ("patents_ai_curated", "patents_ai_candidates", "patents_all"):
        for row in source_rows.get(source, []):
            add(patent_row(row, source))

    for source in ("reports_cv_ar_high_confidence", "reports_cv_ar_candidates", "reports_all"):
        for row in source_rows.get(source, []):
            add(report_row(row, source))

    return rows


def create_rag_documents(conn: duckdb.DuckDBPyConnection, rows: list[dict[str, object]]) -> None:
    conn.execute("DROP TABLE IF EXISTS rag_documents")
    conn.execute(
        """
        CREATE TABLE rag_documents (
            doc_type VARCHAR,
            doc_id VARCHAR,
            doc_no VARCHAR,
            title VARCHAR,
            abstract VARCHAR,
            authors VARCHAR,
            categories VARCHAR,
            keywords VARCHAR,
            score INTEGER,
            evidence VARCHAR,
            publication_date VARCHAR,
            detail_url VARCHAR,
            pdf_links VARCHAR,
            source_table VARCHAR,
            search_text VARCHAR,
            pdf_text VARCHAR
        )
        """
    )
    values = [
        [
            row["doc_type"],
            row["doc_id"],
            row["doc_no"],
            row["title"],
            row["abstract"],
            row["authors"],
            row["categories"],
            row["keywords"],
            int(row["score"]) if str(row["score"]).isdigit() else 0,
            row["evidence"],
            row["publication_date"],
            row["detail_url"],
            row["pdf_links"],
            row["source_table"],
            row["search_text"],
            row["pdf_text"],
        ]
        for row in rows
    ]
    conn.executemany(
        "INSERT INTO rag_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        values,
    )


def make_document_chunks(row: dict[str, object]) -> list[dict[str, object]]:
    sections = [
        ("title", f"タイトル: {row['title']}"),
        (
            "metadata",
            make_search_text(
                f"タイトル: {row['title']}",
                f"キーワード: {row['keywords']}",
                f"分類: {row['categories']}",
                f"根拠文: {row['evidence']}",
                f"概要: {row['abstract']}",
            ),
        ),
        ("pdf_text", f"PDF本文: {row['pdf_text']}"),
    ]
    chunks: list[dict[str, object]] = []
    chunk_index = 0
    for source, text in sections:
        content = make_search_text(str(text))
        if not content or (source == "pdf_text" and not row["pdf_text"]):
            continue
        for chunk in chunk_text(content):
            chunk_index += 1
            chunks.append(
                {
                    "chunk_id": f"{row['doc_type']}:{row['doc_id']}:{chunk_index}",
                    "doc_type": row["doc_type"],
                    "doc_id": row["doc_id"],
                    "doc_no": row["doc_no"],
                    "title": row["title"],
                    "chunk_index": chunk_index,
                    "chunk_source": source,
                    "chunk_text": chunk,
                    "embedding": pack_embedding(embed_text(chunk)),
                    "embedding_dim": EMBEDDING_DIM,
                    "embedding_model": f"local-hashed-ngram-v1:{EMBEDDING_DIM}",
                    "detail_url": row["detail_url"],
                    "pdf_links": row["pdf_links"],
                    "source_table": row["source_table"],
                }
            )
    return chunks


def create_rag_chunks(conn: duckdb.DuckDBPyConnection, rows: list[dict[str, object]]) -> None:
    conn.execute("DROP TABLE IF EXISTS rag_chunks")
    conn.execute(
        """
        CREATE TABLE rag_chunks (
            chunk_id VARCHAR,
            doc_type VARCHAR,
            doc_id VARCHAR,
            doc_no VARCHAR,
            title VARCHAR,
            chunk_index INTEGER,
            chunk_source VARCHAR,
            chunk_text VARCHAR,
            embedding BLOB,
            embedding_dim INTEGER,
            embedding_model VARCHAR,
            detail_url VARCHAR,
            pdf_links VARCHAR,
            source_table VARCHAR
        )
        """
    )
    insert_sql = "INSERT INTO rag_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    batch: list[list[object]] = []
    for document in rows:
        for row in make_document_chunks(document):
            batch.append(
                [
                    row["chunk_id"],
                    row["doc_type"],
                    row["doc_id"],
                    row["doc_no"],
                    row["title"],
                    row["chunk_index"],
                    row["chunk_source"],
                    row["chunk_text"],
                    row["embedding"],
                    row["embedding_dim"],
                    row["embedding_model"],
                    row["detail_url"],
                    row["pdf_links"],
                    row["source_table"],
                ]
            )
            if len(batch) >= INSERT_BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()
    if batch:
        conn.executemany(insert_sql, batch)


def build_database(db_path: Path = DEFAULT_DB_PATH, output_dir: Path = OUTPUT_DIR) -> dict[str, int]:
    source_rows: dict[str, list[dict[str, str]]] = {}
    conn = duckdb.connect(str(db_path))
    try:
        for table_name, source_path in SOURCE_FILES.items():
            path = output_dir / source_path.name
            rows = load_rows(path)
            source_rows[table_name] = rows
            create_text_table(conn, table_name, rows)

        rag_rows = build_rag_rows(source_rows)
        create_rag_documents(conn, rag_rows)
        create_rag_chunks(conn, rag_rows)

        summary = {
            table: conn.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0]
            for table in [*SOURCE_FILES.keys(), "rag_documents", "rag_chunks"]
        }
        conn.execute("CHECKPOINT")
        return summary
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DuckDB database for JAEA RAG search.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    summary = build_database(args.db, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
