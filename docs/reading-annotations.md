# Reading annotation integration

Status: isolated implementation in progress, not merged or enabled in the app.
ADR 0012 remains the release contract; this document records current evidence.

## Implemented in this worktree

- Closed Python and JavaScript bodies for highlight analyses, explanation links
  and research questions, with shared Unicode/page/unknown-field fixtures.
- Canonical singleton SQL tables and typed `research_content` projection. New
  tables install in caller-owned transactions; explicit repeat capture installation
  migrates an already bound schema and installs the corresponding triggers.
- Optional table registration for sharing bundles and detached recovery. Old
  archives without these tables restore into the current schema. New rows retain
  their exact business JSON, input digest and timestamp without provider receipts.
- Read-only mobile cards show questions, reasons, original quotes and explanation
  links using text nodes. The annotation module belongs to the offline shell.

Evidence: 52 Python contract/archive/content tests passed. The complete mobile
check passed 114 Node cases and both existing actual Python HTTP scenarios. Those
HTTP scenarios still cover their prior research/QA payloads; a dedicated actual
annotation producer-to-HTTP scenario remains required. No existing assertion was
removed or weakened. The generic all-feature fixture was extended with valid
bodies for the three newly enumerated feature types instead of accepting null.

## Next actual producer boundary

1. Introduce an explicit workspace-bound annotation operation alongside the
   standalone legacy helpers. The app captures database identity and the effective
   AI route before preparation; publication never consults a later global target.
2. Add the three tables to the closed generation registry with readers capturing
   the actual relevant analyses. For questions these are dive and close-reading
   bodies; bind the verified source PDF used to extract pages outside the SQL lock.
3. Split model-only question production from persistence. The actual desktop
   entry point supplies the original operation context. Completed output is
   accepted against that context or retained; failures preserve useful saved
   questions, and a delivery retry never invokes the model again.
4. Treat SQL as authoritative when present or canonically deleted. Compatibility
   cache writes occur only after acceptance and are repairable. Existing legacy
   cache adoption needs a bounded, explicit migration contract; never infer a
   historical parent epoch merely from its filename or recreate deleted data.
5. Wire highlight preparation and generated PDF marks as one typed publication
   group when the action promises both. Explanation-link generation is a separate
   dependency phase with truthful partial status. Preserve hidden/manual marks.
6. Carry source version and lifecycle through manual highlight add/remove. Add
   actual worker races, duplicate jobs, workspace/account changes, source changes,
   cache/storage failures and migration/tombstone tests before integration.

The question producer and its actual desktop/analysis entrypoints are now wired
in this isolated snapshot, as recorded below. Highlight and reading-link producers
still use their earlier paths. Do not enable annotation synchronization based only on these contract
checks. Full merged checks, exact artifact closure and physical-device acceptance
remain release gates.


## Observed question producer evidence

`research_question_jobs.QuestionJob` now captures the original database identity,
paper lifecycle, target/analysis revisions and AI connection before PDF preparation.
It reads a verified original PDF, calls the existing grounded model validator and
publishes the bounded business row through the shared generation transaction.
Changed analyses, target or PDF retain the generated result; SQL failures retain
typed sidecars and retry receipts without another provider call. Model-only
production is factored out of the legacy helper without changing its public result.

The first producer and legacy selection passed 26 tests. The actual HTTP fixture
now generates questions, sends them to another desktop and the JavaScript reader,
and verifies exact business fields/source hash after offline reopen. This does not
claim the phone downloaded the original PDF bytes or native-device acceptance.

Desktop/analysis entrypoints and canonical read preference are now switched in
this isolated worktree. Explicit legacy adoption, complete source closure and
grouped highlight/link producers remain required.
Do not treat this isolated producer as completed application-wide enrollment.


### Portable source-PDF identity refinement

The first producer tests exposed a portability gap: the input digest is not the
PDF digest, and private generation receipts do not travel in an ordinary sharing
bundle. Each annotation table now retains nullable `document_hash` explicitly.
It must equal the outer sync source hash; null means unknown, not the current PDF.
ADR 0012 is refined accordingly. This schema is isolated/unreleased, not a migration
of a shipped annotation table. Complete backup must include referenced original
bytes; the row alone cannot establish availability.

The source-aware producer/bundle/contract selection passed 68 tests. The expanded
contract selection passed 31 tests, overlapping the previous run. The mobile suite
passed 117 tests and both actual HTTP scenarios, including desktop question
production, two desktop projections, source identity and offline reopen. Earlier
same-binding versus rebound replacement fixtures passed 88 related cases before
this schema refinement; those counts are not additive and not a full-check claim.

Actual list-package tests preserve the generated question's PDF hash and original
PDF bytes through export/import in both unbound and enrolled workspaces. Existing
expectations were retained; new fixtures were corrected to model the intended
binding and supply the current wire fields/identity arguments.

Next integration must make canonical reading/deletion authoritative, carry the
PDF hash into desktop source navigation, and define explicit legacy adoption
without importing orphan caches. The root full check is testing a different,
frozen review/QA/slide batch; it does not cover this isolated annotation tree.

