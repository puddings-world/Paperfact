# ADR 0011: Review retained work without rebasing it implicitly

Status: partially implemented in the unreleased v0.5 branch, 2026-10-27.
Generated SQL and supported remote conflicts have typed application and a desktop
entry point. See `../research-review.md` for exact coverage. Compound/artifact
application, durable edited drafts and full workflow integration remain required.

## Decision

Expose one workspace-scoped **Review changes** view for local stale results and
remote conflicts. A retained result is a successful preservation of work, not an
accepted research update. Display the distinction in the original editor, job
result and workspace status. Never invoke an AI model just to open, compare,
export or retry publication of an existing result.

Use small adapters over the existing records, not a second canonical conflict
database. A durable review-action receipt may reference an original candidate;
do not replace its original observations or rewrite its operation envelope.

| Existing record | Review meaning |
|---|---|
| `research_capture_candidates` | A compound SQL edit rejected at commit; keep its intended mutations together. |
| `research_generation_requests` with `status=candidate` | Generated content and the exact input/output context used to produce it. |
| Owned generation recovery sidecars | Work whose original database disappeared or changed binding; never silently attach it to the replacement workspace. |
| `research_file_candidates` | A retained artifact manifest, observed base and verified file closure. |
| `paperfact_sync_conflicts` and retained inbox receipts | A remotely decided conflict; resolution must reference the exact conflict operation and current canonical revision. |
| Detached `recovery_records` | Original provenance and unsent work from a backup; these are not active old-device operations. |

The adapter validates its underlying format before rendering. Unknown/newer
formats remain exportable evidence with an upgrade state; do not guess their
fields or offer an unsafe Apply action.

## Read model

Use a stable `(workspace, origin_kind, origin_id)` identity and bounded pagination.
Return a title, paper/list identity, feature, preservation reason, timestamp when
available, status and actions supported by that adapter. A timestamp is display
metadata, never conflict authority. Keep large text and binary assets out of list
rows; load previews explicitly and with bounded size.

The detail view separates:

- **The version this work started from**, including an explicit absent target.
- **Current saved content**, loaded with its own current revision/lifecycle token.
- **The retained result**, its source PDF version and relevant changed inputs.

Missing old bytes show an unavailable preview, not a reconstruction from today's
PDF. Source jumps use the candidate's exact document hash. Preview rendering uses
the same sanitized Markdown/deck readers as ordinary research; it never executes
stored HTML, arbitrary paths or generation instructions.

## Actions and transaction boundary

- **Keep current** dismisses the review item through a local decision receipt.
  It does not delete the candidate, remote conflict or historical assets.
- **Copy/export retained work** uses a bounded explicit destination. Include
  research and provenance only; no device login, private service configuration or
  generation diagnostic receipts. A recovered archive remains a private backup,
  distinct from a colleague's sharing package.
- **Compare/edit a proposed result** starts a new draft with original provenance.
  Editing that draft never mutates the immutable candidate.
- **Apply the reviewed result** creates a new typed operation against the version
  shown in the review dialog. Before commit, recheck the current row, parent
  incarnation, workspace and exact file closure. A second change leaves the review
  and draft open. Do not refresh the base immediately before applying.
- **Regenerate from current inputs** is a separate, explicitly labeled AI action.
  It creates a new job context and uses normal account/model routing and progress.

For remote conflicts use the existing explicit resolution operation and
`resolution_of` contract. A normal put is not an equivalent resolution. Local
stale candidates do not automatically become remote conflicts; publish only the
new action selected in review. Deleted/restored parents require an explicit
target choice, not an ID-only reattachment.

Commit the accepted research action, outbox and review receipt together. Use a
stable review request ID and payload fingerprint so repeated Save, process retry
or response loss creates one action. A changed decision cannot reuse that ID.
Compound candidates are reviewed as one operation group; unsupported mutations
block application rather than producing a partially applied success.

Artifact application stages and verifies every required body/asset before
committing the manifest. Desired/applied activation remains recoverable and
separate. Keep the current visible deck and unsaved editor text until the user
chooses to open the accepted revision. A retained manifest alone is not an
available offline deck.

## Desktop and mobile presentation

The workspace status shows a review count and a direct action; a model completion
that retained work says **Saved for review**, not **Updated** or **Synced**.
The original editor keeps its draft and offers a link to that exact item. Opening
the review pane never steals focus from an unrelated active editor.

Desktop supports keyboard navigation and a three-way text comparison, with a
simple two-way fallback when no original body was retained. Mobile starts with
the same explanations, current/retained read-only previews, export and existing
plain-note resolution capabilities. Hide unsupported rich-content application
actions; do not flatten anchored notes or editable decks into plain text.

Externalize English and Traditional Chinese labels. Announce job completion and
review availability through an accessible status region; preserve selection and
scroll during refreshed counts. Large diffs load in a worker and cancellation
discards only the preview request.

## Acceptance

- One stale save retried repeatedly creates one candidate and one visible item.
- Reviewing, dismissing or exporting never changes current research or invokes AI.
- Applying the displayed version changes research once; another edit during review
  retains the draft and leaves the newer research unchanged.
- Remote resolution closes the intended conflict on a second device; choosing a
  different candidate or restored parent does not accidentally close another one.
- A database replacement, workspace switch, sign-out, modal close or late preview
  cannot display private content in another workspace or publish to it.
- Backup/restore preserves original candidate bytes, review receipts and rejected
  chains. Restored old-device operations are never uploaded verbatim.
- Missing/corrupt artifact bytes prevent activation; retries recover without
  regenerating content or losing the previously applied revision.

This view depends on complete adapter validation and reviewed typed writers. Until
those application paths pass behavior tests, offer retention/export and truthful
status rather than an unguarded generic SQL replay button.
