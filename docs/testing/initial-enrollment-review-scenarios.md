# First enrollment after Q&A review

Updated 2026-11-01. Isolated `0.5.0.dev`; unreleased. This adds one required
existing-workspace adapter, not complete arbitrary-workspace enrollment.

## Reader outcome

A researcher may explicitly review and apply an answer that was retained after
its original inputs changed. That creates a `research_chat_review_receipts`
record. Previously the first-enrollment inventory rejected that real table, so
an otherwise supported workspace could not prepare its sync copy.

The copy now validates and preserves this complete receipt privately in
`research_history_archive`. It retains original JSON strings, reviewed text,
question/answer identity, displayed target, graph observations and every declared
original source. Stored database/file paths remain observations. Active request
and review-receipt tables are not recreated in the new workspace. Live accepted
Q&A and its source links enter the existing shared-operation and attachment path.

## Actual actions and required outcomes

| Situation | Action exercised | Required result |
| --- | --- | --- |
| Reviewed answer, current PDF changes | Real prepare/publish-candidate, explicit Review/Apply with repeated request; replace A with B; plan and prepare a new copy and backup. | Exact private receipt and accepted Q&A survive; source SQL and A bytes remain unchanged; no old job or review authority is installed. |
| Independent recovery | Inspect/create backup, restore detached, validate its archived protocol records. | Exact original receipt and required A bytes remain. Detached recovery keeps protocols in recovery_records, not live job tables. |
| Another device continues | Real ReferenceService, journals, blob transfer and peer activation; create a note through an ordinary captured writer and sync back. | Same message/exchange/reply/source identities and exact A at peer; current B remains separate; the peer note returns to the first copy. Private review receipt/request identity does not enter outgoing research. |
| History-only original C | Produce actual earlier C Q&A and later A review, then remove old C live turns/job rows; retain only the self-contained real review receipt. | C remains in the complete backup without becoming live shared research. Missing or replaced C blocks candidate and backup. |
| No path authority | Forbid SQL connections and Path.open while wrapping/validating a receipt. | Complete original row and required hashes remain available without following observed paths. |
| Malformed nested history | Duplicate JSON keys; boolean identities/years; nontext title; unknown fields; wrong result/owner/fingerprint; recompute applicable identity/fingerprint. | Closed nested validation rejects all malformed variants, even where the narrower runtime shape accepts them. |
| Bounds and archive identity | Change an archived body or lower the declared byte bound. | Reject explicitly; no silent truncation or acceptance of a changed record. |
| Cancel, source change or publication failure | Cancel after coverage, alter the source review row during staging, fail final directory publication, then explicitly retry. | No partial output or backup. Source remains exact except the intentional test edit; retry succeeds after publication is restored. |
| Enrolled observation graph | Use real enrolled Review/Apply and vary parent/turn/workspace declarations. | Keep valid declarations; reject foreign targets. Typed synthetic document declarations in this parser control do not claim physical PDF availability. |

## Evidence

Reviewed-QA/history/first-enrollment/recovery integration: **131 passed, 0 failures/errors/skips**, 337.98s pytest /339.39s wrapper on932 unchanged inputs. Bilingual preview/prepare and maintained desktop copy controls: **27 passed, 0 failures/errors/skips**,34.24s pytest /35.69s wrapper on933 unchanged inputs. The exact backend-to-UI delta is three added coverage labels/entries in the dialog and one new UI test file; backend modules/tests are unchanged. These are separate partial gates, not a full app pass. Earlier24new-case selection passed52.70s pytest/54.19s wrapper; it overlaps and is not an extra total. Ruff passes.

The original real-workflow regression failed at `plan.supported` with
`unsupported table: research_chat_review_receipts`. The adapter adds an exact
six-column protocol and forwards it to a pure bounded validator. Runtime review
logic and all prior test files remain unchanged.

New fixture admissions are retained: its first renamed title had an inconsistent
title_key and was correctly refused by lossless projection; the new field was
corrected. A first restore observer looked for live history rather than the
maintained detached recovery_records carrier; its observation was corrected with
the same exact-receipt assertion. A duplicate-context control initially failed
the existing candidate hash before reaching deep validation; it now recomputes
that identity as well as the review fingerprint, without changing refusal.

## Limits and remaining work

These are disposable Windows SQLite/PDF and local ReferenceService scenarios,
not installed Mac/phone, deployed identity/service or live AI/account acceptance.
No model runs during enrollment/recovery/transfer. Research-version history and
other initial-enrollment protocols still require their own integration; generic
review drafts/receipts, capture candidates, file candidates/drafts and integration/
action receipts are not made supported by adding the Q&A review protocol.

Full current-project verification remains required before commit or release.
Do not add overlapping historical pass counts. See the [current status](../status-0.5.0.md),
[initial history contract](../initial-enrollment-history.md) and [full roadmap](../roadmap-0.5.0.md).

Test sources: `tests/test_enrollment_chat_review_history.py` and
`tests/test_enrollment_chat_review_validation.py`; bilingual exact-node explanations
are in `docs/testing/catalog.json`.

The desktop coverage preview also names Q&A review history in English/Traditional Chinese; actual repeated check/prepare controls preserve one complete receipt-bearing copy.
