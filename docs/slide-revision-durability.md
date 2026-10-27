# Durable single-slide AI revisions

The actual `PresentationPane._revise_current_slide` starts a `slide_revision`
job. The worker validates and persists its completed candidate **before** the UI
callback. Navigation is no longer a condition for retaining the output.

- `begin(deck, index, instruction)` captures the original workspace identity,
  paper lifecycle, loaded artifact observation, deck/private bindings, explicit
  legacy roots and provider connection snapshot. Credentials remain in memory.
- `run(job)` acquires one nonblocking deck job lock, captures bounded evidence and
  verified PNG bytes, and resolves the captured AI route before preparing inputs.
  It records the actual model prompt before calling the model. Revisions use the
  deck's saved/historical evidence; absent evidence does not trigger a fresh crawl
  or silently read another PDF after navigation.
- Completed validated output, original instruction, original deck and image
  closure are atomically retained before `save_deck`. Managed publication uses
  the original client/observation and one stable operation ID. Unbound publication
  compares the original file hash and checks the original database/lifecycle.
- `publish(job)` retries a generated result without a model call. An accepted
  request is idempotent; failed activation after a committed managed operation
  retries that same operation. A replaced/rebound workspace or changed paper/deck
  keeps a candidate and receives no new research writes.
- UI adoption also checks the selected workspace, paper, page and original draft.
  Changed drafts remain visible. A matching adopted result is one undo operation.
  The same failed result exposes **Retry save**; changing the instruction starts a
  new job. `editable_deck(job)` strips worker-only lookup overrides so later normal
  editing can add new materials.

## Private receipt contract

Receipts live below the **captured** deck folder:
`<deck-root>/<sha256(local-paper-id)[:24]>/.revision-requests/<request-uuid>.json`.
They are private research output, not telemetry or sync DTOs. Each bounded JSON
record contains the exact keys in `slide_revision.RECORD_FIELDS`:

`version`, `request_id`, `database`, `database_identity`, `binding`, `parent_token`,
`original_file_hash`, `paper_id`, `mode`, `index`, `instruction`, `original`,
`observation`, `file_operation`, `evidence`, `figures`, `prompt`, `system`, `result`,
`summary`, `status`, `reason`.

`figures` maps source IDs to `{sha256, base64}`. Each PNG is decoded/validated;
the full closure is bounded to 128 figures/32 MiB, evidence to 8 MiB, and the
receipt to 48 MiB with result capacity reserved before AI starts. Status is one of
`prepared`, `generated`, `accepted`, `candidate`, `failed`. Prepared/failed
requests are not successful generation receipts. No provider connection snapshot,
API key or account settings object is serialized.

`validate_request_record(record)` validates bounded private data without following
its paths. `load_request(path, database=..., deck_root=..., figures_root=...)`
requires explicitly selected workspace roots, rejects link paths or mismatched
ownership, verifies the PNG closure, and loads **only a completed result**.
Calling `publish(loaded_job)` requires no original image files or new AI call.

The retained file-candidate review UI and complete-backup registry adapter remain
separate integration work. These receipts must be copied losslessly as private
provenance by that adapter, never replayed from embedded paths or promoted to a
fresh observation. Existing managed `research_file_candidates` records remain
available in addition to the full producer receipt.

## Verification

Fixture tests exercise real worker navigation, closing, duplicate activation,
one-step undo, model/account changes, source-file removal, database replacement,
identical paper delete/recreate, stale deck preservation, failed storage with UI
and restart retry, corrupt retained images, managed commit/activation interruption,
and cross-workspace managed publication. They make no real model/network calls or
read the owner's research data. The parent integration runs the full project
check before committing this slice.
