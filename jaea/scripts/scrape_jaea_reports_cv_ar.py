#!/usr/bin/env python3

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException


BASE_URL = "https://jopss.jaea.go.jp/search/servlet/"
SEARCH_URL = urljoin(BASE_URL, "search")
SEARCH_PARAMS = {"ke_type": "報告書", "cnt": "100"}
OUT_DIR = Path(__file__).resolve().parents[1] / "output"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Codex scraper for JAEA report survey)"
}
THREAD_LOCAL = threading.local()

KEYWORDS = {
    "3d_modeling": [
        "3d",
        "3-d",
        "三次元",
        "3次元",
        "三次元モデル",
        "3d model",
        "3d imaging",
        "三次元画像",
        "三次元復元",
        "点群",
        "point cloud",
        "photogrammetry",
        "sfm",
        "stereo vision",
        "ステレオ視",
    ],
    "computer_vision": [
        "computer vision",
        "画像処理",
        "画像解析",
        "画像認識",
        "画像計測",
        "画像診断",
        "物体認識",
        "物体検出",
        "可視化",
        "visualization",
        "image processing",
        "image analysis",
        "image recognition",
        "imaging",
        "camera",
        "カメラ",
        "可視光",
        "赤外線",
        "サーモグラフィ",
    ],
    "ar_mapping": [
        "ar",
        "拡張現実",
        "augmented reality",
        "mixed reality",
        "複合現実",
        "仮想空間",
        "現実空間",
        "重畳表示",
        "空間マッピング",
        "マッピング",
        "地図生成",
        "地図作成",
        "slam",
        "自己位置推定",
        "位置姿勢",
        "pose estimation",
        "localization",
        "mapping",
    ],
    "robotics_remote": [
        "ロボット",
        "robot",
        "rov",
        "ドローン",
        "uav",
        "遠隔操作",
        "遠隔技術",
        "remote",
        "レーザスキャナ",
        "laser scanner",
        "lidar",
        "超音波",
        "イメージング",
    ],
}

EXCLUDE_HINTS = [
    "医用画像",
    "断層撮影のみ",
    "電子顕微鏡観察",
    "顕微鏡観察",
    "x線回折",
    "画像形成",
    "熱流動解析コード",
    "臨界ベンチマーク",
    "シミュレーション・プラットフォーム",
    "ユーザーマニュアル",
]

STRONG_3D_CONTEXT = [
    "三次元モデル",
    "3d model",
    "3d imaging",
    "3dイメージング",
    "三次元画像",
    "三次元復元",
    "点群",
    "point cloud",
    "photogrammetry",
    "sfm",
    "stereo vision",
    "ステレオ視",
]


@dataclass
class ReportRecord:
    report_id: str
    detail_url: str
    title_ja: str = ""
    title_en: str = ""
    authors_ja: list[str] = field(default_factory=list)
    authors_en: list[str] = field(default_factory=list)
    abstract_ja: str = ""
    abstract_en: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    pdf_links: list[str] = field(default_factory=list)
    score: int = 0
    categories: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    evidence_text: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "report_id": self.report_id,
            "report_no": self.meta.get("報告書番号", ""),
            "title_ja": self.title_ja,
            "title_en": self.title_en,
            "authors_ja": "; ".join(self.authors_ja),
            "authors_en": "; ".join(self.authors_en),
            "abstract_ja": self.abstract_ja,
            "abstract_en": self.abstract_en,
            "language": self.meta.get("発表言語", ""),
            "pages": self.meta.get("ページ数", ""),
            "publication_date": self.meta.get("発行年月", ""),
            "keywords": self.meta.get("キーワード", ""),
            "facilities": self.meta.get("使用施設", ""),
            "doi_url": self.meta.get("論文URL", ""),
            "categories": ", ".join(self.categories),
            "score": str(self.score),
            "matched_keywords": ", ".join(self.matched_keywords),
            "evidence_text": self.evidence_text,
            "detail_url": self.detail_url,
            "pdf_links": " | ".join(self.pdf_links),
        }


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch(session: requests.Session, url: str, params: dict[str, str] | None = None) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(url, params=params, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.text
        except RequestException as exc:
            last_error = exc
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"fetch failed for {url} params={params}: {last_error}")


def get_thread_session() -> requests.Session:
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        THREAD_LOCAL.session = session
    return session


def fetch_and_parse_detail(detail_url: str) -> ReportRecord:
    session = get_thread_session()
    html = fetch(session, detail_url)
    return parse_detail(html, detail_url)


def extract_total_and_pages(html: str, cnt: int) -> tuple[int, int]:
    match = re.search(r"検索結果：\s*([0-9,]+)\s*&nbsp;件中", html)
    if not match:
        raise RuntimeError("検索結果件数を取得できませんでした")
    total = int(match.group(1).replace(",", ""))
    pages = math.ceil(total / cnt)
    return total, pages


