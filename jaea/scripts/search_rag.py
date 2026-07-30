#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
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


def expand_query(query: str) -> list[str]:
    terms = [normalize_text(query)]
    lowered = query.lower()
    for key, expansions in QUERY_EXPANSIONS.items():
        if key.lower() in lowered or lowered in key.lower():
            terms.extend(expansions)
    for part in re.split(r"[\s,、/／]+", query):
        part = normalize_text(part)
        if len(part) >= 2:
            terms.append(part)
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


def search_database(db_path: Path, query: str, limit: int = DEFAULT_LIMIT) -> list[SearchResult]:
    terms = expand_query(query)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = conn.execute(
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
        results = []
        for raw_row in rows:
            row = dict(zip(columns, raw_row))
            matched = matched_terms(str(row.get("search_text", "")), terms)
            if not matched:
                continue
            if is_ar_false_positive(query, matched):
                continue
            row["rank_score"] = rank_row(row, query, terms)
            row["matched_terms"] = matched
            results.append(SearchResult.from_row(row))
        results.sort(key=lambda result: (result.rank_score, result.score, result.publication_date, result.title), reverse=True)
        return results[:limit]
    finally:
        conn.close()


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
    if db_path.exists():
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
                f"- 発行/公開日: {result.publication_date or '-'}",
                f"- 詳細: {result.detail_url or '-'}",
                f"- PDF: {result.pdf_links or '-'}",
                "",
            ]
        )
    return lines


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
    args = parser.parse_args()

    try:
        query = parse_invocation(args.query)
        ensure_database(args.db)
        results = search_database(args.db, query, args.limit)
    except Exception as exc:  # noqa: BLE001
        parser.exit(2, f"{exc}\n")

    if args.format == "json":
        print(json.dumps({"query": query, "results": [result.to_dict() for result in results]}, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(query, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
