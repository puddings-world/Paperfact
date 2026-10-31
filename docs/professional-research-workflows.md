# Professional research workflows for v0.5

Status: in development, 2026-10-30. Task drafting, per-list purposes and a bounded
claim-extraction workflow are implemented in the local candidate. This document
distinguishes those operations from optional future agents and release gates.
It does not expand the v0.5 release into autonomous experimentation.

## Product outcome

Help a researcher decide what a paper establishes, whether its methods justify
its conclusions, and how it affects their own work. Keep reading, evidence,
interpretation and the researcher's judgment connected. Support empirical,
theoretical, qualitative, clinical and other research without imposing ML defaults.

## Evidence informing the design

These are representative documented workflows, not evidence of universal adoption
or independent endorsement of vendor accuracy claims.

- [Ai2 Asta agents](https://allenai.org/asta/agents): question framing, finding papers,
  evidence-backed synthesis and scientific-task evaluation. Reuse modular discovery
  and synthesis boundaries; keep researchers able to inspect and correct sources.
- [PaperQA2 engineering report](https://www.futurehouse.org/research/engineering-blog-journey-to-superhuman-performance-on-scientific-tasks):
  iterative query expansion, evidence gathering, citation traversal and answer
  synthesis. Adopt bounded search/evidence/review cycles; do not import benchmark
  performance claims as promises about Paperfact.
- [Elicit systematic-review workflow](https://support.elicit.com/en/articles/14759154-systematic-reviews-in-elicit):
  a review question, eligibility criteria, screening and structured extraction.
  Adopt explicit criteria and traceable extraction cells. An exploratory reading
  list is not automatically a systematic review or PRISMA-compliant search.

Primary references below were checked on 2026-10-30; the Asta agents page,
Asta interaction study and Elicit workflow were rechecked on 2026-10-31:

- [OpenScholar](https://arxiv.org/abs/2411.14199) documents retrieval, cited synthesis
  and a self-feedback loop. Reuse explicit evidence retrieval/validation boundaries;
  benchmark results do not certify this application's models or source coverage.
- The [Asta interaction study](https://arxiv.org/abs/2602.23335) reports users
  revisiting saved outputs and cited evidence nonlinearly. Our design inference is
  saved-first cards, stable source links and preserved drafts, rather than a
  compulsory linear wizard. This is not permission to copy its data-collection model.
- [PRISMA 2020](https://www.prisma-statement.org/prisma-2020) supplies systematic-review
  reporting checklists and flow diagrams. Preserve criteria, exclusion reasons and
  search history if building that optional workflow; ordinary exploratory lists
  must not be advertised as a completed systematic review.

## Reader-facing flow

1. Open a paper and see the original beside its saved explanation.
2. Choose a research task when useful, or type an ordinary question.
3. Review/edit the question and add the actual research purpose.
4. Send explicitly through the existing per-feature account/model route.
5. Inspect source passages; retain personal judgments separately from generated work.
6. Compare papers only after a user selects the corpus and comparison criteria.

Keep the default interface small. The first implementation adds one optional
**Research tasks** menu beside existing quick questions and makes the row wrap.
It previews an editable task before inserting a draft. Existing drafts require an
explicit replacement decision. Preview/cancel does not invoke AI, write research,
change routing, or create a background job. Stale previews never enter a different
paper/workspace. Existing Q&A publication/recovery semantics remain in charge.

The six implemented tasks are claim/evidence analysis, method appraisal,
figure/table interpretation, replication planning, research lineage and research
extensions. These are provider-independent drafting templates, not an autonomous
agent runtime. Prompt requests for quotations are not verified anchors and must
not receive a "verified" badge until the source validator accepts them.

## Study-design reading defaults

The default deep and close reading recipes are `2026-10-study-design`. They ask
for checks that fit the actual empirical, theoretical, qualitative or review
design. Dataset splits, baselines, backbones and training settings apply only
when the paper actually uses them. Reported datasets and evaluation metrics also
apply outside ML. Close reading keeps the paper's own section
order, exact quoted words and reported numbers; unavailable figures, proofs or
materials must not be invented. These instructions do not certify scientific
quality, formal verification or successful replication.

Contribution and reading questions can use observations, proofs, materials,
experiments or stated arguments. Question and highlight prompts ask for only
grounded useful items, without filling a quota. Candidate validation remains
strict: only an exact empty question array is handled as this run identifying no
supported questions, with a clear reason. Saved questions and the existing cached
failure/refresh behavior are preserved; no extra call or automatic retry is added.
Malformed, missing, scalar or null question data remains an error. A located
passage remains distinct from semantic support.

New deep/close writes carry the new recipe marker. Older saved text stays
readable, and ordinary reads and normal queued selection do not regenerate it.
Only the existing explicit rewrite/generate action can replace it. Highlight
format version 2 and question input-only cache identities are unchanged, so this
wording update alone does not invalidate saved cache content or trigger calls.
Fixture tests inspect actual producer requests, saved rows and cache reuse with
simulated responses; they test the prompt contract and application behavior,
not whether a real model produces valid science.

## Compare saved statements with the original

In the local v0.5 candidate, open **Research tasks > Check saved evidence >
Compare statements**. Opening reads local saved work; it does not call a model.
Choose one to eight saved outputs, inspect the Audit account/model and the
4,000-token output budget setting, then generate explicitly. Actual limits depend
on the service; current CLI adapters do not enforce this setting. One captured request
proposes source facts; local checks locate quotations and compare only explicitly
matching scopes. Both differing statements and their locations remain visible.
Rounding, derived values, unknown scope and absent reporting remain distinct.

The modeless view preserves question/note drafts while work drains. Its report is
temporary and copyable, not a saved research artifact or scientific certification.
Opening or changing the next model does not rewrite a completed report. Stop
keeps it while the view stays open; accepted close releases its source snapshot.
While comparison is pending, a bounded read-only recapture can accept unchanged
research inputs after a reading-state write, without another model call. Changes
to notes, source bindings or the actual original still reject delivery. Later
writes after acceptance can invalidate source navigation; idle continuity remains
separate work. See [the bounded review UI](source-fact-review-ui.md) and
[the fact extraction contract](source-fact-extraction.md).

## Professional analysis contract

| Component | Required content | Integrity rule |
|---|---|---|
| Research purpose | Per-list question, intended use, depth/background | User-owned; never overwritten by generated analysis |
| Claim | Author claim, supporting result, interpretation, scope | Separate supported text, inference and unresolved evidence |
| Source | Document identity/hash, passage, anchor, figure/table | Preserve exact source version; missing text/page remains missing |
| Method appraisal | Design, applicable assumptions, controls and uncertainty | Use study-type-appropriate checks; no universal numeric quality score |
| Result | Values, units, comparators, sample size, uncertainty | Unreported differs from zero; no inference from unseen figures |
| Limitations | Author-stated limitation versus reviewer inference | Show which evidence motivates an inference |
| Lineage | Prior gap, changed assumption, later development | Citation occurrence alone proves neither agreement nor influence |
| Reproduction | Materials, procedure, parameters, validation and missing inputs | A plan is not a successful replication; no implicit code execution |
| Research proposal | Hypothesis, falsifier, minimal test, resource needs | Label speculative proposals; novelty requires a separate literature search |

## Implemented bounded claim workflow (local candidate)

The optional **Review claims against the original** entry opens saved content
without login or AI calls. Explicit generation captures the selected Claims
account/model, paper lifetime, deep/close reading inputs and exact PDF snapshot.
One bounded completion proposes consequential assertions, limitations and quoted
passages; deterministic validation locates quotes or records missing/ambiguous
evidence. Empty output fails without replacing prior work. This does not prove
that a quotation semantically supports a proposed judgment.

Publication uses the existing observed-generation boundary. Concurrent edits,
paper/source changes or known deletion retain work for review. Restoring a
deleted set requires a separate default-Cancel confirmation and new incarnation;
force alone never restores it. Saved cards refresh off the GUI thread and never
replace unsent notes/questions. Source navigation verifies the actual loaded
original again; a current PDF is not substituted for a prior version.

The claim set and its declared original source survive supported list packages
and complete backups. Typed historical-source transfer and portable original-version
inspection have integrated fixture coverage. The viewer opens the exact old source
separately while preserving the current PDF and drafts. Generated/imported unbound
ownership and the copy-based enrollment UI also have fixture coverage. Remaining
chat/compound/review/file histories and editable recovery adoption are explicit
migration gates. Mobile displays
saved proposals and distinct verified original artifacts without AI execution;
physical-device offline acceptance remains open.

## Further bounded agent execution (proposed)

Use existing shared operations behind UI/CLI/MCP, not separate implementations.
An action captures the workspace, selected papers, document versions, research
purpose, account/model route and publication target before any remote call.

The researcher chooses a task; the application exposes its plan, stages and
budget. A bounded controller retrieves available source material, extracts typed
findings, validates identities/anchors, identifies evidence gaps and proposes a
small additional retrieval step. Unresolved evidence stays unresolved at the
budget limit. Multi-agent review is optional: two models agreeing does not prove
truth. A critique must point to inspectable evidence or a specific missing check.

- Preserve requested and returned model identities where available.
- Query capabilities rather than treating every text-completion adapter as a
  browser, visual PDF reader or tool-executing agent.
- Keep retrieval/tool execution separate from provider completion. MCP exposes
  workspace operations; it does not itself supply reasoning, login or a search index.
- Show real completed stages, elapsed time, waiting/retry state and cancellation.
  Do not invent progress percentages, completion times or confidence scores.
- Require explicit consent for additional paid calls beyond the selected action's
  budget. Do not silently change accounts/models after a capability failure.
- Capture all accepted results through the 0.5 observed-generation/file boundary.
  Stale work becomes retained review material instead of overwriting newer edits.

## Delivery order and acceptance

1. **Verified checkpoint f7155c0:** professional task drafting and responsive
   question controls. Source: `research_tasks.py`, `desktop/research_tasks.py`.
   Tests include cancellation, repeated activation, existing drafts, context changes
   during preview/confirmation, closing, and existing question/browser layout.
   Full gate passed: 3,155 Python, 18 frontend, 91 mobile and two HTTP scenarios.
   This verifies task drafting, not the proposed research-agent execution layer.
2. **Required existing v0.5 scope:** per-list goals with explicit sync/export domain;
   claim-level verified sources; grounded lineage; source audit and grouped review.
   Enroll writers and assets before claiming these survive sync, restore or sharing.
3. **Integration:** merge maintenance improvements while retaining document identities,
   observed publication and durable Q&A. Resolve actual semantic conflicts; do not
   replace 0.5 writers wholesale with the maintenance branch's direct SQL writes.
4. **Finish synchronization acceptance:** enrollment, bootstrap, attachment closure,
   recovery, offline packs, device management and independent mobile continuation.
5. **Later optional extensions:** cross-paper evidence matrix, eligibility screening,
   disagreement review and citation traversal. Keep them outside the default reader
   until their own operations, tests and source traceability are implemented.

Cloud identity/hosting, service operation and physical Windows/Mac/phone acceptance
remain explicit release gates. No real research upload, paid calls or public
release is authorized merely by this design document.

## Local evidence-check entry

The current development candidate adds **Check saved evidence** under Research
tasks. It reads saved text and the owned original in a cancellable local worker,
shows actual processed-item counts and source-version uncertainty, and never asks
a model from a read. The same bounded operation is available through JSON CLI/MCP.
This is the initial deterministic audit slice, not the completed semantic or
cross-output audit. See [coverage and required next layers](analysis-audit.md).
The default task menu stays small; specialized systematic-review/experiment agents
remain optional workflows with their own criteria, evidence and execution budgets.

## Study-design-aware drafts

The existing Methods task now distinguishes empirical, theoretical and qualitative
appraisal, with mixed/review designs using applicable checks. It asks the model to
state uncertainty about the design, separate reported facts from interpretation,
and avoid universal quality scores or journal prestige as a substitute for review.
The existing Replication task distinguishes same-material checking, independent
data, proof review and qualitative-material/process review; a generated plan does
not imply execution or formal verification. Evidence drafting requests at most
five consequential claims without inventing extra claims to fill a quota.

These remain editable questions under the same six menu entries. Previewing or
cancelling calls no model and writes no research. This tests the software draft
contract; specialist evaluation of actual answers remains an external gate.
