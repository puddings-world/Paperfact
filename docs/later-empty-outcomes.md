# Recorded empty later-work queries

This slice distinguishes an accepted empty lookup from an overview, an unknown
lookup, and a retryable failure. It is staged in an isolated source candidate;
its handoff receipt, rather than this document, records the exact tested bytes.
It is not a declaration that the release, every workflow, or a scholarly review
is complete.

## What the record means

An explicit existing followup lookup may save `paperfact.later-outcome.v1` only
when its accepted fetch and the complete bounded relevant inventories are empty:
no reference rows, no later-work rows (including unjudged rows), and no existing
overview/manual target. At least one provider must have established an empty
query; an unknown paper or malformed response is not a successful empty query.
The record retains the query UUID, exact query time, lookup inputs, provider
states, policy/input digest, and available/unavailable original observation.

The result is **recorded historical query provenance**. It does not certify that
no citing papers exist, that a service is complete, that the receiver queried a
service, or that any scientific conclusion is supported. External indexes can
change after the recorded query. Refresh remains an explicit operation.

No overview or fake summary is inserted. `followups.done` continues to mean a
real overview. Reads, receipt/import, status display and recovery do not perform
lookup, download, account login or model calls. Existing explicit lookup remains
available. No new model task, account control or paid operation is added.

## Input and source authority

The source owner is the selected existing paper, never a title/hash merge, fake
list, or timestamp. Private captures retain the exact database native identity,
existing binding, parent lifetime, source observation and target observation.
An available original is captured through the maintained document/evidence
reader; the recorded PDF hash is not a bibliographic paper identity. An original
may be unavailable without inventing its bytes or borrowing another paper.

The digest includes the actual lookup metadata/policy, full bounded references
and followups, dive observation and overview observation. New unjudged rows,
changed identifiers, source replacement/appearance, parent recreation, target
edits and native database replacement invalidate pending acceptance/currentness.
Read-only source selection prefers persisted workspace registrations. A global
legacy directory is a fallback only for the same explicit current workspace.
Read-only binding observations require actual persisted workspace/device
agreement; missing capture instrumentation cannot make a bound database unbound.

A receiver can treat the record as settled relative to these recorded inputs
only after matching its current policy/inventories/source and fresh local
parent/target scope. Stale records remain preserved and unknown/pending. The
recorded time is visible provenance, not authority. Native sender job receipts
are archive-only observations and are never resumed or rebound as receiver jobs.

## Scheduling, display and retry

A current typed empty record keeps a paper from repeatedly holding up the night
queue. Worker lookahead checks exact sources before selecting its bounded next
papers. A real failure still supports explicit retry; a raw `overview.none`,
`followups.checked` or cleared JSON-null failure hint never establishes completion.
Publication retries keep the original request result without duplicating rows or
outbox entries. A new explicit lookup captures a new request.

The existing desktop bar uses neutral absence text, a recorded timestamp and
readable provider states, with no completion checkmark or scientific score. Its
worker performs source/SQL checks; delivery adds only a reject-only native fence
while retaining the existing owner/source/view checks. The pre-existing status
scope admission still performs synchronous SQL; this slice does not claim to
rewrite that legacy seam. Mobile similarly says recorded query, and explicitly
labels a different, missing or newly appeared original. Provider unknown means
not established, not zero results. No extra persistent UI control is introduced.

## Portable preservation

`later_outcome` is a closed paper-scoped singleton research-content feature. An
actual snapshot row declares the corresponding required capability; declarations
are a sorted union with Inbox, queue pin and reading position. A previous receiver
must refuse an unknown capability before cursor or persisted projection changes.
No-outcome snapshots/packages retain their previous capability shape.

Full list packages carry the typed row and exact per-paper originals separately
from the current primary. Original A cannot be replaced by current B as the source
of a saved record. Identical PDF bytes and bibliographic metadata do not merge two
paper records or their source ownership. A receiver retains conflicting research
with the existing archive/receipt pattern rather than replaying it automatically.
Unbound imports stage and verify exact bytes before the SQL lock, then require
unchanged native/parent/target/source observations and adopted canonical or typed
retained-conflict ownership before granting a fresh receiver source receipt.
A rollback may leave unowned immutable bytes; it grants no active source authority.
Only this call's temporary stages are cleaned up.

The exact duplicate legacy query timestamp can be omitted from a package/enrollment
view once the closed typed record contains it. The sender database is unchanged.
No typed row, a mismatched hint, malformed data or a real failure does not acquire
this exception. The existing enrolled importer still refuses unsupported legacy
KV caches. Recovery includes the typed row, recorded query history and exact paper
source closure; editable recovery stages fresh ownership in an unpublished copy.

## Human scenario map

| Scenario | Observable protection | Tests |
| --- | --- | --- |
| Accepted empty query, PDF present/absent | Typed record; no overview/model; bounded queue advances | `test_later_outcomes.py`, `test_later_outcomes_portable.py` |
| Prior genuine failure | Manual retry reattempts; old failure assertions preserved | existing `test_deep_analysis.py` |
| Unknown/malformed upstream | No accepted empty completion | `test_later_outcomes_query_admission.py` |
| Held source/ID/inventory/target/parent/native change | No stale accepted outcome | `test_later_outcomes_lifetime.py` |
| Partial schema or caller rollback | Refuse unknown definitions; no implicit repair/commit | `test_later_outcomes_schema.py` |
| Pending status/close/source changes | Neutral recorded label only in current scope; late results ignored | new status/delivery tests and existing `test_analysis_status.py` |
| Package A/current B, same bytes/two owners | Exact originals and independent paper ownership survive | new package/bundle/enrolled-package tests |
| Kept conflict, cancellation, failure/retry | Existing research remains; no partial rows/source authority | new package boundary tests |
| Recovery/first enrollment | History is archival; receiver authority is fresh | `test_later_outcome_recovery.py` |
| Mobile old/future/invalid capability | Atomic refusal; no cursor/outbox mutation | `mobile/tests/later-outcomes.test.mjs` |
| Actual local HTTP and offline restart | Authenticated typed metadata plus exact A bytes; primary B unchanged | `mobile/later-outcome-service-check.mjs` |

## Limits and acceptance still outside this slice

An enrolled workspace with an unmanaged legacy primary PDF is a required open
workflow GAP, not a waived release scope. Complete migration is required before
complete backup; the explicit negative control is retained. The next acceptance
must prove explicit observed migration and backup to a fresh editable receiver
with retained source A/current primary B and unavailable-source controls. Current
managed backup tests prove current A and unavailable sources; the separate A/B
package and HTTP controls do not prove that recovery combination.
The managed-primary flow and source preservation must not be described as support
for every legacy/file-history workflow. Nonempty/other compound history scopes
remain unsupported by this finite enrollment adapter. This work does not activate
grounded lineage or apply its two previously rejected recovery/review hooks.

All provider/transport tests use synthetic fixtures. Production hosting/static
allowlists, TLS/identity/device acceptance, real service response behavior and
index completeness require separate acceptance. No owner application/data or real
account/model is exercised. No complete release/full-suite claim follows from
this focused handoff; the parent integration owns the maintained full check.

Candidate development lesson: an accepted empty outcome needs typed source/input
scope independent of generated prose. The local evidence belongs with this
scenario map and receipt; no new global skill rule is promoted here.
