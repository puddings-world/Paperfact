# AI feature plan: 0.5.0 and after

Status: plan agreed with the owner on 2026-11-20. Nothing in this file is
implemented unless a section says so. The rules for which account an AI call may
use are in [AI access policy](ai-access-policy.md); this file is about what the
features are and how they are built.

The earlier proposal for agent capabilities and job contracts is in
[Agent workflows](agent-workflows.md); read it before building section 1.

## Purpose

Paperfact's AI exists to help a researcher, or someone entering research,
understand papers faster and build a knowledge base of their own. An AI answer
that is read once and lost does not serve that. So each AI feature should
produce a small, structured result that is saved, leads back to the passage it
came from, and can be reused by a later feature.

## Scope by release

| Release | In scope |
| --- | --- |
| 0.5.0 | One definition per AI feature and a host task queue; the settings page below; removal of the Gemini key option; single-paper tasks; notes as cards |
| 0.5.1 | Cross-paper features; sections inside a list, the list map and topic convergence |
| Later | Research gaps, writing export, tracking new papers |

## 1. One definition per AI feature (0.5.0)

Today `research.citations` and `research.dive` each have a `task` function that
returns the prompt and inputs, and a `save` function that validates and stores
an answer. The other features build a prompt and parse free text on their own;
the planning text and stray tags that leaked into 論文問答 answers came from that.

Every AI feature gets the same three parts:

- `task(paper_id, ...)`: the prompt, its inputs and the expected output format.
- `save(paper_id, body, ...)`: validates the answer against that format and
  stores it. An answer that fails validation is rejected, never stored as is.
- A task name in `ai_profiles.TASKS`, so the settings page can route it.

Two runners use the same definition:

- **In-app runner**: starts the signed-in Claude Code or Codex CLI, or calls an
  API endpoint, then calls `save`.
- **Host runner**: an agent host (agy, Claude Code, Codex) calls the feature's
  MCP `task` tool, answers with its own account, and calls the `save` tool.

