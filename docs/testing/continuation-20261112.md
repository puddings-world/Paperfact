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
