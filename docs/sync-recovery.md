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
creation. Legacy PDF aliases are recognized only through an exact applied manifest
and portable-to-local paper mapping. Other legacy text, figures, brief files,
presentation histories/drafts and research JSON files require migration first.
There is no misleading “metadata complete” backup mode.

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
