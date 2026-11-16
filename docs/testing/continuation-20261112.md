# Development continuation — 2026-11-12

## Current workspace and ownership

The former temporary integration checkout no longer exists. Current integration is `Paperfact-develop` on `develop/0.5`, initially at `de7ad9d`. The original `Paperfact` checkout remains separate. Preserve uncommitted job-tray and concurrent Q&A/child-launcher changes; they are not part of the inventory fix below.

## Verified change

The collection-only inventory inherited outer PYTEST_ADDOPTS. A caller's execution/plugin options can then prevent collection in the child interpreter. Three added regression cases failed before the fix: success/error environment restoration and a real subprocess whose test body must never execute. The collector now temporarily removes outer options and restores the original value in its finally block; existing source-selection and collection-only tests remain unchanged. README documents this isolation.

Official focused check: `python scripts/check.py --profile focused --python tests/test_test_inventory.py` — privacy scan and Ruff passed; 15 tests passed in 2.72 seconds, 9.7 seconds overall. The initial reproduction using an outer `-n` failed before entering the intended test because this worktree has no xdist plugin; it is not counted as a product regression. The three dedicated cases are the actual before/after evidence.

The official complete `python scripts/check.py` is running, log `build/full-check-20261112.log`; privacy/Ruff passed, no terminal Python result yet. Source edits from another session were observed during this interval, so this is not a frozen release receipt. Revalidate affected inputs before claiming final integration or committing. No commit, push, release, data migration or deployment was performed by this continuation.

## Automatic sync truth and next work

`desktop/continuous_sync.py` already implements explicitly enabled session-local background sync, journal-change debounce, polling, offline backoff, cancellation and connection-generation invalidation. `remembered-sync-connection.md` describes safe native-vault persistence. Saved connection loading does not authenticate or silently authorize uploads. These are implemented local paths, not evidence that hosted onboarding or installed-device acceptance is complete.

Next: execute the real connection -> enable -> local edit -> offline -> reconnect journey against two isolated workspaces; improve the UI where that journey fails. Keep production identity/HTTPS hosting, native credential-store prompts, Windows/Mac/phone physical acceptance and representative offline-file closure as explicit external gates. Never test these against the owner's only research copy.

## Claude coordination

Please keep this worktree's unrelated edits intact. Inventory changes are limited to `scripts/collect_test_inventory.py`, `tests/test_test_inventory.py` and the README note. Check the live complete-check process before starting another whole suite; a log alone is not proof of liveness. Continue shared integration on develop/0.5 and record exact test receipts rather than inheriting the stale November 5 status header.

Reusable lesson review: this is a scoped test-inventory isolation fix; no new global skill rule is warranted. The focused result is not a complete-check or release guarantee.

## Legacy note upgrade — 2026-11-12

A new two-workspace HTTP/controller journey reproduced a real receive failure:
plain note operations omit creation time, so receivers assign different local
timestamps. The first captured rich edit then failed on the original peer with
`Note creation identity cannot change` although its stable note ID and paper
were unchanged. The remote operation had already been accepted; local research
remained intact and the controller paused.

The rich-note writer now permits a one-time timestamp adoption only before a
rich projection marker exists, after the existing plain-note adapter verifies
paper, original local timestamp, kind and absent anchors. Both local note and
identity mapping change in the caller transaction. Existing rich notes retain
the immutable-creation guard; anchored/non-text legacy notes cannot use this path.
A new negative test confirms rich timestamp replacement is rejected without
altering saved content (1 passed, privacy/Ruff green). The broader journey and
content/capture/research selection is still running; do not claim it passed yet.

New tests were added and the writer changed after the ongoing whole-suite process
started. Its result cannot certify these final inputs; a subsequent complete gate
is required before commit. Other sessions also changed integration files during
the run. No source change, credentials or real research was uploaded.

Terminal focused evidence: `build/note-upgrade-focused-20261112.log` records
68 passed in 129.14 seconds (135.5 seconds including privacy/Ruff), including the
actual two-controller HTTP offline/restart/retry journey and unchanged existing
content/capture/research guards. The separate rich-identity negative regression
passed 1 case in 2.80 seconds. These selections do not overlap. No full-gate,
installed Mac, hosted endpoint or physical-device success is claimed.

## Conflict and detached recovery journey

The new `test_joined_workspace_conflict.py` uses two independently bound databases
and the reference authority. After one shared rich-note baseline, each side edits
offline. Synchronization preserves the competing text in an unresolved event,
keeps the canonical text available, and exposes one conflict. A full backup made
at that point restores both canonical content and archived competing content
without restoring the old device identity. An explicit combined interpretation
then reaches both peers; retrying the same resolution and sync adds no events.

Official focused check: `build/joined-conflict-recovery-v2-20261112.log` — privacy
and Ruff passed, 1 case passed in 10.51 seconds, 19.0 seconds overall. Its earlier
version without backup passed separately; these are overlapping cases, not two
independent acceptance counts. The first added backup assertion incorrectly
queried active sync tables in a detached restore. It was corrected to verify
`recovery_records`, matching the established archive contract; production restore
behavior and existing test assertions were not changed.

Limits: this conflict case begins from a shared rich baseline. Simultaneous first
legacy-to-rich upgrades with independently generated timestamps remain a separate
scenario to verify. Native installed-device, production identity/hosting, verified
attachment availability for a representative trip, and mobile acceptance remain
open. No release or broad performance claim is supported by this focused check.

## Concurrent first legacy upgrades — supersedes the limit above

The two-workspace conflict/recovery case now runs twice: once with a shared rich
baseline and once starting with the legacy plain note. The receiver's clock is
fixed to a different year to make the legacy timestamp divergence deterministic.
The legacy case reproduced the creation-identity failure after both sides had
already installed rich projection markers.

The writer now checks the verified birth receipt indexed by incarnation. Only a
matching plain-note birth (same workspace, stable note ID, paper and put action,
with the old two-field payload) proves that creation time was never a portable
identity field. Such notes can adopt the selected version's timestamp after the
current local mapping is verified. Native rich births still reject creation-time
replacement. No new protocol table or weak timestamp-only fallback was added.
Stable note UUID, incarnation and parent remain the cross-device identity.

`build/concurrent-legacy-upgrade-green.log`: privacy/Ruff passed, 4 cases passed
in 15.11 seconds (20.1 seconds overall). Includes both conflict/backup/resolve
variants, offline restart/retry and the native-rich negative guard. These overlap
with previous focused receipts; do not add counts. Existing content/capture/
research regressions are being rechecked after this final writer change.

Shared integration HEAD advanced to `aa4b30e` during the ongoing full check. The
new commit belongs to the other session; its changes are preserved. The live
whole-suite handle remains running, but its evolving inputs do not establish a
frozen release gate. Require an agreed freeze and complete validation before
committing this continuation or publishing a candidate.

Final writer regression selection: `build/legacy-origin-regression-20261112.log`
records privacy/Ruff green and 67 existing cases passed in 83.31 seconds, 89.9
seconds overall. This selection excludes the four new journey/identity cases;
combined, those two selections cover 71 cases on the revised writer. They are
still partial checks, not complete project, platform or deployment acceptance.

## Attachment-aware automatic-sync status

Automatic sync previously chose its idle/poll schedule from metadata counters
only, discarding the attachment result. A new visible-panel regression reproduced
`idle` while the worker reported two pending attachments.

The controller now retains closed attachment counters in independent status
snapshots, shows concise Files pending / Retrying files footer states and detailed
pending/failed counts in the connection panel, and explicitly asks for separate
offline verification. Incomplete file work schedules the next bounded pass;
attachment failures use capped backoff. Successful later passes clear that state.
Repeated timer events cannot start duplicate jobs. This does not certify every
required file is readable offline: that remains the workspace file-check action.

The first focused run stopped at two new line-length errors, which were corrected.
The affected controller/UI/real-file selection is running in
`build/attachment-status-green-v2.log`; no passing count is claimed yet. All
changes remain uncommitted pending a coherent complete gate.

Attachment status terminal evidence: `build/attachment-status-green-v2.log`
records privacy/Ruff green and 27 tests passed in 66.33 seconds, 99.9 seconds
overall. Includes both pending/failure visible-panel cases, existing controller
cancellation/reconnect/revocation tests, actual PDF byte transfer/version binding
and editable deck/figure/speaker-note transfer. Status cases simulate incomplete
attachment summaries over real metadata sync; file-transfer cases use fixture
bytes and authority. No production endpoint or native Mac acceptance is claimed.

## Mobile integration and actual browser acceptance

The official focused mobile gate passed: 535 Node cases, zero failures/skips/
cancellations, and every Python HTTP program invoked by `mobile/check.mjs` exited
successfully. Overall 80.1 seconds; log `build/mobile-integration-20261112.log`.
This covers real fixture authority/engine interoperation, not hosted production.

Fresh headless Edge profiles then passed eight cached-workspace/IndexedDB startup
groups (`build/mobile-browser-startup-20261112.log`). The documented actual-PWA
mode, with `PAPERFACT_NOTE_SERVICE_PYTHON` and `PAPERFACT_TEST_SCREENSHOTS`, also
passed (`build/mobile-actual-pwa-20261112.log`). It verifies atomic outbox/reopen,
UI drafts/focus, static-only service worker, verified offline deck rendering, QA
pairing, automatic cached-scope reload, one queued note, explicit reconnect and
continued desktop/mobile edits. The structured result reports two HTTP/PWA
scenarios, no new restored-page research requests, one authentication request
initiated by the outgoing page that completed during reload, and no errors.
These are distinct observations: do not claim all network activity was zero.

Inspected 320px Traditional Chinese and 390px English actual-app screenshots:
main actions and note text are readable; the tab row scrolls horizontally while
the page itself does not overflow horizontally. A synthetic 390px image is now
under docs/images and linked from README. Screenshots do not establish physical
phone, installed standalone, accessibility or storage-eviction acceptance.

An earlier invocation additionally requested the positional demo screenshot
output. All functional assertions passed, but the subsequent `Page.navigate`
command timed out. That optional demo-navigation capture remains unresolved and
is not counted as a pass. Source inspection shows this navigation follows an
intentionally retained dirty draft and the app has beforeunload protection;
the actual browser dialog event was not captured, so this is not a proven cause.
No harness timeout, assertion, verifier or app draft protection was weakened.
The documented actual-PWA screenshot mode succeeded without modifying code.

The current status header was refreshed from its stale November 5 description.
Full project/three-platform gate, production hosting/identity and installed-device
acceptance remain open. No automatic consent or real credentials were introduced.

Documentation/distribution contract profile passed 46 cases in 1.65 seconds,
6.2 seconds including privacy/Ruff (`build/docs-review-20261112.log`). This profile
does not replace the live complete check or certify the development installer.

## One-paste setup — 2026-11-13

Added a masked one-paste connection input and guarded background parsing using
existing Connection.decoded validation. No new protocol, credential issuance,
vault write, network request or automatic-sync consent is introduced by loading.
Successful load replaces manual fields and stops an old verified route; malformed
input preserves fields. Input clears on admission and on close/disconnect.
Existing explicit verification, per-device binding and join behavior remain.

The new test failed before implementation with the absent UI entry. The first
implementation check stopped on one new line-length error, corrected before
behavior validation. Official focused gate `build/connection-details-green-v2.log`
passed 25 cases in 49.63 seconds (52.9 overall), privacy/Ruff green: 8 new setup
cases plus 17 existing connection cases. Covers normal verification without
implicit requests, empty/malformed/duplicate/oversized input, repeated activation,
held parsing with cancellation, close and workspace replacement, plus existing
join/auth/no-AI checks. These are fixture credentials and authority only.

Service-issued records are private, not public pairing links. Hosted login,
credential issuance UI, production deployment and installed Mac acceptance remain
open. The updated connection guide records the versioned shape and sequence.
The live whole-suite process remains un-restarted; these changes occurred after
its start and still require a coherent complete gate before commit/push.

One-paste integration follow-up: the remembered-connection UI, progressive setup,
automatic-sync and attachment-status selection passed 37 cases in 55.89 seconds
(59.1 seconds overall), privacy/Ruff green. Log:
`build/connection-ui-integration-20261113.log`. This overlaps earlier controller
receipts; do not aggregate it with those counts.

An isolated offscreen Qt preview initially omitted app font initialization and
failed temporary cleanup while fixture objects remained referenced. It was not a
visual pass. After applying the same font setup as the app and releasing the
fixture objects/deferred deletes, preview generation and cleanup exited zero.
Inspected empty and loaded setup screenshots at 680x690: readable labels and
controls, no horizontal clipping, masked credential and visible explicit verify
button. Images are in ignored build/connection-details-{empty,filled}.png and
contain synthetic data only. Native installed Mac rendering remains unverified.

## Reference administration and terminal gate — 2026-11-13

Added `paperfact sync-admin init|issue|serve` with explicit dedicated state and
private output paths. Existing unrelated research directories and output files
are refused, valid issuance retries reuse one device, and output flush failure
rolls enrollment back through a trusted before-commit sink. The entrypoint serves
literal loopback only. It does not deploy a cross-machine HTTPS service or create
an OAuth/production account flow. POSIX output mode and Windows inherited-ACL
limits, crash windows and full flags/API are documented in sync-service-admin.md.

Official authority/admin gate passed 46 cases in 2.52 seconds (5.6 overall),
privacy/Ruff green; includes actual console/HTTP binding, no default research
creation, disk-failure retry and graceful listener closure. Log:
`build/sync-admin-integration-20261113.log`. New command docs/distribution profile
passed 46 cases in 1.26 seconds (3.9 overall); this is a different selection and
not a full release gate.

The old complete-check handle is now terminal FAILED: 1,655 passed / 1 failure,
no frontend/mobile phases reached. Its in-memory claim-MCP test expected 35 tools
while the server returned 38. The concurrent aa4b30e commit changed that source
expectation to 38 after collection; therefore this is a mixed-input result, not
proof that current code still fails. The current unchanged claim transport module
passes all 4 cases in 59.37 seconds (63.6 overall), including official MCP restart.
No test expectation was changed by this continuation to resolve that failure.

Next validation uses an independent detached worktree with a byte-for-byte overlay
of the current committable files and hash-verified declared fonts. Record the
snapshot/source hashes, require no drift inside that candidate, and keep it
unchanged until its complete check ends. Other sessions may continue in develop;
never edit the frozen candidate or infer it includes later shared changes. No
commit/push/release is permitted from a red or evolving-input receipt.

Frozen gate admitted: snapshot is
`C:/Users/user/AppData/Local/Temp/paperfact-v05-frozen-fhiui9h0`, detached at
`aa4b30ebec4f7bb1b7c289531da02cc7c00d7c29` with the byte-exact current overlay.
1,622 committable/runtime-font inputs were hashed; no ignored .env, credentials,
research folders or virtual environment were copied. Declared fonts were copied
only when their pinned SHA-256 matched. Full check is live under the owned runner
handle 39360 (check child PID 39292); confirm the handle, not this note, before
starting another gate. Receipt: `build/frozen-gate-20261113.json` in develop;
full log and frozen-input hashes are in the snapshot's ignored build/ directory.
Do not edit or remove that worktree while the gate runs. No commit was made.

A later observation should record terminal stages, exact Python/frontend/mobile
counts and final input drift. If the shared develop tree changes, compare its
inputs with this receipt and validate those changes separately. Passing this
Windows source gate will not establish Mac/Linux installed or hosted acceptance.

## GCP direction selected — 2026-11-13

The owner chose reuse of existing GCP for deployment planning only. No GCP account,
project metadata, billing, IAM, domain or resource was accessed or modified. The
reviewable proposal is docs/gcp-sync-pilot-plan.md, linked in README. It recommends
one VM plus durable disk and a reviewed same-origin HTTPS/PWA edge for the initial
single-user pilot, and records the Cloud Run/PostgreSQL/GCS adapter work separately.
Official Google documentation was checked for ephemeral Cloud Run storage, FUSE
locking/database limitations, durable disks, IAP, bucket privacy and budget scope.
These facts constrain the engineering recommendation; no price or capacity is
claimed without the missing regional/project/workload inputs.

Project ID, usable hostname and monthly budget were requested asynchronously;
asia-east1 is a proposed region, not an approved/provisioned location. The plan
requires reviewed backup consistency and recovery identity/cursor behavior, not
simply restoring an old server snapshot as though history had never rolled back.
Infrastructure application and research upload remain separate unapproved actions.

Documentation profile: build/gcp-plan-docs-20261113.log — 46 passed in 1.34 seconds,
4.3 seconds overall, privacy/Ruff green. This overlaps earlier docs selections.
The proposal/README updates occurred only in the shared source tree; the running
frozen candidate remains unchanged. No global skill or deployment rule was added.

## Post-freeze credential-output review

A read-only audit found two real output boundaries, reproduced by two added
regressions: a valid record exactly at the codec's size limit became unreadable
after an appended newline, and an output close error after enrollment commit left
an enrolled device without its output. Both tests failed before the fix.

The shared-source writer now emits the exact encoded record and closes it inside
the trusted before-commit callback. No validator was loosened. The new boundary
cases plus existing admin/authority cases pass: 48 passed in 3.16 seconds, 5.9
seconds overall, privacy/Ruff green (`build/admin-output-boundaries-green.log`).
The guide now explicitly includes close failure in its rollback contract; abrupt
process termination remains subject to the previously documented crash limits.

These changes are AFTER the frozen snapshot and are not present in its 1,622-file
receipt. The running candidate was left intact. Any later publication must include
and validate this delta; do not claim the older full gate covers it automatically.
The latest direct observation confirmed the old runner handle and its Python
child remain live; sandbox read denial was resolved by an elevated read rather
than a restart. A live hash comparison found zero changed frozen inputs.

## Private output placement and publication guard

Review found that the initial relative-path admin examples could create private
connection/state files inside a checkout. The examples now use quoted
$HOME/.paperfact-sync paths (valid in the documented PowerShell/sh environments),
with connection output outside the authority subdirectory. Conventional legacy
output names/state folders are ignored as a convenience, not an access-control
boundary. Operators still choose and protect their actual output directory.

The existing privacy scan did not recognize opaque sync tokens. Two new tests
failed before the fix: full credential records in .json and .txt files both let
all mocked stages run. The scanner now rejects the exact version-1 connection
record shape with a nonempty credential, except the explicit documented placeholder.
Reports contain only relative path, line and finding kind, never the token.
Existing secret patterns and expectations remain unchanged. Placeholder/empty and
unrelated JSON are allowed; a real isolated Git inventory test verifies private
conventional outputs are excluded while source files remain committable.

`build/connection-privacy-green.log`: privacy/Ruff green, 52 documentation/check/
distribution cases passed in 1.76 seconds (4.8 overall). Six cases are new; only
the two credential rejection cases were exercised as red-before-fix. These results
strengthen fail-closed publication checks; they do not prove all conceivable
secret formats or archives are detected. No actual credential was examined.

This adds .gitignore, scripts/check.py and its tests to the previously recorded
post-freeze delta. The old frozen gate still runs unchanged and does not contain
this guard. Its terminal receipt must not be advertised as validation of the new
scanner. A local gcloud application was not found on PATH; no cloud login was
attempted, and project/region inputs remain unverified pending owner information.

## 2026-11-13: physical-device acceptance coverage

Extended the existing `mac-acceptance-0.5.md` rather than creating another
acceptance checklist. M08 now checks private connection-record loading without
implicit connection/upload. M16-M20 cover session opt-in after restart, attachment
retry versus verified offline availability, peer revocation preserving local work,
detached client recovery, and a physical phone offline-note round trip. The
procedure distinguishes client backup from authority disaster recovery and requires
separate iOS/Android results. These are prepared steps, not executed device passes.

Validation: `scripts/check.py --profile docs` passed 52 cases in 1.70s; privacy
scan and Ruff passed, total 5.0s. This is scoped documentation/contract evidence,
not the whole-app gate. The existing isolated full check (session 39360) remains
live; its frozen inputs were independently verified unchanged (1,622 files).
This documentation change is after that freeze and does not alter its inputs.

## 2026-11-13: remaining-scope audit during the frozen gate

Read the current roadmap, delivery map, grounded-lineage activation contract and
actual task/producer sources. The lineage core is present but not an activated
end-to-end roadmap feature: no Lineage task registration or complete durable
publication, desktop, portable preservation, sync and mobile workflow is claimed.
Added this explicit implementation gap to the current status front section so a
future full-check pass cannot be mistaken for full v0.5 scope completion. No
production source or old test expectation changed in this audit.

Local ancestry inspection: `git log HEAD..master` was empty and
`git rev-list --left-right --count HEAD...master` returned `84 0` at `aa4b30e`.
This proves local master inclusion only; no remote fetch or merge was performed.
The frozen full-check handle 39360 remained live and advancing during the audit.

## 2026-11-13: archive entry-point schema scope

The live frozen full check emitted a 60-second faulthandler diagnostic while
`test_private_public_draft_can_be_adopted_rechecked_applied_and_backed_up_again`
was inside `inspect -> _Records.row -> recovery_provenance.decode -> _registry
-> _research_schema`. Later dots confirmed the run continued; this was not a
terminal test failure. The snapshot is unchanged and remains running.

Source inspection found the existing metadata scope covers `validate_groups`
but not the outer create/inspect/restore row loops. A new real-archive test first
needed an explicit BEGIN in its fixture (the production transaction guard was
correct). After correcting that fixture, RED reproduced 12 real schema builds
for one backup containing only three retained paper rows, above its fixed budget.

Applied the maintained `schema_definition_scope()` context decorator to create,
inspect and restore_detached. No row, hash, source ownership, database handle or
validation outcome is cached; independent calls and error paths retain fresh
metadata. New cases exercise real archive creation, repeated inspect/restore,
exact retained history, detached identity and failed-inspect retry. The new four
and unchanged thirteen scope cases passed: 17 in 33.55s. The official broader
recovery/aliases/filesystem/note-continuity selection is running as session 30907,
log `build/archive-schema-scope-focused-20261113.log`; no final result yet.

This is an additional post-freeze source change, not covered by the currently
running full snapshot. No existing test was weakened. This repairs missing
call-site coverage of an existing scoped-metadata pattern; no new global skill
rule or installation is warranted. Full validation remains required.

The broader official selection completed: **89 passed in 209.09s**, privacy
scan and Ruff passed, total 212.4s. These 89 include the 17 cases above and are
not an additional disjoint count. Exact log:
`build/archive-schema-scope-focused-20261113.log`. This verifies the real
backup/inspect/detached-restore, alias refusal, provenance scope and note-review
continuity selection only; the matching final full check is still required.


## 2026-11-13: frozen full gate completed

The existing session 39360 terminated with exit 0. The runner verified all 1,622
frozen input hashes unchanged (`drift: []`). At shared HEAD `aa4b30e` plus the
frozen uncommitted overlay, the original full `scripts/check.py` passed:

| Stage | Observed result | Stage seconds |
|---|---|---:|
| Privacy scan | Passed | 1.885 |
| Ruff | Passed | 0.539 |
| Python and desktop stress | 8,849 passed, 1 skipped, 4 warnings | 15,658.316 |
| Frontend | 24 passed, no failures or skips | 0.178 |
| Mobile domain and Python service integration | 535 Node cases passed; all 13 Python integration programs exited successfully | 37.138 |

Full-check reported total: 15,732.591 seconds; outer snapshot/hash runner:
15,739.83 seconds. These are measured durations, not future estimates. Python's
percentage described only its own phase. The earlier 60-second faulthandler
message was diagnostic and did not terminate that phase.

The four warnings are existing invalid escape sequences in fixture literals:
three in `test_runtime.py` and one in `test_share.py`. No expectation was changed.
The requested JUnit file is absent; the terminal log and JSON stage receipt are
the authoritative available evidence. Do not claim a JUnit artifact was produced.
A separate direct run of the exact frozen `test_rich_view_window.py -rs` reproduced
the one skip: its snapshot lacks the vendored KaTeX asset, although Qt WebEngine
is installed. This is incomplete native-window coverage, not a native pass.

Receipts: source `build/frozen-gate-20261113.json`; snapshot path is recorded
there; snapshot `build/frozen-full-check.log` and `build/check-latest.json`.
The private ignored receipt `build/post-freeze-delta-20261113.json` lists the 14
paths changed after the freeze. They include the independently tested archive
scope, private connection output, credential publication guard and documentation.
This pass does not certify those later changes or full v0.5 feature completion.
A matching final full gate is still required before commit/push/release. Its
snapshot preparation must include the declared public web assets as well as
fonts, or explicitly record that optional native coverage remains unavailable.
Do not copy ignored research, configuration or credentials into a test snapshot.
Cloud deployment and physical Mac/phone acceptance remain separate open gates.


The missing native coverage was checked separately in the prepared integration
checkout, with the existing public web assets and isolated default data:
`scripts/check.py --profile focused --python tests/test_rich_view_window.py`
passed **1 case in 8.00s**, privacy and Ruff passed, total 11.1s. The actual
WebEngine reader retained its native window handle. This is Windows coverage,
not physical Mac acceptance. Log: `build/native-window-acceptance-20261113.log`.
It supplements the identified skip; it does not retroactively change the frozen
full-run result or certify the post-freeze source deltas.


## 2026-11-13: archive every selected Lineage original before completion

Source audit found that the inactive producer retained its result only in process
memory, while its exact peer originals had no durable typed private source closure.
Added `lineage_source_snapshots.retain` and the closed archive-only
`paperfact.lineage-source-observation.v1` format. Before spending its first facade
completion, a Lineage job now publishes complete original/receipt pairs for all
available sources. The observations bind actual local source and focal lifetimes,
corpus/request UUIDs, evidence identity, PDF hash/size, database identity and binding.
They use the existing atomic private-source/independent-backup machinery, never a
fake claim, graph operation or active Lineage source owner. The claim original
resolver explicitly refuses this format as lookup authority.

The producer accepts an explicit canonical `corpus_id` or generates one and returns
it in execution metadata. Failed/cancelled source staging spends no model call and
same-job retry repairs lost acknowledgement without duplicate observations. A
completion failure retains all originals but still requires a new explicit job.
A new request keeps distinct provenance for unchanged bytes. Missing peers produce
no invented PDF. A changed live PDF does not replace the archived original; a real
backup and detached restore preserve all three originals/observations without
reviving source, device or job authority. Generated report text, atomic report/
outbox publication and end-to-end Lineage activation remain unfinished.

The first new-file lint gate found six formatting issues; they were corrected
without changing old tests. The first behavior selection passed 46 cases in
60.81s (63.7s total), including the unchanged producer module. The larger source,
claim-owner, recovered-position and note-source selection passed **107 in 285.29s**
(288.5s total); it includes those earlier cases and is not a disjoint count.
Logs: `build/lineage-source-retention-20261113.log` and
`build/lineage-original-boundaries-20261113.log`.

The larger selection began before an additional progress-callback guard and the
last identity/epoch validation changes. A final new-case selection covers that
code, the enrolled peer identity path, native close and a rehashed contradictory
observation; its result is recorded separately below. New tests only were added;
no old expectation was deleted, skipped or weakened. No real accounts/models,
owner research, cloud resources or maintenance releases were used. This is after
the completed frozen full gate and still requires matching final full validation.

Harvest review: the distinction between archived source observations and active
owner authority reuses the repository's existing source/recovery contracts. Its
specific new behavior/evidence stays here and in the producer guide; no new global
rule, skill installation or telemetry collection is warranted.


The final new-case selection passed **20 in 40.64s**, privacy and Ruff passed,
total 43.4s (`build/lineage-source-final-20261113.log`). It covers the final progress
lease guard, selected-identity/hash and focal-epoch checks, actual enrolled peer
IDs, native document close, source/cancellation/retry and real detached backup.
These cases overlap the earlier 107-case selection; do not add the counts.

A subsequent caller audit found an indirect authority crossing: first enrollment
put every private receipt PDF into a generic owned-source pool, and claim/live-QA
fallbacks selected by hash alone. A real imported-claim/Lineage fixture reproduced
the bug: enrollment reported supported after the only eligible claim source had
been removed, because it silently reused the Lineage observation's bytes. RED:
`build/lineage-enrollment-red-20261113.log` (one failed assertion in 1.00s).

The inventory now explicitly tags only this new format's descriptors
`archive_only`; generic file classification/archiving still retains them, while
claim and live-QA fallback refuse automatic promotion. Explicitly selected primary
PDFs stay eligible. The new explicit-choice fixture initially left an unselected
primary alias in the inventoried source tree, correctly triggering the maintained
unmapped-file guard. Moved that fixture file outside the source tree and asserted
its bytes preserved; no production guard or old test was changed. Related
imported-original and chat-history enrollment checks are recorded on completion.


The final enrollment boundary selection completed: **37 passed in 52.53s**,
privacy and Ruff passed, total 55.4s. It includes the two new enrollment isolation
cases plus unchanged imported-source and chat-history enrollment cases. Log:
`build/lineage-enrollment-green-20261113.log`. These are focused results, not a
new whole-application gate. No check process remains pending from this slice.

Current activation boundary: all available corpus originals are privately archived
before the completion and survive independent backup/detached restore. No canonical
Lineage row, all-source active owner, request/candidate result receipt, capture/
package/sync domain or desktop/mobile entry has been activated by this change.
The generated report can still be lost when the process exits. Next implementation
must join the existing observed composite target and peer-source publisher with
replay-safe report retention/publication, then close preservation before routing/UI.
Keep the full v0.5 objective active; do not label this source-retention step a
release or advertise end-to-end Lineage as ready.


## 2026-11-13: durable private Lineage proposals

Completed schema-valid, quote-checked reports now prepare a process-sealed native
candidate and use the existing generation SQL/owned-sidecar channel. The closed
context is `paperfact.lineage-proposal-context.v1`; it always validates as a
candidate, never accepted. Ordered source identities/lifetimes, exact original
observations, original-only recipe and requested/returned models stay with the
report. No credentials, account home or route configuration are retained. Generic
main-key generation stays closed; the unsupported target now refuses with ValueError
before any SQL instead of an internal registry KeyError.

SQL retention verifies the actual original native database identity and binding.
Replacement/rebinding uses the maintained private recovery namespace rather than
writing old work into new SQL. A failed save leaves the completed result cached;
retrying retention cannot spend another model call. Concurrent native retries keep
one exact receipt. A lost commit acknowledgement probes exact committed success
before creating a sidecar. Saved-only reads are bounded and defensive, with a real
second-process reopen test. Canonical `paper_lineage_sets` is not installed.

The existing retained-work review now reads/exports the scientific proposal and
can record an idempotent Keep decision. Generic apply/edit/target selection remain
blocked. Text export is a typed whitelist rather than the claims exporter and
omits private context/owner/route fields. All original observations participate
in backup and first enrollment, including an older native database identity at
the same path and matching scope. They remain archive-only: a current primary B
stays distinct and focal original A gets no active shared artifact just because
a private proposal retains it. Detached recovery stores history without reviving
a device or a resumable job.

### Test map for this increment

| Test module | Researcher-visible invariant |
|---|---|
| `test_lineage_candidates.py` | Reopen exact reports in another process; retain stale results; retry save without another call; preserve all originals in independent backup/restore; reject forged acceptance/incomplete closure. |
| `test_lineage_candidate_boundaries.py` | Refuse retargeted serialized paths; one receipt under concurrent retries/lost acknowledgement; bounded saved reads; no partial backup when an original is missing. |
| `test_lineage_candidate_reading.py` | Keep one decision without installing content; no generic target/apply authority; saved copies cannot mutate storage; generic publication refuses before writing. |
| `test_lineage_candidate_enrollment.py` | First enrollment preserves an old-identity proposal and all exact originals as private history while current B remains and source A gains no active ownership. |

The previous source-only test added in this continuation was updated for the
explicitly requested new persistence behavior: its no-SQL-write assertion now
runs inside the fake completion, before candidate retention; afterward it asserts
one candidate row and no canonical Lineage table. This preserves the original
pre-call invariant and pins the newly authorized after-completion behavior.
No pre-existing HEAD test was removed, skipped or weakened.

### Actual failures and verification

- Several new-module style/import/SQL-literal lint findings were corrected before
  behavior runs. They were not product regression assertions.
- First proposal-journey run: one pass and one failure, 6.50s. Readable export
  wrongly used the claims projection and omitted Lineage statements. Added the
  typed readable projection; the nine-case journey then passed in 26.26s.
- Lost commit-acknowledgement case: two passes, one failure in 7.48s because a
  committed SQL receipt also created a sidecar. Added exact committed-success
  probing; all 15 journey/boundary cases passed in 47.19s (50.5s total).
- The Keep case reproduced an internal main-key registry KeyError; the explicit
  paper-scope receipt branch fixes it without adding a canonical writer.
- First-enrollment case reproduced a missing-original error because only the new
  database namespace was inventoried. Reused the closed proposal source collector.
  Its next fixture run correctly hit the existing non-lossless paper baseline
  guard: the low-level corpus fixture's `title_key` was not the normal derived
  title key. Corrected that fixture using `store.title_key`, not the guard.
- Generic publication of a private proposal reproduced a registry KeyError
  (one failure, 5.76s); added explicit unsupported-target refusal before lookup.

| Selection | Result | Total seconds | Log under `build/` |
|---|---|---:|---|
| Original producer + source-retention files after candidate integration | 55 passed in 112.96s | 116.2 | `lineage-candidate-core-20261113.log` |
| New proposal journey/boundaries after export and acknowledgement fixes | 15 passed in 47.19s | 50.5 | `lineage-candidate-boundaries-20261113.log` |
| Existing generation/review/enrollment history/backup/source plus Lineage files | 199 passed in 388.66s | 392.6 | `lineage-candidate-integration-20261113.log` |
| Keep/enrollment plus existing imported-original/chat-history/decision cases | 41 passed in 102.14s | 105.0 | `lineage-candidate-consumers-20261113.log` |
| Final generic-refusal case plus all existing generic-generation cases | 39 passed in 37.76s | 40.6 | `lineage-generic-publish-green-20261113.log` |

Privacy scan and Ruff passed on these green selections. Counts overlap and must
not be added. The 199-case run preceded the final Keep/enrollment inventory changes;
the 41-case run covers those consumers, and the 39-case run covers the last
unsupported-target guard. Production code was not changed inside those running
checks; separate new reproductions used isolated fixtures. Repository line endings
were preserved for the existing CRLF review file so its diff remains narrow.

These are focused iteration gates. The completed 1,622-input full gate predates
this increment, so a matching final full check is still required before commit,
push or release. No new commit, release, cloud provisioning, real model call,
owner research write or physical Mac/phone acceptance is claimed.

### Remaining activation

Retained private proposals are not observed canonical targets or replay authority.
Atomic composite-target publication, every active peer-source association,
portable capture/package/sync closure, task routing and dedicated saved-first
desktop/mobile display remain required. A raw response stopped before quote
verification still has only bounded in-process retention; durable pending-
verification recovery remains an explicit open case. This supersedes the preceding
source-only checkpoint's statement that every generated report remains volatile,
without claiming all intermediate results or the full Lineage feature are durable.
The full v0.5 goal remains active.

Harvest review: native prepared proofs, archive-only histories and exact commit-
success probing reuse maintained contracts already present in this project. The
new domain's evidence and limits stay in this ledger and producer guide; no global
rule, generated skill copy, telemetry hook or installation was added.


## 2026-11-13: staged portable Lineage operation and graph address

Implemented `lineage_wire`: complete payload/source-hash/row validation, exact
registered sender/receiver identity conversion, focal-first parent closure,
per-paper required-original bindings and a complete staged v2 operation codec.
The existing v2 header and final UTF-8 encoder are shared without changing the
active validator's optional field set. The live registry still refuses Lineage;
no SQL migration, task registration or network publication was added. The existing
inactive-helper test and a complete valid staged-operation rejection case pin this
activation boundary rather than relying on a malformed frame to imply refusal.

The first round-trip fixture compared different saved timestamps (the helper row
used 2026-10-30 and the operation factory 2026-11-13). Corrected the new operation
fixture to use the actual encoded row, preserving the intended exact comparison.
After that correction, 29 wire cases passed and the graph lifecycle case failed:
`apply_accepted` omitted `content_address`. Added a conditional typed-address guard
and copied the address into accepted metadata. The pending overlay preserves it
and checks a known address before mutating state/own/touch maps. Generic untyped
operations retain their existing behavior.

A second new case reproduced that an empty delete could reorder selected peer
identities under the same corpus address: seven passed, one failed in 0.33s.
Changed this closed domain's known-parent check from an unordered set to the
ordered kind/ID tuple list. Fresh incarnations of those same IDs remain supported;
the existing restoration tests still pass. This is a captured corpus-order rule,
not a change to user list sorting/dragging or generic graph parent rules.

| Tests | What they establish |
|---|---|
| `test_lineage_wire.py` (30 cases) | Registered sender/receiver round trip without writes, complete malformed payload/envelope refusals, no identity minting, equal bytes retaining distinct owners, typed deletion and accepted graph address preservation. |
| `test_lineage_wire_lifecycle.py` (10 cases) | Pending put/delete address preservation; every focal/prior/later paper's deleted/recreated lifetime causes conflict without mutation; no reordered empty delete; four-paper closure with an honestly unavailable original; bounded UTF-8 payload without truncation. |
| Existing graph service/client/research, content, files and ordering modules | Default protocol behavior and existing storage/file/ordering round trips after shared header extraction and the conditional metadata guard. |

The first graph union passed **139 in 26.26s**, privacy and Ruff passed, total
29.1s (`build/lineage-wire-graph-20261113.log`). After the ordered-parent fix, the
full affected selection passed **229 in 125.74s**, privacy and Ruff passed, total
128.8s (`build/lineage-wire-integration-20261113.log`). The latter includes the
former cases plus the new lifecycle and existing content/file/ordering selections;
these counts are not disjoint and must not be added. Minor new-line formatting
findings were corrected before behavior checks; no old test was weakened.

Untouched mixed line endings in the existing schema/graph files were restored from
matching HEAD lines, leaving narrow reviewable hunks. No production file changed
inside either running green selection. No real provider, owner research, service
credential, deployment, current maintenance release or physical device was used.

This is a staging prerequisite, not completed live Lineage sync. Next activation
must include the typed canonical target/publication transaction and every active
peer-original association, then the actual registry/materializer/history/snapshot/
package/mobile closure before exposing the dedicated UI/task. The staged validator
is not an alternative HTTP endpoint or a way to bypass live client refusal.
A matching final full check remains required before commit/push/release; the
previous 1,622-input frozen pass predates these changes. External GCP deployment
and installed Mac/phone acceptance remain explicit separate gates.

Harvest review: exact typed multi-parent identities, conditional metadata
preservation and staged activation apply the existing closed-contract/preservation
rules. Their domain-specific evidence remains in this ledger and producer guide;
no speculative global skill or generated skill copy was changed.


### GCP preparation: mounted-state startup guard (2026-11-13)

Added optional `sync-admin serve --require-mount DIRECTORY`. It rejects an absent
mount or an invalid state/mount relationship before opening authority state or a
listener. No initialization fallback is permitted. Existing local serve behavior
is unchanged. Added an inert Linux systemd example and operator prerequisites;
no GCP resources, installed units, accounts or research were modified.

Official focused check of `test_sync_admin.py` and `test_sync_admin_mount.py`:
**21 passed in 1.72 s**, privacy scan and Ruff passed; total 4.5 s. Eight new
cases cover missing/ordinary mount, wrong/relative location, initialized state
preservation and restored-mount retry/close. OS mount success is simulated in
fixtures; a real ordinary directory refusal is also tested. This is not evidence
of a mounted GCP disk, Linux supervisor behavior or installed Mac acceptance.
The full check for the current accumulated revision remains pending. The earlier
frozen full-check result does not cover this addition.


### Pre-call Lineage target binding (2026-11-13)

The previous GCP preparation turn made verified local progress; no deployment
was performed. This checkpoint returns to the incomplete grounded-reading
publication path, not a replacement for the full 0.5 scope.

`LineageJob.prepare` accepts an optional exact native `publication_observation`.
A worker captures a `TargetLease` before AI use, adopts the original request/corpus
UUIDs, rejects a different corpus/key, and rechecks source/SQL target metadata
before spending a completion. During-call changes retain a private candidate with
`lineage_target_changed`; no canonical row is inserted/replaced. A retained lease
can expose its original archive metadata after source/view invalidation but fails
fresh authority checks. The prepared candidate HMAC also binds the native lease.

The optional closed `publication_base` stores only the original request/corpus
UUIDs and exact target/observation hashes. Older archive records remain readable.
These data do not mint native authority. The final publisher still requires
same-write-transaction `check_in`, all-original active ownership, canonical row,
outbox and receipt. Unsupported raw-SQL ABA and native UI delivery remain
separate boundaries. No live schema/task/protocol activation was added.

Evidence, all terminal:
- Initial lint gate caught nine line-length errors; corrected formatting without
  changing test expectations. No behavior test failed in these selections.
- Core selection (`test_lineage_target_jobs`, `test_lineage_jobs`,
  `test_lineage_observation`, `test_lineage_candidates`,
  `test_lineage_candidate_boundaries`): **64 passed in 135.01 s**, total 138.0 s.
- Expanded target plus private review/enrollment/source-boundary selection:
  **24 passed in 71.15 s**, total 74.0 s.
- Final 18-case target module (including four malformed-context boundary cases):
  **18 passed in 36.99 s**, total 39.7 s; exact terminal output in ignored
  `build/lineage-target-final-20261113.log`. Privacy scan and Ruff pass.
Counts overlap and the final module includes later added cases. All model replies
are simulated over isolated synthetic PDFs. No account calls or research writes
occurred. The current accumulated revision still needs a matching final full gate.

The existing local-integration skill already separates retained bytes, current
ownership, GUI delivery and transactional publication. This is a project-specific
application of those boundaries, not a new validated cross-project skill.
No accessible Claude session tool was found in the current tool inventory; the
producer guide and this ledger remain the file-based continuation handoff.


### Staged local compound Lineage publication (2026-11-13)

The preceding target-binding checkpoint made verified implementation progress.
This continuation adds the next transaction seam, without declaring the inactive
Lineage workflow complete or exposing it through UI/CLI/MCP.

`lineage_candidates.checked` centralizes the existing native candidate validation.
New `lineage_publication.prepare` verifies all exact atomic original/receipt pairs
off-lock and binds their verified versions. `publish_in` requires an existing
caller transaction, rechecks the original composite observation, and atomically
writes the canonical local row, every available peer's association in
`research_local_source_owners`, and `research_lineage_publications` request/row/
source receipt. Savepoint rollback preserves earlier caller changes. Caller
rollback removes all compound writes. Exact/concurrent retries verify the current
row and every association, returning one result rather than duplicating records.
No hashing, parsing, model calls or file publication runs under the SQL lock.
Stored receipt/source metadata reads are bounded.

The original observations retain their archive-only format and never become
claim originals through generic lookup. Typed active Lineage source reading is
still missing. Real enrolled candidates refuse this unbound seam instead of
bypassing the outbox. Complete bound publication, all preservation paths and mobile
projection remain implementation requirements before activation. In particular,
backing up a private candidate does not certify canonical publication/history
preservation. No owner data, accounts, release or GCP resources were touched.

Evidence:
- Initial lint reported two import-order issues in new files; fixed imports only.
- The first new exact-row assertion incorrectly compared JSON insertion order
  with SQL column order. It was corrected to compare every declared schema field;
  no stored content expectation or existing test was weakened.
- First compound selection: **9 passed in 31.07 s**, total 33.9 s.
- Final publication/real-bound-refusal/target/candidate-boundary/peer-source union:
  **46 passed in 143.02 s**, total 146.3 s, zero skips. Exact log:
  `build/lineage-publication-integration-20261113.log` (ignored).
  Privacy scan and Ruff pass. This includes 14 new publication cases, caller
  rollback, injected second-association failure, independent caller changes,
  concurrent repeats, changed original/receipt/target, unavailable peer,
  cancellation, missing transaction and real enrolled outbox preservation.
- All PDFs/workspaces are synthetic fixtures and completions are simulated.
  No physical Mac/phone, deployed Linux supervisor or hosted sync was accepted.

The existing canonical local-integration skill already covers one transaction
owner, byte staging and exact retries. This checkpoint applies that rule locally;
no new cross-project rule or generated skill copy is introduced. The current
accumulated revision still requires a coherent final full check before commit,
push or release. The file-based guide/ledger remains the Claude handoff.


### Canonical local Lineage detached recovery (2026-11-13)

The preceding staged-publication turn made verified progress. This checkpoint
extends the actual recovery pipeline rather than treating private candidate
survival as canonical-result preservation.

The closed recovery registry now includes optional `paper_lineage_sets` research
and `research_lineage_publications` protocol rows. `lineage_recovery.Records`
validates every canonical result against a complete publication/candidate/original
association closure. Each available exact paper/source/request keeps its own
identity even when immutable PDF bytes deduplicate. Missing candidates, receipts,
associations, peer papers or original files refuse export/inspection; recomputing
container table hashes cannot bypass domain closure.

Detached restore creates the maintained Lineage research schema only when declared
in the archive. Canonical reports remain exact; old publication, candidate and
source grants remain archive-only in `recovery_records`, with verified PDF objects
retained independently. No native job, sync device or old source association is
reactivated. Recovery inspection accepts that typed read-only content and explains
why editable sync adoption is still blocked pending fresh source ownership and
Lineage enrollment. There is no successful-but-partial editable migration.

A verified adjacent boundary bug was found: later-outcome package `_owned` and
recovery `Records.authority` both accepted archive-only Lineage observations as
unrelated original authority based on owner/hash/lifecycle alone. Two new tests
reproduced the leak (2 failed, 10 deselected, 6.20 s). Both paths now explicitly
exclude this format. Existing intended source ownership remains unchanged.

Evidence, all processes terminal:
- Initial new recovery module: **10 passed in 42.80 s**, total 45.4 s.
- Official affected recovery/adoption/provenance/schema-budget/candidate/later-
  outcome union: **142 passed in 359.25 s**, total 362.4 s. Privacy and Ruff pass.
  Exact ignored log: `build/lineage-recovery-integration-20261113.log`.
  Includes both RED ownership cases after the fix, actual detached restoration,
  exact blob bytes, same-hash distinct paper owners, corruption/refusal and
  existing editable-copy behavior. Slowest case was an actual editable-copy/
  history/backup journey at 9.90 s, not a real service or paid model call.
- Separate isolated current-B/prior-A publication-history round trip:
  **1 passed in 10.03 s**; exact ignored log:
  `build/lineage-recovery-history-20261113.log`. One canonical current row, both
  request receipts, six per-request source associations and both focal originals
  survive; detached current remains B.
- The first lint gate flagged one new import block; fixed ordering only.
  Unchanged adoption-file line endings were restored to their original mixed
  convention, leaving exactly eight added code lines and no logical rewrite.

Counts overlap (142 includes the 12 new core/boundary cases; the history case is
separate). All work uses synthetic local fixtures and simulated completions.
No original research, credentials, current release, GCP resources or accounts were
modified. Source-format distinction and transaction ownership are existing
canonical local-integration rules; evidence stays project-specific rather than
inventing a new global skill. Full current-revision validation, bound publication,
active source readers/fresh enrollment, list-package sharing, mobile and installed
Windows/Mac/phone acceptance remain required. The objective is not complete.


### Saved exact-original inspection and loaded-view delivery (2026-11-13)

The previous detached-recovery checkpoint made verified progress. This turn adds
an actual saved-result source reader, not a new model/crawl operation and not a
claim that the Lineage UI/sync workflow is finished.

`lineage_originals.prepare` reads the exact current local row, latest matching
publication, retained candidate and every original association under the actual
loaded `HighlightOwner`. It validates the native database/binding and all selected
paper lifetimes, then verifies the selected immutable PDF outside SQL. No schema,
source grant, identity or receipt is created. `None` means known unavailable
original/cancellation; a missing or damaged retained original never falls back to
the current primary or another paper. Original A remains inspectable while B stays
the current primary. Byte verification is reused for the atomic pair's same-version
check, avoiding double hashing on the normal path.

The returned native snapshot seals its actual peer/source/hash, metadata, loaded
owner, immutable byte object and file versions. `metadata_current` checks native,
SQL and file metadata without PDF parsing/hashing. `for_delivery` requires the
actual current loaded-owner object, expected result/corpus and source again, so
worker results cannot fill another page, source or reopened/closed view. It returns
verified immutable bytes instead of reopening an unchecked path after delivery.
This is not a global commit lock or a completed native PDF viewport integration.

Shared archive linkage moved into `lineage_recovery.linked_publication`; archive
data still does not grant native authority. The writer creates a guarded
JSON-expression lookup index inside its existing compound transaction. An actual
SQLite EXPLAIN showed `SEARCH research_lineage_publications USING INDEX
research_lineage_publications_target (<expr>=? AND <expr>=?)`, with no global
history scan in that query plan. An unrelated invalid JSON history row cannot be
parsed or selected as the current source. Detached content/objects remain preserved
but this reader refuses absent live receiver grants. Bound source reading remains
unimplemented alongside compound sync publication.

Evidence, all processes terminal:
- Source-only official focused gate: **22 passed in 60.24 s**, total 63.2 s.
- Final source/boundaries/publication/bound-refusal/recovery/history union:
  **53 passed in 191.58 s**, total 194.4 s; privacy scan and Ruff pass.
  Exact ignored log: `build/lineage-originals-integration-20261113.log`.
  Contains all 26 new source cases; counts overlap the 22-case first gate.
- Cases cover exact focal/prior/later bytes, no writes/AI, public-field/byte forgery,
  replaced database, changed canonical/candidate/publication/association/peer life,
  view/source/corpus/close changes, A versus current B, damaged-cache refusal,
  worker verification races, unavailable peer, cancellation, malformed unrelated
  history, detached grant refusal and actual fresh-process restart.
- New import ordering was corrected before the behavior gates. Source SHA/paper
  fields were included in the seal during code review before testing; no failed
  behavior assertion was weakened or skipped.

All research/PDFs are synthetic fixtures and model replies are simulated. No real
account calls, source database writes, release changes or GCP deployment occurred.
The canonical local-integration skill already requires exact source ownership and
last GUI-delivery guards; this checkpoint is local evidence for those rules,
not a new cross-project/global rule. Full current-revision validation, synced
publication/source ownership, fresh editable enrollment, list-package sharing,
PDF/citation UI, mobile and physical Windows/Mac/phone acceptance remain open.
No complete objective, commit or release is claimed.


### Exact original-file lifetime dependencies for staged sync (2026-11-13)

The previous saved-original checkpoint made verified progress. Current source
inspection showed a live-admission blocker: the staged Lineage frame bound all
paper lifetimes but not the individual original file lifetimes. Equal PDF hashes
must not revive an intent after original deletion/restoration. This turn adds that
required dependency contract; it does not reduce the objective to a pure codec.
Live compound publication, shared admission, projection and portable closure
remain the subsequent required implementation.

New `lineage_dependencies` validates an ordered complete `source_dependencies`
list (source ID, portable paper ID, derived file ID, file incarnation). Its strict
codec requires the list for puts and an explicit empty list for retirement. The
base staged wire codec validates pins when supplied, while retaining source-less
staging compatibility; neither codec registers a live feature/service capability.
The eventual live gate must use the strict codec, not that diagnostic compatibility.

`lineage_peer_sources.pins_in` rechecks native observation, storage, staged versions
and the actual optimistic original graph after same-transaction peer publication.
It produces data without a new SQL write/commit. `lineage_dependencies.active`
checks all selected paper lifetimes and every original file incarnation/parent
against an authenticated-workspace-scoped graph in the caller's transaction. It
supplies no authentication/blob proof by itself and must be wired into the future
service acceptance transaction, returning a preserved conflict rather than
silently rebasing stale pins. Same-byte owners stay distinct. Known unavailable
originals have no invented file pin but still have a paper parent.

Evidence, all processes terminal:
- Initial native dependency gate: **13 passed in 51.29 s**, total 54.1 s.
- Expanded attempt: **13 passed, 1 failed** in 57.30 s. The new unavailable-peer
  fixture attempted a live whole-paper delete; the existing validator correctly
  raised `Paper deletion requires a later retention contract`. No product gate
  was relaxed. The pure guard now uses explicitly simulated retired fourth-paper
  metadata; this is not evidence that live paper deletion is supported.
- Expanded wire/peer/address/existing graph union after that fixture correction:
  **165 passed in 112.72 s**, total 115.6 s. Exact ignored log:
  `build/lineage-dependencies-integration-20261113.log`.
- A final explicit native client-scope guard was added. Its affected normal/
  None-client/foreign-client/missing-transaction/forged-staging selection:
  **2 passed, 18 deselected in 8.19 s**, exact ignored log:
  `build/lineage-dependencies-scope-20261113.log`. Counts overlap; the module now
  contains 20 new cases. The 165-case run preceded that final narrow guard.
- Privacy and Ruff pass. Two initial lint errors (line length and lambda style)
  were corrected without changing assertions. Final docs lint also caught a
  nested-context style issue in the new scope test; contexts were combined in the
  same order with identical expectations. No pre-existing test was weakened.

Coverage includes actual native peer/file publication, caller rollback, complete
closed cross-owner refs, actual original retire/restore with unchanged payload,
actual fixture reference-service graph before and after accepted file restoration,
wrong workspace, equal-byte distinct owners, unavailable peer and unknown graph
metadata. No Lineage content event was admitted or transferred; normal live
canonical validation still refuses it. All services/PDFs/accounts are synthetic
fixtures; no external service, paid AI, real research or GCP resource was used.

The new rule is an application of the canonical local-integration lifetime and
transaction boundaries, with project evidence retained here. There is no new
global skill/rule installation. Whole-paper deletion/retention remains an explicit
protocol policy gate, distinct from tested original-file retirement. Remaining
work includes live dependency-complete admission and source conflicts, full bound
publication, receiver/source projection, capture/enrollment/packages/snapshots,
required capabilities, desktop/mobile UI, the matching final full check and all
installed-device/deployment acceptance. The complete objective remains open.


### Independent receiver projection and pure shared rejection guard (2026-11-13)

The previous source-dependency checkpoint made verified progress. A proposed bulk
edit to live protocol/client/initializer/graph/writer paths was rejected by automatic
approval review before execution, citing excessive combined regression/data-mutation
risk and requiring reviewed/tested incremental work. Current-state reads confirmed
no Lineage feature/schema-admission/client wiring from that command was applied.
The command was not retried through a clone or indirect script.

Safer separately reviewed work added only unregistered `lineage_projection` and
isolated tests, then one rejection-strengthening shared pure graph condition.
No feature/task/service admission, default schema initialization, client builder or
existing writer was enabled. The projection initializer must be invoked explicitly
on a caller-owned transaction; no runtime component invokes it yet.

The component stores exact local report data and source-pin operation provenance,
maps registered receiver aliases, validates every materialized paper lifetime,
protects pre-existing unowned research and known corpus owner order, and atomically
rolls back content/metadata on failure. Its last-materialized fingerprint refuses
external edits, unexpected removal and hidden unowned insertions rather than
silently replacing or resurrecting research. Hidden views preserve actual put
provenance; explicit old-incarnation retirement cannot erase restored content.
Authentication, accepted-event ordering/CAS, cursor/outbox and original-byte grants
remain the caller's mandatory boundaries, not claims made by this data callback.

An independent real fixture-service reproduction found the already-implemented
source predicate returned false after same-hash file restoration while shared
`check_preconditions` still returned true. The new test failed with `(False, True)`
in 2.55 s before the guard. A narrowly scoped reviewed change now checks explicit
staged Lineage source dependencies in that pure predicate, adding only rejection,
not any new admissible packet or write path. The test passed in 3.31 s afterward.
Normal live canonical validation still rejects the frame.

Evidence and corrected fixture failures:
- First component run: 2 passed, 1 failed (7.62 s). The new fixture explicitly
  rolled back inside Journal.transaction; the existing journal correctly rejected
  premature transaction termination. Fixtures now use an outer sentinel exception
  for that documented rollback contract, retaining all content assertions.
- Next run: 13 passed, 1 failed (31.33 s). A new reorder fixture changed source
  order while retaining the old verified report ID. It now obtains a correctly
  reverified nonempty report from the actual reordered originals before asserting
  the intended known-corpus move refusal. No report validator was weakened.
- Corrected component gate: **14 passed in 32.09 s**, total 34.9 s; exact ignored
  log `build/lineage-projection-core-20261113.log`.
- Final component/shared-guard/dependency/wire/existing graph union, including
  three added external-content preservation cases: **150 passed in 93.37 s**,
  total 96.6 s, zero skips. Privacy scan and Ruff pass. Exact ignored log:
  `build/lineage-projection-integration-20261113.log`.
- Initial new-file lint caught three long lines; corrected formatting/naming only.
  Counts overlap; the final union contains 17 new projection cases and one new
  shared-guard case. No pre-existing test was deleted, skipped or loosened.

The two-peer case transfers actual fixture paper/original-file events and manually
invokes the staged scientific projection; it is not an accepted end-to-end Lineage
sync event. No new source grants, journal operations or cursor movement result
from that callback. PDFs, accounts, workspaces and service data are synthetic;
no owner research, current release, cloud resource or paid AI was touched.

The canonical local-integration skill already requires one transaction owner,
observed bases, precise lifetimes and preserving newer research. These are local
applications/evidence, not a new global rule or skill installation. Remaining work
is real bound publication/admission, recovery/history/fresh source ownership,
package/snapshot/capability/mobile closure, desktop UI, the matching final full gate
and all external installed-device/deployment acceptance. The complete goal is open.


## Bound exact-original reader - 2026-11-13

Problem: the maintained saved-only Lineage original reader intentionally requires
an unbound local publication/candidate receipt. It cannot consume a bound
receiver projection's exact original-file pins. Do not remove that safeguard or
reinterpret detached archive evidence as active ownership.

Added `lineage_bound_originals`, a separate unregistered, read-only worker reader.
It checks the actual loaded native owner, exact row/visible projection fingerprint,
portable-to-local aliases, all selected materialized paper lifetimes and pinned
paper/original-file graph lifetimes. The selected original must match its actual
locally owned desired file incarnation. The registered read-only store's complete
byte closure is verified after releasing SQL. Missing bytes return unavailable;
no download, AI, current-PDF activation, source grant or schema initialization.
Delivery rechecks SQL/native/file versions and the actual owner object, then returns
immutable verified bytes. It does not reopen an unchecked path.

Evidence:

- Initial 18 component cases: **18 passed in 75.21 s**. Added two further boundary
  cases for native database replacement and real file transfer to a receiving peer.
- First extra-boundary run: **1 passed, 1 failed in 11.53 s**. The new receiver
  fixture used plain sqlite3.Connection; the existing capture installer correctly
  refused it. Corrected only the fixture to use native CaptureConnection, retaining
  installation checks and every content/source assertion. Rerun: **1 passed,
  19 deselected in 5.59 s**.
- Final affected union: **156 passed in 319.69 s**, zero skips, total **323.4 s**.
  Privacy scan and Ruff pass. Exact ignored log:
  `build/lineage-bound-originals-integration-20261113.log`.
  Command: `python scripts/check.py --profile focused --python
  tests/test_lineage_bound_originals.py tests/test_lineage_projection.py
  tests/test_lineage_originals.py tests/test_lineage_original_boundaries.py
  tests/test_lineage_dependencies.py tests/test_lineage_shared_guard.py
  tests/test_sync_graph_client.py tests/test_sync_graph_service.py`.

The union includes all 20 new reader cases: three exact source reads without DB
changes or primary activation; changed GUI owner/row/source/closed view; changed
scientific row/provenance/peer projection/storage; actual original retirement and
same-byte restoration; forged identity/bytes; missing/damaged files; cancellation;
unselected source; actual native DB replacement; receiving-peer owned transfer.
Existing source readers, projection, dependency and shared graph checks also run.
Synthetic PDFs and isolated workspaces only; no real account, paid AI, owner
research, release, cloud or credential state was changed.

The receiver case transfers real supported paper/original-file events, then
manually invokes the staged Lineage projection. It proves metadata alone does not
borrow the sender's cache and receiving the exact owned bytes enables inspection.
It is not an accepted Lineage event, real-device UI navigation or hosted acceptance.
The new module has no runtime import callers. Bound recovery/history, sharing,
mobile capability/projection, formal publication/admission and desktop integration
remain open. The latest accumulated revision still needs its coherent final full
check before any commit/push/completion claim.

Reusable-pattern review: the existing canonical local-integration skill already
covers exact source lifetimes, read-only verification, immutable verified delivery
and actual GUI-owner rechecks. This checkpoint adds project evidence/limits, not a
new global rule or generated skill edit. No available Claude session tool was
identified; this shared ledger remains the continuation handoff.

Final documentation-profile gate: **52 passed in 1.48 s**, total **4.4 s**;
privacy/Ruff and whitespace checks pass. Log:
`build/lineage-bound-originals-docs-20261113.log`. All test process handles from
this checkpoint are terminal; no background full-suite run was started.


## Bound Lineage archive/history integration - 2026-11-13

A real isolated backup of the staged bound projection failed before the change:
`Unsupported research schema must be enrolled before backup` (1 failed, 4.41 s).
The projection also retained only its latest operation, so retirement could lose
earlier portable report content. This checkpoint adds immutable caller-savepoint
history and archive-only typed validation, not positive network admission.

`lineage_projection.initialize_in` explicitly creates
`research_lineage_sync_history(operation_id, entity_id, operation_json)` alongside
its existing staging tables. `write_in` records exact operations in the same
savepoint as the canonical row/current marker, rejects changed-payload reuse and
keeps prior puts after hide/retirement. Normal live journal validation still
refuses Lineage frames. No new writer/task/UI/service admission was activated.

The recovery registry now recognizes current projection and immutable history.
`lineage_recovery.BoundRecords` joins exact archived operations, fixed ordered
paper identities, actual local aliases and original-file versions by their pinned
file incarnation/workspace/paper parent. Visible canonical content/fingerprint
must match; hidden/deleted state cannot silently resurrect a report. Existing
recovery verifies the entire original-byte closure. Historical pins stay archived
after source restoration; they do not become active source grants.

Detached restoration installs scientific canonical rows and verified objects, but
keeps both protocol tables in recovery_records. It installs no old Lineage
projection/device/sync binding. A complete immutable history, local paper mapping,
original incarnation and PDF closure are required even when ZIP/table hashes are
valid. The owned BlobStore argument remains explicit.

Component evidence before the final affected union:

- History plus prior projection: **21 passed in 75.09 s** (4 new history cases).
- The first new archive fixture omitted the existing mandatory BlobStore input;
  it correctly failed. Supplying the fixture-owned store produced **1 passed in
  2.77 s**. No production ownership requirement was relaxed.
- Archive/tamper/hide/retire/source restoration component: **11 passed in 34.07 s**.
- An expanded component reached **13 passed, 1 failed in 43.53 s**: native target
  observation correctly refused a not-yet-enrolled staged Lineage target. The
  test now explicitly models an incoming typed archive update from fresh verified
  sources, not native authority to publish that existing target. It asserts normal
  live canonical admission still refuses. Revised old/new-source and equal-byte
  cases: **2 passed, 13 deselected in 10.03 s**.

The receiving callback remains manually staged; these tests do not establish an
accepted Lineage event or completed native publisher. Typed fresh editable
Lineage ownership, sharing/snapshot/mobile closure, desktop integration, the
matching final full check and external device/cloud acceptance remain open.
All PDFs/workspaces/service data are synthetic. No account, paid call, owner
research, current release or GCP resource changed. No commit or push.

Reusable lesson review: the canonical local-integration skill already separates
retained historical evidence from active ownership and requires caller-owned
atomic writes. This checkpoint records project evidence/limits rather than
promoting another global rule. The shared ledger remains the Claude handoff;
no available Claude session tool has been identified.


Final affected archive/projection/source/adoption/provenance/budget union:
**183 passed in 521.14 s**, zero skips; total **524.8 s**. Privacy scan and Ruff
pass. Exact ignored log: `build/lineage-bound-recovery-integration-20261113.log`.
Command: `python scripts/check.py --profile focused --python
 tests/test_lineage_projection_history.py tests/test_lineage_projection.py
 tests/test_lineage_bound_originals.py tests/test_lineage_bound_recovery.py
 tests/test_lineage_recovery.py tests/test_lineage_recovery_history.py
 tests/test_sync_recovery.py tests/test_sync_recovery_fs.py
 tests/test_recovery_adoption.py tests/test_recovery_adoption_history.py
 tests/test_recovery_provenance_schema_budget.py
 tests/test_recovery_archive_schema_budget.py tests/test_later_outcome_recovery.py`.
The union contains 4 new immutable-history cases and 15 new bound-archive cases;
prior component counts overlap and must not be added as separate coverage.

Automatic review rejected an optional README-tail rewrite because truncating at
a phrase could discard substantial existing/uncommitted documentation. That
command never launched; README contents were verified unchanged by the rejected
operation. No indirect retry was made. Existing added API/limits links remain;
this optional cleanup does not block archive validation or deployment planning.

Final documentation-profile gate: **52 passed in 1.40 s**, total **4.1 s**.
Privacy/Ruff and whitespace checks pass. Exact ignored log:
`build/lineage-bound-recovery-docs-20261113.log`. All process handles started
by this checkpoint are terminal. The accumulated revision still needs its final
full check; no commit, push, deployment, installer or release was produced.


## Portable mobile Lineage read path - 2026-11-13

Source inspection found that the allowlisted SQL read projection did not include
saved Lineage. New `lineage_read_projection` attaches full validated reports to
actual registered portable paper owners, with explicit nonempty/unique `lineage`
required capability. Source schema-v1 now refuses nonempty saved Lineage instead
of silently omitting it. The existing record/byte budgets include every corpus.
Reads remain SQL-only and read-only, with no PDF/model/identity/outbox operations.

Mobile `lineage.mjs` mirrors closed report/set/owner/hash/location/uncertainty
validation, reusing the existing claim normalization/hash/location/text primitives.
`domain.validateProjection` retains the full scientific body and rejects unsupported
capabilities, bad/ambiguous owners and malformed reports before storage changes.
Actual Python-generated reports import through Node Engine without cursor/graph/
outbox/source authority, while retaining drafts and exact nonempty quotations.

The overview now calls a bilingual saved-only `lineage-view` component. Native
44px disclosure controls show prior/current/later stages, proposed roles and
judgments, original quotes, location states, missing evidence and source versions.
All research is text nodes; there is no unchecked link, source activation or model
button. The v17 service-worker shell caches both new static modules. Two existing
version-sensitive expectations were updated, not weakened: old-shell removal now
also asserts removal of v16 while preserving the research cache.

Evidence:

- Independent closed codec: **21 Node cases passed**.
- Initial capability/coexistence/static-shell selection: **57 passed**.
- New Python read path plus actual Node Engine interop: **8 passed in 32.28 s**.
- A localization test correctly caught newly written Chinese labels reduced to
  question marks by a Windows ASCII stdin pipeline (**43 passed, 1 failed**).
  Only new copy was rewritten through explicit UTF-8 with ASCII Unicode escapes.
  Exact code points and every new Chinese caption/error now reject replacement
  question marks. Corrected component: **44 passed**, then one unavailable-peer
  evidence case was added and passed in the final complete mobile suite.
- Final affected gate: **87 Python cases passed in 111.71 s**, all **580 mobile
  Node cases passed** and all **13 existing Python/HTTP integration programs
  passed**; zero skips. Mobile phase 41.1 s; total **156.0 s**. Privacy and Ruff
  pass. Exact ignored log: `build/lineage-mobile-read-integration-20261113.log`.
  The gate includes 45 new Node cases and 8 new Python cases; earlier component
  selections overlap and must not be added as release coverage totals.

Command: `python scripts/check.py --profile focused --python
 tests/test_lineage_read_projection.py tests/test_sync_projection.py
 tests/test_sync_projection_v2.py tests/test_sync_reading_state_projection.py
 tests/test_sync_ordering_projection.py tests/test_sync_document_projection.py
 tests/test_reading_position_projection.py tests/test_document_projection_handle.py
 --mobile`.

Actual browser verification was attempted against an isolated loopback fixture.
Both tab creation and browser inventory returned "The browser access host is
unavailable". No browser interaction or screenshot was possible; the CUA portion
was explicitly closed, and the owned fixture server was stopped and its terminal
exit confirmed. The preserved preview was updated to current static files. No
visual/keyboard/reduced-motion, phone or Mac acceptance is claimed by Node DOM
structure tests. No native user app/account or personal browser was controlled.

This closes the saved-metadata/read-card path only. Live Lineage operations,
original-source activation, fresh editable enrollment, sharing closure, desktop
integration, analysis audit, final whole-repo validation, installers and real
cloud/device acceptance remain open. No real research, credentials, paid AI,
GCP resources, commit, push or release changed. Existing canonical local-integration
rules already cover read-only verification and authority separation; the UTF-8
lesson applies the existing encoding rule. No global rule or generated skill copy
was promoted. This shared ledger remains the available-Claude handoff.


Final schema-object hardening: inspection found the new presence predicate could
recognize a view while the budget preflight counted tables only. `present` now
refuses unsupported non-table schema objects before data reads. A real same-named
view regression preserves the underlying scientific row and all database bytes;
this is this contract's stored-table requirement, not a universal ban on views.

Final rerun after that source guard changed: **88 Python cases passed in 114.04 s**,
all **580 Node cases passed** and all **13 existing Python/HTTP programs passed**;
zero skips. Mobile phase **39.4 s**; overall **156.3 s**. Privacy and Ruff pass.
Exact ignored log: `build/lineage-mobile-read-final-20261113.log`, with the same
command above. The final gate contains 9 new Python and 45 new Node cases.
The preceding 87-case gate is intermediate overlapping evidence, not another
release coverage total. No source edits followed this final integration gate.

Initial documentation-profile gate before this final evidence update: **52 passed
in 1.61 s**, total **4.4 s**; log `build/lineage-mobile-read-docs-20261113.log`.
All owned preview/integration process handles are terminal. The complete accumulated
repository check is still required before committing/pushing or declaring the
full objective complete. No live Lineage write/admission capability was enabled.

Final documentation-profile receipt: **52 passed in 1.73 s**, total **4.5 s**;
privacy/Ruff and whitespace checks pass. Log:
`build/lineage-mobile-read-docs-final-20261113.log`. No checkpoint process is
still running, and no commit, push, installer or deployment was produced.


## Source-complete Lineage package codec and legacy data-loss refusal - 2026-11-13

Actual bug: legacy `bundle.export` did not include stored Lineage. An isolated
published report/list was exported without a refusal, replacing a previous output
with an incomplete package. A new behavioral regression reproduced `DID NOT RAISE`
before the guard (**1 failed in 3.26 s**). Its earlier setup used `closing` on the
store context manager and failed before reaching the product; corrected only the
fixture context usage, preserving all assertions. That setup failure is not a
product regression.

The legacy export now refuses selected Lineage before publication, leaving prior
output unchanged. Incoming Lineage table/source markers also refuse rather than
being silently ignored. Ordinary supported package content is unchanged. Corrected
boundary component: **2 passed in 3.02 s**, later expanded to three cases.

Added `lineage_packages`, an independently staged content-only collector/codec.
It captures exact selected-focal reports and actual full selected/context paper
rows, including off-list peers, with no automatic list membership expansion. It
uses existing native local/bound original readers, immutable verified bytes and
process-local metadata/source proofs. Final `check_export` guards native database,
report/context and all original ownership; same-byte source restoration does not
revive old export permission. Returned metadata are defensive copies; native
observations, graph/device identities and receipts are not serialized.

The standalone ZIP validator rereads bounded actual manifest/tables metadata,
checks ordered exact source declarations, canonical owner paths, hashes, sizes,
all actual PDF pages and every claimed located quote with the maintained evidence
locator. Rehashing a false quotation or page count still fails. Unavailable peers
stay context without invented files; a separate current primary PDF stays intact.
Cancellation, source/metadata mutation, malformed ownership and resource bounds
return no partial admission. The decoder is data validation, not receiver grants.

Initial standalone validation incorrectly reused canonical artifact `read_json`
for list-package metadata, rejecting ordinary indented JSON (**1 failed in 5.29 s**).
The parser now accepts ordinary UTF-8 JSON formatting while rejecting duplicate
keys, nonfinite values, non-integer format and duplicate capabilities. This preserves
the existing list-package format; no artifact-wire validator/test was weakened.
The corrected first component was **4 passed in 15.13 s**; expanded unbound
component **20 passed in 48.37 s**; then local/bound/boundary/cancellation union
**26 passed in 60.24 s**. Counts overlap.

Final affected gate, including an added unavailable-peer preservation case:
**111 passed in 268.19 s**, zero skips; total **272.6 s**. Privacy scan and Ruff
pass. Exact ignored log: `build/lineage-package-codec-integration-20261113.log`.
Command: `python scripts/check.py --profile focused --python
 tests/test_lineage_packages.py tests/test_lineage_packages_bound.py
 tests/test_lineage_bundle_boundary.py tests/test_bundle.py
 tests/test_bundle_capabilities.py tests/test_bundle_offline.py
 tests/test_bundle_documents.py tests/test_package_import.py
 tests/test_later_outcome_bundle.py`.
This contains 27 new collector/codec/boundary cases, plus existing supported
legacy, offline, document, capability and observed enrolled-import paths.

The intended user sharing workflow is still incomplete: no live export/import
capability was enabled for Lineage. Next implement observed fresh receiver mapping,
source ownership, conflict/retry handling, imported-report reading and recovery,
then connect the same adapter to normal list UI/CLI/MCP operations. The temporary
refusal is data-loss prevention, not the completed feature. Live Lineage shared
operations, desktop integration, analysis audit, final whole-repo gate, installers
and cloud/real-device acceptance remain open.

All PDFs, data and providers were simulated fixtures. No owner database, account,
paid AI, cloud resource, current release, commit or push was touched. No background
process from this checkpoint remains live. The existing canonical local-integration
skill already separates content from authority and requires bounded observed
handoffs; these are project-specific evidence/limits, not a new global rule or a
fake transferable grant. This ledger is the shared continuation/Claude handoff.


## Receiver Lineage package mappings - 2026-11-13

Added the independently staged `lineage_package_targets` component. It validates
actual ZIP/PDF content before observing an explicit receiver database, requires
an exact injective mapping for all selected source papers, and remaps only the
local report owner and paper bindings. Report text, evidence/source IDs, quoted
passages, judgments, provider metadata and content hashes are preserved. Original
source descriptors retain sender archive paths and do not grant receiver file
ownership. Observations include current paper metadata, actual native parent
lifetimes, database identity and composite target rows, including target absence.

`check_in` requires the caller transaction, refuses changed/deleted/recreated
owners, different/replaced databases, newly added/edited/deleted report targets,
invalid schema and workspace enrollment, and never commits earlier caller work.
Existing differing rows are returned for review; this component never installs
research or replaces a conflict. Mutable metadata access returns defensive copies.
Bound/synchronized receivers remain refused until compound source admission exists.
The component requires existing receiver papers/lifetimes: first import into an
empty library still needs the enclosing identity/create transaction integration.
Do not commit skeleton paper rows to work around that missing boundary.

First isolated receiver component: **20 passed in 94.34 s**. A separate added
caller-mutation test reproduced an actual race (**1 failed, 20 deselected in
4.59 s**): changing caller metadata after observation affected the prepared
mapping/source declarations. The worker now owns independent JSON/mapping values
before validation. No test was deleted, skipped or weakened.

Final affected gate: **48 passed in 207.44 s**, zero skips; privacy and Ruff pass;
**210.5 s** overall. Exact command: `python scripts/check.py --profile focused
--python tests/test_lineage_package_targets.py tests/test_lineage_packages.py
tests/test_lineage_packages_bound.py tests/test_lineage_bundle_boundary.py`.
Ignored log: `build/lineage-package-targets-integration-20261113.log`.
There are 21 new receiver tests; counts overlap earlier package checks, not a
whole-release test total. Setup of real synthetic publications/PDFs took most
of this run (slowest setup 6.00 s), rather than live provider/network work.
An initial ordinary Ruff invocation could not create its cache under the active
checkout's read-only sandbox; the approved check and a read-only no-cache Ruff
both ran, and the final approved check passed. This is not an application failure.

The earlier package-codec documentation check is now confirmed terminal:
**52 passed in 2.02 s**, total **5.5 s**;
`build/lineage-package-codec-docs-20261113.log`. It is overlapping documentation
validation and does not certify the subsequent product revision.

No owner research, real accounts/providers, cloud resources, installed app,
release, commit or push changed. Tests use temporary workspaces/synthetic PDFs.
The full accumulated revision still needs a coherent complete gate before commit.
No available tool exposed a managed Claude session for direct handoff; the shared
status/contract/ledger remain the continuation handoff. This is not evidence that
no Claude process exists. The canonical local-integration skill already covers
observed ownership, caller transactions and content/authority separation; this
checkpoint adds project evidence, not a new global rule or generated skill copy.
Next implement atomic fresh receiver identity creation plus imported original
ownership/reading/recovery, then connect list sharing and live Lineage operations.

Receiver documentation gate: **52 passed in 1.40 s**, total **4.1 s**;
`build/lineage-package-targets-docs-20261113.log`. Whitespace check passed.
All processes started for this receiver checkpoint are terminal. A documentation
write briefly introduced whole-file README newline churn; its tracked LF style
was restored without deleting text. No additional source change followed the
48-case gate. The receipt append does not change the tested product inputs.


## Fresh receiver transaction and immutable byte handoff - 2026-11-13

The previous receiver convenience path opened its own read-only connection and
could not see papers just created in an enclosing import transaction. Added
`lineage_package_targets.validate` and `observe_in`, using the same target guards
and exact mapping contract. Validation/real PDF parsing happens on an owned worker
before SQL. The native `ValidatedPackage` retains size/hash-rechecked immutable
PDF bytes and scientific/source data; its separate seal binds those exact byte
objects. Every archive source path is rechecked before equal-hash data may share
memory. It creates no file, SQL row, parent lifetime, source grant or AI receipt.
A closed/deleted/replaced ZIP is not reopened as an implicit source later.

`observe_in` requires the actual caller transaction and its pre-connection native
identity. It sees existing plus newly inserted paper rows/lifetimes on the same
connection, and parses/hashes no PDFs. It neither creates those paper rows nor
commits them. Existing `check_in` works on the resulting target lease. Other
connections cannot see new rows before commit; rollback removes papers/list/
membership/lifetimes together; later recreation of equal IDs cannot reuse the
old lease. Cancellation/invalid proof/binding/native identity leaves caller work
uncommitted for caller rollback. Empty content is a no-op. This is the data/target
handoff prerequisite, not completed source-preserving scientific import.

Initial test setup used guessed `lists.title`/`list_items` names instead of the
actual `lists.name`/`list_papers` schema; **1 failed in 3.21 s** before reaching the
product. Corrected fixture SQL and an observed-row assertion key to their actual
shapes; retained all intended assertions. The corrected first component was
**10 passed in 46.22 s**; after immutable bytes/tamper checks, **13 passed in
71.66 s**. Later empty and mixed-owner cases bring this new module to 15 cases.
These numbers overlap the final gate and are not release totals.

First complete affected selection: **63 passed in 265.13 s**, total **269.5 s**;
zero skips, privacy and Ruff pass. Log:
`build/lineage-package-transaction-integration-20261113.log`.
The slow report showed repeated sender setup taking up to 5.78 s for receiver-only
cases. Added `tests/lineage_package_fixture.py`: one real synthetic sender ZIP per
receiver test module, built with the maintained publication/export and fake model.
Each case copies bytes and parses fresh metadata, with its own receiver database,
SQL lifetime, files, observations and byte proof. Native sender/export tests keep
their own native fixtures. A one-off AST comparison verified every Assert node in
both changed receiver modules was identical before/after fixture refactoring.
No assertion/case was deleted, skipped or loosened. Two import-order Ruff failures
stopped the first optimized check before tests; fixed ordering only, then reran.

Final same-scope optimized check: **63 passed in 141.68 s**, zero skips; privacy
and Ruff pass; total **145.3 s**. Exact command:
`python scripts/check.py --profile focused --python
 tests/test_lineage_package_transaction.py tests/test_lineage_package_targets.py
 tests/test_lineage_packages.py tests/test_lineage_packages_bound.py
 tests/test_lineage_bundle_boundary.py`.
Log: `build/lineage-package-transaction-optimized-20261113.log`.
This is test-fixture runtime evidence, not an application performance benchmark or
full-repo release gate. The first optimized import-order failure remains recorded
in `build/lineage-package-transaction-final-20261113.log`.

The contract now includes a task-oriented regression map explaining observable
outcomes instead of only counts. The shared implementation handoff's stale active
checkout instruction now names `Paperfact-develop`/`develop/0.5`; other checkouts
remain independent. No managed Claude session tool was newly available. Shared
contract/status/ledger are the handoff, not a claim of direct Claude execution.

Remaining next integration: publish verified originals with fresh import
provenance (not fake AI generation/candidate records), write scientific rows and
all-original ownership atomically with retry/conflict receipts, close imported
original reading plus backup/re-export, and then enable normal sharing and live
Lineage operations. The target/byte handoff itself grants none of these. The
broader 0.5 analysis audit, complete gate, installers, cloud and real-device
acceptance remain open. No owner research, credentials, paid provider, cloud,
current app/release, commit or push changed. The existing canonical local-
integration skill already specifies the single caller transaction and pinned
source/content-authority boundary; this checkpoint records its project-specific
application, not a new global rule or generated skill change.

Fresh-transaction documentation gate: **52 passed in 1.53 s**, total **4.6 s**;
`build/lineage-package-transaction-docs-20261113.log`. Whitespace check passed.
All worker/check handles started in this checkpoint are terminal. No product
source changed after the final 63-case optimized gate; this receipt only records
completed evidence. A coherent full check remains required before commit.


## Staged native Lineage report/source publication - 2026-11-13

Active checkout/branch/HEAD reconfirmed `Paperfact-develop`, `develop/0.5`,
`aa4b30e` plus preserved uncommitted work. Added `lineage_package_publish` without
normal package, desktop, CLI/MCP, provider or sync registration. This is the next
write component, not a completed public source-preserving import workflow.

The worker's native staged proof binds the existing validated immutable byte
package, explicit receiver mappings, canonical UUID action ID, database identity
and independently hashed/versioned winning source files. Byte publication uses
exclusive local links and owned temporary-file cleanup; damaged existing files
are refused rather than overwritten. Cancelling can leave unowned verified
cache bytes. These create no SQL receipt or reading/replay authority.

The actual caller transaction observes existing/new receiver owners, then the
publisher checks its exact native package, mapping, parent lifetimes, paper
metadata, target observations and file versions. Within one owned savepoint it
writes all six scientific row fields, fresh receiver-only generic original
associations and `research_lineage_imports(request_id,body_json)` native action
provenance. It reads/parses/hashes no PDFs under SQL, publishes no files there
and never commits outer paper/list/membership work. No generation request,
completion, candidate or sender-native device/graph identity is fabricated.

Default conflicting content is kept. Explicit replacement retains displaced
scientific rows in the action body and keeps earlier native import/source history.
An identical action retry verifies current reports plus every actual SQL source
association. Changed payload/lifetimes/mapping under a reused ID refuses; an old
successful action cannot replay over a later local edit. A new deliberate import
uses a new UUID. Source associations bind that action, focal/corpus/source and
receiver native lifetime. The closed archival decoder verifies complete ordered
sources, full cohort lifetimes, types and canonical JSON; recomputing a record
fingerprint cannot transfer the focal original to another selected peer.

25 initial publication tests include success/retry, outer rollback/new-paper
rollback, SQL trigger failure after earlier child writes, default/explicit
conflicts, changed-payload retries, stale/cancelled sources, exact native schema
and primary-key enforcement, history/source/action/corpus budgets, empty content,
unowned staging cleanup and no PDF reads under SQL. Actual AFTER INSERT fixture
triggers interrupt after an earlier source association: cancellation or file
mutation must remove all child report/source/receipt writes while preserving
uncommitted caller work. Tests use independent receivers and the immutable real
synthetic sender fixture; no real model/account/cloud calls.

The first component reached successful publication, then its test incorrectly
called fresh-observation/retry from the main thread and hit the intended
`worker_required` guard (**1 failed in 4.84 s**). Moved that retry, with its owned
connection, into the real test worker; no product guard or assertion was weakened.
The corrected expanded component: **17 passed in 26.13 s**. Added table-shape,
late interruption, receipt-rehash, budget and empty tests before the larger gate.
Initial Ruff import-order/style/long-SQL-string issues were fixed before that gate.

Affected gate: **88 passed in 124.59 s**, zero skips; privacy/Ruff pass;
**127.9 s** overall. Command: `python scripts/check.py --profile focused --python
 tests/test_lineage_package_publish.py tests/test_lineage_package_transaction.py
 tests/test_lineage_package_targets.py tests/test_lineage_packages.py
 tests/test_lineage_packages_bound.py tests/test_lineage_bundle_boundary.py`.
Log: `build/lineage-package-publish-integration-20261113.log`.
Counts overlap earlier package/target checks and do not certify the whole release.

One additional regression verifies the current backup entry point refuses the
unregistered import history, creates no partial archive and changes no research:
**1 passed in 2.62 s**, raw pytest node selection, log
`build/lineage-package-publish-recovery-boundary-actual-20261113.log`.
An initial attempt incorrectly passed `-k` to `scripts/check.py`, which rejected
that unsupported option before running any test; corrected to direct pytest node
selection rather than changing the harness. The publisher module now has 26 cases
across those overlapping receipts. No product source changed after the 88-case gate.
The temporary backup refusal is a gate, not the intended completed backup behavior.

Next close imported-original reading, exact re-export and full current/displaced
import archive closure, then detached/fresh editable recovery and actual list
entry points. Only then activate normal sharing; bound receivers still require
compound source/content journal operations and native cursor/retry handling.
The broader analysis audit, final coherent whole-repo gate, installers, hosted
pilot and real Windows/Mac/phone acceptance remain open. No commit, push, release,
owner database, real credential/provider or cloud resource changed. The existing
canonical local-integration skill already covers separate file publication/
ownership, one caller transaction and retry intent; this checkpoint is validated-
local project evidence, not a new global rule or generated skill change.

Native-publication documentation gate: **52 passed in 1.57 s**, total **4.4 s**;
`build/lineage-package-publish-docs-20261113.log`. Ruff for the current publisher/
test file and whitespace checks pass. All handles started in this checkpoint
are terminal. No product source changed after the 88-case gate; the subsequent
backup-boundary case was separately executed successfully. A coherent full gate
is still required before commit.


## Native imported originals and three-receiver re-export - 2026-11-13

Previous checkpoint was progress: native report/source/action receipt publication
and its exact checks were completed locally. Current branch/HEAD reconfirmed
`Paperfact-develop`, `develop/0.5`, `aa4b30e` plus preserved uncommitted changes.
No normal bundle, desktop, CLI/MCP, provider or sync Lineage admission was enabled.

Added the dedicated `lineage_import_originals` reader and bounded
`lineage_package_publish.current_in` native receipt lookup. The reader requires
the actual loaded owner, exact current scientific row, latest matching closed
native action, actual selected report cohort lifetimes and every exact source
SQL association. It verifies owned PDF bytes off-lock, retains immutable native
snapshots and rechecks current metadata plus identical loaded-view object at
actual delivery. Missing originals cannot be satisfied by a newer primary PDF;
no model, download, source grant, fake AI candidate/request or archive adoption
is performed. Read-only connections close explicitly and tests assert unchanged
actual database bytes. Declared unavailable peers remain unavailable.

Per-report cohort checking matters when one action imported multiple reports.
A deleted peer belonging only to another cohort does not invalidate valid sources
of the selected report; that damaged cohort itself refuses. Exact receipt-bound
source reading is separate from semantic verification of research interpretation.
A caller/controller still owns its real window lifetime and closing barriers.

The staged collector chooses imported/local/bound readers per report and retains
that kind in the final proof check. Mixed local/imported reports on the same paper
can no longer leak a sticky imported-reader selection into a locally generated
corpus. The end-to-end synthetic journey exports the imported report/originals,
validates the actual ZIP, imports into a third fresh receiver and reads all three
exact originals using fresh native associations. Serialized metadata contain no
sender action/source-owner/lifecycle grant. Actual selected/context rows, report
content, quotes and historical generation metadata remain intact.

First reader component: **25 passed in 18.53 s**. Independent batch-cohort,
unavailable-peer and mixed-provenance cases expanded it to **28 passed in 26.94 s**.
A later strict malformed-record test reproduced raw `sqlite3.OperationalError:
malformed JSON` (**1 failed in 2.68 s**) from valid top-level JSON containing a
wrongly shaped report item. The lookup now catches that SQLite JSON-record error
and raises a bounded domain ValueError; it neither selects a fallback nor writes
repair records. No assertion, case or guard was weakened. The new reader module
now has 29 cases. Initial unused test imports were removed before the final gate.

Final affected gate: **118 passed in 142.18 s**, zero skips; privacy and Ruff pass;
total **145.1 s**. Exact command:
`python scripts/check.py --profile focused --python
 tests/test_lineage_import_originals.py tests/test_lineage_package_publish.py
 tests/test_lineage_package_transaction.py tests/test_lineage_package_targets.py
 tests/test_lineage_packages.py tests/test_lineage_packages_bound.py
 tests/test_lineage_bundle_boundary.py`.
Ignored log: `build/lineage-import-originals-integration-20261113.log`.
Counts overlap earlier checkpoints, not whole-release totals. No product source
was changed after this final affected gate.

Remaining next boundary: complete current/displaced native import archive closure,
lossless detached backup/restore and reviewed fresh adoption, then normal list
entry points and bound compound source/content operations. The existing backup
refusal for unregistered import history still passes and is temporary protection,
not completed backup support. Wider analysis audit, complete coherent full gate,
installers, GCP hosting and real Windows/Mac/phone acceptance remain open.
All research/provider data are synthetic isolated fixtures. No owner database,
real credential/account/provider, paid call, cloud, current app/release, commit
or push changed. There was no managed Claude session exposed for direct handoff;
these shared contract/status/ledger files are the continuation handoff. The
existing canonical local-integration skill already requires exact pinned-source
and current-owner checks, not cache fallback; this is validated-local evidence
of that established rule, not a manufactured new global skill or generated copy.

Imported-original documentation gate: **52 passed in 1.39 s**, total **4.3 s**;
`build/lineage-import-originals-docs-20261113.log`. Whitespace check passed.
All handles started for this checkpoint are terminal. No product source change
followed the 118-case gate; this append records finished documentation evidence.
The complete accumulated revision still requires its coherent full gate before
commit, packaging or release claims.


## Imported Lineage source/history archives and detached restore - 2026-11-13

Previous turn was progress: exact receipt-bound original reading and actual
three-receiver re-export passed its affected gate. Current active branch/HEAD
were revalidated as `Paperfact-develop`, `develop/0.5`, `aa4b30e` plus preserved
uncommitted continuation work. This checkpoint adds actual recovery support,
without normal list/CLI/MCP/desktop Lineage admission or cloud/release changes.

Added `lineage_import_recovery.ImportRecords` and the two-column native action
table to the explicit recovery protocol registry. The adapter validates unique
closed actions, metadata budgets, exact SQL original associations and complete
blob references. Current and displaced scientific reports retain all original
versions. Displaced data require actual retained selected-paper/hash provenance,
not a loose equal-hash file belonging to another paper. Historical lifetimes
remain data; no active receiver or replay authority is inferred. Canonical rows
still obey the outer archive's actual-paper owner checks. The import-specific
source budget applies only when imported actions exist, preserving unrelated
legacy backup behavior.

Extracted `lineage_packages.verify_original` from its existing page/located-quote
verifier, and reused it in archive closure validation. Each distinct imported PDF
is hash/size/page/quotation checked across both current and displaced history.
The caller owns aggregate limits: list-package limits remain list-specific;
whole-workspace recovery keeps its existing 8 GiB limit. Quote location checks
do not make proposed research interpretations independently verified facts.
No model, URL, account or source adoption is called by archive validation.

Actual restore keeps current science as research and old native import/source/
lifecycle records in `recovery_records`, with verified PDFs under `objects/`.
No live import/source/device/generation table is installed. Normal first-open
initialization may create fresh local paper epochs; even then, the native source
reader refuses archived old receipts. Reviewed fresh editable adoption remains a
separate next boundary. Retired report history can retain a deleted peer's PDF
without recreating its paper row or source authority. Current canonical reports
continue to require actual selected paper rows rather than weakening that guard.

Initial positive test completed backup/inspect/restore, then incorrectly used the
observe-existing-owner helper before a detached workspace had fresh lifetimes
(**1 failed in 4.34 s**). Corrected the fixture to the app's real first-open
`capture_owner` API; no source/grant guard changed. The initial recovery component
then passed **8 cases in 11.52 s**. A new different-PDF helper initially lacked a
module import (**1 failed, 8 passed in 27.18 s**); fixed that test import only.
The four new version/rehash cases passed **4, 8 deselected in 25.82 s**.

The previous temporary unsupported-import-history test now asserts the requested
complete preservation behavior: actual archive inspection, exact action/original
bytes and unchanged source SQL. Its data-preservation assertions remain and are
stronger than a refusal-only outcome. Unknown future schema rejection is covered
separately. No test was deleted, skipped or loosened to hide data loss.

Affected shared gate: **230 passed in 490.95 s**, zero skips; privacy/Ruff pass;
**509.2 s** overall. Exact command:
`python scripts/check.py --profile focused --python
 tests/test_lineage_import_recovery.py tests/test_lineage_recovery.py
 tests/test_lineage_recovery_history.py tests/test_lineage_bound_recovery.py
 tests/test_sync_recovery.py tests/test_legacy_source_recovery.py
 tests/test_later_outcome_recovery.py tests/test_recovery_adoption.py
 tests/test_recovery_provenance_schema_budget.py tests/test_recovery_record_schema_scope.py
 tests/test_recovery_archive_schema_budget.py tests/test_lineage_packages.py
 tests/test_lineage_packages_bound.py tests/test_lineage_package_publish.py
 tests/test_lineage_import_originals.py`.
Ignored log: `build/lineage-import-recovery-integration-20261113.log`.
Slowest case was an existing owned-backup/retry failure fixture, 8.38 s; these
fixture measurements are not real user-device performance or full release proof.

Two later tests, added after that gate began, ran separately with raw pytest
selection: **2 passed, 12 deselected in 7.66 s**. They prove retired history does
not revive a deliberately deleted peer and future unregistered research schema
still refuses without partial archive/SQL modification. Log:
`build/lineage-import-recovery-retired-20261113.log`.
The new module now has 14 cases across those receipts. Different old/new PDFs,
current and displaced false quotations and false page counts all use real bytes;
recomputed container/table/action hashes still cannot disguise wrong locations.
No product source changed after the 230-case gate. Counts overlap earlier gates.

Next complete reviewed fresh editable adoption of imported archive data, then
normal list operations and bound compound source/content operations with shared
Lineage admission. Saved-first desktop integration, wider analysis audit, final
coherent complete gate, installers, GCP pilot and actual Windows/Mac/phone journey
remain open. No owner research, current app/release, account, credential, paid
provider, cloud resource, commit or push changed. The shared contract/status/ledger
remain the independent-session handoff; no direct Claude execution is claimed.
Existing local-integration skill rules already separate archival data from native
source ownership and require exact original verification. This is validated-local
project evidence of those rules, not a new global rule or generated skill copy.

Imported-history recovery documentation gate: **52 passed in 1.47 s**, total
**4.2 s**; `build/lineage-import-recovery-docs-20261113.log`. Whitespace passes.
All worker/check handles started in this checkpoint are terminal. No product
source changed after the 230-case gate; the two added retirement/unknown-schema
cases were separately executed successfully. The complete accumulated revision
still requires a coherent full gate before commit, packaging or release claims.


## Fresh recovery originals and bounded input lifetimes - 2026-11-13

Status: staged local component, not public editable recovery activation. Current
integration remains `develop/0.5` at `aa4b30e` plus preserved continuation edits.

The native import stage now seals scientific metadata and verified file versions
without retaining its input `ValidatedPackage` or PDF buffers. Native stage
mutation still refuses. New `lineage_package_publish.observe_in` observes actual
receiver papers/lifetimes from that consumed proof in the caller transaction,
without reading/parsing/hashing PDFs or creating a source grant.

`lineage_recovery_sources.prepare` requires the actual sealed service inspection,
an independent unbound target and active current imported/generated source
cohorts. It reconstructs and verifies real originals in bounded off-SQL batches,
releasing each batch input before the next. `stage_in` verifies exact copied
paper/scientific metadata and establishes fresh local source ownership and native
import receipts under one savepoint across all batches. It never edits source
research, commits caller work or reactivates sender/generation/device authority.

First component iteration: cancellation correctly raised the existing `Cancelled`
signal; the test originally expected only generic errors (1 failed, 4 passed in
28.69 s). Fixed the test expectation, preserving cancellation semantics. The
next run reached the two-batch fixture and exposed missing test imports
(1 failed, 11 passed in 58.60 s). Added `zipfile` and the native target adapter;
no production guard was changed for these test setup errors. The unchanged source
component then passed 14 cases in 73.46 s. Its shared publisher input-lifetime
selection had passed 28 cases in 38.87 s before this checkpoint.

Affected shared gate: **167 passed in 353.60 s**, zero skips; privacy/Ruff
pass; **357.0 s** overall. Receipt:
`build/lineage-fresh-recovery-integration-20261113.log`. The process is terminal.
This includes all **15 recovery-source cases**, second-batch cancellation and
a successful SQL phase with PDF reads/parsing deliberately forbidden. Exact
command: `python scripts/check.py --profile focused --python
 tests/test_lineage_recovery_sources.py tests/test_lineage_package_publish.py
 tests/test_lineage_package_transaction.py tests/test_lineage_package_targets.py
 tests/test_lineage_import_originals.py tests/test_lineage_import_recovery.py
 tests/test_recovery_adoption.py tests/test_lineage_packages.py`.
Slowest reported case: `9.49s call     tests/test_recovery_adoption.py::test_actual_editable_copy_has_fresh_authority_complete_history_and_backup`. Case percentages are not time estimates;
fixture timings are not installed-device performance evidence. These counts
overlap earlier receipts and are not release totals. No source changed during
or after this shared gate. No real account, paid provider, owner research or
cloud resource was used.

The contract is documented in `docs/lineage-packages.md` and linked from README
and `docs/sync-recovery.md`. Documentation gate: 52 passed in 1.73 s, 4.8 s
overall, with privacy/Ruff passing; receipt
`build/lineage-fresh-recovery-docs-20261113.log` (before this ledger/status edit).
Scoped whitespace validation passes with native CRLF recognized; unrelated
existing line-ending changes remain preserved, not broadly rewritten.

Next integration must retain all old recovery provenance/historical bytes through
the baseline publisher, support compound Lineage source/content enrollment and
only then connect this preparation to public editable recovery. The public
blocker is intentionally unchanged. Bound archive cohorts still refuse here.
Normal bundle admission, live sync/source operations, desktop/mobile activation,
full accumulated release validation, installers, hosted GCP and physical Mac/
phone acceptance remain unfinished. No commit, push or release occurred.

Coordination: tool discovery exposes worktree management, not an available Claude
session messaging/launch interface. These shared contract/status/ledger files are
the handoff; no Claude execution or completion is claimed. Reusable-lesson review:
the existing canonical local-integration skill already covers exact bytes before
ownership and one transaction owner for compound writes. This is project-local
evidence, not a new global rule; no generated/global skill copy was changed.

Final documentation/status receipt: 52 passed in 1.54 s, 4.3 s overall;
`build/lineage-fresh-recovery-docs-final-20261113.log`. The receipt update script
initially read a PowerShell UTF-16 log as UTF-8 and stopped before writing the
ledger/status; corrected BOM-aware reading. This tooling error changed no source
or feature-test result. The subsequent documentation check below covers the
completed receipt edit; no feature rerun was needed for documentation-only edits.

Post-receipt documentation check: **52 passed in 1.83 s**, **4.8 s** overall;
privacy/Ruff pass. Log: `build/lineage-fresh-recovery-docs-receipt-20261113.log`.
All check handles started in this checkpoint are terminal. The accumulated
revision has not passed a new complete release gate; no commit, installer or
release claim is made.


## Public unbound Lineage list packages - 2026-11-13

Status: integrated development path; affected shared gate passed. Scope is
normal export and ordinary unbound import, not live Lineage sync activation.
The remaining enrolled-import/recovery/mobile/source-control scope is unchanged.

`bundle.export` now merges actual selected Lineage context into cited papers,
retains complete scientific rows and exact original descriptors/bytes, declares
the versioned capability, runs common/native validation and checks all source
proofs before replacing an earlier output. Off-list peers do not become members
or carry their unrelated notes. `bundle.import_` validates/stages originals before
SQL, then uses the existing caller transaction for receiver paper matching,
parent lifetimes, native report/source publication, list content and files. A
package fingerprint supplies retry identity. A main-thread CLI library caller
uses one owned worker; existing desktop background callers stay on their worker.
No provider/network/account operation is needed for Lineage preservation.

Same-ID focal/context records now require matching titles (case/whitespace only)
and the maintained paper identity compatibility rule within the write transaction.
Different papers refuse even with replacement requested. Compatible peers retain
their local notes and epoch. Default scientific conflicts preserve saved research;
explicit first replacement retains the displaced row. A completed package action
still refuses replay over later local edits; reviewed new intent/mapping UX is
remaining work. Enrolled package import rejects the unsupported scope before
research/outbox changes. No live Lineage service/schema admission was enabled.

The former temporary capability-refusal assertion now checks the explicit
capability and is paired with actual public roundtrip/preservation tests. The
previous-output and incomplete-source rejection assertions remain. This changes
the intended development behavior from refusal to exact preservation, rather
than weakening a test to hide missing content.

Evidence so far: 7 initial public/boundary cases passed in 22.16 s; expanded
concurrency/bound-refusal/source-mutation cases passed 10 in 37.72 s; default
import, explicit conflict/history, stale replay and workspace-switch cases passed
13 in 51.53 s. New identity fixtures initially omitted required venue/year/source
columns (1 failed, 10 passed in 50.98 s). Corrected fixture data, preserving all
schema constraints and product guards. Five collision/compatible-peer cases then
passed in 19.97 s, 10 deselected. The public journey module now has 15 cases, plus
3 boundary cases. These selections overlap and are not release totals.

The affected 14-file gate passed **233 cases in 322.75 s**, zero skips;
privacy/Ruff pass; **326.6 s** overall. Receipt:
`build/lineage-public-bundle-integration-20261113.log`. All handles started in this
checkpoint are terminal. Exact command:
`python scripts/check.py --profile focused --python
 tests/test_bundle.py tests/test_bundle_recovery.py tests/test_bundle_offline.py
 tests/test_bundle_capabilities.py tests/test_bundle_documents.py
 tests/test_reading_position_packages.py tests/test_later_outcome_bundle.py
 tests/test_package_import.py tests/test_lineage_bundle_journey.py
 tests/test_lineage_bundle_boundary.py tests/test_lineage_packages.py
 tests/test_lineage_package_publish.py tests/test_lineage_import_originals.py
 tests/test_lineage_import_recovery.py`.
All 18 public journey/boundary cases are included. No product/test input changed
during or after the gate. The slowest reported case was an existing distinct-PDF
archive replacement fixture (5.69 s); these are fixture timings, not a real-device
performance benchmark. Counts overlap earlier gates; no release-total claim.
Updated docs/distribution check passed 52 in 1.60 s, 4.5 s overall, privacy/Ruff
pass; `build/lineage-public-bundle-docs-20261113.log` (before this ledger edit).

Read the corrected `docs/lineage-packages.md` status/API/workflow and README/
sharing links. Next: close enrolled source/content registration, editable recovery,
reviewed import mapping/new intent and source UI; then freeze the complete
candidate for the full release gate and installed Mac/phone/GCP acceptance. The
current accumulated revision is not a complete-check/release receipt. No daily
app, owner research, credentials, paid service, cloud resource, commit, push or
installer was changed. No direct Claude interface was exposed; shared files are
the handoff. The current agent inventory shows only the root agent active.

Harvest review: existing canonical local-integration rules already cover retry
identity, compound transaction ownership, exact bytes before authority and
explicit paper matching. This is validated-local project evidence, not a new
universal rule; no generated/global skill copy was changed.


## Mobile typed Lineage consumer and actual browser checks - 2026-11-13

Status: consumer integration complete at the affected local-test boundary;
complete v0.5.0 and live authority admission remain unfinished. Integration is
still `develop/0.5` at `aa4b30e` plus preserved continuation work.

The mobile normal event path now understands the closed dependency-complete
Lineage envelope via `lineage-ops.mjs`. It checks actual ordered selected paper
parents, corpus/focal IDs, scientific body/source hashes, every available
original's exact file ID/incarnation and typed empty deletion. Known corpus/
parent identities cannot be stripped by an otherwise-valid generic deletion.
Source retirement hides the old scientific projection; restoring equal hashes
under new incarnations does not revive its old pins. Explicit current pins can
project again. Saved snapshots are suppressed per known corpus, not overwritten;
immutable raw receipts remain retained. Existing overview cards remain read-only.

The engine's store transaction owns receipt/content/outbox/cursor publication.
Invalid/stale pages and held jobs closed before delivery preserve durable drafts
and research. Repeated foreground sync shares the same job. File metadata never
grants local PDF bytes, changes the primary binding or invokes/downloads AI/data.
Six new failure reasons have English/Traditional-Chinese explanations. Shell v18
caches the new static module, never authenticated/research routes. The shell
revision expectations changed intentionally with the production cache revision;
no assertion was removed or loosened.

`tests/test_lineage_mobile_wire.py` builds actual native selected-PDF/source
operations and a fully verified three-original report through existing fixtures.
Node consumes those staged frames and preserves the complete report/projection;
mutated/reordered peer pins reject on both sides. Crucially the native live
canonical registry is still asserted to reject that frame. Synthetic accepted
Lineage events test the consumer contract, not real server acceptance. Existing
13 HTTP integrations cover already-admitted features, not live Lineage.

Initial new-module run passed 78 cases because importing the old test module
also registered its 45 cases. Extracted the unchanged pure data factory so full
suite counts do not duplicate old cases. This extraction omitted a hash import
(1 passed, 32 failed) and a previously referenced corpus constant (80 passed,
1 failed across both modules). Fixed the complete fixture import/export graph;
existing test bodies/assertions were retained. The final components pass all
81 cases: 45 existing and 36 new. Native cross-language cases initially passed
2 in 8.61 s; line-wrap lint findings were fixed before the shared gate.

Affected gate **94 Python cases passed in 230.10 s**, **616 Node checks passed**
(zero skips), and all **13 Python HTTP integration programs passed**. Mobile
stage 32.6 s; **266.1 s overall**, privacy/Ruff pass. Exact command:
`python scripts/check.py --profile focused --python
 tests/test_lineage_mobile_wire.py tests/test_lineage_wire.py
 tests/test_lineage_dependencies.py tests/test_lineage_projection.py
 tests/test_lineage_projection_history.py tests/test_lineage_bound_originals.py
 tests/test_lineage_shared_guard.py --mobile`.
Log: `build/mobile-lineage-receiver-integration-20261113.log`; handle terminal.
Counts overlap earlier receipts, not a complete release total. No production
input changed after this gate; the browser scenario was added afterward and
verified separately below.

Actual browser baseline: 6 existing scenarios passed in a fresh temporary
headless Edge profile. Extended browser fixture: **7 scenarios passed**, including
actual IndexedDB scientific reopen, stale-page rollback with drafts intact,
phone-width DOM clipping check, native disclosure focus/click, no unchecked PDF/
AI actions, static consumer cache, unchanged primary PDF metadata and stale-source
suppression across reload. Strengthened it to verify the same cards update/remove
on the actual app's Sync now control without reload; all 7 pass again.
`node mobile/browser-check.mjs <explicit-Edge-executable>`.
Logs: `build/mobile-lineage-browser-baseline-20261113.log`,
`build/mobile-lineage-browser-20261113.log`,
`build/mobile-lineage-browser-live-refresh-20261113.log`.
The browser scenarios share their deliberate synthetic story within one isolated
profile; no owner's profile/accounts or research are used. This is Windows Edge
at an iframe phone width, not Safari/iPhone/Android/Mac installed acceptance or
screenshot-based visual certification. Browser subprocesses and servers exited.

Contracts/status/README now distinguish the ready consumer from pending authority
publication, source/content enrollment, recovery and source controls. Next native
integration must preserve real compound source outboxes/receipts, hidden put
provenance, dependency-aware materialization and all conflict/lifecycle boundaries
before live schema/service admission. Do not infer admission from a mobile fixture.
Then complete enrolled import/recovery, provider/task/UI wiring, full accumulated
gate, installers, GCP private pilot and real Windows/Mac/phone journey. No owner
research, daily app/release, credentials, paid call, cloud resource, commit or push
changed. Shared files remain the independent-session handoff; no Claude run is
claimed.

Harvest review: immutable source lifetimes, metadata-versus-byte authority and
atomic cursor publication already exist in the canonical local-integration skill.
This is validated-local consumer evidence and an independently implemented
language boundary, not a new universal rule. No global/generated skill was edited.

Final documentation receipt: **52 passed in 1.80 s**, **5.1 s overall**,
privacy/Ruff pass; `build/mobile-lineage-receiver-docs-20261113.log`. All task
check/browser handles are terminal. A new coherent complete repository gate is
still required before commit/packaging/release; none is claimed here.


## Protected Lineage projection writer - 2026-11-13

Status: native protected-writer seam, not live Lineage admission. Integration
remains `develop/0.5` at `aa4b30e` plus preserved continuation work.

Before connecting the scientific writer, inspection found that its standalone
savepoint is forbidden by the journal's actual `_authorize_writer`. The new
behavior test demonstrates that `SAVEPOINT`, `COMMIT`, DDL and the standalone
wrapper remain rejected under this unchanged policy. `lineage_projection.apply_in`
now performs only bounded data writes under its caller's transaction/savepoint;
`write_in` retains its own savepoint for standalone callers. Neither grants source
bytes, commits caller work, creates schemas implicitly or writes journal/cursor
records. Caller-owned failure must propagate to its outer rollback boundary.

Visible publication now checks actual current desired original-file metadata and
all materialized selected-paper epochs before and after child writes. Missing,
retired, restored, wrong-incarnation and foreign-parent originals refuse before
publication. Late source retirement or paper replacement rolls back the row,
marker, immutable history and trigger side effects. Hidden puts retain their
original scientific/source provenance after retirement without acquiring a new
grant. PDF reads/parsing/hashing stay outside protected SQL.

The native fixture helper gained optional caller-connection and already-verified
report parameters; defaults preserve all old behavior/assertions. This lets a
real journal owner publish three actual source-file outboxes and the protected
scientific projection in one transaction, with PDF verification performed before
SQL. Injected late failure rolls back all three source operations and scientific
writes; success commits them once. No fake Lineage journal receipt was added
while schema/service admission remains gated.

Initial writer/projection/history component: **28 passed in 104.56 s**, including
7 new cases, before the late-input and compound-owner coverage was added. Final
new writer module: **12 passed in 48.12 s**, zero skips. Logs:
`build/lineage-projection-writer-first-20261113.log` and
`build/lineage-projection-writer-component-20261113.log`. Ruff passes.

Affected shared gate: **138 passed in 364.40 s**, zero skips; privacy/Ruff
pass; **368.2 s** overall. Log:
`build/lineage-projection-writer-integration-20261113.log`; handle terminal.
Exact command: `python scripts/check.py --profile focused --python
 tests/test_lineage_projection_writer.py tests/test_lineage_projection.py
 tests/test_lineage_projection_history.py tests/test_lineage_bound_originals.py
 tests/test_lineage_bound_recovery.py tests/test_lineage_packages_bound.py
 tests/test_lineage_dependencies.py tests/test_lineage_peer_sources.py
 tests/test_lineage_shared_guard.py tests/test_lineage_mobile_wire.py
 tests/test_sync_journal.py`.
All 12 new writer cases are included. Product/test inputs did not change during
or after the gate. Counts overlap earlier receipts and are not release totals.
This does not replace the existing mobile/browser receipts or a complete gate.
Documentation check before this receipt edit: **52 passed in 1.55 s**, **4.4 s**
overall, privacy/Ruff pass; `build/lineage-projection-writer-docs-20261113.log`.

README and the protected-writer contract identify the remaining native work:
complete SCI operation/outbox/receipt publication, explicit schema initialization,
dependency-aware receive ordering/visibility, preservation of hidden put history
and actual two-client conflict/retirement/recovery journeys. Only then register
live admission and finish enrollment/import/recovery, provider/task/UI wiring,
complete frozen gate, installers, hosted GCP and real Mac/phone acceptance. No
owner research, daily app, account, paid provider, cloud resource, commit or push
changed. Shared files are the independent-session handoff; no Claude execution
is claimed. Harvest review: this is a concrete validated-local application of the
existing single transaction-owner skill rule, not evidence to relax permissions
or install a new global rule. No generated/global skill was changed.

Concrete remaining native transfer gap: `FileTransfers.ready_to_push` currently
returns true for every non-file operation, and `SyncClient.sync_once` only adds
same-entity, structure, paper-parent and order dependencies to its deferred set.
It does not yet include Lineage original-file incarnation dependencies. If file
upload preparation defers an original, a future admitted Lineage child must not
be pushed prematurely and turned into an avoidable service conflict. Preserve
real obsolete-source conflicts rather than indefinitely treating them as upload
work. Add exact source readiness/causal deferral and tests for held/resumed
uploads before live admission; do not infer readiness from equal hashes or an
unverified acknowledgement. Source publication, transfer and acceptance are
separate boundaries. This finding is read from the current implementations, not
an implemented fix or a live-account incident.


## Exact original publication readiness ? 2026-11-13

Status: validated-local prerequisite; live native Lineage admission stays closed.
The previous transfer-gap finding above is superseded for preparation by this
entry. Complete native scientific outbox/receipt, dependency-aware receive,
trusted schema initialization, enrollment/import/recovery and desktop task/UI
work remain incomplete. No hosted/device or complete-release claim is made.

Two actual entry points previously returned true for this staged non-file
operation: `FileTransfers.ready_to_push` and desktop `AttachmentSteps.prepare`.
Dedicated before-fix repros each failed at `assert ... is False` with actual
native three-original publication fixtures. Logs:
`build/lineage-transfer-readiness-repro-20261113.log` and
`build/lineage-attachment-steps-repro-20261113.log`.

Both now dispatch recognized typed/source markers through
`lineage_dependencies.ready_to_push_in`. The strict staged codec, native journal
connection path, transaction and workspace/device are checked. For every exact
source creation incarnation, validate its real received accepted/conflict event
and exact original owner/parent/lifetime. Without that result, require a matching
native local source version and outbox, then defer. Unknown/foreign/malformed
publications fail rather than being reported as an upload in progress. Upload
markers and push acknowledgement sequence numbers cannot bypass received-result
waiting. The operation, source pins, outbox and transfer state remain unchanged
by this metadata-only predicate. It performs no file read, auth or network work.

Conflict completion releases transfer waiting, not graph authority. Actual native
competing-source conflicts and same-hash retirement/restoration preserve the
original obsolete pins and fail `active`; no retry silently selects a newer
source. A peer may use actually received original outcomes without uploading
again or copying a sender outbox. Typed retirement needs no originals. Desktop
preparation works with genuinely absent source/document path registrations;
fixture rows are removed and table absence asserted before its real constructor.

Verification (overlapping scopes, not additive release totals):

- Initial component: 9 passed in 42.17 s; subsequent coverage adds source conflict,
  received peer reuse and fixed transaction/database checks.
- Source/journal gate: **115 passed in 236.06 s**, 239.3 s overall, zero skips.
  Command: `python scripts/check.py --profile focused --python
  tests/test_lineage_transfer_readiness.py tests/test_lineage_dependencies.py
  tests/test_lineage_peer_sources.py tests/test_sync_files.py
  tests/test_sync_journal.py`.
  Log: `build/lineage-transfer-readiness-integration-20261113.log`.
  This preceded the common dispatch extraction and desktop hookup; their final
  behavior was rechecked in the next scope.
- Desktop/common predicate gate: **33 passed in 66.81 s**, 70.0 s overall,
  zero skips. Command: `python scripts/check.py --profile focused --python
  tests/test_lineage_transfer_readiness.py tests/test_lineage_attachment_steps.py
  tests/test_workspace_sync_files.py tests/test_workspace_sync.py
  tests/test_workspace_sync_edges.py tests/test_continuous_attachment_status.py`.
  Log: `build/lineage-attachment-coordinator-integration-20261113.log`.
- Final stronger missing-registration cases and documentation/check contracts:
  **52 passed in 7.24 s**, 10.0 s overall, zero skips. Command:
  `python scripts/check.py --profile focused --python
  tests/test_lineage_attachment_steps.py tests/test_usage_docs.py
  tests/test_check_script.py`.
  Log: `build/lineage-source-readiness-docs-final-20261113.log`.

Every gate's privacy scan and Ruff passed. A first gate stopped at a new test's
nested-context style lint; contexts were combined without changing assertions.
The stronger registration fixture initially attempted deletion from an already
absent document table (1 failed/1 passed); its setup now asserts that absence
and deletes only the actual file registration. Product behavior expectations
were retained. No existing tests were weakened or removed.

README links the readiness contract. The producer document's stale opening now
acknowledges implemented unbound packages/mobile readers without implying native
admission. The GCP proposal now includes delivery phases, everyday app lifecycle,
independent AI credentials and the remaining cloud/device gates; no project or
cloud credentials were inspected and no resources created.

The full check remains required before commit/release; the old frozen receipt
predates these changes and is not reused as current evidence. The current
isolated checks are terminal, not background jobs to restart. No owner research,
paid calls, login, daily app/release, cloud deployment, commit or push changed.
Tool inventory still exposes no available Claude-session messaging interface;
this shared contract/status/ledger is the handoff, not a claim of Claude execution.
Harvest review: this is a validated-local application of existing exact-source,
received-causal-evidence and metadata/bytes separation rules. No new universal
rule, generated skill change or global installation is justified.

Final source/desktop component: **16 passed in 68.31 s**, 71.1 s overall,
zero skips, privacy/Ruff pass. Command: `python scripts/check.py --profile focused
--python tests/test_lineage_transfer_readiness.py
 tests/test_lineage_attachment_steps.py`.
Log: `build/lineage-source-readiness-final-component-20261113.log`.
This adds two actual pre-first-upload retirement/restoration journeys: retained
original bytes can still upload, native source creation/delete/restore operations
all drain, readiness then releases, and original science pins remain inactive.
No current-source substitution, fake source outcome or Lineage admission was used.
The first launch stopped only on the new test signature's line-length lint; the
formatter split the signature without changing behavior/assertions.

The final fixed docs profile separately passed **52 tests in 1.37 s**, 4.2 s
overall, zero skips, privacy/Ruff pass:
`build/lineage-source-readiness-docs-contract-20261113.log`.
`sync_file_transfers.py` was restored to its original LF endings after noticing
avoidable line-ending noise; the two existing production entry-point diffs are
now five added lines each. This is not a semantic change or a frozen/full receipt.
All checks in this entry are terminal; no cloud or long-lived test process is
waiting to be polled from this checkpoint.


## Native source-aware receive decision ? 2026-11-13

Status: validated-local prerequisite, not live admission. Inspection confirmed
`SyncClient._materialize_graph.project` currently rewrites hidden puts to empty
deletions and still uses the generic codec/writer. Such a rewrite loses the
scientific put shape while retaining its source pins. That path is not enabled
for Lineage yet. This checkpoint implements the native visibility decision
needed before replacing its typed write dispatch and enabling the common codec.
It does not claim that the current master receiver now accepts Lineage events.

`lineage_dependencies.projection_reason_in(conn, client, operation)` validates a
full staged frame, native journal transaction/path/workspace binding, every
parent/source graph lifetime and its applied projection revision. Remote sender
devices are allowed, foreign receiver bindings are not. It performs metadata
reads only. All pending dependency keys take precedence over hard failures;
otherwise a missing/deleted/replaced dependency hides science with its original
put/provenance, while deferred dependency projection preserves current content.
Typed retirement needs no live sources. Existing same-entity guards, real event
validation/authority and cursor transaction ownership remain caller obligations.

A mixed-source test found a real initial policy bug: after one source's genuine
retirement was received, another original still had an unsent native edit. The
first-pass implementation hid the row before seeing the later pending source.
The before-fix test failed with `state=hidden` instead of `source_pending`:
`build/lineage-receive-pending-priority-repro-20261113.log`, 1 failed in 6.44 s.
The implementation now checks all outstanding keys first. The same test verifies
both canonical scientific content and its projection marker remain unchanged.

The new 10-case module uses real native source creation, push/pull, deletion and
same-hash restoration and a real peer receiver. Scientific projection is staged
under the actual restricted writer authorizer, retaining the full original put,
report and pins in history on hiding. It creates no scientific graph head,
server event, accepted receipt or outbox. A peer with no downloaded originals can
project metadata without file/auth/network work. Parent renaming while pending
retains the current report and converges after sync. Scope checks distinguish a
remote sender from a foreign target database/workspace. Typed retirement has no
source requirement and neither frame nor source pins are modified.

Two cases explicitly lower only an existing native applied revision to model
retained parent/source projection lag. They preserve current scientific content
and immutable history while deferred, then invoke the actual native materializer
against genuine received heads and verify science can project unchanged. No
fake scientific protocol state or source outcome is installed.

Verification:

- Affected gate: **40 passed in 152.84 s**, 155.8 s overall, zero skips,
  privacy/Ruff pass. Exact command: `python scripts/check.py --profile focused
  --python tests/test_lineage_receive_visibility.py
  tests/test_lineage_projection_writer.py tests/test_lineage_projection_history.py
  tests/test_lineage_transfer_readiness.py tests/test_lineage_attachment_steps.py`.
  Log: `build/lineage-receive-visibility-integration-20261113.log`.
  It collected the first eight new receive cases; two later-added lag cases are
  separately covered below. Production inputs remained unchanged during the gate.
- Additional lag cases: **2 passed in 12.58 s**, 15.4 s overall, zero skips,
  privacy/Ruff pass. Exact command: `python scripts/check.py --profile focused
  --python tests/test_lineage_receive_visibility.py::test_retained_projection_lag_preserves_content_until_the_native_materializer_catches_up`.
  Log: `build/lineage-receive-projection-lag-20261113.log`.
- One preliminary gate stopped at a new test SQL string's lint length before
  executing tests. The string was split without changing its query/assertions.
  No existing expectations were loosened or tests removed.

README links the contract. The producer document includes exact reason/action
semantics and a concrete native activation closure checklist: strict codec,
observed source pins in the builder/resolutions, trusted schema setup, explicit
native writer capability, source-before-science ordering, unchanged-head
invalidation, all native client factories, compound publication, enrollment,
imports/recovery and real end-to-end acceptance. These remain implementation
gates, not deployment permission or evidence of live protocol acceptance.

All referenced processes are terminal. Full validation of the accumulated
revision, installers, hosted GCP and physical Mac/phone acceptance remain open.
No commit, push, release, owner research, account credentials, paid calls or cloud
resources changed. Shared contract/status/ledger is the independent-session
handoff; no available Claude-session messaging tool was discovered in the prior
tool inventory, and no Claude execution is claimed.

Harvest review: validated-local application of existing dependency-order,
received-metadata/bytes and retained-history rules. This adds no established
cross-project rule; no global/generated skill was edited or installed.

Final fixed docs profile: **52 passed in 1.74 s**, 4.7 s overall, zero skips,
privacy/Ruff pass; `build/lineage-receive-visibility-docs-20261113.log`.
No product or test code changed after the successful receive gates.


## Main native receive projector wiring ? 2026-11-13

Status: validated-local adapter/setup integration; common native Lineage wire
admission remains closed. This supersedes the previous statement that the main
receiver did not yet invoke the typed decision/writer. It does not supersede the
remaining codec, observed operation/resolution, compound publication/enrollment,
enrolled import/recovery, full release or hosted/device gates.

`SyncClient` and read-only `attach_existing` accept an explicit optional
`projection_writer(conn, operation, *, visible)` for graph reception. The actual
main materializer supplies a canonical JSON copy of the original put/delete and
separate visibility under the existing restricted SQLite authorizer. Late
failure, operation mutation or transaction control fails and rolls back earlier
research writes, graph/inbox state and cursor. Ordinary custom clients without a
projector retain their prior writer behavior; typed Lineage without the explicit
capability refuses synthetic-delete fallback. This is no automatic registration
of an arbitrary custom writer and no change to legacy v1 materialization.

`research_projection_writer` delegates ordinary rows to existing persistence and
full typed science to `lineage_projection.apply_in`. Bootstrap/join, capture,
workspace enrollment/sync, deck runtime, Inbox and primary migration explicitly
register it (nine constructor/attach sites). Trusted `sync_research.initialize`
creates optional Lineage projection/history in its existing savepoint. Older
workspaces are not upgraded on attach: missing schema fails without writes, and
explicit trusted initialization retains caller rollback and binding. Automatic
upgrade UX remains pending rather than being hidden in a read-only attach.

The main receiver orders roots, original-file metadata, other content and reading
state, applies the source-aware reason policy after same-entity guards, and
retains the original typed put when hiding. Tests of actual ordinary research
content with earlier service sequence than its originals prove native source
metadata is projected first. No fake scientific event/head/receipt/outbox is
inserted to claim admission; direct staged typed dispatch tests the writer phase.

A real transaction-boundary regression was reproduced with actual source pushes:
inside receive, after native source projection but before durable cursor commit,
`projection_reason_in` used the old SQL cursor and incorrectly returned
`source_pending`. The failing assertion expected no deferral at that exact
boundary. Log: `build/native-receive-prefix-repro-20261113.log`, 1 failed in
2.40 s. It now derives the evidence boundary from the actual validated contiguous
inbox prefix in the same transaction. An acknowledgement without that received
event still defers; no upload marker or supplied future cursor advances it.

Verification (overlapping scope receipts, not additive release totals):

- Core: **72 passed in 28.96 s**, 32.1 s overall, zero skips, privacy/Ruff pass.
  Command: `python scripts/check.py --profile focused --python
  tests/test_sync_projection_writer.py tests/test_lineage_native_projector.py
  tests/test_sync_graph_client.py tests/test_sync_graph_research.py
  tests/test_sync_content.py tests/test_content_initialization.py`.
  Log: `build/native-projection-dispatch-integration-20261113.log`.
- Broader native factories/receive/recovery: **270 passed in 320.95 s**, 324.5 s
  overall, zero skips, privacy/Ruff pass. Command:
  `python scripts/check.py --profile focused --python
  tests/test_sync_projection_writer.py tests/test_lineage_native_projector.py
  tests/test_lineage_receive_prefix.py tests/test_lineage_receive_visibility.py
  tests/test_workspace_sync.py tests/test_workspace_sync_edges.py
  tests/test_workspace_sync_files.py tests/test_sync_capture.py
  tests/test_workspace_enrollment.py tests/test_workspace_primary_migration.py
  tests/test_research_inbox.py tests/test_sync_recovery.py tests/test_sync_files.py`.
  Log: `build/native-projection-factories-integration-20261113.log`.
  It includes the receive-prefix fix, ten visibility cases and the first three
  native-projector cases. Later-added upgrade/ordering cases are separate below.
  Documentation and the projection module docstring were aligned during the run;
  it is not a frozen/full artifact receipt.
- Explicit upgrade: **2 passed in 4.30 s**, 7.3 s overall, zero skips,
  privacy/Ruff pass. Command: `python scripts/check.py --profile focused --python
  tests/test_lineage_native_projector.py::test_older_native_workspace_attach_is_readonly_and_typed_write_requires_explicit_upgrade
  tests/test_lineage_native_projector.py::test_trusted_lineage_schema_upgrade_rolls_back_with_its_owner_without_rebinding`.
  Log: `build/native-projection-upgrade-20261113.log`.
- Actual receive ordering: **1 passed in 5.95 s**, 9.0 s overall, zero skips,
  privacy/Ruff pass. Command: `python scripts/check.py --profile focused --python
  tests/test_lineage_native_projector.py::test_actual_receive_projects_later_original_metadata_before_earlier_research_content`.
  Log: `build/native-projection-order-20261113.log`.

Initial component run: 4 passed/1 failed because the new invalid-config test
attempted `Journal.attach_existing` on a nonexistent file. That API correctly
refused before the target test ran. Its setup now supplies a no-I/O journal probe
and asserts invalid projector rejection before `_connect`/file creation. No
behavior expectation was removed or weakened. Formatting/import fixes preceded
the successful gates. No old tests were deleted/skipped or validators monkeypatched.
The receive-prefix observer wraps the real native materializer solely to inspect
its actual transaction state, not to change source events or acceptance.

README and the producer contract document new signatures, capability boundaries,
trusted setup and remaining native closure. Full check remains required before
commit/release; no prior frozen full result is treated as current. No owner data,
AI/Google credentials, paid calls, account login, daily release, cloud resource,
commit or push changed. All referenced integration processes are terminal.

Coordination: the current tool inventory now includes Codex task read/messaging
alongside worktree tools, but no identified Claude-session control interface or
Claude task identifier. No unrelated task was messaged. This shared current
contract/status/ledger is the handoff; no Claude execution is claimed.

Harvest review: the candidate reusable distinction is immutable canonical
operation versus local projection visibility, with explicit writer capability
and one receive transaction owner. Ordinary event flow and direct protected
native typed projection are validated locally. Whole native scientific admission
is not yet verified, so retain this evidence with limits here; do not promote a
new global rule or install/generated-copy changes prematurely.

Final fixed docs profile: **52 passed in 1.34 s**, 4.0 s overall, zero skips,
privacy/Ruff pass; `build/native-projection-dispatch-docs-20261113.log`.
No product behavior changed after the successful factory/prefix/upgrade/ordering checks.


## Observed native Lineage puts and actual candidates ? 2026-11-13

Status: validated-local initial data construction, not scientific publication.
This advances the native operation-builder part of the activation closure. The
common journal/service codec still refuses Lineage, and no scientific
outbox/head/accepted receipt is fabricated by these APIs or tests. Native edits,
retirement/restore, incoming/canonical resolution, complete compound publication,
enrolled imports/recovery, stored-result adoption, full validation, installers
and hosted/physical-device acceptance remain incomplete.

New worker-only `SyncClient.new_lineage_operation_in(conn, prepared_sources,
source_operations, payload)` delegates to `lineage_operations.build_in`. The
same-transaction native source proof supplies actual file incarnations, and the
original sealed observation supplies selected paper epochs, target revision and
predecessor, corpus/request identity. Full portable source metadata, including
page counts and availability, must equal the captured originals. Schema-valid
rewrites with recomputed report/set hashes are not source authority. Unavailable
peers keep their observed paper parent but receive no invented original-file pin.
The returned JSON is independent data; construction changes no SQL, target,
source operation, outbox or service state and performs no PDF byte reads/hashing.

The raw API does not prove model execution. Native generated results instead use
`lineage_operations.from_candidate_in`, which checks the actual sealed
`PreparedCandidate`, exact pre-call lease object and pending-publication reason.
It converts the fixed verified row using native aliases and shares the same
construction core/proof checks. The real request ID and requested/returned model
metadata survive; retry performs no new completion. Stale route/cancelled or
retargeted candidates cannot become fresh publication intents. They remain in
the maintained private candidate store. An actual route-change test publishes
source child operations then fails candidate conversion in the owner transaction;
all three file versions/outboxes roll back while the prior candidate stays saved.
No real provider/account call is made: fake completions run through the maintained
Lineage job/retention pipeline.

A new boundary test exposed an ordering error in the first candidate adapter:
it converted local paper aliases before the source proof checked the original
database. A foreign peer database was ultimately refused, but its private paper
mapping had already been queried. The before-fix trace assertion failed:
`build/lineage-candidate-operation-scope-repro-20261113.log`, 1 failed in 3.63 s.
The adapter now checks source/database proof before any paper mapping and reuses
that proof in assembly rather than repeating inspection. The same test passes
with no foreign mapping read. No SQL/event validator or test expectation was
weakened to obtain this result.

Verification (overlapping selections, not additive release totals):

- Initial builder: **8 passed in 18.85 s**, 21.9 s overall, zero skips,
  privacy/Ruff pass; `build/lineage-observed-operations-component-20261113.log`.
- Expanded source/dependency/graph scope: **71 passed in 118.36 s**, 121.7 s
  overall, zero skips, privacy/Ruff pass. Exact command:
  `python scripts/check.py --profile focused --python
  tests/test_lineage_operations.py tests/test_lineage_dependencies.py
  tests/test_lineage_peer_sources.py tests/test_lineage_receive_prefix.py
  tests/test_sync_graph_client.py`.
  Log: `build/lineage-observed-operations-integration-20261113.log`.
  This includes all 12 raw-builder cases and preceded the candidate assembly
  refactor; the final scope below rechecks that changed path.
- Initial actual candidate component: **3 passed in 18.77 s**, 21.8 s overall,
  zero skips, privacy/Ruff pass;
  `build/lineage-candidate-operations-component-20261113.log`.
- Final candidate/target scope: **35 passed in 111.06 s**, 114.0 s overall,
  zero skips, privacy/Ruff pass. Exact command:
  `python scripts/check.py --profile focused --python
  tests/test_lineage_operations.py tests/test_lineage_candidate_operations.py
  tests/test_lineage_publication_bound.py tests/test_lineage_target_jobs.py`.
  Log: `build/lineage-candidate-operations-integration-20261113.log`.
  It includes 12 raw-builder and 4 candidate cases plus maintained target/lease
  and bound-publisher refusal tests. Production/test inputs did not change during
  or after this successful gate; subsequent changes are documentation only.

The tests cover source acknowledgement without intent rebasing, actual
retirement and same-hash restoration, missing native staging/source operations,
a valid yet falsified page count, a different corpus, a later local target,
foreign client/database, unavailable fourth original, unchanged SQL/frame inputs,
no PDF reads, a real retained completion with captured models, one-call retry,
route-change rollback and candidate retarget refusal. Old guard expectations
remain intact. An initial candidate launch stopped at import-format lint before
execution; imports were organized without changing assertions. The source and
new test files were formatted before their checks.

README links the observed-construction contract. It explicitly records that
construction is not publication or semantic validation. The next publisher must
not insert bound results into the unbound publication receipt table: maintained
recovery explicitly refuses that. A candidate architecture is actual native
journal request/receipt plus native projection/history/file versions and the real
private generation candidate. This remains proposed until genuine compound
scientific outbox/receipt and recovery journeys prove it. Post-write/retry checks
must permit only the exact own source/scientific mutation and reject later edits;
do not simply mask all differences from the original observation.

Next implementation should close the typed native save/parent guard, observed
put/retire/restore and incoming/canonical resolution paths, native compound
publisher and exact retries, central closed-codec dispatch, real two-client
service/HTTP events and recovery together. Do not remove current unbound guards,
rehydrate native leases from archive JSON, fabricate scientific journal rows or
mistake a committed original-file operation for published scientific content.

All referenced processes are terminal. Full check still required before any
commit/release; the old frozen gate is not current evidence. No owner research,
daily app/release, AI/Google credentials, paid calls, cloud resources, commit or
push changed. No identified Claude-session control was available from the prior
inventory; shared contract/status/ledger remains the coordination handoff.

Harvest review: this is validated-local use of original observations, native
capability versus portable data, scope-before-read and one transaction-owner
rules already covered by the focused local-integration skill. Keep these exact
limits with the project evidence; no new universal rule or global/generated
skill update is justified from the still-incomplete publication integration.

Final fixed docs profile: **52 passed in 1.43 s**, 4.3 s overall, zero skips,
privacy/Ruff pass; `build/lineage-observed-operations-docs-20261113.log`.
No product or test code changed after the successful final candidate/target gate.


## 2026-11-13: native publication checkpoint and deployment-plan boundary

The previous entry's closed common-admission description is superseded by the
new strict dependency-complete native codec dispatch and explicit
`lineage_shared_publication.publish_in` boundary. Generic content capture still
does not manufacture Lineage operations. Sources and scientific outboxes now
share the caller transaction, exact retries verify the real own journal envelope,
and source lifetime changes invalidate conflict review and old scientific pins.

Verified focused receipts (not a current full-suite result):

- `build/lineage-live-publication-first-20261113.log`: 7 passed in 53.49 s.
  Genuine two-workspace publication/retry, source-before-science delivery,
  verified original bytes, detached recovery, concurrent retry, failure/cancel
  rollback and protection against later edits.
- `build/lineage-live-conflicts-http-20261113.log`: six conflict cases passed;
  the additional HTTP test failed at test-only pagination assumptions. This
  combined invocation was not green.
- `build/lineage-live-http-mobile-final-20261113.log`: the corrected single
  HTTP/mobile journey passed in 8.35 s (11.4 s total), using actual authenticated
  loopback HTTP transfers and genuine service events consumed by mobile.
  Test extraction drains real bounded pages and excludes absent lineage arrays.

Twelve temporary assertions across eleven test modules that rejected fully valid
frames were intentionally changed to strict round-trip acceptance for the
authorized native feature transition. Missing pins, malformed frames, invalid
lifetimes and cross-workspace boundaries remain rejection cases. This is an
explicit contract change, not permission to relax other guards.

Broader Lineage/core regression coverage and a coherent new full check remain
required. Audit per-paper capacity under competing device creates; complete
native UI/task and reviewed package/recovery adoption; align older staged-only
documentation. No hosted Linux, installed Mac or real-phone acceptance is claimed.

`docs/gcp-sync-pilot-plan.md` is the reviewable deployment proposal, with an inert
systemd example. Reuse of the existing GCP project is planning authorization only.
No project/account inspection, cloud creation, credentials, research upload,
owner-data mutation, commit, push or release was performed. Project ID, hostname
and budget are needed before producing target-specific infrastructure and costs.


## 2026-11-13: competing-device capacity and broader regression audit

A new real-journal regression reproduced the missing native capacity guard:
`build/lineage-capacity-repro-20261113.log`, one failure in 4.01 s (the extra
corpus was accepted). `lineage_capacity` now bounds visible local rows and active
authority heads at the existing production constant of 64 per focal paper.
Observations reject new work before model invocation when full. Existing corpus
edits remain allowed. The authority retains excess creates as conflicts; source
retirement alone does not silently reclaim scientific slots.

The receiver defers `projection_capacity` instead of writing a 65th row or
rolling back the entire received page. Actual two-device tests demonstrate
competing last-slot creates, durable conflict, cursor progress, materialization
on an empty subsequent page and explicit resolution after retirement frees a
slot. Low fixture limits exercise the production boundary without manufacturing
64 repeated model/report actions.

`build/lineage-capacity-integration-20261113.log`: **29 passed in 205.69 s**,
209.0 s total, zero skips; privacy/Ruff pass. Includes the 17 named publication,
conflict, HTTP/mobile and capacity scenarios plus directly affected visibility
and receive-prefix cases. See [the human-readable scenario map](lineage-shared-scenarios.md).
A misplaced predicate in the first capacity edit caused an UnboundLocalError;
the code was corrected to keep retirement's early return and put the predicate
after dependency checks. No test was relaxed to fix it.

The first broad Lineage check is explicitly **not green**:
`build/lineage-all-native-20261113.log`, 89 passed and one failed in 229.75 s,
then stopped. The detailed rerun `build/lineage-capacity-enrollment-20261113.log`
had two capacity passes and the same enrollment failure in 18.12 s. The existing
enrollment case requires absence of `paper_lineage_sets`; current explicit native
setup installs its empty schema. All earlier archived-candidate/source assertions
passed, but table existence fails. The owner was asked, per AGENTS.md, whether
to approve the intended schema-existence contract change and replace it with
strict empty science/journal/source-grant assertions. That expectation has not
been edited while the decision is pending.

A complete diagnostic pass across all 55 Lineage modules and a focused generic
journal/service/graph/native-research regression pass were started to discover
other failures independently. Their live handles/logs are not passing receipts.
The diagnostic pass intentionally continues beyond failures; no skip/filter hides
the known enrollment assertion. Record terminal results before another run.
No current full suite, hosted Linux or installed-device acceptance is claimed.

Harvest review: preserve the observed-capacity and nonblocking-projection evidence
here. It is a validated local replication boundary, not a reason to impose one
quota policy on every agentic app. Existing canonical local-integration guidance
covers dependency order, one transaction owner and retained deferred projections;
no new global/generated skill copy or unsupported universal claim is needed.


Terminal follow-up receipts:

- `build/lineage-generic-sync-regression-20261113.log`: **242 passed in 101.11 s**,
  104.3 s overall, zero skips; privacy/Ruff pass. Ordinary journal, service/client,
  v2 graph service/client/research, projection writer, v2 projection and research
  round-trip behavior are covered; this is not the whole application.
- `build/lineage-capacity-docs-20261113.log`: **52 passed in 1.63 s**,
  5.0 s overall, zero skips; privacy/Ruff pass.

The complete 55-module diagnostic is still live under exec session `93284`, with
`build/lineage-complete-diagnostic-20261113.log` its authoritative output. Poll
that same handle/log before any replacement; limited output is not termination.
Earlier focused sessions `66696` and `32112` are confirmed terminal. The pending
owner schema-expectation question remains outstanding; no existing assertion
was changed for it. Keep the full goal active, with deployment and device gates
explicit. No commit, push, installer or hosted service was produced.


## 2026-11-13: shared Lineage task routing

The public settings gap was reproduced: `build/lineage-route-repro-20261113.log`,
one failure in 0.86 s, `Unknown AI task: lineage`. `ai_profiles.TASKS` now registers
`lineage`, and the existing desktop AI task page labels it Research lineage.
No new provider, authentication flow, default fallback or generation on settings
interaction was introduced. Existing explicitly declared frozen-route checks stay
mandatory.

Three new behavior cases verify task override/reset without changing the shared
account/global model, actual Qt save/reopen/cancel without generation, and an
actual LineageJob using its captured model after the next configured route changes.
Requested and returned IDs remain separately recorded.

`build/lineage-routing-integration-final-20261113.log`: **92 passed in 98.20 s**,
101.8 s total, zero skips; privacy/Ruff pass. Includes the new three cases and
existing profile, task-dialog, dispatch-snapshot and Lineage job regressions.
An initial edit script refused mismatched newline assumptions before writing;
its following test remained red. Actual newline handling was corrected; no
assertion was changed. Final source-only LF cleanup is semantically identical.

This is shared route/settings registration, not complete dedicated analysis UI,
source selection, reviewed stored-result adoption or installed-device acceptance.
README and AI setup describe that boundary. The 55-module diagnostic was launched
before this registry addition; it is evidence for its earlier input snapshot,
while the focused 92-case gate covers the new routing delta. Record its terminal
result before starting a replacement. No current full pass is claimed.

Current worktree inventory confirms development remains in `Paperfact-develop`,
`develop/0.5`. Claude processes exist, but no controllable Paperfact session was
identified; no unrelated process was messaged. `parallel-work-0.5.0.md` now marks
the old trust/worktree record historical and points to current shared contracts.
The owner schema-expectation question remains pending, with its test unchanged.
No owner research, account credential, paid call, cloud resource, commit, push,
release or installer changed.

Harvest review: the tested change reuses canonical provider-routing guidance
(explicit stable task, immutable admitted route, shared-account isolation and
requested/returned model separation); no new generic rule or generated/global
skill update is warranted.


## 2026-11-13: actual desktop workflow and terminal diagnostic

The preceding active diagnostic is now terminal; do not restart it as a lost
process. `build/lineage-complete-diagnostic-20261113.log`: **638 passed, 2 failed
in 1663.88 s (27:43)** across its 55 pre-desktop Lineage modules. Failures:

1. Candidate enrollment still asserts absence of `paper_lineage_sets`.
2. Protected-writer rollback asserts absence of the two optional projection/history
   tables, now installed before the test action by native setup. Its scientific-row
   and caller-kv rollback checks passed; the later pending-journal assertion was
   not reached.

Both are table-existence expectations under the pending owner review of explicit
native schema setup. Neither existing assertion has been edited, skipped or
reported as a pass. The diagnostic predates shared route registration and the
new desktop/coordinator files. It is not a full application gate.

### Integrated application path

`lineage_workflow.LineageWorkflow` now coordinates the actual loaded owner, exact
selected corpus, admitted frozen route, retained completion and local/native
transactional publication. Unbound setup may initialize optional storage; native
setup must already exist. Native paths use the capture-aware connection throughout
owner checks and compound writes. A plain journal connection cannot represent the
same capture-bound owner even when its database filename matches; guards were
retained rather than weakened. New native tests genuinely publish original/science
outboxes and receive the same report on another workspace without an unbound
publication receipt.

The actual desktop research-task menu opens `desktop/lineage_dialog.py`. It is
saved-first/modeless, offers up to three peers plus the focal paper, preserves
selected peers across title searches, captures account/model once, reports actual
stages in the activity area, prevents duplicate activation and waits for active
workers on close. Result labels show local time, unavailable originals and explicit
requested/returned model IDs. Caller judgments and unresolved citation requirements
remain visible; located quotes do not certify scientific support.

Quotation actions use the maintained unbound/bound original readers and actual
loaded owner/result guards. A separate read-only Qt PDF buffer displays verified
exact bytes and closes on proof/context invalidation. The primary reader is never
rebound. Missing bytes do not cause a download or a fallback to today's PDF.
Wrong visible paper/workspace owners refuse before a worker or model can start.

### Reproductions, corrections and receipts

- Four initial unbound workflow cases passed in 16.50 s. Initial native wiring
  correctly refused unauthorized DDL, then a plain-connection owner check. Trusted
  existing native schema plus a capture-aware transaction fixed the integration:
  two native cases passed in 17.13 s. No authorizer or owner guard was relaxed.
- The first new Qt fixture wrongly assumed two related papers; the library actually
  includes a third explicitly unavailable original. The fixture assertion was
  corrected without removing that edge. A QTest polling loop then starved Python
  source checks: the 8 s faulthandler trace located the live worker in path/source
  validation. Event pumping plus GIL-releasing waits retained the original 15 s
  timeout and all content assertions. A separate retry fixture initially returned
  quotations from unselected peers; it now explicitly selects that corpus.
- Search-loss reproduction: one failed in 1.75 s; selected `later` disappeared
  while searching for `Prior`. The fix pins actual selected IDs above query matches.
- Missing-index reproduction: one failed in 4.86 s; preparation recreated storage.
  The fix requires the registered root/index before constructing a BlobStore and
  refuses before AI; the native regression asserts index absence and unchanged
  saved science/outboxes.
- `build/lineage-desktop-workflow-integration-20261113.log`: **76 passed in
  154.60 s**, 158.2 s total; actual initial UI/coordinator, original proof and menu
  regressions. This predates subsequent picker/scope usability deltas.
- `build/lineage-desktop-final-actions-20261113.log`: **37 passed in 59.98 s**,
  62.9 s total; picker, storage and actual menu/draft behavior.
- `build/lineage-desktop-account-source-final-20261113.log`: **39 passed in
  70.15 s**, 73.4 s total; adds actual account-switch retention and automatic
  stale-original-window closure.
- `build/lineage-desktop-scope-final-20261113.log`: **41 passed in 76.24 s**,
  79.5 s total; adds wrong visible owner paper/workspace rejection. This is the
  final current action/coordinator/menu scope, with 20 new expanded cases plus
  existing menu regressions. Zero skips; privacy/Ruff pass. Counts overlap.

Visual QA inspected the real synthetic Qt capture. An initial bare offscreen app
rendered missing glyphs; loading the same pinned fonts/Fusion style as normal
startup produced readable text. The final screenshot is in
`docs/images/lineage-native-desktop.png`; the reader guide and scenario map explain
behavior/limits. It is not an installed Mac or production-data screenshot.

### Remaining work and handoff

Do not describe the dedicated source-selection/generation UI as still absent.
Remaining work includes lifecycle/editing UX, research-change announcements,
reviewed stored-result/package adoption, complete editable recovery, mobile source
controls, complete analysis audit and any public CLI/MCP generation adapters.
The 0.5 goal remains active; final full validation, hosted Linux/TLS/backup drills,
real Apple Silicon/phone acceptance and release artifacts remain unproven. Reuse
the prepared GCP plan; project/hostname/budget inputs and deployment authorization
are separate. No cloud account/resource, owner research, actual AI account, paid
call, daily app, commit, push, release or installer changed.

All referenced test handles are terminal: 93284, 48513, 31836, 65175 and 2003.
No test process needs replacement. The owner schema-expectation decision is still
pending; continue independent local work rather than hiding it or running a known
red multi-hour full gate repeatedly. A new coherent full gate is mandatory before
calling the accumulated application complete or committing/publishing.

Harvest: append validated-local evidence to the existing canonical local-integration
reference (no new universal instruction). Conflict-checked `sync_skills.py --write`
updated only repo copies/manifests; its subsequent check reports synchronized.
No global installation or telemetry upload. Full validation remains a release gate.


Final follow-up: `lineage-desktop-docs-final-20261113.log` passed 52 documentation
cases in 1.47 s (4.3 s total); `lineage-harvest-sync-20261113.log` passed 14
repo-skill sync cases in 0.71 s (3.4 s total). Both privacy/Ruff checks passed.
The final source-window resource patch clears its PDF buffer/proof, stops delayed
navigation and deletes the closed Qt dialog; actual buffer/Qt-lifetime assertions
and stale-proof closure pass in `lineage-original-window-release-20261113.log`: two
affected cases passed in 10.78 s, 13.6 s overall, zero skips. The 41-case gate
precedes only that localized resource-release patch; the two affected behaviors
were rerun rather than repeating the 27-minute diagnostic.
All follow-up handles (42763 and 26290) are terminal. No background test process
is left running. The current full application/release gate remains unproven.


## 2026-11-13: generated/imported/native original routing and re-export

The previous turn was concrete progress (actual desktop workflow and verified
resource release). No test handle from it required replacement. The current turn
identified a prerequisite for lifecycle/history: imported scientific rows had a
working receiver original reader, but the new desktop still routed every unbound
row to the generated reader.

### Verified implementation

`lineage_source_reader.reader_in` is now the shared worker-only selector. In the
actual capture-aware read transaction, loaded owner and exact canonical row are
checked before private provenance. A native binding selects the bound reader.
An exact import record selects the imported reader. Otherwise `_latest` must
find the exact generated publication receipt before the local reader is selected.
A missing import match is not authority to presume local generation. Each reader
retains independent prepare/delivery/currentness proof checks; none is attempted
after another fails. No download, model call, primary-PDF activation or new grant
is introduced.

Desktop source actions and `lineage_packages.collect` use that same selection.
Export keeps existing local/import/bound proof kinds, observed closure and final
checks. Genuine receiving-workspace Qt tests verify native original bytes and
unchanged database/outbox state. Import tests verify all three exact source hashes,
corrupt receipts/associations without fallback, cancellation and changed views.
The source window remains independently read-only and bounded on close.

### Experiments and terminal evidence

- `lineage-import-desktop-repro-20261113.log`: one failed in 3.68 s; imported
  original viewing produced no window.
- First explicit dispatch passed three direct imported cases in 5.02 s.
- `lineage-all-origin-desktop-20261113.log`: four passed/one failed in 12.27 s;
  replacing an import receipt with an empty JSON object still tried the generated
  reader. Requiring a real local publication receipt removed that assumption.
- `lineage-all-origin-desktop-final-20261113.log`: nine passed/one failed in
  31.75 s; the local receipt function name was incorrectly wired as `_receipt`
  instead of the existing `_latest`. Corrected the code, not an assertion.
- `lineage-all-origin-desktop-fixed-20261113.log`: **50 passed in 126.21 s**,
  129.7 s total; zero skips, privacy/Ruff pass. All three actual origins and
  existing imported-source boundaries pass together.
- The first export reproduction had a missing test import (NameError), which
  is not product evidence. After correcting/linting it,
  `lineage-import-reexport-fallback-actual-repro-20261113.log` failed in 4.37 s:
  the public re-export path attempted a generated reader for the corrupt import.
- Export now shares the guarded selector.
  `lineage-shared-origin-export-20261113.log`: **76 passed in 245.46 s**,
  248.9 s total; zero skips, privacy/Ruff pass. Includes all new import/native
  desktop cases, normal re-export/third receiver, mixed local/import corpora,
  native packages and public bundle import/export regressions. Counts overlap.

The lifecycle contract is now explicit in `docs/lineage-lifecycle.md`: native
retire/restore uses genuine journals/epochs; unbound actions need transactional
history, original provenance and complete backup/enrollment closure. Removal
never removes source PDFs or fabricates a new model run. The UI/facade for this
contract is still unimplemented; source routing was a necessary prerequisite,
not a narrower replacement for the full version-management requirement.

### GCP planning inputs and boundaries

The installed SDK was found and only `gcloud config get-value project --quiet`
was run, with update checks disabled for that process. Its locally configured
candidate has not been confirmed for Paperfact and is intentionally not copied
into tracked documentation. An asynchronous target-project question is pending.
No auth command, credential listing, cloud resource inventory, billing/IAM change,
provisioning or research upload occurred. Region/hostname/budget still require
confirmation. The existing deployment proposal remains planning only.

The old two schema-existence expectations remain unchanged pending the earlier
owner decision. No current whole-application pass, commit, push, installer or
release is claimed. No owner data/daily app or real AI account/model was used.
All referenced regression processes are terminal (41618, 95957, 19490, 5738,
95525); no replacement run is needed.

Harvest review: this reuses explicit provenance, scope-before-read and no-fallback
source boundaries in the existing canonical local-integration guidance. Keep
the concrete failures and limits here; no additional global rule or duplicate
skill installation is warranted.


Final documentation receipt for the shared-origin change:
`build/lineage-origin-docs-20261113.log` passed **52 cases in 1.92 s**,
4.9 s overall, zero skips; privacy/Ruff pass. No product code changed after the
76-case shared-export gate. The only remaining questions are the earlier native
schema-expectation decision and confirmation of the GCP target; neither is treated
as approval by elapsed time. Continue independent local implementation.


### Lineage lifecycle facade and recovery continuation (2026-11-13)

Added `lineage_lifecycle` as a worker-only observed transaction boundary, with
exact retry receipts for unbound generated/imported reports and real native
journal delete/restore operations. Source grants, retained original bytes and
original generation/import/history evidence are unchanged; no AI work is invoked.
Restore uses the selected immutable origin and refuses changed selected-paper or
source lifetimes, new targets, wrong owners and reused request identities.

The initial local run was terminal: seven passed, one failed in 22.06 s. Its new
fixture renamed a paper while claiming to recreate it. Inspection of the maintained
parent triggers proved rename preserves identity; corrected the fixture to actual
delete/reinsert and added an explicit rename-preserved case. Nine passed in
30.64 s (`lineage-lifecycle-local-corrected-20261113.log`, handle 71095 terminal).
The first actual native facade round trip passed in 9.34 s
(`lineage-lifecycle-native-first-20261113.log`, 73701 terminal).

Registered bounded lifecycle records in recovery and archive-only enrollment
history. Recovery validates exact generated/import/native provenance closure;
detached restore archives actions instead of installing live receipts/identities.
The first backup run refused the unregistered table: nine passed, one failed in
36.67 s. An exact edit anchor then safely refused because it assumed CRLF; the
unmodified process repeated that refusal (nine passed, one failed in 38.83 s).
Both processes were observed terminal before rerunning. Corrected the closed
registry using its actual line ending; twelve lifecycle/archive/native cases then
passed in 56.32 s (`lineage-lifecycle-recovery-registered-20261113.log`, 79141
terminal). No existing refusal policy or test was weakened.

Added imported-origin remove/restore, lost-grant/recreated-parent refusal, native
source-delete/same-bytes-new-incarnation refusal and removed-history provenance
closure regressions. Current focused check is handle 6596, log
`lineage-lifecycle-focused-20261113.log`; record its terminal outcome before using
it as evidence. The initial twelve-case run predates these extra cases.

This is not shipped lifecycle UI. Complete version browsing, native late-failure
coverage, list-sharing privacy, actual UI controls and final full release gates
remain open. No owner database, paid provider, account login, GCP resource,
commit/push/release or installed-device acceptance was used. Previous native
schema-absence expectations remain unchanged pending the owner decision.

Harvest review: lifecycle retirement reuses the existing canonical local-operation
transaction, provenance, retry and parent-epoch patterns. Record concrete fixture
and registry failures here; no new universal rule or duplicate skill copy is needed.


Terminal focused result: `lineage-lifecycle-focused-20261113.log`, handle 6596,
**97 passed in 339.24 s**, 343.1 s overall, zero skipped/failed/error cases;
privacy and Ruff passed. This covers the 18 new lifecycle cases and selected
existing generated/imported/native recovery, enrollment-history and archive-budget
regressions. No product inputs changed during that run. Documentation and the
additional sharing-only test were added after its collection; do not count that
test as part of the 97. Its separate handle is 65653, log
`lineage-lifecycle-sharing-20261113.log`; record its actual result before claiming
list-sharing privacy acceptance. All earlier lifecycle handles are terminal.

Active worktree reconfirmed: `Paperfact-develop`, `develop/0.5`, HEAD aa4b30e.
The worktree inventory still includes separate daily/maintenance/identity and old
frozen checkouts; none were edited or launched by this continuation. Current
shared handoff does not identify an available controllable Paperfact Claude
session; process presence alone is not coordination or permission to contact one.


Sharing privacy result: `lineage-lifecycle-sharing-20261113.log`, handle 65653,
**1 passed in 3.20 s**, 6.6 s overall; privacy/Ruff passed. The real list export
contains no removed report, lifecycle/generation history or peer-only Lineage
originals while the local removal history remains. Product code was unchanged
from the 97-case gate. Scope now explains 19 new lifecycle/sharing cases;
selections and earlier runs overlap. No UI or full-release acceptance is implied.


Documentation terminal result: `lineage-lifecycle-docs-20261113.log`, **52 passed
in 1.50 s**, 4.4 s overall, privacy/Ruff passed. No product code changed after
the 97-case gate; only the sharing test and documentation were added, with their
separate gates above. All lifecycle regression handles are terminal; none need
restart. Full coherent release gate and the earlier two unchanged schema-contract
failures remain unresolved. No commit, push, installer, deployment or device
acceptance is claimed at this checkpoint. Continue native late-failure/cancel,
full history browsing and Qt lifecycle integration before enabling controls.


### Desktop lifecycle and retained-version catalog continuation (2026-11-13)

The previous goal turn was progress: actual lifecycle/recovery code, passing
97-case focused evidence, one sharing privacy case and a scenario map. This turn
continues the larger objective, not a reduced release definition.

Implemented `lineage_versions.collect`: worker-only bounded read-only actual
publication/import/native scientific histories, import-displaced rows, explicit
provenance where available, current equality/target occupancy and paging. Missing
provenance can preserve readable historical data but never direct restore rights.
Versions sort by actual timezone-aware timestamps. No model, file-byte access,
new grant or journal mutation occurs while browsing.

The desktop now has Current analyses/History, paged Older/Newer controls, confirmed
remove/restore, existing activity reporting and worker/context guards. Current-row
source windows remain strict; noncurrent sources are disabled pending a genuine
historical proof path. Restore never overwrites an occupied target. Saved writes
whose follow-up refresh fails report saved/refresh-needed rather than rollback.
Actual detached recovery/adoption and historical original PDFs remain open work.

Initial native rollback test exposed a new fixture bug: caller note used the
non-timestamp string `fixture`. Actual note capture correctly rejected it before
commit. Corrected only the new fixture to an aware ISO timestamp, retaining all
science/history/outbox/caller-note assertions. Initial run: three passed, one
failed in 26.98 s (`lineage-native-lifecycle-rollback-20261113.log`, handle 20039
terminal). Corrected native plus generated catalog scope: 13 passed in 57.01 s
(`lineage-lifecycle-versions-core-20261113.log`, 89561 terminal).

Existing desktop compatibility: 13 passed in 34.80 s
(`lineage-lifecycle-ui-existing-20261113.log`, 7361 terminal). New Qt lifecycle
confirmation/duplicate/cancel/view/close/changed-target/empty cases: six passed
in 18.92 s (`lineage-lifecycle-qt-first-20261113.log`, 22359 terminal). Real
replaced imports, received native edits/older-version restore and those Qt cases:
eight passed in 34.06 s (`lineage-history-shared-qt-20261113.log`, 38147 terminal).
These scopes overlap and predate later failure/retry/paging additions.

Current selected privacy/Ruff/desktop/history/origin/task regression is handle
63894, log `lineage-history-desktop-focused-20261113.log`. Privacy and Ruff passed;
record its terminal test result before using it as evidence. No product code has
changed during that run. A test-only screenshot-layout wait was added after its
collection and needs a separate targeted rerun; do not silently include it in
that gate. Exact text/visibility is asserted, not inferred from file creation.
The first render was inspected: actual readable synthetic Qt layout, but the
new historical-source explanation needed another event/layout delivery before
the capture. No owner app or private paper was used.

Repeated exact edit anchors safely refused mismatched local LF/CRLF layouts;
corrected the scripts, not data or permissions. No broad product text replacement,
old-test weakening, current-release edit, credential access or cloud mutation
occurred. Documentation now records real controls and the remaining source/adoption
and final release/device gates. Existing two old schema-absence expectations
remain unchanged. No coherent current full pass or release is claimed.


Terminal new history/desktop gate: `lineage-history-desktop-focused-20261113.log`,
handle 63894, **48 passed in 184.96 s**, 188.4 s overall, zero skipped/failed/error
cases, privacy/Ruff passing. This covered version catalog, real imported/native
history, native rollback, new/old Qt and origin/task regression. Product source
was unchanged during that run. It predates the following targeted UI change.

Source review identified a committed-write/failed-refresh edge: the UI correctly
reported saved/refresh-needed but still enabled actions against its stale visible
rows. Added an explicit needs-refresh guard to lifecycle/source controls and their
admission boundaries; a successful refresh clears it. A late stop cannot label
an actually committed lifecycle result cancelled. Added stronger assertions and
two nested-confirmation context/selection-change cases. The screenshot-layout
wait added after the earlier collection is included in this rerun.

Current final UI/origin check: handle 3095,
`lineage-history-desktop-final-20261113.log`; privacy/Ruff passed, tests pending.
Do not restart on silent output; observe the same live handle. Version catalog,
shared backend and native rollback source remain identical to the 48-case gate.
No current full application/installer/release or hosted/device proof is claimed.

Harvest review: these are reuse of the existing canonical worker delivery,
transaction ownership, lifecycle and explicit provenance patterns. The failed
new-fixture timestamp and stale-view UI edge belong in this evidence ledger;
no new global rule, generated-skill edit or global installation is warranted.


Final affected UI/origin gate is terminal: `lineage-history-desktop-final-20261113.log`,
handle 3095, **32 passed in 128.51 s**, 131.9 s overall, zero failures/errors/skips,
privacy/Ruff passing. This includes the stale-view guards, actual saved/failed-read
reporting, cancel/close/delivery/nested-confirmation cases, all existing native and
imported source UI checks and the stronger layout assertion. Product code has not
changed after this gate. Source-reader/catalog/native backend remain the same
artifacts covered by the preceding 48-case scope; these counts overlap.

The updated synthetic history screenshot was visually inspected after event/layout
delivery and copied to `docs/images/lineage-history-desktop.png`. The historical
explanation, disabled source controls, enabled restore and resizable split layout
are visible/readable. This is fixture Qt evidence, not installed Mac or semantic
validation. All regression handles in this continuation are terminal.

No new full-suite pass is claimed; the earlier two schema-contract assertions
remain unchanged and the final coherent application/release/device gates are
open. Next: historical-original proof/inspection without activating reports,
complete detached editable adoption, current incoming-change notifications and
remaining public generation/analysis-audit acceptance. External GCP target and
installed-device steps remain independent. No owner DB, actual AI login/call,
cloud provisioning, publish or installer launch occurred.


Final documentation receipt: `lineage-history-final-docs-20261113.log`, **52 passed
in 1.48 s**, 4.4 s overall, privacy/Ruff passing. No product code changed after
the terminal 32-case UI gate. This records an incremental verified development
checkpoint, not v0.5 completion, a commit/push, a current whole-suite pass or a
release. All selected-test handles are terminal; continue the remaining full goal.


### Exact historical original inspection continuation (2026-11-13)

Previous turn was progress: live version catalog and confirmed Qt lifecycle
controls with 48/32-case evidence. This turn closes the historical-original
inspection gap without relaxing current-row readers or activating old analyses.

Added `lineage_history_originals`: sealed process-local proof of an exact retained
generated publication, receiver import receipt or native scientific put, including
actual paper/source lifetimes, independent byte/hash verification and native/file
metadata delivery checks. Scientific current-row equality is not required for this
separate historical boundary. Source retirement/recreation, changed paper epochs,
missing receipts or changed bytes still refuse. No restoration, primary-PDF
activation, model/network call, source grant or outbox mutation is performed.

Desktop source admission uses this reader only for a noncurrent selected version
with recorded provenance. Queued delivery checks its selected origin as well as
row and loaded owner/context. Existing current-row original readers and ordinary
list-package export selection are unchanged. The one temporary lifecycle assertion
that all historical source buttons were disabled was intentionally transitioned
to enabled-for-recorded-origin for this requested feature, paired with actual
historical proof/Qt rejection tests. Existing source protections were not weakened.

Initial new proof run: one failure in 3.66 s. Historical verification itself
succeeded; the new test expected the current reader's changed-row message, while
its real absent-row guard said unavailable. Corrected only that new exact expected
message and removed an unused test import. Then 12 passed in 48.06 s
(`lineage-history-originals-corrected-20261113.log`, handle 10174 terminal).

Extended proof plus actual generated-history Qt scope: **26 passed in 117.59 s**
(`lineage-history-originals-qt-first-20261113.log`, 95066 terminal). This includes
real three-origin bytes, missing/changed grants, source reincarnation, occupied
newer-import slots, malformed/forged proof inputs, cancel/context/close/selection,
open-window permission loss and missing-file repair/explicit retry. A subsequent
origin-only delayed GUI change case is in the larger current gate, not those 26.

Actual imported and peer-native historical Qt windows, each opening all three
selected original PDFs: **2 passed in 16.31 s**
(`lineage-history-all-origin-qt-20261113.log`, 90271 terminal). Viewing added no
outbox operation or canonical row; QPdfDocument loaded hash-matching real bytes.
This separate fixture process used isolated workspaces; no owner data or account.
The new file's fixture re-export alias was corrected to the explicit maintained
pytest export convention after Ruff, without changing product behavior.

Current maintained focused gate: handle 86270,
`lineage-history-originals-focused-20261113.log`; privacy and Ruff passed, inspect
its terminal test result before using it as evidence. It includes all unchanged
current-origin readers and actual Qt/lifecycle regressions, plus the delayed
origin-change case. The separate all-origin Qt file was added after collection;
its two cases have the independent terminal receipt above. Product source has not
changed during the focused gate. An earlier exact multiline label-edit anchor
safely refused before writing; replaced labels through AST-scoped values and
verified formatting, instead of broad unguarded replacement.

Real-reader integration was inspected: `Reader.load` captures the loaded paper
owner before primary-PDF work through `highlight_actions.capture`, so retained
historical originals do not require activating today's primary file. Actual Qt
fixtures keep `document=None`, inspect originals and preserve primary state.
No speculative fix was made after that source check disproved the concern.

The scope is unreleased local implementation. Complete detached editable adoption,
incoming-change notification and remaining analysis/public adapter/full/hosted/
installed-device gates remain open. Existing two native schema-absence assertions
remain unchanged; no full green, commit, push, installer, deployment or actual
Mac acceptance is claimed. GCP target inputs remain separate and unconfirmed.


Terminal broad historical/source/current-reader gate:
`lineage-history-originals-focused-20261113.log`, handle 86270, **130 passed in
492.61 s**, 496.1 s overall, zero failures/errors/skips; privacy/Ruff passing.
It includes the origin-only GUI guard but predates the queued-cancel correction.
The unchanged historical/current-source backend retains this evidence.

Source review then found no cancel recheck in the actual original-window delivery
slot. Added a real completed-worker/held-GUI reproduction for both current and
historical modes. Before fixing, the current-mode case opened a PDF after Stop:
one failed in 4.66 s (`lineage-original-queued-cancel-repro-20261113.log`, terminal).
This was a product defect, not a fixture timeout or external-service issue.
Fixed only the actual delivery slot: refuse cancelled worker results and report
stopped instead of unavailable. All original reader contracts remain unchanged.

Final affected Qt/origin gate:
`lineage-history-originals-ui-final-20261113.log`, handle 53287, **44 passed in
223.56 s**, 226.9 s overall, zero failures/errors/skips; privacy/Ruff passing.
This includes current/history queued cancellation, all actual three-origin windows,
existing source GUI and lifecycle/delivery/close regressions. No product code
changed after this gate. All cited regression handles are terminal. Counts overlap
prior gates and must not be summed as release totals.

Visually inspected the updated synthetic history screenshot: source buttons are
now enabled for recorded historical origins, and the independent verification/
no-restoration explanation is visible. Copied it to the reader guide's existing
`docs/images/lineage-history-desktop.png`. No private paper/account appears.

Next required adoption integration was inspected without changes:
`lineage_recovery_sources.stage_in` still grants fresh current originals only in
caller-owned staging; its docstring explicitly excludes full history/enrollment.
`RecoveryAdoptionService` and workspace enrollment retain their public blockers.
Closing them requires native source grants plus scientific baseline operations
and archived history closure, not merely clearing a blocker or copying old leases.
Continue that full goal; do not treat historical inspection as completion.

Available tool metadata exposes no identified controllable Paperfact Claude
session; no arbitrary thread or unrelated project was contacted. Shared status,
contracts and this ledger remain the honest handoff. No full green, commit/push,
owner DB mutation, paid AI/account action, cloud deployment or installed Mac
acceptance is claimed. The earlier two schema-contract tests remain unchanged.
Harvest review: the queued-cancel fix reuses the canonical actual-delivery guard;
historical byte inspection reuses independent provenance/source ownership. Record
these concrete verified cases here; no new universal skill rule is needed.


Historical-source documentation gate is terminal:
`lineage-historical-originals-docs-20261113.log`, **52 passed in 1.59 s**, 4.7 s
overall, privacy/Ruff passing. No product code changed after the 44-case final
UI/origin gate. This is an incremental development checkpoint; final coherent
full validation, adoption/enrollment completion and external device/hosting gates
remain open. No commit, release or deployment was performed.


## Fresh Lineage enrollment integration, 2026-11-13 continuation

Revalidated the active `develop/0.5` worktree; no changes were made to the
archive checkout, maintenance release, owner's data, cloud resources or accounts.
The previous goal turn confirmed the existing GCP proposal, but did not change
implementation; this continuation resumed concrete recovery acceptance work.

The actual normal enrollment now copies current Lineage under the caller's
transaction, verifies selected originals and emits genuine typed native source
and scientific baseline operations. Exact retry reuses the same events. Old
generated/imported/lifecycle receipts remain archive data with separately
validated historical source closure. Detached editable recovery uses this same
normal enrollment after establishing verified fresh local originals. Native
source authority uses accepted state plus the real pending optimistic overlay;
copying accepted graph rows alone had incorrectly rejected offline publications.

Initial actual integration: **38 passed in 276.37 s**, terminal handle 82651,
`lineage-enrollment-integration-first-20261113.log`. The two old temporary
unsupported-copy expectations were explicitly transitioned into real successful
copy/backup/source-preservation assertions; stale-source and rollback guards
remain. This is distinct from the two older optional-schema absence failures,
which remain unchanged.

This continuation verified newer identity and catalog work:

- Three retired/recreated source/parent cases passed. The fourth guard case
  initially hit the imported helper's fixed ten-second future timeout during
  a second full backup. Result: **3 passed, 1 failed in 55.24 s**, handle 55650.
- Corrected only that new case to use the supported public synchronous entry
  point instead of the unrelated short helper. All identity/source/output
  assertions retained: **1 passed in 28.76 s**, handle 63601. Both current
  and ancestor enrollment seed collisions refuse, while a fresh seed succeeds.
- Real native old/current versions survived detached recovery into a fresh
  editable copy: **1 passed in 19.62 s**, handle 99437. Current row has a fresh
  native origin; displaced archive row has no runtime origin. Reading changes
  neither the copied database nor the original source.
- Missing archived generated publication or its exact candidate refuses a new
  backup without changing current content/database: **2 passed in 21.96 s**,
  handle 13988.

All above direct test handles are terminal. The maintained focused gate launched
with explicit enrollment, recovery, stale-source, source staging and version
catalog modules (handle 31123); record its actual terminal result below rather
than treating its initial privacy/Ruff success as a whole gate pass. New negative
archive cases were added after that gate started and need their own final
privacy/Ruff coverage.

Updated the source helper's obsolete blocker docstring, current status and
lifecycle guide; added a readable scenario map rather than presenting case
counts as a feature map. Archived historical status entries remain dated
evidence; current integration/scenario sections supersede their temporary
blockers. No full application green, release, install, hosted Linux acceptance
or physical Mac journey is claimed.

Harvest review: transaction ownership, independent historical provenance and
new runtime identity are already covered by the canonical local-integration
skill. Keep concrete evidence here; no new global rule or generated skill copy
was needed. Arbitrary live enrolled imports, complete reviewed adoption, incoming
research notifications, public analysis adapters and final release/device gates
remain in the full objective.


Terminal affected gate: `lineage-enrollment-current-focused-20261113.log`,
handle 31123, **52 passed in 417.87 s**, 421.7 s overall, privacy/Ruff passing,
zero failures/errors/skips. This covers all newer identity and recovered catalog
changes plus adjacent normal enrollment, recovery, source and versions modules.
No product source changes followed it. The two new archive-integrity cases were
not in its selection and have their separate passing receipt above.

The first docs run stopped on two line-length errors in that new test file
(no behavior failure); Ruff formatting fixed only those lines. The subsequent
`lineage-enrollment-docs-final-20261113.log` passed **52 docs-contract cases in
1.90 s**, 4.9 s overall, including privacy/Ruff over the new archive tests. Later
README/status/scenario wording was reconciled again; final docs validation is
recorded separately. All test processes cited here are terminal. No model,
account, original database, deployment or release action was performed.

Final documentation receipt: `lineage-enrollment-docs-closed-20261113.log`, **52 passed in 1.69 s**, 4.5 s overall, privacy/Ruff passing. This is a documentation-only follow-up to the unchanged passing product artifact, not a full application gate.


## Real enrolled peer journey, 2026-11-13 next continuation

Previous turn was progress: fresh identity guards, recovered catalog and actual
archive-integrity assertions passed, with the maintained 52-case affected gate.
This continuation closed its explicit missing enrollment-to-peer service proof.

Added `test_lineage_enrollment_peer.py` using actual normal enrollment, sender
AttachmentSteps, reference authority and genuine typed operations, public
SyncSession/sync_bootstrap.join, and selected prepare_offline download. Before
download the saved report is available but original byte inspection returns
unavailable; afterward all three exact original PDFs and ordinary primary
reader documents match independently captured synthetic source bytes. Repeated
sync retains one scientific history item and the same report. The original
research fixture is unchanged, and the inherited active fixture bans AI.

Three initial test-harness failures were diagnosed rather than attributed to
transport or repaired by weakening product guards:

1. Hand-built receiver lacked capture installation: 1 failed, 13.04 s, terminal
   handle 53471. Metadata had already transferred correctly.
2. Installing capture before native journal identity failed with missing
   paperfact_sync_identity: 1 failed, 10.57 s, handle 32235.
3. Switched to the real public join rather than continuing to hand-build the
   receiver. Join and selected offline download succeeded, but the last fixture
   assertion treated a content evidence ID as a local PDF basename: 1 failed,
   19.71 s, handle 22292. Maintained binding schema showed source_id and paper_id
   are deliberately separate. Preserved exact byte assertions through the
   original saved bindings. No product source changed in these experiments.

Final direct journey: **1 passed in 18.74 s**, terminal handle 49131.
Maintained adjacent gate: `lineage-enrolled-peer-focused-20261113.log`, terminal
handle 65387, **5 passed in 49.12 s**, 52.3 s overall, privacy/Ruff passing,
zero failures/errors/skips. Includes the new journey, the two archive-integrity
cases and both existing desktop attachment-readiness guards. No product changes
followed the preceding 52-case recovery/history gate; these are new acceptance
assertions, not an implementation or release claim.

Rechecked the two previously recorded schema failures unchanged, handle 9305:
**1 passed, 1 failed in 11.34 s**. Native upgrade caller-rollback/foreign-binding
test passes including its final unchanged-journal assertion; candidate-only
enrollment still creates the optional paper_lineage_sets table. No old assertion
was edited, skipped or loosened. Record this newer evidence instead of claiming
both old failures remain current; a coherent full gate is still required.

The local integration skill applies; after repeated fixture failures the pua
method prompted source-first setup verification and replacement of the custom
receiver with the real public workflow. No persona narration or new universal
rule was added. Existing integration principles already require public-boundary
evidence and separate byte/metadata states; retain this concrete evidence here.

No owner database, account, paid AI, actual cloud provisioning, public endpoint,
release installer, commit or push was touched. Actual hosted/Windows/Apple Silicon/
phone acceptance, live enrolled package import, reviewed archive adoption,
incoming research notices, public analysis adapters and full release validation
remain in the full active objective. No identified available Claude session is
exposed by the current tools; no arbitrary unrelated thread was contacted.


## Saved Lineage audit adapter, 2026-11-13 continuation

The preceding turn was progress: a public enrollment/join/selected-download
journey established real peer attachment acceptance, with 5 maintained cases.
This continuation inspected the remaining schema contract first: universal
native initialization currently creates the optional Lineage table so future
receivers are ready. A narrow delayed-create change would also affect typed
receive and explicit analysis setup. No compatibility workaround, empty-table
drop, old-test rewrite or unsupported claim was introduced to hide this conflict.
The known candidate-only absence assertion remains unchanged; other useful
implementation work continued without treating that decision as a global blocker.

Implemented the previously explicit saved-Lineage gap in audit_inputs.read_items.
Validated current canonical statements now enter the existing bounded deterministic
checker: subject hash for the item, exact per-source hash/page/anchor for each
quotation, and corpus-scoped item identity. Malformed content rejects the whole
capture. No schema creation, archived proposal promotion, model, download or
research mutation occurs. Existing AuditCapture native/file/saved-state guards
remain in effect. Desktop and existing analysis.audit JSON CLI/MCP operation use
this same adapter. Cross-paper quotations remain source_mismatch with no focal
location; they are not mislabeled as successful semantic or other-original checks.

Updated both language labels and visible scope explanation; Lineage cards have
proper feature names. New desktop tests use actual generated canonical content,
real Qt windows and navigation verification, not a fabricated render-only report.

Direct evidence:
- 5 backend/public-operation/read-only/invalidation/corpus-identity cases passed
  in 17.03 s, terminal handle 59771.
- The first new Qt harness checked idle before the scheduled initial refresh
  started: 1 failed in 3.64 s. Fixed only that new test's wait to require delivered
  report and actual disclosure-button API; production timing and old tests unchanged.
- Both language desktop cases passed in 8.37 s, terminal handle 49815.

Maintained affected gate: `audit-lineage-focused-20261113.log`, terminal handle
79887, **91 passed in 134.66 s**, 138.3 s overall, privacy/Ruff passing, zero
failures/errors/skips. Selection covers both new modules, existing audit_inputs,
audit_ui, SQL outputs, saved-source links and actual JSON CLI/official MCP.
No semantic source changes followed that gate. Verified the two edited source
files used CRLF in HEAD; restored original line endings after the gate so their
review diff contains 40 insertions/5 deletions instead of whole-file churn.
No unrelated source changes or old assertions were touched.

README, current status, audit API/scope guide and scenario map now describe this
bounded integration. Complete multi-original corpus checking, semantic support,
archived-version audit, enrolled live package import, reviewed archive adoption,
incoming research changes, public analysis generation adapters, full application
gate and actual hosted/installed-device acceptance remain part of the active
objective. This is not a finished v0.5 release or a replacement for those items.

The local-integration skill's common validation/read-only boundary applies; the
source-version-preserving principle is already canonical. No new universal skill
rule or generated copy edit was warranted. No identified controllable Claude
session is available; shared documents remain the handoff. No owner research,
credentials, paid account calls, cloud deployment, commit, push or release occurred.

Final audit documentation gate: `audit-lineage-docs-20261113.log`, **52 passed in 1.32 s**, 4.4 s overall, privacy/Ruff passing. CRLF-aware diff whitespace check passed for the two edited source files; default Git whitespace interpretation treats their pre-existing CRLF convention as trailing CR. No Git config was changed. These are partial gates, not full release evidence.


## Saved-text incoming update notice, 2026-11-13 continuation

Previous turn was progress: the current canonical Lineage audit adapter and
91-case affected audit gate passed. This continuation implements incoming
saved-text notification rather than restating cloud planning.

The actual reader now attaches one loaded-paper owner/token to the existing
WorkspaceChanges worker. Bounded read-only signatures cover note card fields,
maintained chat/link/pending data, and explanation/close-reading rows. The root
observer has one additional research signal; list revision notifications retain
their former behavior. Native reads are capture-aware and their transaction
closes before delivery. Identical observations still compare with the actual
accepted display baseline. Old-view tokens are ignored; a workspace change
during research delivery prevents a subsequent list refresh.

ReaderPage binds/resets the notice with its captured highlight owner and
acknowledges actual note rows. ReaderPreparation acknowledges chat/dive snapshots
only at valid display installation. The notice preserves PDF instance/page, drafts
and focus. Explicit reload uses existing owned preparation and note loading.
Busy/repeated actions coalesce, read failure retains retry, and Later suppresses
only the exact observed signature. Other original/deck/research views retain
their independent refresh rules. No schema, daemon, AI call or download added.

Initial experiments/evidence:
- Invalid native fixture timestamp: 1 failed, 1 passed in 3.75 s.
- Valid timestamp exposed the native analysis observed-write requirement:
  1 failed, 1 passed in 3.35 s. Replaced native fixture analysis SQL with a
  genuine journal content operation; production guards were preserved.
- Signature/observer scope: **12 passed in 16.43 s**, terminal handle 53889.
- Actual reader exposed a production adapter mismatch: note cards omit paper_id
  but hash helper required it. Result: 1 error in 2.33 s. Fixed hash fields to
  match actual cards; separate owner checks still scope the paper.
- Actual notice/reload/failure/retry/repetition/dismiss/old-view scope:
  **5 passed in 9.42 s**, terminal handle 50569.
- Added reentrant workspace-delivery coverage. Maintained adjacent gate:
  saved-text-notice-focused-20261113.log, terminal handle 63977,
  **180 passed in 167.39 s**, 171.4 s overall, privacy/Ruff passing, zero
  failures/errors/skips. Covers existing workspace refresh/lifetime, main-window
  scope and saved-reader contracts. Preserved the observer HEAD's mixed original
  line endings after the gate with a semantics-equality assertion.

An exact write guard prevented overwriting the existing activity-view module
research_updates.py. New notice uses saved_text_notice.py. Shared main.py edits
used exact small anchors, preserving the owner's and Claude's existing changes.

Visual QA used an ignored build plugin without weakening assertions. First
synthetic capture passed the scenario in 2.84 s but offscreen Qt showed CJK squares.
Loaded normal app style plus installed Windows CJK fallback (1 passed in 1.57 s).
That exposed question marks in new label strings. Corrected terminal encoding
with String.raw/ASCII Unicode serialization and added exact language assertions.
Final direct GUI scope: **6 passed in 8.01 s**, terminal handle 2232. Visually
inspected the corrected real reader: readable single-row notice and both controls
fit; original and drafts retained. Copied only the synthetic banner into
docs/images/saved-text-updates.png. Prior audit labels were inspected too and
contained no replacement question marks; no unrelated repair was made.

After the 180-case gate, source changes are only corrected label text and
preserved observer line endings. Final affected/privacy/docs receipts follow
below. README, sync guide, API guide and scenario map explain the bounded scope.

Local-integration skill supplied common observer/delivery/lifetime boundaries;
frontend-motion supplied palette, spacing, focus/pressed/disabled states and no
attention-stealing animation. Actual Qt screenshot evidence was inspected. Existing
canonical invariants cover the lesson; concrete evidence stays here without a
new universal skill rule. No global installation, real account, owner research,
GCP resource, installer, commit, push or release was changed.

The complete v0.5 objective stays active: enrolled imports/reviewed adoption,
complete multi-original audit, public generation adapters, remaining research
surfaces, full gate, hosted recovery/HTTPS pilot and actual Windows/Apple Silicon/
phone acceptance remain open. The known optional-schema contract is unchanged.

Final affected gate is terminal: saved-text-notice-final-fixed-20261113.log,
handle 69169, **20 passed in 26.47 s**, 29.6 s overall, privacy/Ruff passing.
The first final-gate attempt stopped at Ruff on long ASCII-escaped label lines;
reserialized the same parsed language values as UTF-8 source without behavior
changes. No source changes followed the passing gate. Scopes overlap the earlier
180-case gate; they are not release totals.

Additional source review found continuous sync currently connects the ordinary
list-revision changed signal to local_changed. The new per-paper research
observations intentionally do not emit list refreshes or label every observation
as a local write. Existing notes/chat that lack list revision triggers still
reach the next scheduled poll; full outbox-only debounce notification should be
verified/implemented separately. Corrected the sync guide's overbroad claim. No
extra sync request or cadence change was introduced into the notice.

Final documentation gate is terminal: saved-text-notice-docs-20261113.log, handle 42039, **52 passed in 2.03 s**, 5.5 s overall, privacy/Ruff passing. CRLF-aware whitespace check passes for the three shared edited source files. No product changes followed the final 20-case gate. No full green, commit/push, cloud deployment, release or installed-device acceptance is claimed.


## Distinct local-outbox wakeup, 2026-11-13 continuation

Previous goal turn was progress: actual saved-text notice/delivery and the
180-case adjacent plus 20-case final affected gate passed. This turn revalidated
the current observer/controller before changing how automatic sync is scheduled.

The initial note and peer tests passed individually (1 in 3.44 s; 1 in 4.80 s),
but lacked a post-initial-sync idle precondition. Adding it exposed an actual
class defect: polling the initial own projection set waiting again. That failed
before the fix in 2.73 s. Do not cite the earlier loose tests as proof that the
missing wakeup hypothesis was correct; their initial waiting state masked it.

Implemented a separate WorkspaceChanges.local_operations signal driven by the
existing committed local journal, scoped to its captured workspace/device. No
new table, trigger, worker, account or model call. The observer captures a monotonic
local sequence and checks only rows appended since its prior observation. A new
row wakes sync only if unacknowledged or acknowledged ahead of the receive cursor.
Full manual sync before observation updates the marker without an extra pass.
Remote receive and acknowledgment changes cannot impersonate local writes.
The current desktop controller uses the dedicated signal; older custom observers
without it retain their previous generic-change fallback.

The native read result now carries independent research and outbox components;
list changed remains a three-field revision comparison. Advisory research
ValueError/SQLite failures are isolated so one unavailable open reader cannot
starve other local journal work. Current-window checks occur after both callbacks.
Explicit consent, session generations, busy checks, file retry and offline backoff
remain owned by the unchanged controller/session flow. Shared source edits preserve
existing mixed line endings and previous uncommitted work.

Early/final evidence:
- First distinct-signal note/peer cases: **2 passed in 7.46 s**, handle 65613.
- Added rollback/consent/backoff/unavailable-reader cases. Five passed, but a new
  fixture tried protocol paper deletion, which is intentionally unsupported:
  **5 passed, 1 failed in 14.63 s**, terminal handle 48805. Replaced that new
  invalid fixture action with a simulated expired advisory reader plus a genuine
  valid captured note write. No protocol deletion guard or old test was changed.
- New manual-sync race failed before its outstanding-row fix: **1 failed in
  3.54 s**. The first signal implementation would schedule an unnecessary pass
  after a manual pass had already sent/received the appended row.
- With the outstanding-upload/receipt check: **7 passed in 16.11 s**, handle 91140.
- Added actual authority-accepted/local-ack-before-pull coverage: **8 passed in
  18.17 s**, handle 19516, Ruff passing. Accepted-but-unreceived remains pending
  receipt work rather than incorrectly becoming complete.

Maintained affected gate: continuous-outbox-focused-20261113.log, terminal
handle 43282, **116 passed in 130.97 s**, 134.6 s overall, privacy/Ruff passing,
zero failures/errors/skips. Includes the new eight cases, existing continuous
sync, real offline restart/peer HTTP journey, attachment status, workspace refresh/
lifetime, reading signatures/notices and main-window scope. No product changes
followed this gate. Updated README, sync guide, scenario map and current status.

Harvest review: the canonical integration skill already separates remote acceptance
from local application and UI invalidation from ownership. This verified case
records why replication scheduling needs its own local outstanding-write clock;
no unverified global rule, credential access or generated skill changes were made.

Next investigate the optional Lineage schema contract without weakening its old
assertion. Candidate design (not implemented/verified): keep an absent optional
report table absent during candidate-only enrollment; initialize maintained schemas
inside the trusted complete receive transaction when admitting actual typed Lineage,
and at explicit native analysis preparation. Low-level typed writer/attach must
remain strict and read-only, source and caller rollback must still hold, and an
empty joined workspace must receive its first report. Verify all affected native
publication/receive/prepare/enrollment/recovery paths before adopting that design.
Do not simply drop an empty table after creation to make a test pass.

The full objective remains active: complete import/reviewed-adoption and audit/
public adapter work, coherent full gate, hosted recovery/HTTPS pilot and actual
Windows/Apple Silicon/phone acceptance remain open. No owner research, paid call,
real account, GCP resource, installer, commit, push or release was changed. No
identified controllable Claude session is currently exposed; shared docs remain
the coordination handoff.

Terminal documentation gate: continuous-outbox-docs-20261113.log, **52 passed in 1.83 s**, 5.0 s overall, privacy/Ruff passing. Shared observer/controller CRLF-aware diff whitespace check passes. No source changes followed the 116-case gate. All cited test processes are terminal; no full application green or release/deployment/device acceptance is claimed.


## 2026-11-13 optional report schema: preserve candidate-only enrollment

Previous goal turn made progress: the GCP proposal was checked against official
storage constraints, a pre-existing Ruff line-length issue was corrected, and the
docs gate passed 52 cases. No cloud deployment or owner data access occurred.
The earlier continuation probe handle 11227 is now unknown/terminal; its final
result was not available. It was not cited as a passing result.

Implemented generic metadata-only initialization while keeping the report store
absent. Explicit loaded-owner analysis initializes inside the actual owned
transaction; full native receive checks database/local binding and initializes
once before capacity/readiness, in its receive transaction. Attach/read and the
protected low-level projection remain migration-free and strict. No empty table
is created then dropped merely to satisfy the old assertion.

Initial recreated probe: 14 passed, 1 failed in 98.27 s. New lifecycle scope:
3 passed, 1 failed in 30.94 s. Both identified actual CaptureConnection DDL denial
at explicit analysis initialization, including when its table already existed.
Fixed that specific call with the existing suppress_capture trusted typed-action
scope after owner.check; no general authorizer or tests were weakened. Ruff then
identified import/line-length issues only in the new tests; formatted that file.

Maintained schema/enrollment/native-projector/real-receive/workflow gate:
lineage-schema-focused-20261113.log, terminal handle 7245, **21 passed in 145.67 s**,
149.2 s overall, privacy/Ruff passing. Includes the unchanged formerly failing
candidate-only enrollment assertion, direct projector schema-upgrade protections,
exact scientific receive before PDF grants, real late projection failure with
full database/schema/cursor rollback and duplicate-free retry, and cold native
explicit analysis with one model call and genuine outbox publication.

Added two actual post-DDL cancellation/view-change cases; broader enrollment,
peer-download and editable-recovery regression is pending a terminal receipt.
README stale Lineage implementation statements and the schema contract/reader
were corrected; new schema scenario map explains each observable acceptance.

Harvest review: the existing canonical skill already requires one transaction
owner, protected writes, read-only attach and independent byte authority. Record
this case as local evidence here rather than inventing a global migration rule
or modifying generated skill copies. Full validation and hosted/device gates
remain open. No commit, push, installer, real account or research migration.


Final broader receipt: lineage-schema-recovery-20261113.log, terminal handle
15499, **38 passed in 349.57 s**, 354.1 s overall, privacy/Ruff passing, no
failures/errors/skips. Includes six new lifecycle cases (post-DDL cancellation
and view change both restore the exact pre-transaction dump), actual enrollment,
peer report-before-bytes/offline download, generated/imported/native editable
recovery, archived source rejection, new identity guards, displaced history and
archive-integrity checks. No product/test edits followed this receipt. The
21-case and 38-case selections overlap; never add them into a release total.

The longer gate was verified through its same live handle and exact process
command line before completion. Buffered pytest output was not treated as a hang
or reason to restart. No unrelated Python process was stopped. Full application
validation is still required before completion, commit, push or release.

Next integration priority: run a coherent full gate on the accumulated artifact,
resolve any actual regressions without weakening old tests, then continue the
remaining enrolled package/reviewed-adoption and multi-original audit paths.
GCP configuration needs the confirmed project/region/domain/budget before any
cloud mutation; actual hosted recovery and installed Windows/Mac/phone journeys
remain required. No exposed tool identifies a controllable Claude session;
shared status, scenario maps and this ledger provide the handoff.

Terminal documentation receipt: lineage-schema-docs-20261113.log, **52 passed in 1.67 s**, 4.8 s overall, privacy/Ruff passing. All cited regression processes are terminal. No full-check green, deployment, release or installed-device acceptance is claimed.


## 2026-11-13 full accumulated-candidate validation started

Previous goal turn was a verified wait on the same full-check process, handle
37194. It was polled live, not inferred from a lock or report file. The complete
check started at local 23:19:44; privacy/Ruff passed and Python/desktop is still
running at the latest observation. Output is preserved in
build/full-0.5-continuation-20261113.log; isolated pytest root is build/check-dcc62590.
No source or test edit has been made since the run started. No terminal result or
full-pass count is claimed. Do not restart solely for buffered output.

Read-only local ancestry: develop/0.5 aa4b30e includes master 1b44466;
rev-list --left-right --count returns 84 0. No remote fetch was performed, so this
is local integration evidence only. Corrected stale roadmap/status descriptions
that still called Lineage unregistered and the historical master merge pending.
Preserved dated failures and package/live-source limitations. Documentation was
edited during the run; record its separate final check rather than describing
this run as a frozen all-input artifact with an immutable hash receipt.

Actual remaining implementation is enrolled source-complete live package import,
reviewed retained-result adoption, complete multi-original/semantic/cross-output
audit, mobile original controls and remaining public generation adapters. Source
and byte authority cannot be adopted by removing unbound guards. Full check,
installed packaging, Linux/HTTPS recovery and Windows/Apple Silicon/phone acceptance
remain distinct requirements. No user research, live account, cloud resource,
commit, push, installer or release was changed.

Documentation-only validation during the live full run: direct unchanged usage/distribution/check-script contracts, **52 passed in 1.71 s**, log build/full-wait-docs-20261113.log. The full-check report was not overwritten. At local 23:28:47 the exact pytest process was responsive, CPU increased and new isolated fixture directories were being created; buffered output reached 4% of cases. This percentage is not a time estimate or a terminal result. Handle 37194 remains the one full-check process to resume.


## 2026-11-13 isolated mobile exact-original continuation

Previous turn made progress correcting stale status/ancestry docs, with 52 direct
documentation contracts passing; it also verified the same running full-check
handle 37194. That full check remains active and was not restarted. At 23:53:31,
its exact process 66244 was responsive, CPU had increased to 1259 s and fresh
fixture directories were being created. Buffered output reached 14-15% of cases;
that is not a time estimate, terminal count or green release result.

While preserving canonical source/test inputs, implemented an isolated mobile
exact-original candidate in build/lineage-mobile-next-20261113. Full behavior,
failures, evidence and integration guards are in
[the candidate map](mobile-lineage-originals-candidate.md). Final isolated Node:
**642 passed in 7.759 s**, zero failures/skips/cancellations. Final real Chromium
components and actual synthetic-IndexedDB PWA startup/open/close: **15 checks
passed**, 390 x 844, two URLs created/revoked, no horizontal overflow. The final
app workspace/busy admission fix follows the Node checkpoint and is covered by
that final browser check. Do not call this canonical integration or phone
acceptance. Preserve the candidate manifest/review patch and recheck all baseline
hashes before any later integration; avoid line-ending churn.

The candidate retains exact original leases, explicit download, optimistic
retirement refusal, no byte grants from read-only metadata, real peer bytes,
scoped delayed delivery, URL cleanup, native Escape and current opener focus.
The v19 shell change preserves research caches; old-test version expectations
were updated only in the isolated copy and its upgrade assertion was strengthened.

Raw failed probes are retained: initial widget screenshot lagged behind DOM;
blocking capture helper timed out; asynchronous direct renderer capture succeeded.
The new peer fixture first used a wrong device, then illegally changed corpus
parents; both real protocol guards were preserved. A fresh two-source corpus
now opens the peer's different exact PDF and keeps the original corpus. Native
Qt key injection did not prove Escape; real browser input plus an expanded,
visible opener retains the strict focus assertion. Actual PWA probing then found
an early enabled action during workspace setup; disable-until-admitted fixed it.

Observed unresolved pre-existing browser warning: the index CSP IPv6 loopback
source expression is ignored by Chromium. Never claim zero-console/IPv6 cross-
origin acceptance or broaden HTTP permissions just to suppress it. The verified
127.0.0.1 synthetic journey and same-origin HTTPS deployment design are separate.

Harvest review: existing delivery/ownership/event-loop principles already cover
these local lessons. This is local evidence, not a new global rule or authorization
to install skills, change credentials or upload data. No canonical product source,
owner research, cloud resource, paid call, commit, push, installer or release changed
in this candidate. Full objective and hosted/device acceptance gates remain active.

2026-11-14 terminal candidate-documentation check: maintained privacy scan and Ruff passed; direct usage/distribution/check-script contracts **52 passed in 3.25 s**, log build/lineage-mobile-candidate-docs-20261114.log. The ongoing canonical full-check report was left untouched. Last poll of handle 37194 still reports a running process; no full green or source integration is claimed.


## 2026-11-14 browser CSP and offline restoration in the isolated candidate

Previous goal turn made concrete progress: source leases/dialog/app wiring,
642 Node passes, 15 real-browser checks and guarded candidate artifacts. Continued
the exact canonical full-check process 37194 without restarting or mutating its
source/test inputs. Latest sampled buffered output is 18% of Python cases; no
terminal count, full pass, commit or deployment is claimed.

The isolated PWA had an actual inherited invalid CSP IPv6 source expression.
Verified current W3C CSP grammar and the browser warning, then removed only the
invalid expression. A browser-facing factory preserves the lower-level IPv6
transport. Initial constructor-time preflight would reject cached workspace
restoration; source inspection identified that regression before integration.
Moved the browser-only check to the actual post/credential-send boundary. No
network request is made just by restoring a cached research workspace, and no
CSP broadening masks the invalid expression.

Final isolated suite: **647 passed in 7.608 s**, no failures/skips/cancellations,
lineage-mobile-origin-offline-final-node-20261114.log. Actual IPv4 and IPv6 browser
runs each passed **18 checks**, with zero JavaScript/CSP errors; both include a
real same-origin synthetic authenticated session request plus cached offline
research/original reading when the saved network origin is unusable. Native
headless GPU diagnostics remain in logs, not reported as zero system errors.
[Updated behavior/API/evidence map](mobile-lineage-originals-candidate.md).

All twelve previously recorded canonical base hashes were rechecked unchanged
before extending the candidate manifest/review patch to sixteen files. Nothing
was integrated or copied over canonical product files. The existing full-check
report remains authoritative and unmodified by isolated test reporting.

Harvest review: the canonical delivery/network/ownership boundaries already cover
these invariants; record the concrete offline-restoration case here rather than
manufacturing a new global rule. Remaining enrolled live import, reviewed adoption,
complete audit, full validation, GCP hosting/recovery and physical-device gates
remain active. No owner research, account, paid call, cloud resource, release,
installer, commit or push was changed.


## 2026-11-14 canonical full result and isolated enrolled import

The canonical run ended: privacy/Ruff passed, Python **3,349 passed and one
failed in 6,730.59 s**; overall 6,735.1 s. Stop-on-first-failure meant frontend
and mobile stages were not reached. Log: build/full-0.5-continuation-20261113.log.
The full result in build/check-latest.json is failed and has not been overwritten
with a focused receipt. No full rerun, commit, push or release was performed.

Failure: test_lineage_address_stage's inactive-stage assertion requires Lineage
not to appear in AI tasks. Current explicit Lineage task routing is implemented
and tested separately. The test also guards absent default storage and rejects
generic wire input; those protections must not be discarded when reconciling the
old activation expectation. No existing assertion has been modified in this
checkpoint. Product source/tests were unchanged throughout that full run; shared
documentation changed, so this is not an immutable all-input freeze receipt.

Independent enrolled import candidate: source-complete native publication, owned
transaction rollback, preview staleness, exact PDF proof transfer, actual peer
receive, duplicate prevention and detached preservation now have isolated local
evidence. Affected scope **63 passed in 348.60 s**; final strengthened scope
**3 passed in 19.93 s**. These overlap. The four-file candidate manifest/patch
are saved under build/lineage-import-next-20261114; nothing is integrated.
See enrolled-lineage-import-candidate.md for the 16-case map, failure history,
provenance and limitations. Existing canonical tests remain unchanged.

GCP proposal remains planning-only. Existing skill boundaries cover the verified
local transaction/proof behavior; no additional universal skill rule is claimed.
Hosted Linux/TLS/backup operations, reviewed adoption, coherent full validation
and physical-device acceptance remain outstanding.

Candidate-handoff documentation contracts: **52 passed in 2.12 s**, direct
pytest scope tests/test_usage_docs.py tests/test_distribution.py
tests/test_check_script.py; log build/lineage-import-candidate-docs-20261114.log.
This partial documentation gate does not replace the failed full receipt.


## 2026-11-14 canonical integration of mobile originals and enrolled import

Previous turn made progress by preserving the four-file candidate, its scenario
map and the terminal failed-full result. This turn re-read the canonical scope,
architecture, handoff and owned-operation skill. Branch/HEAD remain develop/0.5
at aa4b30e plus preserved uncommitted work. Exact original/candidate hashes were
checked before writes; 19 product/test files were integrated while retaining
equal original line spans and their EOL. The old bundle refusal-test transition
was left unchanged, pending the separate owner question about two activation
contracts. No old protection assertion was removed or skipped.

Integrated import scope: **50 passed in 241.08 s** (test_lineage_enrolled_import
and test_package_import), lineage-import-integrated-20261114.log. This includes
all 16 new complete-import, rollback, stale-target, actual-peer, duplicate,
replacement-refusal and preservation cases. Ruff passed on all three backend
source/new-test files. The old bundle journey invalid-date assertion is still
known to expect blanket refusal, so no full pass is claimed.

Integrated mobile Node: **647 passed in 5.079 s**, zero failures/skips/cancel,
lineage-mobile-integrated-node-20261114.log. A byte-identical canonical mobile
copy with hashes in build/lineage-browser-integrated-20261114/provenance.json
passed **18 real Chromium checks each for IPv4 and IPv6** at 390 x 844, zero
JavaScript/CSP errors. Logs: lineage-mobile-integrated-browser-fixture-20261114
and lineage-mobile-integrated-browser-ipv6-20261114. First probe failed because
its synthetic original-source.json was omitted; only the test fixture copy was
fixed. GPU diagnostics and an aborted socket during view shutdown remain in raw
logs; zero-system-errors is not claimed. The actual screenshot was inspected
and saved as docs/images/lineage-original-mobile.png.

Updated README, import/mobile guides and CLAUDE/development handoff to distinguish
actual development integration from old inactive-stage descriptions. Public GCP,
real phone/Mac, reviewed replacement/adoption and complete/full acceptance remain
open. No cloud, real account, research DB, release, commit or push changed.

Terminal integrated mobile service gate: **647 Node cases plus all 13 actual
isolated Python/HTTP programs passed**, lineage-mobile-integrated-services-absolute-
20261114.log. The initial service invocation used a relative interpreter while
the child cwd is mobile, producing ENOENT; corrected only the invocation to the
resolved absolute interpreter. No product fix or test relaxation was needed.
The 647-case Node selections overlap and are not summed. Maintained committable
privacy scan and whole-tree Ruff passed; whitespace check passed. Full result
remains failed in check-latest.json and was not replaced by partial reporting.

Final affected documentation/distribution/check-script plus actual authenticated
Lineage HTTP-to-mobile scope: **53 passed in 10.28 s**,
lineage-integrated-docs-http-20261114.log. Whitespace passed again, and all 19
integrated source/test hashes still match the integration receipt. No source/test
mutation occurred after these affected gates. Partial results have not replaced
the saved failed full report. No checks are currently running from this turn.

Harvest review: this integration validates the existing owned-transaction,
source-proof and final-delivery boundaries rather than establishing a new portable
rule. Keep this dated project evidence; no canonical/global skill changes or
generated-copy synchronization are warranted here. Next work includes the owner
activation-contract decision, reviewed Lineage replacement/adoption and friendly
package mapping, followed by a coherent full candidate. The objective remains
active; GCP preparation is not deployment and physical-device gates remain open.


## 2026-11-14 actual desktop enrolled import review

Previous goal turn integrated native source-complete import and mobile originals
with concrete affected evidence. Continued in the same verified develop/0.5
checkout/HEAD, preserving owner/Claude main.py lines and research. The operation
skill's owned transaction, observed identity and GUI delivery boundaries apply.
No identified controllable Claude session is exposed; shared status/guide/scenario
docs provide the coordination handoff.

Added PackageReview worker facade and a native PackageReviewDialog. File/share-
link imports select the existing factory; unbound legacy imports keep their old
call shape. Choose the destination list and explicitly search/pair papers, prepare
a fixed-archive preview, then separately confirm its existing transactional apply.
No title-based merge, provider call, implicit download or synchronization starts.
Preview counts are human-readable, not raw operation JSON. Active-only search is
bounded; long/duplicate titles have distinct short labels and exact target IDs.

The facade owns the active Ticket so close can win final publication without a
second UI signal. The window drains its admitted worker before cleanup; stale
queued results disable actions. A commit that already won is reported saved in
the old workspace and cannot navigate the new one. Scope/ZIP changes, cancellation,
retry and exact native research saves have actual fixture coverage.

Evidence/failure sequence (partial, overlapping selections):
- Initial new fixtures: 5 and 6 setup errors from tuple/registration wiring; fixed
  only the new fixtures, assertions intact.
- Initial corrected backend/GUI scope: **11 passed in 14.80 s**.
- Added final-publication cases plus old entry tests: **23 passed, 3 failed in
  29.45 s**. Extra language keyword broke the legacy injected constructor; source
  factory was corrected, old assertions unchanged.
- Native + adjacent link/pin/transfer gate: **35 passed in 39.69 s**,
  package-review-entry-regression-20261114.log.
- Extra search fixture incorrectly named Journal.append: **37 passed, one failed
  in 61.37 s**. Reading the actual API corrected that invocation; canonical wire
  validation then refused paper deletion as designed: **38 passed, one failed
  in 61.72 s**, package-review-delivery-20261114.log. No protocol guard changed.
- Corrected explicitly simulated inactive-view case, actual file-dialog Lineage
  import with all three exact PDFs, and docs/distribution/check contracts:
  **54 passed in 17.27 s**, package-review-lineage-docs-20261114.log. It preserves
  actual scientific rows and opens each exact saved original; no AI/upload. The
  simulated graph test is not evidence that paper deletion is supported.

The 18 new backend/GUI/Lineage cases and adjacent existing cases are mapped in
package-review-scenarios.md. Scopes overlap; no aggregate release total is claimed.
Visual QA initially lacked fonts; same pinned Noto/Fusion startup configuration
produced a readable actual Qt screenshot, inspected and saved as
docs/images/package-review-desktop.png. No physical Mac or real owner data used.

The two earlier activation/refusal contract questions remain pending. Their
canonical old tests are untouched; the saved full report remains failed. No new
full run, commit, push, installer, release, cloud account/resource or real paid
call was made. Reviewed scientific replacement/adoption, origin negotiation,
complete audit/recovery, hosted GCP and physical-device gates remain active.

Harvest review: existing explicit identity, publication-ticket and final-delivery
principles cover this work. Record the concrete local cases here; no new global
rule or generated-skill edit is warranted.

Final review checkpoint: maintained committable privacy scan, whole-tree Ruff
and focused whitespace check passed. After the final guide/status changes, docs/
distribution/check-script scope **52 passed in 1.91 s**,
package-review-final-docs-20261114.log. All seven source/test hashes match the
review handoff manifest; check-latest.json still records the failed full run.
No active test process remains from this turn; earlier handles are terminal.
No commit/push/release or external device/cloud acceptance is claimed.


## 2026-11-14 native scientific import version comparison and receive history

Previous goal turn added the actual native destination/mapping review and evidence.
Continued in verified develop/0.5 at aa4b30e plus preserved uncommitted work. Added
sealed process-local native report comparisons, complete explicit choices and a
read-only current/incoming Qt view. Separate final import confirmation remains.
Generic replace still refuses different science; no old test assertion changed.

Keep preserves local research without publishing the incoming report. Replace
requires actual native projection ownership and the same selected paper identities,
retains prior history, and rechecks exact archive/receiver/mapping/SQL/native marker.
A missing marker or unowned/removed report cannot be silently adopted/restored.
Cancellation and late write failure roll back science/history/outbox/receipt.
The facade keeps capabilities in memory; they are not research package or sync
fields. Long comparisons list numbered papers; missing model metadata is honest.

A new actual peer test exposed accepted-event history coalescing: current research
arrived but the old version was missing from the receiver's catalog. Source fix
retains each validated accepted SCI event, actual inbox and graph receipt checked,
in the existing receive transaction before latest-head materialization. History
is metadata, not a byte grant. Rollback/cursor/source-prefix contracts remain.
An adjacent old test then exposed capacity reads of an absent optional report
table; local_room_in now returns room without DDL, but wrong schema kinds fail.
The original failing old assertions were preserved.

Final backend/peer/backup/generic-receive/typed-prefix/schema/visibility/shared-
version/optional-capacity scope: **76 passed in 215.79 s**,
lineage-import-history-final-20261114.log. Actual peer catalog has both reports,
current selection is correct, three exact PDFs bind, and independent backup /
inspect / detached restore preserves research and history.
Final comparison GUI scope: **8 passed in 71.47 s**,
lineage-import-comparison-final-ui-20261114.log. Earlier overlapping scopes:
24 passed in229.62s; 25 passed in147.83s; initial5 passed in43.16s. Do not sum.
Exact scenario and failure map: lineage-import-comparison-scenarios.md.

Failures preserved: nested tuple/JSON list equality (1 failed10.14s), new portable
versus local binding assertion (1 failed9.14s), actual peer missing old history
(1 failed9.80s), new fixture's wrong artifact terminal label (1 failed11.96s),
then old optional-schema capacity regression (54 passed1 failed63.74s). Source
fixes preserve all scope fields, source bytes and transaction boundaries; fixture
corrections use the actual identity conversion and stronger bound terminal state.

The actual synthetic Qt screenshot was re-inspected and copied to
docs/images/lineage-import-comparison.png. No actual app/research/account was
modified, no cloud/deploy/paid call/push/commit/release was performed. No controlled
Claude session is exposed; these docs remain the shared implementation handoff.

Still required: bounded reindex of already-consumed beta inbox history (raw
accepted events remain retained), unowned-result adoption, full audit/recovery,
performance, coherent full gate and hosted/physical-device acceptance. Owner
activation/refusal contract questions remain pending; the canonical old tests
and failed full report remain unchanged. Goal stays active.

Harvest review: the existing owned-operation/proof/final-delivery principles cover
these fixes. Keep dated concrete evidence here rather than adding an unverified
universal rule or changing global/generated skills.

Terminal comparison checkpoint: committable privacy scan, whole-tree Ruff and
focused whitespace passed. Final docs/distribution/check-script scope **52 passed
in 1.51 s**, lineage-import-comparison-docs-20261114.log. All eleven source/test
hashes match the integration manifest. The authoritative full report remains
failed and was not replaced by partial reporting. All test handles from this turn
are terminal; no background check is being left silently running.

Pattern-harvest inspection found the canonical local integration rule already
requires received research/history/cursor atomicity. Candidate refinement for a
future coherent checkpoint: explicitly prove that accepted predecessors remain
in the researcher-visible catalog when multiple events coalesce to one current
head. Local evidence is the actual peer/backup case and76-case gate; old-beta
backfill remains unfinished. This project evidence is not promoted to a global
rule and no generated/local skill copies were overwritten.

Next safe work: bounded, resumable existing-beta inbox-to-history reindex with
transactional watermarks and native source/binding checks; then unowned-result
adoption. The full activation/refusal contract decisions, complete audit/recovery,
release artifacts and hosted/physical-device gates still require their own work.


## 2026-11-14: bounded legacy-beta Lineage history repair

Implemented an offline, resumable index repair for previously accepted native
Lineage events. Each bounded batch validates workspace/device/file identity,
contiguous inbox sequence, accepted outcome and graph receipt. History and its
private watermark commit atomically; cancellation rolls back the current batch
while completed batches remain resumable. Status inspection uses a read-only
connection. Repair does not generate research, grant attachment bytes, invoke
AI, or rewrite the current scientific result/outbox. Device/file checkpoints are
excluded from detached research recovery.

The History reader exposes Update version index only when needed. Worker
cancellation/close drain, duplicate activation and late-delivery scope checks
protect the current view. Automatic synchronization also repairs bounded batches
and remains pending until the real saved-event prefix is indexed. Progress uses
actual event counts, without invented percentage or ETA.

Exact overlapping receipts (do not sum):
- Core first scope: 5 passed in 57.43 s.
- Existing sync regression scope: 32 passed in 52.25 s.
- Core guards before the final read-only case: 10 passed in 116.19 s.
- Desktop/history scope: 15 passed in 107.16 s.
- Automatic sync/connection scope: 45 passed in 75.30 s.
- Final current-source new core/UI/automatic cases: **20 passed in 182.59 s**,
  build/lineage-history-repair-final-20261114.log.
- Final docs/distribution/check-script scope: **52 passed in 1.81 s**,
  build/lineage-history-repair-docs-20261114.log.

The final privacy scan, whole-tree Ruff and selected whitespace check passed.
All eleven source/test hashes match
build/lineage-history-repair-integration-20261114.json. The authoritative
build/check-latest.json remains the failed full check; focused receipts do not
replace it. The two old activation/refusal contract decisions remain pending;
canonical old tests were not weakened. No full/release acceptance is claimed.
The actual synthetic Qt capture is documented in
lineage-history-repair-scenarios.md and docs/images/lineage-history-index-repaired.png.

No owner research database, installed app, account, paid model, cloud resource,
commit, push or release was touched. GCP remains a review-only deployment plan.
Installed old-beta migration, Windows/Apple Silicon/phone journeys, hosted TLS,
backup/restore, complete audit/recovery and the coherent full gate remain open.
No controlled Claude session is available; documentation is the shared handoff.

Harvest review: the canonical integration skill already covers atomic received
history/cursor publication. Candidate refinement is a cancellable multi-batch
derived-index repair: preserve durable completed prefixes, isolate file/device
watermarks from portable science, and keep inspection read-only. Evidence is
local and synthetic; no universal/global rule or generated skill was changed.


## 2026-11-14: local authority backup export and read-only inspection

Previous goal turn classification: progress (verified history repair and exact
checkpoint). This turn addressed an actual GCP preparation gap: authority startup
and issuance existed, but coherent service backup capture did not. No cloud
operation was authorized or performed.

Added sync_authority_backup.export/verify and shared sync-admin backup /
verify-backup CLI commands. A bounded BEGIN IMMEDIATE reservation holds authority
writers while SQLite's backup API captures committed state, including WAL. The
entire authority SQL snapshot retains events/conflicts/tombstones/device and
upload metadata. Retained event prefixes/receipts and object ownership are checked;
every committed workspace object is streamed and hashed, including old/conflict
bytes. Incomplete upload bytes and derived blob indexes are intentionally absent.
This is a private operator snapshot, not directly runnable restored authority.

Existing output is never overwritten, cancellation/deadline/failure releases the
writer lock, and completion is published last through a flushed pending manifest.
POSIX directory fsync is implemented but not exercised on this Windows host.
Inspection validates closed paths/shape/bounds, exact bytes, no extra files,
SQLite integrity and retained-event coverage through a read-only connection;
late mutation is refused. Actual external module CLI execution returns bounded
JSON without printing a token or creating its configured unused research folder.

Final source/test scope: **132 passed in 22.80 s**,
build/authority-backup-console-final-20261114.log. This includes31 new cases and101
unchanged adjacent admin/mount/authority/blob-service cases. Earlier overlapping
scopes:23 passed7.41s,127 passed21.60s,131 passed23.51s. Do not sum.
Docs/distribution/check-script scope: **52 passed in1.80s**,
build/authority-backup-docs-20261114.log. Current committable privacy scan and
whole-tree Ruff passed; selected tracked whitespace check passed. Source/test
hashes in build/authority-backup-integration-20261114.json match all three inputs.
All test process handles from this turn are terminal.

Observed development failures were corrected without weakening existing tests:
Windows fsync on a read-only file handle failed (1 failed0.80s); the backup copy
now uses a writable handle for its flush. The first WAL fixture did not retain a
read transaction and SQLite removed its checkpointed WAL (1 failed1 passed1.22s);
the fixture now holds an actual older snapshot and asserts real later WAL bytes.
A byte-text patch initially assumed CRLF in the LF admin module and failed before
writing it; the corrected patch preserves its actual line endings. New-code Ruff
format/import corrections do not alter old tests or CI acceptance.

Operator workflow/API, exact scenario map and limitations are documented in
sync-authority-backup.md and testing/authority-backup-scenarios.md. README, admin
guide, GCP proposal, roadmap and status link the implemented seam and open gates.

Not complete: cloud upload/scheduling/retention, actual isolated restore with fresh
identity, old client cursor acceptance, Linux and power-loss behavior, large-store
capacity, hosted TLS/proxy, installed Windows/Apple Silicon/phone journeys,
complete research audit/adoption and coherent full check. The authoritative
build/check-latest.json remains profile=full,status=failed,full_check_passed=false;
old activation/refusal tests remain unchanged pending the requested decision.
No full pass, release, cloud backup/RPO, restore or deployment is claimed.

Owner research, installed app, credentials and current release were untouched.
No paid AI, GCP resource/IAM/billing change, upload, commit, push, installer or
release occurred. No available identified Claude session was exposed; the shared
documents remain the handoff. Goal stays active.

Harvest inspection: validated-local evidence supports keeping authority snapshot
consistency, immutable byte coverage and completion publication separate from
restore identity. Existing integration skill already covers transaction/file
publication boundaries. Cloud disaster recovery is still unverified, so this
checkpoint remains project evidence rather than a new global rule or generated
skill update.


## 2026-11-14: fresh-identity authority reconstruction and native peer journeys

Previous goal turn classification: progress (local authority backup export and
inspection). This turn implemented the missing isolated recovery path, without
cloud provisioning or changing any real service/client workspace.

sync_authority_restore.restore and sync-admin restore-backup select exactly one
backed-up workspace, require a new output and workspace ID distinct from all
source workspace IDs, verify the snapshot, reconstruct committed bytes through
ordinary blob APIs, and replay events through ordinary authority admission.
Operation IDs/provenance, accepted/conflict outcomes, head revisions and lifecycle
metadata are retained; workspace ID and its canonical protocol fingerprints
change. Verified ordering-set proofs are re-keyed with the exact supplied set;
stale/opaque proofs stay conflicts. Any replay/state mismatch refuses completion.
Temporary reconstruction credentials are deleted before the service marker is
published. Old devices/labels/token hashes and unfinished upload sessions do not
become active authority state. A new recovery.json receipt records source digest
and explicit new scope. No listener or device enrollment is started implicitly.

The verifier now carries the exact file identities it hashed into the actual
restore boundary. A database changed immediately after inspection cannot be
re-trusted under a newly captured identity. Source/manifest/object identities are
checked again before publication. Inspection remains genuinely read-only.
The existing full source backup remains intact; failed output is private and
incomplete, never overwritten, and can be retried to a fresh pathname.

Final coherent affected scope: **194 passed in87.11s**,
build/authority-restore-final-20261114.log:20 new recovery cases,2 native recovery
peer journeys,31 existing backup cases and141 unchanged adjacent admin/mount/
authority/blob/ordering/session cases. The final source/test files were not
changed by this turn while that run was active; docs were reconciled separately.
All eight source/test/dependency hashes in
build/authority-restore-integration-20261114.json match the current inputs.
Docs/distribution/check-script: **52 passed in1.46s**,
build/authority-restore-docs-20261114.log. Current committable privacy scan,
whole-tree Ruff and selected whitespace passed. All test handles are terminal.
No focused result replaced build/check-latest.json: it remains
profile=full,status=failed,full_check_passed=false.

Concrete verified journeys: an explicitly reissued device bootstraps a new local
workspace, downloads an editable deck with original speaker notes/citations/
layout and two exact figures; another native journey retains two imported
Lineage versions and all three exact PDFs through the actual native source-proof
interface. Missing primary PDF counts stay truthful (one in the deck fixture,
two in the Lineage fixture), while all intended artifact transfers complete.
A real desktop SyncSession rejects rebinding its old local journal to the fresh
identity without changing pending outbox or issuing push/pull/upload. Old token
and ahead cursor accesses are refused, not reset.

Earlier receipts/failures (overlap; do not sum): basic15 passed9.36s. First native
fixture incorrectly expected complete availability without declared primaries:
1 failed8.38s. Refined native run reached real workspace-scoped order CAS mismatch:
1 failed1 passed21.98s; proof run1 failed19 passed33.12s. Read-only inspection of
retained synthetic databases isolated accepted list_order event7 becoming conflict;
canonical_set_bytes explicitly includes workspace ID. The implementation now
re-keys self-consistent observed-set proofs, verifies exact outcomes and tests
accepted/stale/opaque cases for both order kinds. Next run reached21 passed1
failed38.27s because the native fixture has one actual primary and two missing,
not three missing; new fixture now pins its exact declarations and verifies every
artifact. No existing assertion was weakened, skipped or deleted. One docs exact
replacement failed on Windows CRLF before touching the existing file; corrected
byte patches preserve mixed existing line endings. New-code Ruff fixes only sort
imports/format new files. All corrected inputs are covered by the final194 cases.

Public workflow/API and detailed evidence maps: sync-authority-restore.md and
testing/authority-restore-scenarios.md. README, admin/backup guides, status,
roadmap and GCP proposal distinguish this local seam from operational readiness.

Outstanding full goal gates: source-result adoption and complete research audit,
coherent whole-application test contract resolution/full pass, release artifacts,
GCS upload/scheduling/retention, real VM/Linux/TLS/disk-loss recovery, large-store
capacity/power-loss behavior, automatic reconciliation of newer unsent old-client
work, and installed Windows/Apple Silicon/phone acceptance. Existing canonical
activation/refusal tests remain unchanged pending the requested decision.
No owner research/current app/release/account was touched. No paid call, cloud
resource/IAM/billing change, upload, commit/push, installer or release occurred.
No identified controllable Claude session is exposed; shared docs are the handoff.
Goal remains active; local recovery does not establish completion or an RPO.

Harvest review: candidate/validated-local evidence is that a recovery realm change
also changes scope-bound CAS digests, not only the visible workspace field; keep
old observed sets/outcomes and original bytes, and carry verification proof to
actual publication. Existing local-integration rules cover the transaction/file/
identity boundaries. These concrete cross-domain tests are recorded here; no
untested cloud recovery claim or new universal/global/generated skill is added.


## 2026-11-14: exact matching-package legacy Lineage adoption

Previous goal turn classification: progress (fresh-identity authority recovery
and native peer/deck/source journeys). Current work addressed an actual remaining
migration path, without claiming every legacy result is now adoptable.

Source-complete PackageImporter review now offers an explicit adopt choice only
when a private saved row matches the independently verified incoming payload
exactly and has no native graph/head/pending operation/marker/history. Actual
selected paper materialization and incarnations are required and included in the
sealed review. Model/generation metadata, timestamp, source hash and science text
stay unchanged. Generic replace cannot confer this authority. Missing native
markers, known native history, different science and retired results remain
ineligible. Direct source selection without a matching package is still open.

The same compound package transaction rechecks/removes only the exact private row,
performs the ordinary typed original/science write, and commits source grants,
canonical row/history/outbox/import receipt together. Generic native projection
still refuses unowned rows; its guard was not weakened. Late failure or cancellation
restores the consumed row and earlier caller work. Retry uses the existing sealed
request/fingerprint receipt. A real peer receives adopted science and all three
exact original PDFs; independent backup/inspection/detached restore retains them
without reactivating identity or source grants. No model or login is invoked.

Actual comparison and normal final Import remain separate stages, default Keep.
The preview identifies identical analyses being included in sync.20 rapid clicks
publish one science/history entry; closing before final Import writes nothing.
Pending close/workspace-switch tests found a real GUI error-path issue: failed
worker delivery had not marked an old view stale. Both successful and failed
stale delivery now share _mark_stale, retaining saved-local notification if commit
already happened. Held workers cannot write into switched scope, controls pause,
original SQL stays exact and a different database is not created.

Exact overlapping receipts are mapped in
 testing/lineage-matching-adoption-scenarios.md (paths below build/):
- first core6 passed55.80s; expanded core/GUI16 passed140.61s;
- new core/GUI/pending20 passed1 failed142.01s (stale-control bug; fixed source);
- corrected pending and unchanged delivery scope20 passed107.24s,
  lineage-matching-adoption-delivery-20261114.log;
- final comparison3 passed plus1 failed43.38s (recovery fixture lacked explicit
  owned BlobStore); corrected recovery1 passed14.43s;
- backend38 passed1 failed302.35s (old caller-transaction error copy); source
  now says caller transaction without changing ownership behavior/test;
- projection/writer/review18 passed1 failed74.41s (preexisting-schema assertion);
- complete baseline/writer/review audit18 passed2 failed73.10s, all selected
  cases executed without -x or skips. Old failure retained; the new baseline
  fixture falsely assumed report-table absence. Its actual selected setup
  explicitly executes lineage_sets.SCHEMA. New proof pins the three empty tables
  and exact complete SQL/schema before/after late protected failure:1 passed4.19s;
- final docs/distribution/check-script52 passed1.56s.
Do not sum overlapping scopes. The five new files select23 behavior/proof cases;
these are not a single full-release pass. Existing old tests were not changed.

The unresolved old writer assertion requires protocol tables absent after
rollback even though generic preparation created them before the action. Exact
baseline preservation has independent proof; deleting those old tables to satisfy
it would be wrong. The old activation/refusal questions also remain pending.
The authoritative full report remains profile=full,status=failed,
full_check_passed=false; no focused green replaces it. No full/checkpoint commit,
push or release is claimed. All tool process handles from this turn are terminal.

The manifest build/lineage-matching-adoption-integration-20261114.json records11
current source/test hashes and exact terminal receipts. Product sources were not
changed while the final delivery scope ran; the later projection error-copy change
has its own explicit gate. This is affected-input evidence, not an immutable
whole-worktree full candidate. The synthetic Qt screenshot was viewed and linked
at docs/images/lineage-matching-adoption.png. Current privacy/Ruff/whitespace
checks accompany the recorded docs gate.

README, status, roadmap, comparison/adoption workflow and scenario map distinguish
matching-package adoption from pending direct legacy-source selection. Other
requirements remain: coherent full gate/contracts, complete audit, native-corrupt
history repair where needed, hosted GCS/TLS/VM recovery, newer unsent-client
reconciliation, release artifacts and installed Windows/Apple Silicon/phone
acceptance. Owner research/current app/release/accounts were untouched. No cloud,
credential changes, paid call, upload, publish or installer occurred. Tool metadata
again exposed no identified controllable Claude session; shared docs are handoff.
Goal remains active.

Harvest review: local evidence reinforces separate observed adoption authority,
exact parent lifetime scopes, compound rollback and GUI delivery checks for errors
as well as success. Canonical integration rules already cover these boundaries;
keep this concrete evidence/candidate refinement here while the full gate is
unresolved. No global rule, generated skill overwrite or installation was made.


## 2026-11-14: private GCS backup publication preparation

The owner selected reuse of existing GCP for deployment planning. Added the
concrete operator-only GCS publisher, headless setup commands, private-bucket
checks, create-only content-addressed objects and an exact manifest published
last. Unchanged payloads are reused across snapshots after size, checksum,
metadata and generation verification. Cancellation, uncertain acknowledgements,
concurrent publication and changed local inputs have explicit failure behavior.
No real GCP client credentials, network request, resource or research upload was
used. This is local preparation, not cloud deployment or disaster-recovery proof.

Google Cloud Storage 3.17.1 and CRC32C 1.9.0 were installed only into the isolated
develop environment; the lockfile adds operator/test dependencies. Desktop base
requirements are unchanged. Packaging configuration excludes cloud operator SDKs;
an actual installer has not been built to verify that exclusion. Setup-script
behavior was exercised in a disposable checkout with a simulated dependency
installer and a real temporary Python environment. POSIX execution remains untested.

Final affected gate: build/gcs-backup-final-20261114.log, 112 passed in 64.02s.
This includes 37 new cases and 75 adjacent administration, backup, restore,
native research recovery and dependency checks. Real SDK multipart and resumable
request construction were executed against an in-memory HTTP transport with
anonymous fixture credentials: build/gcs-backup-sdk-wire-final-20261114.log,
2 passed in 2.21s (included in the 112; do not sum). The initial SDK fixture
failed because it assumed contentType in JSON metadata; actual SDK source showed
MIME/session headers. Corrected the fixture, retaining byte/checksum/generation
assertions; production code was unchanged by that correction.

Final documentation gate: build/gcs-backup-docs-20261114.log, 52 passed in 1.58s.
Privacy scan, Ruff, scoped whitespace and uv lock checks passed in the same final
validation run. The 13 source/test/config hashes in
build/gcs-backup-integration-20261114.json were verified after validation.
Earlier overlapping receipts: first 26 passed in 9.11s; operator 33 in 12.47s;
integrated 109 in 67.27s. These are not additional unique tests.

No full check ran this turn. The authoritative prior full report remains failed;
focused checks do not replace it. No commit, push, release, installer or owner-app
restart is claimed. Pending: confirmed project/region/domain/budget, private
hosting and Linux operations, remote snapshot retrieval and isolated cloud
restore, retention/scheduling, coherent full gate and installed Windows/Apple
Silicon/phone acceptance. The example upload unit is manual and inert, not a
scheduled backup policy. Cross-process retry reuses complete objects but does not
persist resumable-session URLs. No cost, byte-resume or recovery-time promise.

Harvest review: immutable payload publication plus a separately verified final
manifest and tests at the actual SDK transport seam provide useful local evidence.
Cloud restore and live operation remain unverified, so no universal rule or
generated/global skill update was made. Goal remains active.


## 2026-11-14: exact cloud-backup retrieval and local recovery

Previous goal turn classification: progress (publisher implementation, actual
SDK transport evidence and operator deployment documentation). Revalidated the
active develop/0.5 checkout at aa4b30e. Continued locally without GCP or owner
research. No external service/session was restarted. Relevant canonical local
integration and harvest skills were read; no new subagents were spawned.

Added sync_gcs_fetch.fetch and sync-admin download-backup: explicit bucket and
manifest SHA, bounded private-policy/generation/raw-range retrieval, independent
SHA/CRC verification, closed manifest/path/count/byte validation before payloads,
exclusive new output, ordinary authority SQL/event/source/attachment closure
verification against .manifest.pending, completion marker last. No restore or
enrollment is implicit. The internal backup inspector now supports precisely the
ordinary or pending manifest name; public verification still requires completion.
No old test was weakened. There is no partial-download resume or retention policy.

Evidence: first 17 new fixture cases passed in 7.70s. Real SDK download transport
worked on the first wire run; restore exposed a new test fixture's incorrect
workspace name, corrected to the fixture's actual workspace-a. The final two SDK
cases passed in 2.83s, including multi-range bytes, replayed conflict/PDF and old
credential refusal. Initial adjacent command used the wrong dependency-test file
and collected zero cases; corrected command ran 134 passed in 77.35s. This includes
22 new retrieval cases and the prior 112 adjacent tests, not 134 plus 22. Final
docs gate: 52 passed in 1.35s. Privacy and all-repository Ruff passed. A non-escalated
Ruff attempt could not create its cache; the approved active-checkout validation
subsequently ran successfully. Initial new-code formatting/import findings were
fixed before final validation. No source/test edits followed the final gate.

The five current source/test hashes and exact receipts are retained in
build/gcs-fetch-integration-20261114.json. Partial checks never replaced the prior
failed full report. No full check ran this turn; no commit, push, installer,
release or overall completion is claimed. The target project/region/domain/budget,
real cloud retrieval/restore, private TLS/Linux operations, scheduled backup and
retention, full-suite contract resolution, unsent-client recovery reconciliation,
and installed Windows/Apple Silicon/phone journey remain open. No live ADC,
cloud API, paid model or research transfer was used. SDK HTTP was in memory.
Tool metadata exposes no identified controllable Claude session; shared workflow,
scenario map, roadmap/status and this ledger are the coordination handoff.
Goal remains active.

Harvest review: completion-after-authority-closure and independent range-byte
proof reinforce existing local integration rules. Keep the concrete checkpoint
as validated-local evidence here; no new global/canonical rule or generated-skill
copy was warranted while live recovery and the full gate remain open.


## 2026-11-14: old-device recovery visibility and guarded desktop review

Previous goal turn: progress (exact GCS retrieval and actual SDK/local recovery
evidence). Revalidated develop/0.5 at aa4b30e and the active source/docs before
continuing. Owner research, maintenance release, running app and credentials were
not touched. Canonical local integration and harvest skills were consulted.

Added read-only sync_device_recovery.review and sync-admin review-device-backup.
It verifies the selected authority snapshot, exact shared received prefix, canonical
journal fingerprints and acknowledgments, then distinguishes entries already in
backup, absent unconfirmed entries, newer acknowledged entries and newer received
events. Counts can overlap. No event is replayed or acknowledged and no database
is initialized/rebound. File/WAL changes, gaps, inconsistent receipts and bounded
record/time failures refuse a result. It is not a full research/file audit.

The Workspace Advanced page now has a default-collapsed service-backup comparison
control. It shares the backend, background worker and lifecycle admission guards.
Repeated clicks cannot create another task; cancel/close drain work; native/file
and stored-binding changes reject GUI delivery. The receipt is explicitly a
point-in-time observation, not an automatic reconciliation or ownership grant.

New backend first run failed because the path guard incorrectly rejected separate
siblings; corrected the guard, retaining the prohibition on a device inside the
backup. Backend then passed 13 cases in 4.01s. Initial UI test did not navigate to
the actual Advanced page; corrected the fixture, not the visibility assertion.
PowerShell pipe encoding initially damaged Chinese literals; rewritten with UTF-8
input/output and an exact UI assertion. No existing test was weakened or skipped.

Native failures were not counted as passes: one eight-dot process ended with heap
corruption; isolated non-held cases passed 3, while held/next-window runs aborted
with main-thread garbage collection. Single cancellation passed. Read source and
official Qt ownership/thread docs, checked installed PySide6 6.11.2 (ruling out a
searched 6.12-specific report), then removed the new strong parent reference and
widget capture in background closures. Kept ownership weak and service-only work.
A subsequent sequence had 7 pass/1 delayed-delivery failure; added a stronger
actual-thread/timing observation without removing the original binding assertions.
The isolated diagnostic passed 1 in 1.04s; the final original eight-case sequence
passed in 2.61s. Exact universal Qt/root-cause attribution remains unproven; the
larger final regression below exercises the current artifact, not a claim that
all Qt/native memory failures are eliminated. No harness/dependency bypass.

Final affected gate: build/device-recovery-integrated-20261114.log, 144 passed in
92.84s (21 new plus 123 adjacent existing). Docs: 52 passed in 1.41s. Privacy,
all-repository Ruff and scoped whitespace passed. Final synthetic Qt screenshot
was viewed; explicit installed font fixed test-process missing glyph rendering,
and a generic displayed location avoids private machine paths. Capture receipt:
1 passed in 1.26s, overlapping the above UI scope. No source/test change followed
the final affected gate. Seven source/test hashes are recorded and rechecked in
build/device-recovery-review-integration-20261114.json.

No full check was rerun; build/check-latest.json remains full/failed/false.
Explicit async approval to modernize the three old staged activation/import/
rollback-precondition contracts was requested with preserved safety assertions;
no response is assumed and those old tests remain unchanged. Project AGENTS.md
forbids deleting/skipping/weakening existing tests without approved behavior changes.
No commit, push, installer, release or overall completion is claimed. Remaining:
explicit per-change fresh-identity reconciliation, complete research/file preservation
and guided restore, complete audit/legacy adoption where pending, coherent full
gate, real GCP/Linux/TLS/retention recovery and Windows/Apple Silicon/phone acceptance.
The metadata inventory exposes no identified controllable Claude session; shared
workflow/status/roadmap/scenario map and this ledger provide the handoff.
Goal remains active and meaningful local work remains available.

Harvest review: exact lost-ack classification and weak UI ownership/service-only
worker inputs add validated-local observations. Existing integration rules already
cover observed authority and delivery guards; the native root cause is not proven
universally. Keep this evidence local; no invented global rule or generated skill
copy/update was made.


## 2026-11-14: direct saved Lineage adoption through selected originals

Previous goal turn: progress (old-device read-only recovery review and actual
workspace UI). Revalidated active develop/0.5 at aa4b30e. Preserved all prior
uncommitted work, owner research, maintenance release, live app and credentials.
No subagent was spawned, and metadata still exposes no identified controllable
Claude session. Shared docs/API/scenario map provide the handoff.

Implemented worker-only DirectAdoption inspect/prepare/apply using the existing
explicitly enrolled runtime and original-source publication boundary. Selected
originals become a sealed byte-validated scientific lease after SHA/page/located-
quote checks; no matching list ZIP, list mutation or model call is needed. Observe
actual saved science, materialized paper parents, desired source versions and
absence of native scientific ownership. Compound publication rechecks them and
commits source grants/activation, identical science/model/time, native history,
outbox and retry receipt together. Generic projection's unowned-row protection
is unchanged. Cancellation, changed inputs, forgery and late failures preserve
original research; harmless staged cache may remain. Existing/retired native
science requires its separate repair/restoration path, not direct adoption.

Connected the operation to the current saved reader: eligible private rows offer
original selection; canceling a picker starts no job; verification has no research
commit; separate confirmation admits sync. Duplicate actions share normal worker
admission. Existing close/cancel/context guards drain work, and actual queued GUI
delivery rechecks the row/binding before enabling confirmation. A changed row
requests refresh. Already-native/historical/unenrolled rows do not offer it.
The owner is held weakly and background closures carry service/data, not widgets.
Actual picture inspection prompted existing-primary-role styling for confirmation,
with new AI generation secondary during review; Choose again immediately resets
that hierarchy. No decorative motion/dependency or extra login/AI permission flow.
Relevant local integration, harvest and frontend-motion static-design guidance
were applied. No canonical/global skill files or generated copies were changed.

Initial core 8 passed in 44.16s. Expanded 9 pass/1 invalid-fixture failure in 58.03s:
new PDF hashes lacked their derived source IDs; the validator correctly refused.
Corrected fixture updates and validates source/statement/passage/report IDs; code
validation was not weakened. Corrected core/native recovery 11 passed in 79.92s.
The real native journey uploads new originals, backs up/restores the authority,
joins a fresh device, checks unchanged report/model and exact three PDF bytes.
A later false-located-quote case independently rejects a valid PDF hash without
mutating science. Initial actual UI 5 passed in 36.62s; expanded pending-apply and
queued-delivery checks were added afterward. New-test formatting findings and a
script assertion against an already formatted span were corrected before testing;
no old tests were changed/skipped/loosened.

Integrated affected gate: build/lineage-direct-adoption-integrated-20261114.log,
103 passed in 609.06s (initial 20 new plus 83 adjacent cases). Its specific session
80750 stayed live during silent output; approved read-only counters for its exact
child confirmed 258.7 CPU seconds and 187.8 MB working set at one observation.
No unrelated command lines, accounts or processes were printed/changed; an initial
sandboxed counter request was denied and the approved read-only counter succeeded.
The process was not restarted. Long fixture/native scenarios are not a made-up
percentage, ETA or evidence of overall release progress.

After that gate, visually justified style-only UI changes passed eight in 67.20s,
and Choose-again/confirmation paths passed two in 19.74s. Final capability review
replaced self object-address identity with a random service scope; a deterministic
alias-seam negative case proves a foreign service cannot borrow the plan while
its owning service still applies it. This strengthens the documented service
scope, not a claim of a malicious-Python sandbox. Final all-current-core and two
reader flows: 15 passed in 138.95s. Current new-case count is 21 (13 core, eight UI).
These scopes overlap; do not sum counts. The input manifest retains seven hashes
from the 103-case gate, the exact three subsequent files, seven final hashes and
layered receipts. No source/test change followed the final delivery gate.

Final docs 52 passed in 1.72s; privacy/all-repository Ruff/scoped whitespace passed.
A new trailing README blank was fixed before the final gate. Viewed final synthetic
Qt screenshot uses an explicit installed font registered before widgets and no
private path. Late-font capture initially had missing glyph/overdraw artifacts;
re-rendered rather than editing bitmap data. Final capture case passed in 9.93s.
README now links the workflow beside native import guidance and includes the real
fixture screenshot. Status/roadmap no longer list supported private-row adoption
as universally missing; unknown legacy migration remains explicitly unresolved.

The authoritative full report remains full/failed/full_check_passed=false. No full
check ran, and no commit, push, release, installer or app restart is claimed. The
old three staged-test contracts remain unchanged and no async reply is inferred.
Their reconciliation must be assessed against the already accepted feature scope;
this turn did not treat a timeout as approval. Complete audit, per-change recovery
reconciliation, coherent full gate, operational GCP/TLS/retention and installed
Windows/Apple Silicon/phone acceptance remain open. No real ADC, GCP request,
research upload, model call or provider login occurred. Goal remains active.

Harvest review: validated-local evidence now shows selected originals and archive
originals share one typed scientific/compiler boundary while SQL observation and
source ownership remain separate. Late GUI delivery and independent plan scope
are verified at their actual boundaries. Existing integration rules cover these;
keep concrete evidence here rather than manufacture a universal/new global rule.


## 2026-11-14: prepare a coherent full gate after contract reconciliation

Previous goal turn classification: progress (direct source-selection adoption,
native/peer recovery and guarded confirmation UI). Revalidated develop/0.5 at
aa4b30e, project scope/architecture/handoff and the actual three failing tests.
Exact current reproduction: three failed in 10.77s. No production code changed.

First repaired only the absent-schema rollback fixture: verify both derived
metadata tables are empty, remove them only in this isolated fixture, assert
absence, then retain every original rollback assertion. The existing initialized-
baseline whole-SQL preservation case remains unchanged. This fixes test setup,
not transactional behavior. Added a fresh child import boundary: the known Lineage
AI task remains present, all registries remain unchanged, no default workspace
is created and attempted model/process/network work is forbidden and observed.
The initial setup/boundary cohort passed 14 in 53.18s.

Revisited the earlier optional approval question against accepted requirements.
Per-feature AI routing and complete native research-package import were already
requested and documented. A helper-import side-effect prohibition does not mean
an agreed task must remain globally absent forever. The public import's old
fixture has an invalid membership timestamp; it should fail that specific
validation, not claim every Lineage package is unsupported. Adjusted only those
stage-only expectations; no new activation/behavior was introduced and no missing
reply or timeout was inferred as consent. Preserved all default-store/producer/
generic-wire/raw-delete and no-partial-research/outbox guards. Added complete
valid-metadata public import with exact three PDFs/model/science/time and retry,
and valid-metadata missing/corrupt-original refusal. No skip or harness change.

Repaired modules/public-boundary cohort: 58 passed in 148.98s. Stronger attempted-
call observation plus existing per-task routing: four passed in 4.03s. These
overlap. New-test import formatting was fixed before execution. Scenario/decision
map: docs/testing/lineage-contract-reconciliation.md. Owner research, provider
logins, maintenance release and current app remained untouched. No cloud, paid
call, upload, commit, push, installer or release occurred. Current goal remains
active; complete audit/recovery integration and hosted/installed acceptance are
not claimed by these preflights. Next action is the unchanged standard full check
on a hashed, frozen candidate, not more repeatedly broadened partial selections.


## Workspace-scoped deck inputs (2026-11-14)

New native deck observations emit closed schema-2 input provenance with their
origin workspace. Manual edits preserve the exact loaded provenance, including
legacy schema 1. Saved-evidence reads accept same-workspace references only;
foreign scope stays explicitly unverified even when native IDs coincide. No
original is inferred from the current focal paper. Mobile validation and offline
reopen retain the same block. Original-source manifests remain strict schema 1.

An existing audit test caught a variable shadowing error: the new input block
replaced the captured database-version witness. Renamed the variable; retained
all old read-only, mutation-refusal and exact-source assertions.

Evidence: 46 affected Python cases passed in 78.29s pytest / 81.5s total; 17 mobile
artifact cases passed; actual JavaScript/Python HTTP authority fixture passed.
Critical integration gate: 14 passed in 7.68s pytest / 10.8s total. Privacy and
Ruff passed. All runs used the Windows 25% CPU/two-processor governor. No full
historical suite, paid AI or owner research database was used.

Fresh ignored PWA artifact: `build/mobile-workspace-inputs-v23`, 50 files,
3,911,242 bytes, independently verified content ID
`f61ec2ac7aab6f917da315ec9f53354275073e2d863a7f720b8b39139128e776`.
This is build integrity evidence, not browser/physical-device acceptance.

Full deck recovery, verified cross-workspace source mapping, hosted TLS and
installed Mac/phone acceptance remain open. The existing local-integration skill
already distinguishes historical proof from current authority; no duplicate skill
or unverified global rule was added at this checkpoint.


## Atomic native deck recovery and desktop review (2026-11-14)

Implemented `sync_recovery_deck_group.prepare` and the existing recovery review's
English/Traditional Chinese **Use old complete deck** action. Full editable
objects, tables, both PNG assets, speaker notes, source URLs/catalog and verified
root-paper originals survive new native publication and independent peer reopen.
Confirmation/cancellation and repeated clicks use the existing worker boundary.

Original ownership, desired/applied deck, outbox and payload-bound receipt share
one transaction. Native artifact activation uses its established capture boundary;
the first real rollback test exposed direct writes being correctly denied before
that fix. Damaged/missing bytes, stale targets, altered prepared plans, late
private legacy files and post-activation file changes cannot partially publish.
A recorded successful retry preserves later deletion; a new explicit restore is
required. The old source and owner research stay unchanged. No paid/model call.

Evidence: 18 deck/claim/note/held-worker cases passed in 99.51s pytest / 103.1s total.
The final table/caption/URL comparison and real peer scenarios plus all 14 curated
critical cases passed: 17 in 38.68s pytest / 42.1s total. These scopes overlap and
are not summed. Privacy, Ruff and configured whitespace checks passed. Windows
CPU hard cap 25%, maximum two logical processors; no historical full suite run.
The existing scenario map documents each protected user-visible requirement.

Related/foreign original-owner mapping, legacy private-deck enrollment,
highlight/link/Lineage recovery, scientific semantic validation, hosted HTTPS and
installed Mac/phone acceptance remain open. No release, deployment or push.
Existing transaction/receipt/provenance skills already cover this reused method;
no duplicate skill was introduced. No controllable Claude session was available;
the existing execution board remains the handoff.


## Recorded related-paper deck originals (2026-11-14)

Extended the same native deck recovery operation to related originals whose
recorded paper/document epochs and hash match retained source operations.
Existing explicit metadata recovery decisions prove destination parent epochs;
missing parents are named for review. Native comparison displays original paper
titles/hashes. Equal bytes under different recorded owners are not merged.
All original ownership, editable deck/applied slot, outbox and decision remain
atomic. Existing root-only receipt shapes stay readable. A successful retry
preserves later source retirement even after old source assets are lost.

The selected module passed 17 cases in 148.54s pytest / 152.1s total. Final
parent-prompt/related-native-peer/UI scope plus all 14 critical cases passed:
16 in 33.40s pytest / 37.0s total. These overlap. Privacy and Ruff passed under
25% CPU / two-logical-processor / 300-second Windows limits. No historical suite,
real accounts, paid AI, deployment or owner research was used. The new fixture's
initial unsupported paper-deletion attempt was corrected to the supported source
retirement contract; production deletion policy and old assertions were retained.
A contradictory-owner test also prompted validating all declared ownership before
reading PDFs, so the actual ambiguity is reported before an unrelated missing file.

Remaining: different input-origin workspace mapping, portable saved-evidence
mapping after recovery, unknown legacy provenance, highlight/link/Lineage groups,
hosted HTTPS and installed Apple Silicon/phone acceptance. No release or push.
The existing skill already covers exact ownership, explicit parent lifetimes and
atomic receipt retry; no redundant global rule or new worktree was introduced.


## Exact-original highlight analysis and mark recovery (2026-11-14)

Added the typed `sync_recovery_highlight_group` service and the existing native
recovery review action. It verifies owned PDF bytes, normalized original-text
identity and every complete quote, then retains selected roles/reasons/coverage
with freshly verified mark geometry. Current hidden choices take precedence;
manual and unrelated marks stay unchanged. Source quote identity and uncaptured
source/target words are checked before publication. No model is invoked.

Original ownership, analysis, marks, outbox and receipt share one transaction.
Child failure/cancellation rolls the group back. Successful retry recognizes the
original decision after later deletion or lost source bytes; corrupted receipts,
changed targets and altered prepared plans cannot restart writes. An old native
source need not have a current capture writer: its journal/head and visible rows
are verified read-only. Target native capture remains required.

Evidence: 12 focused cases passed in 94.47s pytest / 97.9s total. Final native peer
(no AI calls), adjacent claim/note review, repaired Traditional Chinese deck label
and all 14 critical cases: 18 passed in 40.31s pytest / 43.7s total. These overlap.
Privacy/Ruff/configured whitespace passed under 25% CPU, two logical processors
and a 300-second budget. No historical suite, hosted service, paid call or owner
research was used. Native English/Traditional Chinese confirmation, cancellation
and repeated activation were exercised in actual Qt widgets.

The new UI fixture initially reused an observation-scoped review ID. It now
locates the stable operation in the newly prepared page, preserving the existing
HMAC observation guard. A real source lacking a capture writer exposed an invalid
read-side dependency, corrected without initializing/writing the source. New
Traditional Chinese strings (including earlier deck additions) had been converted
to question marks by the shell-to-Python input encoding. UTF-8 text is repaired;
actual Chinese action labels are asserted in both affected native flows.

Remaining: independent manual-mark and reading-link/Lineage recovery, explicit
source-deletion decisions, foreign-workspace/legacy ownership and portable audit
mapping, hosted HTTPS and installed Apple Silicon/phone acceptance. Exact quote
location does not certify semantic support or change the active primary PDF.
Existing ownership/transaction skills cover this reused method; no duplicate
skill, extra worktree, release, deployment or push was introduced.


## Independent manual-highlight copies (2026-11-14)

Extended the existing sealed note-copy adapter, not a parallel recovery engine.
Native manual-highlight puts receive a distinct portable copy key, retain quote,
position and creation time, and return a distinct result format. Notes retain
their original identity derivation and receipt format. Owned original, mark and
journal/outbox share the existing transaction and retry boundary. Later deletion
stays deleted on repeat; new copies can use the destination's verified original.

Normal drawing and recovery now share line-aware selection parsing, including
cross-line hyphen joins. The parser grants no file/write authority. Recovery
still checks owned bytes, source paper lifetime, exact hash, coordinates and quote.
The typed adapter discharges only the manual mark's generic source-closure blocker;
other research stays unsupported by this copy action.

The real storage schema permits one manual mark per paper/PDF/selection. A new
UUID alone cannot make a duplicate valid. Added a bounded semantic geometry lookup
before copy and again inside the transaction; collisions preserve the existing
mark and show a clear disabled-action reason. Different positions stay independent.
Native English/Traditional Chinese review shows full quote/page range, confirms
before writing, cancels without work and rejects rapid repeated activation.

Evidence: eight backend cases passed in 67.52s pytest / 70.9s total. The three
native UI cases passed in the subsequent shared-adapter cohort; that cohort then
failed on an old note error-message assertion. Both legacy error wordings were
restored without changing any old assertions. Final integration scope includes
all 17 existing note-copy cases, positioned-note native transfer, two normal manual
add/remove variants, all three manual-copy UI cases and all 14 critical journeys:
37 passed in 132.08s pytest / 135.8s total. These scopes overlap. Privacy and Ruff
passed with 25% CPU/two processors and a 300-second budget. No historical suite,
owner research, actual account login, paid call, deployment or release was used.

Remaining: reading-link/Lineage groups, explicit source-deletion decisions,
foreign-workspace/legacy and portable-audit mappings, hosted HTTPS and installed
Apple Silicon/phone acceptance. Existing copy/ownership/receipt skills cover this
reuse; no duplicate skill, extra worktree or protocol feature was introduced.


## Read-only exact explanation-link context (2026-11-14)

Added `sync_recovery_reading_context.resolve` and native readable comparison.
The actual source review resolves the saved key against full rendered sections,
ordered highlight items and exact PDF. It tries verified current native values,
then bounded own-journal/accepted-inbox versions. Optional absence stays explicit;
section IDs are not shifted by borrowing a newer explanation. Foreign conflicts
cannot supply accepted dependencies. No model, source/target write or replay grant.

The output binds visible sections/items, not unrecorded execution metadata.
Actual retained metadata is preserved without inventing old timestamps. Search
and result budgets fail explicitly; no truncation or approximate quote match.
A source-only highlight verification helper now takes the real source observation,
while the existing highlight recovery keeps its target authentication and writes.
Native English/Traditional Chinese view shows actual old explanation/quote/link
text and explicitly says comparison only. Group Apply is not enabled yet.

Evidence: 13 source/optional/history/foreign/budget/actual Qt cases passed in
102.13s pytest / 106.7s total. Shared highlight source/native peer, adjacent
highlight/note/manual UI and all 14 critical journeys: 18 in 67.80s pytest / 71.9s
total. Scopes overlap. Privacy/Ruff/configured whitespace passed under Windows
25% CPU/two logical processors/300-second budgets. No historical suite, owner
research, actual accounts, paid AI, deployment, push or release was used.
README recovery prose is consolidated around tasks and one guide instead of
appending another implementation-history paragraph.

Next: compose confirmed link-group publication through the real target observation.
Re-resolve source inputs, compare every destination member, and explicitly review
optional absence before clearing a newer target explanation. Stage originals
off-lock; original ownership, all grouped content, journal/outbox and decision
receipt need one transaction and rollback tests. Successful retries must preserve
later edits without requiring lost originals. The read-only output is not write
authority. Lineage/origin/audit mapping and hosted/installed-device gates remain.
Existing ownership/history skills cover this reuse; no duplicate/global skill or
additional worktree was introduced.


## 2026-11-14: inspect validation scope without running it

- Added `scripts/check.py --plan` for the existing critical/release/focused/docs/full
  profiles. It reuses the runner selection and lists named journeys, exact Python
  selectors, frontend/mobile files and stages without collection, subprocesses,
  runtime discovery, privacy scanning or report writes. Invalid selections fail.
- The preview explicitly distinguishes file selectors from collected case counts
  and automated scope from installed-device/live-provider/hosted acceptance. It
  does not prune historical tests or claim release acceptance.
- One bounded affected-plus-critical check passed: 70 cases, pytest 11.29s, total
  14.8s; privacy and Ruff passed. Windows job cap: 25% CPU, at most two logical
  processors, 300s deadline. New behavioral cases cover both curated profiles,
  unchanged existing reports, no runtime/command execution, focused scope and
  invalid-selection refusal. No historical full suite, release/device execution,
  paid calls or owner research access. Initial Ruff line-length failure was fixed
  before this pass; no assertions were weakened.
- This extends the existing runner rather than adding another test system. No new
  reusable architecture pattern was established; canonical skills are unchanged.


## 2026-11-14: confirmed exact reading-link groups

- Added `sync_recovery_reading_group.prepare`/`ReadingGroup.apply` using actual
  target observations, the existing source resolver, mapped paper ownership and
  exact quoted-original verification. Four native contents and owned original
  share the transaction with outbox and a bounded fingerprinted decision receipt.
  Optional source absence is explicit: differing current words require reviewed
  replacement and a native delete; existing absence needs no write. Native paper
  deletion remains unsupported. Manual/AI PDF layers and active PDF stay separate.
- The English/Traditional Chinese native review now offers a confirmed complete
  explanation group, readable source/current members and a clearing warning.
  Cancellation has no writes, repeated activation saves once, and failed children
  roll back content/original ownership/outbox/receipt. Unowned staged bytes may
  remain. Corrupt receipts and uncaptured private words refuse safely.
- Saved retries validate retained source/native operations and exact context, not
  current availability or write eligibility. They preserve later edits/deletions
  and can recognize success after old original bytes become unavailable. The UI
  skips redundant context resolution when a sealed group/receipt is available.
- Evidence: source-context plus initial backend scope, 18 passed in 158.94s pytest
  / 162.6s total; new seven group cases plus all 14 critical cases, 21 passed in
  103.78s pytest / 108.0s total; final affected bilingual Qt confirmation/reload,
  source comparison and docs, 14 passed in 67.19s pytest / 75.2s total. These are
  overlapping selections, not a summed count or full-suite claim. Windows bounds
  were 300s, 25% CPU and at most two logical processors, one check at a time.
- The complete-group case performs real FileTransfers and native synchronization
  to an independent enrolled client, compares all four saved content tables and
  exact original bytes, and preserves nonempty manual/AI mark layers. An added
  source-file-unavailable retry passed in a stopped follow-up run (1 passed,
  1 failed); its overall failure was the new UI test trying to reuse the intentionally
  invalidated observation after save. The test now uses the actual reload flow;
  both languages and adjacent comparisons pass in the final 14-case selection.
  A fixture helper initially guessed a nonexistent table; corrected to the actual
  annotation registry without weakening the behavior assertion. Ruff formatting
  failures were corrected before passing checks. Existing readonly comparison
  expectations were intentionally updated for the accepted confirmed group action.
- Reuses the existing source-versus-target, atomic transaction and durable-receipt
  pattern. No new global skill rule, worktree, task board, paid call, owner research
  access, cloud deployment, push or release. Lineage groups, independent source
  deletion, foreign/legacy mappings, audit continuation, hosted HTTPS/native vaults
  and installed Windows/Apple Silicon/physical-phone acceptance remain open.


## 2026-11-14: multi-original native Lineage groups and read-only WAL leases

- Added a sealed native Lineage group adapter and English/Traditional Chinese
  comparison/confirmation in the existing old-device review. It verifies retained
  source operations, all selected parent mappings, exact readable PDFs/page counts
  and every recorded located quotation. Original ownership/outbox and a fresh
  source-pinned scientific operation/history commit with one bounded receipt.
  Report/selected identities and generation metadata stay exact; no source grant
  is replayed and no model is called by recovery. Different/retired target reports
  need explicit replacement; uncaptured words refuse. Existing source retirement
  still requires its own explicit decision.
- Preparation is read-only. Partial child exception/cancellation rolls back all
  original ownership, report/schema, outbox and receipt; immutable unowned cache
  bytes may remain. A saved retry checks retained native evidence and never
  overwrites later edits/deletions. Original/primary PDFs and other research remain
  independent. A source context or cached metadata alone grants no write authority.
- Actual native FileTransfers and recovered authority deliver an unchanged
  portable report to a fresh enrolled client; all three selected originals are
  independently downloaded and verified without primary PDF activation. Bilingual
  Qt actions show full statements/quotes/sources, explicitly retain semantic limits,
  cancel without writes and save one decision despite repeated activation.
- Found a first-read source-review false positive before group publication: main
  native version stayed identical while a mode=ro open created a zero-byte WAL.
  Fixture GC did not solve it. A read-transaction pin broke an unchanged concurrent
  writer assertion; idle-reader initialization still failed after sidecar cleanup.
  Both approaches were removed. Only nonexistent/zero-byte WAL are now equivalent;
  main and every nonempty WAL keep full native versions. Existing concurrent-write
  tests are unchanged; two new real first-read cases verify stable review/index
  and invalidation after a real later write. No persistent connection or retry loop.
- A new test helper initially built a space-separated SQL column list and failed;
  fixed to the actual comma-separated schema list, with assertions unchanged.
  Formatting errors were corrected before passing gates. Four backend group cases
  passed in 27.31s pytest / 31.9s total. Final coherent affected-plus-critical gate:
  63 passed in 124.49s pytest / 129.2s total; privacy/Ruff passed; no skips or
  failures. Selections overlap and are not a summed completion percentage. Windows
  budget: 300s, 25% CPU, at most two logical processors, one check at a time.
- Recorded the validated-local SQLite lesson in the existing canonical integration
  skill/evidence, not a new skill/global rule. No worktree, task board, real login,
  paid call, owner research access, push, release or deployment. Separate gates:
  source-deletion/foreign/legacy ownership and scientific-audit mapping, hosted
  HTTPS/native vaults, installed Windows/Apple Silicon and physical phone use.

- Post-documentation canonical skill/usage contracts plus critical journeys:
  37 passed in 15.78s pytest / 22.7s total. The peer case was then extended through
  the official Lineage original reader and GUI-delivery proof for all three sources;
  that sole changed case passed in 21.75s pytest / 27.9s total. Product source was
  unchanged; no full suite or repeated broad check.
- Curated release selection keeps its size: the complete Lineage recovery/peer/
  official-reader case replaces the narrow corpus-key-only representative. The
  old test/assertions remain intact for domain changes and historical diagnosis.
- Final changed runner/usage contracts after selecting the complete Lineage release
  representative: 56 passed in 2.15s pytest / 7.3s total, privacy/Ruff passed.
  The release baseline still has 33 Python selectors; selectors are not collected
  case counts. Product source and earlier scoped evidence stayed unchanged.


## 2026-11-14: owner interruption about validation latency

- Original-source use/retirement is an uncommitted candidate in the existing
  stabilization worktree, not integrated, pushed or released. The source publisher
  still refuses implicit restoration; explicit reviewed use creates a fresh file
  lifetime. Candidate tests cover cache/note preservation, rollback/cancellation,
  stale target/corrupt receipt, actual en/zh confirmation and an independent peer
  through use/retire/use. Bad noncanonical artifact JSON is rejected, not normalized.
- Latest bounded affected-plus-critical run finished with 41 passed in 234.60s
  pytest / 266.3s runner (266.985s governor). It was not the historical full suite.
  Slowest fixture setup was 72.17s. The live faulthandler stack pointed to
  `sync_service.py:83` opening the synthetic authority with `sqlite3.connect`,
  during positioned-note fixture bootstrap/offline download, before the new
  source-decision behavior ran. Lock contention, storage delay and scheduling
  remain hypotheses; the stack alone does not prove the cause.
- The owner correctly noted the accumulated delay: multiple earlier focused
  iterations also ran. Do not quote just the last gate duration as total waiting.
  No further test was launched after the concern. The known runner completed,
  all tool handles were observed terminal, and the governor reports a hard cap
  of two logical processors, 25% job CPU, below-normal priority, 300s deadline.
  A short live CPU sample after completion is not historical peak utilization.
- Next: simplify the new source-decision fixture, which currently inherits a full
  positioned-note recovery/download setup it does not need. Preserve one actual
  peer lifecycle and the meaningful failure/confirmation boundaries; no bulk test
  deletion, raised budgets or parallel runners. Reuse passing evidence for
  unchanged product code. Finish docs/checkpoint only after the coherent candidate
  and any changed fixture are verified. A speculative active-prior-publication
  guard patch failed its precondition and did not land; do not report it implemented.


## 2026-11-14: reduce new original-decision setup before more validation

- Replaced only the new file's inherited positioned-note/original/offline-download
  fixture with one native backup/recovery, metadata-only join, one real synthetic
  PDF and both plain/positioned saved notes. Actual authority enrollment, native
  writes, parent mapping and blob ownership remain real. The dedicated peer case
  still uploads/downloads and verifies use/retire/use convergence, exact bytes,
  fresh restored incarnation and preservation of notes/cache/later decisions.
  No historical test, assertion, scope guard or time/resource budget was weakened.
- Product source is unchanged from the prior 41-case critical/affected pass.
  Only five changed fixture cases ran: 5 passed in 48.55s pytest / 55.2s total,
  privacy/Ruff green. Setup durations 5.67-7.06s; the prior 72.17s SQLite-open
  outlier is not claimed causally fixed. No parallel runner, real login, model
  call, owner database, process kill or background diagnostic was introduced.
- Completed API/workflow/scenario documentation for the existing candidate. The
  publisher defaults to refusing retirement/reparent restoration; the explicit
  original decision stages owned verified bytes and publishes a fresh lifetime
  with a bounded local receipt. Retirement grants no bytes and can work offline.
  Bad canonical JSON/missing source bytes, orphaned native request, stale target,
  cancellation/write failure and corrupt receipts refuse safely. Unknown
  foreign/legacy mappings, retired-input scientific rebinding/audit, other deletion
  choices, hosted/native-vault and installed/physical-device gates remain open.
- Added only one release representative for the distinct original-source
  use/retire/use peer journey. The curated baseline now has 34 Python selectors,
  not 34 collected cases; focused validation never runs all those by habit.
- Final changed runner/usage contracts passed: 56 cases, 5.17s pytest / 12.6s
  total, privacy/Ruff green. No repeated 41-case product run. Existing critical
  evidence covers unchanged product code; the changed fixture itself has the
  fresh five-case pass. Existing typed-transaction/source-lifetime skill patterns
  cover the implementation; fixture simplification is recorded locally rather than
  manufacturing a new reusable skill. No hosted/device completion claim.


## 2026-11-15: Explicit restored-original Lineage rebinding

- Extended the existing three-original native peer journey rather than adding a
  Cartesian scenario matrix. Native retirement hides the report but retains its
  put/history; same-byte restoration gives the source a fresh incarnation and
  does not revive old scientific pins. Explicit reviewed replacement verifies
  retained native source ownership, canonical artifact closure, readable PDFs,
  page counts and every located quote, then atomically publishes fresh target
  dependencies/report/history/receipt. No model, primary PDF or owner data used.
- Hidden current reports remain inspectable in the comparison. Native projection
  marker/history/policy distinguish real retired-input hiding from an uncaptured
  deletion or edit. Missing ownership/bytes, changed paper lifetimes and unknown
  legacy/foreign mappings still refuse. Desktop retry IDs include actual target
  input lifetimes so an old receipt cannot suppress a later restoration decision.
- The native journey checks independent peer delivery, old reader-proof refusal,
  newly verified reader delivery, stale review refusal, fresh-observation saved
  retry and preservation of later edits/source restorations. Existing exception,
  cancellation, false-quote, corrupt-receipt and en/zh-TW UI cases remain.
- Diagnosed initial review failures instead of weakening file guards. The shared
  test_sync_files.side fixture used a SQLite transaction context without close.
  A disposable single-file reproduction showed gc.collect closing that writer
  changed its Windows USN while stat/ChangeTime stayed unchanged; explicit close
  made collection stable. Added contextlib.closing at that actual fixture seam.
  This is separate from the earlier unexplained 72.17s SQLite-open setup outlier.
- Before the UI retry-key extension, six affected cases passed in 76.43s pytest /
  82.0s total. Final source: curated critical journeys + six affected Lineage
  cases + one original lifecycle + one editable-deck transfer representative:
  22 passed in 106.51s pytest / 112.8s total, privacy and Ruff green. One bounded
  runner, 300-second deadline, at most two logical CPUs and 25% job CPU cap.
  No historical exhaustive/release run, paid provider, production deployment or
  installed Windows/Apple Silicon/phone acceptance is claimed.
- Existing canonical local-integration skill already requires explicit SQLite
  handle closure, separate retained proof/current eligibility and caller-owned
  atomic receipts. This checkpoint adds project evidence, not a duplicate skill.


## 2026-11-15: Confirmed native Lineage retirement

- Reused the existing sealed LineageGroup API, native tombstone codec, projection
  and recovery UI. Selected typed deletes now offer a distinct en/zh-TW action
  and confirmation. Active reports require explicit replacement; current report
  words are visible before the choice. No arbitrary empty payload is promoted
  into a scientific deletion and no old envelope is replayed.
- Source/target observations, mapped paper lifetimes, native report/marker checks
  and caller-owned transaction protect a fresh native deletion, history/outbox
  and receipt. Absent/already-retired reports record a no-op decision. No original
  bytes, model call or download is needed. Cancellation/late failure rolls back;
  stale comparisons and corrupt receipts refuse; successful saved retries cannot
  delete later restored reports. Desktop request identity includes the target
  report lifetime, permitting a new explicit decision after a later restoration.
- Extended the existing independent peer journey with report retirement, exact
  retained native report history, three unchanged original manifests, nonempty
  independent notes, later restored report and safe old retirement retry. Existing
  bilingual UI journeys now confirm/cancel/flood both restore and retirement.
  Added only two failure variants for retirement rollback, absent decision, stale
  target and corrupted receipt; no historical assertion was removed or weakened.
- Eight affected cases passed in 94.75s pytest / 98.1s total. Then critical +
  usage-doc contracts: 23 passed in 8.55s pytest / 11.9s total. The final added
  exact-history assertion reran only its one overlapping peer journey: 1 passed
  in 23.31s pytest / 27.2s total. Privacy/Ruff green; sequential bounded runs,
  300-second deadline, at most two logical CPUs and 25% job CPU cap. Do not sum
  overlapping cases. The existing release representative covers this expanded
  lifecycle without adding another release selector or historical suite run.
- Existing typed-operation/atomic-receipt skill guidance already covers this
  extension; no new global rule/skill, worktree, daemon or task board. Other
  scientific/manual-mark deletion choices, foreign/legacy mappings, broader audit
  integration, hosted identity/HTTPS/native vaults and installed Windows/Apple
  Silicon/physical-phone acceptance remain open. No release or deployment.


## 2026-11-15: Useful packaged-acceptance failure reports

- Audited the current release scope before choosing another local feature. Mac
  installed verification previously wrote report.json only on total success,
  leaving failures as disconnected raw logs. Extended that existing runner, not
  the app protocol or a new daemon/service. No packaged binary was built or run.
- The closed paperfact.packaged-acceptance.v1 report is durably updated at each
  named check and on failure, timeout or Ctrl+C. It retains completed checks, the
  detection stage, categorical failure and host OS/architecture. Only status
  passed + passed true + exit 0 accept the packaged local workflow. Hard kill or
  report-write failure may leave an incomplete running/missing report, never pass.
- Version is parsed only from the frozen CLI; commit/dirty are allowlisted from
  bounded fixed packaged metadata reads. Unknown values stay unknown; no mutable
  checkout identity is substituted. Reports exclude raw exception/command/output,
  private paths/accounts/environment and research. Raw logs stay separate and
  require review. Existing output folders are refused without changing old reports.
  CLI exits 1 on failure and 130 on interruption, without printing raw exceptions.
- Tests cover process failure, zero-exit background traceback, timeout with partial
  local output, missing executable, interruption, metadata limits/privacy and
  preserved previous runs. One fake-child success journey exercises the actual
  orchestration, real synthetic ZIP fidelity and duplicate-import SQL assertions;
  it is not native-app acceptance. A real child Python CLI invocation against a
  nonexistent bundle checks sanitized nonzero failure and unchanged old report.
- Initial core + report/distribution/usage selection: 36 passed in 11.54s pytest /
  17.3s total. Strengthening the success journey exposed platform.machine launching
  a Windows cold-start subprocess before report initialization. Reused the app's
  no-shell sysconfig/os.uname approach. Final changed report/distribution/usage
  selection: 23 passed in 2.80s pytest / 6.8s total, Privacy/Ruff green. Unchanged
  app critical evidence is reused. Historical assertions/unchanged functions were
  preserved, not loosened; no whole-suite or packaging run during iteration.
- README, toolchain, release and Mac acceptance guides now explain report states,
  candidate identity, retry directories and sharing limits. Existing CI already
  collects report.json in its always-run provenance artifact; workflow upload
  permissions/log collection were not changed. No release/deployment was invoked.
- Existing public-app-support skill covers categorical reports and separate raw
  logs; existing local patterns cover no-shell identity. No duplicate/global skill
  was created. Actual frozen Windows/macOS/Linux execution, native Mac foreground/
  Keychain, hosted identity/HTTPS and physical multi-device/PWA acceptance remain
  open alongside the remaining research recovery/mapping/audit requirements.
- Final updated usage-doc contracts: 9 passed in 1.42s pytest / 9.7s total;
  no repeated product/core or packaging run after documentation-only edits.


## 2026-11-15: Shared explicit historical original inspection

- Factored bounded retained-native ownership and exact PDF closure into the
  existing original-decision module. inspect_retained verifies the actual file
  slot/version, source workspace/paper epoch, journal/accepted history, canonical
  owned closure and readable bytes. The shared note inspect_original helper opts
  in only with strict allow_retained=True. Source-side note/claim/highlight/
  explanation/deck recovery uses it; normal target/live original access does not.
- A document-pinned report is not retroactive original-file epoch authority.
  Native Lineage retains its exact source_dependencies checks. Target publication
  still refuses known retired/reparented files unless explicitly restored. No
  model/network, automatic activation, old-operation replay or source DB write.
  Legacy/foreign mappings and missing ownership/bytes remain explicit blockers.
- Extended five existing native peer journeys by retiring their old source first.
  All pre-existing payload, exact-file transfer, source-preservation, independently
  enrolled peer, curated-layer and saved-retry assertions remain. Added one lean
  case for default refusal, explicit read-only access, strict boolean, tampered
  journal, missing ownership despite cached bytes and unmatched paper lifetime.
- First bounded selection: 19 passed (14 critical + 5 original decisions), then
  the new case stopped at an invalid fixture setup: it tried whole-paper deletion,
  which the wire contract explicitly refuses. Product refusal was correct. Fixed
  only that new case to supply a genuinely unmatched paper incarnation; no product
  source changed between selections and no pre-existing assertion was weakened.
- Remaining affected selection: 6 passed in 111.67s pytest / 144.0s total. The
  privacy scan itself took 30.7s; its underlying scheduling/storage cause is not
  established. Reused the same-source passing critical/original-decision evidence
  instead of restarting those cases. Privacy/Ruff green; sequential 300-second
  bounded checks, at most two logical CPUs and 25% job CPU cap. No exhaustive,
  release or packaging run, real account, paid model or owner database involved.
- Existing local-integration patterns already distinguish retained evidence from
  current activation/ownership and require typed caller transactions. Reused
  those rules rather than creating another skill or global instruction. Remaining
  other deletion choices, foreign/legacy mappings, audit integration, hosted
  identity/HTTPS/native vaults and installed Windows/Apple Silicon/physical-phone
  acceptance remain open. No deployment, release or research migration.


## 2026-11-15: Equal PDF bytes are not paper-owner identity

- Continued the full release-scope audit while requested GCP project/HTTPS/budget
  inputs remain unconfirmed. No cloud resource/account/fee or real research was
  touched. Onboarding already has local operator issuance/pairing; hosted/device
  gates remain separate. The live saved-Lineage audit revealed a concrete hash-
  only owner attribution defect rather than requiring another generic subsystem.
- Before product edits, reproduced real three-paper saved Lineage with identical
  original bytes and distinct actual owners. Foreign-owner quotations incorrectly
  received located/exact checks against the focal paper. The primary regression
  asserted they could not be located and failed against the original source.
- source-checks.v3 adds optional closed source_paper_id provenance to items and
  passages. The typed saved-row adapter reads actual owners and maps native
  aliases through the real local registry. Legacy single-paper shapes stay valid.
  Different owners never become exact because bytes match; quotes/quantities stay
  unresolved and the bilingual GUI offers no foreign-owner jump. A focal citing
  passage retains its own owner independently of its statement subject.
- Propagated the boundary: no focal retrieval spans for an explicit foreign owner;
  appraisal refuses before account/model capture; fact output binding remains
  different_original, hence not exact-comparable. Extraction discloses the owner/
  binding in its existing captured prompt. No second call, paid fallback, model
  substitution, research rewrite, original activation or schema migration.
- Six new collected cases: quote/quantity/schema owner guard, actual multi-paper
  attribution, no borrowed spans/route/exact fact binding, native alias resolution,
  and actual en/zh-TW Qt findings/navigation. They use real synthetic PDF/SQL/
  publication data, with simulated model output only. Alias-registry verification
  is not a full enrolled or installed multi-device acceptance claim.
- Affected shared-schema/appraisal/facts/UI modules: 184 passed in 247.36s pytest /
  251.4s total (178 existing + 6 new cases). This selection is not the daily gate
  or a full historical/release run. Core/docs plus two existing deck compatibility
  representatives: 25 passed in 12.95s pytest / 17.1s total. Reused the first pass
  rather than repeating it after docs/selection changes. Release-plan/critical-
  default/docs contracts: 13 passed in 1.42s pytest / 4.9s total. Privacy/Ruff green,
  one bounded job at a time, at most two logical CPUs and 25% job CPU cap.
- Release adds only the equal-byte owner representative (35 Python selectors);
  daily critical remains 14. Historical assertions were not weakened or removed;
  no 184-case default, new workflow/job/daemon/worktree or global skill. Existing
  local-integration guidance already says same hashes do not grant source/owner
  authority; this is project evidence closing that known class of violation.
- Full per-parent/corpus/list-survey audit, expert scientific evaluation, remaining
  deletion/mapping/recovery, hosted identity/HTTPS/native vaults and installed
  Windows/Apple Silicon/physical-phone acceptance remain open. No push, release,
  deployment, owner app restart or research migration from this checkpoint.


## 2026-11-15: explicit current Lineage corpus audit

- Added worker-only `audit_lineage.prepare` and the optional `corpus_key` on the
  existing shared `analysis.audit` operation, including the official MCP adapter.
  The default focal audit is unchanged. One actual provenance selector chooses
  the maintained generated/imported/bound reader; failures never try another
  origin, download or equal-byte peer. No model, schema creation, original
  activation, research write or account access.
- Each source independently verifies ownership and exact PDF bytes; statement
  prose is checked only on its subject original, quoted passages on their own
  source. Partitioned indices retain an explicit saved-statement correspondence.
  Unavailable sources stay visible with no report. A sealed process-local result
  rechecks the actual owner, unchanged DB/WAL and every original at delivery;
  cancellation/changes discard the result. Unrelated real SQL writes invalidate
  this conservative read lease too; it is not a persisted authority or restore.
- Four-original, total-byte/page/word and aggregate saved-input/quantity limits
  fail explicitly. No quality percentage or semantic/causal certification.
- Five new collected cases only. Existing imported and bound-source cases gain
  one whole-corpus assertion each; existing official SDK test checks the optional
  schema and refusal. Daily critical remains 14 and release stays 35 selectors.
- Final directly affected modules: 13 passed in 35.64s pytest / 40.6s total.
  Imported/bound original representatives: 2 passed in 9.33s / 13.8s total.
  Earlier individual passes overlap and are not added to these counts. One first
  fixture erroneously corrupted the download instead of the actual owned
  retained snapshot; corrected the target, kept the refusal assertion. One
  misspelled selector collected no tests; the corrected representative pass is
  recorded above. Privacy and Ruff passed; all jobs sequential and CPU-bounded.
- Reused the canonical local-integration source-proof/delivery patterns; no new
  universal skill or global installation is justified. This is project evidence.
- Desktop whole-corpus control/lifecycle UX remains next; historical/legacy
  corpus mapping, list surveys, expert evaluation and hosted/native/installed
  Windows/Apple Silicon/physical-phone gates remain open. No deployment, push,
  release, owner-app restart or research migration.

- Final daily critical: 14 passed in 12.24s pytest / 17.7s total; privacy and
  Ruff green. This is scoped integration evidence, not exhaustive or installed
  release acceptance. No unchanged broad module rerun.


## 2026-11-15: desktop whole-Lineage action

- Added Check all originals beside the current Lineage actions. Reuses the
  existing shared sealed corpus worker, Qt thread/cancellation, activity hub and
  independent original viewer. No extra server, settings panel, workspace or AI
  call. The original saved-evidence panel retains its focal-only behavior.
- Real source-completion counts reach the local bar and existing app activity
  handle; repeated clicks cannot queue a second job. Findings stay under their
  own quotation, including unavailable-source text and an explicit snapshot-only
  summary. Located text does not establish scientific support or influence.
- Actual owner/row/selection/native/source guards run at delivery. Cancel,
  historical selection, another loaded paper and close/drain discard delayed
  results. Context invalidation hides previous findings. Idle close releases
  retained original proofs/bytes. No source activation or draft replacement.
- Seven new collected cases (two languages, failure/retry/unavailable, four
  pending lifecycle outcomes), not a cross-product. Existing dialog generation,
  saved-read, account, original-viewer and close behavior retained. Changed desktop
  modules: 20 passed in 172.63s pytest / 181.9s total. Setup dominated durations
  (synthetic PDF/DB publication), not paid calls. After the final idle-close and
  stronger language assertions, only their 3 affected cases reran: 3 passed in
  37.42s / 44.9s total. Earlier passes overlap; do not sum counts. Privacy/Ruff
  passed. Every job was sequential, max two logical processors, 25% CPU cap and
  300s wall budget. No historical or release suite was started.
- README/audit guide/test map and existing handoff updated; Mac acceptance M21
  explicitly requires a synthetic saved-Lineage fixture and real packaged UI
  results. Native layout/foreground and physical-device acceptance are not
  implied by offscreen Qt success. The frozen verifier does not automate M21.
- Reused the established provenance-before-delivery and shared-operation
  patterns; no new universal skill. No controllable Claude connector was exposed;
  the existing execution board remains the handoff. No push, deployment, release,
  owner-app restart or research migration. Remaining historical/legacy mapping,
  list-survey audit, recovery choices, hosted identity/HTTPS/native vaults and
  installed Windows/Apple Silicon/physical-phone acceptance remain open.

- Final daily critical: 14 passed in 17.26s pytest / 23.0s total, privacy
  and Ruff green. No full historical/release/packaging run. Reused unchanged
  core/CLI/MCP and imported/bound evidence from the preceding checkpoint.


## 2026-11-15: source-complete cross-device acceptance material

- The prior verifier seed contained only one PDF and a deep explanation, so it
  could not support the new Mac M21 corpus journey. Extended the existing demo
  helper with `acceptance_package(destination)`: one list member, two context
  papers, a typed synthetic Lineage, three originals/five pinned quotations, and
  four packaged PDF files. No new app command, server or worktree.
- The helper requires an explicitly bound empty absolute fixture workspace and
  new absolute output. Portable data is clearly authored as synthetic-fixture,
  with no requested/returned model. Production package validation checks the
  archive before publication; observed receiver import creates real imported
  original context. No sender-native grants, test-framework dependency, account,
  network, private paper or provider hook is used. Existing screenshot seeding
  remains unchanged except replacing deprecated fitz import with pymupdf alias.
- Packaged verifier seed now uses this material. New lineage-audit and
  lineage-audit-result stages invoke the actual frozen JSON CLI, require all
  three originals/five quotations, and refuse incomplete results. Report identity
  remains actual packaged metadata; M21 GUI/physical devices remain separate.
- Four new collected cases only: actual ZIP/duplicate import/public JSON CLI
  audit/re-export file equality, plus three safety refusals. Existing runner
  orchestration now asserts the new stages and failure on incomplete audit; its
  fake child apps are explicitly not native package acceptance. Final related
  modules: 16 passed in 10.10s pytest / 14.1s total, privacy/Ruff green. Earlier
  runs overlap. A deprecated import warning initially broke strict stdout; fixed
  the source rather than relaxing the assertion. A lint-only attempt ran no tests.
- Concrete ignored local artifact: build/acceptance-lineage-v1/
  Paperfact-synthetic-research.zip, 9,788 bytes, SHA-256
  b080d5312ed4e7d9da040cdd1216db1bc4531b23e0594d47274c208ed4259a9e.
  Exact delivered bytes separately traversed real source CLI import twice, audit
  and re-export in isolated account/data homes: 3 originals, 5 located quotes,
  4 byte-identical PDF files. material.json records observed results and marks
  native_package_acceptance false. This ZIP is research material, not an installer.
- README/toolchain/Mac guide/test map updated with child-only workspace binding,
  generation commands, original.zip handoff, checksum and actual stage meaning.
  No full historical suite, owner research, credentials, restart, cloud, push,
  installer build or release. Daily critical stays 14; release stays 35 selectors.
- Existing local-integration/package ownership guidance covers this verified
  boundary; no new global skill. Hosted identity/HTTPS/native stores, real
  installed Windows/Apple Silicon/phone acceptance and other remaining recovery/
  legacy/corpus gates stay open.

- Final daily critical: 14 passed in 5.40s pytest / 8.7s total, privacy/Ruff
  green. No repeat of unchanged corpus, desktop, mobile or historical matrices.

- Concurrent integration advanced to c7a9c60 with the other reader session's
  4c8fa36 (changed-block typesetting), e17c35c (one-pass file-name mapping) and
  c23e336 (stall screen/tab context). Preserved them by merging develop/0.5
  into the existing stabilization branch (14d37bb), after checkpointing this
  material as 805ef53. No reset, copied source or new worktree.
- Revalidated the actual merged tree only where it changed: the same acceptance
  modules plus three name-collision/index boundaries, 19 passed in 10.05s pytest /
  13.3s total; merged daily critical, 14 passed in 5.70s / 9.1s total. Privacy/Ruff
  green. These overlap earlier counts. Incoming rich-view/stall changes were
  preserved, not independently certified as a full native UI acceptance by this
  package checkpoint. Existing board remains the shared handoff.


## 2026-11-15: confirmed single manual-highlight retirement

- Existing recovery choices now support a narrowly typed remove decision for a
  recorded version-2 manual-highlight deletion. Resolve the exact incarnation's
  creation from retained local/accepted native history; prove its workspace,
  entity, feature/key and parents. A tombstone/hash/title is not enough. Generic
  research/notes/AI deletions remain outside this action; KINDS is unchanged.
- Target comparison must match the effective native manual head, exact mapped
  active paper lifetime, projection marker and bounded visible row. The shared
  sealed Decision writes one new native deletion and its receipt atomically.
  Source remains unchanged; originals are neither inspected nor granted; receipt
  flags preserve that distinction. Existing successful retry preserves a later
  restored mark. UI request identity includes the current native target lifetime.
- Reuses the existing recovery selector/worker and Yes/No confirmation (No by
  default). The action is explicit, never preselected as automatic replay.
  Five new actual isolated outcomes cover independent peer delivery and another
  retained mark, later-restore-safe retry, receipt rollback and stale refusal,
  untracked/absent target plus wrong-note refusal, and real Qt No/Yes deduplication.
  These pass: 5 in 26.95s pytest / 30.5s total.
- Shared compatibility representatives: 9 passed in 28.48s / 31.8s total, including
  note replacement, exact parent proof, held apply across cancel/close/workspace/
  binding changes, confirmation selection/target changes, and Chinese manual copy.
  No historical/default selector growth or new worker/worktree/settings panel.
- First negative fixtures hit existing protections before the intended boundary:
  a duplicate anchor was correctly refused, then an ordinary SQLite connection
  lacked the native capture callback. Corrected to a distinct real selection and
  the existing CaptureConnection/suppress_capture fault-injection seam in fixtures
  only. Assertions were retained; production capture is never suppressed here.
  Lint-only corrections ran no tests. No repeated paid calls, account login,
  private research or cleanup. All checks use one CPU-bounded job at a time.
- README/recovery guide/scenarios/status/handoff/test map updated. Reuses existing
  native provenance, lifecycle and atomic-receipt patterns; no new global skill.
  Manual in-place restore/legacy mapping, other scientific deletion choices and
  hosted/installed/native-vault/physical-device gates remain open. No push, release,
  cloud deployment, owner-app restart or data migration.

- Final daily critical: 14 passed in 5.13s pytest / 8.4s total; privacy/Ruff
  green. No full historical/release run, redundant peer matrix or new selector.


## 2026-11-15: source-verified original-identity manual restore

- The existing restore choice now handles a selected native manual put only when
  its target is known retired. Prove the retained target creation/deletion,
  projection, integer identity/creation date and exact mapped paper lifetime.
  Restore the original portable key; active/duplicate/unproved content refuses.
  The target must already own an eligible exact original; this action does not
  grant file ownership or switch the primary reader. Legacy/source mapping stays
  outside this slice; the existing explicit original-source action remains separate.
- Reuses maintained byte/position/selected-text verification during preparation,
  off the GUI. The sealed Decision now optionally retains that immutable native
  file-version witness. The application receipt, native restore and outbox share
  one SQL transaction; file changes before/after writing, stale state, receipt
  failure and cancellation roll back. Successful retry uses its payload-bound
  application receipt before current-source eligibility and preserves later
  deletion/edits even if bytes disappear. The verified-original flag records
  verification at commit, not continued availability. No AI or new wire format.
- Existing recovery selector offers original-identity restore separately from
  its default independent copy. Dedicated Chinese/English confirmation defaults
  to No; target-lifetime request IDs prevent accidental repeat work. Unavailable
  originals keep comparison readable and show a bounded reason.
- Five new collected cases only. Real source/target/peer fidelity and retry,
  forged/file witness refusal, atomic/stale/post-write mutation rollback,
  active/duplicate/unavailable refusal, and real Chinese No/Yes/deduplication plus
  missing-original comparison. Shared restore/removal/receipt representatives:
  10 passed in 77.64s pytest / 81.2s total. After stronger fault/UI assertions,
  only those 2 affected cases reran: 2 passed in 19.17s / 22.3s total. Earlier
  four-case passes overlap; counts are not added. Privacy/Ruff green; sequential
  two-core/25%-CPU/300s-bounded checks, not a historical/release matrix.
- Fault injection initially patched a temporary read connection's client, so it
  never reached the real transaction. Source inspection confirmed each native
  CaptureConnection attaches a fresh client. Patched the maintained shared writer
  callback imported by those connections; the exact same rollback assertion now
  passes with an observed file mutation. No production bypass or relaxed test.
- README/recovery guide/scenarios/status/handoff/test map describe the API and
  limitations. Reused existing native proof/receipt patterns; no new global skill,
  setting panel, worktree or selector matrix. Hosted first-device identity/HTTPS/
  native vaults, installed Windows/Apple Silicon/phone acceptance, remaining
  scientific and legacy mapping work stay open. No cloud, push, release, owner
  app restart or private research migration.

- Final daily critical: 14 passed in 7.59s pytest / 11.2s total, privacy/Ruff
  green. No unchanged whole recovery/corpus/mobile matrix or historical run.

## 2026-11-15: one-platform native candidate delivery

- Extend the maintained Release workflow with manual `platform=macos` or default
  `all`. Tag events retain all three platforms. Both paths retain critical source
  acceptance, frozen research verification, provenance and the 30-minute job cap.
- Mac refuses a non-arm64 runner. Upload only the generated synthetic
  `original.zip` separately; account/workspace folders are not artifacts.
- Extend the existing update asset contract rather than adding test selectors.
  Affected update/Mac packaging checks: 28 passed in 1.10s pytest / 4.3s total;
  privacy/Ruff green under the two-core/25%-CPU/300s governor.
- No claim of native success from these Windows fixture checks. Live CI run,
  actual frozen report and installed Apple Silicon acceptance remain gates.
- Required daily critical: 14 passed in 6.99s pytest / 10.1s total; privacy,
  Ruff and whitespace check passed. No exhaustive or release matrix repeated.

- Actual GitHub run 43633002571 built the clean arm64 candidate f86a214.
  Native source critical passed; frozen first-use/import/duplicate-import passed,
  then reader exited -11 under QT offscreen. No installer was uploaded.
  Report/logs preserved in ignored build/mac-candidate-43633002571.
  Next experiment: native Cocoa for isolated Mac GUI checks, retaining every
  data/reader/source/fidelity/foreground assertion and Linux Xvfb behavior.
- Cocoa selection/privacy and verifier orchestration: 12 passed in 1.08s /
  4.2s total. Daily critical: 14 passed in 7.34s / 10.6s total. Privacy/Ruff
  and whitespace passed. Native result remains pending the next CI run.
- Run 43633506467 (d6d05f2) also failed at reader with -11 under Cocoa;
  backend selection alone is ruled out. Do not claim a native fix. Existing
  faulthandler writes to the synthetic recipient workspace, outside the previous
  artifact glob. Include only that fixed app-fault.log in raw fixture evidence,
  retaining every verifier step and withholding failed installers.
- Diagnostic artifact contract: 1 passed / 19.8s total; critical 14 passed /
  13.5s total, privacy/Ruff green under the same bounded single-job runner.

- Run 43634104252 succeeded on clean 3b3b550, macOS arm64, 0.5.0.dev:
  2026-11-14T19:48:48Z to 19:53:07Z (4m19s). Source critical and all frozen
  stages passed: reader, duplicate import, exact four-PDF export, three-original/
  five-quotation audit, CLI/MCP retries and native Launch Services foreground/close.
  Synthetic app-fault.log is empty. DMG artifact 14129980205; fixture 14129267960.
- Two preceding -11 reader crashes remain unexplained. This passing run changes
  the evidence to intermittent, not fixed. Do not promote Cocoa as a proven crash
  remedy or release a stable update from one pass. Existing diagnostics/harvest
  patterns cover the boundary; no new global skill is justified. Installed Mac
  input/upgrade/corpus UI, Windows/phone and private HTTPS/device gates stay open.
- GitHub build-macos archive: 278993197 bytes, archive SHA-256
  8f6f79dee001c5e78955e3cee8be70f46d12589d3f882732875adfc419bdcd1a.
  This is GitHub artifact metadata, not a locally verified DMG digest. Local
  transfer remained incomplete and was stopped to bound this delivery cycle;
  no app/test process or remote artifact was stopped/deleted. Use the run artifacts.
- Evidence-only docs gate: 58 passed in 2.09s / 5.1s total, privacy/Ruff and
  whitespace passed. Reused unchanged critical/native evidence; no new test
  selectors, worktrees, deployment or stable release.

## 2026-11-15: isolate intermittent native reader failure

- Previous turn made progress: native candidate artifacts and actual acceptance
  evidence exist, but two reader -11 failures remain unresolved.
- Require three sequential launches of the same Mac bundle and synthetic
  recipient. Stop on first failure (never retry-until-green); each completed
  reader stage remains in the report, final success records launch count.
  Other OS checks stay unchanged. Extend existing orchestration regression
  with second-launch failure, preserved fault evidence and no downstream export.
- Existing verifier cases: 12 passed in 1.30s / 4.3s total. Daily critical:
  14 passed in 7.97s / 11.1s total. Privacy/Ruff/whitespace passed under the
  two-core/25%-CPU/300s budget; no new selectors or exhaustive run.
- Run 43635055205 reproduced reader -11 on the second launch, after one
  successful reader stage. Captured Python native-fault stack: Qt app.exec,
  no active Python PDF worker. It does not prove a MuPDF crash.
- Source review found an application-wide _FileOpens filter still installed
  in main.run, despite window_events.py documenting the same PySide/WebEngine
  receiver-wrapping crash class. Move FileOpen handling to QApplication.event,
  whose receiver is only the application. Keep the existing PDF dispatcher and
  do not intercept unrelated native objects. Verify actual fresh-Qt file events,
  non-PDF fallback, early/closed handler and unchanged open-with behavior.
  Root-cause attribution remains provisional until native verification.
- Actual fresh-Qt application events and existing PDF open-with: 2 passed in
  3.71s / 7.3s total. Critical 14 passed in 7.24s / 10.4s total; privacy/Ruff/
  whitespace green. No direct app/application.installEventFilter calls remain
  in source. Native three-launch acceptance still pending; not a proof of
  installed stability or a full Qt/PDF threading audit.
- Actual native run 43635889503: clean e753ad3fdbcc8f6d947eaf43e2a239ce6a793acc,
  macOS arm64, 0.5.0.dev. Critical 14 passed in 4.55s. Job 20:08:39Z-20:13:46Z
  (5m07s), 2026-11-14 UTC. Frozen report passed with exactly three reader
  stages, reader_launches_verified=3, four PDFs preserved, three-original/
  five-quote audit, 38 MCP tools and retry/restart, native foreground/close.
- Native report downloaded and independently matched to actual job JSON output
  in ignored build/mac-candidate-43635889503. Build artifact 14130193207,
  fixture 14130168089, provenance 14129774220. GitHub build ZIP metadata:
  279311695 bytes, sha256 76ec969799efcbea465c8b20b7ee85260d057767a09ced074232ac7a0f27ad99.
  This is the artifact archive digest, not a locally checked DMG digest.
- Goal/harvest checkpoint: verified removal of a documented global-filter
  hazard with preserved actual OS file events; three native launches now pass.
  Keep the lesson in project event-boundary/acceptance evidence. No new global
  skill or universal claim about native crashes, thread safety or stability.
  Physical Mac input/upgrade/long-running/corpus UI, Windows/phone and hosted
  private HTTPS/device-identity gates remain explicitly unaccepted.
- Evidence-only documentation validation: 58 passed in 4.81s / 13.7s total;
  privacy/Ruff/whitespace passed. Reused unchanged native/critical evidence.
  No new selector count, broad historical run, deployment or stable release.

## 2026-11-15: confirmed native note retirement after authority recovery

- Prior turn made progress: global file-open filter removed and actual Mac
  three-launch/native acceptance passed. No new installer needed for this scoped
  checkpoint; delivered candidate e753ad3 does not include the following work.
- Existing choices.prepare(..., "remove", ...) now accepts recorded v2 note
  deletions with retained native creation proof, active exact-parent target head,
  integer identity/creation clock, bounded visible payload and rich projection.
  Plain and positioned notes use the actual native writer; no source ownership
  grant, PDF inspection/activation or AI. Existing mark removal stays separate.
- Reuse one transaction for native deletion, outbox and application receipt;
  failed/cancelled writes roll back. Same-request retries preserve later native
  restore/edit, even after deletion reaches an independent native peer. UI uses
  note-specific en/zh text, default-No confirmation and current-target-lifetime
  request IDs through the existing worker/controller.
- Five new collected cases only. With the unchanged arbitrary-note refusal
  representative, 6 passed in 36.85s pytest / 40.0s total. Final projection guard
  and existing manual-removal/note-replace representatives: 3 passed in 21.33s /
  24.5s total (one overlapping case). Privacy/Ruff green under two-core/25%-CPU/
  300s limits. Daily critical stays 14; release stays 35 selectors.
- First fixture run compared an unrelated legacy two-field note creation clock
  that its wire payload never carries. Corrected that new fixture to the full
  native timestamp-carrying note payload; retained exact peer-row equality and
  both plain/positioned deletion cases. Not a global legacy-clock migration fix.
- Reused typed-history/native-receipt patterns; no new global skill. Other
  scientific/parent deletion, legacy mapping and installed/hosted acceptance
  stay open. No historical matrix, real accounts, owner data or native rebuild.
- Critical: 14 passed in 8.21s / 11.5s total; privacy/Ruff/whitespace green.
  Final review caught terminal encoding replacing new Chinese labels with
  question marks. Replaced them with ASCII Unicode escapes and strengthened
  the UI test to assert the actual Chinese label/wording, not internal text
  aliases only: 1 passed in 5.62s / 8.9s total. Existing critical/source-control
  evidence reused after this text-only correction; no unchanged whole rerun.
- Final docs gate: 58 passed in 1.87s / 5.1s total, privacy/Ruff/whitespace
  passed. Checkpoint is locally verified only; source/native e753ad3 acceptance
  remains scoped to its exact artifact and does not cover this new note action.

## 2026-11-15: source-authored compound-intake note timestamps

- Previous turn made progress: confirmed note retirement committed/integrated.
  This turn reviewed writer scope, then reproduced a concrete divergence in
  ResearchOperations intake: two-field notes omit source creation time.
  Fixed-clock native empty-peer test failed before the change (3.54s pytest /
  6.6s total): expected source 2026-01-02, observed current receiver/writer time.
- Emit the existing six-field native note payload with the one source clock
  already captured by intake. Both create_list/add_papers keep their text input,
  bounds, request fingerprint, result shape, stable IDs and operation count.
  No new wire type, implicit legacy migration or public CLI/MCP redirection.
- Strengthen existing tests, no new collected cases/selectors: actual source/peer
  metadata equality under different clocks; restart/retry preserves note edits
  and original times; partial writer/receipt failures also roll back rich-note
  projections. Initial four affected cases: 4 passed in 9.33s / 12.3s total,
  privacy/Ruff green under the two-core/25%-CPU/300s governor.
- Source audit inventory is explicitly historical; link current implementation
  contracts rather than treating the October baseline as current missing work.
  Still no arbitrary existing-workspace adoption or claim of complete writer
  enrollment. Installed/hosted/mobile gates and remaining recovery/audit scope
  stay open; no native build, owner-data access or paid/provider activity.
- Final add-papers timestamp case plus unchanged concurrent-retry/paged-HTTP
  representatives: 3 passed in 7.62s / 10.7s total, privacy/Ruff green under
  the same single-job resource governor. No new collected cases or selectors.
- Daily critical: 14 passed in 7.25s / 10.4s total, privacy/Ruff/whitespace
  passed. Reused existing source-clock/payload-bound-receipt pattern, recorded
  in project evidence; no new global skill or publication/hosting claim.

## 2026-11-15: current-source three-platform candidate acceptance

- Previous turn made progress: new graph-intake notes preserve source clocks,
  native peer/retry/rollback checks passed and source was integrated/pushed.
- Next gate is actual native Windows/Mac/Linux packaging of current source,
  not another historical test run. Review found Linux QT_QPA_PLATFORM=xcb
  while the critical source step omitted the existing DISPLAY_WRAPPER used
  by screenshots/build/frozen checks. Reuse that wrapper for source checks;
  keep all assertions, profiles and the 30-minute per-job budget unchanged.
- Extend the existing workflow asset contract, no new cases/selectors. This
  static contract does not prove Linux execution; live CI reports remain needed.
- Workflow contract: 1 passed in 0.35s / 3.4s total. Critical: 14 passed in
  7.71s / 11.0s total. Privacy/Ruff/whitespace green, bounded single local job.
  Initial assertion line-length failure corrected without changing assertions.
- Native run 43638983559 Linux job 132582023201 passed critical checks but
  failed screenshot startup: desktop/fonts.py keyBindings(FullScreen)[0] raised
  IndexError because the theme supplied no binding. Windows/Mac jobs retained.
- Existing label test reproduced the exact IndexError before the fix (0.53s
  pytest / 3.7s total). Resolve actual shortcuts and labels through one helper: native
  binding wins; fullscreen alone falls back to F11; other unavailable bindings
  produce an empty sequence. Wire FocusMode through the same helper so F11
  actually acts, not just appears in a tooltip. No new cases/selectors.
- Actual fallback key, label and unchanged focus/ruler/layout behavior: 4 passed
  in 2.90s / 6.3s total, privacy/Ruff green under bounded local resources.
  No new cases or selectors. First run Mac native job passed; Windows build
  still live. Do not relaunch overlapping builds or claim Linux packaged success.
- Startup fix critical: 14 passed in 7.61s / 10.8s total, privacy/Ruff and
  whitespace green. First run 43638983559 is terminal: Windows and Mac native
  build/frozen acceptance succeeded for 7f62f5d; Linux failed before packaging.
  Next run uses the fixed common source; no earlier job is left live/overlapped.
- Second native run 43639589003: desktop frozen reports for clean 00151ba
  all passed (Linux 2m37s, Mac 4m24s, Windows 6m24s). Exact JSON saved under
  ignored build/candidate-43639589003. Linux includes AppImage CLI/MCP; Mac
  includes three reader launches and Launch Services foreground/close.
- Full Windows log review contradicted the green job for mobile assets: source
  critical 14 passed, but mobile artifact tests reported 0 pass/5 fail, hidden
  by later successful native commands in a PowerShell multiline step. Do not
  call this complete cross-platform/PWA acceptance or release it on that basis.
- All five failures were strict fixture cleanup path checks against Windows
  DOS short TEMP aliases. Allocate under realpath(tmpdir()) first, retaining
  exact root/parent/device/inode assertions and exact-owned-path removal.
  No broad TEMP cleanup, path relaxation or production artifact rule changes.
- Asset preparation and mobile test/build/verify use Bash fail-fast, matching
  the existing frozen step. Existing workflow contract pins both shells.
  This is validation repair, not proof that the mobile artifact already passes.
- Local mobile artifact regressions now pass 5/5; workflow contract passes 1
  (0.34s Python, 3.63s Node, 7.2s total with privacy/Ruff). Original cleanup
  assertions retained. Actual Windows Git Bash injection: native node exit 7
  propagates, later marker command does not execute (10s-bounded check).
- Repair critical: 14 passed in 8.92s / 12.5s total; privacy/Ruff/whitespace
  green. Refresh the existing readiness/roadmap: curated gates and actual
  native/platform evidence replace stale October baseline language. Physical
  upgrade/phone/hosted gates remain open; .dev candidates do not auto-update.
- Documentation gate: 58 passed in 1.92s / 5.1s total, privacy/Ruff and
  whitespace green. No new test cases/selectors or owner database/account use.
- Final run 43640792668, clean 4594626421a925c8c8e2fec1ba8d89239fea9ee8,
  0.5.0.dev: actual Windows/Linux/Mac frozen JSON all passed. Windows critical
  14 in 5.36s; Linux 14 in 2.72s; Mac 14 in 3.23s (5 warnings). Not 42 unique
  journeys. Windows Node explicitly tests=5/pass=5/fail=0, after the fail-fast
  repair; no accepting a green shell/job without reading its earlier outcomes.
- UTC 2026-11-14 native jobs: Windows 21:04:00-21:09:38 (5m38s), Mac
  21:04:00-21:07:46 (3m46s), Linux 21:03:58-21:05:58 (2m00s). Each preserves
  four PDFs and audits three originals/five quotations; 38 MCP tools plus
  restart/retry. Mac: three reader launches and native foreground/close. Linux:
  actual AppImage CLI/MCP retry/restart. Reports/index retained under ignored
  build/candidate-43640792668; no large installer download/recheck ritual.
- Artifacts: build-windows 14131664054 (184190567 bytes), build-macos
  14131758096 (278933034), build-linux 14131847288 (282127022); fixture-macos
  14131892595; mobile-web 14131782507. GitHub artifact ZIP SHA-256 respectively:
  6ab20aff758247909e95f899d24cdd09bffd0d1ec2b95f08b9cad44f916611b6,
  deaffa77f2fe07df4b72a620b097a273f7f9b0712cdd51a4c82df4f66a46253d,
  3221f6f7dcb4610dcfe907715e880ad857f8b755daac6f065822cefdf44ab308.
  These are archive metadata digests, not locally verified installer payload hashes.
- Verified checkpoint/harvest: actual native stages, exact test counts and
  artifact identities beat aggregate green status. Keep the shell/Windows-path
  evidence and limits in existing project docs; no new global skill or hooks.
  Curated release selection, installed upgrade/real-provider/physical-device/
  private-hosted gates remain open. No tag, release, cloud cost or owner-data use.
- Final evidence-only documentation gate: 58 passed in 1.87s / 5.6s total;
  privacy/Ruff/whitespace green. Reuse exact native/critical evidence for
  candidate 4594626; no further native rebuild after documentation-only edits.


### 2026-11-15: isolated Windows installer acceptance (native run pending)

- Remote master fetched and inspected: 1b44466a2aaf5a3ea17a3eba16f27777f0507a36
  is already an ancestor of integration checkpoint dbea334; left/right count
  151/0. No maintenance-line merge or ancestry-only test rerun was needed.
- Existing frozen verifier now accepts an optional exact Windows setup artifact
  only in matching clean repository CI, with a fresh owned destination. No local
  installer was executed and no native workflow was dispatched in this turn.
- Install and same-version reinstall use acceptance mode, explicit destination,
  no restart/close/reboot, fixed per-stage logs, source identity and payload hash.
  Installed version, reader and CLI/MCP are checked before reinstall/uninstall;
  bounded generated research files must remain byte-identical at every action.
  Refused/stale paths, wrong version, data mutation and incomplete uninstall stop
  with the exact active stage and retain failed evidence. No broad cleanup.
- Focused bounded command: scripts/check_bounded.py --profile focused --python
  tests/test_windows_installer_acceptance.py tests/test_built_app_verification.py
  tests/test_updates.py::test_the_build_names_match_what_the_release_workflow_uploads.
  Result: 18 passed in 2.09s; 5.7s total including privacy/Ruff. First attempt
  stopped on two Ruff findings before pytest (16.8s); fixed, no assertions weakened.
  Five new collected cases cover the distinct installer contract; critical remains
  14 and curated release remains 35 selectors. No historical suite expansion.
- New installer phase is simulated locally, not native acceptance. Previous
  three-platform candidate 4594626/run 43640792668 remains the delivered package.
  Real Windows CI execution, old-release upgrade, registry/shortcut integration,
  Mac installed upgrade, hosted sync and phone/device acceptance remain open.
- Checkpoint review: owned destinations, categorical reports and synthetic data
  reuse the existing support/acceptance pattern. No new global skill, hook or
  background service is warranted from this single unexecuted native phase.

- Default bounded critical: 14 passed in 6.32s / 9.6s total, privacy/Ruff green.
- Documentation gate: 58 passed in 1.94s / 5.0s total; whitespace check clean.


### 2026-11-15: native installer diagnostic follow-up

- Candidate 84ec689, run 43644279988: Linux and Mac completed successfully;
  Windows critical 14 and mobile artifact 5/5 passed, frozen import/reader/
  export/audit/CLI/MCP passed, then windows-install failed permission_denied.
  The report does not locate the denied operation. No installer conclusion or
  permission/environment attribution is justified yet. Reports/logs retained in
  ignored build/candidate-43644279988; the prior common candidate stays available.
- Added bounded private failure-detail.log separately from categorical report;
  existing failure tests check traceback presence/bounds while sensitive values
  remain excluded from report.json. No new collected cases.
- Existing Release workflow now supports a Windows-only manual candidate for
  platform-specific diagnosis; all remains default and tags still build all OSes.
  Existing matrix assertions retain every original platform and add this choice.
- Focused 18 passed in 2.10s / 5.3s total; critical 14 in 5.03s / 8.4s total.
  No assertion was weakened, local installer executed, user data changed, public
  release created or production sync deployed. Next collect the exact denied path
  through one Windows-only candidate before choosing a fix.

- Enrollment documentation reconciled against current source: queue/reading logs,
  paper-scoped queue pins and desktop preview/prepare/open are implemented, not
  blanket pending work. Unknown files/schema and complete installed/hosted adoption
  remain gates. Representative unchanged fixtures: 3 passed in 10.58s / 13.7s total
  (lossless legacy copy plus two restore/adopt cycles; actual desktop PDF candidate
  preview/prepare/open; no-side-effect queue-pin coverage). No new test cases.

- Windows-only diagnostic run 43644980935 (e5e0ece) reached windows-install and
  failed before subprocess execution: ready -> _data_hash -> _file_hash ->
  stream.read -> PermissionError. The former snapshot included HOME/browser
  caches alongside research; the exception lacks the filename, so no exact cache
  path is claimed. The research-preservation boundary is now the exact generated
  PAPERFACT_DATA workspace, excluding non-research HOME caches. Existing success
  coverage injects an unreadable HOME cache while retaining whole-fixture final
  equality; mutation inside research still fails the existing case. No exception
  is ignored inside the protected research tree.
- Snapshot-boundary fix: focused 18 passed in 1.66s / 4.7s total; critical 14
  passed in 7.46s / 10.7s total. Documentation gate before this fix: 58 passed
  in 2.28s / 5.4s total; only the protected-tree wording changed afterward.

- Native follow-up 43645524973 (19baf71) still fails before setup execution in
  research _file_hash stream.read. The HOME-only hypothesis did not fix it; no
  specific file or lock owner is established. Do not ignore inaccessible research
  files. Added a private exception note identifying the exact bounded path for
  the next native run, including a simulated filename-less PermissionError.
  This is diagnostic instrumentation, not a claimed installer fix. Stop candidate
  rebuilds in this turn; preserve the failure and resume the specific check next.
- Final diagnostic instrumentation: focused 17 passed in 1.55s / 5.2s total;
  critical 14 passed in 4.87s / 8.1s total, privacy/Ruff green. Existing test
  assertions retained; no additional collected cases. Working native gates remain
  explicitly open; source-qualified prior Mac/Linux evidence is not a common
  three-platform pass for the current diagnostic commit.


### 2026-11-15: reproduce and drain the native fixture producer

- Avoided a diagnostic rebuild: source fixture reproduction under the existing
  Windows governor identified .research-jobs/<sha256>.lock as the denied path
  after reader exit, but not after import. Exact source lock key matches feature
  resources and owner demo:paperfact. The helper is an intentional detached Popen
  from ReaderPage._check_resources; no cache attribution or handle leak is claimed.
- In a second bounded reproduction, the maintained idle_lock_files validator
  observed the producer finish after 4.89s, then complete research fingerprint,
  export, exact-source audit and actual CLI/MCP restart/retry passed. Total 20.563s.
  This is partial source diagnostic evidence, not frozen package acceptance:
  source doctor had already reported missing formula assets in this worktree.
  No assets were downloaded, no account login/model call or owner data was used.
- Added typed ActiveResearchWork (still a ValueError for existing callers) and
  installer-only bounded polling of that type before each research snapshot.
  Unknown/malformed locks and all other errors fail immediately; 30-second drain
  timeout fails; native destination identity is rechecked after waiting. Every
  research file, including closed mutex files, remains in the final byte hash.
  No deletion, lock skipping, repeated producer execution or process killing.
- Focused: 27 passed in 13.32s / 16.6s total, covering existing active/unknown-lock
  enrollment guards, complete frozen verifier and install simulations. One new
  collected case tests drain success, timeout and unknown-error refusal with a
  synthetic clock; daily critical and curated release selectors unchanged.
- Production drain helper replay: 19.453s total; post-reader wait 4.83s, then
  complete research reads/export/audit/CLI/MCP passed in the partial source
  diagnostic. Critical 14 passed in 5.26s / 11.2s total; docs 58 passed in 1.80s /
  5.4s total. First affected check stopped on one Ruff line-length finding
  before pytest (4.9s); fixed without changing assertions.

- Native Windows verification now passed: source
  7704504a64fe413cfa4b9ede5a4360d596448dde, clean 0.5.0.dev,
  run 43647271358 / job 132607754373, 22:17:12-22:23:43 UTC (6m31s).
  Actual report: installed/reinstalled/uninstalled/research_preserved all true;
  installed reader and installed CLI/MCP 38-tool retry/restart passed. Frozen
  roundtrip preserved 4 PDFs, exact original/quote audit passed. Critical 14 in
  4.60s; actual mobile artifact 5 tests/5 pass/0 fail. Not only aggregate job green.
- Setup payload SHA-256 (computed inside the native verifier):
  3c99fb85c35780fa3ce40274f1402e231bbbee5e759bd04942aa793c10687d06.
  build-windows artifact 14134856199, 184107709 bytes; GitHub archive digest:
  1e683f333243777f64b866e6069e45667de11f012319ec5d03eeb7b59000e351.
  Report/index retained under ignored build/candidate-43647271358. No large
  installer download, local execution or public release was required.
- Mac/Linux source 84ec689 reports in run 43644279988 remain separate qualified
  evidence, not native acceptance of current Windows source 7704504. Common
  three-platform delivered candidate remains 4594626. Old-release upgrade,
  registry/shortcuts, real-provider, hosted sync, actual Mac/phone and complete
  curated-release gates remain open. No owner research or production resources.
- Verified checkpoint review: reproduce a failing native fixture locally before
  another packaging cycle; wait for known producer quiescence rather than skip a
  locked research file. Reuse existing typed idle-lock validation and retain
  failure artifacts. This is project evidence, not a new global skill/hook/rule.
- Final evidence-only documentation check: 58 passed in 1.87s / 4.9s total,
  privacy/Ruff/whitespace green. Reuse native and critical evidence for unchanged
  source 7704504; no packaging rebuild for these documentation updates.


### 2026-11-15: confirmed claim-analysis retirement

- Added explicit typed removal for a recorded v2 claims/main deletion through
  existing choices/decision/native transaction. Require exact retained creation,
  mapped paper lifetime, current native head/projection and bounded visible row.
  Preserve deep/section analyses, PDFs, notes, original ownership and history;
  no model, file-access grant, envelope replay or implicit source restoration.
- Initial behavior test exposed that claims use deterministic v2 entity identity,
  not Lineage-only content_address; replaced that assumption with the fixed slot
  plus retained creation proof. First behavior attempt: one failed in 6.57s;
  corrected without weakening expectations. Formatting/callback binding findings
  were fixed before tests, not interpreted as feature failures.
- Backend 3 passed in 19.45s / 22.7s total: actual independent native peer after
  transfer; later restore/retry; receipt failure/cancel rollback; stale target and
  untracked visible content. Actual claim-specific zh-TW confirmation plus prior
  note confirmation: 2 passed in 9.02s / 12.5s total (one overlapping existing case).
  Four new collected cases; no blanket stress matrix, critical/release selectors
  unchanged. Whole suites and installed/hosted/physical-device checks not run.
- Compatibility selection: 3 passed in 14.46s / 18.3s total (arbitrary-note
  removal refusal, active/duplicate/unavailable manual restore refusal, keep-only
  decision). One initial selector name did not exist, so that attempt ran zero
  tests; corrected to the actual named case, no test removed or skipped.
- Critical 14 passed in 4.69s / 7.9s total; docs 58 passed in 1.91s / 5.0s total;
  privacy/Ruff/whitespace green. Checkpoint review reuses the existing confirmed
  note/manual/Lineage decision pattern; no new universal skill or duplicate
  protocol is warranted. No native package rebuild or release in this turn.


### 2026-11-15: verify retained history before outbound work

- Current journey audit found desktop and mobile sync pushed before pulling.
  The service already rejected a future cursor, but only after outgoing work could
  be admitted. New regression demonstrated missing history did not raise before
  the fix (one failed in 0.67s / 3.8s total). No old expectation was weakened.
- Nonzero-cursor clients now request exactly the retained frontier event and
  compare complete canonical event data before prepare_push/file bytes/outbox
  upload/acknowledgment. Local inbox reads are bounded and closed before network;
  initial cursor-zero bootstrap is unchanged. No source-generation fallback,
  cursor reset, outbox deletion, envelope replay or hidden operation retry.
- Reference service pull exposes typed SyncHistoryUnavailable/HTTP 412 after
  authentication, with a closed non-content error. Python and mobile transport
  distinguish it from auth/attachment errors. Desktop automatic sync pauses with
  en/zh preservation guidance; PWA shows equivalent guidance and v24 refreshes
  only static code, preserving research caches/IndexedDB.
- Python: 5 passed in 2.85s / 5.9s total (missing/different/matching frontier,
  authenticated HTTP error, automatic pause/no retry/private error isolation).
  Mobile: 22 passed / 0 failed in 3.5s governed time across history/engine/
  transport/static-shell tests. One new JS case exercises all three history states.
- Existing desktop manual/retry/offline-concurrent-note compatibility: 3 passed
  in 4.24s / 7.2s total. Actual JavaScript -> Python HTTP service integration
  passed in 1.953s, including rich analysis, offline note chain, retries, PDF,
  conflict/edit-delete and editable-deck offline closure. CPU capped, sequential.
- A frontier comparison is not proof of every historical event or protection
  against authority reset during the pass. Complete generation negotiation,
  installed Windows/Mac and hosted/phone acceptance remain open. No cloud action,
  login/model call, real-user data, release or native package rebuild performed.
- Consolidated mobile history regression into existing engine.test.mjs so the
  established release mobile selection includes it. Added one release Python
  selector for the three short frontier scenarios (36 selectors, not cases);
  daily critical remains 14. This pins an observed data-safety requirement, not
  a new stress matrix. PWA artifact built/verified locally: 50 files, 3912422 bytes,
  eeb27a957d584bf2f703aedca8f82cb73dded54d71ae731966a4afe218eabeed.
- Final source critical: 14 passed in 8.72s / 12.2s total. After consolidating
  the JS case, mobile selection remains 22 passed/0 failed in 3.188s; docs 58
  passed in 2.19s / 5.5s total. Privacy/Ruff/whitespace green; actual flattened
  map confirms critical 14 selectors and release 36 selectors. No full-release
  or historical suite run. Existing SW assertions were retained while updating
  the intentional cache version to v24 and adding v23 retirement coverage.
- Checkpoint review: validate retained history before publishing new work, use
  categorical recovery guidance, and never repair a missing prefix by discarding
  local state. Keep this verified project evidence; no new global rule/skill,
  background service, credentials, cloud resources or extra worktree introduced.


### 2026-11-15: first enrollment of actual CLI/MCP-created research

- Real imports.propose/commit regression reproduced unsupported writer scopes for
  integration_changes/operations/previews (1 failed in 1.95s / 4.9s total).
  Added closed known-import archive adapters through existing private history;
  retain exact original records, never install live previews/retry authority or
  follow reference URLs. Unknown generic receipt schemas still block.
- Initial copy exposed non-lossless list_papers: the import producer began at 1,
  native order projects dense positions from 0. Future imports now match the
  ordinary zero-based list writer. Explicit source membership comparison retains
  all other fields and complete order while normalizing distinct nonnegative
  ordinals; ambiguous ties/invalid values block before preparation. Source stays
  unchanged. Queue ranks and prose are not normalized.
- Shared PaperInput moved unchanged to a pure schema module; public ops.PaperInput
  alias retained. Archive validation no longer imports the workspace/provider
  operation runtime. Existing untrusted-field tests and alias identity pass.
- Four new cases: exact archived records in candidate and detached recovery_records,
  research/PDF/list-order preservation and inactive old requests; unknown/malformed
  records and ordering refusal; cancel/changed-source retry; actual desktop preview,
  archive-only counts, repeated activation and unchanged source workspace.
  4 passed in 18.36s / 21.6s total. New test initially expected detached private
  history in the active table; corrected to the existing recovery_records contract
  and also assert all live import tables remain empty. No production restore rule
  or existing assertion weakened.
- Additional boundary/compatibility gate: 5 passed in 5.22s / 8.3s total (includes
  one new case again); shared input/archive boundary gate 10 passed in 4.42s /
  7.7s total (overlapping new case plus nine unchanged input cases). Counts overlap.
  Pure validators reject embedded URL credentials without echoing them.
- One representative added to curated release (37 selectors); critical remains 14.
  No native package build, cloud action, login/model call or real-user data use.
  Arbitrary receipt formats, full in-place adoption, hosting/issuance and actual
  Windows/Mac/phone journeys remain separate gates.
- Final post-extraction enrollment representative: 1 passed in 5.34s / 11.7s
  total; critical 14 passed in 7.62s / 11.2s total; docs 58 passed in 2.11s /
  5.2s total. Privacy/Ruff/whitespace green. Skill copies synchronized through
  scripts/sync_skills.py --write without conflicts; no global installation.
  Initial Ruff findings stopped before pytest and were fixed without weakening
  behavior assertions. Release map now has 37 selectors, not a collected count.


## 2026-11-15: common native candidate b4ec451

- Previous continuation was a verified wait: run 43652950917 was confirmed live.
  Observed that same run to completion; no duplicate dispatch or local broad test.
- [Run 43652950917](https://github.com/puddings-world/Paperfact/actions/runs/43652950917)
  built clean `b4ec451505c6117837969600469962d89dac9d8b`, `0.5.0.dev` on all three
  desktop platforms. Windows 6m19s, Mac arm64 4m33s, Linux x86-64 2m00s.
  The tag-only draft job was skipped as designed; no release or deployment.
- Inspected actual packaged-acceptance.v1 JSON, not just green job conclusions.
  Each reports passed, clean source identity, four preserved research files,
  import/repeated import, reader, export, original audit, credential isolation
  and CLI/MCP (38 tools, retry and restart recovery).
- Critical: Windows 14 passed in 3.85s; Mac 14 passed with five warnings in
  4.96s; Linux 14 passed in 2.00s. These are the same 14 journeys on each OS,
  not 42 distinct requirements. Privacy/Ruff passed. Windows actual mobile
  artifact TAP: tests 5, pass 5, fail 0. Historical exhaustive and curated
  release selections were not run for this manual candidate.
- Windows exact installer acceptance: installed/reinstalled/uninstalled and
  research_preserved all true; installed reader/CLI/MCP passed. Setup payload
  SHA-256 `63a5ea17c004618f6e4e5e7f94dd3702891e0dff27e4195adb7db28b819f67eb`.
  Acceptance mode is isolated; older-release upgrade and registry/shortcuts not
  checked. Mac three consecutive reader launches and Launch Services foreground
  passed. Linux AppImage CLI/MCP/retry/restart passed.
- GitHub artifact archive identities (not contained payload hashes):
  Windows 14137201591, SHA-256 `fd90aa1c3c5843be2bd6feb874adca13e638912b4d5c3ff4eb6f97dbc3bbbf65`;
  Mac 14137420312, `55c77273fa5670a5bf6a202617e9af137509ab94b73f6f9a93d178eac2ab1481`;
  Linux 14136339737, `7f907f17670df327998bffda0b4f549141206209b10c7a9346baf1fa04f4d954`.
  Mac synthetic fixture 14136663999; mobile static artifact 14136916281.
  Exact reports/index retained in ignored `build/candidate-43652950917/`.
- Updated existing status/readiness/board/Mac acceptance entry only. Candidate
  source is still b4ec451; this documentation checkpoint does not require another
  native build. No new reusable pattern beyond existing support/evidence rules;
  no skill copy or global rule change.
- Physical M01-M21, real provider login, complete writer/recovery mapping,
  authority generation/rollback protocol, live HTTPS issuance, hosted backup
  recovery and physical-phone durability remain open. Native packaging does not
  prove them. Deployment inputs remain unconfirmed; no cloud resources created.
- Documentation checkpoint: bounded docs 58 passed in 1.87s / 5.0s total;
  default critical 14 passed in 8.06s / 11.3s total. Privacy/Ruff and
  CRLF-aware whitespace checks passed. No exhaustive rerun or native rebuild.


## 2026-11-15: check acknowledged history before outbound work

- Previous turn made progress: common candidate artifacts verified, existing Mac
  acceptance/readiness/status updated, checkpoint 48e3a98 integrated and pushed.
- Found a remaining received-only history gap: successful push followed by failed
  pull retains server_revision even at cursor zero. A following pass could send
  new work without checking that known remote history. Actual regression failed
  before the implementation (`DID NOT RAISE SyncHistoryUnavailable`). An initial
  fixture edit did not apply because of mixed line endings; inspected source and
  corrected the fixture before accepting its failure as evidence.
- Desktop now probes received cursor and a newer highest acknowledgment, closing
  its read-only transaction before requests. Bounded saved operation comparison
  is explicit: older journals do not retain full acknowledgment outcome/head.
  Mobile checks both full retained observations, before outbox or position work.
  No cursor reset, discarded work, automatic replay or new transport/schema.
- Expanded the existing test selector to received / acknowledged-only / both,
  each with missing/different/matching service history. Eleven Python cases
  (including HTTP and desktop pause) passed in 3.67s / 9.1s total. Engine plus
  cache upgrade: 13 passed, zero failed/skipped, 0.515s governed execution.
  Earlier normal acknowledgment failed because validate_event returns canonical
  JSON, not a dict; corrected the implementation without loosening assertions.
- Static shell v25 replaces v24 while retaining research stores. Existing daily
  critical remains 14 and curated release remains 37 selectors. No exhaustive
  run, paid calls, owner research, native rebuild, publishing or deployment.
  Common installed-test packages remain b4ec451 and predate this refinement.
- Full authority-generation negotiation/reset-during-pass protection, hosted
  recovery, complete mapping and physical device gates remain open.
- Compatibility: three existing causal-parent/older-page/lost-response tests
  passed in 0.65s / 3.7s total. Actual JS-to-Python HTTP service journey passed
  in 1.828s. v25 local static build and verify passed: 50 files, 3,913,134 bytes,
  artifact ID `18c82faea1ac51f4d76179eb02f6808357b5e6a58127a2234ae107dfcc09aae2`.
  This is an ignored local artifact, not a hosted deployment.
- Docs 58 passed in 2.28s / 5.7s total; default critical 14 passed in 4.72s /
  8.1s total. Privacy/Ruff/CRLF-aware whitespace passed; skill copies synchronized
  without conflict. Existing mobile probe-order assertions remain exact, extended
  to the two-proof case rather than weakened to mere handler invocation.


## 2026-11-15: recorded deep/section reading retirement

- Previous turn made progress: acknowledged-history safety fix 0718d49 integrated
  and pushed, with source/mobile evidence and exact remaining gates recorded.
- Reproduced a missing typed action: a retained native dive deletion incorrectly
  fell through to manual-highlight validation and failed with no exact manual
  creation proof. New reading test failed before implementation in 9.17s.
  Initial formatting failures stopped before pytest and were fixed first.
- The existing claim-removal path is now a closed three-report adapter: claims,
  dive and close_reading, each only its deterministic paper/main slot. It still
  requires exact source creation, mapped paper lifetime, active current head,
  projection and bounded matching visible content. Removal uses one fresh native
  operation and one atomic receipt; no old operation replay or PDF/source grant.
- Existing desktop review offers a separate saved-reading label/notice and
  default-No confirmation. Original, notes, other report rows and source history
  remain unchanged. Claim inputs are not silently regenerated or rewritten when
  a deep/section reading is retired. A later restore survives old decision retry.
- Expanded three of four existing behavior requirements by typed report slot;
  shared receipt failure/cancel/stale logic runs once. Ten selected cases passed
  in 95.82s / 99.1s total, including actual Chinese Qt confirmation/repeated click,
  independent native peer and exact PDF/content preservation. No new test file
  or daily/release selector. Most time is isolated PDF/native fixture setup.
- Tightened bounded reads for reading body/spec/timestamp, then checked oversized
  untracked specs for both reading types plus successful dive peer delivery:
  three passed in 33.71s / 37.1s total (overlapping coverage, not extra unique
  requirements). No historical suite, concurrent check or owner data was used.
- Existing native-history/mapped-parent/atomic-receipt patterns already describe
  this extension; no new portable skill rule or copied skill update is needed.
  Common packaged candidate remains b4ec451, predating this extension and 0718d49.
  Complete legacy/source mapping, other scientific deletions, authority generation,
  hosted recovery and physical Windows/Mac/phone acceptance remain open.
- Final documentation gate: 58 passed in 1.81s / 5.1s total. Default critical:
  14 passed in 7.94s / 11.1s total. Privacy/Ruff and CRLF-aware whitespace passed.
  Source errors remain categorical; each visible-row test expects its own exact
  report label. These are scoped source/Qt-fixture results, not packaged evidence.


## 2026-11-15: isolate workspace-window routing across platforms

- Previous turn made progress: recorded deep/section retirement e2e484b integrated
  and pushed. Audited existing preparation/opening contracts rather than assuming
  prepared copies issue service credentials or establish runtime adoption.
- Source diagnosis: desktop SINGLE_INSTANCE_KEY unconditionally lowercased the
  data path. Distinct case-sensitive POSIX roots could collide; the focus handler
  raised the reader before checking its actual database and left later validation
  errors outside its rejection boundary. No claim of a reproduced physical Mac
  incident is made. Formatting/import findings stopped before pytest and were
  corrected without changing behavior expectations.
- Added the small existing-workspace `instance_key` seam: Windows retains its old
  normalized key; existing POSIX roots use device/inode identity. Missing roots
  use normalized paths without creating directories. Startup recomputes after
  ensure_dirs before handoff/listen, so first and later launches agree.
  Physical aliases share a window; distinct directories do not share a folded key.
- Focus frames can be bound to the receiving database; desktop validation and
  navigation run inside rejection handling before foreground activation. This
  changes no workspace path, research schema, sync credentials or saved draft.
- Three new platform-policy cases extend an existing test file. Focus/launch and
  actual restore/join Qt paths: 17 passed in 9.23s / 12.5s total, including exact
  framing, wrong database, credential exclusion, retries and draft preservation.
  Windows policy emulation is not native Mac/Linux case-sensitive-volume proof.
- Existing Mac/Linux processes must be closed before installing a newer candidate:
  old path-folded keys are not a compatible cross-version IPC protocol. Native
  package/physical upgrade acceptance remains open. Packages remain b4ec451;
  no rebuild, release, deployment, owner-data access or historical suite here.
- No new portable skill is promoted: workspace identity/delayed-delivery fences
  already describe the method, and native observations remain pending.
- Integration evidence: docs 58 passed in 1.86s / 5.0s total; default critical
  14 passed in 7.97s / 11.5s total. Privacy/Ruff and CRLF-aware whitespace passed.
  The 17-case affected check took 12.5s; no historical test count or percentage
  is used as a completion measure, and no parallel test was launched.


## 2026-11-15: require actual packaged same-workspace handoff

- Previous turn made progress: workspace-window isolation 2e8a229 integrated and
  pushed with short source/Qt evidence. Native behavior remained unproved.
- Existing frozen acceptance only started readers sequentially. Added one actual
  concurrent-launch stage to the same verifier and report: host Qt connects to
  the expected fixture root's endpoint; a second frozen invocation must return
  while its primary stays alive; primary must then exit normally. The second
  smoke limit is 60s versus a 15s process timeout, so a duplicate window cannot
  falsely pass via a short automatic close. Primary uses a 20s smoke close.
- Only the isolated synthetic recipient and verifier-owned process are used.
  Primary/secondary logs are private, abnormal exits/tracebacks/timeouts fail,
  no retry masks a failure, and failure cleanup terminates only its owned child.
  No old app, daily data, provider login or cloud service is touched.
- Expanded existing orchestration tests with live-primary success, absent endpoint,
  secondary error/timeout and primary loss. The fake-child suite passed 17 in
  1.56s / 4.7s total before final assertion-only/report documentation updates;
  this is not native acceptance evidence. Existing frozen checks are retained.
- The old common b4ec451 packages do not contain this check or later source fixes.
  A new coherent native build is planned after local gates, not one build per
  small commit. Native report facts will be recorded separately after observation.
  Cross-version coexistence, first-use consent, distinct-workspace process behavior,
  physical Mac/phone, complete mapping/authority protocol and hosted gates remain.
- Final local gates: docs 58 passed in 1.93s / 5.4s total; default critical
  14 passed in 7.44s / 10.7s total; updated roundtrip report assertion 1 passed
  in 0.80s / 3.8s total (overlap). Privacy/Ruff/whitespace passed. The new handoff
  does not acknowledge first-use consent; it uses the already acknowledged
  synthetic recipient. Native execution, not these mocks, must prove handoff.


## 2026-11-15: common native d2689e8 candidate passed

- Previous turn made progress: native-handoff verifier d2689e8 committed/integrated/
  pushed and exactly one native candidate dispatched. This turn observed that same
  live run 43656611701 to completion; no duplicate dispatch or local broad test.
- [Run 43656611701](https://github.com/puddings-world/Paperfact/actions/runs/43656611701)
  built clean `d2689e8a27f6bdb444bcde7f4261254f9bacf02b`, `0.5.0.dev` on all three
  desktop platforms. Windows 7m20s, Mac arm64 3m33s, Linux x86-64 2m18s.
  Tag-only draft job skipped as designed. No release or service deployment.
- Inspected actual packaged-acceptance.v1 reports: passed with matching clean
  identity, all three instance_handoff flags true, four exact preserved research
  files, import/repeated import, reader/export, original audit, credential isolation,
  CLI/MCP 38 tools with retry/restart. These are native same-workspace handoffs,
  not only mocked process tests or sequential launches.
- Critical: Windows 14 passed in 5.82s; Mac 14 passed with five warnings in 3.18s;
  Linux 14 passed in 1.92s. Same 14 journeys across OSes, not 42 distinct cases.
  Windows actual mobile artifact TAP: tests 5/pass 5/fail 0. Privacy/Ruff passed.
  Curated release 37 selectors and historical full suite were not run here.
- Mac three-start and Launch Services foreground/close passed. Linux AppImage
  CLI/MCP/retry/restart passed. Windows actual install/installed reader+CLI+MCP/
  same-version reinstall/uninstall and research_preserved all true. Installer
  payload SHA-256 `8248fc50ae3958f45bc9182210db0b0662175b3bea94a59796210ebd761b9289`.
  Old-release upgrade/coexistence and registry/shortcuts remain not checked.
- GitHub artifact ZIP identities (not contained payload hashes):
  Windows 14138891485, SHA-256 `5b60e7b5395de35c8140b70c00df28507705137cf02977fea1337a5c07993055`;
  Mac 14138416028, `570be6bb583982f251766f4a65a5451577469f39cb14f0dbf24a40f9589ca700`;
  Linux 14138640641, `f5bada40fadf7dec7368f88437c2461dd8d49af569a0b981a1a90be4ba8f624e`;
  synthetic Mac fixture 14138241369, `6db48cd58401448e30a4e49ff4cf44e4a3ea15f1c63303e9acc862a718ac481a`;
  mobile static 14137374460, `6fd2a0836d07c65b4367259ee8af6d03fb612eb672e7e64971c9982484ce2af0`.
  Reports/index retained in ignored `build/candidate-43656611701/`.
- Updated the existing Mac acceptance/readiness/status/board to this exact candidate.
  Docs-only checkpoint does not require another native build. Earlier b4ec451
  reports remain historical evidence, not current candidate proof.
- Physical M01-M21, actual new report-removal UI, separate-workspace process cases,
  real providers, complete writer/source mapping, full authority generation/reset
  protection, private HTTPS issuance and hosted recovery/phone durability remain
  open. Native artifact presence does not prove those features' installed journeys.
  Existing support/evidence patterns suffice; no new skill or global rule promoted.
- Documentation checkpoint: 58 passed in 2.34s / 6.1s total, privacy/Ruff passed.
  The unchanged runtime reuses this exact source candidate's critical passes on
  all three OSes above; no repeated local critical/exhaustive/native run for a
  download-link update. CRLF-aware whitespace check passed.


## 2026-11-15: mandatory HTTP execution continuity

- Previous turn made progress: common d2689e8 artifacts actually verified and
  downloads refreshed in f8fbdf5. New code does not change those package facts.
- Source diagnosis: a received/acknowledged frontier proof is not an atomic
  receiver guard if the HTTP listener changes before later writes. Added a random
  per-listener X-Paperfact-Sync-Instance offer, mandatory authenticated request
  guard and closed 428 sync_session_changed rejection before service acceptance.
- Payload bounds precede handshake; valid identity precedes pinning/private work.
  Missing/changed/malformed/duplicate response offers cannot replace a pin.
  Headerless private requests fail (identity/pairing/forget bootstrap is exempt).
  Proxies must preserve both directions; the real browser test proxy now does.
- Python recreates a transport to reconnect. Mobile begin_session clears only the
  ephemeral pin and increments a delivery generation; Engine.connect invokes it.
  A late old response cannot pin a previous execution. Cookie secrecy and expected
  workspace/device checks remain. Existing UI guidance now checks version match.
- Existing raw HTTP/browser fixtures now perform the required identity preflight;
  no authorization/schema/data-preservation assertions were removed. Typed old
  blob/pairing unsupported errors were retained rather than treating absence as
  malformed JSON. A fake streamed httpx response initially used an already-read
  body; replaced it with the proper ByteStream fixture, not a production bypass.
  Missing offer in an old throttle fixture was corrected to model the new protocol.
  Formatting findings stopped before pytest and were fixed.
- Affected Python HTTP/blob/device/browser: 149 passed in 18.87s / 22.2s total.
  Mobile transport/engine/cache: 31 passed in 3.594s governed execution. Actual
  JS/Python HTTP journey passed in 2.344s. Isolated real headless Chromium cookie
  pairing/reload/explicit reconnect/Chinese forget: four PASS observations in
  14.39s, report build/browser-protocol-v26.json. No real profile, provider or data.
- v26 shell replaces v25 without clearing research stores. Daily critical stays
  14; one actual listener-restart representative adds a distinct release requirement
  (38 selectors, not a historical full run). No new test file or public deployment.
- This is listener-execution acceptance, not confidentiality of buffered HTTP bytes
  or a complete authority protocol. Persistent history epochs, split-brain,
  unsupported in-place live DB rollback, deployment/physical gates remain open.
  New native packages are not built here; delivered candidate remains d2689e8.
- Final delivery review caught a Python late-body race: an older identity response
  could overwrite an execution pinned while its body was delayed. Regression
  first failed (`DID NOT RAISE`) in 0.71s. Pin delivery now rechecks under a small
  lock without holding it across I/O. All history/continuity cases: 17 passed in
  3.66s / 6.9s total; actual JS/Python service path rechecked in 1.875s.
- v26 allowlisted local artifact built and verified: 50 files, 3,914,699 bytes,
  artifact ID `a569b6605a3c129ed7b242279ad1427e8025a52f72d5ceeb809549f9e9ba8619`,
  ignored build/mobile-web-execution-v26. No upload or hosting is implied.
- Docs gate: 58 passed in 1.96s / 5.6s total; default critical 14 passed in
  7.80s / 11.1s total before the final HTTP-only pin-delivery refinement.
  No full historical run, paid calls, research access, cleanup or native rebuild.
- Final runtime gate after pin-delivery lock: critical 14 passed in 7.77s /
  11.4s total, privacy/Ruff passed. Docs/CLI contract 58-case evidence remains
  applicable; only dated evidence text changed afterward. Skill copies match
  canonical content; CRLF-aware whitespace passed. No native/cloud dispatch.


## 2026-11-15: ordinary profiles can prepare without exporting local authority

- Previous turn made progress: mandatory HTTP execution continuity 03d7ab1
  integrated/pushed. Reviewed server backup recovery already reconstructs a fresh
  workspace and removes old credentials; no duplicate restore-generation system
  was added. Hosted/device and persistent protocol gates remain separate.
- Found real initial-copy blockers: update cache, local schedules/sharing/retry KV
  and lists.legacy_queue were rejected as unsupported despite intact research.
  The actual schedule/update-writer regression failed pre-fix with unsupported KV
  and unsupported research KV: lists.legacy_queue (1.86s / 5.1s total).
- Added explicit private KV classification; a bounded legacy adoption ID remains
  local data in copy/backup/restore, including intentionally retired-list markers.
  Unknown analysis/update/drive scopes and malformed marker values still block.
- Bound workspace refresh now returns before legacy list construction and rechecks
  under the existing write lock. No journal replay or implicit extra shared list.
  Ordinary unbound one-time conversion and read-only refresh are unchanged.
- Also classified actual AI settings, Google client config, usage and consent DB
  files/sidecars. Root ai-accounts/usage-changes/diagnostics are pruned before
  descendants are walked; root links and unknown research retain validation.
  The regression's scanner fails on private traversal and verifies excluded values
  never reach candidate or independent backup. No owner account files were read.
- Initial controls/unknown scopes/agent-import cases: 5 passed in 12.09s / 15.3s.
  Strengthened full-SQL preservation plus marker failures/unbound/read-only
  compatibility: 9 passed in 11.01s / 14.2s. Private-tree pruning, existing unknown
  file/schema failures and exact PDF/backup closure: 10 passed in 18.79s / 21.9s.
  Counts overlap; no completion percentage. Formatting findings stopped before
  pytest and were fixed, including a duplicate import, without weakening checks.
- The existing release agent-import case now includes a real update-cache write;
  no selector added: daily critical 14, release 38. No new test file, live account,
  paid call, native build, research migration, cloud action or broad cleanup.
  d2689e8 remains the delivered native candidate and predates these source fixes.
  Complete arbitrary legacy/source/runtime adoption and physical gates remain.
- Final actual desktop preview/prepare/open, updated agent-import representative
  and unreadable research-directory rejection: 3 passed in 5.70s / 9.0s total.
  The latter proves non-private scan errors fail rather than silently omitting
  research. Docs 58 passed in 2.07s / 5.9s total; default critical 14 passed in
  7.12s / 10.2s total. Privacy/Ruff/CRLF-aware whitespace passed; skill copies
  synchronized without conflict. Unchanged passing checks were not broadened to
  historical/stress or native builds. No global rule/installation was changed.


### 2026-11-15: packaged sync execution verification

- Previous turn changed authoritative source (1336991); the CPU-status turn then
  verified no live test processes and matching clean integration/source HEADs.
- Delivered d2689e8 predates execution pinning and private-profile preparation.
  Rather than certify these from old packages, extend the existing native verifier
  with one loopback `sync-protocol` stage through the actual packaged CLI.
- Run synthetic init/issue/serve, authenticated pull, stop/restart, HTTP 428 for
  the old execution and explicit handshake/pull. No research writes, real account,
  cloud resource or public release. Private credentials/logs stay isolated.
- Initial focused result: 17 passed, 1 failed in 2.83s / 6.0s total: verifier
  assumed an object while existing pull API returns an array. Corrected the
  verifier to the existing contract; production protocol was not changed.
- Focused final: 20 passed in 5.33s / 8.3s total; includes actual isolated source
  CLI and owned-child cleanup on normal, bad-header and stale-accepted outcomes.
  Native evidence remains pending until a new clean candidate runs on each OS.
- No new reusable global pattern: closed result reporting and owned-child cleanup
  already have canonical skill coverage. No skill copies/global hooks changed.
- Docs: 58 passed in 1.89s / 5.0s total. Default critical: 14 passed in
  7.89s / 11.4s total; privacy, Ruff and CRLF-aware whitespace passed.
  No historical-suite run. Candidate dispatch follows this clean checkpoint.
- Clean source 8bf00f999bb25acf20de4df94a697fa06323dd4e was integrated/pushed,
  then manual all-platform run 43663374908 completed successfully. No draft/public
  release. Windows/Mac/Linux jobs: 464/274/189 seconds (7m44s/4m34s/3m09s).
- Downloaded/inspected all three actual provenance reports, not just job badges:
  exact clean SHA/version; sync_protocol authenticated_pull, stale_execution_refused
  and reconnected all true; same-workspace handoff all true. Mac reader launches=3
  and mac-foreground completed. Existing research/CLI/MCP/original audit retained.
- Windows actual installed/reinstalled/uninstalled/research_preserved all true,
  installed CLI/MCP tools=38 and retry/restart passed. acceptance_mode=true;
  older_release_upgrade_checked=false, registry_shortcuts_checked=false.
  Contained setup SHA256: 88e1836c050538e6e59d3875ecffeaa408efe03b02c96c2d6ab748572285f5a3.
- Per-OS source critical: Windows 14 in 5.75s (10.7s total), Mac 14 with five
  warnings in 4.07s (7.2s total), Linux 14 in 3.11s (5.8s total). Same 14 journeys,
  not 42 unique cases. Windows mobile artifact TAP tests=5/pass=5/fail=0.
- Small reports and full artifact index retained privately under ignored
  build/candidate-43663374908/. Mac build archive 14140619840, 278776354 bytes,
  SHA256 b6a7663f3935fc4fbcc668800973d1baa0ef7eddf5711174e3487063e15a3603.
  Mac synthetic research archive 14140824453,
  SHA256 93a34e8f7f58a80714fb43401ee95aebd11a19bc8b401098a08dbb638ad91549.
  These are GitHub archive hashes, not the contained DMG or research ZIP hash.
- Updated existing status/readiness/Mac/test-map/board to this common candidate.
  No native rebuild for these documentation-only changes; source/critical/native
  evidence belongs to 8bf00f9. Hosted, physical devices, full source/runtime mapping,
  persistent authority protocol, scholarly evaluation and release gate remain open.
- Final documentation-only check: 58 passed in 1.79s / 4.9s total, privacy
  and Ruff passed. Reused unchanged source-critical/native evidence rather than
  rebuilding or running the historical suite for download/status edits.


### 2026-11-15: recorded context-summary retirement

- Previous goal turn made progress: 8bf00f9 added actual packaged sync execution
  verification and all-platform candidate delivery; 88cd586 recorded exact results.
  Both worktrees started clean at that checkpoint. No native job remains live.
- Reviewed desktop authorized passes: each constructs/verifies a fresh transport;
  retained received/acknowledged frontier checks still run before publication.
  No unsupported persistent-epoch or complete installed-sync claim was made.
- Found a remaining typed recovery gap: context/main deletion fell into the manual
  highlight path. New real native case failed pre-fix with "Deletion has no exact
  native manual-highlight creation proof" (8.35s / 11.5s total).
- Added context only to the closed report-removal registry and saved-reading action.
  Exact native creation, mapped parent lifetime, current head/projection and every
  visible field must match. Summary/reading JSON may be null. SQL predicates bound
  summary/reading JSON/timestamp before materialization; edited must be integer 0/1.
  No original grant, source activation, AI call or generic deletion authority.
- Same receipt/outbox transaction and no-op retry preserve a later restoration.
  Existing tests now cover four report slots through the same four requirements:
  peer/retry, receipt failure/cancel/stale target, untracked visible content and
  actual Chinese default-No/single-flight confirmation. No new test file, gate
  selector or stress matrix; daily critical remains 14, release 38 selectors.
- Complete affected file: 13 passed in 119.84s / 123.4s total. Final context-only
  byte/type guards and wording: 3 passed in 29.02s / 32.3s total (overlapping cases,
  not an aggregate unique test count). Refusal checks cover oversized summary,
  reading JSON and edit marker without changing the invalid target. All checks
  used the single Windows governor (two logical processors/25 percent CPU).
- Initial import ordering/line-length checks stopped before pytest and were fixed;
  no behavior assertion was weakened. Source/Qt evidence only: installed/hosted/
  physical-device and remaining source/research mappings are still gates.
- Existing typed-write/receipt/bounded-input skill guidance already covers this
  extension; harvest review found no new reusable rule to manufacture. No global
  skill copies, owner data, cloud resources or current release were changed.
- Final docs: 58 passed in 2.05s / 5.2s total. Critical: 14 passed in
  7.70s / 10.9s total. Privacy, Ruff and CRLF-aware whitespace passed. No historical
  suite, repeated native build or real account/provider invocation.


### 2026-11-15: list-overview evidence status and remaining survey contract

- Previous turn made progress in 3ee86f5 (recorded context retirement). Current
  source and integration started clean there. No local/native check was left live.
- Investigated list-survey auditing: current rows hold text/count/spec/time/edit,
  and generation digests mix analyses/context/abstracts. These do not provide a
  portable claim-to-original ledger. Existing single-paper AuditCapture explicitly
  leaves list_surveys unchecked. No current list/PDF was assigned to old prose.
- Added a compact bilingual list-overview notice for recorded roadmap, saved
  research or unknown workflow; manual edits and unverified sources are explicit.
  It adds no button or background job and hides/clears on empty/changed workspace.
- Expanded the existing SurveyDialog file with one behavior test that loops the
  actual closed workflow/language states. AI/http calls fail the test, full SQL
  dumps stay unchanged, and empty/workspace changes clear stale labels. Existing
  rewrite-running and default-No replacement protections remain unchanged.
- Initial Ruff line-length failures stopped before pytest; fixed escaped text
  wrapping. Focused final: 3 passed in 1.55s / 6.5s total. No selector matrix,
  real account/model/network call, owner data or new worktree.
- Synthetic render initially used a nonexistent theme module, then the shared
  environment's editable integration source rather than the uncommitted source.
  Those outputs are not visual evidence. Corrected with explicit src PYTHONPATH,
  an imported-file assertion and normal style/font loading. Final bounded render
  passed in 0.984s; English and Chinese 900x500 PNGs were actually inspected under
  ignored build/survey-evidence-20261115/current/. Text wraps without clipping.
- Added the full remaining source-aware survey contract to the existing audit
  plan: immutable input/member/source identities, per-statement originals and
  explicit gaps, manual-link invalidation, shared sync/bundle/recovery transport,
  owned-reader/sealed audit, and independent peer/stale/cancel/retry acceptance.
  It is explicitly planned, not silently treated as complete by this status UI.
- Reviewed harvest applicability: existing evidence/identity/unknown-state rules
  already cover this change; no new global skill or hook was manufactured.
  Delivered native candidate remains 8bf00f9; this source is not repackaged.
- Final docs: 58 passed in 2.07s / 5.2s total. Default critical: 14 passed
  in 7.41s / 10.4s total. Privacy, Ruff and CRLF-aware whitespace passed.
  No historical-suite run, packaging rerun, release or cloud deployment.


### 2026-11-15: exclude app-owned HTTP cache from first-enrollment research

- Previous turn progressed in 6c6fadc (evidence-status UI and explicit remaining
  survey contract). Source/integration began clean there; no test/build handle live.
- Audited real workspace writers before changing coverage. http.fetch writes URL-
  hashed response bytes under config.HTTP_CACHE=httpcache, including retrievals
  after normal use. Storage maintenance already treats this namespace as cache.
  It was not excluded, so normal cached directories blocked complete-copy coverage.
- Extended the existing private-controls case with actual http.fetch disk writes
  and synthetic httpx responses. Its protected scanner failed before the fix when
  the inventory descended into httpcache (1.79s / 5.3s total). No external request.
- Registered only the reserved top-level httpcache in the existing exclusion set;
  no new copier or cache service. Root path/link checks remain in place, descendants
  are not enumerated, and neither cache responses nor recheck files become backup
  research. No cache is deleted, parsed as source authority or automatically rebuilt.
- The regression modifies a cached response and writes another after the first
  research inventory. Preparation still publishes coherent research/backup, retains
  source cache bytes locally and excludes the private response marker from archive.
  Explicit primary PDFs stay verified/bound/in the independent backup. Declared
  original requirements and unknown/unreadable research remain guarded.
- One distinct unknown-path boundary was added to the existing coverage case:
  httpcache-notes is research, not an excluded prefix. All historical assertions
  remain. Affected coverage/PDF/cache/source-change/error set: 15 passed in 30.19s /
  33.3s total. No new test file or critical/release selector; still 14/38 selectors.
- Actual existing Qt preview/prepare/open now includes a cached response: 1 passed
  in 3.77s / 6.8s total, preserving exact primary PDF, notes, source and account
  isolation. No owner data, live accounts, paid calls or native build were used.
- This extends the existing reserved-private-tree pattern; harvest review found no
  new global rule to promote. Remaining KV/legacy/source/runtime adoption, installed
  and hosted/physical-device gates remain; delivered candidate is still 8bf00f9.
- Final docs: 58 passed in 1.98s / 5.0s total. Default critical: 14 passed
  in 8.69s / 11.7s total. Privacy, Ruff and CRLF-aware whitespace passed.
  Source checkpoint only; no historical sweep, native rebuild or deployment.


### 2026-11-15: paper-scoped citation graphs across native sync and packages

- Previous turn progressed in 08759f7 (owned HTTP-cache exclusion). Worktrees began
  clean there. Citation graph KV contains actual retrieved relations/counts, so it
  cannot be omitted like a response cache. Scope remains the complete v0.5 roadmap.
- Added closed citation_graph/main content over only citegraph.<local-paper-id>.
  Existing storage/readers stay intact; no schema/private-KV migration or arbitrary
  table replication. Every selector/projection uses the closed namespace and exact
  paper mapping. Raw validated JSON remains byte-for-byte lossless in local KV.
  Receivers construct their key; no wire-chosen setting key/source grant is allowed.
- Closed four-field body: aware retrieval time, bounded distinct non-self edges,
  integer counts and 200 KiB raw value, with normal payload/operation caps. Python
  and mobile share Unicode, duplicate/escaped-key, boolean/fraction/exponent and
  shape verdicts. Lookup IDs remain inert data; no DOI/title identity inference.
- Producer now observes its native graph/parent before external work and carries
  the base through commit. Initial deletion test hit the existing observation
  requirement; fixed its explicit observation, not the protection. Actual late
  provider response retains a candidate and preserves the newer graph. Concurrent
  independent graph edits retain both incoming/head versions and acknowledge safely.
- Capture/snapshot/graph peer/delete/private KV plus copy/backup baseline: initial
  3 passed in 7.90s / 11.1s total. Existing affected capture/content/citegraph files
  plus copy representative: 63 passed in 74.05s / 77.3s total. Later stale-provider
  and contract checks: 2 passed in 3.81s / 11.1s. Final concurrent/peer/Unicode/copy
  slice: 4 passed in 11.67s / 14.7s total. Counts overlap, not an aggregate score.
- Enrolled package importer now accepts only validated graph KV for a declared
  package paper, maps its receiver owner, preserves existing graph by default and
  supports explicit replacement. Exact retry preserves a later edit. Other legacy
  KV remains refused. Initial new test assumed imported; real API is applied_locally;
  fixed that new expectation without changing production semantics. Graph import
  and old unsupported-KV check: 2 passed in 5.46s / 8.5s total.
- Final existing release-selected agent-import baseline now also preserves graph
  raw JSON/capture/independent backup/detached restore, alongside request-authority
  isolation. No selector added: critical 14, release 38. Final baseline/closed-row/
  package-later-retry slice: 3 passed in 10.17s / 13.4s total. No new test file.
- Mobile validates/retains the graph as ordinary saved research. The existing bounded
  position tokenizer has opt-in whole-JSON duplicate/integer-token checks; normal
  position ingress remains intact. Its old HTTP stub lacked execution headers and
  ignored after/limit, so it failed before its target numeric assertion. Repaired
  only those pre-existing fixture contract gaps; every float/exponent rejection
  and unchanged store/cursor assertion remains. Final three-file Node set: 59/59
  in 0.735s governed. Final expanded content fixtures: 32/32 in 0.359s (overlap).
- An edit script had failed parsing before its mobile mutations; the prior 63-case
  result covered only already-written Python source. Reapplied mobile edits and
  verified them independently; no mobile success was inferred from that old check.
- Actual JS-to-Python HTTP with a graph beside existing pairing/revocation, drafts,
  rich analysis, notes, PDF/deck/offline/conflict checks: passed in 1.953s governed.
  v27 static build/verify: 0.532s/0.218s; 50 files, 3916230 bytes, artifact ID
  0e7ddb34524afc62a97bbf5c3d005fc946d73f7a3d07bc87582857b96926c710 under ignored
  build/mobile-web-citation-graph-v27. Built locally, not deployed or native packaged.
- Harvested one validated-local mixed-storage boundary into the existing canonical
  local-integration skill and synchronized only project .agents/.claude copies.
  No global installation/rule, real model/account call, owner database, release or
  cloud resource changed. Native candidate remains 8bf00f9. Old clients require a
  coordinated update for the new feature; installed graph refresh, hosted/physical
  devices, remaining KV/legacy/source/recovery and full survey audit remain gates.
- Final docs/skill consistency: 58 passed in 2.01s / 5.4s total. Critical:
  14 passed in 8.29s / 11.5s total. Privacy, Ruff and CRLF-aware whitespace
  passed. No historical suite or native/hosted build was started for this checkpoint.


## 2026-11-15: packaged citation-graph persistence gate

- Extended the existing packaged loopback verifier rather than adding another
  suite: actual CLI init/issue/serve, synthetic paper and scoped citation graph,
  exact accepted envelope/content, idempotent retry and no extra event, then exact
  graph recovery after listener restart and mandatory execution re-handshake.
- The existing response bound, per-command/startup/HTTP timeouts and owned-child
  cleanup remain. Public report adds three closed graph booleans; no identifiers,
  raw graph, credential or authority database is included.
- CI diagnostics now allow only four exact synthetic protocol log paths in
  addition to existing logs. A contract test prevents a whole-folder upload.
- Focused packaged-verifier file: 22 passed in 7.04s / 10.1s total, privacy and
  Ruff passed. Actual isolated service covered; graph-loss, stale execution and
  wrong-header failures reaped their children. No owner research or paid calls.
- This extends already-established packaging/privacy methods; no new global
  skill rule is inferred. Frozen candidate build, installed devices and hosted
  acceptance remain separate gates. Candidate still 8bf00f9 until a new run passes.
- Integration gate: 14 passed in 5.91s / 9.3s total, privacy and Ruff passed.


## 2026-11-15: common v27 native candidate delivered

- Clean source 15aae7e17c3ffa41852ee949d6fc1cabdc67e145, version 0.5.0.dev,
  run https://github.com/puddings-world/Paperfact/actions/runs/43671331418.
  One manual all-platform dispatch; no release or deployment. Windows/Mac/Linux
  jobs passed in 398/330/186 seconds. Local build CPU was not used.
- Read all three actual paperfact.packaged-acceptance.v1 reports and source build
  metadata: matching commit, dirty=false, passed=true. Each reports all six closed
  sync booleans, including exact citation graph, duplicate retry and restart
  persistence; instance handoff and CLI/MCP 38-tool retry/restart also passed.
- Critical per OS: Windows 14 in 3.74s / 7.2s total; Mac 14 plus five warnings in
  5.57s / 9.0s; Linux 14 in 5.56s / 8.3s. These are overlapping journeys, not 42
  distinct requirements. Windows mobile artifact tests: 5 passed, zero failed.
- Mac arm64 report verifies three reader starts; native Launch Services acceptance
  passed. Windows installer report verifies clean install, same-version reinstall,
  uninstall, exact research preservation and installed CLI/MCP; older-release
  upgrade and registry/shortcut checks explicitly false, not inferred passed.
  Contained setup SHA-256: 95b91a0b350bf3d9792a0bac0be29f7cff499ba4f3c4c2ffa9caa35e68a72377.
- Artifact ZIPs (hashes identify GitHub archives, not their contained installers):
  Windows 14144148013, 184141069 bytes,
  3cd07615bc0f52cc5e2b4d35e9de00e44a353e18062a479ea377cfda3d074806;
  Mac 14145025254, 279423984 bytes,
  8612793792e88f9874e7d0587c8160504571c36c8e40b03aacc5accc9b244e7f;
  Linux 14144970038, 282167106 bytes,
  fa8922d3d2b23de2079f618539f6da44d100dfaf25b609761f72733d5cc6b583;
  Mac synthetic fixture 14144900578, 7591 bytes,
  a274278e5ccd4f6a807f12ea3086b3e050851c4f170092711e460554b4700beb;
  mobile web 14143544601, 883563 bytes,
  552e116465315b7b0354e8546efaaab6c59147c41a108bf1bdd51f106a17853b.
- Small provenance reports, exact artifact index and three job logs retained under
  ignored build/candidate-43671331418. Existing Mac guide/status/readiness/test map
  and sole board now identify the common candidate. No big installer download or
  repeat build was needed to record this documentation checkpoint.
- Candidate includes context retirement, overview evidence labels, reserved-cache
  exclusion and scoped citation graphs/v27 parity since 8bf00f9. Old headerless
  peers require coordinated update. Dev bundles do not auto-update.
- Physical M01-M21, installed vault/input/upgrade/coexistence, hosted HTTPS/device
  issuance/revocation/backup and phone durability remain not run. Complete legacy
  mapping/recovery, source-aware survey audit and persistent authority/history
  commitments remain incomplete. No claim of completed v0.5 or public readiness.
- Documentation consistency: 58 passed in 2.21s / 5.5s total; privacy, Ruff
  and CRLF-aware whitespace passed. Reused unchanged code/native evidence.


## 2026-11-15: offline mobile citation reading

- Closed a real reader gap: canonical citation rows were retained by the receiver
  but omitted from the mobile overview. The existing annotations/overview seam
  now renders collapsed saved reference cards with title/key, year/venue, purpose,
  gist, saved judgment/reasoning/basis and separately collapsed literal passages.
  Missing passages are explicit. No fetch/model call, external URL or write action.
- Source notices distinguish unknown, unopened, matching and different original
  versions. Matching a hash is not quote/semantic verification. Existing current
  verified PDF state is the only comparison input. Incoming changes continue
  through the existing render/selection/draft model; no new worker or store.
- Used existing CSS tokens; 44px native disclosures, visible keyboard focus,
  whitespace-preserved passages and unbroken-title wrapping. English/Traditional
  Chinese 390px previews actually inspected and retained as synthetic docs images.
- Final affected Node files (annotations, content, shell upgrade): 59 passed,
  zero failed in 0.423s / 0.579s governed. Initial shell test still expected v26
  although source already used v27; updated its explicit v28 contract and added
  v26/v27 eviction while preserving every research-cache/request assertion.
- Strengthened existing JS/Python HTTP rich-content baseline with an exact full
  citation record beside prior graph/analysis/draft/note/PDF/deck/conflict checks:
  passed in 2.000s governed. No new release/critical selectors.
- Final focused actual Chrome DOM scenario: bilingual disclosure/focus, literal
  hostile-looking text with no executable nodes, long title within 320px, changed
  original notice; passed in 2.109s governed including owned-browser shutdown and
  exact temporary-profile cleanup. No owner browser profile or research used.
- Browser diagnostics were not an exhaustive green gate: dump-dom stopped before
  async IndexedDB completion. The broader old harness prohibited every Lineage
  button, predating the exact-original viewer. Replaced that obsolete UI contract
  with only the expected localized source action, actual modal open/close, no
  edits/unchecked links and unchanged durable research. Waits now reacquire an
  enabled live button after async reads rather than clicking an obsolete node.
  One full body reported eight passing journeys but its helper cleanup failed;
  a later whole-harness attempt stalled at startup. Do not claim a reliable full
  browser pass. The final focused scenario avoids unrelated IndexedDB startup;
  broader harness timing and physical-browser durability remain acceptance gaps.
- The initial helper left only its own locked profile; no broad TEMP cleanup,
  ACL change or unrelated process termination was attempted. Graceful owned
  Browser.close plus process wait fixed cleanup in the focused helper.
- v28 static build/verify: 0.609s / 0.250s; 50 files, 3920367 bytes, artifact ID
  9542054449a159be40bc1b9d9a781eeddf037708b7e73a63092610021dc8fb28 under ignored
  build/mobile-web-citation-cards-v28. Built locally, not deployed or native packaged.
- Native candidate remains clean 15aae7e, v27. Do not rebuild it for a documentation
  change or claim it contains these cards. No new architecture pattern was proved;
  existing read-only/source/privacy/browser guidance suffices, so no skill copies
  or global rules changed. Hosting/device/full mapping and recovery gates remain.
- Final docs: 58 passed in 2.28s / 6.0s total. Critical: 14 passed in
  7.54s / 11.0s total. Privacy, Ruff and CRLF-aware whitespace passed.
  No owned citation-test Chrome process remained. No native rebuild was started.


## 2026-11-15: first-sync resource history

- Fixed an actual preparation blocker: resource lookup uses native compound
  receipts and a completion hint, but the old archive adapter accepted only an
  empty followup fetch. The existing private archive now supports the closed
  resources phase; no new table/protocol/module or transport is introduced.
- Strict bounded duplicate-key-safe context/mutation decode plus maintained
  envelope/output validation; closed paper/authors and typed observed resource
  rows. Unexpected model inputs and nonempty legacy extracted-text provenance
  remain unsupported. Declared PDFs join the existing owned-byte closure check;
  archived paths are not opened or used as capabilities.
- Only exact validated accepted owner/completion matches omit a redundant live
  resources hint. Actual completion remains in the archived mutation. Candidate,
  malformed or mismatched hints do not suppress work. Reads are SQL-bounded and
  owner-filtered, with record/total-byte limits. NULL candidate_id remains the
  existing successful-receipt contract, separately checked from oversized data.
- Actual mocked-network resource producer, readable original, first-copy/live
  resource operation, exact archived strings, no private context in the outbox,
  unchanged source and independent backup/restore verified. Detached restoration
  intentionally retains old private history in recovery_records, not live tables;
  the initial new test expected the wrong table, then was corrected to compare
  full exact records and original PDF bytes without changing production restore.
- Affected history file: 11 passed in 23.85s / 27.0s total. Early runs stopped on
  formatting, then exposed the new adapter's incorrect blanket NULL rejection;
  fixed the implementation. Unknown nested input correctly raised the existing
  validation error; the new negative test now asserts that contract and redaction.
- Existing private-archive and mixed-KV skill boundaries already cover this change;
  no new portable rule or synchronized/global skill copy is needed. Source-only
  progress; native candidate stays 15aae7e. No deployment, owner data or paid calls.
- Expanded the existing negative behavior with duplicate nested keys, unsupported
  author/model snapshots, a foreign captured owner and nonempty legacy text;
  no new selectors. Mismatched hints and private error redaction remain pinned.
- The broader hint check exposed a prior citation-graph import message regression:
  unsupported legacy KV still correctly refused without any writes, but lost its
  established error category. Restored legacy research KV only for non-graph
  scopes; malformed graphs keep their existing category. Existing tests unchanged.
- Strict new negative plus unchanged later-hint regressions: 14 passed before the
  selected graph-import journey caught a newly introduced local import alias
  shadowing its selected file path. Fixed that code, not the test. Final graph
  journey: 1 passed in 3.12s / 6.2s total; prior slice was 14 passed/1 failed,
  not a green combined run. The alias fix changes no accepted data contract.
- Final docs consistency: 58 passed in 2.00s / 5.3s total. Critical: 14
  passed in 7.59s / 11.1s total. Privacy, Ruff and CRLF-aware whitespace passed.
  Existing native/device evidence was not rerun or broadened.


## 2026-11-15: first-sync citation and related-work history

- Extended the same private compound-history boundary to all maintained phases:
  citation analysis, nonempty fetch, related-work judgment, resource lookup and
  reference/followup manual edits. Producers and archive validation now share
  PAPER_INPUT_COLUMNS; no second inferred paper schema, table or transport.
- Strict nested JSON, exact typed captured rows, output validation and declared
  source closure remain. Model inputs are retained privately only for the two
  model phases. Unknown nested fields, duplicate keys and unsupported text-only
  provenance still refuse. Boolean/float schema versions now explicitly refuse.
- First-copy fetch completion hints can be omitted only with an exact validated
  accepted owner/phase/completion record. Actual timestamp remains in the inactive
  archive. Enrolled package import/unsupported legacy behavior is unchanged.
- Strengthened the existing producer representative, without adding selectors:
  actual mocked-network/model output, live-row equivalence, exact archived receipt
  strings, no private inputs in the outbox, unchanged source and independent
  backup/detached history/PDF restore. Initial new test placed output inside its
  source; the existing isolation guard correctly refused. Corrected fixture paths
  to independent owned siblings without changing the guard.
- Four producer paths unbound/enrolled: 8 passed in 24.51s / 27.7s total. Expanded
  producer, stale-candidate, both manual-edit phases and resource negative slice:
  21 passed in 41.36s / 44.8s total. Candidate/manual records match exact original
  archive bodies and keep existing visible-data/outbox assertions. These overlap;
  they are not summed into distinct coverage or a release percentage.
- Source-only checkpoint; candidate remains 15aae7e/v27. v28 is not deployed.
  Runtime maintenance/adoption, remaining legacy/source mapping, unavailable
  original bytes, full scientific audit and hosted/physical-device gates remain.
  Existing private-archive skill guidance suffices; no new global rule or copy.
- Final strict-version representative: 1 passed in 4.70s / 8.0s total. Source
  critical gate: 14 passed in 8.46s / 12.2s total; docs consistency before the
  final map addition: 58 passed in 2.16s / 6.0s total.
- Strengthened the existing release-selected agent-import first-copy representative
  with a real native citation publication, exact archived context/mutation, live
  fields and detached history restore. The first fixture omitted mandatory basis;
  storage correctly retained a candidate. Supplied explicit title-only basis,
  preserving the accepted-outcome assertion. Final representative: 1 passed in
  5.89s / 9.8s total. Daily 14/release 38 selectors remain unchanged. No native
  rebuild or historical full suite was run for this source checkpoint.
- Final updated-map/docs consistency: 58 passed in 2.39s / 6.8s total.
  Privacy, Ruff and CRLF-aware whitespace passed. Reused unchanged source gate.


## 2026-11-15: retained legacy compound text

- Verified that the queried-empty later-outcome contract should remain empty-only;
  no permissive change was made to it. The actual first-copy gap was nonempty
  extracted-text provenance, which previously required a separate adapter.
- Added one self-contained private archive protocol, compound_text_history_v1,
  retaining the complete exact original request and UTF-8 input. No live table,
  job, network endpoint or source/PDF grant. Strict joint request/text hash checks
  retain CRLF/Unicode bytes; malformed origin/request/text and corruption refuse.
- Collector reads only the two known workspace cache names derived from owner,
  compares the observation lexically, rejects links, bounds reads to 3 MiB and
  checks versions before/open/after plus actual hash. Observed external paths are
  never opened. Changed/missing/unowned layouts still block rather than disappear.
- Exact full-request fingerprints carry verified text to completion-hint matching.
  The file is accounted for as an archived input; source SQL/bytes remain unchanged.
  Raw legacy backup now refuses declared text that it cannot retain completely;
  reviewed copies/backups carry the self-contained private evidence instead.
- Focused legacy-text preserve/path/change plus prior PDF-backed resource test:
  3 passed in 9.99s / 13.2s total. Enhanced existing release first-copy baseline,
  corrupt/private text and prior resource rejection: 3 passed in 11.26s / 14.4s.
  No new release/critical selectors; the baseline now preserves exact citation,
  import receipt, citation graph, text and PDF through detached restore.
- Native CI adds that same one focused first-copy representative per OS with a
  three-minute cap; Windows tag release does not duplicate its existing selection.
  This is necessary native file/version coverage, not a historical suite expansion.
- Native candidate remains 15aae7e pending a new run. Its older app cannot inspect
  the new private protocol. Live sync wire format is unchanged. Current text is
  inactive evidence, not a verified original, rendered PDF or old-job authority.
  Runtime adoption, arbitrary derivatives and hosted/device acceptance remain.
- Source critical: 14 passed in 7.55s / 10.7s total; docs 58 passed in
  1.97s / 5.2s. Harvested the validated-local checksum-versus-byte-closure boundary
  into the existing canonical local-integration guide/reference; project copies
  synchronize through the maintained script, without global installation.
- Integration advanced independently to bd9a6bb with nightly UI work (34aee49).
  Preserve it: checkpoint this work first, merge that integration head, then verify
  affected combined behavior before fast-forwarding and pushing. Remote was still
  2086a1a at inspection; no other session's working changes were present there.
- Merged independent nightly work without conflicts (8f191bf). Combined nightly
  and first-copy focused check: 10 passed in 6.66s / 9.9s; integration critical
  14 passed in 7.20s / 10.5s. Source interfaces and GUI/nightly behavior retained.
- Cross-feature inspection found the two new nightly banner flags were unknown to
  first-copy inventory. Reproduced through the existing release representative:
  unsupported KV scope, 1 failed before the fix (5.4s total). Classify only the two
  exact device-control keys; do not grant the nightly namespace. The same test now
  asserts no copied flag, unchanged original research and complete private history.
  Added an unknown nightly research key to the existing scope-rejection matrix.
- Final nightly-control/first-copy/unknown-scope slice: 5 passed in 9.66s /
  12.9s total. Final merged source critical: 14 passed in 8.66s / 12.2s total.
  Both retain the CPU governor and existing selector counts. No source data moved.
- Final combined docs/skills: 58 passed in 1.91s / 5.2s total; privacy, Ruff
  and CRLF-aware whitespace passed. Native builds must use this merged clean source.


## 2026-11-15: merged v28 native candidate delivered

- Clean f7616aede7154d16e1c017c102b7706f2b49ed97, 0.5.0.dev, run
  https://github.com/puddings-world/Paperfact/actions/runs/43677890610.
  One manual all-platform dispatch. Jobs Windows/Mac/Linux: 488/328/180 seconds.
  Draft skipped; no public release, cloud deployment or local packaging CPU.
- Downloaded and checked all three actual paperfact.packaged-acceptance.v1 reports
  against clean source identity, exact six sync flags, same-workspace handoff and
  38-tool CLI/MCP retry/restart. Mac arm64 verifies three reader starts; native
  foreground/close passes. Linux AppImage passes. Windows clean install, same-version
  reinstall/uninstall and research preservation pass; older-release upgrade and
  registry/shortcut checks remain explicitly false.
- Critical per OS: Windows 14 in 6.16s / 10.8s total; Mac 14 plus five warnings in
  5.06s / 8.6s; Linux 14 in 3.53s / 6.1s. First-sync representative: Windows 1 in
  2.72s / 5.3s; Mac 1 plus five warnings in 2.09s / 4.7s; Linux 1 in 2.39s / 4.2s.
  These are overlapping requirements, not 45 unique journeys. First-copy checks
  are source/native fixture evidence, not frozen GUI adoption or physical sync.
- Windows mobile artifact tests: 5 passed, zero failed. v28 artifact verified:
  50 files, 3927551 bytes, content ID
  49329abb66e39c5af92060436349a7b95afd57a78f90ac4a3c44df2183c6dea9.
  Built, not deployed. CI content identity is distinct from prior local checkouts.
- Artifact ZIP IDs/bytes/SHA-256 (not contained installer hashes):
  Windows 14147456214 / 184177049 /
  6b47030f3275036a6cb7cc5233833d551652943b35698a89c57f8a0e9c1f6c3a;
  Mac 14147686143 / 281483108 /
  362815127dd2cef026993d02fa2a29088a0b64638d31fcd671ddcb5415bc6b5b;
  Linux 14147710748 / 282190838 /
  de74aad78a524e4ed646f0df4386c32f15496f23195abe99634ee0b8e68b4db5;
  Mac synthetic fixture 14146878113 / 7617 /
  975dc2c46ae8465ed3708b9d4470a2535f40581551df33ae2d4a71e49e23f08c;
  mobile web 14147205901 / 884735 /
  9cabf3a629fa2bd6b8c19bb8ce9fdaf134dcaa327ccebe2365b16a71e8cf51b1.
  Contained Windows setup hash:
  2f362c68a83d11a426691a9a1f430ddf3ab0c2ad13dbb7fa15e9b9ebdb4f3d67.
- Small reports, artifact index and exact three job logs retained under ignored
  build/candidate-43677890610. Download guides/status/readiness/test map and the
  existing skill reference updated from actual evidence; documentation-only
  checkpoint reuses this candidate rather than rebuilding unchanged source.
- Candidate includes v28 mobile citations, context/graph work, first-sync complete
  compound/private-text history and independently merged nightly opener/banner,
  with its exact device-control isolation fix. Dev bundles do not auto-update.
  M01-M21, native vault/input/upgrade/coexistence, hosted HTTPS/device issuance/
  revoke/backup and phone durability remain not run. Full legacy/source mapping,
  runtime adoption, scientific/survey audit and persistent history guarantees stay
  incomplete. Curated release selection not run; no v0.5 release approval claimed.

- Documentation checkpoint validation: governed docs profile 58 passed in 2.04s
  (5.3s total), with privacy scan and Ruff passed. No runtime source changed after
  the verified candidate; critical/native packaging evidence is reused, not rerun.


## 2026-11-15: retain reading-only legacy text before first sync

- Found a maintained producer gap: fetch.extract_text writes canonical text files
  even when no compound analysis receipt exists. The first-copy inventory rejected
  those files. Existing enrollment_history now retains a closed private
  legacy_text_cache_v1 record for known unambiguous current-paper text/pdf names.
- Uses the shared bounded UTF-8/version/link-safe reader, preserves exact BOM/CRLF
  and hashes, skips paths already retained by compound history and enforces the
  existing aggregate budget at every addition. No new module, live table, daemon,
  active reader cache, original grant or shared text payload. Unknown paths and
  sanitized-owner collisions remain blocked. Desktop preview shows history-only
  text snapshots; preparation and source preservation use the existing worker.
- New normal/rejection behavior coverage plus strengthened existing release and
  desktop representatives: five passed in 15.36s / 18.5s total. After adding the
  per-addition bound and UI count: two passed in 5.35s / 8.8s total. Includes private
  copy/detached restore, no PDF/file grants or outbox text, invalid UTF-8, oversize,
  empty bytes, corrupt proof, source changes, ambiguous names and unknown files.
  Existing compound external-path and changed-byte guards remained green.
- Initial test-edit scripts stopped on mixed-line-ending assertions; no product
  test result was claimed. A new rejection fixture then omitted required paper
  fields, failed after one passing case, and was corrected by cloning the trusted
  fixture columns. No assertion was removed or weakened.
- Final critical: 14 passed in 7.58s / 10.8s total, privacy scan and Ruff passed.
  All checks governed: one at a time, max two logical CPUs, 25% job CPU, 300s budget.
  Historical full/release selections not run; no real account/model/research use.
- Source after f7616ae only. The delivered native candidate is unchanged and does
  not support this additional private protocol; native/physical acceptance and
  full runtime adoption, remaining mapping, hosting and history guarantees stay open.

- Documentation/skill consistency: 58 passed in 1.89s / 5.0s total; privacy and
  Ruff passed. Project copies synchronized without conflicts; no global install.


## 2026-11-15: opt in to continuous sync while joining a desktop

- The existing pairing/joining screen now offers one default-off checkbox for
  automatic sync on opening the exact new workspace. It is shown only with a
  remembered verified connection, frozen during work and saved only after fresh
  destination/device validation. Source workspace and its startup preference stay
  unchanged. Existing remember_joined adds an explicit Boolean startup keyword;
  it calls the existing native consent boundary, not a new credential protocol.
- Existing SDK and actual clipboard/pair/join tests now cover default-off and
  opt-in; the latter constructs a fresh ContinuousSync controller and proves
  reauthentication and research sync without another connection-button action.
  Four normal cases passed in the initial behavioral slice before the next case
  exposed a fixture mistake (not a six-case pass).
- The initial cancellation fixture tried to cancel a publication Ticket after its
  metadata publication. Ticket correctly treats that publication as final. The
  test now invokes the actual GUI Stop path while the worker is held at native
  save: it also cancels the connection generation. No assertion was loosened.
  Stop/native-save failure preserve the destination and prevent startup permission;
  retry of the same destination succeeds without another authority device.
- Two new failure/retry variants plus three existing queued startup close/permission/
  binding guards: five passed in 14.42s / 17.7s total. Both-language rendering,
  actual MainWindow startup and session-only manual joining: four passed in
  13.52s / 16.7s total. Actual en/zh-TW joined-screen images inspected under build/;
  the option fits and defaults off. Initial translation-literal formatting/syntax
  errors were corrected before these behavior results; no test ran on that red lint.
- All tests use fake native storage and isolated authorities. No owner credential,
  hosted deployment, installed Mac/Windows prompt or physical-device sync claimed.
  Existing candidate f7616ae does not contain this newer source change. No new
  runtime module, worktree, daemon, global skill or release selection was added.

- Final critical gate: 14 passed in 4.97s / 8.2s total; privacy scan and Ruff passed.
  No repeated historical/full run. Existing explicit-consent and generation-fence
  methods were reused; no new portable skill rule was manufactured.


## 2026-11-15: new native candidate includes reading caches and join consent

- Clean source cb6ca667b0a95f6d0f49a802bcba6415260d0fd6, 0.5.0.dev,
  https://github.com/puddings-world/Paperfact/actions/runs/43680889932.
  One all-platform manual dispatch; Windows/Mac/Linux jobs passed in 411/308/192
  seconds. Draft skipped, no public release, no deployment or local packaging.
- Downloaded all three actual paperfact.packaged-acceptance.v1 reports and checked exact
  clean source/version, all six sync flags, all three instance-handoff flags,
  four preserved PDF files and 38-tool retry/restart. Linux nested AppImage
  integration passed too. Mac arm64 reports three reader launches plus native
  Launch Services foreground/close. Windows install/reinstall/uninstall and
  research preservation passed; old-release upgrade and registry/shortcut checks
  remain explicitly false. A first ad-hoc Linux summary assertion omitted the
  documented nested AppImage result; inspection confirmed it and the exact
  per-platform expected report schema then passed. No product test was changed.
- Actual source counts: critical Windows 14 in 5.16s / 9.8s total; Mac 14 with
  five warnings in 4.86s / 9.6s; Linux 14 in 3.16s / 5.8s. Existing first-sync
  representative: Windows 1 in 2.85s / 6.1s; Mac 1 with five warnings in
  1.97s / 4.2s; Linux 1 in 1.88s / 3.9s. It now includes unreferenced private
  text beside citation/compound/PDF/graph, backup/restore and local nightly state.
  These overlap requirements and are source fixtures, not frozen GUI adoption.
- Windows mobile artifact tests: 5 passed, zero failed. The unchanged v28 web
  content identity is 49329abb66e39c5af92060436349a7b95afd57a78f90ac4a3c44df2183c6dea9,
  50 files / 3927551 bytes; built, not deployed. ZIP hashes may differ from the
  prior build while verified web content remains the same.
- Public artifact ZIP IDs/bytes/SHA-256 (not contained installer hashes):
  build-windows: 14148039099 / 184171385 /
  4a3db3042bab8c570dccfc6046df148bf7eb84a7a842730720cccf608ecca6fa;
  build-macos: 14147654648 / 279528381 /
  35ef668cfba9375d00e8a9dc498b47b5ebda0b843299ca70ab0745d5f5c3a73a;
  build-linux: 14148422443 / 282196771 /
  e576bc1f31a85c84650c8cbe2448446590734eb8fa31934a5ea25a3eb22fabe6;
  research-fixture-macos: 14148092535 / 7591 /
  3c0a0802743d19c88281b02ade314f522b5ab5615574b7d20c03cb65329dd17e;
  mobile-web-cb6ca667b0a95f6d0f49a802bcba6415260d0fd6: 14147853585 / 884735 /
  7373cf56f1b44f551a1f2f37d2e6613d3646db5c46408f48c30d52482de69c1b;
  Contained Windows setup SHA-256:
  6376ee6a080a2e0c22b30249d0cdee7f534c0015cc1147accbc9de3c56b8882f.
- Small provenance/acceptance reports, exact three completed job logs and artifact
  index are retained under ignored build/candidate-43680889932. A request for the
  Linux log while the workflow was still active correctly reported unavailable;
  the same run completed and the logs were retrieved afterward, without restart.
- Latest remote master checked at 1b44466a2aaf5a3ea17a3eba16f27777f0507a36 is an
  ancestor of this candidate (merge-base --is-ancestor exit 0). No maintenance
  merge is pending at that observed checkpoint.
- New packages contain private standalone reading-cache preservation and explicit
  default-off new-folder startup sync. Native packaging is not proof of the new
  GUI/Keychain journey on physical Mac; Windows source/Qt evidence stays scoped.
  Existing Mac guide M16 now distinguishes session-only and startup permission.
  M01-M21 physical acceptance, hosted issuance/backup/TLS, mobile durability,
  remaining adoption/mapping, survey audit and persistent history remain open.
  Curated release selection not run; no complete v0.5 beta acceptance claimed.

- Documentation-only checkpoint: governed docs profile 58 passed in 3.76s /
  7.1s total, privacy and Ruff passed. No runtime source changed after the
  candidate; critical/native evidence is reused rather than rebuilding.


## 2026-11-15: focal-only offline reading keeps annotation and Lineage originals

- Reproduced an actual gap by extending the existing three-source peer journey:
  selecting only the focal paper reported downloaded, but actual bound Lineage
  original inspection returned None for a related source. Pre-fix test failed in
  11.57s / 14.9s total at that missing-original assertion.
- OfflineService now validates closed current annotation and Lineage source rows,
  maps their actual workspace owners, and keeps exact native Lineage source/parent
  lifetime pins. Even the focal original needs its Lineage companion manifest;
  primary bytes alone do not supply that reading authority. Unknown/unavailable
  sources are not synthesized. Metadata work is bounded to 64 MiB and 256 original
  dependencies across the selection; current deck/PDF coverage stays intact.
- The existing guarded SyncSession passes exact planned artifact IDs to download
  and status, with source pins in its invalidation signature. Exact queries retain
  the bounded full scope rather than the old 200-file cutoff, and leave unrelated
  primary PDFs/decks alone. Missing original manifests and stale source pins now
  return partial rather than a false downloaded result. Global ordinary-sync
  transfer defaults and the live wire protocol are unchanged. No new runtime module.
- Affected evidence: initial source/peer slice 3 passed in 30.64s / 33.8s total.
  Final source/offline/selected-download/peer slice: 61 passed in 260.16s / 263.5s
  total, within the 300s governor. Many invalid-input parameters each rebuild the
  same full world in about four seconds; consolidate their side-effect-free setup
  later without dropping assertions. Do not rerun this unchanged slice by habit.
- The new reading-links variant first used plain SQLite, correctly rejected by
  paperfact_capture. CaptureConnection alone then correctly retained a stale
  candidate because deletion lacked an observation. The fixture now uses the real
  observe_content/observe_target/expecting transaction; no guard/test was weakened.
  That isolated variant passed in 4.77s / 7.9s total. Formatting failures before
  behavior execution were corrected and are not counted as application passes.
- Strengthened final peer representative: 1 passed in 33.30s / 36.6s total.
  Focal-only preparation makes all three bound original viewers usable without
  activating unrelated primary PDFs. Ordinary/resumable verification refuse a
  corrupt related original; missing manifest reports partial with count 1. A
  different native source pin with unchanged original bytes reports stale, rejects
  old cached verification and remains partial; restoring actual retained metadata
  restores readiness. The original whole-selection/history/retry assertions remain.
- Existing focused skill reference records this local evidence; project copies
  use the maintained synchronizer. No new portable rule or global installation.
  New behavior is source after candidate cb6ca66, not in the delivered Mac package.
  No real account, model, owner data, host, installed Mac/phone or public release.
  Remaining adoption/mapping, hosting/device and persistent-history gates stay open.

- Final integration gate: critical 14 passed in 7.13s / 10.5s total; docs/skill
  consistency 58 passed in 1.86s / 5.1s total. Privacy and Ruff passed in both.
  All local checks governed, one at a time. No historical full/release selection
  or native rebuild was repeated; existing candidate identity remains cb6ca66.

## 2026-11-15: mobile reading preparation, source after cb6ca66

- Existing engine/app now share one bounded single-paper plan: primary PDF,
  current owned deck/image closure, native annotation originals and exact Lineage
  source pins. Downloading never grants arbitrary URLs/snapshots; partial/unknown
  source versions cannot produce a complete result. Generation, paper/account,
  cancellation and metadata guards fence late delivery. Verified items survive
  retry and cached-only verification needs no transport. No new runtime module.
- Existing core engine/original/artifact checks: 56 passed, 0 failed, 1.1045s Node /
  1.266s governed total. New fixture errors (operation-ID collision, missing import,
  line-ending edit assertion and null-prototype comparison) were corrected before
  this pass; earlier failures are not evidence of success. Original assertions stay.
- Cache/component checks: 60 passed, 0 failed, 0.5108s Node / 0.641s governed total.
  Shell v29 intentionally invalidates v28 and retains research caches. Two existing
  fixed v19 expectations were updated to v29; no behavior assertion was removed.
- Actual JS client/Python loopback authority passed in 2.0s governed total including
  prepared target counts and retained PDF/deck bytes. Fixture accounts/data only.
- Isolated Chrome: actual preparation, one cached PDF, zero new outbox entries and
  EN/ZH 390px screenshots observed. Full end-to-end browser check did NOT pass:
  first two runs searched English while native locale was Chinese (11.546/11.563s),
  explicit user-agent experiment stopped at startup (11.0s), next reached screenshot
  checks but incorrectly expected immediate worker control (12.062s); after reload
  sequencing correction another run stopped at startup (11.421s). No product guard
  was relaxed; stop repeated browser runs and retain offline-reload as an open gate.
  Diagnostic files are isolated under build/offline-reading-browser-20261115.
- Existing skill ownership/context patterns already cover this change; no new
  portable rule or global skill installation is warranted. No owner research,
  real login/model, deployment or public release. Native candidate remains cb6ca66.

- Final critical gate: 14 passed in 7.05s / 10.3s total; docs consistency:
  58 passed in 1.81s / 4.8s total. Privacy and Ruff passed. All checks one at a
  time under max-two-processor/25% CPU governance; no exhaustive suite repeated.
- Local static v29 artifact built then independently verified: 50 files,
  3,932,964 bytes, ID 900fd28c8b5650f518116a794172c7a8f2ffafec5896e41c467711ed4df1a284.
  Build 0.531s, verification 0.219s governed. It is not deployed and does not
  update the previously delivered native/mobile candidate automatically.

## 2026-11-15: actual v29 artifact offline browser acceptance

- Previous turn made authoritative progress: ddd12cd implemented and integrated the
  offline-reading action. The repeated isolated Python-static-server diagnostic
  was not a pass. Changed diagnostic approach to Node static serving of the exact
  verified artifact, retained network/error output and localized label matching.
  Actual preparation, EN/ZH screenshots, fresh offline shell and transport-free
  verification then passed in 2.781s governed. This does not prove the sole cause
  of the earlier startup failures, which stay recorded above.
- Kept the reusable check inside existing mobile/browser-check.mjs, opt-in via
  PAPERFACT_TEST_JOURNEY=offline-reading. Existing fixture mode is unchanged.
  It checks rapid activation, one cached PDF, zero research outbox writes, actual
  language switching, no viewport overflow, 44px action height, distinct offline
  document identity and transport-free cached verification. No new default gate
  selector/test module, external service, account or research data.
- The maintained runner passed against v29 artifact
  900fd28c8b5650f518116a794172c7a8f2ffafec5896e41c467711ed4df1a284 in 2.953s;
  existing workspace-startup fixture also passed its eight named behaviors in
  2.813s. Both CPU bounded. Runner removes only the exact mkdtemp profile it owns,
  after browser exit; no prefix enumeration, other-session deletion or ACL change.
- Reviewed actual EN/ZH 390px screenshots; bounded results/screenshots retained in
  docs. Native/source provenance and device gates remain separate. No full suite
  or native rebuild needed for a test-runner/docs checkpoint; native candidate
  stays cb6ca66. No deployment or physical Safari/phone acceptance implied.

- Checkpoint gates after maintaining the runner: critical 14 passed in 7.89s /
  11.3s total; docs 58 passed in 2.01s / 5.2s total. Privacy and Ruff passed.
  Existing ownership/context and diagnostic-evidence skills cover the change;
  there is no new portable lesson to promote. No historical/full suite rerun.

## 2026-11-15: remove irrelevant attachment setup from no-write validation

- Previous turn progressed and integrated 76e427c; no pending process to restart.
  A scoped source audit still leaves persistent history/authority, remaining
  source/recovery mapping and runtime adoption as real product work. This checkpoint
  addresses the owner's explicit slow-test constraint before broadening that work.
- Confirmed the selected-download invalid-selection case spent 3.99s setting up
  two clients, PDFs and decks to test a rejection taking 0.02s; the offline invalid
  budget case spent 2.26s on setup. Two unchanged cases passed in 7.04s pytest /
  7.984s governed. This was measurement, not an application failure.
- Existing test_workspace_offline validation fixture now keeps real enrolled
  metadata, pending research and a verified native connection, without unrelated
  PDF/deck bytes. All input variants and assertions stay. Per-case preservation
  asserts exact database bytes, pending operations and zero network/blob calls.
  The no-write environment is module-scoped; mutating integrations remain isolated.
- Intermediate per-case lean setup: 21 passed in 25.00s / 25.921s total. Final shared
  no-write setup plus the unchanged full selected PDF/editable-deck and pin lifecycle
  representatives: 23 passed in 11.90s / 12.625s total. Validation setup took
  1.09s/1.02s once per module. Different selections; no invented speedup percentage.
- No product source, historical parameter/assertion, critical14 or release38
  selector changed. The test map explains scope; development docs now name the
  actual develop/0.5 integration line rather than superseded sync-foundation.
  No new generic skill: this is established fixture-isolation practice, with local
  evidence/limits recorded here. No owner data, paid call, deployment or release.

- Final integration gates: critical 14 passed; docs 58 passed in 2.06s / 5.5s
  total. Privacy and Ruff passed in both. One governed check at a time; no
  historical/release run, application rebuild or source behavior change required.

## 2026-11-15: freeze the next common native candidate

- Previous turn progressed: 8751ff6 integrated guarded no-write fixture reuse and
  current development guidance. No running check was restarted. The next common
  candidate will include selected annotation/Lineage originals and mobile v29,
  beyond delivered cb6ca66. A manual workflow dispatch creates test artifacts only.
- First curated release attempt failed honestly in 121.1s: Python 52 and frontend
  24 passed; mobile 95/96 passed, with the acknowledged-but-unreceived note fixture
  replacing *all* pull responses with an empty list. That now also erased the
  retained-frontier proof, which correctly stopped before upload. No product
  history guard was removed or changed.
- Corrected that existing fixture to delay only new tail delivery while serving
  the previously received prefix. All old content/dependency/reconnect assertions
  remain; new checks pin unchanged cursor, actual acknowledgment beyond it and the
  exact delayed request. Existing missing/different-history rejection still runs.
  Domain/engine 32 passed in 0.4096s / 0.546s governed total.
- Coherent curated release rerun passed: Python 52 (119.487s stage), frontend 24
  (0.402s), mobile 96 (4.860s), actual JS/Python protocol (2.016s), privacy/Ruff.
  Total 129.464s / 129.672s governed. Run ID d37894a58b804cafa0c99f38ebe04813,
  max two processors/25% job CPU, 1800s release ceiling. No full historical suite.
  This is automated source evidence, not installed/hosted/physical acceptance.
- Native candidate dispatch/results and exact build identity will be recorded
  only after the workflow reports them. No tag, public release or deployment.

## 2026-11-15: common native c1cbef2 candidate delivered

- Exact clean source c1cbef20d48d29e2767bed60a6393298819389d4, 0.5.0.dev,
  manual run https://github.com/puddings-world/Paperfact/actions/runs/43688772032.
  All three build jobs succeeded; draft job skipped. No release/tag/deployment.
  Existing run was observed throughout, not restarted on output delays.
- Native job durations: Windows 132734753245, 405s; Mac arm64 132734753036, 277s;
  Linux 132734753295, 189s. CI critical14: Windows 4.64s / 9.1s total;
  Mac 4.76s / 8.0s (5 warnings); Linux 3.40s / 6.0s. First-sync representative1:
  Windows 2.94s / 5.6s; Mac 1.79s / 4.0s (5 warnings); Linux 9.12s / 11.0s.
  These source/native fixture checks overlap with the local curated selection.
- Downloaded each acceptance/provenance report and checked actual JSON, not just
  green jobs: exact clean source/version, passed packaged-acceptance.v1, four PDFs,
  three handoff flags, six execution/restart/citation-graph flags and CLI/MCP38
  with retry/restart. Linux AppImage checks also pass. Mac arm64 three reader starts
  and mac-launch-services-foreground pass. An initial ad-hoc check wrongly expected
  host.os=Darwin; actual schema says macOS. Inspected raw values, then verified the
  exact macOS/arm64 contract without changing any product/test behavior.
- Windows install/reinstall/uninstall and research preservation pass in acceptance
  mode; older-release upgrade and registry/shortcuts checks explicitly remain false.
  Inner Windows installer SHA-256:
  a98fc54d353e4904ef0418e110ae2b609ed761f06dddcaa3b116b60aa65d7bad.
- GitHub artifact archives (not inner installers), all same run/source:
  Windows build 14151034252, 184240765 bytes,
  9daaf27636d8611e54e547d6437f011804101135df7ed8ee761f290807f81717;
  Mac build 14151871485, 279275526 bytes,
  4a6c33e2ec5158a3d87498989360ec5c69b74b67850f54b5138d0fadc29a1a81;
  Linux build 14150674932, 282204707 bytes,
  1240dad09bdb1c93558d1e84eba2ea218fab5b0018cba93d5c572111dce7f001;
  Mac synthetic research 14151756764, 7597 bytes,
  180bb10a10e223c86906fc46c9ea7b1f3b0bf2fb69747b1c9ad3e4576964749b.
- CI mobile archive 14151596876, 888231 bytes,
  e15fca4ef32368bc679ecd2b907573289e492feec98886abb94d3286898ed05f.
  Windows static-artifact tests5 passed0failed. Downloaded its real bytes and
  independently verified v29: 50 files/3940356 bytes, content ID
  6573854331ecc52eebe3e10d63d3901dc3aa8e2c4fe34bdfebd36755745b41eb.
  It differs from the earlier local artifact; do not substitute the older hash.
  Existing opt-in browser journey passed against this exact CI artifact in 2.953s
  governed: actual repeated action, EN/ZH touch layout, fresh offline document,
  transport-free cached PDF verification and unchanged research outbox.
  Latest bounded browser result now points to CI bytes; earlier local result remains
  described in preceding entries. No physical Safari/phone durability claim.
- Mac guide/current status/board/testing index now identify this candidate. Older
  cb6ca66 records remain historical evidence. Dev bundles require explicit replacement
  with the same isolated test data, not auto-update or daily-data migration.
  Remaining runtime/source mapping, persistent authority/history, survey audit,
  installed upgrade/input/native vault, live providers, hosted and M01-M21 physical
  journeys remain open. No new portable skill rule or global installation needed.

- Delivery documentation gate: 58 passed in 1.87s / 5.0s total, privacy/Ruff passed.
  This is docs after the frozen candidate, not a rebuild or another release-gate run.

## 2026-11-15: durable history prefix authority primitive

- Previous turn progressed: native c1cbef2 delivered; docs integrated as 8da477a.
  Verified clean worktree first. Continue the full goal; hosting/physical gates
  do not prevent this needed local continuity work. No agent/worktree/service added.
- Existing frontier comparison cannot distinguish changed earlier events when the
  last event is identical. New native history_page primitive demonstrably rejects
  that fork using a linked canonical-event digest. It is not yet a desktop/mobile/
  HTTP change and must not be claimed as full end-to-end authority protection.
- Existing sync_service now retains sync_history in the same event/head/graph
  transaction; duplicate/restart proofs remain stable. Explicit bounded legacy
  prepare_history resumes a prefix without rewriting events. Partial preparation
  refuses new event writes until complete. Reads use bounded ranges, not a full
  history scan per ordinary action. Exact Unicode/number event strings hash with
  a scoped seed and length-delimited bytes. No new runtime module or dependency.
- Backups verify optional full/partial history prefixes and reject altered/gapped/
  orphaned commitments without repairing source. Fresh-workspace recovery accepts
  the optional table, replays exact science/conflicts/bytes, computes a new scoped
  history and retains credential isolation. Original legacy backup compatibility
  remains; no owner workspace or deployed authority was opened/migrated.
- Formatting and one mixed-line-ending edit assertion were corrected before any
  behavior run; no red behavior result was hidden. Initial service/backup/fresh-
  recovery slice: 72 passed in 11.82s / 12.547s governed. Added explicit corrupt
  commitment backup checks and source/fresh-scope proof comparisons: three scoped
  representatives passed in 1.87s / 2.609s. Existing concurrent retry now also checks
  the single committed proof. All historical assertions retained; critical/release
  selector counts unchanged. No historical full suite or native rebuild.
- Next implementation must persist/validate proofs with actual receiver cursor
  transactions, carry them through bounded HTTP/browser/native transports and check
  mutation preconditions at the authority's write transaction. Durable identity/
  service fencing and recovery/adoption UX remain open. No new generic skill rule
  is justified until the shared client boundary is implemented and verified.

- Integration checks: critical14 passed in 7.98s / 11.4s total; strengthened
  concurrent-proof representative1 in 0.51s / 1.140s; actual existing JS/Python
  HTTP protocol passed in 2.063s; docs58 in 2.13s / 5.4s. Privacy/Ruff passed.
  Cursor bounds and conservative encoded-page delimiter accounting were reviewed
  before checkpoint; the relevant history slice is rerun for that final boundary.

- Final bounded history slice: 5 passed (35 unrelated service cases deselected) in
  1.19s / 1.922s total. No full/release rerun or package rebuild; delivered native
  candidate remains c1cbef2. The whole 0.5 goal remains active and incomplete.

## 2026-11-15: actual desktop verified receive and acknowledgment protocol

- Previous goal turn progressed: 51972ec retained backend commitments. Revalidated
  clean branch/board before edits. Delivered native c1cbef2 is unchanged; this is
  source after candidate, not a new package or completed 0.5 release.
- Actual SyncSession uses sync_verified_once with required history HTTP endpoints;
  legacy sync_once stays an explicit experiment API, never a fallback. Portable
  seed/step helpers live in existing journal module; no dependency/module/daemon.
  Bounded legacy replay matches real inbox records before persisting prefix and
  never initializes a higher proof from an opaque remote digest.
- HTTP history pull/push use existing identity/execution/body limits. Research
  pushes check retained prefix and unchanged tip inside the authority write.
  Genuine concurrent advance returns retryable425. Exact acknowledgment record
  strings avoid Python/JS number reserialization. Client verifies the next digest
  before acknowledging; wrong/unknown proof leaves intent pending. No mobile
  engine or attachment/device mutation guard is claimed connected yet.
- Receiver research/inbox/cursor/proof commit together. Matching own intents
  already received are acknowledged there, repairing a lost push response without
  trying to validate an obsolete reply. Unreceived acknowledgment/proof commit
  together through an additive trusted journal hook. A proposed file-tail rewrite
  was rejected by automatic review as potentially truncating uncommitted code;
  it was not executed. Safer additive changes retain the original acknowledge body.
- Initial four verified representatives passed (3.078s total). Affected native
  client/HTTP/journal/desktop files: 143 passed/1 failed in37.64s because an old
  assertion searched for push instead of push_verified; outcome/data assertions
  already passed. Updated only that trace plus asserted no legacy push. New race
  testing then exposed an already-received own intent still pending; fixed the
  production receive/migration reconciliation, not the expected outcome.
- Expanded verified cases: four passed in1.56s/2.281s; full continuity plus desktop
  session30 passed in15.27s/16.156s. Forged ack, actual HTTP concurrent writer,
  same-tail fork, no downgrade, malformed records and conflict retention are covered
  without multiplying parameter matrices or adding critical/release selectors.
- History progress now uses actual remaining counts in the existing connection
  area; partial preparation keeps last-success and caught_up honest. Qt observer
  initially assumed QLabel.textChanged, which does not exist; fixed the test to
  observe real setText values during actual worker execution. Its single journey
  then passed in2.48s/3.391s. No product workaround for this test error.
- Recovery initially treated the proof cache as derived/excluded, but that would
  lose an unreceived commitment not reconstructible from an operation/sequence.
  Corrected before checkpoint: explicit protocol schema retains proofs as inactive
  recovery_records; received points verify against inbox and unreceived points
  retain matching outgoing acknowledgment. Detached restore does not activate
  proof/device/connection authority. Existing recovery scenario now exercises a
  real verified acknowledgment followed by failed delivery and exact retained proof.
- Backend/recovery slice8 passed in3.50s/4.235s. Exact record-only acknowledgment
  format: verified4 passed in1.72s/2.406s. Final affected continuity/actual desktop/
  Qt/recovery/MainWindow-startup slice26 passed in18.87s/19.703s. All governed,
  sequential, isolated fixtures; no real account/model/research workspace involved.
- Canonical local-integration evidence records native-only applicability and
  limits; maintained project copies synchronized without conflicts. No global
  installation or new universal rule. Next: mobile proof persistence/routes,
  attachment/device mutation guards, legacy-unreceived-ack review/adoption UI,
  durable authority fencing, hosted and installed-device acceptance. No deployment,
  tag, public release, full historical suite or candidate rebuild this checkpoint.

- Final gates: critical14 passed in10.01s/16.6s total; docs58 in2.07s/8.6s.
  Privacy/Ruff passed. Actual existing mobile/Python legacy protocol passed in
  2.031s governed, preserving current mobile compatibility without claiming new
  mobile proof protection. Final diff whitespace check passed. Integration HEAD
  and origin were both51972ec with a clean integration tree before checkpoint.

## 2026-11-15: refuse completed history older than retained acknowledgment

- Revalidated clean stabilization and integration source at 91c2525. The
  receive transaction checked crossed acknowledgment hashes but did not
  reject a caught_up tail ending below an already retained acknowledgment.
- Added the check before any research/inbox/cursor/proof writes. Extended
  the existing lost-pull/restart journey: repeated direct refusal and an
  actual HTTP sync pass with valid preflight but a rolled-back empty tail
  preserve the exact database, accepted note and pending receipt; a later
  valid sync still applies the causal follow-up. No new selector matrix.
- Final affected file: 21 passed in 3.34s, 6.4s total with privacy/Ruff,
  under the single-check two-core/25-percent CPU governor. Initial guard
  checks passed too; the second run followed added actual-entry coverage.
- This refines the existing retained-ack invariant; no new global skill
  or additional background system. Native candidate c1cbef2 unchanged.
  Mobile durable proof flow, attachment/device guards, legacy review,
  durable authority fencing, hosting and physical acceptance remain open.
- Integration gates: critical 14 passed in 7.38s (10.7s total); docs 58
  passed in 2.11s (5.4s total). Privacy/Ruff passed in both. All checks
  ran sequentially with the same CPU governor; no full historical suite,
  packaging, paid call, account login or owner research access.


## 2026-11-15: mobile verified history and private recovery v3

- Started from clean common 8f017f1 in the existing stabilization worktree. The
  actual mobile Engine.sync now requires history_page/push_verified. Existing
  frontier checks remain additional semantic evidence; no legacy write fallback.
  Bounded local-inbox replay compares actual retained records; never seed a higher
  remote digest. A single 25-page foreground budget includes reception/preparation.
- Receive before upload; independently verify each next acknowledgment and retain
  newer accepted points across failed delivery/restart. Exact raw UTF-8 strings
  preserve native float/Unicode hashing. Safe-integer checkpoints reject rounding.
  Content/receipts/cursor/proof and acknowledged outbox/proof each save atomically.
  Generation/scope are rechecked after async reads and before requests/commits.
- First focused run: 41/44 passed. Three expectations still described the previous
  push-first flow: moved delayed-tail failures after actual acceptance and tightened
  the lost-response upload count from two to one. Original saved-content, causal,
  conflict, no-duplicate and retry assertions retained. The next affected set61
  passed in3.719s governed; expanded proof/recovery/transport47 passed in3.859s.
- Broader affected consumers initially153/154: initial seed persistence changed
  state during a cancelled held initial receive. Fixed the product by retaining
  the zero seed virtually until verified commit, rather than weakening the exact
  state assertion. Corrected engine/Lineage52 passed in0.735s governed.
- Private proof observations export under closed recovery v3/capability sync_history;
  v1/v2 shapes remain unchanged without proofs. Import/re-export keeps current and
  archived received/acknowledged observations inactive, with original outgoing full
  events. No active cursor/device/connection permission or old job is installed.
- Actual generic Chromium8 journeys pass in3.125s, including IndexedDB note/proof
  reopen, scope isolation, drafts/focus and linked saved research. Source-position
  browser initially failed because its proxy allowed only old routes. Added only
  history pull/push routes, retained authorization/instance headers and moved fault
  injection to verified push. IDs remain exact; retry receives accepted source
  without another upload. Added bounded partial-result diagnostics on fixture exit.
- Source-position journey then16/17: obsolete v12 cache name failed offline asset
  checks. Both position fixtures now inspect actual v30. Dialog journey11 cases
  passed but actual-app hook selected pairing's first primary button; fixed it to
  open Advanced manual connection and activate that fieldset's actual button.
  No product authentication shortcut or acceptance assertion was removed.
- Final actual position journey17 passed in23.125s governed, including real PDF
  workers, source-first/lost-reply behavior, independent native package/backup
  preservation, inactive recovery/review, offline fresh worker and scope bounds.
  Actual position dialog11 plus full-app PDF-card hook pass in14.906s. Cookie
  pairing/reconnect/forget4 pass in8.391s without browser credential exposure.
- Final explicit nine-file mobile selection156 passed in5.636s/5.796s governed;
  actual Python HTTP interoperability passes in1.969s, including equality between
  independently retained mobile prefix and authority checkpoint. Native exact-byte
  float/Unicode vector also matches; forged proofs, same-tail divergent prefixes,
  storage rollback, legacy mismatch, unsupported service, stale local reads and
  held responses retain actual notes/outbox. No critical/release selector expansion.
- One local v30 static artifact built/verified in0.562s:50 files/3944491 bytes,
  ID83c4877d149a6f54e2153a407c4065b6cbc1a1fd2cd3f1263f69a9e44d9e9382.
  Maintained exact-artifact offline-reading journey passes in2.547s: repeated
  activation, EN/ZH narrow touch layout, new offline document and cached-only PDF
  verification. Local evidence stays under build/mobile-history-v30-*; not hosted.
- Canonical local-integration evidence extended and maintained copies synchronized
  without conflicts. No global skill, daemon, task board, owner database, account
  login, paid call, native rebuild, tag, public release or deployment this checkpoint.
  c1cbef2/run43688772032 remains the delivered v29/native candidate. Attachment/device
  proof guards, durable authority fencing, native legacy-ack adoption/review, remaining
  mapping/recovery/survey and hosted/installed/physical acceptance remain open.
- Final integration gates: critical14 passed in4.74s/7.9s total; docs58 passed
  in1.93s/5.3s total. Privacy/Ruff passed in both. All executions sequential
  with at most two logical processors and the25-percent job CPU ceiling.


## 2026-11-15: attachment mutation history guards

- Continued from clean common89e89bc. Reused existing blob service/HTTP transport,
  desktop guarded transport and mobile original-source uploader. No new runtime
  module, worktree, daemon or task board. Device-control mutation guards remain
  separate; source after the delivered candidate is not a released installer.
- Added explicit history/blobs begin/append/commit/cancel routes with closed
  checkpoint fields. Legacy direct experiment methods retain their prior shape;
  actual desktop sync and mobile original-source upload always supply proofs.
  Unsupported verified routes stop rather than falling back to old mutations.
- Each authority write transaction verifies the retained prefix. Begin repeats
  after namespace persistence; commit repeats after bounded physical verification
  before ownership publication. A valid suffix advance can keep uploading; a
  mismatched prefix cannot change partial bytes/reservations or grant ownership.
- Native history/session30 passed in23.26s/26.3s total. First attachment selection
  stopped at an old-server fixture returning404 without reading the request; it
  now consumes the bounded body before the unchanged404 assertion. No production
  error or authentication behavior was loosened. A new test initially expected
  unavailable rather than the existing stricter authorization denial for unowned
  bytes; corrected that new assertion to PermissionError.
- Attachment HTTP plus actual desktop PDF/deck47 passed in13.01s/16.1s total.
  Extended the new case to compare exact database and physical-file snapshots on
  repeated refused mutations and to prove no legacy fallback. Final new HTTP plus
  both actual desktop journeys3 passed in10.32s/13.4s total. The desktop PDF test
  also requires nonzero retained checkpoints at actual blob admission.
- Several style gates stopped before executing tests for overlong newly written
  lines; corrected the source/tests and retained Ruff's existing limit. No check
  timeout or broad historical run. All executions sequential under the existing
  two-core/25-percent governor and isolated synthetic workspaces.
- Actual mobile Chromium source-position/recovery17 passes in23.078s, explicitly
  refusing legacy attachment writes and requiring the current proof on actual
  begin/append/commit. Its original operation IDs, deterministic small-body-only
  upload, independent desktop package/backup and offline source assertions remain.
- Affected mobile engine/transport/retention/position/recovery67 passed in3.633s/
  3.781s governed; real mobile/Python HTTP interoperability passes in2.016s.
  No release/critical selector expansion. Earlier local v30 artifact83c4877 and
  native/v29 candidatec1cbef2 are unchanged; source assets require a future matching
  build/deployment. No real account, paid call, owner research, tag or release.
- Canonical local-integration evidence extended; no new universal rule. Remaining:
  device-control guards, durable authority fencing, native legacy-ack review,
  remaining mapping/recovery/survey, hosting and installed/physical acceptance.
- Integration gates: critical14 passed in7.90s/11.0s total; docs58 passed
  in1.88s/5.0s total, with privacy/Ruff passed. Final whitespace review and
  integration-parent checks follow; no full historical suite or packaging.


## 2026-11-15: device controls, issuer-bound pairing and legacy proof preparation

- Continued from clean common828e73f in the existing worktree. Actual desktop
  device rename/revoke/create-invitation use read-only mutation_checkpoint and
  explicit history/devices routes. Authority validates prefixes inside writes;
  catalog/local Disconnect remain independent. No legacy mutation fallback.
- sync_pairings adds bounded canonical history_checkpoint. Existing seven-column
  authorities upgrade idempotently; backups/restores accept absent/old-seven/current
  schemas. Grants and invitations never transfer into a new recovered workspace.
  Issuance retries retain original prefix/expiry, including valid suffix growth;
  unproven old invitations require a fresh code. Issuer/scope is checked first.
- Fresh redemption and exact claim retries verify the issued prefix in the same
  admission transaction. Wrong history creates no device and leaves code unclaimed;
  correct recovery retries the same code. Existing admitted credential resume after
  expiry/revocation retains its prior contract; this is not durable control fencing.
- First native device/pairing selection:19 passed before one legacy test expected
  generic404 instead of the existing specific continuity-refusal type. Tightened
  that assertion to SyncHistoryUnavailable, retained unsupported-pairing behavior.
  Held spies forward checkpoint kwargs without changing duplicate/cancel assertions.
  Import/style gates were corrected before further tests; no test requirement removed.
- Device/HTTP/pairing48 passed in17.76s/20.8s total. Actual Qt device/pairing27 pass
  in54.10s/57.2s total, including singleton/repeated click, confirmation/cancellation,
  late connection and changed workspace, preservation, native-vault retry and join.
  New history refusal retains the proposed label/research and gives EN/ZH guidance.
- Actual cookie browser plus authority recovery13 passed in5.21s/8.2s total. New
  case changes issued history after browser preparation:412, no replacement cookie,
  no admitted device or claimed code; restoring correct prefix allows exact retry.
  Recovery covers pre-pairing, seven-column and current proof-bearing invitations.
- Found a genuine upgrade gap: an older beta DB could lack the proof table while
  attach_existing deliberately does no DDL. Explicit SyncSession.sync now calls
  prepare_history_checkpoint: create only an absent table at local zero; existing
  corrupt/missing rows refuse. Device action itself never migrates. Existing bounded
  preparation checks actual inbox before uploads; no higher remote digest is adopted.
- Strengthened the device journey with a real legacy accepted/unreceived operation,
  refusal while proof is incomplete, retained inbox reception, absent-table upgrade
  on explicit sync, successful control retry, and exact refusal after proof-row loss.
  Final this journey plus issuer-bound HTTP2 pass in2.81s/5.7s total. Earlier initial
  migration2 passed in2.91s/5.9s before strengthening the legacy scenario.
- Browser completion412 maps to sanitized history guidance. Bilingual pairing21
  unit/transport cases pass in3.172s governed; actual Chromium cookie pairing4 pass
  in8.531s using an invitation bound to the issuer's actual prefix, not a legacy
  unproven fake grant. No JavaScript credential persistence or automatic reload sync.
- Shell v31 replaces v30 as current source; old-shell purge test retains every
  previous isolation assertion. Final affected browser/shell/Lineage81 pass in
  3.654s/3.797s governed. One local static artifact verifies in0.515s,50 files/
  3945541 bytes, ID7bb89dcb3732d02a94b64f1bc6082c5485e85ec0e43a7252466e30461290505b.
  Exact-artifact preparation/repeated activation/EN-ZH touch/fresh offline-document/
  cached-only PDF verification passes in2.704s. Local build/mobile-device-history-
  v31-* only; not deployed and not a rebuilt native installer.
- All checks sequential with the existing two-core/25-percent governor. No critical/
  release selector expansion, historical full suite, real account/model/owner data,
  new worktree/module/daemon/board, public tag/release or cloud deployment. Canonical
  evidence extended, not a new global rule. c1cbef2/run43688772032 remains the
  delivered native/v29 candidate; later local v30 artifacts remain historical.
- Remaining: durable authority/control-history identity and split-brain fencing,
  native unreceived-legacy-ack review/adoption, remaining mapping/recovery/survey,
  production obsolete-writer policy, hosted and installed/physical acceptance.
- Final integration gates: critical14 passed in8.14s/11.4s total; docs58
  in1.90s/5.1s total. Privacy/Ruff passed. Final whitespace and clean-parent
  review precede checkpoint; no full historical suite or native rebuild.


## 2026-11-15: local listener ownership and database-lifetime refusal

Scoped continuation after2b3c17e; native candidate c1cbef2/run43688772032 remains
unchanged. No public release, deployment, research migration or new worktree.

- Reference HTTP listener acquires the existing OS-backed local job claim before
  bind, refuses a second same-database listener, releases failed startup safely,
  and retains ownership until admitted workers drain. Actual child exit releases
  the OS claim without deleting sidecars. Independent authority remains available.
- Closing interrupts incomplete HTTP headers. A held backend push still completes;
  lost client reply is sanitized, and retry of its original operation returns the
  one accepted event. Shutdown-only initially failed on the Windows makefile read;
  final detach/socket.close is tested against the actual blocked read, not a sleep.
- Initialized service pins an absolute database/native file lifetime and opens
  `mode=rw`. Actual replacement/removal refuses session/write with HTTP412 and does
  not recreate a missing database. Identity change before commit rolls back SQL;
  hard-link and unknown-native-ID fixtures refuse unsafe continuity. No claim of
  same-inode restore/ABA detection or distributed fencing.
- Second CLI serve is actionable, preserves exact authority bytes, and normal
  online backup verifies while the claim is held; only manifest/database are
  exported in the empty-attachment fixture, with no process-lock sidecar.
- Existing browser restart fixture now actually stops its old server before
  rebinding; opt-in fixture uses a separate authority. Original cookie, expiry,
  revocation and isolation assertions retained. All HTTP412 routes provide typed
  history guidance in desktop/mobile; no downgrade to old writes.
- Final affected Python122 pass in20.11s/23.2s total, selected mobile17 in3.281s,
  actual JS/Python protocol2.047s. Sequential existing governor: two logical cores,
  25-percent job CPU; no historical full suite. Initial harness `closing` misuse
  and Ruff failures were corrected, not hidden; final affected selection is green.
- No native installer rebuilt. Mobile v31 source changes transport semantics;
  earlier content pin7bb89dcb is historical, not an exact pin for this change.
  Windows local fixtures do not establish Mac/Linux shutdown or installed-device
  acceptance. Durable authority/control-history, anti-rollback/distributed fencing,
  legacy acknowledgment review, remaining recovery/mapping/survey and hosted/
  physical-device acceptance remain open.

- Final integration gates: critical14 pass in4.85s/8.2s total; docs58 pass
  in2.13s/5.2s total. Privacy/Ruff and whitespace pass. Historical full suite
  and native rebuild not run; installed/hosted acceptance remains open.


## 2026-11-15: candidate acceptance follows guarded sync

After9891031, the existing frozen protocol verifier now writes the synthetic paper
and exact citation graph through verified-history routes, independently checks
linked acknowledgment hashes, rejects an incorrect proof before same-operation
retry, and verifies the retained checkpoint after process restart. Existing exact
legacy-read graph/persistence/execution assertions remain. A duplicate packaged
listener must exit2 with guidance while the first still answers. No synthetic
credential/database is added to uploads; existing four exact logs remain.

Two negative verifier cases inject false acceptance of a bad proof/duplicate
listener and must fail; existing stale-execution/bad-header/lost-graph cases remain.
Affected verifier plus the six selected source lifetime journeys:30 pass in12.01s,
15.2s governed total. Candidate workflow runs those six explicit OS-sensitive
journeys with a three-minute cap before packaging. Daily critical14 and release38
selectors unchanged; no new test system or historical stress run. Actual Mac/Linux
CI remains pending dispatch, not inferred from Windows source validation.

Final pre-candidate gates: critical14 pass in4.63s/7.9s total; docs58 pass
in1.90s/4.9s total; existing release workflow contract1 pass in0.32s/3.5s
total. Privacy/Ruff pass. No historical full suite or installed-device claim.


## 2026-11-15: inspected355382c native candidate (run43705488673)

One dispatch for all platforms, clean355382c7557150c98aee08be7b6fd12ea8274791;
no tag/public release or deployment. Mac arm64 job3m07s and Linux3m25s pass.
Downloaded provenance reports have status=passed, passed=true, failure=null,
clean matching source, four preserved PDFs, CLI/MCP38 retry/restart and all ten
sync_protocol booleans true, including guarded history/wrong-proof/duplicate-listener
refusal and checkpoint after restart. Mac records three reader starts/foreground;
Linux records AppImage integration. Windows is live in Build at10:50:33UTC;
not declared passed or restarted. Current Mac guide supplies exact artifact links
and GitHub-reported archive digests, not a claim of local physical DMG execution.

Exact downloaded CI mobile artifact:50 files/3953007 bytes, shellv31, content ID
8b6f4eac84eeedabd025cfa2237cc18c3312a16834405313028e6f7263493229.
Independent verify0.218s; actual Windows Chromium offline preparation/repeated
activation/EN-ZH touch/fresh offline-document/cached-only verification2.641s,
under the existing governor. Prior7bb89dcb local pin and c1cbef2/v29 native run
remain historical. Physical M01-M21, hosted HTTPS/two-device, native vault/upgrade,
durable authority/control history and distributed fencing remain open.

The existing test guide now maps stages to concrete protected behaviors and limits;
counts are not a completion percentage. No new test harness, full historical run,
owner research access or broad cleanup. Preserve the exact live Windows run for
follow-up; a polling timeout is not permission to restart it.

Final run state: completed/success at10:52:37UTC; no failed platform or retry.
Windows job8m37s, source lifetime step passed, provenance clean355382c; downloaded
report status=passed/passed=true/failure=null and all ten sync_protocol booleans
true, four PDFs/CLI-MCP38. windows_installer records installed/reinstalled/
uninstalled/research_preserved=true and exact installed integration; acceptance
mode only, older_release_upgrade_checked=false and registry_shortcuts_checked=false.
Installer-file SHA256=e1886109ace62984b2fa7051fe93af90d2e99f632a2e041b55372ea0ce418a61.
Windows artifact14158518613; Mac14158073852; Linux14157614948; mobile14157644516.
GitHub-reported native artifact ZIP digests: Windows5c6b4c22b3161bc077ea400e41b43e7bdc4dac71784e937cd6cf2d59ae90bdc1,
Macd1631a62f180d7ef7ad066903dcf99c2ab546ebe9905b542f8c3c4adddb88641,
Linuxaef052afc5240ffb05dfd77d38e9acbd31af4ab0b0520170266de6c86b819ff2.
The small provenance reports and mobile assets were downloaded/inspected;
native installer archives were not locally downloaded or run on physical devices.
No source change or rebuild is needed for this evidence-only documentation update.

Final evidence-doc gate: docs58 pass in1.91s/5.0s total, Privacy/Ruff pass.
Earlier docs58 in1.78s/4.8s covered the interim live-run wording. Critical14
evidence reused from unchanged355382c runtime; no unnecessary native rebuild.


## 2026-11-15: explicit desktop legacy-history review/adoption

Source after6940c26; delivered355382c candidate/run43705488673 remains unchanged.
No rebuild/public release/deployment or research migration this checkpoint.

Old acknowledged-but-unreceived operations can now be compared through bounded,
resumable, read-only linked-history pages, matching every retained inbox event and
receipt operation/sequence. New opaque in-memory review inputs are never exported
or sent as a wire packet. Per-page progress uses actual sequence/receipt counts.
Guarded Session retains it only within this connection generation; existing single-
job admission, authenticated identity, live workspace and cancellation apply.

Existing desktop dialog reveals Review saved sync history only after a history
refusal. Completed review reveals Use verified history with default-No confirmation.
Adoption rechecks the service prefix/current local proof inputs and writes only
proof metadata; no research projection, cursor reset, outbox discard, attachment
work or automatic upload. Explicit Sync now performs subsequent receive/push.
A truly absent legacy proof table is created at adoption; corrupt existing evidence
is not reset. Core exact retry is safe; local evidence changes require fresh review.

Validation: initial4 new core cases passed1.09s/4.0s; strengthening missing-table
retry exposed an OperationalError on the second adoption. Fixed product schema
condition using current transaction observation; unchanged acceptance then7 passed
in2.76s/5.9s total. Initial Qt2 passed3.14s/6.3s; added Stop/retry coverage and
actual per-page progress. Full affected history/session/edge/dialog63 passed
44.15s/47.2s total. Strengthened existing success case adds a real received prefix
and compares every SQL row except intended proof metadata; all4 selected cases
pass2.35s/5.4s total. Initial Ruff import/line-width failures corrected; no historical
assertion weakened or skipped. Test additions protect distinct behavior boundaries,
not a new suite-size target.

Remaining: rebuilt native/Mac and physical/hosted acceptance for this source;
durable authority/control history, anti-rollback/fencing, remaining research
mapping/recovery/survey evaluation and complete installed multi-device journeys.
A matched old receipt cannot prove an unrecorded old outcome or missing research.
Cooperative capture/page budgets are not hard real-time OS cancellation. No new
worktree, runtime module, daemon/board, provider call or owner-data test.

Final resource review: retained proof inputs now store content fingerprints rather
than raw operation/event bodies. The evidence fingerprint budget is16 MiB (Python
metadata overhead is additional), with streamed per-record validation and the
existing100,000-row/cancellation/deadline bounds. The injected one-byte budget
refuses before writes;12 final core/session/Qt cases passed6.94s/10.1s before
this compact-witness refinement. Final refinement evidence follows below.

Final compact-fingerprint/budget core/session/Qt acceptance:12 pass in6.35s/9.4s
total, including over-budget refusal without writes. Earlier affected63 evidence
precedes the compact-witness refinement; no false exhaustive pass is claimed.

Final compact-witness integration gates: critical14 pass in4.83s/8.1s total;
docs58 pass in1.76s/5.3s total. Privacy/Ruff and whitespace pass. All checks
sequential/two-core/25-percent CPU bounded; no full historical suite or rebuild.


## 2026-11-15: official service closes unverified prototype mutations

Source after897cd7a. Official sync-admin serve always passes the strict policy;
no new CLI bypass flag or user setup. Old research/blob/device write routes return
sanitized412 after authentication/execution guard, including browser aliases.
Verified routes, session/catalog/event/blob reads and legacy-history review stay
available. Repeated denied writes change no SQL or partial transfers; guarded
writes/rename/retry remain accepted once. The low-level local reference factory
retains its documented experimental compatibility default; dedicated historical
mobile transport fixtures mark that mode explicitly.

Strict native new-device redemption/browser completion require invitation issuer
proof in the enrollment transaction. Legacy unbound invitation refusal creates no
device/claim; fresh verified issuance/retry succeeds. An authenticated browser can
resume without extra grants; revocation and cookie/tab/origin controls remain.
The real CLI/key restart fixture now issues its invitation through the guarded
route; original restart/device-count/key-isolation assertions are preserved.

Frozen verifier now requires a valid prototype push to be rejected before normal
guarded graph admission and adds prototype_writes_refused. A deliberate false-
acceptance case must fail. The initial source CLI test did fail: isolation removed
PYTHONPATH and the shared venv loaded Paperfact-develop, confirmed by an actual
child module path/signature. Source-only test children now explicitly select this
checkout, without changing frozen env filtering or global Python config. Initial
Ruff test imports/width fixed; the strict acceptance assertion was never weakened.

Final affected six files:145 passed30.07s/33.3s total. Exact delivered mobile v31
artifact8b6f4eac84eeedabd025cfa2237cc18c3312a16834405313028e6f7263493229
passes four actual Chromium UI journeys in9.031s against strict Python fixture:
singleton keyboard-ready connection, cookie pairing without JS secret storage,
offline note/reload/reconnect same device, ZH forget/cancel preserving research.
Native355382c/run43705488673 stays the delivered candidate; no installer rebuild,
public release, production deployment, paid call, owner research or account access.

GCP plan now distinguishes supported fresh-identity recovery from unsupported
same-identity SQL/disk rollback and sets the still-proposed control-journal/external-
anchor/client-fencing/crash-recovery acceptance requirements. Project/region/
hostname/budget/retention/operator and hosted/physical acceptance remain gates;
no independent anchor or durable control history is claimed implemented.

Final integration gates: critical14 pass7.47s/10.8s total; docs58 pass1.92s/5.4s
total. Privacy/Ruff/whitespace pass. No full historical suite or native rebuild;
all checks sequential under the existing CPU/time governor.


## 2026-11-15: pinned0.4.3 preservation and readiness reconciliation

Source afterbeb696a. Audit confirms origin/master1b44466 matches remote and is
fully merged (zero maintenance-only commits); no master merge was necessary.
Published release metadata:0.4.3/0.4.1/etc are previews,0.4.6 remains draft. Latest
public baseline0.4.3 resolves to3abdf434555583ca4a6827892d54b487e9e40671.
Readiness had stalecb6ca66 evidence and a historical ADR said enrollment UI did not
exist; updated references now distinguish current355382c artifacts, later source
and genuinely remaining hosted/physical/recovery gates without inventing passes.

Existing frozen verifier optionally accepts --legacy-source. CI now fetches and
archives only the exact old src/seed script, validates closure/Git blob bytes,
and creates synthetic old research with those writers. New CLI exports old schema,
runs the same init_db entry used by desktop, and exports again with no source
PYTHONPATH override. Private snapshot compares seven old table families/columns;
both package exports compare list/order/old research fields and PDF/deck bytes.
The source-format-only report explicitly leaves old binary install and GUI upgrade
false. No new runtime module/worktree/daemon; no owner install/data touched.

This reproduced a real OperationalError: old workspace had no list_reading_goals.
Fixed bundle export to treat only known absent extensions as empty, including
paper_annotation_known; existing non-table/malformed extensions still fail.
No source schema write is required merely to export old research. The regression
uses actual0.4.3 data, positioned Unicode note/Q&A, manual highlight, deep reading,
renamed list/read flag and edited canvas/speaker notes. Deliberate note/PDF/canvas
and exported-note corruption or a modified old source cannot pass.

Initial missing-schema export failed; retained synthetic fixture traceback located
the actual bundle query. Ruff/string-format issues corrected, not hidden. After
fix6 cases pass10.76s/13.9s; affected verifier/bundle/workflow41 pass27.08s/30.3s.
After adding actual schema init (and a valid old read/read_at flag), final7 selected
upgrade/schema cases pass16.86s/20.0s. Final broad/gate evidence follows below.
No historical full suite, native/OS old-binary upgrade claim, release or cloud
resource change. New CI stage is prepared, not yet a native pass.

Final upgrade guard verifies actual new tables after init (a zero exit alone is
insufficient) and requires every old exported field to remain present. The no-op
negative fixture initially fell through to its deck-damage branch; corrected only
that fixture dispatch while retaining the specific schema-initialization refusal.
Final affected verifier/bundle/workflow42 pass34.05s/37.3s total. Remote tagv0.4.3
independently resolves to the same3abdf434555583ca4a6827892d54b487e9e40671.

Checkpoint gates: two existing positive goal/annotation-capability round trips pass
in0.98s (4.2s stages); fixed critical14 pass7.22s (10.6s stages). The existing
docs gate passed5.168s stages/5.391s governed total. All are partial curated checks,
not the historical suite; CPU governor remained2 logical processors/25 percent.
No live test processes remained during the owner-requested CPU investigation.


## 2026-11-15: checkpoint3b344c7 native delivery and Windows archive failure

Committed/integrated/pushed3b344c77cbea449f22767f35d5475b6ae2672bfc, clean.
Run43714643158: Mac arm64 passes5m30s, Linux passes2m55s; Windows fails6m45s
at legacy-source-preflight after prior packaged research/protocol checks pass.
Downloaded actual Mac/Linux reports show passedtrue, failurenull, original0.4.3
research preserved before/after real initialization, seven old table families,
PDF/deck bytes unchanged and eleven sync protocol booleans true. Old binary/GUI
upgrade remains false. The Mac guide records exact new artifacts/hashes; no public
release/deployment or physical-device acceptance was performed.

Windows synthetic failure-detail.log identifies exact source-byte mismatch.
Reproduced in memory: git archive with core.autocrlf=true converts source LF to
CRLF; false preserves original Git blobs. Fix archive preparation with explicit
-c core.autocrlf=false; do not normalize accepted source or weaken hash checking.
Regression executes the actual workflow recipe under inherited autocrlf=true,
then verifies the complete pinned source closure; modified-source refusal stays.
Two affected cases pass3.12s/6.2s stages after a reported Ruff line-length fix.
No broad suite or successful-platform rebuild. A Windows-only candidate follows.

Downloaded mobile artifact has the same8b6f4eac84eeedabd025cfa2237cc18c3312a16834405313028e6f7263493229
content ID as the earlier offline-accepted v31. Existing byte verifier passes
50files/3,953,007bytes in0.219s governed. Initial shell quoting failed before
verification; corrected with stdin script, not a different acceptance rule.


## 2026-11-15: Windows follow-up accepted and screenshot evidence corrected

Clean4ee34278c463a25f6b40fc64e01b2286187c3c5e/run43715636579 passes7m34s.
Downloaded provenance records pinned0.4.3 old-format preservation true, actual
schema initialization, both exports and edited deck bytes unchanged. All11 strict
sync flags pass. Isolated installer install/reinstall/uninstall and research
preservation pass; old-binary upgrade and registry/shortcuts remain false.
Setup payload SHA25615c308826c35e64bc990d3d1541cd473864088d7a36cf5b00bf65376a27f6595;
GitHub artifact ZIP SHA256ccedd3f1135bdfa5ecc42aca43bf0282c2698f45e671a3ce43d475eac86e5e08.
The Mac guide distinguishes3b344c7 Mac/Linux from4ee3427 Windows; app runtime is
unchanged between them. No common-build, installed Mac, hosted or release claim.

Inspected actual Mac screenshot artifact: dive.png was uniform/blank. Existing
script pumped events a fixed number of times despite asynchronous saved-content
preparation and WebEngine rendering. Made the existing command import-safe and
wait for preparation idle, nonempty saved body and the exact rendered page with
fonts ready; timeouts are finite and a blank pixel surface is refused before save.
Screenshot CI alone now uses native Cocoa on Mac and documented --disable-gpu;
normal app graphics and runtime code remain unchanged. New helper cases cover
queued completion, timeout, blank refusal, saved image bytes and stale-page callbacks.
Initial Ruff spacing failure corrected; initial3 cases pass0.49s/3.4s stages.

Actual isolated Windows plain capture passes2.688s and was visually inspected.
Real WebEngine initially reports GPU context loss and the new blank guard refuses
its empty surface in10.016s. With documented software flag, real typeset capture
passes5.328s, visually showing saved explanation, formula and code blocks. Uses
existing public web assets only, isolated synthetic data/home and dead proxies;
no owner app, research, account login, model call or download. Native Mac screenshot
change remains unexecuted until a later coherent candidate. No new native build.

Final screenshot/workflow selection5 pass0.75s/3.9s stages; critical14 pass7.54s/10.8s
stages; docs58 pass1.80s/5.1s stages. Privacy/Ruff and whitespace pass. All local
checks sequential and governed; no historical full suite or additional native run.


## 2026-11-15: survey input lifetimes guard same-content recreation

Source afterc4edb7b. Inspection of research_generation._inputs('survey') found it
retained paper SQL/digest/order but not each input paper lifetime. Actual mocked
survey.write reproduction deletes/recreates an input with identical metadata and
retained analyses during the model call. Before the fix it publishes unexpectedly
(red1 in1.93s/5.0s stages); this is a publication identity failure, not a PDF check.

The existing captured input now includes each ordered member's existing local
paper lifecycle token. Current publication re-reads those tokens in its normal
transaction. Recreated papers keep the old survey intact and retain this output
as a candidate. Old pending observations without those tokens cannot automatically
publish; retry returns the retained candidate without another model invocation.
No source substitution, original hash, scientific support, new schema, public
protocol field or provider behavior is invented. Unchanged rendered prompts and
normal generation remain unchanged. The complete portable survey evidence ledger,
statement quotations, original transfer, recovery and UI remain open.

Affected9 cases pass10.78s/14.0s stages: exact prompt, same-content input recreation,
metadata/membership/order/dive/list changes and workspace-switch isolation. Three
additional affected cases pass5.44s/8.6s: old pending context remains a candidate,
actual enrolled generation/edit reaches an independent peer, newer edit wins.
All use synthetic workspaces/fake providers under the existing sequential governor.
No native rebuild, owner research access, model call, deployment or public release.

Checkpoint gates: critical14 pass7.19s/10.4s stages; docs58 pass1.93s/5.3s stages.
Privacy/Ruff/whitespace pass. Critical/release selector lists remain unchanged.


## 2026-11-15: source-aware survey record and owned-original engine

Source afterd4a4ff7. Added focused survey_content/survey_sources business modules,
reusing closed claim primitives, actual workspace DocumentReader, sealed evidence
snapshots and deterministic quote verification. No new table, protocol, user action,
background service, model call, download, native build or research migration.
The complete persistence/sync/package/recovery/UI workflow remains unimplemented;
this checkpoint is the record/corpus boundary, not a substitute release scope.

survey.evidence_inputs projects only the frozen actual full-prompt/per-paper digest,
ordered inputs/titles and real lifetimes. Its first test exposed that .inputs hides
_members; fixed the producer to read its private frozen data, not today's database.
Provider-facing .inputs now also hides private paper lifetime observations. Actual
normal prompts and same-content recreated-paper refusal remain verified (13 cases
4.27s/7.6s stages at that intermediate point).

Closed1MiB record: exact prose/digest pairing, independent paper/lifetime/hash source
identities, missing/unselected source states, per-statement quotes and model metadata;
no account fields or semantic-proof claim. Strict duplicate/nonfinite/budget/foreign
source and page checks fail whole records. Local inputs and model metadata do not
constitute receiver ownership; future publication needs retained original/mapping
proofs. No legacy evidence or native grants are manufactured from old plain prose.

Actual PDF capture/verification has process-sealed capabilities and defensive report
copies. It keeps old original snapshots after file replacement but current() refuses
publication readiness. A model cannot submit its own checked location. Current
managed registration wins over a conflicting legacy alias; equal-byte distinct
owners are not interchangeable. Capture/verify/cancel/budget failures leave SQL
unchanged. Hash large private contexts for capability sealing, rather than charging
their raw bytes against the smaller public report budget.

Initial Ruff line lengths were corrected. Initial PDF fixture wrongly assumed a
pdf_path column; inspected the real reader/tests and used the maintained per-paper
PDF directory convention instead (no schema added or assertion loosened). First3
actual-PDF cases pass4.50s/8.0s stages; final4 including managed registration and
capability-type/budget handling pass6.75s/11.1s stages. Latest coherent contract,
retained input and real-PDF selection15 passes4.95s/9.0s stages. Final critical/docs
evidence follows. No full historical or real-provider/installed-device acceptance.

Final integration gates: critical14 pass8.13s/11.7s stages; docs58 pass2.01s/5.7s
stages. Privacy/Ruff/whitespace pass. Source-only checkpoint; no exhaustive suite
or native build. Canonical source-engine evidence copies synchronized normally.


## 2026-11-15: durable survey originals through existing atomic archives

Source aftera705cea. Added the closed private survey source-observation owner kind
to the existing atomic source-pair storage; no second file warehouse or research
schema was created. Each record hashes its paper/lifetime/hash plus list/lifetime
and generation request. Validation stays in survey_content, so archive metadata
does not import the AI dispatcher. Malformed owner-format types fail ValueError.

survey_sources.retain_originals requires an actual sealed checked proposal. Each
PDF/receipt is published together using the maintained fsync/stage/rename seam.
Group cancellation can leave complete unassociated pairs; retry reuses exact
records/bytes without duplicate observations. retained_originals requires the
complete expected association and verifies actual stored files. Wrong list tokens,
forged receipt data, raw report dictionaries and corrupt archived files fail;
corruption is never overwritten as a retry shortcut. Canonical SQL/outbox and
active reader state remain untouched. Survey receipt cannot authorize a claim
original even with an otherwise matching paper owner; added explicit exclusion
alongside the existing Lineage corpus guard.

Actual managed original (with a different legacy alias) is retained correctly.
Replacing/removing current a.pdf cannot lose its captured original. Independent
detached backup includes exact bytes and owner record, restores them as inactive
recovery provenance, and creates neither active source nor sync identity. Source
receipt consumers (enrollment, outcome packaging and claim staging) were inspected;
actual focused existing receipt/Lineage/claim regression13 passes22.50s/26.8s stages.
New retained-original cases3 pass5.79s/12.5s; initial native/detached2 pass4.98s/8.5s.
Final coherent retained/native/detached5 pass9.04s/12.3s after pure-validator and
malformed-owner handling. SQL dump remains unchanged in archive-only actions.

Publication sizing decision: operation limit256KiB is below report limit1MiB.
Do not force inline report JSON into ordinary survey rows. Next extend the
existing verified artifact path with explicit list ownership, keeping prose and
source ledger in one body, selected paper lifetimes and receiver bindings explicit.
Original assets must precede canonical publication; body/original availability
remain distinct. Canonical report persistence, typed peer/bundle/recovery, AI
workflow and UI remain open. No native rebuild, real accounts, paid call, public
release or cloud resource change. Final critical/docs evidence follows.

Final checkpoint gates: critical14 pass8.34s/12.2s stages; docs58 pass2.05s/5.8s
stages. Privacy/Ruff/whitespace pass. Canonical evidence copies synchronized;
critical/release selectors unchanged. No full historical suite or native rebuild.


## 2026-11-15: native list-owned survey artifact seam

Base6b7bf46; existing stabilization worktree/branch only. Preserve owner data and
installed releases. Added a distinct list-file namespace and closed survey manifest,
with no fake paper ID or change to existing paper/deck/original identities. Complete
report JSON lives in a verified blob, not the256KiB journal envelope. Actual native
paper/original lifetimes are bounded input dependencies, not structural parents.
The body retains prose and evidence together; source-state gaps remain explicit.
Native service admission checks active original lifetimes in its transaction.
Source outcome waits reuse the existing Lineage receipt loop and still require
actual received outcomes; upload and acknowledged-only states are insufficient.
Materialization creates survey.json only and rechecks the exact active list owner.
It never activates or claims offline availability of the source PDFs.

New tests initially exposed fixture mistakes (old list fields, reusing producer
statement IDs, missing blob upload, then accidentally publishing the report before
source retirement). Corrected those to use actual contracts and keep the report
pending until the intended stale-source publication. No production guard or old
assertion was weakened. Final assertions exercise actual accepted peer report
bytes, incomplete originals, corrupt bytes, closed owner/workspace/source pins,
service conflict and delayed delivery after list retirement.

Commands: scripts/check_bounded.py --profile focused --python with explicit
selections. Initial coherent survey4 plus existing Lineage readiness14:18 pass
102.61s,109.7s stages. Final survey5 plus existing actual deck/original peer
journeys2:7 pass32.12s,39.0s stages. Critical14 pass13.03s,20.0s stages; docs58
pass4.01s,11.8s stages. Privacy/Ruff pass, whitespace checked. All checks sequential
with2 logical CPUs/25% job cap/300s wall limit; no full historical suite or build.
Maintained critical14/release38 selectors unchanged. Existing canonical skill
evidence records local boundary reuse; generated copies synchronized.

This is not a trusted canonical survey publisher. Derive publication bindings
from sealed captured proposals and actual native mappings next, then make the
canonical reference/receipt atomic. Bundle/recovery mapping, mobile artifact codec,
desktop/CLI/MCP and AI workflow are still pending. No new UI action is enabled;
installed Mac/Windows candidates are unchanged. Hosted authority/fencing, GCP
deployment and physical cross-device gates remain open. Collaboration uses only
the existing board/Git; no new worktrees, jobs or cloud resources.


## 2026-11-15: trusted native survey publisher and offline completion

Base245535c; no new worktree, store, daemon or user action. Native observations of
report absence/version and captured source mappings now enter the process-sealed
pre-dispatch corpus. Unenrolled read-only source captures still work; they cannot
publish native artifacts. Preparation uses actual owned originals and their atomic
archives, stages verified blobs off-lock and derives native bindings from SQL
mappings. Model JSON cannot supply portable ownership. Existing paper original
publication is reused. Selected retired originals/report require explicit review.

Caller-owned publication rechecks actual context, report and original lifetimes.
Its savepoint covers every original grant plus the report/outbox; an exception
caught by the caller removes only those writes, preserving prior observed note
edits. Exact retries reuse the same current operation, including after received
service acknowledgements. A competing report or retirement is not an idempotent
success. Local publish materializes after commit outside the SQL lock; interrupted
materialization leaves a durable pending intent. Completion can reattach from disk
and use verified local bytes without the old PreparedSurvey or network. It checks
current desired report/list/source lifetimes and native database identity again
before activation. Staged bytes or detached originals alone cannot grant authority.

A new recovery-race test made an actual same-binding SQLite replacement during
materialization:1 expected failure3.92s,9.1s stages. Before the guard the replacement
received activation. Pinning/rechecking native database identity fixes that path.
This local admission/delivery guard does not solve durable remote authority rollback
or copied-host fencing; those existing release gates remain open.

Initial publisher5 pass12.76s/20.2s stages; publisher6 plus directly affected
missing/cancel/managed-source3 pass25.33s/33.8s stages. Exact acknowledgement retry
6 pass22.96s/30.7s; disk-reattachment6 pass20.82s/26.2s. Final frozen publisher/
recovery7 pass18.66s/24.9s stages. Earlier fixture correction used the existing
observed-note edit contract; no guard or historical assertion was weakened.
All via scripts/check_bounded.py --profile focused --python with explicit
selectors, one check at a time,2 logical CPUs/25% job cap/300s budget. Critical14/
release38 selectors unchanged. Final critical/docs and integration follow.

The publisher stores the canonical list-owned artifact/reference, leaving legacy
plain list_surveys unchanged. Trusted internal APIs are documented in analysis-audit.
Durable stale-proposal review, bundle/recovery identity mapping, mobile artifacts,
common CLI/MCP/UI and AI dispatch remain open. No owner research/credentials or
installed packages were touched; no public release/build or hosted resources.

Final frozen gates: critical14 pass7.89s/13.6s stages; docs58 pass3.56s/8.3s.
Privacy/Ruff/whitespace pass. Canonical evidence copies synchronized. No full
historical suite, installed-device run, native build, public release or cloud change.


## 2026-11-15: independent mobile saved-report reading

Base1827493; existing stabilization/integration branches only. Added strict
list-owned survey manifest/body support to the existing mobile domain and artifact
cache. Receive checks active source lifetimes for accepted publication, without
waiting for bytes. Bound metadata never claims original PDFs are cached. Complete
body validation retains the existing1MiB report/200KiB prose and256KiB operation
limits; whole-record asynchronous SHA-256 leaves synchronous claim hashing bounded
at220KiB. Exact source/statement/report/prose IDs and canonical integer JSON agree
with native output. Integrity scope is report_bytes_and_record; quote locations
are retained producer evidence, with semantic validation explicitly not_performed.

Engine.survey reads saved content offline; existing artifact downloads remain
shared, authenticated, resumable and quota bounded. Projection exposes active
list-owned surveys independently of decks and originals. List-overview cards read
cached reports, offer download/progress/retry and separate PDF status, fold excerpts
under statements and lazily populate source inventory. Research text stays literal.
Current list/engine/render-generation guards suppress navigation/account/close
results. Shell v32 includes both modules and replaces v31 code while preserving
research caches. Existing shell version assertions were advanced with the intended
cache change, adding v31 to stale-cache coverage rather than dropping prior checks.

A synthetic actual native publisher creates a report above256KiB with located and
explicitly unlocated excerpts. Independent HTTP mobile receive/download tests
interrupt after one chunk, resume at the exact offset, verify the entire ledger,
reopen without transport, keep original PDFs unavailable and hide cached access
after owning-list retirement. No model/account/cloud/research upload is used.
Fixture setup corrections aligned with existing journal/client initialization and
required paper fields. The final method inventory includes existing local
begin_session and authenticated history_page: neither writes research. All recorded
requests are read/auth/history/ranges; the phone outbox remains empty.

The explicit full mobile runner now includes the survey protocol check; its fixed
program inventory and a failure-propagation assertion cover that addition. Curated
critical14/release38 lists are unchanged. Ordinary focused CLI correctly rejects
mobile/tests paths; selected Node commands use the existing Windows governor API,
not a widened harness or an exhaustive run. One job at a time,2 logical CPUs/25%
cap/90s command budget. First artifact/original/shell38 pass2.719s (3.062s governed).
Final grouped reader/codec/old artifact/original/shell/build/runner52 pass15.073s
(15.375s governed); actual native HTTP journey5.094s. Final Unicode native fixture
(Chinese plus supplementary emoji) passes6.844s, app module syntax0.266s. Critical14
pass12.27s/20.6s stages; final docs58 pass4.95s/11.3s. Privacy/Ruff/whitespace pass.
Canonical evidence copies synchronized. No full historical/mobile sweep or native
rebuild. Build-contract tests create and verify actual allowlisted assets locally.

This is source and local fixture acceptance, not native browser visual acceptance,
deployed shell, Safari/iOS/Android durability, real Mac/phone use, cloud authority
fencing or a public release. Existing delivered packages stay unchanged. Plain
legacy surveys remain source-unknown. Package/recovery mappings, durable stale
proposal review and AI/desktop/common CLI/MCP creation are still open. Existing
board/Git provide handoff; no new worktree, task board, daemon or cloud resource.


## 2026-11-15: portable survey closure and detached-restore owner fix

Base4b35801; existing stabilization tree only. Internal survey_packages collector
reads actual native report/original grants, explicit inverse paper mappings and
verified immutable bytes without SQL writes. Metadata is bounded before loading
paper rows. The portable body carries exact historical research plus declared
package-paper bindings, never a sender operation/device/workspace writer. Selected
originals use per-owner derived paths; PDF budget64MiB, report1MiB, wrapper3MiB,
metadata8MiB. Strict actual ZIP metadata and namespace/file closure checks retain
missing-source states and independently verify every located quotation against
PDF pages. A rehashed false located quote fails; unlocated passages stay unresolved.
No original fallback, path following, import grant or model/network call occurs.

Tests use the actual trusted survey publisher. Initial6 pass14.00s/21.7s stages;
final contract6 (including case-aliased reserved namespace refusal)12.51s/19.3s.
The collector/codec remain internal, intentionally not hooked into public bundle
buttons until receiver mapping/persistence, bound/unbound transaction and re-export
are complete. Existing public bundle behavior is unchanged; no silent new-capability
import or synthetic generation context is introduced. Existing board records the
next receiver boundary rather than opening a second plan/store/daemon/worktree.

Actual backup/restore reproduced KeyError: paper_id in _detached_files (expected
red1,5.19s/11.7s stages): the old applied-file materializer assumed all owners were
papers. An explicit survey branch validates closure and preserves the full body,
original PDF objects and native mappings as inactive objects/recovery_records.
It does not invent a paper, current survey row or active source/device. Existing
generic blob reference/authority-backup paths were inspected; deck materialization
remains on its original branch. The regression checks actual independent restore
and exact archived mappings, absence of live sync/source authority, and original
backup bytes. The maintained unreviewed detached-reexport refusal is preserved;
reviewed reattachment remains required, with the original archive retained.

Final package/recovery7 plus existing editable-deck recovery1:8 pass12.65s/16.9s
stages. Fixed critical14 pass7.74s/11.8s stages; docs58 pass2.31s/7.1s stages.
Privacy/Ruff/whitespace pass. One bounded job at a time,300s/2-core/25% governor.
Critical14/release38 selectors unchanged; no exhaustive suite or native/mobile
build. Canonical local-integration evidence synchronized; no new global rules.

Still open: actual package receiver matching and persistence, atomic bound/unbound
import/re-export with user-owned identities, reviewed survey recovery and stale
proposal UI, common AI/desktop/CLI/MCP dispatch, hosted authority/fencing and
physical Mac/phone/Safari acceptance. No installed app, owner database, credential,
public release or cloud resource was changed. The full0.5 objective remains active.


## 2026-11-16: explicit existing-owner survey receiver

Base9c6dc9b; same stabilization tree and integration board. Internal
survey_package_import validates the actual ZIP and seals explicit receiver
list/paper identity observations, selected archive version, database identity and
device binding. It stages verified private report/original blobs off-lock, creates
fresh receiver native source pins, and publishes originals/report/outbox under a
caller-owned savepoint. No fake AI proposal, implicit enrollment or sender device
authority. Default preserves current content without research writes; explicit
replacement retains native history. Retry reuses the exact native intent and
post-commit materialization can use the existing durable pending completion.

Eight behavior groups cover independent peer receive/re-export, failure after a
real source grant, cancellation/caller rollback, changed targets/archive, invalid
mapping/proof, preserve/replace previews, request reuse/foreign database refusal,
and a report whose originals are all unavailable. The last case reproduced
KeyError: survey_sources when the optional empty inventory was omitted; using its
specified empty default fixes it without inventing original ownership. The peer
fixture was corrected to use its actual registered version directory. No prior
expectation or selector was weakened.

Final focused run e9f3f994e3a7475a83c670466a48342a passes: selected tests28.476s,
privacy2.903s, Ruff0.219s; total31.69s, governed31.922s, returncode0. Report selection
is only tests/test_survey_package_import.py. Its terminal handle is gone and both
matching run-ID reports confirm completion. This is not an exhaustive suite pass.
One governed check at a time;300s/2 logical CPUs/25% hard cap/lower priority.

Public PackageImporter new-list/new-paper planning still uses prospective graph
roots before actual SQL rows exist; it cannot call this existing-owner preparer
directly. Integrate validated portable data/native payload building within its
single root/source/report transaction and existing action receipt; do not commit
roots early. Unbound storage/re-export, public bundle capability wiring, reviewed
reattachment and UI/AI/common dispatch remain unfinished. No native rebuild,
production upload, real provider call, daily research write or new worktree.

Integration critical14 passes8.19s (12.3s stages); documentation/skill consistency58
passes2.25s (6.3s stages). Privacy/Ruff and whitespace pass. Selectors unchanged;
no full historical suite or rebuilt installer. Tests remain sequential and bounded.


## 2026-11-16: compound enrolled survey package import

Base52ae59b; existing stabilization folder/board. The package validator now
recognizes strict survey_evidence metadata/reserved paths and lists report files
with a list owner, distinct from paper-owned originals. Ordinary archives without
the extension retain their earlier validation/import path. A sealed immutable
survey_package_native frame carries checked report/source bytes, not sender
operations. Prospective-root payload construction derives the receiver's actual
list/paper/original lifetimes; apply rebuilds against same-transaction source grants.

PackageImporter now owns root creation, membership, source/report publication,
local materialization activation, outbox and its existing receipt in one transaction.
Injected failure/cancellation after actual report application roll everything back;
retry succeeds. No research writes occur during preparation. Default preserve,
explicit replacement/history and exact receipt retry are verified. Existing-owner
mapping still needs confirmation. No new receipt system, fake AI context, early
root commit or implicit enrollment is introduced.

New compound6 cases initially pass19.54s/26.4s stages. Adding existing report
preserve/replace yields7 new cases. These plus existing package_import/bundle checks
pass51 in70.03s (75.7s stages), one governed job,300s/two logical CPUs/25% hard cap.
The first check stopped at three new overlong source lines; only line wrapping
was fixed. No test expectation or critical14/release38 selector was weakened.

Normal export does not yet emit the new extension. Local-only import explicitly
refuses before research/file publication and preserves the original ZIP; its
persisted report store, enrollment mapping, reader and public export/re-export are
next. No completed public sharing workflow, new native installer, hosted service
or physical acceptance is claimed. Existing deployed/daily research is untouched.

Final critical14 passes8.93s (15.1s stages); docs/skill consistency58 passes3.94s
(10.2s stages). Privacy, Ruff and whitespace pass. No exhaustive historical suite
or native rebuild was performed. These fixture results do not replace the open
Mac/Windows/mobile installed-device and hosted acceptance gates.


## 2026-11-16: public survey sharing without enrollment

Basec8ea528, same tree/board. Public bundle export now collects saved native or
receiver-local reports, full exact originals and source-paper context. The common
strict ZIP contract validates exports before atomic replacement. Local-only import
stages originals through the maintained immutable receiver evidence cache, observes
pre-stage parents/current report, checks same-ID paper identity before writes, and
publishes local source associations/current report beside roots in the existing
bundle transaction. No sender writer, fake AI request or implicit enrollment.

research_local_surveys stores bounded canonical local versions with list/database
lifetimes and source associations; replacement retains historical rows. Exact
retry returns unchanged without duplicate versions. Local source grants never
become primary PDFs automatically. Export checks all paper fields before reading
bounded context and rechecks their fingerprints, original byte versions, actual
current associations and list lifetimes before publication. Native-to-local and
local-to-local independent receivers retain exact report/PDF data using fresh
native local ownership. Source-complete surveys explicitly require included PDFs.

Backup recognizes local versions as protocol data and retains exact PDF objects;
independent detached restore leaves all report/source records inactive. Public
list export now refuses retained detached survey reports until reviewed
reattachment, rather than silently dropping them. Existing detached native-report
coverage gains the same guard. The compound test's temporary local-only refusal
is intentionally replaced by the now-supported successful import; no assertion is
removed to disguise a failure.

Initial local5 failed at final export after JSON serialization changed tuple file
versions to lists. Canonical comparison fixes the representation mismatch without
refreshing hashes or weakening mutation checks; local5 then pass9.14s/14.7s stages.
A larger five-file selection timed out (run93c2ee1907264e7aaaee27f0bb2a4718,
307.391s governor/return124). Stack samples were in SQLite identity/connection
initialization, and a brief process sample does not establish CPU saturation or
root cause. The bounded process is terminal and its reports mark timed_out; it is
not a pass. No process restart on observation timeout or unrelated process kill.

The next diagnostic changed scope: one existing shared package journey passes6.08s
(7.797s governed/60s ceiling). Changed local/compound/portable survey files then
pass22 in92.58s (106.5s stages) under300s/two cores/25% hard cap. Eight local groups
cover public roundtrips, original tamper, replacement lifetimes, complete context
bounds/final staleness, exact retry, post-publication rollback and inactive backups.
Fixed critical14/release38 remain unchanged. Existing package/bundle regressions
are checked separately instead of rerunning the timed-out combined selection.

This is source data-path acceptance, not completed source-aware desktop UI/AI
creation, first-enrollment mapping, reviewed report reattachment, durable service
authority, a new native package or hosted/physical-device acceptance. Daily research
and delivered release files remain untouched; no public release/deployment.

Existing package_import/bundle44 pass130.76s (137.2s stages) as the separate
bounded selection. This closes the earlier combined-selection regression evidence
gap without hiding its timeout or broadening historical test selectors. The
process inventory showed no remaining bounded pytest job after timeout; unrelated
MCP/app/assistant/voice processes were not terminated. No saturation/root-cause
claim is derived from cumulative process CPU counters.

Final critical14 passes11.68s (18.4s stages); docs/skill consistency58 passes3.38s
(8.5s stages). Privacy/Ruff/whitespace pass. No native build, exhaustive historical
suite, installed-device or hosted-provider check was performed. All checks ran
sequentially; final scoped passes supersede the earlier incomplete combined run
for these exact inputs, while the timeout remains recorded above.


## 2026-11-16: saved-report desktop reading and exact original pages

Baseadb0daa; same existing worktree/board. Shared survey_reader reads actual
native/local reports without writing research. Report bytes are verified off-thread;
PDF hashes/pages/located quotes are verified only on explicit inspection. Sealed
content, exact original ownership and database/WAL/report byte observations protect
read/delivery. Native metadata can show a retained applied report while an updated
version awaits bytes. No AI, network, activation or source substitution.

The first normal native read failed currentness. Diagnostic evidence showed
signature=True/proof=True and unchanged DB metadata, but absent WAL became a
zero-byte WAL during read-only opening. Normalize only absent/empty WAL; retain
nonempty WAL and full DB/file guards. No retry, sleep, weaker source hash or
write-capable connection masks the failure. Reader7 pass9.09s/13.0s stages,
including actual changed metadata/replaced DB refusal and pending-update reading.

SurveyDialog now separates its existing editable summary from a saved Report &
sources tab. Source-aware content selects initially unless the reader already
chose a tab or is editing. HTML-escaped statements, literal quotations, missing
passage labels, source inventory and exact-page previews retain explicit semantic
limits. Legacy edit/generate controls are hidden for saved evidence; they do not
rewrite it. Refresh and per-pane cancel are visible, one worker deduplicates jobs,
workspace/list changes suppress delayed delivery, and close drains cancellation.
The old job-result path can reopen its disposed pane and selects the editable tab.

Actual Qt UI8 plus old3 initially pass23.74s/27.6s stages. Initial screenshots had
missing glyphs even for English: the bare QApplication fixture omitted production
style/font setup. Using actual startup Fusion/style and shipped fonts gives
readable EN/ZH screenshots, visually inspected. No font download or global setting
change. Visual review also removed a duplicate notice, retained the ampersand in
the Qt tab label, and added clear original/page status and explicit cancellation.
Final UI9 plus old3 pass25.55s/30.3s stages, including list as well as workspace
switching and cancel-then-retry. Formatting-only failures were fixed before test
execution; no historical expectation was removed. Final English synthetic screenshot
is maintained under docs/images/saved-survey-sources.png.

All tests are isolated, one governed job at a time,300s/two logical CPUs/25% cap.
No historical full suite, native rebuild, real provider call, daily research write,
public release or deployment. Structured AI creation, first-enrollment mapping,
reviewed report reattachment, durable authority and hosted/physical-device gates
remain open. This checkpoint proves source/Qt behavior, not installed-device parity.

Final focus review reproduced an actual active-job race: saved-report completion
selected tab1 while a legacy overview job was running, hiding its status. The
single-case60s governed repro fails in3.922s (index1 versus expected0). Auto-select
now respects active/queued jobs as well as reader tab choice and editing. The case
passes with final UI10 plus old3:13 pass30.03s/35.4s stages. Existing assertions
remain; no new fake job/model invocation is used. The maintained screenshot remains
a synthetic local fixture, not the owner's research or an installed Mac capture.

Final integration critical14 passes8.00s (12.2s stages); docs/skill/link consistency58
passes3.58s (7.7s stages). Privacy/Ruff/whitespace pass. Critical14/release38 selectors
stay unchanged. No exhaustive historical suite, native rebuild, daily-app restart,
installed Mac/device or hosted-service acceptance is claimed.


## 2026-11-16: first-enrollment saved-survey preservation

Basec47b522; same tree/board. Source inspection found local surveys were archive-
only during enrollment and history identity fell back to absent request_id, so
multiple versions shared None. Existing history now keys local rows by version_id.
The current local report is captured through an actual sealed owner export and
converted into the maintained portable frame without a fake AI context. Native
candidate publication derives fresh list/paper/original lifetimes. Old rows and
source receipts stay private archived data, not sender/device authority.

The new inventory compares stable report content/digests rather than process-local
proof IDs; existing SQL/file inventories still guard source changes. Shared source
bytes remain immutable/deduplicated with existing bounded limits. Only current
reports gain native heads. Report staging is off-lock; metadata/outbox/activation
share one checked transaction within the isolated candidate. Original source grants
were already made in that private candidate. Existing final directory/backup
publication owns all-or-nothing exposure. No source database rewrite or automatic
adoption/connection/upload occurs.

New8 initially pass43.00s/52.0s stages, including actual reference peer and EN/ZH
coverage. The first peer fixture passed an operation dict to download instead of
its required entity ID; this was corrected without wire/API changes. Adding an
all-unavailable source case first exposed fixture use of the strict artifact JSON
decoder on ordinary pretty package metadata; it now uses ordinary metadata JSON,
retaining strict canonical report/body validation. The single missing-original
case passes7.77s (9.266s governed), with old bytes archived but no new native grant.
No existing assertion or supported source policy was weakened.

Final selection: new9 plus six named old journeys (normal research/private controls,
primary PDF/backup, empty workspace, imported claim originals, Lineage and real Qt
preview/prepare/open).15 pass79.96s (81.171s governed),300s/two logical CPUs/25% cap.
Existing check_bounded.execute runs the explicit pytest nodes; critical14/release38
selectors are unchanged. No job overlaps another. Source and candidate byte/quote
checks, source/backup rollback and independent peer data are actual fixture evidence,
not just callback dispatch. Native paths, private credentials and old local epochs
are not promoted into wire authority.

Runtime adoption/connection, real native key stores, installed Mac/Windows and
physical phone/hosted acceptance remain separate gates. Source-aware AI generation,
stale-result review and reviewed report reattachment remain unfinished. No native
rebuild, release, real AI/model call, cloud resource or daily-research change.

Final integration critical14 passes10.26s (16.7s stages); docs/skill consistency58
passes2.67s (8.9s stages). Privacy/Ruff/whitespace pass. No exhaustive historical
suite or native build; the candidate/backup and independent peer tests do not
replace installed-device, runtime-adoption or hosted-service acceptance.

## 2026-11-16: captured-account source-aware survey generation boundary

Implemented `survey_jobs.SurveyJob.capture/generate` over actual generation
observations and sealed original snapshots. The new worker uses the survey task
route/global selection once, passes the frozen settings to the existing facade,
accepts only a bounded closed sections/statements/passages response, and records
requested versus actually reported model identity. It never accepts model-supplied
checked locations. Private original/receipt retention is reused and checked on
retry; no canonical SQL publication occurs in the generation method.

Ten affected behavior tests cover: captured route/byte input/provenance and cached
retry; duplicate activation plus provider failure/retry; pre-call cancellation and
late cancellation without another completion; pre-call/during-call input changes;
malformed/duplicate/extra-key/oversized JSON and invented checked locations; empty,
edited and over-budget inputs without inference; interrupted original retention;
actual native publication/read/exact-page inspection and older-proposal refusal;
explicit unselected originals/unmatched quotations; and corruption refusal on a
completed retry. All model completions are simulated and PDFs are synthetic.

Initial static checks exposed overlong new fixture strings. The first behavioral
run exposed a new-test mistake: semantic_validation belongs to the report, not
the statement. The new assertion now reads the existing report field; no existing
assertion, codec, selector or verification rule was weakened. Final affected check:
10 passed15.17s,21.9s stages, governed300s/two logical CPUs/25% job cap. Earlier
eight-case run passed12.18s/16.8s before the evidence-gap/corruption cases were added.
Counts overlap. No concurrent test job or exhaustive historical run.

This internal boundary does not yet replace desktop/CLI/MCP legacy dispatch.
Unbound publication and durable stale-proposal/review recovery remain unfinished.
An in-memory checked response plus durable PDFs is not a durably saved response.
Installed Mac/Windows, physical phones, native credential stores and hosted gates
remain open. No native build, release, owner-data change or real AI call.

Integration critical14 passes10.78s (16.1s stages), including package/PDF
preservation, notes/Q&A, configuration isolation, offline conflicts and recovery.
Per-list reading-goal context is another required generation input not yet captured
by this internal survey seam; it must be added with stale-goal publication guards.
Docs/skill consistency58 passes2.68s (7.6s stages); privacy/Ruff pass.

## 2026-11-16: publish generated reports in unbound workspaces

Implemented survey_local_generated.prepare/publish, consuming actual sealed
survey proposals. Source capture now observes the local current report as well
as native report state. The job refuses changed local reports before inference.
Preparation reuses version/source storage directly, without a fake import or
generation context. A process proof binds the proposal, staged originals and
explicit replacement intent. Publication rechecks original inputs/lifetimes,
database identity and local target in its transaction. Exact accepted retry is
read-only, and a superseded old report is never reactivated. Existing local
source receipts describe byte ownership, not an invented foreign import action.

Seven new local behavior cases plus existing generation10/local-package8 pass:
25 in45.61s,49.2s stages, governed300s/two CPUs/25% hard cap. Added pending global
workspace-switch case passes separately1 in1.87s/2.844s governed60s. No source
code changed after the25-case pass. Eight new cases cover saved reader/exact PDF
page/export, duplicate retry, before-AI and post-staging target changes,
preserve/default plus explicit replacement history, proof tampering, failure and
cancel after actual SQL publication with rollback/retry, corrupt/missing originals
and switching the global workspace without retargeting the captured write.

The initial combined run failed1/passed10 because the new report observation
changed an established stale-input error message. The first targeted raw-byte
edit then failed its anchor due to mixed line endings; the shell incorrectly
continued and repeated the unchanged failing selection (failed1/passed10).
The next edit verified the actual region, handled its mixed endings and checked
the edit exit before testing. Reordering code preserved the old error/assertion;
no existing test or accepted behavior was weakened. These failures are not passes.

The saved current report is durable; a completed proposal that cannot yet
publish still lacks durable cross-process review/recovery. Desktop/CLI/MCP
dispatch and captured per-list goal context remain required. No native build,
paid AI call, owner-data mutation, hosted deployment or installed-device acceptance.

Integration critical14 passes9.07s/13.5s stages; docs/skill consistency58
passes2.52s/6.8s stages. Privacy/Ruff/whitespace pass. No exhaustive run.

## 2026-11-16: capture and retain each survey's research goal

Actual goal rows now join survey input observations, with bounded text/version
reads. Existing plain-text prompts and the structured worker use captured goal
text. Recipe v2 adds required goal metadata; closed v1 reports stay readable
without invented historical purpose. Native/local stale guards reject changed
goals. Saved readers show literal historical purpose; package export retains it.

The first new behavioral run passed1/failed1: clearing an unset goal is an
existing no-op, so the new fixture now performs a real set-then-clear sequence.
No existing goal behavior/assertion changed. The expanded run passed57/failed1
in74.19s (79.6s stages), exposing the prior checkpoint's incorrect assumption
that no loaded native adapter meant an unbound workspace. Local observation now
returns no writer eligibility when binding is registered; read-only managed
capture still works, and generation/publication refuse unobserved writes. The
existing real managed-PDF test now additionally asserts both publisher refusals,
generation preflight and unchanged SQL. No old assertion was weakened.

Final affected selection (new goal6, existing jobs10/local publisher8/
observations38):62 pass51.22s,56.6s stages, governed300s/two CPUs/25% hard cap.
The new file's first static check caught an overlong SQL string and stopped before
tests. Mobile codec/view/shell10 pass in1.016s governed; actual native Python ->
authenticated HTTP/mobile report check passes5.578s, including a real Unicode
goal in a >256KiB report, exact resume and offline restart. These ran sequentially
inside one180s budget. A source inspection corrected double-escaped Unicode in
the new fixture before this run; the passing fixture uses actual Unicode text.

Named Qt report/source reading (native/local, EN/ZH) plus first-enrollment with
independent peer:5 pass21.64s/22.625s governed120s. No source changed after these
passes. Shell changes deliberately advance v32 to v33; the existing upgrade test
now explicitly requires old v32/v31 shell removal and unchanged research caches.

Installed Mac/Windows, physical phones, service/mobile hosting, runtime adoption,
durable control authority and completed-result review remain open. The saved
goal is historical metadata, not semantic evidence or a new source/write grant.
Structured desktop/CLI/MCP dispatch remains pending; the existing plain-text
survey flow already consumes captured goal text. No release, owner-data mutation,
paid inference, credential change, or deployment.

Integration critical14 passes8.46s/16.1s stages. Docs/skill consistency58
passes3.55s/32.5s stages; privacy scan accounts for26.4s of the latter.
Privacy/Ruff and CRLF-aware whitespace checks pass. No exhaustive run or build.
Owner feedback: finish this bounded checkpoint; prioritize connecting existing
end-to-end user flows and a coherent candidate over adding further isolated seams.

## 2026-11-16: desktop/CLI source-aware report workflow

Report & sources now starts the existing private queued CLI handoff with captured
Survey route, expected report ID and confirmation. The shared execute worker
retains checked scientific output and exact original receipts before native/local
publication. The existing recovery namespace recognizes archive-only survey
contexts; --retained returns report JSON without AI/write. Cooperative completed
cancellation retains without another completion call. In-app reapplication and
hard-termination/exactly-once billing guarantees remain open.

Parent initialization now precedes reader work; a lost read version permits one
fresh snapshot, then stops under continuing changes. Existing byte/owner guards
remain. UI14 cases passed before the next file's Windows replacement fixture
failed: an open startup lease blocked physical replacement before its handler.
That fixture now waits at most5s, keeping all no-job/no-write assertions.
Remaining selection passed22 before the new enrollment fixture failed; canonical
PDF/settings layout plus explicit PDF mapping preserve the original unknown-file
refusal. Worker13 pass18.66s/21.9s stages; its corrected final cancel/enrollment
case passes1 in1.95s/2.625s governed. Read-only retained CLI case passes1
in1.75s/2.532s. These selections overlap, not one whole-suite pass.

New desktop native/local flow passes2 in9.88s/10.813s governed, covering cancel,
duplicate activation, captured private route/args, close, actual publication and
result reopening (only child IPC completion is simulated). Deterministic
mutation/continuous-change cases passed in UI14. A temporary diagnostic observer
collided with the instance QTimer name and failed after24.734s; no repository code
came from that observer. Other stopped anchor/static runs were not passes.
No existing assertion was weakened or historical test removed.

Critical14 passes8.20s/12.2s stages. All runs use isolated/synthetic data and
two CPUs/25% cap, without real inference or owner-workspace changes. A coherent
preview build is next; installed Mac/Windows, physical phones, runtime adoption,
hosted deployment, durable authority and retained-result review still gate v0.5.

Docs/skill consistency58 passes2.57s/22.6s stages (privacy17.9s).
Privacy/Ruff/CRLF-aware whitespace pass. Installed native focus and provider
authentication are not established by offscreen/simulated checks.

## 2026-11-16: coherent three-platform preview delivered

Run43754647228 completed successfully from clean88595d332eaf36d911e3d15521e8d3f07ae976ca.
Windows7m44s, Mac arm64 5m48s, Linux2m25s. Three downloaded small provenance/
acceptance reports identify the same clean beta-candidate source and pass.
Mac checks three Cocoa reader starts/foreground. Windows checks installed version,
reader/integration, reinstall and uninstall; research remains. Both retain
packaged0.4.3 format initialization/export preservation and strict sync protocol.
Linux includes AppImage integration. Actual old GUI-binary upgrade, physical
devices, live providers and hosting are still separate gates.

Artifacts: Mac14177314884, Windows14178142192, Linux14177398894; exact ZIP sizes/
GitHub digests and Mac instructions are in the guide. Big installers were not
downloaded or independently hashed locally. No public release/tag or auto-update
was created (draft skipped). One TLS observation timeout and one early report
file observation failed; the same run was re-polled/read, never restarted.
Only delivery documentation changes after88595d3; no candidate rebuild for those.

Delivery docs/consistency58 passes2.47s/6.5s stages; no runtime changes
after the exact source candidate and no redundant installer rebuild.

## 2026-11-16: bounded candidate evidence audit

Re-read all three downloaded build-info.json and frozen-acceptance/report.json
files for run43754647228. Each records clean commit88595d3 and passed=true.
The report files are nested under frozen-acceptance; their absence at the
provenance directory root does not mean the evidence was lost.

These checks do not exercise source-aware report generation through a frozen
CLI against a model endpoint. Source fixtures cover that behavior, but the
installed/frozen new-report path remains an explicit acceptance gap.

An authenticated API download of Windows artifact14178142192 was stopped by
a45-second subprocess deadline after703,470 bytes of the184,546,969-byte ZIP.
The incomplete ignored download is not an installer and has not been hashed,
extracted or executed. No network cause is established. No build or test was
restarted, no real account/model was invoked, and no daily install/data changed.

Next frozen report check: extract the complete verified candidate into an
isolated folder without installing it; use synthetic research and a loopback
model response. Require a saved report, located original quote, captured versus
returned model identity, retained-result reading and cached retry without a
second model call. Keep the private desktop handoff check separate from a direct
CLI invocation. Until these run, do not claim frozen new-report acceptance.

## 2026-11-16: completed AI result browsing and correct check source

The existing saved-report pane now reads this list's validated retained survey
results on its one background executor. The selector shows captured time/model;
rendered goals/statements/quotations remain literal. Archive mode has no original
links, saved-report capability or write action. Current report restores normal
reading. No new model call, background service, worktree or owner-data change.
Reviewed reapplication, archival original inspection and frozen/provider/device
acceptance remain open. Candidate88595d3 predates this UI; no rebuild was started.

Initial static checks stopped on new callback bindings and one line length.
An affected run then passed12 before a native retry fixture timed out; diagnostic
selection passed both retry variants before exposing a missing list_retained.
Actual module paths proved the shared virtualenv was importing the develop tree,
not this checkout. Those runs cannot certify this change. The runner now prepends
its own src to child PYTHONPATH, preserving extra paths afterward. Two new cases
exercise actual Python imports against a synthetic conflicting module, with and
without an inherited search path. No existing assertions or selection were weakened.
This source-binding lesson is recorded in the canonical development guide;
no unrelated portable skill or global installation was added.

Correct-source affected UI/worker/check-runner selection:85 pass99.41s pytest,
103.0s all stages. A proposed optional screenshot/selector polish stopped on a
mixed-line-ending anchor before changing files; its following seven new UI cases
passed18.35s/21.7s stages, but no screenshot/polish claim is made. The verified UI
cases cover EN/ZH literal goal/quote retention across reopen, no extra inference,
current-report return, empty archive, failure/retry, repeated activation,
cancellation, workspace-switch delivery and close/drain. The API also refuses
observed database replacement. No aggregate whole-suite claim is made.

Integration critical14 passes8.10s/11.6s total; documentation consistency60
passes2.47s/5.9s total. All use the bounded two-CPU/25% governor. No exhaustive
historical suite, installer rebuild, real provider call or deployment.

## 2026-11-16: exact retained-original inspection

The existing SavedReport seal now distinguishes an owned recovery-file version
from current canonical content. Retained report text opens without PDF parsing;
source inspection checks its atomic private receipt/PDF pair, hash/page/quote and
final versions. It never substitutes the current primary PDF. Archive mode cannot
start regeneration/login; both publication preparations reject the read-only value.
Current report returns to normal reading; reviewed reapplication remains open.

Affected reader/UI/worker49 pass144.83s pytest/148.2s all stages. Added publisher
refusal and in-flight receipt-change assertions then pass7 in8.74s/12.0s; these
overlap the earlier49. Critical14 pass8.16s/12.1s; docs60 pass2.25s/6.0s.
Two static runs stopped immediately on new overlong source literals/decorators;
the existing assertions were not weakened. Prior archive UI expectations changed
explicitly from no source action to exact verified archival inspection, as required
by the retained-result workflow. Tests cover current-PDF replacement, report and
receipt corruption, missing/corrupt originals, changed workspace and mutation
during rendering. Exact SQL dumps remain unchanged and no extra model call occurs.

This reuses the existing archive-versus-writer separation; the canonical skill
reference records the verified case, without adding a new skill/global install.
No daily research/account, real inference, background service, build, release or
deployment changed. Native88595d3 predates this source; installed/physical/hosted
acceptance and reviewed reapplication remain separate gates.

## 2026-11-16: confirmed retained-report application and test diagnosis

Use this report now prepares the existing verified local/native import and asks
with a default-Cancel plain-text confirmation. Goal/model/source data remain
historical; the current list goal and previous report versions are preserved.
No model/login/download occurs. Real widget tests include cancel then confirm,
repeat clicks, goal/workspace changes during confirmation and close-before-write
with exact owned-stage cleanup. OS temporary staging stays outside research data.

Manual-review admission checks the archive seal/file and actual original owner,
not the historical whole-database/WAL read stamp. Current report/goal are captured
separately; established import target checks and the bounded goal check share the
write transaction. The strict saved reader and its source checks remain unchanged.
Unrelated UI settings survive without invalidating the review. Exact retry is an
acknowledgment; old retries cannot reactivate over newer reports. Same original
workspace/list/paper lifetimes/members are required; detached mapping stays open.

Diagnosis evidence, not a complete pass: backend12 passed24.7s stages; initial UI
waits failed. Thread capture located pending apply in Windows file_change checks.
Governed40-observation probe: qWait2.125s versus yielding below1ms; counterbalanced
native-warmed yield/Qt/yield was0.015s/0.860s/0.015s. The Qt helper now pumps events
and sleeps5ms to yield Python execution, keeping the same8s deadline/assertions.
New UI8 passed19.2s stages. Later combined runs exposed archive admission based on
an expired global DB/WAL snapshot (now replaced by explicit logical review intent),
then an existing native read false-invalidated after unrelated fixture GC.

The latter now has a deterministic GC regression: proof bytes stayed valid while
WAL disappeared. The shared sync fixture had used a transaction-only SQLite context
without closing. Both fixture connections now close explicitly, with SQL behavior
and expectations unchanged. Native/local GC cases pass2 in7.4s stages after the
fix; before it the native case fails immediately after GC. No production file
version guard was loosened. One tool creation attempt never started because
approval review timed out; the permitted single retry created the intended check.

Final combined selection90 passes141.74s pytest/145.4s all stages, governed300s,
two CPUs/25% cap. This covers saved-report UI, new review UI/backend, saved-reader
and shared sync-capture fixture tests. It is an affected selection, not the whole
historical suite or release acceptance. Initial anchor/static/fixture failures and
partial passes are not counted as successful verification. No owner research,
credentials, paid inference, daily app, native build, release or deployment changed.
Candidate88595d3 predates this source; installed/device/hosted gates remain open.

Final read-seal tightening binds the actual archived/current memory fields, not
only their stored signatures. Expanded backend/UI24 pass44.78s/48.3s stages,
including altered-read refusal without SQL writes. These overlap the earlier90.
Final critical14 passes7.53s/11.1s; docs/skill consistency60 passes1.98s/5.2s.
No runtime source changed after these passes. The pending in-app finish-activation
entry is explicitly retained in the release-readiness gates.

## 2026-11-16: pinned pending-report completion in the desktop

SavedReport now seals its exact desired native operation, separately from the
applied version used for display. Missing applied state is pending too. Finish
saved report uses the existing executor and local completion backend, with no AI,
authorization, network or new source/report operation versions. Expected operation
and original database identity are checked inside admission; registered roots,
owners and activation are checked after materialization. Import/review callers
also complete only the exact operation they saved. No wire format changed.

New first/update scenarios14 pass32.13s/35.6s stages. They cover close/reopen,
failure/retry, repeat/direct activation, close/cancel, newer intent/forged read,
workspace switch and storage/database replacement. One new static check stopped
before tests on formatting; an initial run passed10 before a new storage-change
fixture called registration incorrectly. The actual registration API refuses moves;
the corrected fixture explicitly injects concurrent migration/restore metadata,
without weakening production registration or expected activation refusal.

Final affected reader/publication/import/review/widget selection88 passes185.66s
pytest/189.7s stages, governed300s/two CPUs/25% CPU cap. These overlap the14 above;
no exhaustive historical suite was run. Production source/owner/version guards
remain and no research expectation was weakened. Only synthetic originals and
isolated databases were used. Candidate88595d3 predates this source. Installed
process restart, physical devices, hosting and detached adoption remain open;
no daily app/data, real accounts, model billing, native build or release changed.

Checkpoint gates: curated critical14 passed7.90s pytest/11.5s stages;
previous docs selection passed5.624s stages (run50950ea23fea465695c1c7320beb88f9).
The bounded reports retain the two-processor/25% cap; the historical suite was
not run. The earlier check process is terminal, and no validation process remained
at the checkpoint inspection. No production code changed after the88-case pass.

## 2026-11-16: candidate Mac listener-shutdown failure

Candidate1f36ffb/run43770829105 passed Windows and Linux; Mac stopped before
packaging in the six-case authority gate. The original incomplete-header
regression timed out with server_close joining a worker in socket.recv_into.
Normal close alone also failed locally; it is not the final fix. Cancellation-aware
raw reads now poll readiness/closing at100ms intervals, preserving the normal
10-second read deadline and buffered socket ownership. Backend work still drains
before authority release. No timeout/assertion was loosened.

An expanded HTTP/admin run exposed a separate process-exit fixture issue: the
Windows venv executable differs from its base runtime. The fixture now publishes
the actual listener PID in its owned atomic ready file and terminates that PID,
then waits for process exit; it no longer assumes the launcher is the listener.
A new fragmented-request fixture initially omitted the required instance header
and received428; supplying the normal session-issued instance makes it exercise
valid delayed traffic. Initial failed runs are not passing evidence.

Final affected HTTP/admin76 pass8.71s pytest/11.9s stages under the two-CPU/25%
bounded governor. The existing shutdown case completes in0.15s locally. The
new fragmented request waits250ms, succeeds and leaves research unchanged.
The active-worker case additionally checks that its reader descriptor stays owned
until worker exit. Mac validation of this correction is pending the next candidate;
Windows offscreen/local evidence is not a physical Mac or hosted-service pass.

Candidate5945820/run43771771878: Mac now passes authority lifetime checks, then
fails Screenshots with TimeoutError(rendered reading page), before packaging.
The single Mac-only retry43772183133 reproduces the same failure. Screenshot,
rich-view/HTML and demo inputs match the preceding88595d3 candidate; that is not
a root-cause diagnosis. No third blind retry was started. Linux succeeds; Windows
was still in frozen acceptance when recorded. Mac render-state observation is the
next diagnostic action; no test was skipped and no Mac package pass is claimed.
Local final critical14 pass7.62s pytest; docs60 pass2.08s pytest/5.4s stages.

## 2026-11-16: observe Mac rendering readiness without changing acceptance

The small failed Mac screenshot artifact was downloaded: it contains only
list.png, which renders the generated list; there is no reading screenshot.
The render gate now observes the same five predicates independently and records
only booleans on timeout, or missing/invalid callback. Its deadline, exact-page
requirement and blank-image refusal are unchanged. No body text is emitted.
Focused screenshot regressions8 pass0.73s pytest/5.0s stages, including stale
completion, blank image, missing/invalid callbacks and distinct false predicates.
This is diagnostic instrumentation, not a rendering fix or a Mac pass. A Mac-only
CI run is required to obtain the previously missing page-state evidence. App
runtime source remains5945820; no daily data, accounts or hosting changed.

## 2026-11-16: recover deferred saved-text admission

Instrumented Mac095e099/run43772814805 reports exact page/document/main/fonts
ready but main text absent. A governed local synthetic WebEngine probe passes
10.453s; it is not a Mac reproduction. Source inspection identifies an unhandled
boundary: a database write after worker delivery but before deferred WebEngine
admission correctly refuses old HTML, yet schedules no new read for the same
live reader. A deterministic held-callback UI case fails before the correction
on the missing busy/retry signal.

The existing admission now schedules the existing finite retry only if publication
token, reader context and preview still match; the original fence refusal remains.
No delayed work is admitted for changed papers/workspaces or closed owners. The
worker performs fresh saved-data validation; there is no AI call. A newly added
answer-case assertion initially assumed a pending-only retry link still appeared
after an answer; it now checks the saved exchange identity, question and actual
new answer. Existing assertions were not weakened.

Affected reader/rich-view31 pass15.51s pytest/19.4s stages, with two CPUs/25% cap.
Coverage includes unrelated UI write and real answer between delivery/callback,
old source and paper rejection, close/drain, bounded semantic rechecks and drafts.
This proves the source gap and its recovery, not that it caused every Mac render
failure. The original Mac screenshot gate must still pass before delivery.

Macd81e828/run43773596071 still fails rendered-page acceptance with matching
page/document/main/fonts but no main text. The deferred-admission gap is verified
locally, but is not established as the sole cause of this CI failure. The screenshot
tool now retains at most24 lifecycle state events (load/patch/content-present and
shown-state booleans), preserving call arguments/results and excluding HTML.
Focused screenshot9 pass0.81s pytest/4.0s stages. Critical evidence for unchanged
app runtime is reused fromd81e828; this diagnostic changes only the screenshot
tool and its regressions. No further app repair is claimed before the trace.

## 2026-11-16: first saved body must replace the blank document

Mac232285f/run43774002067 supplies the decisive trace: an empty full load, then
a nonempty setHtml request with no page advance and no patch callback at all.
Python marks the requested body shown; the actual matching, complete document
still contains an empty main element. The deferred-retry fix cannot recover a
callback that never arrives. No renderer-crash or provider cause is inferred.

RichView now requires a nonempty previous body before patching in place. Empty
to nonempty performs the ordinary full load, independent of JavaScript callback
delivery; later populated-document updates retain patching and scrolling. The
new regression refuses the old unnecessary JavaScript request, then simulates
its missing callback. The existing deferred-admission regression now starts from
a nonempty earlier document so it continues to protect actual patch callbacks;
it no longer asks the repaired blank transition to use the old behavior.

Affected reader/rich-view32 pass14.77s pytest/18.3s stages, two CPUs/25% cap.
No readiness predicate, deadline, stale-owner check or blank-image refusal is
weakened. Mac source/frozen verification of the fix is still required.

Mac2fb6923/run43774457806 passes6m03s. Downloaded provenance artifact14185706911
ZIP SHA25665b2668d834d8cb306f7d72362f6c1e77e03acfe68281376b6234beefc5ae6e2
and screenshots14185632796 SHA2566d7a501f2cce23f077d36e8ed65d28fcf67c310119df36b2702e4ff48893150c
match independent hashes. Clean commit/arm64/pass true, three reader launches,
four files,38MCP tools and11 sync protocol flags were read from the actual report.
Actual dive.png visually contains Chinese explanation, formula and pseudocode.
DMG artifact14184844475 is279157494bytes, GitHub ZIP digest
9d36a2e95a15b7383d2c8d28f8f9910480a3ca4ce62f3e57a1def2ca2ab23472;
the installer payload was not independently downloaded/installed here. Mac guide
has direct downloads, isolated launch and short first checks. New report dialogs,
physical devices, live accounts, old installed-binary upgrade and hosting remain
separate gates. No public release or data migration. No Windows/Linux rebuild
was started for this Mac delivery checkpoint.

## 2026-11-16: bounded source-aware report CLI acceptance

Added one loopback synthetic completion journey to the existing frozen verifier,
using a fresh workspace/profile and generated research package. The actual supplied
CLI imports, generates, exports, reads retained output and retries from cache.
The exported PDF hash, quote location, requested/returned model IDs and exact
retained/exported report agree; reads/cache produce no second completion. The
closed report adds a named source-aware-report stage and categorical result.
This is CLI coverage, not desktop handoff or scientific-support validation.

Initial new-helper failures were fixture mistakes: missing --out, omitted files/
ZIP prefix and a hardcoded page1 quote actually on page2. Reading the generated
artifact identified the last; the synthetic response now uses the actual captured
page. Product quote-location refusal was correct and was not weakened.
Standalone source journey1 pass7.5s stages; final helper/verifier43 pass41.51s
pytest/44.9s stages, under two CPUs/25% governor. No historical suite, real account,
paid model, external search, user data, build or release was used in this checkpoint.
The delivered2fb6923 Mac remains unchanged and does not include this new acceptance
report. Actual frozen execution of the new stage remains a candidate gate.

## 2026-11-16: same-source frozen report acceptance on three platforms

Clean e5eb093/run43776461463 passes Windows6m14s, Mac6m20s and Linux3m31s.
Actual provenance ZIPs downloaded/read and hash-matched:
- Windows14186950654:4b3112747a351ddf2afc1816bdb96a9db049814b4ae2989a700a7e9846890aaa
- Mac14186229638:9510b661daefd919f645d382094321649a5446c99696c039dd32b5cef58fac16
- Linux14186920337:c2e8e81f4b9ea7cdbdaca6b5d4cd1ca468a61f7214d6fbc2def4665307bc5ae0

All assert clean exact commit, passed true, completed source-aware-report and
saved/quote_located/originals_verified/retained_read/cached_without_completion
true, with separate synthetic requested/returned IDs. Four research files remain;
Windows includes isolated install/reinstall/uninstall, Mac three reader starts
and foreground, Linux AppImage integration. Installer ZIP metadata/direct links
are in the existing Mac guide; no large payload download was attempted here.
No public release/tag, live provider, paid call, owner-data migration or hosted
service. The frozen-CLI report gate is closed; desktop transport/dialog, physical
devices, old installed-binary upgrade and authority/hosting gates stay open.

## 2026-11-16: superseded status snapshot (90b13e5)

Historical snapshot preserved byte-for-byte below. It is not the current status.
Original status SHA-256: `d4ac59b736d8a67359e43c09b9646d395e76157999978090955d0bbfac9cdca4`.

~~~~markdown
# v0.5.0 current status

Updated 2026-11-16. **Development, unreleased; no complete beta acceptance.**

Latest common native candidate: clean
[88595d3 / run43754647228](https://github.com/puddings-world/Paperfact/actions/runs/43754647228).
Mac arm64/Windows/Linux all pass source and frozen acceptance from the same
`88595d332eaf36d911e3d15521e8d3f07ae976ca`, channel beta-candidate/version0.5.0.dev.
Mac5m48s includes three native launches and foreground; Windows7m44s includes
isolated install/reinstall/uninstall preserving research; Linux2m25s includes
AppImage integration. All small provenance/reports were downloaded and checked
for the clean exact commit and passing result. Source supports connected
Report & sources generation, captured purpose/route and retained-result reading.
Actual provider inference remains simulated; hosted/installed-device acceptance
and full v0.5 gates remain open. No release/tag/daily auto-update was published.
[Downloads and exact Mac instructions](testing/mac-acceptance-0.5.md).

### Earlier delivery evidence

Latest native delivery: Mac arm64/Linux use clean3b344c7
([run43714643158](https://github.com/puddings-world/Paperfact/actions/runs/43714643158));
Windows uses clean4ee3427
([run43715636579](https://github.com/puddings-world/Paperfact/actions/runs/43715636579)).
Mac5m30s/Linux2m55s/Windows7m34s pass packaged0.4.3 format initialization/export
preservation and all11 strict sync protocol checks. Windows additionally passes
isolated install/reinstall/uninstall with research preserved. Its first archive
preflight failed because Git changed line endings; the corrected follow-up passes
without changing verification. App runtime is unchanged between the two commits.
The [Mac guide](testing/mac-acceptance-0.5.md) records exact artifacts/hashes.
These are separate source commits, not one common build. Installed old-binary,
physical-device and hosted acceptance remain open; no public release was created.
The following355382c evidence is the previous common all-platform baseline.

Previous common native baseline [355382c / run43705488673](https://github.com/puddings-world/Paperfact/actions/runs/43705488673),
clean source `355382c7557150c98aee08be7b6fd12ea8274791`, version `0.5.0.dev`.
All three packaged reports pass: four PDFs, CLI/MCP retry/restart, reader/handoff,
verified-history service restart and citation graphs. Mac arm64 passes three starts
and native foreground; Linux passes AppImage integration. Windows passes install,
reinstall and uninstall with research preserved. Jobs took 3m07s/8m37s/3m25s
(Mac/Windows/Linux); older-release upgrade and registry/shortcuts remain untested.
[Exact Mac downloads and physical gates](testing/mac-acceptance-0.5.md).

Included functionality:

- Focal-only offline preparation follows exact native annotation/Lineage originals,
  including source lifetime pins. Missing/corrupt originals remain partial; unrelated
  primary PDFs stay unbound.
- Mobile **Prepare offline reading** verifies the current PDF, native declared
  originals and current decks. It deduplicates jobs, retains verified items for retry
  and refuses stale/unknown provenance as complete. Shell v31 is built, not hosted.
  The actual CI artifact passes Windows Chromium preparation, repeated activation,
  EN/ZH touch layout and fresh offline-document/cached-only verification.
- Existing private compound/referenced/unreferenced reading-text preservation,
  scoped citation graphs, nightly delivered-paper controls and explicit default-off
  new-folder automatic-sync permission remain included. Native credential-store
  and installed two-device journeys are still unrecorded.

Current affected checks and exact historical results are in the
[continuation ledger](testing/continuation-20261112.md). This candidate runs
critical14, first-sync preservation and six source lifetime journeys per OS before
packaging. Frozen acceptance checks actual guarded writes, wrong-proof refusal,
exact retry and history after restart. Counts overlap and are not a completion
percentage; no exhaustive historical run was performed for this candidate.

The CI v31 asset ID is
`8b6f4eac84eeedabd025cfa2237cc18c3312a16834405313028e6f7263493229`.
It is verified, not deployed. Update client/service/assets together; old headerless
peers are refused. Close older test-app processes before replacing a test bundle.
Full runtime adoption, remaining source/recovery mapping, persistent authority/history,
survey audit, old-release upgrade and hosted/physical-device acceptance remain open.
No tag, public release, production deployment or daily-workspace migration occurred.

This candidate uses verified history in the actual desktop and
mobile sync entries and bounded HTTP. Received data/cursor/proof and acknowledgment/proof commit
atomically. A completed receive tail older than a retained acknowledgment is
refused before writes, preserving the note and pending receipt for retry.
Inbox preparation is bounded and compared to actual local records;
new writes verify the observed tip in the authority transaction. Concurrent advance
retries, forged proofs stop, and inactive backup proof records remain preserved.
Mobile v31 saves received/acknowledged proofs with the local transaction and retains
inactive v3 recovery observations. Actual desktop/mobile attachment uploads now
carry the retained prefix into server mutation transactions, including a second
check after physical verification and before ownership. Actual desktop device
controls now require prepared proofs; fresh invitation claims recheck the original
issuer prefix. Explicit sync initializes missing legacy proof tables without
resetting damaged evidence. Source after355382c adds explicit desktop legacy-ack review and default-No
proof adoption, with read-only/resumable comparison and no automatic upload or
cursor reset. Windows Qt/native fixtures pass; a rebuilt/installed Mac journey
remains open. Durable authority fencing remains open. Same-host listener exclusion now holds through
admitted-worker drain; initialized services refuse observed database replacement
or removal without recreating missing files. This is not distributed fencing or
durable control-history protection. Source after897cd7a also makes official
serve reject unverified mutation routes and unbound new pairing claims; actual
Chrome accepts the existing v31 artifact against that strict service. Mac/Linux3b344c7 now package these changes; Windows acceptance remains blocked
at the old-source preflight. Source also adds pinned
old-source backward-export/schema-initialization preservation, passing on both
Mac/Linux packages in that run. Known absent0.5 export extensions now preserve old
workspace sharing; malformed present extensions still fail. This is not an
installed old-binary or GUI upgrade pass. See the [contract and limits](sync-http.md#verified-desktop-flow-and-wire-contract).

The integration line is `develop/0.5`. Preserved snapshots and unintegrated
candidates are listed in [workspace stabilization](workspace-stabilization-2026-11-14.md);
they are not automatically promoted into release evidence.

| Area | Current evidence | Remaining gate |
|---|---|---|
| Offline sync, history/conflicts and attachments | Preserved implementation checkpoint integrated; scoped fixtures, critical journeys and native Mac candidate evidence retained; compound graph-intake notes now retain source-authored creation times across native peers and retries; desktop/mobile now compare the retained history frontier before upload or attachment preparation, pausing with preservation guidance for missing/different history | Remaining recovery/mapping scope and actual installed multi-device journey |
| Saved desktop connection | Explicit reconnection and device-local startup opt-in; exact-credential/workspace fences, offline backoff and real MainWindow fixture delivery | Native vault prompts, installed restart/upgrade and hosted first-device issuance |
| Device pairing | Desktop create/copy/pair/join controls, native pending retry before enrollment, independent keys and verified destination storage; local fixtures pass | Real native vaults, hosted first-device issuance and installed/physical-device acceptance |
| Mobile PWA | Scoped deck inputs survive authenticated transfer and offline reopen; v31 reading preparation plus execution and received-plus-acknowledged history guards included in the verified candidate artifact. Offline/domain/service evidence plus actual JS/Python pairing, verification and revocation; same-origin cookie UI, per-tab binding and four actual Chromium journeys pass; operator key creation/loading and CLI restart verified; pinned static artifact and review-only HTTPS template prepared | Live HTTPS host, platform key permissions, Safari and physical phone acceptance |
| Scientific audit and recovery UI | Desktop current-corpus action uses the shared sealed worker with per-quotation findings, honest source-count progress and existing activity reporting; CLI/MCP use `corpus_key`, with independent generated/imported/bound originals and stable passage indices; owner-aware source-checks.v3 refuses equal-byte foreign-paper attribution through deterministic audit, retrieval, appraisal and fact binding; native alias and bilingual GUI checks pass. Confirmed atomic explanation-link and native Lineage groups (including fresh multi-paper original dependencies), with exact historical context; explicit original-source restoration/retirement preserves cache and later decisions; restored-original Lineage rebinding rechecks retained native originals/quotes and publishes fresh source pins without silently reviving the old report; confirmed native Lineage retirement reaches an independent peer while preserving exact report history, originals and notes; explicit historical source inspection shared by note/claim/highlight/explanation/deck recovery, with current target-source access unchanged; confirmed manual-highlight removal and source-verified original-identity restore, with native creation/projection checks, sealed owned-PDF witnesses, atomic receipts, peer delivery and later-decision-safe retries; typed metadata/note/manual-mark copies, exact-original highlight analysis/marks, complete native deck (including verified related-paper originals) and portable claim-group recovery; exact historical input pins from local/accepted history, original passage checks, atomic receipts and independent peer delivery verified locally | Other scientific deletion choices and legacy manual/source-lifetime mapping, foreign-workspace deck mapping, legacy/source-lifetime mapping, unavailable originals, installed corpus-action acceptance, historical/legacy corpus mapping, list-survey audit and scholarly evaluation |
| Metadata recovery | Recorded parent decisions preserve metadata, reading/order and note copies; positioned notes can atomically include verified post-backup originals, with native peer delivery verified locally; confirmed plain/positioned note deletion uses exact native history/projection checks, one atomic receipt/outbox transaction, independent peer delivery and later-restore-safe retries; confirmed claim-analysis deletion now preserves its original/deep/section research, with exact creation/projection guards, atomic decision/outbox, independent peer delivery and default-No desktop confirmation; known CLI/MCP import control records can now be archived privately during first enrollment while live research/PDFs/order are retained, with old preview/retry authority left inactive | Remaining scientific deletion/audit integration, legacy source mapping, unavailable originals and unproved parent migrations |
| Tests and resource use | Latest affected HTTP/device/browser/admin122 in23.2s total; mobile17 plus actual JS/Python protocol5.3s; candidate verifier/lifetime30 in15.2s. Exact CI mobile pin/offline journey2.9s. Checks are sequential with Windows two-core/25-percent governor. Critical14 and release38 selectors unchanged; [behavior map](testing/README.md#what-the-native-candidate-actually-verifies) | Frozen GUI-client/installed sync acceptance, historical deduplication and native resource cap on Mac/Linux |
| Release | Clean355382c candidate/run43705488673: all three native critical14, first-sync and six lifetime source journeys plus frozen verified-history protocol pass; four PDFs, normal reader/handoff and CLI/MCP preserved; Mac three starts/foreground, Windows install/reinstall/uninstall with research preserved, Linux AppImage. Exact CI mobile artifact and Windows Chrome offline reload pass | Old-release upgrade/coexistence, shortcut/registration/input/long-running/corpus/recovery UI, real-provider, hosted/two-device and physical phone journeys remain open; no public release/deployment |

The preserved checkpoint is integrated locally. Immediate priority is completing recovery
UX and durable private pairing/hosting, then installed-device acceptance. Existing
release requirements are selected by behavior, not historical test count. Latest three-platform candidate CI has passed; public-release and installed-device acceptance remain open.

The exact inventory, preservation scope and migration prerequisites are in
[workspace stabilization](workspace-stabilization-2026-11-14.md).
The [execution board](parallel-work-0.5.0.md) records actual claims and current scope. Detailed older evidence remains in the development/continuation
ledgers; overlapping case counts are not summed into a completion percentage.


Source-only screenshot readiness waits for saved/rendered content and refuses
blank PNGs. Local plain/WebEngine capture checks pass; native Mac screenshot
changes await the next coherent candidate. App runtime is unchanged.


Source afterc4edb7b now captures actual survey input paper lifetimes. A same-content
paper recreation retains a candidate instead of overwriting the old overview;
older pending inputs without lifetime observations require review. Normal enrolled
generation/edit still reaches an independent peer. These are private publication
guards, not complete portable claim sources or a new native artifact.


Source afterd4a4ff7 adds the internal versioned list-survey evidence codec and sealed
owned-original proposal engine. Actual prompt/input hashes and lifetimes, original
quote checks, explicit missing states and currentness are locally verified, including
registered managed originals and foreign equal-byte refusal. No UI/AI dispatch,
canonical storage, sync/package/recovery integration or new native build is claimed.
See the [engine contract](analysis-audit.md#source-aware-survey-engine-local-implementation-not-a-shipped-workflow).


Source aftera705cea retains actual survey originals as atomic private PDF/receipt
pairs, with exact retry/cancel/corruption handling and explicit exclusion from
claim-original grants. Independent detached backup/restore preserves those bytes
as inactive provenance. It does not save or synchronize a canonical survey report.
The next report publisher must use a list-owned verified artifact (256KiB operation
limit versus1MiB report), followed by peer/package/mobile/recovery and UI integration.


Source after6b7bf46 adds the native list-owned survey artifact seam. Complete report
bytes use existing verified blobs, not an enlarged inline journal operation.
Metadata names the list owner and exact native source lifetimes; uploads wait for
received original outcomes and stale sources retain conflicts. A peer can receive
and materialize the exact report without activating its PDFs. Trusted proposal
publication, bundle/recovery, mobile codec and UI/AI dispatch remain open. This
source-only checkpoint does not replace the previously delivered Mac/Windows builds.


Source after245535c adds trusted native survey preparation/publication. Pre-dispatch
sealed observations include report absence/version and actual portable originals.
The caller-owned savepoint publishes originals plus the report/outbox atomically;
retries reuse the same intent, while newer/retired targets and changed originals
fail closed. Local materialization is off-lock and can retry an interrupted pending
intent, including a no-network completion entry after reconnecting from disk.
Completion rechecks native database identity before activation. Plain survey rows
and installed builds are unchanged. Mobile/package/
recovery mapping, durable stale-result review and UI/AI integration remain open.


Source after1827493 adds mobile saved-report reading: strict native list-owned
wire/body parity, authenticated resumable blobs, explicit PDF separation, offline
reopening and localized list-overview cards. Shell v32 includes both new modules
and preserves research caches. Real synthetic native publication sends a report
over256KiB through independent HTTP ranges, with interruption/resumption and list
retirement. This is not an updated deployed PWA or native installer. Physical
Safari/iOS/Android, hosted authority and device durability gates remain open.
AI/desktop/common dispatch, package/recovery and stale-proposal review are unfinished.


Source after4b35801 adds an internal source-complete portable survey package
collector/validator. Actual native ownership is checked before exporting immutable
report/original bytes; the portable body excludes sync/device authority. ZIP
metadata, exact PDF pages and located quotations are independently rechecked.
This has not enabled a new bundle button or declared import success. Receiver
mapping/persistence, atomic integration with bound/unbound imports, conflicts and
re-export remain required. Existing public bundle behavior and installed packages
are unchanged. See the portable contract and requirement map.

Detached recovery now handles list-owned applied survey files without treating
them as paper decks. A real backup/restore preserves the complete report, exact
PDF objects and historical mappings as inactive data; no previous device/source
authority is revived. The original archive remains required before reviewed
re-export. Existing editable-deck recovery is also verified. This closes the
restore crash, not the pending receiver/UI reattachment or public package adapters.


Source after9c6dc9b adds the internal existing-owner survey receiver. Explicit
receiver mappings mint native report/original ownership; default preserve,
reviewed replacement, exact retry and same-transaction rollback are verified.
Independent peer delivery and re-export pass; reports without available originals
do not invent PDF grants. Eight affected groups pass under the governor in32s.
The shared enrolled whole-list importer now plans new roots and publishes
originals/report/activation/action receipt in its single transaction; actual
post-report failure and cancellation roll everything back. Default preservation
and explicit replacement retain native history. Normal list export now includes
the extension, and a local-only receiver can import/re-export without enrollment.
Local version history and exact source associations are stored in the same import
transaction; detached backups preserve reports/PDFs as inactive data. Reviewed
reattachment, AI creation and hosted/physical gates remain open. First-enrollment
candidate preparation now maps current local reports to fresh native owners while
archiving previous local versions; explicit runtime adoption/connection gates remain. No new installer or deployment.

Desktop source now includes the separate Report & sources tab for native/local
saved reports. It verifies report bytes off-thread and inspects exact original
pages only on request; no AI/download/publication is triggered. Literal source
text, missing passages, retained-version notices, refresh/retry, cancel, duplicate
admission and stale workspace/list/close delivery are covered in real Qt fixtures.
Existing editable overviews stay separate. EN/ZH screenshots use production fonts
and were visually inspected. These source fixtures are not installed Mac acceptance.

### Source after the88595d3 preview: completed-result browsing

Report & sources now offers Completed AI results, with background loading,
captured time/model selection and a read-only historical goal/statement/quote view.
Current report returns to the saved report. Reopening this view does not call AI
or apply retained content. Archived original inspection now verifies the retained
receipt/PDF/quote without substituting today's PDF. Archive reads are refused as
publication inputs and cannot start regeneration/login. Use this report now
prepares an explicit receiver-owned review and asks before publication, using the
existing local/native import boundary. Historical goal/model metadata and prior
versions remain; the current goal is unchanged. Same original workspace/list/paper
lifetimes are required. Detached remapping and installed acceptance remain open;
the existing88595d3 installers predate these entries.

The check runner now binds child Python imports to the selected checkout's src,
preventing a shared editable virtualenv from silently validating another branch.
Affected report UI/worker/check-runner selection:85 pass in103.0s total. These
are source fixtures, not installed-device/provider or hosted acceptance.


### Source after563b708: finish locally saved reports

Finish saved report now handles first publication and later pending updates in
the existing report pane. It completes accepted on-device report files without
AI, login, download or new operation versions. The selected desired operation,
original database identity, registered storage and native owners are pinned;
changed targets are refused. Close/reopen, failure/retry, duplicate activation,
workspace switch and storage/database replacement have source fixture coverage.
Pending state no longer disappears merely because no older applied report exists.

Affected saved readers, publishers/imports, review callers and widgets88 pass
185.66s pytest/189.7s all stages under the existing two-CPU/25% governor. This is
source validation;88595d3 remains the native candidate and predates this workflow.
Frozen/installed Mac/Windows, physical mobile, hosted operation and detached
mapping/runtime-adoption requirements remain open.

### Native candidate1f36ffb: Mac gate failed

Run43770829105 passes Windows and Linux, but Mac fails the incomplete-HTTP-header
shutdown regression before packaging. Do not label it an all-platform passing
candidate. A source correction uses cancellation-aware reads while retaining
reader descriptor ownership and backend/authority draining. Affected HTTP/admin
76 pass11.9s stages locally; the next native build must validate Mac separately.
No public release or change to daily research was made.

Candidate5945820 now passes the Mac authority lifetime gate. Its Mac packaging
is blocked later by a reproducible screenshot rendered-page timeout in
runs43771771878 and43772183133. Linux passes; Windows was still running when
recorded. This is not an all-platform delivered candidate. See the Mac acceptance
record; exact render-state diagnosis remains before another rebuild.

### Delivered Mac preview2fb6923

Mac43774457806 passes6m03s from clean2fb69238377a4a43d8cccae28eef78820494bf6a.
Source, reading screenshot and frozen app gates pass. The small provenance/report
and screenshots were downloaded, ZIP hashes matched and the actual reading text
was visually inspected. Three native starts/foreground, four research files and
all11 strict sync protocol checks pass; [download and test steps](testing/mac-acceptance-0.5.md).
No new Windows/Linux build at this source, public release, hosted deployment or
physical-device acceptance is claimed. New report dialogs remain source/widget
verified rather than comprehensively covered by standard frozen acceptance.

### Common-platform previewe5eb093

Run43776461463 passes Windows6m14s/Mac6m20s/Linux3m31s from clean
e5eb093ad708b52580daccce4058d24dfcc59998. All three small provenance archives
were downloaded, independently hash-matched and read. Actual frozen CLIs pass
the new report stage: one synthetic completion, located quote, exact original,
separate requested/returned model IDs, retained read and cached retry without
another completion. This closes the named frozen-CLI report gate, not desktop
private handoff, every report dialog, physical devices, hosted authority or full
release approval. Downloads are in the Mac acceptance guide; no public tag or
service was created. The daily app and owner research remain unchanged.

~~~~

## 2026-11-16: persisted official-authority file lifetime

Before the fix, replacing a revoked-token database with its earlier file and
constructing a new official authority did not raise; the new regression demonstrates
that restart gap. New official markers are v2 with the actual device/inode pin.
Startup checks before opening and passes the expected identity into ReferenceService
so a later replacement/removal cannot trigger schema creation on the wrong file.
Normal restart preserves revocation. The marker is not silently regenerated.

Legacy v1 serving/issuance now refuses with static recovery guidance, but explicit
backup remains compatible. Fresh-workspace restore emits a new actual pin and
requires new credentials; original research remains and old tokens fail. Backup
carries its admission pin into the captured source identity. Research/backup/wire
formats are unchanged; service-marker compatibility changes deliberately.

Initial static checks stopped on import/test-signature formatting. The first
marker decoder incorrectly required canonical artifact JSON; it was replaced with
the existing duplicate-safe whitespace-tolerant service JSON decoder. No source
or test assertion was weakened. Admin21 passed6.0s stages; final selected
admin/mount/backup/restore/native/HTTP/service189 pass59.19s pytest/62.7s stages.
The new marker refuses extra fields, duplicate keys, floating identities and
changed native identity. Constructor races refuse before SQL writes and never
recreate a missing database. All data/tokens are synthetic.

This closes the named local file replacement/restart gap only. Same-file SQL
rollback, joint marker/database restoration, independent control history and
cross-host fencing remain open. The e5eb093 native candidates predate the source
change. No app restart, owner-data mutation, real credential, cloud operation,
installer build or release was performed.

## 2026-11-16 retained local device/pairing checkpoint

- Implemented official v3 marker with exact native identity and deterministic
  device/pairing digest; cooperating transactions serialize and publish the
  checkpoint before committing SQL. Legacy v1/v2 are explicit-backup-only.
- Same-file revoked-token resurrection failed before the implementation. Current
  fixtures cover restart/pairing/concurrent enrollment, schema rollback, explicit
  retry and actual subprocess exit after publication, with access/export refusal
  and sanitized recovery guidance. No new wire, backup or research format.
- Fixed a local service-format import shadowing backup FORMAT. The old-schema
  fixture now creates explicit legacy files instead of deleting a current guarded
  table; all original recovery/research/old-grant assertions are retained.
- Affected bounded selection: 195 passed in 66.46s pytest, 70.1s stages. Earlier
  intermediate failures are not passes. This selection overlaps existing cases;
  it is not an exhaustive release or all-feature gate.
- Source-only: e5eb093 native artifacts predate the guard. No owner research,
  account/model, cloud resource, new build, app restart or physical device used.
  Joint marker/database rollback, independent control history/anchor and
  cross-host fencing remain open; no power-loss durability claim.

## 2026-11-16 extend the existing report gate to private QProcess routing

- The same source-aware-report verifier now uses production JobHandoff and a real
  QProcess for initial generation through the selected CLI's private stdin entry.
  Child disk AI is disabled; exact captured requested/returned models, unchanged
  disk settings, source/PDF identity, retained read and one-completion cached retry
  remain assertions. Credentials are absent from argv/environment/user output.
- Failure cases refuse zero exit without handshake and enforce an outer deadline
  with owned child shutdown. The Qt startup timeout stays independent (30s), so
  a short harness deadline cannot race its own identical protocol timer.
- Initial affected source/helper/protocol/desktop-private/packaged-verifier scope:
  100 pass45.77s pytest/49.1s stages, CPU bounded. Existing frozen e5eb093 evidence
  is unchanged and does not prove this source extension. Full frozen GUI dialogs,
  provider accounts and physical-device/hosted journeys remain separate gates.
- No new product command/hook, installed tool, build, cloud call or owner data.

## 2026-11-16 preserve offline originals during legacy cleanup

- Reproduced a selected offline paper still being offered by storage.plan before
  the fix. Current claims now include device-local offline intent and native
  desired/applied/document-intent owners, including inactive/superseded records.
- Cleanup rechecks claims at execution, rejects disguised cache/paper entries and
  root/linked path scopes, and stops before deletion on invalid/unmapped retention
  metadata. Explicit unpin restores ordinary cleanup only without another owner.
  Immutable blob/version/history stores remain outside this cleaner.
- Storage/offline43 pass53.47s pytest/56.9s stages with the bounded CPU runner.
  Storage cases cover stale preview, repeated prune, retained original states,
  explicit unpin and no deletion on invalid retention metadata; existing offline
  fixtures cover actual local intent and byte-readiness behavior. Native symlink
  mutation races, actual installed-device cleanup and complete automatic asset
  eviction are not proven by these fixtures.
- No real cleanup or vacuum was run, no research directory or account was touched,
  and no native artifact/release/cloud deployment was created.

Final storage/CLI selection25 passes2.56s pytest/5.8s stages, including preview
and confirmed cleanup returning status2 with bounded review guidance and no
file deletion on invalid retention metadata. This overlaps the storage/offline
selection above and is not an additional feature count.

## 2026-11-16 common native candidate0a64ec7

- Exact clean source0a64ec7ed8c2aec8c435c12f285eae36d80d5d61,0.5.0.dev,
  beta-candidate; run43784461643. Windows7m40s, Mac arm646m15s, Linux3m36s
  success; draft skipped. No tag/release/deployment or owner-data mutation.
- Each OS passes critical14, first-sync preservation1 and authority/retention14
  source cases. The existing three-minute source lifetime stage now includes
  same-file control rollback, publication/process-exit and stale-preview offline
  preservation; no historical full-suite run or duplicate build was added.
- Independently downloaded/hash-checked all three small provenance ZIPs. Their
  build-info and frozen reports confirm exact clean source, passed true and both
  private_handoff/child_disk_settings_ignored true. Host desktop JobHandoff and
  real QProcess drive the actual frozen CLI; child disk AI is disabled. One
  synthetic completion preserves PDF/located quote and requested/returned model,
  retained read and cached retry. This is not full frozen GUI-dialog acceptance.
- Windows additionally passes isolated install/reinstall/uninstall with research
  preserved; Mac three launches/foreground; Linux AppImage integration. Verified
  mobile ZIP contains shellv33; built only, no HTTPS deployment or phone evidence.
- Large installer ZIPs were not downloaded here; their digests below are GitHub
  artifact metadata, not independent payload checksums. Native vault/live account,
  physical Mac/Windows/phone convergence, old installed-binary upgrades, complete
  runtime coverage and independent authority control/hosting gates remain open.

| Artifact | ID | ZIP bytes | Published ZIP SHA-256 |
|---|---:|---:|---|
| provenance-macos | 14190002815 | 3023 | `8928e62b01a78b20572e413225560e99b145f5f528fa38f43b5a516e24fb42a1` |
| build-linux | 14189797058 | 282627999 | `0330e09f4b783331e094dd8d426d2b229261e3fc5dd9d939233306be5ad71e76` |
| mobile-web-0a64ec7ed8c2aec8c435c12f285eae36d80d5d61 | 14189708134 | 896862 | `d3cd1845865c04fec587441251c51bdb1ed608a6fe47b3373c7458e71a655f1a` |
| build-macos | 14189674380 | 279114356 | `e4370c5195f2357087996fd74c51d257d56bcd59f8f399fc6a563544004019a9` |
| build-windows | 14189183704 | 184672050 | `a6289da8c804995adc6967881a9725f2f944d9c61c4b319e1f26f40eb14376ce` |
| provenance-linux | 14189058557 | 3032 | `7d7747f41b46c67b69431371b8831e31483db60b157f4e2645aab1eb766b71a3` |
| provenance-windows | 14188969318 | 3404 | `1d5502ba3db7dcd82aad6e26aba705867bb6efa052818a0183920907a0f27336` |

## 2026-11-16 shared saved list-report source audit

- Added explicit Check all sources in Report & sources and the existing shared
  analysis.audit operation with list_id only. Paper/corpus calls stay compatible;
  mixed targets fail before reading. Official MCP discovers the new parameter;
  tool count and transport names do not change.
- Factored the original exact-source read/verification from survey_reader.inspect
  so preview and full report audit share ownership/hash/page/location rules. Each
  captured original is parsed once, with final lifetime/source rechecks. Findings
  distinguish verified/unavailable/not-selected sources, recorded versus actually
  rechecked locations, unlocated passages and statements with no source passages.
  Scientific semantics are always not_checked. No raw research output is logged.
- Local/native service and existing reader/audit integration31 pass64.2s stages;
  desktop/actual CLI/official MCP8 pass28.4s; added original-change/budget and
  close/workspace-switch cases10 pass25.8s. Selections overlap, not feature totals.
  The existing report acceptance helper now audits its generated report through
  actual JSON CLI without another synthetic model completion.
- Existing executor deduplicates clicks and preserves the visible report; closing,
  cancellation and workspace/report changes discard late delivery. SQL snapshots
  remain unchanged. Bound16 captured originals/128MiB/default60s cooperative work;
  native parsing is not a hard instruction-level timeout. No live account/network,
  owner data, new package, release or deployment. Delivered0a64ec7 predates it.
- Earlier formatting/edit failures produced no passing test evidence; one edit
  stopped on mixed newline bytes and a requested new selector did not yet exist.
  Exact-byte correction preceded the passing scoped checks. No test was weakened.
