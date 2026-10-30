# Pins belong to a list membership

A list pin is a research preference for keeping one paper prominent in one list.
It is separate from `ui.offline.*` device-local retention intent and from reading
progress. The domain itself requests neither a PDF download nor an AI provider call.

The shared wire domain is existing `research_content` with
`feature="list_pin"`, `scope={kind:"list",id:list_id}`, `key=paper_uuid`,
`data={pinned_at:timezone_timestamp}` and `source_document_hash=null`. The entity
ID uses the existing deterministic content identity. Parents are ordered
`[list, paper, membership]`; the member ID must be the deterministic list/paper
pair. The member's own retained root incarnations must equal both supplied roots.
Checking only the pair hash or an active membership bit is insufficient.

Removing and re-adding the same pair creates a new membership incarnation. An old
pin remains in history but cannot become visible on that new membership. Pin
creation touches the membership's structural marker, so removal races use the
existing causal/structural conflict rules. Conflicts retain both operations;
restoration remains an explicit action against the current membership.

## Actual desktop actions and transaction ownership

`list_pins.set_pinned(conn, list_id, local_paper_id, on, expected=None)` owns no
commit and uses no global workspace selection. Enrolled workspaces require their
`CaptureConnection`; an ordinary SQLite or trusted journal connection is rejected
before mutation rather than being mistaken for an unbound workspace. It resolves the portable paper,
checks the current materialized membership, and writes through the shared journal
and research projector in the caller's transaction. An optional observed token
rejects a stale target/membership before changing data. A synchronous UI action
observes the current membership under the caller's write transaction.

`Data.set_pin` remains a singleton wrapper. `Data.set_pins` applies a bounded,
deduplicated selection in one transaction, and the existing window action calls
it once. A missing or stale second selection rolls back the first. Repeated
identical activation produces no additional operation, preserves `pinned_at`, and
does not write list order, reading state, notes or provider settings. A failed save
shows a sanitized progress/activity message before any reload or flag update. A
post-commit refresh error separately reports that the pin was saved and needs a
refresh; it does not claim the successful write was rolled back. Existing
pinned-first desktop presentation remains separate from saved collection order.

The explicit current toggle can restore its selected pin with a fresh incarnation.
Raw SQL cannot revive retained tombstones, even when it supplies a current
observation token. Ordinary first-create SQL is captured; delayed edits should
carry the existing observation/expecting boundary. Unsupported raw restoration
retains a candidate or fails without overwriting live research.

## Membership cleanup and schema safety

The narrow `paperfact_pin_membership_delete` SQL trigger deletes only the removed
membership's matching `pins(scope,paper_id)` row. Other lists and legacy queue
pins remain untouched. Local captured SQL cascades record the prior pin and its
delete before the membership tombstone; rollback restores both rows and outbox.
Typed/remote membership deletion also hides dependent pins through graph lifetime
rules and performs SQL cleanup without creating echo operations.

New trusted schema and explicit `capture.install` install this trigger. The
projector verifies its actual closed SQL definition, not merely a trigger name.
A typed pin action can install a missing owned trigger inside its caller's
transaction; rollback rolls that installation back. A same-named different trigger
requires explicit review/repair. No initializer silently overwrites it.

A pre-pin prototype workspace must run the existing explicit schema installation
before receiving pin operations. Missing/changed cleanup schema fails projection
without advancing the cursor. Retry after installation applies the original
history once. There is no new startup migration or automatic production enrollment.

## Baseline, recovery and sharing

Capture uses the shared serializer for every supported per-list pin, with members
before pins. A bounded enrollment plan verifies the actual list, paper and
membership row plus timestamp. `scope="queue"` is reserved legacy state, not a
portable list pin: migrate it explicitly before enrollment. Orphans, invalid
stamps and unexpected cleanup writer definitions are blockers; source rows are
not dropped or normalized.

The existing complete-or-fail recovery archive retains pin SQL, content history
and protocol evidence. Detached restore preserves flags without activating old
device identity. Existing list packages already represent pins, so their format
and capability requirements stay unchanged. Package imports keep the sharing
contract and do not grant a peer's sync identity. Desktop queue-scope toggling
remains local for an unbound legacy workspace.

## Independent mobile reader

Canonical graph projection exposes `member.pinned/pinned_at` and displays a small
localized read-only badge. It does not sort members, change selection or introduce
mobile pin editing. Missing/deleted/recreated membership hides an obsolete pin.
The module is part of the exact static offline shell cache.
The existing adapter-initialized read-only SQL snapshot can include optional pin
fields only for actual matching list memberships; queue/orphan rows are excluded.
Absent fields stay absent for older snapshots. Import validates the boolean and
its timezone timestamp relation.

A snapshot remains read-only evidence. Native canonical member projection rebuilds
member state and never inherits snapshot pin intent. Tests import a snapshot,
apply newer graph history, remove and restore a member, then reimport the old
snapshot: the old pin cannot return. A new explicit current pin operation is
required. Older closed validators reject the new wire feature instead of dropping
unknown history; participating clients must update together.

## Evidence and limits

`tests/test_list_pins.py` exercises actual desktop data actions, concurrent repeats,
atomic selections, exact membership/root closure, stale observations, SQL and
typed cascades, rollback/close, conflict restoration, baseline, recovery, packages
and explicit schema migration. Mobile fixtures check badge rendering, persistence,
unknown/malformed rejection and snapshot/lifecycle interactions. No real account,
research database, network, AI, release or telemetry is used.

This does not finish enrollment: legacy queue/reading-log migration, remaining
file writers, shared maintenance locking, reviewed adoption and physical Windows,
Mac and phone acceptance remain gates. Actual mobile browser appearance is not a
physical-device acceptance result; the badge has fixture rendering coverage.
