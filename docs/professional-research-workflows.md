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

- [Ai2 Asta](https://allenai.org/blog/asta): question framing, finding papers,
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

Additional primary references checked on 2026-10-30:

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
separately while preserving the current PDF and drafts. Unbound ownership and
complete first-enrollment migration remain required follow-ons. Mobile displays
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
