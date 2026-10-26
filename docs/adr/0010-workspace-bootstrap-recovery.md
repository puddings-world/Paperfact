# ADR 0010: Workspace bootstrap and independent recovery

Status: partially implemented. Independent complete-or-fail recovery CLI and detached
reader restore are implemented; enrollment/bootstrap/reapply remain planned. 2026-10-26.
See [recovery contract](../sync-recovery.md) for supported schemas and migration gates.
This defines local orchestration around the existing reference protocol. There is
no public enrollment, snapshot-download, restore or retention endpoint today.

## Decision: replay retained history first

The first new-device bootstrap replays **all workspace events from sequence 1**
through `ReferenceService.pull` and `SyncClient.receive`. Keep all receipts,
tombstones, conflicts and resolution events. Do not construct a bootstrap by
copying only `sync_heads`, exporting the read-only projection, or importing a list
bundle. Those representations cannot reproduce the current protocol's invariants.

Full replay is the simplest truthful initial implementation. Its cost grows with
history; report progress by received events/bytes, without inventing a percentage
when the server has not supplied a total. Canonical snapshot optimization is
deferred until it can carry the following exact closure and pass replay-equivalence
tests, not introduced as an unverified shortcut.

| Required closure | Current dependency |
|---|---|
| Every original operation, outcome, event sequence and canonical head at that event | `receive` requires contiguous events and rejects fabricated conflict heads or changed replay content. |
| Creation/incarnation receipts, accepted and conflicting versions | Membership `added_at` and historical reading-state parent closure use origin receipts; retained rejected lineages can also support explicit retirement. |
| Parent identities/incarnations, active/tombstoned graph and structure markers | Child edits, parent deletion/restoration and structural dependencies cannot be inferred from current rows. |
| `depends_on`, `structure_depends_on` targets and their original device | Dependency validation is scoped to the same device/entity or touched parent; timestamps do not replace these receipts. |
| Conflict operations and every `resolution_of` target/resolution | A later accepted resolution must close the original conflict on every device; ordinary edits do not do this. |
| Creation sequence, exact active set and ordering receipts | Default order and digest compare-and-swap depend on incarnation/set semantics, not current SQLite positions alone. |
| All referenced blob manifests and ownership/retention references | Current, historical, conflicted and unsent content may need old PDF/asset bytes. Knowing a hash grants no access. |

An eventual compact snapshot needs a versioned authoritative checkpoint including
this dependency closure, verifiable prefix identity and its matching cursor.
Replacing the inbox with canonical heads while keeping the old cursor is invalid.

## First enrollment of an existing local workspace

1. Require a complete writer/file coverage registry, compatible schema and verified
   independent backup. The current `sync_capture.install`/`capture_existing` helpers
   alone do not meet this gate; unsupported file saves still bypass capture.
2. Acquire a workspace maintenance lock honored by UI, CLI, MCP and workers. Drain
   active writes; preserve open drafts. Create a consistent SQLite snapshot using
   SQLite's backup API and inventory/pin its exact file closure. Legacy mutable
   files must be quiescent or hash-checked before/after copying; retry/abort if they
   change. Never copy a live main SQLite file while ignoring WAL contents.
3. Prepare a staging workspace, leaving the original intact. Generate one workspace
   UUID and one device UUID. Assign portable paper/note/turn identities once,
   preserving local row references through mapping tables. Persist resumable
   baseline progress, mappings, immutable files and operation IDs in staging;
   restarting does not allocate a second identity set or duplicate operations.
4. Emit the complete baseline in bounded dependency-ordered batches: roots before
   children, memberships before reading state/order, manifests after verified local
   bytes. Include explicit lists, not a guessed privileged queue. Invalid/unsupported
   records remain in the original backup and block declaring enrollment complete;
   no silent omission, truncation or title-based merging.
5. Validate the staged semantic snapshot and capture coverage, then activate that
   workspace through the existing explicit runtime binding with a controlled
   restart. Preserve the original as the rollback copy. All subsequent research
   writes use capture; release the maintenance lock before network upload.
6. Upload owned bytes and baseline operations with their existing retry identities.
   Provision the empty remote workspace/device through a trusted administrative
   path; `ReferenceService.enroll` is such a fixture seam, not a public account API.
   Do not issue other devices access to a half-published baseline. Record readiness
   only after the baseline receipts are received contiguously. Interrupted upload
   resumes; local offline edits remain queued behind their real predecessors.

The staging directory, activation receipt and rollback path are explicit local
records. Do not change imported modules' workspace paths in a running process or
replace a database still opened by another process. No network-dependent step is
allowed to hold the source database write lock or prevent ordinary offline reading.

## New device joining the same private workspace

- Authenticate a **new** device and call existing `session_info` before receiving
  or sending private bytes. Verify the expected workspace/device/service binding.
  Start with an empty staging research database; initialize its own Journal/client
  and adapters. Historical operation device IDs remain unchanged as provenance;
  they do not become this device's active identity or outgoing credentials.
- Pull bounded pages from cursor 0 and use `receive` unchanged. Each page commits
  research, receipt/history, graph and cursor together. Restart at that durable
  cursor. A gap, changed event or incompatible schema stops bootstrap; never skip
  an event or reset the cursor to make an error disappear.
- With today's API, an exhausted page (`len(page) < requested_limit`, including an
  empty page) establishes a complete observed prefix C for that read transaction.
  Persist C as the bootstrap checkpoint; events arriving later are ordinary tail
  sync. A continuously busy workspace may remain in catch-up; do not claim a fixed
  initial high-water mark from an endpoint that does not exist.
