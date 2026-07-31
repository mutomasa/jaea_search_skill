#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from jaea.scripts.rag_embeddings import cosine_similarity, embed_text, get_embedder, to_vector, unpack_embedding  # noqa: E402

DEFAULT_DB_PATH = REPO_ROOT / "jaea" / "jaea.duckdb"
DEFAULT_LIMIT = 8

QUERY_EXPANSIONS = {
    "3d": ["3D", "3次元", "三次元", "3Dモデル", "三次元モデル", "3Dイメージング"],
    "3D": ["3D", "3次元", "三次元", "3Dモデル", "三次元モデル", "3Dイメージング"],
    "三次元": ["三次元", "3次元", "3D", "三次元図面", "三次元モデル", "三次元復元"],
    "3Dモデル生成": ["3Dモデル生成", "三次元モデル", "3D model", "3次元", "三次元復元", "モデリング"],
    "三次元図面": ["三次元図面", "カメラ画像", "画像マッチング", "三次元", "3D"],
    "カメラ画像": ["カメラ画像", "カメラ", "画像分析", "画像処理", "画像解析"],
    "セマンティックサーベイマップ": ["セマンティックサーベイマップ", "サーベイマップ", "地図生成", "ロボット", "マップ"],
    "線量マッピング": ["線量マッピング", "線量率マップ", "放射線場マッピング", "マッピング", "線量"],
    "遠隔ロボット": ["遠隔ロボット", "ロボット", "遠隔技術", "遠隔操作", "ROV"],
    "AR": ["AR", "拡張現実", "augmented reality", "重畳表示", "仮想空間", "現実空間"],
    "空間マッピング": ["空間マッピング", "地図生成", "マッピング", "SLAM", "自己位置推定", "位置姿勢"],
}


