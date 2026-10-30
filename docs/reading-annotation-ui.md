# Reading annotation workflow

The desktop reader and full-analysis pipeline use the same workspace-bound preparation service.
It publishes the selected evidence and its located PDF marks as one protected group, then links
that evidence to saved deep explanations. Manual marks and hidden AI marks remain user choices.

- The action snapshots the paper, workspace, PDF and AI route. Switching papers or accounts
  while work runs cannot redirect the result or replace a different reader view.
- Repeated activation shares the existing work. The normal background activity bar reports
  the actual evidence and explanation phases; it does not invent completion percentages.
- Stop prevents a subsequent phase. An in-flight provider call may still finish. Evidence
  already accepted remains saved, and the UI reports incomplete explanation linking honestly.
- A stale completed group is retained for review, rather than replacing current research.
  Reviewing a highlight group shows analysis, located marks and unmatched quotes together.
- Existing complete research can be read offline without calling a model. Unavailable account,
  source or workspace capability never triggers an unprotected legacy write fallback.
- A phone receives the closed annotation projection and renders plain text locally. The service
  worker caches only static application modules, not authorization or research responses.

Validation uses isolated enrolled and unenrolled SQLite/PDF fixtures, simulated models and an
actual Qt worker. It covers route isolation, source replacement, deletion, repeated activation,
partial cancellation, retry, draft preservation, and HTTP-to-offline mobile projection.
Native macOS packaging, live provider login and real cross-device transfer remain separate checks.