## Workspace-aware question browser - isolated checkpoint

The actual desktop reader now supplies its database explicitly. Canonical saved
questions and canonical deletion markers are authoritative; viewing them does not
consult AI accounts or regenerate content. A bounded legacy cache remains an
explicitly unverified preview. Unknown source versions cannot request a PDF jump;
known source jumps carry the exact original PDF hash into the reader's existing
source-version guard. Reading an unavailable database shows a retryable message,
preserves the same view and draft, and does not launch generation.

Question updates capture the route and workspace before worker dispatch. Rapid
repeat activation creates one job; callbacks from an earlier paper, workspace or
load epoch cannot repaint the current view. A failed update preserves prior
questions and shows the actual failure, including when displaying legacy content.
The analysis pipeline uses the same explicit operation. Canonical annotation
transactions invalidate normal workspace polling; rolled-back changes do not.

Evidence: 72 combined producer, legacy, reader and desktop cases passed in
63.36 seconds, including 11 new workspace UI scenarios. Counts overlap earlier
runs; this is not a full-check or merged-root claim. A separate root full check
found a retained-QA toolbar height regression; its fix stays on root and must be
preserved when applying the tiny main.py caller change from this worktree.

Remaining gates: explicit verified adoption of old cache content without AI,
unexpected non-storage exception delivery after model completion, compatibility
cache repair policy, grouped highlight/mark publication, explanation-link and
manual-highlight producers, complete backup closure and the merged full suite.
No native device, live account or real research database was exercised here.


### Explicit legacy question adoption operation

`question_legacy_adoption.prepare` builds an immutable preview without AI or
account lookup. It requires the exact original input digest, a currently verified
PDF, matching quoted text/page and the captured analysis bodies. Preparing does
not adopt or rewrite the old cache. Explicit `adopt` uses the captured generation
boundary; repeated acceptance returns the same receipt, while changed inputs,
source or a later canonical deletion retain a candidate instead of overwriting.
The current adoption records current provenance; it does not claim the old cache's
historical parent identity. The question input snapshot now observes the canonical
authority marker so an insert/delete between preview and acceptance is visible.

Evidence: 68 combined adoption/producer/reader/UI tests passed in 41.83 seconds,
including 20 new adoption cases across enrolled and unbound workspaces and an
actual legacy-helper-to-adoption journey requiring only the first fake model call.
Initial failures were new fixture construction errors: enrolled edits must use
observed writes, and a deliberately missing parent must be injected with capture
functions registered rather than issuing unsupported enrolled parent deletion.
All original behavioral assertions were preserved. The desktop preview/accept
entrypoint is still required before claiming end-user legacy migration support.
This isolated source has not passed the complete project check or been merged.


## Atomic highlight layer and canonical readers - isolated checkpoint

The actual model-only highlight producer now has a workspace-bound `HighlightJob`.
It captures the account route, original database/lifecycle, existing marks and
graph observations before work. It reads the exact verified PDF, resolves selected
quotes into raw word anchors and publishes canonical analysis, marks, outbox and
the generation receipt in one transaction. The closed receipt includes the located
mark plan; a failure after the analysis write rolls everything back and preserves
the complete result outside the database. Changed PDF/input/hidden preferences
retain a candidate. Repeated completion does not call a model or add another row.

Old mark rows retain hidden preferences instead of being deleted during selection
changes. Current visibility also checks membership in the current selected quotes,
not just input/PDF hashes: identical inputs can produce a different output set.
The mobile projection hides omitted historical marks and canonical deletions while
leaving manual marks independent. This is a tested local distinction, not a claim
that an input hash is a universal output-version identifier.

The question-adoption UI is now integrated in this worktree. The first combined
run exposed two 600px cases: the full hash label forced a 790px minimum width.
The label now wraps within its allocation and action buttons use a flow layout.
No existing size assertion was relaxed; the original combined suite plus new
responsive cases passed 140 tests. No live account or native platform check ran.

Evidence before the final canonical-reader refactor: 22 highlight generation
cases passed; the broader generation/lifecycle/question/link/archive selection
passed 147 cases. Counts overlap. All 119 mobile tests passed after the active-mark
filter. Ruff passed. The new `annotation_reader.saved` supports bounded read-only
access to all three canonical features, with known deletion distinct from absence;
its fresh combined verification is recorded separately after completion.

Integration is deliberately incomplete: actual highlight/material/deep-explanation
entrypoints still use the legacy path. Before enabling this writer, implement the
typed grouped review adapter (the generic single-row review must not apply only
the analysis), complete source closure with the newer root backup layer, connect
the two-stage highlight/link workflow and canonical readers, merge the observed
manual-mark hooks, and run the complete merged suite. The single-row review and
explicit-target paths need grouped handling; the new registry entry is not proof
of that coverage. Do not merge this tree as a finished annotation feature.

The canonical root is a separate 626-file verified snapshot: 2,884 Python/desktop,
18 frontend, 91 mobile and two actual HTTP scenarios passed. Its safe restart was
checked by process lifecycle and empty error logs, not native visual acceptance.
This isolated tree has not passed the full check and is not running the user's app.
