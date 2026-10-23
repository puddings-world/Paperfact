# Paperfact research planning evidence

- Pattern / revision: bounded discovery and preview-before-commit, revision 2.
- Status: validated-local; not yet reused in another app.
- Date / project: 2026-10-23, Paperfact.
- Trigger: researchers need to discover a field without already knowing its
  bibliography, and want a choice of output without confusing search breadth
  with full-text analysis or formal review completion.
- Invariants: models select retrieved IDs; annotations reference original abstract
  passages; a preview does not create research records; selection and explanation
  commit atomically; explicit follow-up analysis targets the created list.
- Preconditions: a public search adapter and a task-scoped model facade. Do not
  claim exhaustive coverage, verified citation edges or completed PRISMA work.
- Trade-off: bounded abstract-based discovery is faster and cheaper than reading
  all candidate full texts, but methodological and empirical claims need checking.
- Implementation: `src/paper_daily/research_plan.py`,
  `src/paper_daily/desktop/import_dialog.py`, `src/paper_daily/desktop/main.py`.
- Regression evidence: `tests/test_research_plan.py`,
  `tests/test_research_plan_ui.py`, `tests/test_research_outputs.py` cover depth and
  output combinations, unknown/duplicate IDs, source passages, scope confirmation,
  model snapshot isolation, repeated activation, stale results, cancellation,
  rollback/retry, saved research and offline bundle transfer.
- Commands: `python -m pytest tests/test_research_plan.py
  tests/test_research_plan_ui.py tests/test_research_outputs.py -q`;
  repository-wide verification: `python scripts/check.py`.
- Live check: public scholarly search exercised Semantic Scholar failure followed
  by OpenAlex fallback and returned 25 candidates. The minimal public response in
  `tests/fixtures/research_search_openalex.json` anchors adapter parsing. Synthetic
  UI screenshots were inspected for readable Chinese labels and preview space.
- Limits: fake model responses test orchestration, not literature-review quality.
  No live model generation or paid full-text run was used for verification.
  User research content was not used as a stress-test fixture.
- Privacy: evidence contains repository paths, synthetic data and public API
  metadata; no credentials or identifying account details. No global promotion.

## PDF retrieval follow-through

2026-10-23, validated-local: `tests/test_pdf_downloads.py` and
`tests/test_pdf_downloads_ui.py` verify a three-worker cap, cross-list deduplication,
actual byte progress, alternate source fallback, cancellation/retry, atomic PDF
publication, reader/download lock coordination, preserved selection and shutdown
cleanup. A malformed PDF exposed a Windows native file-handle leak when validation
opened a file by path; validating bounded bytes instead allows reliable cleanup.
117 targeted tests passed with simulated network streams and isolated databases.
These tests do not establish that every publisher will permit downloads.


Follow-up UX correction requested by the user: progress must not increase row
height. It now occupies a short slot on the title line and terminal states use
the existing PDF tag area. The previous expanded-height assertion was updated
to the user-requested original height; added tests cover all job states and
narrow/wide list widths. Compact UI and queue-key tests: 24 passed. The initial
live download run completed the current eight-paper list (seven missing originals)
without model calls; no user titles or identifiers are retained in this evidence.
