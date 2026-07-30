# jaea-search

This is a Claude Code shortcut for the standard invocation:

`jaea-search "検索キーワード"`

Use the repository-local JAEA search skill for the following search keyword:

`$ARGUMENTS`

Follow @skills/jaea-search/SKILL.md.

If `jaea/scripts/search_rag.py` exists, run:

```bash
uv run python jaea/scripts/search_rag.py "$ARGUMENTS"
```

If `jaea/jaea.duckdb` does not exist, the search script builds it automatically from `jaea/output`.

If the search script or DuckDB is unavailable, search these fallback files:

- `jaea/output/jaea_patents_ai_curated.md`
- `jaea/output/jaea_reports_cv_ar_high_confidence.md`
- `jaea/output/jaea_reports_cv_ar_candidates.md`

Return related patents and reports separately, with evidence chunks, reasons, and links.
