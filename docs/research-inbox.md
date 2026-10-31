# Research Inbox candidate

The Research Inbox captures a DOI, HTTP(S) URL, or short idea for later explicit
triage. It preserves the exact captured text separately from DOI/display
normalization. Saving, reading, restoring, reviewing, importing, and exporting
never fetch a URL, search, download a paper, open a link, or call an AI provider.
The native and mobile actions open saved captures first, with small English and
Traditional Chinese interfaces. They do not attach captures to a selected paper
or list and do not change the active reader or its drafts.

## Ownership and shared operations

`inbox_item` is a closed v2 root kind with a canonical UUID and no parents. Its
outer authenticated workspace is the sync authority. A payload cannot declare a
workspace, paper, list, source, or capability. Local unbound workspaces use a
persistent device-local lifetime nonce, minted only by an explicit first write.
Readers capture the initial path, native database identity, and database/WAL
witness before worker startup. Worker reads and writes verify the actual binding
and lifetime. A changed workspace or same-path replacement requires explicit
reopening; the service never follows a global database path.

The payload contains only `kind`, exact `text`, `state`, `created_at`, and
`updated_at`. Text is nonblank and at most 2048 Unicode codepoints and 8192 UTF-8
bytes. Kinds are `doi`, `url`, and `idea`; triage states are `new`, `kept`, and
`dismissed`. Timestamps are aware metadata, never conflict authority. Creation
time cannot change inside an incarnation. DOI/URL validation is local parsing
only. Credentials, userinfo URLs, and non-HTTP(S) schemes are refused.

Every explicit mutation uses a durable UUID request and a fingerprint. An exact
retry returns its original receipt; changed content cannot reuse the request.
Optimistic observations compare the actual saved version/incarnation/action.
A stale draft becomes a retained proposal without overwriting the current item.
Ordinary graph conflicts and explicit resolution use the existing shared
operation journal and outbox. A retained proposal is never replayed
automatically. Keeping the current local version records a decision without
queuing another entity operation. Delete retains history; restore is explicit
and creates a fresh incarnation. Equal text is never an identity merge.

## Preservation and compatibility

Workspace backups retain current captures, deleted text, saved versions, and
retained proposals. Sender request receipts and lifetime nonces are archive-only.
Detached restore and explicitly reviewed enrollment copies receive fresh local
and shared lifetimes; they never adopt sender receipt authority. The copied
workspace retains its historical texts locally, while enrollment publishes only
its current roots under fresh receiver operations. Old historical versions are
not manufactured as newly accepted server operations.

List snapshot packages deliberately exclude workspace-wide Inbox data. A
separate bounded one-entry JSON export/import API preserves exact payload text
and creates a fresh receiver item identity. It carries no sender graph or
workspace authority. This API is tested but has no file-picker UI in this slice.

Read projections declare `inbox` only when actual captures, tombstones, or
retained conflicts exist. Projection records are read-only until real shared
history provides edit authority. Old Python and mobile parsers reject the new
kind/capability before committing cursor, projection, or data changes. Mobile
validation is independent, with shared positive and negative contract fixtures.
Final integration must deliberately union Inbox with the newer queue-pin and
reading-position contracts; an unknown capability must keep failing closed.

## Responsive user actions

Native construction, polling, rendering, and result delivery perform no SQL or
hashing. Bounded pages contain at most 256 captures; metadata preflight limits
are 100000 combined rows, 64 MiB, and 16 KiB per stored row. SQL, ownership checks,
conflict resolution, and request hashing run on a worker. GUI delivery checks a
sealed proof with current native file witnesses, captured context, editor epoch,
and draft state. Close drains/cancels an owned worker and preserves a draft until
the user explicitly discards it. Cancellation defaults to keeping the draft.

Mobile captures and per-entry drafts use the same atomic local store as the
ordinary outbox. Repeated clicks and restart/retry do not duplicate a request.
Saving updates only Inbox and a fixed status label, preserving the existing PDF
object, reader selection, and note drafts. Network synchronization remains an
explicit action through the existing connection. Source text is never telemetry
or HTML. Native Qt focus and dialog operations remain on the GUI thread.

## Evidence and limits

The accompanying build handoff records exact beforeimages, final source hashes,
focused Python counts, the complete mobile test count, and actual private
loopback HTTP programs. Earlier staged positives are distinct from the final
frozen-byte checks. No real account, model, research data, external network,
release, publication, or daily workspace was used.

This is an isolated candidate rather than a full-suite or integration claim.
The parent owns contextual integration and the full canonical check. The shell
cache v9 here is unserved and unreleased; integration must choose one coherent
cache version and retain every shell dependency. The native dialog currently
retains unsaved drafts during its lifetime; mobile drafts also survive local
restart. Native process-crash draft recovery is not claimed. Native OS/browser
appearance, screen-reader behavior, and real device pairing remain manual
checks. Ordinary reader opening still has its separately documented legacy
synchronous I/O; Inbox does not add a source-jump path or exercise that gap.
No blocked lineage recovery/export hook is applied by this candidate.
