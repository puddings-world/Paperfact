# Analysis audit: checking AI output against the paper (proposed, v0.5)

Status: proposed design, 2026-10-27. Nothing here is implemented yet. It extends the
planned **claim-level sources** and **lineage explanations** in
[roadmap-0.5.0.md](roadmap-0.5.0.md).

Every AI feature in the reader writes text a researcher may repeat: the deep dive,
close readings, answers (and the notes kept from them), slides, paper highlights,
the reference and follow-up analysis, the 研究脈絡 story and list surveys. The audit
checks that this text agrees with the paper and with itself, and shows the reader
where it does not. It never rewrites output on its own and never replaces the
reader's judgement.

## Principles

1. **The reader stays accountable.** Following RAISE (Cochrane, Campbell, JBI and
   CEE, 2025), the audit flags and explains; it does not silently correct, hide or
   score research. Every finding links to the passage it is about.
2. **Deterministic checks first.** Whatever can be checked without a model (a quote
   is in the PDF, a page exists, a resolved reference is the cited paper) is checked
   that way, on every run, at no cost.
3. **Ask checkable questions, never for a quality score.** Where a model is needed,
   it answers "does this passage support this sentence: supported / not found /
   contradicted", not "how good is this". Judges scoring overall quality agree poorly
   with people and favour their own family's output.
4. **A different judge from the writer.** The audit task routes, where the user has a
   second provider, to a different model family than the one that wrote the output.
   When only one is available the report says so.
5. **Missing evidence is shown, not invented.** "No source found" is a valid,
   visible result; the audit never supplies a citation.
6. **Findings are derived and local.** They are recomputed from the output and the
   paper, are not research data, and are not synced or exported in bundles.

## What is checked

### Layer 1 — deterministic (always, no AI)

