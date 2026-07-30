# jaea-rag

JAEA特許・報告書データから、ユーザの研究アイディアや検索キーワードに関連する資料を提示する。

## Trigger

Use this skill when the user invokes:

- `jaea-rag "検索キーワード"`
- `/jaea-rag 検索キーワード` as a Claude Code shortcut

Also use this skill when the user asks to find related JAEA patents, reports, 3D modeling, computer vision, AR mapping, image processing, spatial mapping, dose mapping, or remote robotics references.

## Inputs

- Skill name: `jaea-rag`
- Search keyword: free text, usually quoted, for example `jaea-rag "3Dモデル生成"`
- Standard invocation: `jaea-rag "検索キーワード"`
- Claude Code shortcut: `/jaea-rag 検索キーワード`

## Data Sources

Primary DuckDB target:

- `jaea/jaea.duckdb`

Fallback files when DuckDB or the search script is unavailable:

- `jaea/output/jaea_patents_ai_curated.md`
- `jaea/output/jaea_patents_ai_candidates.csv`
- `jaea/output/jaea_reports_cv_ar_high_confidence.md`
- `jaea/output/jaea_reports_cv_ar_candidates.csv`
- `jaea/output/jaea_reports_all.jsonl`

## Search Procedure

1. If `jaea/scripts/search_rag.py` exists, run:

   ```bash
   uv run python jaea/scripts/search_rag.py "検索キーワード"
   ```

2. If `jaea/jaea.duckdb` does not exist, the search script builds it automatically from `jaea/output`.
3. If the DuckDB search path is unavailable, search the fallback Markdown/CSV/JSONL files with `rg`.
4. Prefer high-confidence report candidates before broad candidates.
5. Always include patents and reports separately when both are relevant.
6. Treat results as related technical references, not legal patent clearance.

## Response Format

Return results in Japanese unless the user asks otherwise.

Use this structure:

1. 要約
2. 関連する特許
3. 関連する報告書
4. 技術的な接点
5. 追加で見るべきキーワード

For each result, include:

- Title
- Document ID or report number
- Why it is related
- Detail URL
- PDF link when available

## Ranking Guidance

Prefer records where the search keyword appears in:

- title
- categories
- matched keywords
- evidence text
- abstract

For 3D or AR queries, avoid false positives from:

- `Ar` meaning argon
- generic `3D` numerical simulation without image, mapping, camera, robot, or spatial context