- Derive desired files from that exact prefix. Receive missing files independently,
  verifying size/hash and ownership. A metadata-ready workspace may open with clear
  unavailable-file status; it must not claim offline completeness. An explicitly
  requested offline selection activates only after its entire verified closure is
  ready. Record `metadata_cursor=C` and the availability set separately.
- Atomically activate the validated staging workspace, then continue from C.
  Do not auto-run AI, regenerate analysis, fetch arbitrary published URLs, move
  current reader focus or overwrite local drafts during bootstrap/tail apply.

This path preserves portable entity IDs through protocol operations. Local SQLite
integers and filenames are reconstructed through adapters. An unrelated nonempty
local workspace is not a rejoin: keep it separate, back it up and import selected
research through the normal sharing/import contract after joining.

## Independent backup format and restore

Implement a separate versioned recovery package, not another mode of the ordinary
list bundle. Its closed manifest records workspace/protocol/backup versions,
captured cursor, original device as provenance, record counts, file sizes/hashes,
and whether all required bytes are present. An incomplete offline cache must be
reported as an incomplete recovery package, never a complete independent backup.

Capture the complete accepted inbox, graph/receipt state, outstanding operations
including acknowledged-but-not-received work, action/retry receipts, portable maps,
local conflict candidates and explicit unsaved recovery drafts. Include immutable
bytes referenced by accepted, conflicting, historical, pending and draft versions,
plus legacy research files not yet migrated. Record export/import identity metadata
needed to preserve intent; provider accounts, API/OAuth tokens, CLI homes, telemetry,
device scheduling and active authentication/session configuration are excluded.

Use an SQLite backup snapshot as the input, then rebuild an **allowlisted recovery
database** rather than shipping every table or raw database pages. Deleted secrets
in free pages and unknown KV entries must not leak through a blind database copy.
Preserve original operation envelopes as evidence, but do not make their old device
binding or upload flags active on restoration. The backup stays local/private by
default; cryptographic encryption/key recovery is a separate release requirement,
not a claim implied by hashes or file permissions.

Restore into a new isolated directory and verify schemas, all hashes and semantic
links before activation. Keep the source package and current workspace untouched.
For offline disaster recovery, provide a detached, readable restored workspace
with recovery drafts/candidates; it must not silently contact an old service.
For same-workspace rejoin, create a new device identity and replay authoritative
history first, then reconcile the restored outstanding work:

1. Match original operation IDs and exact payloads against the replayed receipts.
   Already-accepted or already-conflicted operations are not sent again; an old
   backup's `server_revision` is evidence to verify, not authority to advance C.
2. Preserve absent/unaccepted operations, their causal graph, observed bases and
   bytes as durable recovery candidates. Never send an old-device envelope using
   the new token, rewrite device IDs in place or automatically rebase old edits.
3. The first restore UI offers explicit review/reapply as **new** local actions,
   with stable recovery-request receipts. Compare old/current/candidate content;
   preserve all versions when choosing a resolution. Map new operation IDs and
   unaccepted creation incarnations consistently across selected dependent actions.
   Existing accepted parent incarnations remain exact; do not attach children to
   a newly restored parent merely because its entity ID matches.
4. Until that reapply workflow is implemented, retain and export the candidates
   without claiming they are synchronized. Do not discard them to finish restore.

## Retention, stale devices and authority recovery

Initial policy: no event/receipt/tombstone compaction and no garbage collection of
referenced history blobs. Cache eviction is distinct from deleting retained remote
research. Revocation blocks subsequent requests, not copies already downloaded.

If a future retention horizon is introduced, the protocol must explicitly identify
the minimum replayable cursor and required bootstrap version. An older client first
backs up its unsent work, then stages a fresh bootstrap and reviewed recovery.
An empty pull response must never mean that history was silently discarded.

A restored **server** database must not reuse old sequence numbers for different
events. A future service-generation/checkpoint identity is required before automated
authority rollback can reconnect clients. Today a client cursor ahead of the server
is an error; do not lower it or pretend the mismatch is a normal new-device join.
Server backups must pair authority events/heads/graph with owned immutable bytes;
client backup restoration is not an administrative server-restore procedure.

## Implementation seams and acceptance

- Add a local `sync_bootstrap` orchestrator around `runtime` binding, `store.SCHEMA`,
  `sync_research` mappings, `sync_capture`, Journal/client, owned blobs and transfers.
  Keep it separate from `bundle.import_`/`research_service` sharing operations.
- Add a recovery package module with closed table/file allowlists, SQLite snapshot
  rebuilding, persistent phase receipts and atomic staging activation. Extend the
  existing bundle path/hash safety helpers; do not reuse bundle merge semantics or
  assume its history exclusions are acceptable for backup.
- First prove empty-device full replay across parent rename/delete/restore, rejected
  parent lineage, dependent offline edits, conflict resolutions and order changes.
  Compare semantic projections and history with the source, not integer local IDs.
- Then test interrupted baseline/page/blob/activation phases, corrupt/missing bytes,
  concurrent tail events, revoked credentials and restarting every phase. Verify
  no duplicate baseline, no partial active workspace and no AI calls.
- Finally restore a backup containing acknowledged-but-unreceived edits, unsent
  dependency chains, conflicts and deck drafts under a new device. Prove source
  preservation, no credentials in the package, exact candidate recovery and
  idempotent reviewed reapply before advertising complete recovery.

Run the complete project check for each implementation batch. Recovery adds no public
service endpoints or deployment. Its targeted behavior tests cover private archives,
retained protocol/candidates, exact bytes, detached readers and failure preservation;
bootstrap and reviewed reapply acceptance remain outstanding.