def extract_result_links(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    for h2 in soup.find_all("h2"):
        anchor = h2.find("a", href=True)
        if not anchor:
            continue
        href = anchor["href"]
        if not re.fullmatch(r"search\?\d+", href):
            continue
        items.append((anchor.get_text(" ", strip=True), urljoin(BASE_URL, href)))
    return items


def split_people(text: str) -> list[str]:
    return [normalize_space(part) for part in re.split(r"\s*;\s*", text) if normalize_space(part)]


def parse_meta(soup: BeautifulSoup) -> dict[str, str]:
    meta: dict[str, str] = {}
    for row in soup.select("table tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 3:
            continue
        key = normalize_space(cells[0].get_text(" ", strip=True))
        value = normalize_space(cells[-1].get_text(" ", strip=True))
        if key:
            meta[key] = value
    return meta


def extract_report_id(detail_url: str) -> str:
    query = urlparse(detail_url).query
    match = re.fullmatch(r"(\d+)", query)
    return match.group(1) if match else query


def parse_detail(html: str, detail_url: str) -> ReportRecord:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title_ja = normalize_space(h1.get_text(" ", strip=True)) if h1 else ""
    title_en = ""
    authors_ja: list[str] = []
    authors_en: list[str] = []
    abstract_ja = ""
    abstract_en = ""

    if h1:
        siblings = []
        for sib in h1.find_next_siblings():
            if sib.name == "table":
                break
            text = normalize_space(sib.get_text(" ", strip=True))
            if text:
                siblings.append((sib.name, text))
        if siblings and siblings[0][0] == "h2":
            title_en = siblings[0][1]
            siblings = siblings[1:]
        paragraph_texts = [text for name, text in siblings if name == "p"]
        if paragraph_texts:
            authors_ja = split_people(paragraph_texts[0])
        if len(paragraph_texts) > 1:
            authors_en = split_people(paragraph_texts[1])
        if len(paragraph_texts) > 2:
            abstract_ja = paragraph_texts[2]
        if len(paragraph_texts) > 3:
            abstract_en = paragraph_texts[3]

    meta = parse_meta(soup)
    pdf_links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().endswith(".pdf"):
            pdf_links.append(urljoin(BASE_URL, href))
    pdf_links = list(dict.fromkeys(pdf_links))

    score, categories, matched, evidence = score_record(
        title_ja=title_ja,
        title_en=title_en,
        abstract_ja=abstract_ja,
        abstract_en=abstract_en,
        meta=meta,
    )
    return ReportRecord(
        report_id=extract_report_id(detail_url),
        detail_url=detail_url,
        title_ja=title_ja,
        title_en=title_en,
        authors_ja=authors_ja,
        authors_en=authors_en,
        abstract_ja=abstract_ja,
        abstract_en=abstract_en,
        meta=meta,
        pdf_links=pdf_links,
        score=score,
        categories=categories,
        matched_keywords=matched,
        evidence_text=evidence,
    )


def score_record(
    title_ja: str,
    title_en: str,
    abstract_ja: str,
    abstract_en: str,
    meta: dict[str, str],
) -> tuple[int, list[str], list[str], str]:
    fields = [
        title_ja,
        title_en,
        abstract_ja,
        abstract_en,
        meta.get("キーワード", ""),
        meta.get("報告書番号", ""),
    ]
    text = " ".join(fields)
    lower_text = text.lower()
    score = 0
    categories: list[str] = []
    matched: list[str] = []

    for category, keywords in KEYWORDS.items():
        category_hits = []
        for keyword in keywords:
            if keyword_matches(lower_text, keyword):
                category_hits.append(keyword)
        if category_hits:
            categories.append(category)
            matched.extend(category_hits)
            score += {
                "3d_modeling": 3,
                "computer_vision": 4,
                "ar_mapping": 5,
                "robotics_remote": 2,
            }[category]
            score += min(len(category_hits), 4)

    for hint in EXCLUDE_HINTS:
        if hint.lower() in lower_text:
            score -= 4

    if categories == ["3d_modeling"] and not any(keyword_matches(lower_text, keyword) for keyword in STRONG_3D_CONTEXT):
        score = min(score, 5)
    if categories == ["robotics_remote"]:
        score = min(score, 5)

    matched = sorted(set(matched), key=str.lower)
    categories = sorted(set(categories))
    evidence = build_evidence(fields, matched)
    return score, categories, matched, evidence


def keyword_matches(lower_text: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,3}", lowered):
        return re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", lower_text) is not None
    return lowered in lower_text


def build_evidence(fields: list[str], matched: list[str]) -> str:
    if not matched:
        return ""
    for field in fields:
        lower = field.lower()
        for keyword in matched:
            idx = lower.find(keyword.lower())
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(field), idx + len(keyword) + 120)
                return normalize_space(field[start:end])
    return ""


def write_csv(path: Path, records: Iterable[ReportRecord]) -> None:
    fieldnames = [
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
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_row())


def write_markdown(path: Path, total: int, scraped: int, candidates: list[ReportRecord]) -> None:
    lines = [
        "# JAEA報告書のComputer vision / AR mapping候補",
        "",
        f"- 取得日: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 対象URL: {SEARCH_URL}?ke_type=報告書",
        f"- 検索結果件数: {total}",
        f"- 詳細取得件数: {scraped}",
        f"- 候補件数: {len(candidates)}",
        "",
        "| スコア | 区分 | 報告書番号 | タイトル | 根拠 | 発行年月 | PDFリンク | 詳細 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in candidates:
        pdfs = "<br>".join(record.pdf_links) if record.pdf_links else "-"
        categories = "<br>".join(record.categories) if record.categories else "-"
        evidence = record.evidence_text or ", ".join(record.matched_keywords[:6])
        lines.append(
            f"| {record.score} | {categories} | {record.meta.get('報告書番号','-')} | "
            f"{record.title_ja} | {evidence} | {record.meta.get('発行年月','-')} | "
            f"{pdfs} | {record.detail_url} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_done_ids(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            report_id = row.get("report_id")
            if report_id:
                done.add(report_id)
    return done


def collect_detail_urls(
    session: requests.Session,
    first_html: str,
    pages: int,
    page_limit: int | None,
) -> list[str]:
    detail_urls: list[str] = []
    seen: set[str] = set()
    stop_page = min(pages, page_limit) if page_limit else pages
    for page in range(1, stop_page + 1):
        params = dict(SEARCH_PARAMS)
        params["ShowPage"] = str(page)
        html = first_html if page == 1 else fetch(session, SEARCH_URL, params=params)
        for _, detail_url in extract_result_links(html):
            if detail_url not in seen:
                seen.add(detail_url)
                detail_urls.append(detail_url)
        print(f"[page {page}/{stop_page}] detail_urls={len(detail_urls)}", file=sys.stderr)
        time.sleep(0.05)
    return detail_urls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="detail pages to scrape after URL collection")
    parser.add_argument("--page-limit", type=int, default=None, help="search result pages to collect")
    parser.add_argument("--candidate-threshold", type=int, default=6)
    parser.add_argument("--progress-interval", type=int, default=25)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    all_jsonl = OUT_DIR / "jaea_reports_all.jsonl"
    errors_jsonl = OUT_DIR / "jaea_reports_cv_ar_errors.jsonl"

    session = requests.Session()
    first_html = fetch(session, SEARCH_URL, params=SEARCH_PARAMS)
    cnt = int(SEARCH_PARAMS["cnt"])
    total, pages = extract_total_and_pages(first_html, cnt=cnt)
    page_limit = args.page_limit
    if args.limit and page_limit is None:
        page_limit = math.ceil(args.limit / cnt)
    detail_urls = collect_detail_urls(session, first_html, pages, page_limit)
    if args.limit:
        detail_urls = detail_urls[: args.limit]

    done_ids = load_done_ids(all_jsonl) if args.resume else set()
    candidates: list[ReportRecord] = []
    scraped = 0
    skipped = 0
    failures = 0

    mode = "a" if args.resume else "w"
    pending_urls: list[str] = []
    for detail_url in detail_urls:
        report_id = extract_report_id(detail_url)
        if report_id in done_ids:
            skipped += 1
        else:
            pending_urls.append(detail_url)

    with all_jsonl.open(mode, encoding="utf-8") as all_fh, errors_jsonl.open(mode, encoding="utf-8") as err_fh:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_url = {executor.submit(fetch_and_parse_detail, detail_url): detail_url for detail_url in pending_urls}
            for completed, future in enumerate(as_completed(future_to_url), start=1):
                detail_url = future_to_url[future]
                try:
                    record = future.result()
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    err_fh.write(json.dumps({"detail_url": detail_url, "error": str(exc)}, ensure_ascii=False) + "\n")
                    err_fh.flush()
                    print(f"[error] {detail_url}: {exc}", file=sys.stderr)
                    continue

                all_fh.write(json.dumps(record.to_row(), ensure_ascii=False) + "\n")
                all_fh.flush()
                scraped += 1
                if record.score >= args.candidate_threshold:
                    candidates.append(record)
                    print(
                        f"[candidate {len(candidates)}] [{completed}/{len(pending_urls)}] "
                        f"score={record.score} {record.report_id} {record.title_ja}",
                        file=sys.stderr,
                    )
                elif args.progress_interval and completed % args.progress_interval == 0:
                    print(
                        f"[{completed}/{len(pending_urls)}] scraped={scraped} "
                        f"skipped={skipped} candidates={len(candidates)}",
                        file=sys.stderr,
                    )

    candidates.sort(key=lambda r: (r.score, r.meta.get("発行年月", ""), r.title_ja), reverse=True)
    write_csv(OUT_DIR / "jaea_reports_cv_ar_candidates.csv", candidates)
    write_markdown(OUT_DIR / "jaea_reports_cv_ar_candidates.md", total, scraped + skipped, candidates)

    summary = {
        "total_results_reported": total,
        "search_pages_reported": pages,
        "detail_urls_collected": len(detail_urls),
        "detail_pages_scraped": scraped,
        "detail_pages_skipped_by_resume": skipped,
        "cv_ar_candidates": len(candidates),
        "candidate_threshold": args.candidate_threshold,
        "failures": failures,
    }
    (OUT_DIR / "jaea_reports_cv_ar_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
