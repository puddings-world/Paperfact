# Legacy queue pins

Queue pins have a typed portable representation independent of lists, daily queue
rows, PDF versions and device-local offline retention. The implementation and
fixture contract below cover this capability; a release still requires the
combined whole-project gate and separate physical-device acceptance.

## Representation and current writes

A pin is `research_content`, feature `queue_pin`, paper scope, singleton key
`main`, closed data `{pinned_at: <timezone-aware timestamp>}`, null source hash
and exactly one current paper parent. Its identity uses the existing deterministic
content-ID function. It preserves SQL `pins(scope='queue', paper_id, pinned_at)`
verbatim, including an orphan paper with no queue row or list membership.

`TABLE_FEATURES['pins']` remains `list_pin`; queue rows dispatch explicitly before
that default. Existing list pins keep their ordered list/paper/membership closure
and membership cleanup. Queue pinning never creates a list, membership or queue
row, and never renames an existing list.

The actual `list_pins.set_pinned` action observes its target inside the caller's
transaction, accepts an optional loaded observation, refuses stale owner/target
state, and treats repeated on/off intent as a no-op. Explicit current intent can
restore a pin tombstone with a fresh incarnation; arbitrary SQL cannot revive it.
An actual list whose ID is `queue` remains allowed: its membership removal cannot
delete the global queue pin. The maintained cleanup trigger excludes that reserved
pin scope. Runtime pin intent and receive projection require the safe trigger.
Only the exact recognized prior cleanup SQL can be migrated at explicit installer
boundaries, within the caller transaction; unknown SQL, including changed literal
case, is never rewritten. Read-only source inventory separately recognizes exact
old-or-new SQL so a fresh safe editable copy can preserve an old unbound source
without changing its bytes. This recognition does not implement an in-place UI
upgrade: an unsafe old runtime needs explicit installation or the copy path.

Projection requires the exact materialized paper incarnation. SQL and outbox
writes roll back together. Ordinary unbound writes retain their existing behavior.

## Packages and preserved receiver curation

List packages include `queue_pins` only for papers actually exported in that list.
Each row is exactly `{paper_id, pinned_at}`. The subset has at most 10,000 rows;
owners are nonempty strings of at most 4096 UTF-8 bytes. Oversized exports fail
before creating a package. Nonempty rows require the `queue_pin`
package capability; older readers reject the declared capability. Without queue-pin rows this extension does not change the package format. Whole-workspace backup preserves orphan pins outside
any list; list export does not invent membership to include them.

Fresh unbound and enrolled imports preserve the incoming timestamp. If a receiver
already has a different pin timestamp, its current pin wins even with Replace.
The report says it was preserved, and the original incoming timestamp, receiver
timestamp, original owner alias, receiver alias and exact raw package SHA are
retained atomically as closed archive-only `queue_pin_import_v1` records in the
existing validated history archive. They never become current pin or replay
identity. Before retention, existing plus incoming deduplicated archive records
must remain within the shared 10,000-record / 64 MiB limits; failure leaves the
caller transaction unchanged. Equal imports are no-ops; identical conflict retries deduplicate, while
a later different conflict adds another immutable record. The existing completion
message appends one preservation notice; no extra modal or job is introduced.

These records survive restart, independent backup, detached restore, editable-copy
preparation and repeated backup/adoption cycles. Editable copies receive fresh
workspace/device/parent authority; historical receipts remain private archive
content. Package native-version checks bind the raw SHA to the inspected snapshot.
Unknown protocols, fields, owners, malformed timestamps and unsupported list-pin
scopes remain blockers.

## Read-only snapshots and mobile

A SQL read projection may include `paper.queue_pin = {pinned_at}`. Only projections
that actually contain a queue pin declare the closed top-level
`required_capabilities: ['queue_pin']`. Missing, extra, duplicate, unknown or unused
capabilities are rejected. An actual pre-extension validator rejects the new
marker before its transactional importer persists anything. With no queue pins,
the old top-level shape remains unchanged.

Mobile independently validates the closed wire format and strict timestamp
spellings, shows a saved read-only pin without creating queue/list state, and
retains its separate list-pin display. A known canonical put overrides stale
snapshot data; a typed canonical deletion suppresses it. No new mobile pin writer,
AI call, credential access or upload is added. Existing shell modules contain the
change, so there is no new static module to register; the parent release owns the
shared service-worker cache-version change.

## Regression evidence

- `tests/test_queue_pins.py`: real two-peer writes, raw observed capture, explicit
  restore, epoch guards, rollback, simultaneous repeats, closed wire goldens and
  side-effect-free SQL snapshots.
- `tests/test_queue_pin_packages.py`: actual older-reader refusal, fresh imports,
  receiver curation, immutable history, changed package refusal, storage rollback,
  retry and repeated recovery/adoption.
- `tests/test_queue_pin_migration.py`: fresh initial copy and two independent
  backup/adoption cycles, orphan pin preservation, malformed scope/time/owner
  refusal before output creation.
- `mobile/tests/queue-pins.test.mjs` and the actual authenticated loopback fixture:
  Python/mobile golden agreement, offline serialized reopen, deletion/restore,
  idempotence, no mobile outbox, strict snapshot capabilities and saved display.
- `tests/test_bundle_pin_notice.py`: one concise bilingual notice, zero-preserved
  compatibility, malformed report refusal and duplicate/failure-retry delivery.

The former valid queue-pin rejection fixtures intentionally become positive
preservation/atomic-publication assertions. Separate missing-owner, unknown-scope,
naive-time, malformed-row and unsupported-protocol negatives remain. In particular,
`test_unsupported_research_write_rolls_back` now has a supported queue-pin atomic
commit case plus a separate malformed queue-pin rollback case. This is the approved
new capability, not a relaxation of invalid input handling. Paper deletion itself
is still outside the existing graph protocol; changed-paper epoch fixtures verify
stale refusal, while real pin deletion/restoration is exercised end to end.
