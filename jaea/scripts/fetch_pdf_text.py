#!/usr/bin/env python3
"""Download PDF files from JAEA links and extract text into rag_documents.pdf_text.

Usage:
    uv run python jaea/scripts/fetch_pdf_text.py
    uv run python jaea/scripts/fetch_pdf_text.py --limit 20
    uv run python jaea/scripts/fetch_pdf_text.py --dry-run
    uv run python jaea/scripts/fetch_pdf_text.py --rechunk   # rebuild rag_chunks for updated docs
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DB_PATH = REPO_ROOT / "jaea" / "jaea.duckdb"
DEFAULT_LIMIT = 50


def _fetch_pdf_bytes(url: str) -> bytes:
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("Run: uv add httpx") from exc
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError("Run: uv add pypdf") from exc
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def first_pdf_url(pdf_links: str) -> str | None:
    if not pdf_links:
        return None
    for part in re.split(r"[\s|,]+", pdf_links.strip()):
        part = part.strip()
        if part.startswith("http") and ".pdf" in part.lower():
            return part
    return None


def rechunk_documents(conn: duckdb.DuckDBPyConnection, doc_ids: list[tuple[str, str]]) -> int:
    """Rebuild rag_chunks rows for the given (doc_type, doc_id) pairs."""
    from jaea.scripts.build_duckdb import make_document_chunks
    from jaea.scripts.rag_embeddings import EMBEDDING_DIM, embed_text
    import struct

    schema = dict(
        conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'rag_chunks'"
        ).fetchall()
    )
    use_float = schema.get("embedding", "BLOB").startswith("FLOAT[")

    refreshed = 0
    for doc_type, doc_id in doc_ids:
        conn.execute("DELETE FROM rag_chunks WHERE doc_type = ? AND doc_id = ?", [doc_type, doc_id])
        row = conn.execute(
            "SELECT * FROM rag_documents WHERE doc_type = ? AND doc_id = ?", [doc_type, doc_id]
        ).fetchone()
        if not row:
            continue
        cols = [c[0] for c in conn.description]
        doc = dict(zip(cols, row))

        for chunk in make_document_chunks(doc):
            vec: list[float] = embed_text(str(chunk["chunk_text"]), dim=EMBEDDING_DIM)
            emb = vec if use_float else struct.pack(f"{len(vec)}f", *vec)
            conn.execute(
                "INSERT INTO rag_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    chunk["chunk_id"],
                    chunk["doc_type"],
                    chunk["doc_id"],
                    chunk["doc_no"],
                    chunk["title"],
                    chunk["chunk_index"],
                    chunk["chunk_source"],
                    chunk["chunk_text"],
                    emb,
                    EMBEDDING_DIM,
                    f"local-hashed-ngram-v1:{EMBEDDING_DIM}",
                    chunk["detail_url"],
                    chunk["pdf_links"],
                    chunk["source_table"],
                ],
            )
            refreshed += 1
    return refreshed


def update_pdf_texts(
    db_path: Path,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    rechunk: bool = False,
) -> dict[str, int]:
    conn = duckdb.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT doc_type, doc_id, pdf_links
            FROM rag_documents
            WHERE (pdf_text IS NULL OR pdf_text = '')
              AND pdf_links IS NOT NULL AND pdf_links != ''
            LIMIT ?
            """,
            [limit],
        ).fetchall()

        if not rows:
            print("pdf_text が空のドキュメントはありません。")
            return {"succeeded": 0, "failed": 0, "total": 0, "chunks_added": 0}

        succeeded = 0
        failed = 0
        updated_ids: list[tuple[str, str]] = []

        for doc_type, doc_id, pdf_links in rows:
            url = first_pdf_url(pdf_links)
            if not url:
                continue
            print(f"  {doc_type}:{doc_id}  {url}")
            if dry_run:
                print("    [dry-run] スキップ")
                continue
            try:
                pdf_bytes = _fetch_pdf_bytes(url)
                text = extract_pdf_text(pdf_bytes)
                if text:
                    conn.execute(
                        "UPDATE rag_documents SET pdf_text = ? WHERE doc_type = ? AND doc_id = ?",
                        [text, doc_type, doc_id],
                    )
                    updated_ids.append((doc_type, doc_id))
                    succeeded += 1
                    print(f"    OK ({len(text):,} 文字)")
                else:
                    print("    テキストなし")
            except Exception as exc:
                failed += 1
                print(f"    FAILED: {exc}")

        chunks_added = 0
        if rechunk and updated_ids:
            print(f"\n{len(updated_ids)} 件のドキュメントの chunk を再作成中...")
            chunks_added = rechunk_documents(conn, updated_ids)
            print(f"  chunk 追加: {chunks_added} 件")

        conn.execute("CHECKPOINT")
        return {"succeeded": succeeded, "failed": failed, "total": len(rows), "chunks_added": chunks_added}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JAEA PDF を取得して rag_documents.pdf_text を更新する。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="1回で処理する最大PDF数")
    parser.add_argument("--dry-run", action="store_true", help="ダウンロードせずに対象URLを表示")
    parser.add_argument("--rechunk", action="store_true", help="PDF取得後にrag_chunksを再作成する")
    args = parser.parse_args()

    result = update_pdf_texts(args.db, args.limit, args.dry_run, args.rechunk)
    print(
        f"\n完了: 成功={result['succeeded']}, 失敗={result['failed']}, "
        f"対象={result['total']}, chunk追加={result['chunks_added']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
