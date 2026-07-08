#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException


BASE_URL = "https://jopss.jaea.go.jp/search/servlet/"
SEARCH_URL = urljoin(BASE_URL, "search")
SEARCH_PARAMS = {"ke_type": "特許", "cnt": "100"}
OUT_DIR = Path("output")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Codex scraper for JAEA patent survey)"
}

AI_KEYWORDS = {
    "high": [
        "人工知能",
        "機械学習",
        "深層学習",
        "ディープラーニング",
        "ニューラルネットワーク",
        "画像認識",
        "画像解析",
        "物体認識",
        "物体検出",
        "姿勢推定",
        "行動認識",
        "パターン認識",
        "異常検知",
        "特徴量",
        "semantic segmentation",
        "neural network",
        "machine learning",
        "deep learning",
        "computer vision",
        "image recognition",
    ],
    "medium": [
        "認識",
        "推定",
        "分類",
        "学習",
        "識別",
        "最適化",
        "予測",
        "画像",
        "カメラ",
        "ロボット",
        "自律",
        "ドローン",
        "センサフュージョン",
        "モデル",
        "estimation",
        "classification",
        "prediction",
        "optimization",
        "autonomous",
        "robot",
    ],
}

EXCLUDE_HINTS = [
    "画像形成",
    "画像表示",
    "焼却炉",
    "抽出装置",
    "放射性廃棄物",
]

CURATED_SELECTION = {
    "P53940": {
        "bucket": "pure_ai_ml",
        "category": "Physical AI / neural control",
        "reason": "ニューラルネットワーク制御部を明示。海洋ロボットの位置保持を対象にした自律制御アルゴリズム。",
    },
    "P53400": {
        "bucket": "pure_ai_ml",
        "category": "Machine learning / decision tree",
        "reason": "標準試料から因子スコアを学習し、決定木で未知試料を分類・同定する。",
    },
    "P54481": {
        "bucket": "pure_ai_ml",
        "category": "Pattern recognition / feature-based classification",
        "reason": "検出パターン認識と特徴量抽出により、α線・β線・γ線を識別する。",
    },
    "P53320": {
        "bucket": "peripheral_algorithms",
        "category": "Computer vision / AR mapping",
        "reason": "複数静止画から三次元モデルを生成し、現実空間と仮想空間の重畳表示を行う。",
    },
    "P13787": {
        "bucket": "peripheral_algorithms",
        "category": "Image processing / visual mapping",
        "reason": "赤外線カメラと可視光カメラの画像処理で線量率マップを作成する。",
    },
    "P53229": {
        "bucket": "peripheral_algorithms",
        "category": "Inference / sparse estimation",
        "reason": "少数観測からスパースベクトル復元により線源分布を推定する。",
    },
    "P53264": {
        "bucket": "peripheral_algorithms",
        "category": "Optimization / observation planning",
        "reason": "逆推定が成功する最少観測点数を求め、観測点配置を最適化する。",
    },
    "P14040": {
        "bucket": "peripheral_algorithms",
        "category": "Inference / model-based estimation",
        "reason": "遮蔽解析結果と実測中性子束を比較してデブリ堆積量を推定する。",
    },
    "P13534": {
        "bucket": "peripheral_algorithms",
        "category": "Inverse analysis / probabilistic modeling",
        "reason": "ミュー粒子の散乱角をガウス分布で扱い、構造物内部状態を解析する。",
    },
}


@dataclass
class Record:
    patent_id: str
    detail_url: str
    title: str
    authors: list[str]
    abstract: str
    meta: dict[str, str]
    pdf_links: list[str]
    score: int
    matched_keywords: list[str]

    def to_row(self) -> dict[str, str]:
        return {
            "patent_id": self.patent_id,
            "title": self.title,
            "authors": "; ".join(self.authors),
            "abstract": self.abstract,
            "detail_url": self.detail_url,
            "application_no": self.meta.get("出願番号", ""),
            "publication_no": self.meta.get("公開番号", ""),
            "registration_no": self.meta.get("登録番号", ""),
            "application_date": self.meta.get("出願日", ""),
            "publication_date": self.meta.get("公開日", ""),
            "registration_date": self.meta.get("登録日", ""),
            "ipc": self.meta.get("IPC", ""),
            "pdf_links": " | ".join(self.pdf_links),
            "score": str(self.score),
            "matched_keywords": ", ".join(self.matched_keywords),
        }


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


