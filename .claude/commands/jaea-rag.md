# jaea-rag

This is a Claude Code shortcut for the standard invocation:

`jaea-rag "検索キーワード"`

Use the repository-local JAEA RAG skill for the following search keyword:

`$ARGUMENTS`

Follow @skills/jaea-rag/SKILL.md.

If `jaea/scripts/search_rag.py` exists, run:

```bash
uv run python jaea/scripts/search_rag.py "$ARGUMENTS"
```

If the search script or DuckDB is unavailable, search these fallback files:

- `jaea/output/jaea_patents_ai_curated.md`
- `jaea/output/jaea_reports_cv_ar_high_confidence.md`
- `jaea/output/jaea_reports_cv_ar_candidates.md`

Return related patents and reports separately, with reasons and links.