@dataclass
class SearchResult:
    doc_type: str
    doc_id: str
    doc_no: str
    title: str
    abstract: str
    categories: str
    keywords: str
    score: int
    evidence: str
    publication_date: str
    detail_url: str
    pdf_links: str
    source_table: str
    rank_score: int
    matched_terms: list[str]
    evidence_chunks: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "SearchResult":
        return cls(
            doc_type=str(row["doc_type"] or ""),
            doc_id=str(row["doc_id"] or ""),
            doc_no=str(row["doc_no"] or ""),
            title=str(row["title"] or ""),
            abstract=str(row["abstract"] or ""),
            categories=str(row["categories"] or ""),
            keywords=str(row["keywords"] or ""),
            score=int(row["score"] or 0),
            evidence=str(row["evidence"] or ""),
            publication_date=str(row["publication_date"] or ""),
            detail_url=str(row["detail_url"] or ""),
            pdf_links=str(row["pdf_links"] or ""),
            source_table=str(row["source_table"] or ""),
            rank_score=int(row["rank_score"] or 0),
            matched_terms=split_terms(str(row["matched_terms"] or "")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "doc_type": self.doc_type,
            "doc_id": self.doc_id,
            "doc_no": self.doc_no,
            "title": self.title,
            "categories": self.categories,
            "keywords": self.keywords,
            "score": self.score,
            "rank_score": self.rank_score,
            "matched_terms": self.matched_terms,
            "evidence": self.evidence,
            "publication_date": self.publication_date,
            "detail_url": self.detail_url,
            "pdf_links": self.pdf_links,
            "source_table": self.source_table,
            "evidence_chunks": self.evidence_chunks,
        }


def parse_invocation(argv: list[str]) -> str:
    if not argv:
        raise ValueError('検索キーワードを指定してください: jaea-search "検索キーワード"')
    args = list(argv)
    if args[0] in {"jaea-search", "/jaea-search", "jaea-rag", "/jaea-rag"}:
        args = args[1:]
    query = " ".join(args).strip()
    if not query:
        raise ValueError('検索キーワードを指定してください: jaea-search "検索キーワード"')
    return query


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _tokenize_jp(text: str) -> list[str]:
    """Tokenize Japanese text with janome (optional). Falls back to empty list."""
    try:
        from janome.tokenizer import Tokenizer as JanomeTokenizer

        tokenizer = JanomeTokenizer()
        tokens = []
        skip_pos = {"助詞", "助動詞", "記号", "補助記号", "接続詞", "感動詞", "空白", "接頭詞"}
        for token in tokenizer.tokenize(text):
            pos = token.part_of_speech.split(",")[0]
            if pos in skip_pos:
                continue
            base = token.base_form
            surface = token.surface
            word = base if (base and base != "*") else surface
            if len(word) < 2:
                continue
            tokens.append(word)

        # Drop fragments that are strict sub-strings of words already in the original text
        # (e.g. janome splits "ドローン" → "ド" + "ローン"; "ローン" ⊂ "ドローン" → discard)
        original_words = {w for w in re.split(r"[\s,、/／]+", text) if w}
        tokens = [t for t in tokens if not any(t in w and t != w for w in original_words)]
        return tokens
    except ImportError:
        return []


def _expand_with_llm(query: str) -> list[str]:
    """Ask Claude Haiku for related keywords. Returns [] on any error."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "以下の研究・技術検索クエリに関連する日本語・英語キーワードを5個以内で"
                        "カンマ区切りで出力してください。余分な説明は不要です。\n\n"
                        f"クエリ: {query}"
                    ),
                }
            ],
        )
        text = response.content[0].text.strip()
        return [t.strip() for t in re.split(r"[,、，]", text) if t.strip()][:5]
    except Exception:
        return []


def expand_query(query: str, use_llm: bool = False) -> list[str]:
    terms = [normalize_text(query)]
    lowered = query.lower()
    for key, expansions in QUERY_EXPANSIONS.items():
        if key.lower() in lowered or lowered in key.lower():
            terms.extend(expansions)
    for part in re.split(r"[\s,、/／]+", query):
        part = normalize_text(part)
        if len(part) >= 2:
            terms.append(part)
    terms.extend(_tokenize_jp(query))
    if use_llm:
        terms.extend(_expand_with_llm(query))
    return unique([term for term in terms if term])


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def split_terms(value: str) -> list[str]:
    return [term for term in value.split(" | ") if term]


def _get_chunk_schema(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(
        conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'rag_chunks'"
        ).fetchall()
    )


def _get_embedding_model(conn: duckdb.DuckDBPyConnection) -> str:
    row = conn.execute("SELECT DISTINCT embedding_model FROM rag_chunks LIMIT 1").fetchone()
    return (row[0] or "") if row else ""


def _has_vss(conn: duckdb.DuckDBPyConnection) -> bool:
    try:
        conn.execute("LOAD vss")
        return True
    except Exception:
        return False


def search_database(db_path: Path, query: str, limit: int = DEFAULT_LIMIT, use_llm: bool = False) -> list[SearchResult]:
    terms = expand_query(query, use_llm=use_llm)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        document_rows = conn.execute(
            """
            SELECT
                doc_type,
                doc_id,
                doc_no,
                title,
                abstract,
                categories,
                keywords,
                score,
                evidence,
                publication_date,
                detail_url,
                pdf_links,
                source_table,
                search_text
            FROM rag_documents
            """,
        ).fetchall()
        columns = [column[0] for column in conn.description]
        documents = {}
        for raw_row in document_rows:
            row = dict(zip(columns, raw_row))
            documents[(str(row["doc_type"]), str(row["doc_id"]))] = row

        chunk_scores = rank_chunks(conn, query, terms, limit=max(limit * 12, 48))
        results_by_doc: dict[tuple[str, str], dict[str, object]] = {}
        for chunk in chunk_scores:
            key = (str(chunk["doc_type"]), str(chunk["doc_id"]))
            row = documents.get(key)
            if not row:
                continue
            entry = results_by_doc.setdefault(key, {"row": row.copy(), "chunks": [], "score": 0})
            entry["chunks"].append(chunk)
            entry["score"] = max(int(entry["score"]), int(chunk["chunk_rank_score"]))

        for keyword_result in search_documents_by_keywords(documents.values(), query, terms, limit=max(limit * 2, 12)):
            key = (keyword_result.doc_type, keyword_result.doc_id)
            entry = results_by_doc.setdefault(key, {"row": documents[key].copy(), "chunks": [], "score": 0})
            entry["score"] = max(int(entry["score"]), keyword_result.rank_score)
            if not entry["chunks"]:
                entry["chunks"].append(
                    {
                        "chunk_id": f"{keyword_result.doc_type}:{keyword_result.doc_id}:document",
                        "chunk_source": "document",
                        "chunk_text": keyword_result.evidence or keyword_result.abstract or keyword_result.title,
                        "similarity": 0.0,
                        "matched_terms": " | ".join(keyword_result.matched_terms),
                        "chunk_rank_score": keyword_result.rank_score,
                    }
                )

        if not results_by_doc:
            return search_documents_by_keywords(documents.values(), query, terms, limit)

        results = []
        for entry in results_by_doc.values():
            row = entry["row"]
            chunks = sorted(entry["chunks"], key=lambda item: item["chunk_rank_score"], reverse=True)[:3]
            matched = unique([term for chunk in chunks for term in split_terms(str(chunk["matched_terms"]))])
            if is_ar_false_positive(query, " | ".join(matched)):
                continue
            row["rank_score"] = int(entry["score"]) + min(len(chunks), 3) * 5
            row["matched_terms"] = " | ".join(matched)
            result = SearchResult.from_row(row)
            result.evidence_chunks = [
                {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_source": chunk["chunk_source"],
                    "similarity": round(float(chunk["similarity"]), 4),
                    "text": chunk["chunk_text"],
                }
                for chunk in chunks
            ]
            results.append(result)
        results.sort(key=result_sort_key, reverse=True)
        return balanced_limit(results, limit)
    finally:
        conn.close()


def rank_chunks(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    terms: list[str],
    limit: int,
) -> list[dict[str, object]]:
    schema = _get_chunk_schema(conn)
    embedding_type = schema.get("embedding", "BLOB")
    use_float_array = embedding_type.startswith("FLOAT[")

    # Determine query embedding: use matching model if FLOAT[] schema
    if use_float_array:
        model_label = _get_embedding_model(conn)
        model_name = model_label.split(":")[0] if ":" in model_label else model_label
        embedder = get_embedder(model_name)
        if embedder is not None:
            query_embedding = embedder.embed(" ".join(terms))
        else:
            from jaea.scripts.rag_embeddings import EMBEDDING_DIM
            query_embedding = embed_text(" ".join(terms), dim=EMBEDDING_DIM)
    else:
        query_embedding = embed_text(" ".join(terms))

    # Use SQL-side similarity when FLOAT[] (faster; HNSW index used if present)
    if use_float_array and _has_vss(conn):
        dim = int(embedding_type.split("[")[1].rstrip("]"))
        raw_rows = conn.execute(
            f"""
            SELECT
                chunk_id, doc_type, doc_id, doc_no, title,
                chunk_index, chunk_source, chunk_text,
                embedding, embedding_dim, detail_url, pdf_links, source_table,
                array_cosine_similarity(embedding, ?::FLOAT[{dim}]) AS vss_sim
            FROM rag_chunks
            ORDER BY vss_sim DESC
            LIMIT ?
            """,
            [query_embedding, max(limit * 6, 200)],
        ).fetchall()
        columns = [c[0] for c in conn.description]
        rows_with_sim = []
        for raw in raw_rows:
            row = dict(zip(columns, raw))
            row["_precomputed_sim"] = float(row.pop("vss_sim") or 0.0)
            rows_with_sim.append(row)
    else:
        raw_rows = conn.execute(
            """
            SELECT
                chunk_id, doc_type, doc_id, doc_no, title,
                chunk_index, chunk_source, chunk_text,
                embedding, embedding_dim, detail_url, pdf_links, source_table
            FROM rag_chunks
            """,
        ).fetchall()
        columns = [c[0] for c in conn.description]
        rows_with_sim = [dict(zip(columns, r)) for r in raw_rows]
        for row in rows_with_sim:
            row["_precomputed_sim"] = cosine_similarity(query_embedding, to_vector(row["embedding"] or b""))

    ranked = []
    for row in rows_with_sim:
        chunk_text_value = str(row.get("chunk_text", ""))
        matched = matched_terms(chunk_text_value, terms)
        if is_ar_false_positive(query, matched):
            continue
        similarity = row["_precomputed_sim"]
        keyword_score = 12 * len(split_terms(matched))
        source_boost = {"title": 35, "metadata": 24, "pdf_text": 12}.get(str(row.get("chunk_source", "")), 0)
        curated_boost = 8 if row.get("source_table") in {"patents_ai_curated", "reports_cv_ar_high_confidence"} else 0
        chunk_rank_score = round(similarity * 100) + keyword_score + source_boost + curated_boost
        if matched or (allow_semantic_only(query) and similarity >= 0.28):
            row["matched_terms"] = matched
            row["similarity"] = similarity
            row["chunk_rank_score"] = chunk_rank_score
            ranked.append(row)
    ranked.sort(key=lambda r: (r["chunk_rank_score"], r["similarity"], r["title"]), reverse=True)
    return ranked[:limit]


def allow_semantic_only(query: str) -> bool:
    normalized = normalize_text(query)
    parts = [part for part in re.split(r"[\s,、/／]+", normalized) if part]
    return len(normalized) >= 5 or len(parts) >= 2


def search_documents_by_keywords(
    rows: Iterable[dict[str, object]],
    query: str,
    terms: list[str],
    limit: int,
) -> list[SearchResult]:
    results = []
    for row in rows:
        matched = matched_terms(str(row.get("search_text", "")), terms)
        if not matched:
            continue
        if is_ar_false_positive(query, matched):
            continue
        row = row.copy()
        row["rank_score"] = rank_row(row, query, terms)
        row["matched_terms"] = matched
        results.append(SearchResult.from_row(row))
    results.sort(key=result_sort_key, reverse=True)
    return balanced_limit(results, limit)


def result_sort_key(result: SearchResult) -> tuple[int, int, str, str]:
    return (result.rank_score, result.score, result.publication_date, result.title)


def balanced_limit(results: list[SearchResult], limit: int) -> list[SearchResult]:
    if len(results) <= limit:
        return results
    selected = results[:limit]
    types_in_all = {result.doc_type for result in results}
    types_in_selected = {result.doc_type for result in selected}
    missing_types = types_in_all - types_in_selected
    if not missing_types:
        return selected
    for missing_type in sorted(missing_types):
        replacement = next((result for result in results[limit:] if result.doc_type == missing_type), None)
        if replacement is not None and selected:
            selected[-1] = replacement
            selected.sort(key=result_sort_key, reverse=True)
    return selected


def rank_row(row: dict[str, object], query: str, terms: list[str]) -> int:
    source_table = str(row.get("source_table", ""))
    query_term = normalize_text(query)
    query_parts = [part for part in re.split(r"[\s,、/／]+", query_term) if len(part) >= 2]
    search_text = str(row.get("search_text", ""))
    return (
        int(row.get("score") or 0)
        + (70 if query_parts and all(term_matches(search_text, part) for part in query_parts) else 0)
        + (80 if query_term and term_matches(str(row.get("title", "")), query_term) else 0)
        + (40 if query_term and term_matches(str(row.get("evidence", "")), query_term) else 0)
        + (8 * len(split_terms(matched_terms(search_text, terms))))
        + (30 if contains_any(str(row.get("title", "")), terms) else 0)
        + (18 if contains_any(str(row.get("categories", "")), terms) else 0)
        + (16 if contains_any(str(row.get("keywords", "")), terms) else 0)
        + (12 if contains_any(str(row.get("evidence", "")), terms) else 0)
        + (6 if contains_any(str(row.get("abstract", "")), terms) else 0)
        + (6 if source_table in {"patents_ai_curated", "reports_cv_ar_high_confidence"} else 0)
    )


def contains_any(text: str | None, terms: list[str]) -> bool:
    if not text:
        return False
    return any(term_matches(text, term) for term in terms)


def matched_terms(text: str | None, terms: list[str]) -> str:
    if not text:
        return ""
    return " | ".join(term for term in terms if term_matches(text, term))


def term_matches(text: str, term: str) -> bool:
    if term == "AR":
        return re.search(r"(?<![A-Za-z0-9_])AR(?![A-Za-z0-9_])", text) is not None
    haystack = text.lower()
    needle = term.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,3}", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
    return needle in haystack


def is_ar_false_positive(query: str, matched: str) -> bool:
    if query.strip().upper() != "AR":
        return False
    matched_values = set(split_terms(matched))
    augmented_context = {"拡張現実", "augmented reality", "重畳表示", "仮想空間", "現実空間"}
    return "AR" in matched_values and not matched_values.intersection(augmented_context)


def ensure_database(db_path: Path) -> None:
    rebuild = True
    if db_path.exists():
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            conn.execute("SELECT 1 FROM rag_chunks LIMIT 1")
            schema = dict(
                conn.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'rag_chunks'
                    """
                ).fetchall()
            )
            embedding_type = schema.get("embedding", "")
            has_valid_embedding = embedding_type == "BLOB" or embedding_type.startswith("FLOAT[")
            if has_valid_embedding and schema.get("embedding_dim") == "INTEGER":
                rebuild = False
        except duckdb.CatalogException:
            pass
        finally:
            conn.close()
    if not rebuild:
        return
    from jaea.scripts.build_duckdb import build_database

    build_database(db_path)


