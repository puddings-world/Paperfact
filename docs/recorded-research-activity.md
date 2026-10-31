# Recorded research activity

The desktop Research activity window and mobile Activity dialog are bounded,
read-only views of the existing received journal and current local projection.
They do not add a sync kind, table, last-opened timestamp, viewport record, model
call, account lookup, transport operation, or scheduled research job.

## Recent changes

Recent changes reads at most the newest 200 received events and shows up to 50
items in descending received-sequence order. It hides accepted echoes from the
current device, while retaining conflicts from either device. It distinguishes
current locally applied changes, accepted history, accepted changes awaiting
local application, retained conflicts, and file manifests awaiting verified-byte
binding. Resolved conflicts remain historical records with a resolution label.

An applied-file marker is labelled only as a recorded binding whose availability
must be checked when opened. Metadata or a persisted verified flag alone never
produces a “PDF downloaded” claim. Passively reading activity does not follow source paths, read PDF bytes,
initiate a download, or activate received files. The explicit desktop passage
action verifies the already-loaded local PDF on a worker.

## Continue reading

Continue reading suggests at most 20 papers from current, active, applied received
`note` and `reading_state` puts. It includes this device's received changes. It
uses received sequence rather than a guessed reading time, a filename, or UI
render time. The newest eligible record for each paper is shown.

Its coverage label explicitly says **recorded reading and note updates**, not the
last paper opened or last PDF page. Local changes not yet received, local opening
history, legacy delivery logs and an unobserved native PDF viewport are not
substituted for those records. An unenrolled database stays untouched and reports
that received activity is unavailable.

Open paper is an explicit action. Desktop navigation opens a managed paper through
the existing reader, without marking delivery, persisting a new opened-at time,
or starting optional background analysis. If that paper is already loaded in the
same database, the action retains its source and viewport. Active work, draft
text and pending passage selections block navigation rather than being discarded.

Locate saved passage is a separate desktop action for a managed source and an owned note with
an unchanged source-pinned anchor. It requires the exact database, paper owner,
current and loaded PDF hash, the actual captured source owner, and the exact saved
note anchor. A worker verifies those semantic and byte proofs; GUI delivery checks
the captured reader epoch and object identities plus native database/source versions.
It only locates in the reader already open; it never loads another PDF and queues
a delayed jump. A new current PDF does not silently replace a retained old source.

Mobile can open a source-pinned saved note only when its paper's matching current
PDF is already loaded. It opens the saved note, preserving the PDF object, and
does not claim to move the native viewer's page. A retained draft for that note
blocks this action even after restart. Source replacement, stale parents, a
connection/workspace switch, close, or newer local work invalidates pending actions.

## Boundaries and verification

The desktop reader opens only the existing selected SQLite database in read-only
transactions, validates its durable binding and file identity, caps input bytes
and parent closure, and explicitly closes every handle. It validates canonical
received receipts before projecting them. Construction captures only the resolved path, file identity and native DB/WAL
witness, before scheduling the first worker. SQL binding capture, bounded reads,
selected-record revalidation and source hashing run off the GUI thread. The first
worker rejects an intervening same-path rebind; a failed initial read cannot
establish a replacement binding for retry. Results are immutable sealed JSON
snapshots. GUI polling and delivery use native metadata only. Any changed DB or
nonempty WAL invalidates the proof; absent and zero-byte WAL both mean no frames,
which permits SQLite read-only open/close without adopting a newer content witness.
A stale report requires explicit refresh; a changed initial binding requires reopen.
Closing the dialog or owner, restart and update paths retain a running worker
until it has stopped. Both dialogs use plain text and bilingual English/Traditional
Chinese copy, with keyboard-accessible actions and duplicate-action guards.

Tests cover real journal materialization, own echoes and retained conflicts,
metadata without bytes, sequence ordering, malformed/oversized receipts,
source/note ownership, database replacement with real closed handles, drafts,
failure/retry, duplicate clicks, queued GUI delivery races, close and workspace
switches. The activity service fixture compares the independent Python and mobile
reports over the real typed HTTP service, then exercises own note/conflict events,
source A to B replacement, deleted-note fallback and offline reopening.

This companion slice does **not** implement the research Inbox, a general
cross-device viewport/page-resume record, or physical iPhone/Android acceptance.
Those remain separate release gaps. It does not replace the full project gate.

## Responsive desktop proof boundary

The saved-activity read, resolve, source preparation and delivery paths add no SQL
or PDF hashing to the Qt thread. Native focus/open callbacks stay on Qt. The
existing ordinary `MainWindow.open_anywhere` / `ReaderPage.load` implementation
still performs synchronous reader I/O; that is a separate maintenance gap, not a
claim of this slice. A real ordinary-reader integration test records that boundary
while asserting unchanged notes, queue/reading records, sync operations, delivery
state and opened-at state. Capability-seam tests cover the new native callback
contract separately from the real managed-PDF ownership/hash tests.

Regression tests prohibit SQL and hashing on GUI construction, polling, rendering,
source activation and prepared-result delivery. They include real source owners,
notes, parent incarnations and device binding, delayed first reads, nonempty WAL
and checkpoint invalidation, reader/view/source replacement, drafts, cancellation,
closing with an active source worker and duplicate activation. Accepted close must
hide the native dialog and release Qt modality; a disposed flag alone is not
sufficient. No real account, model, network service or research workspace is used.
Physical desktop/phone interaction and the full project check remain separate gates.
