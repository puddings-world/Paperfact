# Independent research recovery

`sync_recovery` creates a private, complete-or-fail research archive and restores
it into a fresh **detached** workspace. It does not enroll a device, connect to a
service, merge a shared list, change the active workspace, or run AI.

```sh
python -m paper_daily.sync_recovery create /workspace/papers.db /backups/research.zip --blob-root /workspace/owned-blobs
python -m paper_daily.sync_recovery inspect /backups/research.zip
python -m paper_daily.sync_recovery restore-detached /backups/research.zip /new/recovered-workspace
```

Use the project's environment Python (`.venv/Scripts/python.exe` on Windows,
`.venv/bin/python` on macOS/Linux). `--blob-root` names the explicitly owned local
BlobStore, not a remote service namespace. Omit it only when no retained research
references immutable bytes. The destination ZIP and restore directory must be new.
An optional `--legacy-root` adds another directory to the migration inventory; it
does not suppress checking the database's own directory.

## What is retained

- All registered research tables and explicit research KV entries, with portable
  identity mappings and reading state/order.
- The complete received event prefix, graph receipts, accepted/conflicted versions,
  resolution records, outgoing operations, and acknowledgments beyond the inbox.
- Current, historical, conflicted, pending and candidate PDF/deck blob references.
  Every referenced byte must exist and match its size/SHA256.
- Capture candidates, validated generation receipts and owned generation sidecars.
  Original database paths are provenance only. Deck drafts are retained only when
  their referenced assets are pinned by their original validated manifest.

The exporter first uses SQLite's backup API, including committed WAL data. It then
serializes typed allowlisted rows into bounded JSONL files. Source SQLite pages,
free pages, SQL statements, triggers, arbitrary tables/KV entries, account tokens,
provider configuration, telemetry, and device transfer/session configuration are
not copied. This archive contains private research; hashes are integrity checks,
not encryption or anonymization.

Unknown research schema, unflushed capture state, incomplete history, missing or
corrupt bytes, unpinned draft assets, and unclassified legacy research files block
creation. Applied PDF aliases are recognized through an exact manifest and
portable-to-local mapping. Required original legacy PDFs can also be adopted into
the archive, without live enrollment, by exact hash from trusted workspace PDF
roots. Use `pdf_roots=[...]` or repeated `--pdf-root` for explicitly owned external
directories; embedded receipt paths are never followed. See
[archive-only legacy source adoption](legacy-source-recovery.md).
Other legacy text, figures, brief files,
presentation histories/drafts and research JSON files require migration first.
There is no misleading “metadata complete” backup mode.

Schema definitions are reused only within each synchronous create, inspect or
restore operation. The scope contains immutable column metadata, not research
rows, database connections, file hashes or validation decisions. Every archive
row and nested retained-history group is still validated; independent calls,
threads and retries construct fresh metadata. This bounds repeated schema
construction when a research archive includes earlier recovery provenance.