Done: `research.dive`, `research.citations`, `research.ask` (host tools only;
the app's own 論文問答 already used the same request and publication).
Still to convert: 精讀, the highlight drafts chained after a deep dive, AI 翻譯.

### In the app, or from an agent host

Decided 2026-11-20: the two are separate. A button in the app runs only what
Paperfact can start itself (Claude Code, Codex, an API endpoint), and shows its
result when the job ends. An agent host uses Paperfact through MCP while the
reader works in that host. A feature is never assigned to a host in settings:
a button that only leaves a request for another program is confusing.

### Host task queue

The queue has one use: scheduled analysis. Papers due for ahead-of-time
analysis are queued, and the host's own scheduler lists them
(`research.tasks.pending`) and answers each through the feature's `task` and
`save` tools. Paperfact's own scheduled task is then not needed for AI work.
Paperfact cannot wake a host.

Done: the queue and `research.tasks.pending`, for deep dives and reference
analyses. Not done: scheduled analysis adding to the queue.

## 2. Settings page (0.5.0, layout proposed)

Per-feature routing already exists (進階設定 · 各功能的 AI). The page is uneven
in another way: the first screen offers Claude, Codex and Gemini as three equal
buttons although Gemini is a billed API key, and other API endpoints sit in a
third dialog.

Proposed: one page, two parts.

**AI sources** for the app's own buttons:

| Group | Rows | Billing shown |
| --- | --- | --- |
| Subscription sign-in | Claude, Codex | Counts against the plan |
| API endpoint | Anthropic key; OpenAI-compatible endpoint | Billed per use |

**Features**, one table: feature, source, model. The first row is the default;
every other row follows it until changed.

**Connect an agent host**, a separate section that only gives connection
settings and instructions for agy, Claude Code and Codex. It is not a source in
the table above.

Done: the picker's three buttons are Claude, Codex and **API 端點**; the last
lists every saved endpoint and opens the connection form to add one. The toolbar
opens one window with three tabs: **全域預設**, **各功能的 AI** and **連接外部
agent**; setting the default or saving feature choices keeps it open, and closing
with unsaved feature choices asks first. The agent-host tab gives the MCP entry
and changes no setting. Not done: per-host instructions (agy, Claude Code, Codex
each store the entry differently), and the connection form is still a separate
dialog opened from **API 端點**.

### OpenAI-compatible endpoint

One form: name, base URL, API key, model. Presets fill the URL for OpenAI and
for a local Ollama server; anything else is typed. It covers local models and
self-hosted services.

### Gemini

- Done: the "Gemini API 金鑰" button and preset are removed. No Gemini CLI or
  agy backend exists or will be added.
- A Gemini subscription is used from agy, as an agent host.
- A Gemini key connection saved earlier keeps working and is listed as an
  ordinary OpenAI-compatible endpoint.

### Connecting agy

Paperfact never handles the agy sign-in; the reader signs in inside agy. The
agent-host section offers:

- the MCP server entry to add to agy's configuration,
- a short instruction file for agy describing the tools.

Check agy's current MCP configuration path against its documentation before
writing the instructions; this has not been tested with agy yet.

## 3. Single-paper tasks (0.5.0)

Stored through the existing annotation features (`annotation_content.FEATURES`),
each with a fixed format and passage anchors:

1. Prerequisites: what the reader must know first, and what to read for each.
2. Novelty: the difference from the closest earlier work, step by step.
3. Limitations and open objections.
4. Glossary and step-by-step derivations.
5. Reproduction checklist: data, hyperparameters, compute.

Depth follows the reader's research style setting: more background and analogy
for a newcomer, more comparison and criticism for a researcher.

## 4. Notes as cards (0.5.0)

No separate card store. Notes gain what a knowledge base needs:

- A type in the existing `kind` column: concept, method, claim, open question.
- Links from one note to several papers, and from note to note.
- "Save as note" on a 論文問答 answer and on a section of a deep dive, keeping
  the passage anchor.

Claims with evidence and research questions keep their own stores; one
knowledge-base view lists and searches all of them together.

## 5. Cross-paper features (after 0.5.0)

These read the structured results of sections 3 and 4, not the PDFs, so cost is
bounded and every statement has a source.

1. Deeper context for one paper: per earlier work, which component was kept and
   which step changed; per later work, what it corrected or criticised.
2. Comparison table for a list: problem, core method, data, metric, main
   result, limitation.
3. Conflicting claims across papers.
4. List synthesis against the list's reading goal: covered, missing, next.

The tasks `compare`, `survey`, `overview` and `lineage` exist today in a
shallower form; read them before designing these.

## 6. Lists (0.5.1 and later)

A list today is flat: a name, a note, papers in order, one reading goal and one
survey. Research narrows over time, and the list should be able to follow.

Changed 2026-11-22 (owner): sections inside a list replace the earlier
"sub-lists, two levels" plan. A list is collected mostly as the references for
one research topic, so it needs classification inside it and a view of how its
papers relate, without opening each paper's context in turn. A sub-list would
be another place to enter and leave; a section is a heading in the same list,
so there is one level of navigation and no tree to limit.

In 0.5.1, with the cross-paper features:

1. **Sections.** A list has a main line and any number of named sections. A
   section is either a category of the topic (for example "phase recognition
   models") or a side question (for example "which Jaccard variant is
   comparable?"); a side question stores the question it answers.
   - A paper can be in the main line and in sections at once; its read state is
     shared, and it is shown once with its other places named.
   - The list's count, progress and next paper follow the main line. A side
     question is collapsed by default and does not dilute them.
   - A side question ends in one of three ways: closed with a conclusion card
     (section 4) while its papers stay; merged into the main line; or promoted
     to a list of its own that records the list and question it came from.
   - No hard limit. Past about 20 papers in a section, or 5 sections, the app
     suggests promotion.
   - Sections are made by selecting papers, or by AI proposing groups for the
     reader to confirm. AI never moves a paper without confirmation.
   - An agent host adding papers for a side question offers "new section in
     this list" first, then the main line, then a new list.
2. **List map.** A second view of the same list, beside the paper rows, for
   reading the list as a whole:
   - One lane per section, papers placed by year within the lane, each showing
     read state and its one-line role in the list.
   - Relations between papers in the list, each from a stored source: a
     citation (`refs`, `cites`) or a statement in a paper's context
     (`paper_context`, which today stores a title, earlier or later, and a
     reason; the kinds in section 5, item 1 refine it). Selecting a
     paper shows its relations; nothing is drawn that has no source, and no
     relation is inferred from titles.
   - A paper with no relation to the rest is marked, as a prompt to check
     whether it belongs.
   - The comparison table (section 5, item 2) is the map's other form: the
     same sections as row groups.
   The map reads stored results only. Papers without a context or reference
   analysis appear without relations and are counted, so the reader can see how
   complete the picture is and start the missing analyses explicitly.
3. **Topic convergence.** A list's reading goal gains a stage (exploring,
   focusing, decided) and, per stage, the question being asked and why other
   directions were dropped. AI points out papers that no longer fit the goal
   and directions still missing; the reader decides what to move out.

Later:

4. **Research gaps.** Collect what no paper in the list has done, from each
   paper's limitations and open questions (section 3).
5. **Writing export.** A decided list becomes a related-work outline and BibTeX,
   with the sections as its headings.
6. **New papers.** For a decided list, look periodically for new papers citing
   its core papers and hold them for review; never add them automatically.