def extract_total_and_pages(html: str, cnt: int) -> tuple[int, int]:
    match = re.search(r"検索結果：\s*([0-9]+)\s*&nbsp;件中", html)
    if not match:
        raise RuntimeError("検索結果件数を取得できませんでした")
    total = int(match.group(1))
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
        if not href.startswith("search?P"):
            continue
        items.append((anchor.get_text(" ", strip=True), urljoin(BASE_URL, href)))
    return items


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_detail(html: str, detail_url: str) -> Record:
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_space(soup.find("h1").get_text(" ", strip=True))

    author_block: list[str] = []
    h1 = soup.find("h1")
    if h1:
        for sib in h1.find_next_siblings():
            if sib.name == "table":
                break
            text = normalize_space(sib.get_text(" ", strip=True))
            if text:
                author_block.append(text)
    abstract = ""
    authors: list[str] = []
    if author_block:
        authors = [line for line in author_block[:-1] if len(line) < 80]
        abstract = author_block[-1]

    meta: dict[str, str] = {}
    for row in soup.select("table tr"):
        th = row.find("th")
        tds = row.find_all("td")
        if not th or len(tds) < 2:
            continue
        key = normalize_space(th.get_text(" ", strip=True))
        value = normalize_space(tds[-1].get_text(" ", strip=True))
        meta[key] = value

    pdf_links: list[str] = []
    for label in ("公開特許公報", "特許公報"):
        value = meta.get(label, "")
        if ".pdf" in value:
            for anchor in soup.find_all("a", href=True):
                if anchor["href"].lower().endswith(".pdf") and label in anchor.find_parent("tr").get_text(" ", strip=True):
                    pdf_links.append(urljoin(BASE_URL, anchor["href"]))
    pdf_links = list(dict.fromkeys(pdf_links))

    patent_id_match = re.search(r"search\?(P\d+)", detail_url)
    patent_id = patent_id_match.group(1) if patent_id_match else ""
    score, matched = score_record(title, abstract, meta)
    return Record(
        patent_id=patent_id,
        detail_url=detail_url,
        title=title,
        authors=authors,
        abstract=abstract,
        meta=meta,
        pdf_links=pdf_links,
        score=score,
        matched_keywords=matched,
    )


def score_record(title: str, abstract: str, meta: dict[str, str]) -> tuple[int, list[str]]:
    text = " ".join([title, abstract, meta.get("IPC", "")]).lower()
    score = 0
    matched: list[str] = []
    if re.search(r"\bai\b", text):
        score += 5
        matched.append("AI")
    for keyword in AI_KEYWORDS["high"]:
        if keyword.lower() in text:
            score += 5
            matched.append(keyword)
    for keyword in AI_KEYWORDS["medium"]:
        if keyword.lower() in text:
            score += 2
            matched.append(keyword)
    for hint in EXCLUDE_HINTS:
        if hint.lower() in text:
            score -= 2
    return score, sorted(set(matched))


def write_csv(path: Path, records: Iterable[Record]) -> None:
    records = list(records)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_row())


