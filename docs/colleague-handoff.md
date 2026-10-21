# Independent colleague handoff

The supported local workflow is: install -> import -> read -> select the
recipient's AI -> continue research -> export. No connection to the sender's
computer, Paperfact cloud account or shared database is required.

## First use

1. Run the platform setup command from the README, then open the reader.
2. An empty collection overview is normal. Acknowledge the usage explanation;
   the separate optional improvement-statistics checkbox can remain unchecked
   without changing any reader or AI functionality.
3. Import a research bundle and review its contents. Available PDF bytes, saved
   analyses, annotations, figures and decks travel together. Missing PDFs are
   reported. Imported articles start unread.
4. Read saved work without an AI account. For new AI work, use AI settings to
   install/open the selected official CLI's setup instructions and sign in with
   the recipient's own account. Model/plan availability belongs to that provider.
5. Select the global connection or a per-feature override, continue analysis and
   save edits. Re-export the selected collection to share those saved results.

Run `paperfact doctor` for local checks. Optional `--ai` invokes the selected
model and may use quota; optional `--sources` contacts scholarly websites.

## Shared operation boundary

`research_service.py` is the local interface used by desktop/CLI bundle operations:

- `list_collections() -> list[dict]`: stable list IDs and names.
- `inspect_bundle(source: Path) -> dict`: validated preview.
- `export_bundle(list_id, out: Path, *, notes=True, with_pdfs=True, log=...) -> dict`.
- `import_bundle(source: Path, *, replace=False, pdfs=True, log=...) -> dict`.

The functions use the process's configured workspace, not a caller-supplied
database path. They do not provide a network server, external authentication or
general agent execution. A future MCP adapter should authorize workspace/file
access and expose bounded schemas before calling these services. AI generation
continues through the task-profile facade; account configuration never travels
inside a research bundle.

Packed-file installation is staged. Caught file-write and DB-transaction failures
restore installed files and roll back rows. Retry merges without duplicating list
membership. A failed rollback preserves its recovery directory and reports it.
This does not claim crash-consistent recovery from forced process termination.
Older/link-only packages may fetch missing PDFs; normal packed bundles work offline.

## Acceptance evidence

- `test_workspace_transfer_ui.py`: empty startup, no automatic AI, GUI bundle
  preview/export/import, selected-list scope and failure/retry.
- `test_bundle_offline.py`: offline fidelity, PDF-version conflicts, private-data
  exclusion, corrupt/unexpected/missing files.
- `test_bundle_recovery.py`: write/transaction failure, restoration, retry,
  preserving an earlier export and detecting files changed during packing.
- `test_colleague_journey.py`: separate sender/recipient data, saved reading
  content, recipient login/selection, deep analysis persistence and re-export.
  Provider authentication, model discovery and inference are simulated; research
  storage, UI selection and task routing are real.
- `test_feedback_consent.py`: explicit acceptance, decline, reminder preferences,
  policy renewal, lifecycle deduplication and withdrawal during export.
- `test_doctor_local.py`: no model/network calls in ordinary diagnostics.

The release gate remains `python scripts/check.py`. Automated fixtures do not
prove vendor OAuth availability for another person's account, platform installer
signing, or behavior on a machine that has not been tested.
