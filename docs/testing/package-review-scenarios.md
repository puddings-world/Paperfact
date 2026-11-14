# Desktop native-package review scenarios

Status: development integration, 2026-11-14; not a release/device pass.
The maintained full result remains failed at an old activation-stage contract.
No old assertion was weakened, skipped or changed in this iteration.

## Researcher actions

| Behavior | Observable acceptance |
|---|---|
| Inspect and review | Same research SQL dump before and after preview; confirmation is separate |
| Explicit pairing | Search returns actual local IDs; selected IDs survive into the native operation |
| Reuse | A reviewed second import into the selected list does not create a second paper |
| Canceled picker | Existing mapping/preview retained; no new job |
| Changed mapping | Old confirmation disabled and preview cleared |
| Failure and retry | Existing choices retained, confirmation disabled on failure; retry can prepare |
| Repeated review/apply | One admitted worker; final saved research does not duplicate |
| Changed ZIP | Old inspected fingerprint cannot authorize new archive contents |
| Cancel before publication | Exact SQL/outbox rollback; private staging removed; explicit retry works |
| Close at final commit | Session cancellation and native transaction use the same Ticket |
| Close held worker | Dialog stays alive until drain; no result is applied after close |
| Workspace changes at queued delivery | Preview cannot enable Apply in another workspace |
| Commit already won | Original workspace keeps saved research; stale result cannot navigate the new one |
| Inactive-view defense | Simulated inactive graph rows cannot consume the active search limit; this is not a paper-deletion protocol test |
| Long/duplicate titles | Choices are short and distinct, retaining the actual selected ID |
| Native versus legacy | Captured workspaces use review; old unbound constructor/call contract retained |

New cases live in `test_package_review.py` and `test_package_review_dialog.py`.
They use actual fixture databases, packages, native operations and journal state.
Held-worker and failure callbacks simulate timing without provider/paid calls.
Adjacent existing sharing-link, pin-notice and workspace-transfer tests remain
unchanged. Passing these scopes does not certify all app actions or third parties.

## Failure history

Initial new fixture wiring passed a `(path, hash)` tuple as a path and omitted
transitive fixture registrations. These were corrected in new tests; assertions
were unchanged. The first expanded gate found the new factory unnecessarily
passed a language keyword to the legacy injected constructor. Production routing
was corrected to preserve its original call shape; the three old entry tests were
not modified. An additional new fixture first named a nonexistent Journal
method, then correctly encountered the current protocol's explicit paper-deletion
refusal. Both failed experiments are retained. The defensive reader test now
supplies a simulated inactive graph over actual SQL; it neither fabricates an
admitted tombstone nor relaxes the real protocol. Actual paper-deletion retention
acceptance remains outside this fixture's evidence.

Initial bare Qt capture had missing glyphs. The final actual widget capture uses
the same installed pinned fonts and Fusion setup as app startup, with synthetic
research. It was inspected before copying to documentation. No physical Mac or
phone, real researcher database, cloud resource, account or model was exercised.

## Remaining gates

Affected receipts are in the continuation ledger. Old Lineage activation/refusal
expectations still await the owner's response; do not claim a full green gate.
Reviewed scientific replacement/adoption, ambiguous-origin negotiation, maximum-
size performance and installed-device acceptance remain separate work. This UI
uses explicit pairing and refuses unsupported replacement rather than silently
merging by title.
