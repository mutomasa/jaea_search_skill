from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from jaea.scripts.build_duckdb import build_database  # noqa: E402
from jaea.scripts.search_rag import ensure_database, parse_invocation, search_database, term_matches  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_output_dir(tmp_path: Path) -> Path:
    output = tmp_path / "output"
    output.mkdir()

    patent_all_fields = [
        "patent_id",
        "title",
        "authors",
        "abstract",
        "detail_url",
        "application_no",
        "publication_no",
        "registration_no",
        "application_date",
        "publication_date",
        "registration_date",
        "ipc",
        "pdf_links",
        "score",
        "matched_keywords",
    ]
    patents = [
        {
            "patent_id": "P53320",
            "title": "情報処理方法、情報処理装置、及び、情報処理システム",
            "authors": "Author",
            "abstract": "複数静止画から三次元モデルを生成し、現実空間と仮想空間の重畳表示を行う。",
            "detail_url": "https://example.test/patent",
            "application_no": "",
            "publication_no": "2023-000001",
            "registration_no": "",
            "application_date": "2022/03/02",
            "publication_date": "2023/09/14",
            "registration_date": "",
            "ipc": "",
            "pdf_links": "https://example.test/patent.pdf",
            "score": "8",
            "matched_keywords": "三次元, 画像",
        }
    ]
    write_csv(output / "jaea_patents_all.csv", patents, patent_all_fields)
    write_csv(output / "jaea_patents_ai_candidates.csv", patents, patent_all_fields)
    write_csv(
        output / "jaea_patents_ai_curated.csv",
        [
            {
                "bucket": "peripheral_algorithms",
                "category": "Computer vision / AR mapping",
                "patent_id": "P53320",
                "title": patents[0]["title"],
                "reason": "複数静止画から三次元モデルを生成し、現実空間と仮想空間の重畳表示を行う。",
                "application_date": "2022/03/02",
                "publication_date": "2023/09/14",
                "detail_url": "https://example.test/patent",
                "pdf_links": "https://example.test/patent.pdf",
            }
        ],
        ["bucket", "category", "patent_id", "title", "reason", "application_date", "publication_date", "detail_url", "pdf_links"],
    )

    report_fields = [
        "report_id",
        "report_no",
        "title_ja",
        "title_en",
        "authors_ja",
        "authors_en",
        "abstract_ja",
        "abstract_en",
        "language",
        "pages",
        "publication_date",
        "keywords",
        "facilities",
        "doi_url",
        "categories",
        "score",
        "matched_keywords",
        "evidence_text",
        "detail_url",
        "pdf_links",
    ]
    reports = [
        {
            "report_id": "5081069",
            "report_no": "JAEA-Review 2025-033",
            "title_ja": "動画像からの特徴量抽出結果に基づいた高速3次元炉内環境モデリング",
            "title_en": "Fast 3D in-vessel environment modeling",
            "authors_ja": "Author",
            "authors_en": "",
            "abstract_ja": "カメラ画像と動画像処理を用いて炉内環境を三次元化する。",
            "abstract_en": "",
            "language": "Japanese",
            "pages": "10",
            "publication_date": "2025/11",
            "keywords": "3D Modeling ; Camera Image Analysis",
            "facilities": "",
            "doi_url": "",
            "categories": "3d_modeling, computer_vision",
            "score": "12",
            "matched_keywords": "3D, カメラ画像",
            "evidence_text": "動画像からの特徴量抽出結果に基づいた高速3次元炉内環境モデリング",
            "detail_url": "https://example.test/report",
            "pdf_links": "https://example.test/report.pdf",
        }
    ]
    write_jsonl(output / "jaea_reports_all.jsonl", reports)
    write_csv(output / "jaea_reports_cv_ar_candidates.csv", reports, report_fields)
    write_csv(output / "jaea_reports_cv_ar_high_confidence.csv", reports, report_fields)
    return output


def test_parse_invocation_accepts_standard_skill_form() -> None:
    assert parse_invocation(["jaea-search", "3Dモデル生成"]) == "3Dモデル生成"
    assert parse_invocation(["/jaea-search", "カメラ画像"]) == "カメラ画像"
    assert parse_invocation(["jaea-rag", "3Dモデル生成"]) == "3Dモデル生成"
    assert parse_invocation(["線量", "マッピング"]) == "線量 マッピング"


def test_short_ar_term_does_not_match_argon_or_words() -> None:
    assert term_matches("AR mapping", "AR")
    assert not term_matches("argon gas and particle analysis", "AR")
    assert not term_matches("Ar ion and ar_mapping category", "AR")


def test_ensure_database_builds_when_missing(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "missing.duckdb"
    called = []

    def fake_build_database(path: Path) -> dict[str, int]:
        called.append(path)
        path.write_text("created", encoding="utf-8")
        return {"rag_documents": 0}

    monkeypatch.setattr("jaea.scripts.build_duckdb.build_database", fake_build_database)

    ensure_database(db_path)

    assert called == [db_path]
    assert db_path.exists()


def test_build_database_and_search(tmp_path: Path) -> None:
    output_dir = make_output_dir(tmp_path)
    db_path = tmp_path / "jaea.duckdb"

    summary = build_database(db_path, output_dir)

    assert summary["patents_all"] == 1
    assert summary["reports_all"] == 1
    assert summary["rag_documents"] == 2
    assert summary["rag_chunks"] > summary["rag_documents"]

    results = search_database(db_path, "3Dモデル生成", limit=5)

    assert len(results) == 2
    assert results[0].doc_type == "report"
    assert "3次元" in results[0].title
    assert results[0].evidence_chunks
    assert "chunk_source" in results[0].evidence_chunks[0]
    assert any(result.doc_type == "patent" and result.doc_id == "P53320" for result in results)

    ar_results = search_database(db_path, "AR", limit=5)
    assert [result.doc_id for result in ar_results] == ["P53320"]