Private Lineage original observations also use the existing typed source-receipt
closure: each selected available PDF keeps its own paper, lifetime, corpus and
request identity. Their `paperfact.lineage-source-observation.v1` records and exact
PDF bytes are retained in independent backups. Schema-valid Lineage proposal
records also retain their ordered source closure; a replaced database's owned
sidecar includes the original version pairs rather than borrowing current PDFs.
They grant no claim/source lookup permission, synchronization identity or resumable producer. Detached restore keeps
them as historical recovery records. See [the producer boundary](grounded-lineage-producer.md#durable-original-observations-2026-11-13-continuation).

## Detached restore

Restore checks the closed archive inventory, bounded counts/sizes and every digest.
Rows are checked and hashed again during staging, so replacing the ZIP after initial
inspection cannot substitute different data. Trusted current schema and migrations
create `papers.db`; source SQL is never executed. All files are staged before the
new destination directory is published. Existing destinations and source files stay
untouched on failure.

Original protocol and candidate rows live in `recovery_records`, with provenance in
`recovery_identity`. The original device identity and pending flags are **not** an
active Journal; a fresh recovery device UUID is recorded. The archive's raw paths
never select output locations. `objects/<sha256>` retains all required versions.

Applied PDFs become safely derived `pdf/<local-paper-name>.pdf` aliases. An incoming
desired replacement does not displace the last applied PDF. Applied decks rebuild
the ordinary presentation slot, editable layout, speaker notes, images and evidence
under a hash-derived paper directory. Pending/conflicted/draft versions remain in
archived protocol rows and immutable objects for later reviewed recovery. Opening
this directory uses the ordinary explicit workspace selection; restore does not
switch a running app's database.

Alias creation fails before publication if the reader's ASCII sanitization or
case folding would map an applied PDF to more than one retained paper ID. This
also checks papers without downloaded PDFs, whose lookup could otherwise open
another paper's bytes on Windows or a case-insensitive macOS volume. Windows
reserved device names and oversized aliases are rejected. IDs and mappings are
never silently renamed. These workspaces need a reviewed migration or a future
detached reader with explicit hash-based mappings before this recovery format can
restore them; complete recovery for every possible legacy ID is not yet supported.

## Remaining gates

Re-exporting a detached database is blocked until archived recovery rows can be
reconciled; keep the original recovery ZIP. Automatic legacy-file migration, first
enrollment, new-device bootstrap, review and
reapply of archived candidates, encrypted backups/key recovery, a maintenance lock
shared with every writer, and UI recovery controls remain separate work. A detached
restore must not be advertised as a resumed private sync session. Run creation while
writers are quiescent for a complete workspace checkpoint; SQLite snapshotting alone
does not freeze mutable legacy files or producers writing separate recovery sidecars.

The format caps metadata at 256 MiB, individual rows at 16 MiB, 500,000 rows,
10,000 blobs, and 8 GiB total. Limits fail explicitly; no records are truncated.


Publication uses native no-replace directory rename: Windows `os.rename`, Linux
`renameat2(RENAME_NOREPLACE)` and macOS `renamex_np(RENAME_EXCL)`. Missing native
symbols or unsupported filesystem/kernel flags fail explicitly; there is no POSIX
check-then-rename fallback. See the [Linux manual](https://man7.org/linux/man-pages/man2/rename.2.html)
and Apple's [rename contract](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/rename.2)
and [flag definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h).
Fixture tests exercise both POSIX native contracts and failure codes. Real macOS/Linux
filesystem integration remains a platform acceptance check when tested from Windows.


## Staged Lineage result and original closure

The local development backup registry includes optional `paper_lineage_sets`
research and private `research_lineage_publications` receipts. The latter has
closed fields `request_id`, `candidate_id`, `row_json`, `sources_json`. This does
not enable a Lineage task, desktop action or live protocol capability.

An unbound canonical row must have a complete publication receipt. Each receipt must match
its exact retained candidate, pre-call publication-base descriptor and every
original association in `research_local_source_owners`. All selected paper IDs
must exist; unavailable originals stay explicitly unavailable. Every declared PDF
is included by verified hash and size. Equal bytes may be stored once but do not
merge different source/paper/request identities. Missing history, a changed
association or missing original refuses backup before publishing an output file.
Archive inspection repeats these checks, even when an altered container's table
hashes have been recomputed.

Detached restore installs the exact research rows using maintained schema and
keeps old publication/candidate/source observations in `recovery_records`; it
never installs old publication authority, local original grants or sync identity.
The PDF objects remain in the detached archive's verified `objects` directory.
An old reader that does not recognize these tables must reject the package rather
than ignore them. This is a format extension within the closed recovery registry,
not a compatibility promise for v0.4 clients.

Recovered Lineage can be inspected as preserved research, but conversion into an
editable synchronized workspace remains explicitly blocked until typed fresh
source ownership and Lineage enrollment are implemented. The inspection explains
that gate and preserves the detached source. This is not an automatic destructive
migration or a completed active-source reader. List-sharing packages, live sync,
mobile projection and full installed-device acceptance remain separate work.


The development recovery registry now also preserves staged bound projections:
`research_lineage_sync_sources` (current metadata) and
`research_lineage_sync_history` (immutable complete operations). A bound canonical
row must match the exact visible marker and historical operation after retained
paper-alias mapping. Every available original pin must match its retained file
incarnation, exact paper parent and workspace, with full verified bytes. Hidden
or deleted reports retain earlier scientific/source history without restoring an
active report. Missing history or altered source lifetimes cannot be disguised
by recomputing ZIP/table hashes. See the
[bound history contract](grounded-lineage-producer.md#bound-projection-history-and-detached-recovery).

These two protocol tables restore into `recovery_records`, never live projection
or sync/source authority. Historical pins remain archival evidence after source
retirement, not permission to attach to a restored incarnation. The existing
explicit owned BlobStore input remains required. This archive-only extension does
not activate the Lineage producer, network admission, editable enrollment or UI.


## Native imported Lineage history

Recovery now preserves `research_lineage_imports` as typed protocol data beside
current `paper_lineage_sets` and every exact local original association. Both
current and displaced reports retain their referenced PDF versions. Archive
inspection independently verifies original hashes, page counts and located
quotations; recomputing container/table hashes cannot make a false location true.
Missing/foreign associations or unavailable required bytes refuse without a
partial destination. Unknown future research schemas remain unsupported.

Detached restoration keeps import/source/lifecycle records in `recovery_records`
and original bytes under `objects/`; it does not reactivate old native or sync
identities. A fresh local paper lifetime alone grants no access through the native
imported-source reader. Reviewed editable adoption and actual source-UI activation
remain pending. Retired historical source data do not recreate deleted papers.
See [the imported-history contract](lineage-packages.md#imported-history-backup-and-detached-restore)
for exact boundaries, limits and regression coverage.


### Staged fresh Lineage original preparation

The internal [fresh-source adoption component](lineage-packages.md#fresh-originals-from-detached-recovery-inspections)
can verify active unbound imported/generated archive cohorts and stage fresh
receiver originals in bounded batches. A caller-owned savepoint covers all
batches, source associations and fresh parent lifetimes; retry is idempotent.
It never edits the detached source or installs old native grants. It is not
registered in `RecoveryAdoptionService.prepare`: complete history retention and
compound Lineage enrollment must close before synchronized editable copies are
enabled. The user-facing unsupported-content blocker remains in force.
