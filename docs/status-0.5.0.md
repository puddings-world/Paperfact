# v0.5.0 implementation status

Updated 2026-11-14. **0.5.0.dev, unreleased; complete release acceptance pending.**
Active integration is `Paperfact-develop` on `develop/0.5` (shared HEAD `aa4b30e`
plus uncommitted continuation changes). The historical temporary integration
checkout no longer exists. Daily research and the maintenance release remain
separate from this development work.

## Latest full-check result (2026-11-14)

The latest completed full check is **failed**: Python 3,349 passed, one failed
in 6,730.59 s; privacy/Ruff passed. Frontend/mobile stages were not reached.
The staged Lineage task/import assertions and rollback-fixture precondition have
now been [reconciled with the agreed v0.5 contract](testing/lineage-contract-reconciliation.md).
All default-store, generic-wire, source-closure and rollback protections remain.
The repaired modules passed 58 cases; final routing/import boundaries passed four
(overlapping). This is preflight evidence, not a replacement full-check pass.
The mobile-original and enrolled-import code/new cases were subsequently
integrated on 2026-11-14 after exact base-hash checks, preserving unchanged line
spans. The historical stage-only expectation transition is now covered by the
contract reconciliation above; full acceptance is still required.
Affected import/package integration passed **50 cases in 241.08 s**. Mobile
semantics passed **647 cases**, and the maintained mobile-to-Python entry point
passed all 13 isolated HTTP programs. Real Chromium passed 18 checks each for
IPv4/IPv6; this is not installed-device or release evidence. See the ledger and
[import scenario map](testing/enrolled-lineage-import-candidate.md).

## Desktop import review (2026-11-14)

Native file/share-link import now exposes destination-list and explicit paper
pairing, worker preparation, readable preview and separate confirmation. Closing
cancels the actual publication ticket and drains work; stale GUI delivery cannot
apply or navigate into another workspace. The actual three-original Lineage UI
journey and defensive active-search case plus docs contracts passed **54 cases
in 17.27 s**. Adjacent regression evidence and failed-fixture limits are in the
[scenario map](testing/package-review-scenarios.md). Native different-version
comparison is covered below; unsupported legacy migration, full acceptance and
device/deployment gates remain open.

## Native scientific version comparison (2026-11-14)

Different owned Lineage reports can now be explicitly compared, kept or replaced
while retaining the prior native version. Separate final import confirmation is
required. The reviewed decision is bound to the actual archive, receiver, mapping
and saved scientific/native state; generic replace cannot bypass it.
The final decision/peer/backup/receive/capacity/version gate passed **76 cases in
215.79 s**, and final comparison UI passed **8 cases in 71.47 s**. The actual peer
version catalog lists old/new reports, explicit downloads bind all three originals,
and independent backup/detached restore preserves both history and current research.
[Guide](lineage-import-comparison.md) / [scenario map](testing/lineage-import-comparison-scenarios.md).
Existing-beta accepted-event backfill now has the local implementation below.
Unsupported legacy migration, complete full validation, performance, installed
migration, hosted and physical-device gates remain unfinished.

## Local existing-beta history repair (2026-11-14)

A bounded native service now restores missing accepted versions from retained
inbox/graph receipts, with atomic per-batch checkpoints and restart/cancel resume.
Normal explicit sync calls it; opted-in automatic sync keeps scheduling pending
work. Offline History offers Update version index, disabled once current. No AI,
PDF download, current research or outbox mutation is part of this repair.
The final new core/UI/automatic scope passed **20 cases in 182.59 s**. Earlier
adjacent reader/connection/controller scopes passed separately; see the
[scenario map](testing/lineage-history-repair-scenarios.md). Progress is device/file
scoped and excluded from research archives; actual history remains preserved.
The full, installed-beta migration, Mac/phone and hosted gates remain unproven.

## Current integration evidence

Optional Lineage report storage is now initialized only for explicit analysis or
complete typed receive. Generic enrollment creates synchronization metadata while
leaving an absent report table absent. The affected schema/enrollment/native
projector/receive/workflow gate passed **21 cases in 145.67 s** (149.2 s overall),
privacy/Ruff passing. The prior candidate-only absence assertion is unchanged and
now passes. The final schema/cancellation/enrollment/peer-download/editable-recovery
gate passed **38 cases in 349.57 s** (354.1 s overall), privacy/Ruff passing.
The two selections overlap; no coherent full or installed-device pass is claimed.
See the [schema scenario map](testing/lineage-schema-scenarios.md).

Automatic sync now wakes from actual outstanding appended local journal entries,
rather than list-render revision changes. It ignores complete own/manual receipts
and peer receive projections, while accepted-but-unreceived operations still
schedule receipt recovery. The affected sync/observer/reader/window gate passed
**116 cases in 130.97 s** (134.6 s overall), privacy/Ruff passing. See the
[behavior map](testing/continuous-outbox-scenarios.md). Explicit consent, offline
backoff and live/device/full release gates remain unchanged.

The actual reader now has a [saved-text update notice](saved-text-updates.md)
for changed explanations, Q&A and notes, including unlisted open papers.
Detection preserves the loaded original, page, keyboard focus and drafts;
explicit reload uses actual accepted saved-content delivery. The adjacent
observer/reader/main-window gate passed **180 cases in 167.39 s** (171.4 s
overall). After a visually discovered Chinese-label correction, the final
affected gate passed **20 cases in 26.47 s** (29.6 s overall), privacy/Ruff
passing. These overlap and do not prove full release/device readiness.

The shared saved-evidence checker now includes current Lineage statements with
per-statement and per-quotation source versions. The affected backend/Qt/CLI/MCP
scope passed **91 cases in 134.66 s** (138.3 s overall), privacy/Ruff passing.
It checks only the currently owned original, labels other originals explicitly,
and retains the complete-corpus and semantic-audit limitations. See
[concrete audit scenarios](testing/audit-lineage-scenarios.md). This does not
establish full release/device readiness; the newer schema gate above resolves
the candidate-only absence regression locally.

The [desktop Lineage action](lineage-reader.md) now connects saved-first reading,
source selection, explicit frozen-route analysis, native/unbound transactional
publication and exact-original windows. It preserves unsent reader drafts,
selected papers across searches and completed requested/returned model metadata.
The final action/coordinator/menu scope passed **41 cases** (76.24 s; 79.5 s
overall), including account/context changes, active-worker close, original proof
invalidation and missing-store refusal. An earlier related original-proof scope
passed 76 cases (154.60 s; 158.2 s overall); selections overlap. Shared route/task
settings have a separate 92-case passing scope. These are local fixture checks,
not a whole-application or installed-device pass.

Original inspection and package re-export now share explicit native/generated/imported
origin selection. The actual all-origin desktop scope passed 50 cases (126.21 s;
129.7 s overall); the current package/original/bundle scope passed 76 cases
(245.46 s; 248.9 s overall). This includes imported source PDF windows, corruption
without alternate-reader fallback, cancellation/view changes and a genuine native
receiving workspace. These overlap other receipts and do not resolve full release
gates; lifecycle controls are covered by the newer focused evidence below.

