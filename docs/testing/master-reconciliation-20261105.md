# Master reconciliation and Mac delivery gate — 2026-11-05

Current local ancestry check, 2026-11-13: `master` at `1b44466` is an ancestor of
`develop/0.5` at `aa4b30e`; `git rev-list --left-right --count develop/0.5...master`
returns `84 0`. No local maintenance commit is missing from the development branch.
This read-only check did not fetch or establish the latest remote state. The
pending-merge narrative below is historical; packaging and installed-device gates
remain unfulfilled unless the current status records separate acceptance.

Remote master was verified and fetched as `1b44466a2aaf5a3ea17a3eba16f27777f0507a36`.
No remote `feature/0.5-sync-foundation` existed at that check. The isolated candidate
has a pending merge through `8bc4a3b`; the subsequent `docs/ai-setup.md` change from
`1b44466` is already in its working tree. This is not a completed merge commit.

## Reconciled citation behavior

The previous full gate stopped at 1,157 passes because maintenance HTML citation
tests addressed removed private fields. Their observation/activation helpers now
operate actual native cards. Stored-row assertions, obsolete-card rejection,
cross-paper modal saves, cancellation/retry, duplicate submissions and late
workspace callbacks remain covered. RichView body/scroll guards are exercised on
the real RichView independently; six legacy action-URL injection shapes are
rejected through native label link events. The old browser frame probes are
replaced by native projection lifetime checks. A native storage failure keeps its
editor draft and allows Save retry; it is not expected to escape as an exception.

This port exposed an actual regression: a removed-but-not-yet-deleted card could
still edit after sorting. A side-specific card epoch now revokes old callbacks
without revoking the map or persistent toolbar. RED evidence:
`citation-native-port-red-v2` (2 passed / 1 failed). The corrected selection then
passed 46 cases (`citation-native-port-fixed`), with privacy/Ruff and no drift.

The map suite exposed a dropped master operation, `lookups_running`. Restoring it
also restores master's whole-analysis admission guard for outstanding citation,
later-work or graph children. Queued fitting now refuses a closed/deleted pane.
All 83 selected native/map/admission/desktop-choice cases passed in 55.92 seconds,
with privacy/Ruff and no drift across 1,171 inputs:
`citation-master-admission-20261105`. This is a focused gate, not release approval.

An AST inventory compared additions from the common ancestor to master against
the candidate. Missing private names alone are not missing functionality: examples
include extracted translation/thumbnail controllers and the intentionally native
citation renderer. Such inventory is a triage aid, not proof of full parity.

## Delivery sequence

Run a frozen full `scripts/check.py` gate; fix failures without weakening behavior.
Then complete the merge ancestry through fetched master, preserve independent
canonical documentation edits, commit the tested candidate, and push its feature
ref. Dispatch the existing Release workflow manually on that exact ref (no tag).
Only deliver the Mac arm64 DMG once its build/packaged acceptance succeeds, with
commit identity, SHA-256 and report. A manual workflow does not publish a release.

At this checkpoint no merge commit, push, Actions dispatch, Mac artifact, physical
Mac acceptance or production synchronization deployment is claimed. The daily
research database and installed app were not used by the tests.

## Additional maintenance compatibility

The first Nov 5 full attempt was deliberately interrupted after 569.91 seconds,
with no source drift, when static comparison found two further omitted behaviors.
It is not a full pass and has no complete case count.

Legacy highlight-link callers again cache answered-but-empty results and only
forget them on explicit retry. Typed v0.5 publication retains its stricter rule:
an empty/malformed refresh cannot erase a previously saved, source-bound result.
The producer remains free of global storage writes.

An unanswered question can again be copied into an editable draft without an AI
call. Sending replaces the old unanswered question and appends the new one in the
same transaction, after verifying the captured conversation and source. A failed
append rolls back the deletion. Switching papers drops replacement authority;
rapid repeated submission remains one job. A completed/retained answer cannot be
silently replaced by this path. Queued UI projection lag is handled using the exact
owned question receipt, not arbitrary current rows.

Focused `editable-retry-v2-20261105`: 15 passed, zero failures/errors/skips,
50.03 seconds including privacy/Ruff, 1,172 frozen inputs with no drift. This
selection includes four new cancellation/switch/repeat/rollback cases plus the
existing maintenance retry and empty-cache/typed-publication cases. A subsequent
workspace-path guard was added before the next full gate. No existing assertion
was weakened. This focused result is not a release gate.

The second full attempt was interrupted after 525.48 seconds (zero input drift)
for a sync transaction contract review; it is not a completed full gate. The
ordinary enrolled retry and rollback tests already passed before the additional
hardening, so no red regression is claimed for that observation-scope review.
The shared delete helper now keeps its observation context active through commit,
both for standalone deletion and the atomic edited-question replacement.

