# Workspace location and independent recovery UI

Status: implemented for isolated fixture validation; not a claim that private
sync enrollment or the complete v0.5 release is available.

Open **Research data → Workspace and recovery** in the desktop app. The dialog
shows the captured active database directory and its actual location policy:
`PAPERFACT_DATA`, legacy `PAPER_DAILY_DATA`, installed-platform default, source
checkout `data/`, or an explicitly selected location. It does not change defaults,
move the workspace, open another database, or access provider accounts.

## Status semantics

- Background reads use read-only SQLite transactions, a two-second SQL execution
  budget and counts capped at 100,000 (shown with `+`). No constructors that enroll
  a workspace or initialize a sync client run during status refresh.
- Committed local records are separate from unsaved editor drafts. Queued uploads,
  acknowledged operations awaiting their stream receipt, and unresolved conflicts
  have separate counts. Zero pending changes does **not** mean synchronized;
  connection state and last successful sync remain explicitly unknown.
- Registered blob paths must belong to the captured workspace and agree on one
  owned store. A refresh checks at most 256 objects / 64 MiB, with a two-second
  hashing budget checked between 256 KiB reads. Counts describe that sample, not
  complete research dependency closure. Unregistered or unreadable storage is
  unknown, never silently displayed as zero missing files or available offline.
- File verification reads current bytes and compares SHA-256/size; it does not
  trust a previous `complete` index flag. It does not mutate the blob index.
  These are cooperative I/O budgets, not an OS-level deadline for a stalled disk.

## Backup and restore

The real buttons call `sync_recovery.create`, `inspect`, and `restore_detached`.
Full schema, retained history, candidate records, PDF/deck closure and credential
exclusion stay under that module's complete-or-fail contract. Unsupported legacy
files or missing historical blobs cause a failed backup, not a metadata-only ZIP
presented as complete. See [recovery scope](sync-recovery.md).

Backup is unavailable while known desktop research workers run. The modal dialog
blocks new desktop editing; automatic analysis launch is held while it is open.
There is no repeated acknowledgement checkbox. A read-only `data_version` watch
and bounded typed generation/chat/compound sidecar inventories bracket the
snapshot: a detected change discards the stage and asks for retry. SQLite and
sidecars do not share a cross-process maintenance lease; this is change detection,
not a universal atomic snapshot across arbitrary external file writers. Files
needed by retained manifests are fully verified by the existing recovery API.

All results are built in owned temporary directories. New ZIP publication uses
exclusive hard-link creation; restored directories use the existing native
atomic no-replace helper. Existing destinations and the active workspace are
never overwritten. Destinations inside the active workspace or managed storage
are rejected. Unsupported filesystem publication fails rather than falling back
to an overwrite-prone rename.

Inspect copies the chosen ZIP into bounded temporary storage and verifies that
exact copy. Restore copies it again and requires the same complete package hash
as the displayed preview, then validates and rebuilds into a staging directory.
A valid replacement ZIP with the same backup ID still requires a new preview.
Preview and restore can temporarily require an additional archive-sized copy.

Restored research is left in the explicitly chosen **new** directory with
`papers.db`, verified objects, readable applied files, and archived recovery
records. It is detached: no old device credentials, capture binding or outbox is
activated, and the running app never switches automatically. Opening/re-enrolling
that restored workspace remains a separate explicit bootstrap step.

## Worker and interaction boundaries

One worker runs per dialog. Repeated clicks and refreshes cannot queue duplicate
backups. Cancel and close invalidate publication before its atomic boundary;
underlying recovery verification is not forcefully terminated. The dialog says
it is waiting for that stage, retains the worker, and closes after safe cleanup.
The main window cannot destroy an active workspace worker. A cancellation after
publication cannot undo or mislabel a successfully created artifact.

Workspace path, database identity and durable binding are captured and checked.
Changed/replaced workspaces reject late publication and stale UI updates. No
callback refreshes the reader, steals its draft, or triggers AI. Error summaries
never display raw exception bodies. Scrollable content keeps close/cancel actions
reachable at smaller sizes; paths and status text support copying.

Not implemented by this UI: enrollment, device registration/revocation, automatic
transport, pinning/eviction, relocating the active workspace, or activating a
restored installation. The dialog labels these as unavailable.

## Acceptance scope

`test_workspace_service.py` and `test_workspace_dialog.py` use temporary research,
simulated failures and actual offscreen Qt actions. They cover content/hash
roundtrips, existing destinations, corrupted/changed packages, missing bytes,
bounded status, pending/receipt distinctions, rollback on concurrent writes,
cancel/close, repeated activation, workspace replacement/switch, retry, responsive
layout and actual main-menu wiring. Existing recovery tests remain required.
No real research database, provider login, model call, sync server or cloud service
is exercised. Native Windows/Mac dialogs and Mac filesystem behavior remain part
of the release acceptance matrix; offscreen tests do not establish those passes.