The shared [Lineage lifecycle backend](lineage-lifecycle.md#shared-lifecycle-api-development)
now supports observed removal/restoration for generated, imported and native
reports, exact retries and archive-only action evidence. The selected lifecycle,
recovery and enrollment-history gate passed **97 cases in 339.24 s** (343.1 s
overall), with privacy/Ruff passing. Eighteen new lifecycle cases are explained in
the [scenario map](testing/lineage-lifecycle-scenarios.md). A separate ordinary
list-sharing privacy regression is recorded in the ledger. The newer version
catalog, confirmed desktop controls, native late-failure/cancellation and actual
import/native history scope passed **48 cases in 184.96 s** (188.4 s overall),
privacy/Ruff passing. After committed-but-stale-view guards, the final affected
Qt/origin scope passed **32 cases in 128.51 s** (131.9 s overall), privacy/Ruff
passing. The scopes overlap; they are not release totals. Historical-original
inspection now uses its own retained-provenance/source proof boundary. The related
source/Qt gate passed **130 cases in 492.61 s** (496.1 s overall). After a newly
reproduced queued-cancel race was fixed at actual window delivery, the final
affected Qt/origin scope passed **44 cases in 223.56 s** (226.9 s overall),
privacy/Ruff passing. These overlap and do not certify the release. Fresh editable detached Lineage adoption now has local integration evidence;
see [the enrollment scenario map](testing/lineage-enrollment-scenarios.md).
The latest affected enrollment/recovery/version gate passed **52 cases in
417.87 s** (421.7 s overall), privacy/Ruff passing. Two separate negative archived
evidence cases passed in 21.96 s. Counts are overlapping scopes, not release
totals. The actual fresh enrollment -> attachment publication -> public join ->
selected offline-download journey now has a separate **5-case passing gate**
(49.12 s, 52.3 s overall), privacy/Ruff passing. It verifies the exact report,
three original PDFs, ordinary offline reading and duplicate-free resynchronization
through the reference authority; this is not an installed-device/hosted pass.
Final full/release/device acceptance remains open.

The complete pre-desktop Lineage diagnostic is terminal: **638 passed, 2 failed**
in 1663.88 s. Both failures assert absence of optional tables now created by native
setup (candidate enrollment and protected projection rollback). These assertions
remain unchanged. A later direct recheck of those exact two cases produced
**1 passed, 1 failed in 11.34 s**: the native schema rollback and unchanged
journal passed; candidate-only enrollment still failed at that checkpoint.
The newer 21-case schema gate above passes that unchanged assertion. No full
green result is claimed.

Native journal/service publication, exact source lifetime/conflict handling,
HTTP/mobile consumption and detached recovery have focused evidence. Capacity
integration passed 29 cases; ordinary journal/service, graph, note/list and native
research regression passed 242 cases (101.11 s; 104.3 s overall). All counts refer
to overlapping dated scopes, not release totals. Stored-result/package adoption,
broader recovery/analysis audit,
public generation adapters and final
full/hosted/device gates remain open.

See [native shared publication](grounded-lineage-producer.md#native-shared-publication)
and the [continuation ledger](testing/continuation-20261112.md) for limits.

| Area | Current local evidence | Remaining completion/acceptance gate |
|---|---|---|
| Library/notes and conflicts | Targeted offline-edit, resolution and recovery journeys pass. | Matching final full check and installed-device journey. |
| Continuous sync | Connection UI, reference administration and background coordination are implemented locally. | Hosted pilot, native credentials and real cross-device acceptance. |
| Attachments | Verified-transfer and pending/failure/offline-status paths have targeted coverage. | Complete installed-device and interrupted-transfer acceptance. |
| List packages | Public unbound Lineage import/export retains exact originals and off-list context; affected 233-case gate passes. | Complete full gate, enrolled import, reviewed mapping/new intent and source controls. |
| Mobile | Saved Lineage cards, genuine native HTTP event consumption and 7 isolated Edge browser scenarios have local evidence. | Enrollment/adoption, source controls, broader browser/accessibility and physical-device acceptance. |
| Grounded reading | List-goal/claim paths and native Lineage publication, source lifetimes, conflicts and detached recovery have focused coverage. | Reviewed stored-result/package adoption, lifecycle/editing UX, analysis audit and full/device gates. |
| Backup/recovery | Generated, imported and native Lineage can create fresh editable copies with verified originals, new scientific operations and retained archive history. | Final adjacent/full gate, enrolled live import, hosted recovery rehearsal and installed-device acceptance. |
| Release | `0.5.0.dev`, unreleased. | Full validation of the accumulated revision and certified installers. |

<details>
<summary>Detailed local test evidence (overlapping selections, not release totals)</summary>

- The initial native put builder now uses sealed pre-analysis target/source
  observations and actual published original operations. Its native-candidate
  adapter preserves the real request and requested/returned models without
  another completion, rejects stale route/retargeted output and checks database
  scope before reading private paper mappings. Falsified yet schema-valid source
  metadata is refused; source retirement/restoration cannot rebase the intent.
  Source/dependency/graph scope: 71 passed (118.36 s; 121.7 s overall). Final
  candidate/target scope: 35 passed (111.06 s; 114.0 s overall), including all
  16 new builder/candidate cases. Zero skips; privacy/Ruff pass. These overlapping
  checks construct frames and real source children, not scientific outboxes or
  accepted events. Final compound publication, edit/retire/restore/resolution,
  complete shared admission, stored-result adoption and full/device gates remain
  open. See [observed native construction](grounded-lineage-producer.md#observed-native-operation-construction).

- The main graph receiver now passes immutable original operations and separate
  visibility to explicitly registered native projectors. Native factories for
  join/bootstrap, capture, enrollment/sync, deck runtime, Inbox and primary
  migration register the adapter; generic custom writers retain their old path.
  Trusted setup creates optional schema, while attach stays read-only. Original
  file metadata is projected before dependent content. A real receive-prefix bug
  was reproduced/fixed: just-received own sources are not misclassified pending
  before cursor commit. Core scope: 72 passed (28.96 s); factory/recovery/transfer
  scope: 270 passed (320.95 s; 324.5 s overall), zero skips, privacy/Ruff pass.
  Additional two upgrade cases and one actual receive ordering case pass. These
  counts overlap earlier receipts. Common native Lineage admission, observed
  operation/resolution building, compound publication/import/enrollment and
  full/install/hosted/device acceptance remain open. See the
  [explicit projector contract](grounded-lineage-producer.md#explicit-graph-projector-registration-and-trusted-setup).

- The staged native receive visibility decision now distinguishes pending,
  deferred, missing, retired and replaced parent/original metadata. Every pending
  dependency takes precedence over earlier hard source failures, preventing
  source order from erasing current research while edits remain unsent. Protected
  writes preserve full hidden puts/history; genuine source events and independent
  peer metadata are used, without manufacturing scientific receipts. Affected
  gate: 40 passed (152.84 s; 155.8 s overall); two additional retained-projection-lag
  cases passed (12.58 s; 15.4 s overall), zero skips, privacy/Ruff pass. The existing
  materializer repairs those actual native heads before staged science resumes.
  This is not live native receive/admission: its remaining implementation closure
  is explicit in the [receive contract](grounded-lineage-producer.md#native-receive-visibility-decisions).

- Exact-source publication readiness now gates both file-transfer and desktop
  attachment preparation. It waits for each source's validated received result,
  not uploaded bytes or an acknowledgement; final conflicts retain their original
  pins and end transfer waiting. Peer receipts need no duplicate upload, and
  missing/foreign publications fail explicitly. Affected source/journal scope:
  115 passed (236.06 s; 239.3 s overall). Desktop scope: 33 passed (66.81 s;
  70.0 s overall). Strengthened real missing-registration and docs/check tests:
  52 passed (7.24 s; 10.0 s overall). Selections overlap, all have zero skips,
  privacy/Ruff pass. Final source/desktop component: 16 passed (68.31 s;
  71.1 s overall), including retirement/restoration before the first upload:
  the real source queue drains without reviving stale science. Live Lineage
  admission/materialization and final full/device
  validation remain pending. See [source readiness](grounded-lineage-producer.md#source-publication-readiness).

- The staged native projection now has a journal-owned DML path and standalone
  savepoint wrapper. The real SQLite authorizer remains unchanged: transaction
  control and DDL stay forbidden inside its writer. Exact desired original and
  materialized-paper epochs are checked before/after publication; late changes
  roll back. Three actual source outboxes and scientific projection commit or
  roll back under one real journal owner in fixtures, without fabricating a
  Lineage outbox/receipt while admission is closed. Affected gate: 138 passed
  (364.40 s; 368.2 s overall), zero skips, including 12 new writer cases. Remaining
  native work includes complete content
  publication/receipt, schema initialization and receive/materialization before
  live admission. See [protected-writer integration](grounded-lineage-producer.md#restricted-journal-writer-compatibility).


- The mobile event path now validates closed typed Lineage content, exact ordered
  paper/source-file lifetime dependencies and known immutable addresses. Current
  scientific cards update on foreground sync; source retirement/restoration and
  typed tombstones suppress stale saved fallback without discarding receipts or
  changing the primary document. Metadata creates no byte/AI grant. Affected
  gate: 94 Python cases (230.10 s), 616 Node checks and 13 existing Python HTTP
  integration programs; 266.1 s overall, privacy/Ruff pass, zero test skips. Two
  Python cases consume actual native three-original frames in Node and confirm
  server/journal Lineage admission remains disabled. All 36 new consumer cases
  and 45 existing saved-Lineage cases are included without duplicate fixture
  registration. Separate fresh-profile headless Edge: 7 scenarios pass, including
  real IndexedDB reopen/rollback, actual phone-width cards/disclosure, in-place
  foreground updates and stale-source hiding across reload. No physical-device,
  independent semantic review, hosted Lineage service or full release claim.


- Normal list export and unbound import now use the source-complete Lineage
  codec/publisher in the shared bundle workflow. Actual public roundtrips retain
  complete saved reports and original PDFs across three receivers, without
  adding context peers as members or copying their unrelated notes. Concurrent
  retries create one action, file/SQL failures roll back, late source/workspace
  changes refuse, and same-ID bibliographic collisions require review. Compatible
  existing peers retain local notes/epochs. Enrolled import still refuses before
  changing research/outbox state. The affected gate passes 233 cases (322.75 s;
  326.6 s overall), zero skips, including all 18 public/boundary cases. No live
  Lineage sync admission, full gate, installer or device acceptance is claimed.


- Fresh unbound recovery-original staging now verifies active current archive
  cohorts in bounded off-SQL batches and creates new local source ownership in
  one caller savepoint. The native import stage releases input PDF buffers after
  staging; exact metadata/file proofs remain mandatory. The affected gate passes
  167 cases (353.60 s; 357.0 s overall), zero skips, including 15 recovery-source
  cases. Second-batch failure/cancellation rolls back earlier batches, retries
  do not duplicate sources, and the SQL phase performs no PDF read/parsing.
  Source research is unchanged. Complete history retention/enrollment and public
  editable recovery are still pending; the existing blocker remains. See the
  [API and limits](lineage-packages.md#fresh-originals-from-detached-recovery-inspections).


- Imported current/displaced Lineage history now participates in complete backup
  and detached restore, with exact original associations, different saved PDF
  versions and independent quote/page validation. Old protocol/source identities
  remain archived, never active receiver grants. The shared archive/read/package
  gate passes 230 cases (490.95 s; 509.2 s overall), zero skips. Two additional
  retirement/unknown-schema cases pass separately (7.66 s), added after that gate
  started. The new recovery module has 14 cases across those receipts. Temporary
  current-format backup refusal was replaced by complete preservation; unknown
  formats still refuse. Reviewed editable adoption, normal entry points, full
  release validation and installed-device/hosted acceptance remain incomplete.


- Imported Lineage originals now have their own native receipt/lifetime-bound
  reader and source-complete staged re-export path. The actual three-receiver
  journey retains exact focal/peer bytes without copying sender grants or using
  AI. Independent cohorts and imported/generated source routing are covered.
  A malformed stored report record was reproduced as a raw SQLite error and is
  now refused with a bounded domain error. The affected package gate passes 118
  cases (142.18 s; 145.1 s overall), including 29 new reader cases. No app/PWA
  source activation was added. Imported-history recovery and live entry points
  remain incomplete; no installed-device or hosted-pilot acceptance is claimed.


- A staged unbound Lineage publisher now records exact scientific rows, every
  available original association and a distinct native import-action receipt in
  one caller transaction. Repeated requests verify actual content/associations;
  conflicts preserve current content by default, explicit replacement retains
  displaced rows/history. Mid-child failure, late cancellation and original
  mutation roll back all child writes. The affected gate passes 88 cases
  (124.59 s; 127.9 s overall), including 25 new publisher cases. One subsequent
  backup-boundary case passes separately: the current recovery path explicitly
  refuses this unregistered history without creating an incomplete backup.
  Imported-original reading/re-export/recovery and live registration remain open.


- Fresh receiver target observation now uses the caller's existing transaction,
  so new paper identities need no intermediate commit. The off-lock validator
  retains exact immutable PDF bytes without granting source ownership. Fifteen
  new cases cover fresh/mixed owners, rollback, stale epochs, cancellation,
  native-proof changes and ZIP-independent bytes. The final affected package
  gate passes 63 cases (141.68 s; 145.3 s overall), zero skips. Reusing only
  immutable sender ZIP fixtures reduced that same scope from 269.5 s, with all
  receiver behavior assertions and independent mutable receivers preserved.
  At that checkpoint publication was not yet implemented; recovery/reading and
  live import integration remain pending.


- Staged receiver mappings now retain scientific evidence while remapping explicit
  existing local paper owners, returning current conflicts and rechecking native
  lifetimes/composite targets in the caller transaction. The affected package gate
  passes 48 cases (207.44 s; 210.5 s overall), including 21 new receiver cases.
  Caller-input mutation was reproduced and fixed with owned input snapshots.
  Empty-library atomic creation, source ownership and normal import remain pending.


- A source-complete Lineage package collector/codec now retains selected off-list
  paper context and exact originals, and independently checks PDF page counts and
  located quotations. The affected new/existing list-package gate passes 111 cases
  (268.19 s; 272.6 s overall). The legacy bundle path now explicitly refuses
  Lineage instead of silently dropping it or replacing an old export. Fresh
  receiver import/source ownership and live package integration remain incomplete.

- Full saved-Lineage portable read metadata and bilingual overview cards now retain
  quotes, proposed roles and unresolved evidence. The affected gate passes 88
  Python cases plus all 580 mobile Node cases and all 13 existing Python/HTTP
  integration programs (156.3 s overall). Forty-five Node and nine Python cases
  are new; source/cursor/outbox/authority remain unchanged on read import.
  Browser UI verification was attempted but its access host was unavailable; no
  screenshot, physical-phone or Mac acceptance is claimed. Live Lineage
  operation/source integration and the complete release gate remain pending.

- Archive-only Lineage integration now preserves exact bound projection/history
  and source-file incarnations in real backups and detached restores. The affected
  projection/read/archive/adoption/provenance/budget gate passes 183 cases
  (521.14 s; 524.8 s overall), including 4 new immutable-history and 15 bound-archive
  cases. No live Lineage packet admission or fresh editable enrollment was enabled.


- A separate, unregistered bound-original reader now checks exact visible Lineage
  projection metadata, selected paper/source lifetimes, receiving aliases and
  locally verified original bytes. It adds no packet admission, automatic source
  grant, download, model call or UI registration. Fresh editable recovery and real
  producer/protocol/UI integration remain incomplete.
  The affected source/projection/dependency/shared-graph gate passes 156 cases
  (319.69 s; 323.4 s overall), including 20 new bound-reader cases.

- Desktop: legacy note upgrades, concurrent offline edits, independent conflict
  backup/restore and idempotent resolution have four new journey/guard cases;
  67 existing content/capture/research cases pass after the writer fix.
- Attachment status: 27 affected cases pass, including pending/failure UI,
  cancellation/reconnect and real fixture PDF/deck/asset transfers. Metadata
  synchronization does not certify complete offline file availability.
- Mobile: 535 Node cases and all Python HTTP programs in the mobile check pass.
  Eight fresh-profile IndexedDB/startup groups and the documented actual PWA
  browser/HTTP offline-reload/continued-edit mode pass. Phone-sized screenshots
  were inspected; these are Windows Edge tests, not physical-phone acceptance.
- Lineage: the backend now archives all available selected originals before a
  completion, with typed corpus/request/source/lifetime observations. Twenty final
  source-boundary cases pass, including real detached backup and enrolled peer IDs.
  Archive-only claim/QA enrollment boundaries also pass 37 selected cases. These
  observations do not activate canonical report storage or UI/sync.
- Lineage proposal results now survive process restart through private generation
  candidates/owned sidecars. Source-complete backup, foreign-database isolation,
  idempotent retry and readable export pass focused checks. A 199-case integration
  selection passes, followed by 41 consumer and 39 generic-generation cases after
  the final narrow fixes. Counts overlap; this is not a matching full gate.
- Optional pre-call composite-target binding now rejects changes before a model
  call and retains during-call conflicts without replacing the canonical target.
  Native leases remain distinct from archived hashes/current write permission;
  18 final target cases pass, with 64 earlier core and 24 consumer cases passing
  in overlapping focused selections. An unbound caller-transaction publisher is now staged; live shared publication
  and complete preservation remain unimplemented.
- The staged unbound Lineage publisher now installs the exact row, all available
  original associations and retry receipt in one caller transaction. The 46-case
  publication/peer/target selection passes; real sync-bound candidates are refused.
  This does not enable bound source readers, list-package sharing or mobile.
- Local detached recovery now validates canonical Lineage/publication/candidate/
  per-paper original closure, restores research and archives old authority.
  The affected recovery/adoption/source union passes 142 cases, plus a separate
  A/B version-history case. Editable sync adoption remains explicitly gated
  pending fresh source ownership.
- A staged saved-original reader now verifies exact local peer bytes and their
  publication/association closure, with an actual loaded-view delivery guard.
  It creates no identities/grants and does not activate detached or bound sources;
  native PDF viewport/citation-button integration remains open. The 53-case
  source/publication/recovery selection passes, including 26 new source cases.
- The staged portable Lineage operation codec and typed graph-address lifecycle
  pass 229 selected cases with existing graph/content/file/ordering contracts.
  Live Lineage journal/service admission remains closed until publication,
  all-source ownership and complete preservation/receiver integration are ready.
- Dependency-complete staged Lineage frames now pin every available original's
  file incarnation as well as all paper lifetimes. Pins derive from actual
  same-transaction peer publication. Shared graph preconditions now reject stale
  explicit pins; normal live Lineage packet admission remains closed. Source-less
  staged frames are not live operations.
  A 165-case related selection passes; the final native-client guard has two
  affected follow-up cases passing. These counts overlap, not a full gate.
- An independently staged receiver projects exact reports/pins using registered
  aliases and materialized paper lifetimes, preserving external edits and caller
  rollback. A 150-case component/shared-guard/wire/graph selection passes. Runtime
  schema, writer, client, service admission and UI registration are unchanged.
- The frozen full check completed with 8,849 Python passes, one optional native
  skip, 24 frontend passes and 535 mobile Node passes; all 13 mobile Python
  integration programs exited successfully. Its 1,622 input hashes stayed exact.
  The native skip was reproduced: the snapshot lacks the vendored KaTeX asset.
  A separate local Windows WebEngine test with the assets passes (one case).
  Later changes (including archive performance and private connection boundaries)
  still require a matching final full gate. No new commit, release or installed
  update is claimed.

</details>

See [the exact continuation ledger](testing/continuation-20261112.md) for receipts,
failures, overlapping selections, remaining gates and Claude integration notes.
Formal private onboarding/hosting, native credential prompts, full platform
packaging and installed Windows/Mac/iPhone/Android acceptance remain open.

A further local backup performance fix applies the existing operation-local
schema metadata scope to create, inspect and detached restore. Its real-archive,
provenance, alias and note-continuity selection passes 89 cases; every row/hash is
still checked. This change is after the completed full-check freeze and therefore
requires final full validation. See the continuation ledger for the diagnostic,
RED reproduction, exact scope and timings.

## Remaining implementation, separate from release checks

The candidate is not waiting only for a green suite or cloud credentials.
Lineage is now registered in `ai_profiles.TASKS`; the actual desktop research menu
opens its saved-first reader and explicit analysis workflow. Native publication,
all-source pins, receive projection, conflict handling and mobile saved display
have local integration evidence. This supersedes the earlier inactive staged
workflow checkpoint, not the remaining release acceptance gates.

Remaining Lineage integration includes source-complete package import into an
already enrolled workspace, reviewed adoption of older retained results, mobile
exact-source controls and installed-device acceptance. The unbound package
publisher deliberately rejects a synchronized receiver; removing that guard is
not an implementation. A live importer must use reviewed receiver mappings and
one observed transaction for new source operations, scientific content and retry
receipts, while preserving current research and source lifetimes. See
[the current package boundary](enrolled-package-import.md) and
[the activation contract](grounded-lineage-producer.md). Native first-enrollment
and fresh editable-recovery evidence do not establish arbitrary live import.
A bounded raw completion cancelled before quote verification is still process-owned;
durable pending-verification recovery also remains open. Task registration alone,
templates, or displaying a process-owned report does not satisfy the feature.

Other remaining scope includes the complete analysis audit and unsupported
research-format/writer/recovery variants described in the roadmap and typed
contracts. Each requires current source-level evidence before closing it.
Native installers, hosted service operation and installed Windows/Mac/phone
acceptance remain additional gates after implementation and full validation.

## Historical maintenance reconciliation

### Maintenance integration and Mac candidate gate

The isolated candidate is being reconciled with master `1b44466`. Native citation
actions, core-claim note cards, empty reading-link caching and editable unanswered
questions have been restored without abandoning the v0.5 workspace ownership and
transaction guards. Background-rendered question cards now retain the same retry
action as the reader contract. The retry/render selection passes 84 cases; this
does not replace the full check, which is running again after the integration fix.

See [the exact reconciliation ledger](testing/master-reconciliation-20261105.md)
for failed gates, targeted fixes and counts. Merge ancestry, a green full check,
native macOS arm64 packaging and physical-device acceptance remain distinct gates.
No v0.5 installer is certified or published yet. The existing master 0.4.6 Mac
artifact is only a maintenance comparison and must not be labeled v0.5.

## Previous work: actual recovered and remote highlight native continuation

The actual review entry now has bilingual recovery/adoption, source A/current B,
two historical variants, private saves/reopen, confirmation, full-group remote
sync and resolved-conflict controls evidence. Held recovered-original close and
another accepted decision during native verification preserve private words and
never grant late Apply. The suspected nested remote-state concern did not require
product changes; actual reopen controls already enforce the closed decision.

The maintained selection passes **6 new cases in79.09s**, privacy/Ruff
green with no failures/errors/skips/input drift. All1155 inputs from the preceding
130-case gate remain byte-identical; this adds one test file, not a new whole-app
pass. [Actual actions and limits](testing/highlight-native-continuation-scenarios.md).
The isolated catalog explains333 functions/605 cases. Cancelled-result
sidecar native entry, highlight tools, audit/formats, canonical integration,
whole check/installers, production and installed-device acceptance remain open.

## Previous work: native highlight revision and safe review-window retirement

Actual bilingual quote/reason/role fields now save private variants, inspect the
correct original, verify all quotes and confirm whole-group application. Later
typing, failed saves/decisions, held cancellation/close, explicit restoration,
native shortcuts and compact layouts have executed Qt evidence. Existing claim,
retained-original and review flows are included in the same frozen selection.

**130 related cases pass (24 new), 706.7s; privacy/Ruff green, zero
failures/errors/skips/input drift.** [Human actions, groups and screenshots](testing/highlight-native-editor-scenarios.md).
The previous59-pass/one-failure visibility and64-pass/one-teardown-error cleanup
regressions are fixed in code without changing old tests. Earlier native aborts
remain recorded, not counted as passes.
The isolated catalog explains329 functions/599 cases; other inventory
is undocumented. These are selected checks, not a whole-application or installer pass.

Recovered/remote native entry journeys, highlight CLI/MCP, complete derived-link
audit, remaining formats, canonical integration, whole check, installers, production
and installed Windows/Mac/phone acceptance remain open. No daily app replacement.

## Previous work: confirmed complete highlight groups and real local continuation

The backend now atomically saves the exact private words, original ownership,
analysis, complete mark group, outbox and decision receipt. Manual and hidden
choices survive; deleted items require explicit restoration. Captured final-state
checks, cancellation, source/native changes, concurrent/lost-reply retries and
late callback mutations are covered. B stays selected. Actual recovery without
old paths, remote-analysis resolution, offline peer hiding/notes and second backup
pass in the related selection.

The frozen maintained focused gate passes **269 cases (38 new)** in614.83s,
privacy/Ruff green, zero failures/errors/skips/input drift. Existing analysis,
manual-mark, private/revision, reading-link and review/backup records are included.
[Actions, group times and limits](testing/highlight-application-scenarios.md).
Native highlight editing, CLI/MCP, complete derived-link audit, remaining formats,
whole check, canonical integration, installers, production and devices remain open.
The isolated catalog explains312 functions/575 cases. No release.

## Previous work: exact highlight originals, separate from publication

Backend verification stages/rechecks A, matches producer page provenance and
rebuilds complete edited quote locations while current B stays selected. Unresolved
quotes retain issues and no partial mark plan. Independent owned-original reads
remain available after analysis/visibility changes, with exact private references,
native/retirement guards and no modification grant. Recovered A can be read/verified
with the old folder unavailable. The common read boundary preserves claim adapters.

The frozen maintained focused gate passes **121 cases (17 new)** in809.14s;
privacy/Ruff green, zero failures/errors/skips/input drift. Existing claim original
Qt/CLI/official MCP, text/note original and private-format/core paths are included.
Old tests/Main/scripts/mobile are preserved. [Actions/results](testing/highlight-verification-scenarios.md)
and [source contract](highlight-source-verification.md).

This remains backend work. Atomic Apply, native highlight controls, highlight
CLI/MCP and complete offline-peer/rebackup remain open. The isolated catalog
explains292 functions/537 cases. Full check, canonical product integration,
installers, production and installed devices remain required. No commit/push/release.

## Previous work: durable private highlight continuation

Typed receiver selection and two private variants now survive restart through the
shared review journal. Complete analysis/AI marks and manual-set observations retain
stale human content, without a research/outbox write or generic Apply capability.
Independent backup/read-only recovery/editable adoption works without the old folder.
Actual reference-service conflicts support offline private edits; lone marks refuse.
Retired material work no longer clears a newer source's queued Browse request.

The frozen maintained focused gate passes **196 cases (45 new)** in544.69s;
privacy/Ruff green, zero failures/errors/skips/input drift. Existing claim/private
draft/history recovery, grouped annotation and material/original paths are included.
No existing tests/Main/scripts/mobile changed. [Executed actions](testing/highlight-private-scenarios.md)
and [private-state contract](highlight-draft-private-state.md).

This is backend private state. Original verification/inspection, transactional Apply,
native controls, CLI/MCP and complete peer/offline/second-backup journeys remain open.
The isolated catalog explains279 functions/520 cases; other inventory is still
undocumented. Full check, canonical product integration, installers, production and
installed devices remain required. No commit/push/release or daily-app replacement.

## Previous work: highlight revision core and material navigation

The shared original-snapshot quote locator and manual highlight revision core are
implemented. Complete-group proposals retain coverage provenance and selectable
original anchors; missing/ambiguous passages do not become partial mark groups.
The core is not connected to durable typed drafts, native Apply or transport tools.
Owned-reader Browse now waits for its collection and respects subsequent navigation;
legacy current-mark preview never bypasses a failed research owner.

The frozen maintained focused gate passes **318 cases (43 new)** in535.09s;
privacy/Ruff green, zero failures/errors/skips/input drift. It includes prior source,
claim/highlight, manual-mark, material-reader and independent-original interactions.
No existing tests/scripts/mobile changed. Main's highlight entry delegates its jump
to the owned collection lane; all unrelated Main work is retained.
[User actions and scope](testing/highlight-revision-scenarios.md) ·
[Remaining integration contract](highlight-draft-continuation.md).

Reviewed explanations now cover256 functions/475 cases in the isolated
catalog. Other inventory, canonical product integration, the full gate, installers,
production and installed-device acceptance remain required. No commit/push/release.

## Previous work: parent review decision continuity

Original inventory items now project the latest local direct/typed decision.
Closing the actual claim editor requests one bounded read-only status refresh;
the same row updates without rebuilding editors or moving selection, focus,
cursor or scroll. Local labels explicitly do not assert synchronization.
Failure exposes an explicit retry; native replacement/close refuses late delivery.
Metadata writes permit at most one reread. No model or research write is involved.

The frozen maintained focused gate passes **114 cases (25 new)** in482.22s,
privacy/Ruff green, zero failures/errors/skips/input drift. Includes existing
review/draft, compound, remote-claim, CLI/official MCP, historical/deck entry paths.
Only research_review.py and desktop/review_dialog.py changed among prior source;
new metadata helper and two test files. Old tests/Main/scripts/mobile are preserved.
[Actions, actual image, per-group times and limits](testing/parent-review-scenarios.md).

The display-only fence treats zero-byte WAL lifecycle as neutral while retaining
full database/nonempty-WAL versions. A real uncheckpointed write is tested with
unchanged database bytes. Source proofs and Apply/sync authority retain their
independent verification. It is not a general permission to weaken source fences.

The catalog adds15 functions/25 cases with bilingual action/outcome/limit prose;
226 functions/432 cases now explained. Remaining inventory is still undocumented.
Remaining typed formats, whole-app checks, canonical product integration,
installers, production and installed devices stay required.

## Previous work: independently owned originals after a decision

Claim originals remain readable after Apply or conflict closure, without reviving
application authority. Native unsaved text can retain its immutable source scope;
transports require an exact saved draft revision. Owned sources and complete
recovered private sources are checked independently of current claim heads/PDF B.
Retirement, native replacement and modified bytes refuse without fallback.
The existing verified path remains for fresh sources needing source staging.

Actual Qt controls cover both languages/renderers, retry, dirty text, repeated
activation, worker recheck, source retirement and held edit/close/render. Actual CLI
processes and the official MCP SDK cover restart and reading after Apply.
The frozen maintained focused gate passes **151 cases (22 new)** in887.11s;
privacy/Ruff green, zero failures/errors/skips/input drift. Existing source viewers,
claim editors and local tools are included. No prior tests/Main/scripts/mobile changed.
[Actions and exact results](testing/claim-original-reading-scenarios.md).

The integration catalog adds18 source-pinned bilingual explanations for22 cases;
211 functions/407 cases now have prose. Remaining inventory remains undocumented.
Parent review-list refresh, remaining typed formats, whole-app checks, canonical
product integration, installers, production and physical devices remain required.

## Previous work: native remote/cancelled-result workflows

Actual bilingual Qt entry now covers remote conflicts and completed cancelled
results: edit, source inspection, Cancel/Yes, sync/reopen, private edit/copy/save,
held cancellation/parent close and another device deciding first. Known stale/
applied drafts require explicit review; pending and closed conflicts have separate
guidance and cannot produce another decision. The backend still checks authority.

The maintained focused check passes **58 cases (8 new)** in256.09s, with
privacy/Ruff green and zero failures/errors/skips/input drift. Existing native
claim/review/source interactions are included. No previous tests, Main, backend,
scripts or mobile changed. Actual980/620px synthetic screenshots are retained.
[Actions and screenshots](testing/claim-continuity-scenarios.md).

Remaining formats, broader interruptions/UX, complete application checks, canonical
product integration, installers, production and physical devices remain required.

## Previous work: actual offline remote-claim resolution and recovery

A real two-database conflict now supports private offline claim review, client
recreation, return sync, conflict closure on both peers, independent backup and
editable adoption with original A and selected PDF B preserved. Completed cancelled
results also remain discoverable/editable. Version2 private observations capture
the full remote conflict; version1 remote drafts retain text but require explicit
reselection. Shared missing/unconfigured PDF checks no longer falsely reject.

The maintained focused check passes **111 cases (10 new)** in524.53s:
privacy/Ruff green, zero failures/errors/skips and no frozen input drift. Includes
private/canonical claim paths, existing Qt editing, CLI/MCP and note/source viewers.
No old tests changed. Dedicated native-button journeys were not covered at that
snapshot; see the newer native results above. Other formats/interruptions, the
complete gate, canonical integration, installers, production and devices remain required.
[Executed data journeys](testing/claim-continuity-scenarios.md) ·
[Contract and compatibility](claim-conflict-continuity.md).

## Previous work: shared claim CLI/MCP and interacting regression

Nine `review.claims.*` tools now share the typed native review service and the
owner-bound private/decision journal. The initial maintained focused run recorded
**101 passed, one failed** in446.92s, stopping at an outdated packaged-tool inventory.
After extending that inventory, **49 related/unreached cases pass** in30.69s.
Product source stayed unchanged; earlier claim/note/native cases were not all rerun.
Both runs have privacy/Ruff green and no input drift. Keep these separate receipts;
do not add overlapping counts or claim a single whole-application pass.
The combined selection exercises actual CLI processes, official MCP restart,
existing notes/transports, native claim application/UI, imports, audit and OS locks.

An accepted retry now returns its committed outcome before waiting for unrelated
source work; a new failed-before/fixed-after case pins this behavior. New pending
requests still inspect original ownership under the OS source lock. Two existing
numeric expectations expand discovery from17 to26 tools, and the packaged
inventory gains nine explicit names; old operation/retry/restart assertions remain.
[Executed actions](testing/claim-review-operation-scenarios.md)
and [operation contract](local-claim-review.md).

Those sidecar/remote/offline claim journeys were not yet executed at this snapshot;
see the newer continuity evidence above. Remaining typed formats, canonical product
integration, the complete gate, installers, production and devices stay required.

## Previous work: native structured claim editing

The isolated integration UI now exposes explicit target selection, editable claim/
reason/quote fields, private variants/restart, original verification and confirmed
Apply. The shared viewer inspects A while primary B remains selected. Background
autosave retains later typing; cancellation/close/failure and native replacement
have actual Qt coverage. Matching interaction gate: **60 passed (20 new)**,
263.97s runner, zero input drift/failures/errors/skips.
[Human actions and real synthetic screenshots](testing/claim-draft-application-scenarios.md).

The preceding backend231-case gate covers atomic publication and independent
recovery/local offline-peer note/rebackup. It is historical, not another current
whole-application pass. Claim CLI/MCP was still pending at that snapshot; actual sidecar/remote editing and offline claim
editing and remaining release requirements stay open. [Contract](claim-draft-application.md).
No canonical product replacement, installer or release.

## Previous foundation: private structured claim continuation

Receiver selection, private save/load, restart and independent recovery retain
original baselines without granting write authority. The prior 93-case gate is
historical; overlapping tests are rerun only within the selection above.
[Private-state contract](claim-draft-private-state.md).

## Previous foundation: structured claim revision core

A closed claim-edit proposal format binds the full baseline and original source;
manual revisions rebuild all quote locations/IDs from captured A, retain missing
and ambiguous states, and never grant publication or semantic support. Backend
metadata marks manual work, without a model call. The selected core/source/schema
gate passes **113 cases (22 new)**, 93.44s, with unchanged 979 inputs.
[Actual actions and limits](testing/claim-draft-revision-scenarios.md).

This is an internal foundation. Typed receiver selection, durable private drafts,
atomic Apply and the desktop editor are not yet connected; the full recovery
journey remains required. [Integration contract](claim-draft-resumption.md).

## Previous candidate: offline workspace startup and usable headers

PWA reload restores an existing cached workspace, selected paper, drafts and
outbox without credentials or automatic service calls. Missing/corrupt scopes
refuse without empty initialization. Explicit demo choice clears only the hint.
Headers keep whole labels / 44 px targets in both languages at 320/390/600/1100 px,
with keyboard dialogs and reduced motion. The final maintained mobile gate passes
535 unit cases and all 13 HTTP scenario programs; eight real IndexedDB/startup groups
and the actual offline PWA journey pass. [Actions, screenshots and limits](testing/workspace-resume-scenarios.md).

Library papers with no selected list now also resume. Two new failing regressions
were repaired; later refreshes and explicit empty navigation retain the user choice.
The final matching selected gate is 48.50s with zero source drift.

This closes the previously recorded manual-reopen and narrow-header UX gaps.
Production identity, physical devices and the whole application gate remain open.

## Previous candidate: actual desktop/mobile text editing

Ordinary desktop text notes remain editable on the phone without losing creation
metadata; anchored/quotation notes remain read-only. Clean editors follow incoming
revisions, while genuine unsaved drafts keep their original observations and text.
Actual Qt/peer checks pass22; the final maintained mobile gate passes512 unit cases
and all13 HTTP scenario programs. Real PWA controls/IndexedDB cover offline reload,
manual workspace reopen, duplicate Save, another phone save after a desktop reply,
and protected unsaved text. [Actions, screenshots and limits](testing/plain-note-editing-scenarios.md).

The subsequent startup/header candidate above addresses manual reopen and label
wrapping; physical devices, production and the full application gate remain open.

## Previous candidate: independent note continuation

Two new full-flow scenarios pass (121.25s runner / 119.84s pytest): a private
public-operation draft survives backup, detached recovery, editable adoption,
fresh source inspection with old folders blocked, Apply and another backup;
an accepted note reaches a peer, is edited offline, survives client recreation,
syncs back and remains unchanged when the first device repeats its old Apply.
PDF A and selected PDF B stay distinct; private drafts and runtime receipts are
not replicated. [Actual journeys and limits](testing/note-continuity-scenarios.md).

The only added Python input is this journey test; all 975 inputs from the previous
88-case selection are byte-identical. That selection was not rerun or relabeled
as a current whole-application pass. Physical devices and production remain gated.

## Previous candidate: shared recovered-note operations

Desktop, JSON CLI and local stdio MCP now share explicit historical-note target
selection, durable private drafts, bounded original references and atomic Apply
with private state and retry receipts. Actual CLI processes and the official MCP
SDK cover restart/reconnect, source words, duplicate requests, late private edits,
native database replacement and read-only recovery. The current interacting
selection is **88 passed** in 720.97s, including 13 new cases;
zero source drift, failures, errors or skips. This is not a complete application pass.
[Actions and results](testing/local-note-review-scenarios.md) ·
[Operation contract](local-note-review.md).

The earlier 12/13 run failed on an empty assertion in a new test. It now compares
the complete replacement logical database, preserving all safety expectations.
The normal public backup/adoption and peer paths are now covered as described
above; other interruption/format combinations remain unaccepted. Runtime retry
receipts are not transferable authority.

## Previous candidate: explicit source and passage choices

Recovered notes can explicitly choose a native PDF/passage or become source-less
manual notes. Original unknown attribution survives separately from the new choice
through private saves, restart, accepted peer transfer and repeated backup/adoption.
English/Chinese Qt controls preserve manual edits, show the fitted original and
require final source/target confirmation. The selected new behavior gate is **22
passed**, 170.55s pytest / 172.06s runner, same969 inputs and zero drift/failure/skip.
See [actual actions, elapsed times and screenshots](testing/note-source-mapping-scenarios.md).

The broader selected 85-case interaction run found three failures. They were fixed
and their existing cases passed targeted rechecks; that is not a new full85 pass.
Source-less reading, existing original viewers and source ownership remain independent
of AI accounts. Pending private saves finish before initial original capture; closed
reviews do not turn shutdown into recoverable source selection. Invalid presentation
closure refuses backup with its supported recovery error.

## Previous candidate: typed note-draft continuation

Recover a real note conflict and both human variants, explicitly choose a receiver note,
save privately, restart, verify original A, inspect A while B stays selected, confirm and
apply once. Receiver note ID, paper and creation identity are protected; reviewed
body/kind/page/anchor travel together. Source-less notes never inherit B's attribution.
Notes use their own closed observations, not a fabricated generation-table context.
Text and notes share source staging after independently validating their typed bases.

Editable adoption retains complete old backup groups without reactivating old jobs.
The review reader now discovers their saved drafts in both editable and detached copies,
including a second backup/restore. A private cached PDF is usable only when the complete
validated recovered group actually contains that immutable draft; current store binding,
complete metadata and exact bytes must agree. Known deleted originals still refuse.
Source ownership, rich note, outbox and decision receipt commit in one transaction.

Earlier frozen selected gates (before the source-choice candidate): **21 passed** for source location/store boundaries (350.86s); **56 passed** for text/note/source/UI interactions (573.89s). Same960 inputs, zero drift/failure/error/skip. These are selected checks, not a complete app pass.

New safeguards validate actual selectable word endpoints, retain native private-cache owner observations through Apply and read-only revalidation, and revoke old application permission when explicit rechecking fails. Versionless positioned notes remain private/unresolved; source-less plain notes stay supported. Unrelated index writes can revalidate the same A without a new target. [Executed action results and times](testing/note-source-check-results.md).

Actual English/Chinese Qt controls cover explicit target selection, source labels/opening,
private edits, Cancel/Yes, duplicate activation, reopen and held close/switch. The local
reference-service journey also transfers the accepted note and A, retains B, and verifies
a second independent backup. [Actions, outcomes and synthetic screenshots](testing/note-resumption-scenarios.md).
Earlier new-fixture errors are recorded: another preexisting note, required observed-save
semantics, explicit restoration and UUID-dependent first-row selection. Corrected fixtures
retain the original expected behavior; all older test inputs remain unchanged.

## Remaining release requirements

| Researcher outcome | Local candidate | Still required |
| --- | --- | --- |
| Windows/Mac continuation | Shared operations, offline queues/retry, conflicts and device controls | Every writer/history/source format; production identity/service; installed-device round trip |
| Independent recovery | Text/note resumption, supported histories, PDFs and editable decks | Remaining typed/structured formats and recovery boundaries; complete migration/peer journey |
| Mobile reading | PWA reading, notes and service fixtures | Physical iPhone/Android offline/restart/reconnect and desktop convergence |
| Grounded research | List goals, source-bound claims, bounded audit/appraisal, local native Lineage and source-complete enrolled import | Reviewed Lineage replacement/adoption, complete durable audit/consistency output, remaining sharing/sync continuity and expert review |
| Public distribution | Maintenance update/diagnostic foundations | Matching full checks, platform installers, production operations and device acceptance |

Basic missing/changed-provenance and actual page/word controls now have selected coverage.
The note contract still requires deeper nested/size controls, additional source-reference recovery/ownership variations, source-choice
and cross-paper/parent lifecycle variations and remaining integration coverage.
Remaining claim/history and recovered/remote native highlight journeys, installed transports and deck-specific draft resumption remain open. Existing selected passes do
not close these requirements or the [full roadmap](roadmap-0.5.0.md).

## Full check remains failed

Last default `scripts/check.py`: Privacy/Ruff passed, 392 Python cases passed, one failed
at missing `cites.analyse_result`; 467.486 seconds total. Frontend/mobile were not reached.
The API has focused repair evidence, but the unchanged automatic-fill assertion still
expects ten citations whereas current behavior retains one and reports a partial result.
Completion/source policy and missing-section continuation remain unresolved; no older
expectation was loosened. Do not restart this known-red full gate merely for a new number.
A matching complete green gate is mandatory before commit, push or release.

Last complete inventory snapshot: 8,230 cases / 4,600 functions / 577 files.
The subsequent 22 claim-revision, 22 private-storage, 22 application/reader and 20 native-editor cases are separate and not recollected into that snapshot.
Reviewed explanations: 329 functions / 599 cases in the isolated candidate; other cases remain undocumented.

Collection discovers names without executing bodies. The explanation report now opens
with reviewed prose selected; undocumented inventory remains available. Percentages
describe one invocation's phase, not completion, time remaining or scholarly quality.
No installed Mac/phone, real AI account/model, production cloud or expert research check
was performed. Hosting, identity/pairing, operator/storage/retention/recovery choices and
the Windows → offline Apple Silicon Mac → phone → desktop journey remain mandatory.


## Local authority backup export and inspection (2026-11-14)

The development candidate adds explicit operator `sync-admin backup` and
`verify-backup` operations. SQLite backup APIs capture committed WAL state under
a bounded writer reservation; streamed committed objects, retained-event closure,
private output and final completion publication have isolated behavior coverage.
See [operator workflow and limitations](sync-authority-backup.md) and the
[scenario map](testing/authority-backup-scenarios.md). This is not cloud backup,
restore, a coherent full-check pass or installed-device/release acceptance.


## Local fresh-identity authority recovery (2026-11-14)

An explicit operator command reconstructs one backup workspace into a new service
folder with a fresh workspace ID. It preserves accepted/conflict outcomes, head
revisions and graph lifetimes, revalidates all committed bytes, re-keys verified
ordering scope hashes and drops old sessions before final publication. See
[recovery workflow](sync-authority-restore.md) and [behavior scenarios](testing/authority-restore-scenarios.md).
Cloud operations, automatic newer-client migration, installed-device acceptance
and the coherent full check remain open; this is not a release/deployment claim.


## Exact-content legacy Lineage adoption (2026-11-14)

The source-complete package review can explicitly include an identical private
saved analysis in native sync while preserving its full row, model metadata,
original timestamp and exact sources. The sealed choice binds actual selected
paper lifetimes and refuses any known native journal/graph/marker/history.
The generic projection guard remains unchanged. See [workflow and scope](lineage-matching-adoption.md)
and [behavior map](testing/lineage-matching-adoption-scenarios.md). Direct adoption
without a matching original-complete package, native corruption repair, complete
audit and full/release/hosted/installed-device acceptance remain open gates.


## Local GCS publication adapter (2026-11-14)

An explicit source-only operator command validates a private bucket and publishes
verified immutable shared content before a snapshot's completion manifest. It
supports safe exact retry, generation checks, bounded progress/cancellation and
cross-snapshot PDF reuse. The SDK and headless setup are locked and separated from
client runtime packaging. See [workflow and remaining gates](gcp-backup-publication.md)
and [scenarios](testing/gcs-backup-scenarios.md). All cloud tests use simulated
clients; real GCS/hosting, remote fetch/restore, scheduling/retention and the full
application/installed-device acceptance remain open. No deployment is claimed.

### Private cloud backup retrieval (local)

Exact-snapshot operator retrieval now checks bounded raw downloads and authority/attachment closure before publishing a local completion marker. Real SDK in-memory transport scenarios include fresh-workspace restore with conflicts and PDF bytes. Real GCP, full-suite and installed-device acceptance remain open. See [retrieval](gcp-backup-retrieval.md).

### Old-device recovery visibility (local)

A read-only device/authority-backup comparison now shows work absent from the selected backup without resetting old identities or journal entries. A collapsed Advanced desktop action uses the common service and guarded worker lifecycle. [Workflow](device-recovery-review.md). Automatic/per-change reconciliation, complete preservation and installed recovery acceptance remain open.

### Direct private Lineage adoption (local)

The saved reader now supports explicit original selection, byte/page/located-quote verification and separate confirmation to include an unchanged private report in sync. The common transaction retains source grants, science/history, outbox and retry receipt. It creates no list or new AI result. [Workflow](lineage-direct-adoption.md). This closes the direct source-selection implementation gap for supported current private rows; native corruption, unknown legacy migrations, full and installed/hosted acceptance remain open.