def write_markdown(path: Path, total: int, ai_records: list[Record]) -> None:
    lines = [
        "# JAEA特許のAI関連候補",
        "",
        f"- 取得日: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 対象URL: {SEARCH_URL}?ke_type=特許",
        f"- 取得件数: {total}",
        f"- AI関連候補: {len(ai_records)}",
        "",
        "| 特許ID | タイトル | AI関連の根拠 | 出願日 | 公開日 | PDFリンク | 詳細 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in ai_records:
        basis = ", ".join(record.matched_keywords[:6]) or "目視確認"
        pdfs = "<br>".join(record.pdf_links) if record.pdf_links else "-"
        lines.append(
            f"| {record.patent_id} | {record.title} | {basis} | {record.meta.get('出願日','-')} | "
            f"{record.meta.get('公開日','-')} | {pdfs} | {record.detail_url} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_curated_markdown(path: Path, curated_records: list[Record]) -> None:
    lines = [
        "# JAEA特許のAI関連ピックアップ",
        "",
        "## 純AI/ML",
        "",
        "| 区分 | 特許ID | タイトル | AIとの関係 | 出願日 | 公開日 | PDFリンク | 詳細 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    pure_records = [r for r in curated_records if CURATED_SELECTION[r.patent_id]["bucket"] == "pure_ai_ml"]
    peripheral_records = [r for r in curated_records if CURATED_SELECTION[r.patent_id]["bucket"] == "peripheral_algorithms"]

    for record in pure_records:
        meta = CURATED_SELECTION[record.patent_id]
        pdfs = "<br>".join(record.pdf_links) if record.pdf_links else "-"
        lines.append(
            f"| {meta['category']} | {record.patent_id} | {record.title} | {meta['reason']} | "
            f"{record.meta.get('出願日','-')} | {record.meta.get('公開日','-')} | {pdfs} | {record.detail_url} |"
        )
    lines.extend(
        [
            "",
            "## AI周辺アルゴリズム",
            "",
            "| 区分 | 特許ID | タイトル | AIとの関係 | 出願日 | 公開日 | PDFリンク | 詳細 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for record in peripheral_records:
        meta = CURATED_SELECTION[record.patent_id]
        pdfs = "<br>".join(record.pdf_links) if record.pdf_links else "-"
        lines.append(
            f"| {meta['category']} | {record.patent_id} | {record.title} | {meta['reason']} | "
            f"{record.meta.get('出願日','-')} | {record.meta.get('公開日','-')} | {pdfs} | {record.detail_url} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_curated_csv(path: Path, curated_records: list[Record]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "category",
                "patent_id",
                "title",
                "reason",
                "application_date",
                "publication_date",
                "detail_url",
                "pdf_links",
            ],
        )
        writer.writeheader()
        for record in curated_records:
            meta = CURATED_SELECTION[record.patent_id]
            writer.writerow(
                {
                    "category": meta["category"],
                    "patent_id": record.patent_id,
                    "title": record.title,
                    "reason": meta["reason"],
                    "application_date": record.meta.get("出願日", ""),
                    "publication_date": record.meta.get("公開日", ""),
                    "detail_url": record.detail_url,
                    "pdf_links": " | ".join(record.pdf_links),
                }
            )


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    session = requests.Session()

    first_html = fetch(session, SEARCH_URL, params=SEARCH_PARAMS)
    total, pages = extract_total_and_pages(first_html, cnt=int(SEARCH_PARAMS["cnt"]))

    detail_urls: list[str] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        params = dict(SEARCH_PARAMS)
        params["ShowPage"] = str(page)
        html = first_html if page == 1 else fetch(session, SEARCH_URL, params=params)
        for _, detail_url in extract_result_links(html):
            if detail_url not in seen:
                seen.add(detail_url)
                detail_urls.append(detail_url)

    records: list[Record] = []
    for idx, detail_url in enumerate(detail_urls, start=1):
        html = fetch(session, detail_url)
        record = parse_detail(html, detail_url)
        records.append(record)
        print(f"[{idx}/{len(detail_urls)}] {record.patent_id} {record.title}", file=sys.stderr)
        time.sleep(0.1)

    records.sort(key=lambda r: (r.score, r.meta.get("公開日", ""), r.title), reverse=True)
    ai_records = [r for r in records if r.score >= 4]
    curated_records = [r for r in records if r.patent_id in CURATED_SELECTION]

    (OUT_DIR / "jaea_patents_all.json").write_text(
        json.dumps([r.to_row() for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(OUT_DIR / "jaea_patents_all.csv", records)
    write_csv(OUT_DIR / "jaea_patents_ai_candidates.csv", ai_records)
    write_markdown(OUT_DIR / "jaea_patents_ai_candidates.md", len(records), ai_records)
    write_curated_csv(OUT_DIR / "jaea_patents_ai_curated.csv", curated_records)
    write_curated_markdown(OUT_DIR / "jaea_patents_ai_curated.md", curated_records)

    summary = {
        "total_results_reported": total,
        "detail_pages_scraped": len(records),
        "ai_candidates": len(ai_records),
        "ai_curated": len(curated_records),
        "pages_scraped": pages,
    }
    (OUT_DIR / "jaea_patents_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
