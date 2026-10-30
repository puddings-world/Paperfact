# Original-PDF annotation review

This integration uses the existing local `ResearchReview` service. The desktop
and mobile review shells do not adopt an analysis row directly.

- `preview("generation", request_id)` and `preview("sidecar", request_id)` show
  one typed group: the retained analysis, located AI marks, and unmatched quote
  indexes. `editable` is false; JSON or text edits cannot replace part of a group.
- Preview resolves the selected paper's original PDF and verifies its SHA-256 and
  extracted source text. It rebuilds locations from the retained original quotes
  without calling an AI provider. A missing or changed PDF disables application.
- The sealed preview records the current parent row and lifecycle, annotation
  rows, hidden preferences, graph observations, and document manifests. Applying
  compares that exact displayed base again inside the write transaction.
- `decide(preview, request_id=...)` writes analysis, located marks, outbox and review
  receipt together. Failure rolls all of them back. Retrying the same decision
  returns the receipt without a second model call or duplicate operations. The
  retained source request remains available after either outcome.
- Existing manual marks and AI hidden choices survive. Omitted historical AI marks
  remain stored; current analysis membership controls the displayed layer.
- Restoring deleted content or selecting another current owner requires
  `target_preview(preview, paper_id)` followed by explicit target confirmation.
  The target must have the exact same verified PDF. Enrolled restorations create
  new graph incarnations instead of reusing deleted authority.
- Individual remote `highlight_analysis` and `ai_highlight` conflicts are currently
  keep/export-only. A singleton does not carry sufficient authority for complete
  grouped application. This limitation must remain visible until remote grouped
  source review is implemented. Manual highlights retain their independent API.

The analysis pipeline resolves its original PDF immediately after fetch and before
parallel remote explanation/citation work. It calls `reading_annotation_jobs.prepare`
with that immutable fingerprint, original owner, workspace and AI connections.
It never recaptures replacement bytes when the remote phase completes. Highlight publication is one phase; linked
explanation generation is a separate dependent phase with honest partial status.
The shared reader/materials UI uses the same scoped job service. Automatic
post-dive preparation also carries the original owner, PDF hash and captured
connections through `DiveResult`/`DiveCompletion`. It writes status only to that
owner and remains opt-in. Replacing the source between explanation acceptance and
annotation preparation preserves the explanation and refuses another AI call on
replacement bytes. Standalone legacy helpers retain their compatibility API.

Canonical-deletion markers (`paper_annotation_known`) travel in optional list
bundle rows and are restored live from detached backups. They prevent an old
compatibility cache from resurrecting a removed analysis after import or restore.
Packages with canonical annotation rows or deletion markers use format 2 with
explicit required capabilities. Older clients reject those packages rather than
silently lose deletion knowledge and resurrect a compatibility cache. Older
format-1 packages without these extended rows remain readable.

## Verification boundary

Focused fixture tests exercise accepted and stale groups, hidden/manual mark
preservation, failed writes and retries, failed-generation sidecars, changing PDF
bytes during publication, parent edits, private-path-free exports, explicit
restoration, and complete-source backup recovery. No live provider, production
workspace, or physical mobile device is used. The complete project check and the
cross-platform/device release gates are still required after integration.
