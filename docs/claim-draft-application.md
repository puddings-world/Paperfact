# Source-verified structured claim application

2026-11-02, isolated `0.5.0.dev`, unreleased. Local backend evidence now covers
exact-original verification, explicit application, independent recovery, a local
offline peer and another backup. A field-based native editor is now connected
in the isolated integration candidate. Nine [claim CLI/MCP operations](local-claim-review.md)
now share this native boundary, with an atomic private/public retry journal.
This is not installer readiness.

## Native editor candidate

Review changes -> Revise claims opens a pinned, owned session. An editable managed
workspace is required; detached recovery remains read-only. Separate target choice,
field edits, private Save, Verify original and confirmed Apply share the backend
below. Claims, judgment/reason, quotations, page hints and optional reference fields
are editable. Quote edits clear old word boundaries; verification rebuilds them.
Saved variants and papers use bounded pages. Preserved target comparisons are labeled
as the last review; only explicit reselection captures a new target. Generic claim
decisions remain disabled, and previews show human-readable claims rather than JSON.

All database/PDF admission, save and verification work runs off the GUI thread.
Background Save may complete against an earlier text snapshot: its receipt advances
the local revision, but later typing remains dirty and is saved next. A debounce
that expires during admitted work schedules another attempt instead of dropping it. Closing waits
for admitted private work, cancels verification and preserves words after failure.
Host close waits for its owned editor. Cancellation observes the current job event.
The original viewer is shared with text/note recovery and never selects A as primary.

Selected matching native interactions: **60 passed, 20 new**, 263.97s
runner, zero input drift/failures/errors/skips. Actual Qt controls cover both
languages, 980/620px action reachability, saved/recovered editing, late database
replacement and source opening. No installed-device or scholarly-quality acceptance.
[Actions and actual screenshots](testing/claim-draft-application-scenarios.md).
Two supplemental actual-field cases pass without product changes: complete private
add/remove/reference contents and bounded rapid/empty collection controls. Prior
test bodies remain byte-exact; these disjoint checks are reported separately.

Local design evidence (`validated-local`): when an editor receives an old autosave
acknowledgment, compare its exact saved body/request with current fields before
clearing dirty state. A rotating job needs a cancellation callback that observes
the current event. The failing held-save/current-cancel cases and matching corrected
Qt cases are the evidence; this is not a new global skill or tested vendor/runtime rule.

## Shared operation boundary

Use the existing explicit `ResearchReview` receiver-selection/private-draft methods,
then `verify_claim_draft(preview, body, restore_deleted=False, cancelled=...)`,
`claim_draft_report(verified_preview)`, and
`apply_claim_draft(verified_preview, body, request_id=..., confirm_target=True)`.
Run database/PDF work in an owned worker when adding UI/transport adapters.
The default generic text decision continues to refuse structured claim drafts.

Verification reads the actual receiver-owned original A, while the selected
primary B remains unchanged. It validates the complete original baseline and the
exact edited JSON, rebuilds quoted-word locations and claim IDs, and maps only
the receiver identity. Original analysis-input digests remain provenance. Manual
revisions record `backend=manual` and no model; locating a quote does not prove
semantic support. Missing/ambiguous evidence remains explicit.

The returned preview is a process-local capability, not portable authority.
Closed reviews, changed native databases/bindings, changed paper lifetimes,
changed target claims or selected PDFs refuse. Editing again requires another
verification. Failed/cancelled rechecking revokes the earlier permission.
Private storage/restart preserves words and the old base, never an active grant.

## One confirmed transaction

Application commits original-source ownership, the canonical accepted claim
operation, its sync outbox and decision receipt together. Staged file bytes alone
grant no ownership. Receipt-write failure rolls back all research/journal ownership;
the same request can retry. Identical concurrent requests and a lost commit reply
return the original result without duplicate writes. A repeat of an accepted old
decision cannot replace later research. Reusing its request with changed content
refuses. Deleted claims require explicit restoration and a new graph incarnation.

A source retired after verification is rejected before any old source-publication
receipt/cache return. Accepted decision retries still return their saved result;
they do not republish or resurrect anything. Current primary B stays selected.

## Recovery and offline evidence

The actual fixture journey preserves two private interpretations, independently
restores/adopts with the original folder moved away, chooses the new receiver,
verifies A and applies once. A second local reference-service client receives the
accepted claim and both PDFs, queues a note offline, restarts and syncs it back.
Repeating the original Apply leaves that note and the claim intact. Another backup
and detached restore retain the accepted claim, both PDFs and both private variants.
Private drafts and runtime decision receipts do not replicate to the peer.
This is a backend/protocol journey, not native claim editing on a physical laptop.

## Reader repair found by the journey

Reusing the same database path after independent recovery exposed cached portable
paper identities. Reader observations now include native database identity; cache
reuse also requires the current portable paper identity. Two regressions fail
before the fix and pass after, for both equal-data and changed-paper replacements.
Old results lose authority; fresh reads can resolve the new database normally.

## Scope and remaining work

The preceding backend gate passed **231 cases**, including **22 new**,
in 392.92s runner time, with zero input drift/failures/errors/skips.
[Human actions/results](testing/claim-draft-application-scenarios.md).
No older tests were weakened. Earlier failed fixture runs and both reproduced
product defects remain in ignored evidence; historical passes are not summed.

Required next: registered claim CLI/MCP operations, actual sidecar/remote claim
resumption and accepted offline claim-edit convergence. Broader editor/history/source
boundaries, remaining typed highlight/deck recovery, full checks, canonical integration,
production identity/hosting and Windows/Mac/phone packaged acceptance remain required.
No live AI, credentials, deployment, telemetry, installer, commit or release was
performed here. The full v0.5 objective remains open.