| Check | Applies to | Passes when |
|---|---|---|
| D1 Quote exists | every quoted source sentence (highlights, dive quotes, slide sources, citing sentences) | the text occurs in the extracted PDF text of the exact document version, after whitespace and hyphenation normalisation |
| D2 Anchor resolves | page, figure, table and anchor references | the page, figure or table number exists in that PDF; an anchor's document hash matches the open version |
| D3 Numbers appear | numbers in generated text (metrics, dataset sizes, counts, years) | each number, with its unit, appears in the paper text or in a cited span; derived numbers are marked as derived |
| D4 Reference identity | 承先 rows resolved to a paper or DOI | the resolved title passes `openalex.same_paper` against the citation text; a mismatch is the most damaging error (the reader is shown another paper's analysis) |
| D5 Evidence basis | 承先 rows with `basis='title'` | the row makes no claim about how the paper uses the reference (purpose and verdict are marked "title only") |
| D6 Story coverage | 研究脈絡 and 接下來必讀 | every title in 接下來必讀 is a 承先 or 啟後 row; every paper named in the story is one |

### Layer 2 — claim grounding (model, checkable)

1. Split an output into atomic claims (one assertion each), keeping its position.
2. For each claim, collect candidate spans: its own anchor if it has one, else the
   best-matching passages of the paper (local retrieval, no model).
3. Ask the judge per claim and span: `supported`, `not_found` or `contradicted`, with
   the span it relied on. A claim is grounded only when a quoted span supports it.
4. Report the grounded share per output, and list every `contradicted` and
   `not_found` claim with its span.

Results are cached by (output hash, document hash, rule version), so an unchanged
output is never judged twice.

### Layer 3 — consistency across outputs

Each paper gets a **fact sheet**: datasets (name, size, centres, licence), tasks,
metrics with values, method names, baselines and stated limitations, each with its
source span. Facts are extracted from the paper once, then every output is compared
with it and with each other. A conflict (the deep dive says 3,000 videos, the slides
say 1,000) is a finding on both outputs. As in PaperQA2's contradiction detection,
conflicts are graded so that rounding and wording differences are not reported.

## Lineage rules (承先 / 啟後 / 研究脈絡)

Lineage is where errors spread furthest: a wrong relation is repeated in the story,
in 接下來必讀, in slides and in shared bundles. These rules apply in addition to the
layers above.

| Rule | Requirement |
|---|---|
| L1 Purpose from the citing sentence | 與原文的關係 (how this paper uses a reference) must be supported by a sentence of this paper that cites it (`contexts_json`). Without one, the row is title-only (D5). |
| L2 What the reference is | 這篇在做什麼 may only use the reference's own abstract or text, never this paper's description of it presented as fact. |
| L3 Relation from the later paper | A 啟後 relation must be supported by the later paper's sentence that cites this one. |
| L4 Citation function | Each citing sentence is classified as one of: `uses-method`, `uses-data`, `extends`, `compares`, `supports`, `contrasts`, `background`. Adapted from scite's supporting / contrasting / mentioning classes, made finer for lineage. `supports` and `contrasts` are flagged for the reader to confirm, since classifiers are least accurate on them. |
| L5 Story sentences map to rows | Each sentence of 研究脈絡 cites the 承先 or 啟後 rows it summarises; a sentence with none is flagged as unsupported. |
| L6 Inference is labelled | A relationship not stated in any citing sentence (for example "this likely inspired") is shown as inferred, never as fact. |
| L7 Team claims use ids | 作者團隊 matches (shared author or institution) come from OpenAlex ids; names alone never establish them. |

## How it is used

- **In the reader:** a **檢查** panel per paper lists findings by severity
  (`contradicted` > `identity mismatch` > `not found` > `title only` > `inferred`).
  Each finding opens the output at the claim and the PDF at the span. Rows and cards
  with findings carry a small mark. The panel shows the grounded share and which
  judge was used.
- **On demand and after analysis:** Layer 1 runs after every analysis step. Layers
  2 and 3 run when the reader asks, or as part of 深入分析 when the list's reading
  goal enables it; they count as AI use and show their cost like other tasks.
- **From the command line and agents:** `paperfact audit <paper> [--layer 1|2|3]
  [--json]` and a read-only MCP tool return the same findings, so Claude Code or
  Codex can audit without the desktop app.

## Skills

The rules above are written once as portable skills in `skills/` (see
[development-skills.md](development-skills.md)), used by both the app's audit
prompts and by coding agents reviewing changes to analysis prompts:

- `analysis-grounding-audit`: Layer 1 and 2 procedure, claim splitting, the three
  verdicts and how to cite a span.
- `lineage-citation-audit`: rules L1–L7 and the citation-function classes, with
  worked examples from real citing sentences.
- `cross-output-consistency`: the fact-sheet fields and conflict grading.

A change to an analysis prompt must keep the audit's gold set passing (below).

## Evaluation

- **Gold set:** about 10 papers from a real reading list (the Cataract list is the
  first candidate), with each output's claims, lineage rows and fact sheet checked
  by hand. It measures the audit's own precision and recall per rule.
- **Fixtures:** deterministic checks get unit tests from these papers' extracted
  text; model checks get recorded judge responses, so the suite runs offline.
- **Reported, not hidden:** the audit's measured precision per rule is shown in its
  documentation, and rules below an agreed precision stay advisory.

This gold set doubles as the first slice of a lineage benchmark: the "why this paper
exists" answers it checks are taken from real citing sentences, not from a model.

## Data and boundaries

- Findings live in a local table keyed by (paper, output, item, rule, output hash,
  document hash). They are derived, so they are neither synced nor bundled; a
  recipient re-runs the audit on their own copy.
- No new external service: lookups reuse the OpenAlex client already used by the
  reader; model calls go through `llm.complete` with a new `audit` task.
- The audit reads outputs and the paper; it never edits analysis. Fixing a finding
  is the reader's action (edit, re-run that step, or accept).

## Phases

| Phase | Scope | Depends on |
|---|---|---|
| A1 | Layer 1 (D1–D6) and lineage rules L1, L5, L7; the 檢查 panel; CLI | nothing new |
| A2 | Layer 2 claim grounding; citation function (L4); judge routing | claim-level sources |
| A3 | Layer 3 fact sheet and consistency; skills published; gold-set report | A2, reading goals |

## Open questions

- Claim splitting granularity for slides (one bullet, or each clause).
- Whether a list's reading goal may require Layer 2 before a paper counts as analysed.
- Where the gold set's hand-checked records live so they can be shared without
  sharing copyrighted full text.

## References

- RAISE: Recommendations and guidance on responsible AI in evidence synthesis
  (Cochrane, Campbell Collaboration, JBI, Collaboration for Environmental Evidence,
  2025). https://www.cochrane.org/zh-hant/events/recommendations-and-guidance-responsible-ai-evidence-synthesis
- Skarlinski et al., "Language agents achieve superhuman synthesis of scientific
  knowledge" (PaperQA2, including contradiction detection), arXiv:2409.13740.
- scite Smart Citations: supporting / contrasting / mentioning citation statements.
  https://help.scite.ai/zh/article/what-is-scite-1gfjuck
- Cao et al., "Automation of systematic reviews with large language models"
  (otto-SR), medRxiv 2025.06.13.25329541 (preprint; tool not released).