`editable-retry-integration-20261105` passed all 93 selected cases, with zero
failures/errors/skips, in 240.02 seconds including privacy/Ruff. All 1,173 frozen
inputs stayed unchanged. It covers both new desktop retry tests and enrolled
deletion/new-question journaling, plus the existing research-chat, reader-scope,
link caching, producer and wrapped-JSON publication suites. These 93 include prior
focused selections; counts must not be added together as unique coverage.

## Core-claim note cards

The third serial full gate completed unsuccessfully: 1,318 passed / 1 failed /
zero errors or skips, 2,165.88 seconds including the wrapper, 1,173 inputs with no
drift. The failure was a genuine omitted maintenance feature: the Notes tab's
core-claim generation button and AI claim card label, not just a renamed test API.

The entry and labels are restored. Desktop generation captures its original
workspace owner, verified PDF, provider connections and model before background
work. It rechecks quote positions through the existing PDF highlight locator,
including cross-line hyphenation. Changed source/highlight/paper inputs refuse
publication; manually edited note cards survive regeneration. Deleting untouched
generated cards and adding replacements share an observed transaction in enrolled
workspaces. The normal activity runner provides progress and prevents teardown
while a job is active. Duplicate clicks, switching paper, failed model calls and
failed launch are covered. Compatibility callers outside this desktop scope are
unchanged.

The maintenance UI test retains its original visible-content/source-link assertions;
it now waits for the actual AskRunner and ReaderPreparation instead of the removed
OffThread/prepare fields. The isolated note-card rendering fixture supplies a no-op
claim-toolbar refresh; separate real-reader tests exercise that toolbar.

`core-claim-parallel-v4-20261105`: 44 passed, zero failures/errors/skips, 45.70s,
1,175 frozen inputs with no drift. After reusing the canonical PDF locator,
`core-claim-source-final-v2-20261105`: 13 passed, zero failures/errors/skips, 29.61s,
same input count and no drift. These selections overlap and must not be summed.

Local acceptance tooling now has pytest-xdist 3.8.0 / execnet 2.1.2. The full
check remains scripts/check.py; PYTEST_ADDOPTS supplies four workers, loadfile
distribution and zero worker restarts. Each file stays in one process, and the
existing tests/conftest.py creates each process's disposable default workspace.
No cases or assertions are skipped. This tooling was installed only in the local
development environment; it is not a new application runtime dependency. A failed
initial parallel adapter ran zero tests; it was removed in favor of the project's
existing isolation. The new parallel full gate is still required before commit.

These fixes reuse the project's captured-owner, observed-transaction and canonical
source-locator patterns. No unverified global skill rule was promoted.


## Background question-card parity

The first parallel full gate ended with 345 passes and one failure in 254.92s;
1,175 frozen inputs, no drift, privacy/Ruff green. The existing reader-contract
test found that background rendering omitted the restored editable-question retry
link. The renderer now includes it and appends pending-receipt actions without
overwriting it. Existing exact HTML assertions were retained.

`saved-retry-render-20261105` passes 84 cases in 134.92s, zero failures/errors/skips,
privacy/Ruff green and no input drift. This includes bound/unbound saved readers,
both rich/plain output and editable retry transaction tests. Counts overlap earlier
selections. The next full gate is `v05-delivery-full-parallel-v2-20261105`; its
result is pending, not implied by the focused pass.


## Remaining producer-contract decision and complete audit

`v05-delivery-full-parallel-v2-20261105` ended with 844 passes / one failure,
zero errors/skips, 484.62s and no input drift. Master intentionally supplements a
missing close reading after a deep dive; two legacy producer tests assume the
whole workflow makes only one model call. Both bound and unbound variants expose
the mismatch. The owner was asked whether to preserve master's supplemental
reading and update the expected per-producer call counts. No existing assertion
has been weakened or changed while that decision is pending.

The first keep-going audit was explicitly interrupted after 423.28s to increase
parallelism from four to twelve isolated workers on the 16-logical-core host.
It is not a completed gate; the interrupted child report still says running and
must not be treated as success. The authoritative terminal wrapper records failure.
The replacement is `v05-delivery-full-audit12-20261105`. A local pytest hook only
disables first-failure stopping and prints failures as they occur; failure exit
codes and all test cases remain intact. No application source changed for this.

Independent frontend validation: 24 passed, zero failures/cancelled/skipped/todo.
Independent mobile validation: 535 passed, zero failures/cancelled/skipped/todo;
all service-check subprocesses in mobile/check.mjs exited successfully (111.33s
for the mobile stage). Receipts: delivery-web-20261105-result.json and separate
frontend/mobile logs under ignored build/. These are not a full-check pass and
do not establish real Mac/phone or hosted-service acceptance.

GitHub master was rechecked during this run and remains
`1b44466a2aaf5a3ea17a3eba16f27777f0507a36`. No candidate commit, push, release tag or
v0.5 Mac build was performed while the gate is red.