def format_markdown(query: str, results: list[SearchResult]) -> str:
    patents = [result for result in results if result.doc_type == "patent"]
    reports = [result for result in results if result.doc_type == "report"]
    lines = [
        f"# JAEA検索: {query}",
        "",
        f"- 関連候補: {len(results)}件",
        f"- 特許: {len(patents)}件",
        f"- 報告書: {len(reports)}件",
        "",
    ]
    lines.extend(format_section("関連する特許", patents))
    lines.extend(format_section("関連する報告書", reports))
    lines.extend(
        [
            "## 技術的な接点",
            "",
            summarize_connections(results),
            "",
            "## 追加で見るべきキーワード",
            "",
            "- " + "\n- ".join(suggest_keywords(results)) if results else "- 該当候補がないため、検索語を広げてください。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def format_section(title: str, results: list[SearchResult]) -> list[str]:
    lines = [f"## {title}", ""]
    if not results:
        lines.extend(["該当候補はありません。", ""])
        return lines
    for idx, result in enumerate(results, start=1):
        lines.extend(
            [
                f"### {idx}. {result.title}",
                "",
                f"- ID: {result.doc_id}",
                f"- 番号: {result.doc_no or '-'}",
                f"- 関連度: {result.rank_score}",
                f"- 分類: {result.categories or '-'}",
                f"- 根拠: {result.evidence or ', '.join(result.matched_terms) or '-'}",
                f"- 根拠chunk: {format_evidence_chunks(result.evidence_chunks)}",
                f"- 発行/公開日: {result.publication_date or '-'}",
                f"- 詳細: {result.detail_url or '-'}",
                f"- PDF: {result.pdf_links or '-'}",
                "",
            ]
        )
    return lines


def format_evidence_chunks(chunks: list[dict[str, object]]) -> str:
    if not chunks:
        return "-"
    snippets = []
    for chunk in chunks[:2]:
        text = normalize_text(str(chunk.get("text", "")))
        if len(text) > 180:
            text = text[:177] + "..."
        snippets.append(f"{chunk.get('chunk_source')}:{text}")
    return " / ".join(snippets)


def summarize_connections(results: list[SearchResult]) -> str:
    if not results:
        return "該当候補がありません。"
    terms = suggest_keywords(results)[:6]
    return "、".join(terms) + " の観点で既存資料との接点があります。"


def suggest_keywords(results: list[SearchResult]) -> list[str]:
    values: list[str] = []
    for result in results:
        values.extend(split_comma_text(result.categories))
        values.extend(split_comma_text(result.keywords))
        values.extend(result.matched_terms)
    cleaned = [normalize_text(value) for value in values if normalize_text(value)]
    return unique(cleaned)[:10] or ["3D", "画像処理", "マッピング", "ロボット"]


def split_comma_text(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,、;；]", value) if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description='Search JAEA patent and report data. Standard form: jaea-search "検索キーワード"')
    parser.add_argument("query", nargs="*", help='Use either "検索キーワード" or jaea-search "検索キーワード".')
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--expand-with-llm", action="store_true", help="Use Claude Haiku to expand query keywords")
    args = parser.parse_args()

    try:
        query = parse_invocation(args.query)
        ensure_database(args.db)
        results = search_database(args.db, query, args.limit, use_llm=args.expand_with_llm)
    except Exception as exc:  # noqa: BLE001
        parser.exit(2, f"{exc}\n")

    if args.format == "json":
        print(json.dumps({"query": query, "results": [result.to_dict() for result in results]}, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(query, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
