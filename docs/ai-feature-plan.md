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
| 0.5.1 or 0.5.2 | Cross-paper features |

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

Features still to convert: 論文問答, 精讀, the highlight drafts chained after a
deep dive, AI 翻譯.

### Host task queue

A reader can assign a feature to an agent host instead of an in-app account.
Starting that feature in the app then records a pending request instead of
running anything. The host picks it up through one new MCP tool that lists
pending requests, answers each through the feature's `task` and `save` tools,
and the open reader refreshes.

- Paperfact cannot wake a host. The request waits until the reader asks the
  host to work, or until the host's own scheduler runs. The app says so where
  the request is shown.
- Nightly analysis moves to this queue: the host's scheduler drains it, and
  Paperfact's own scheduled task is no longer needed for AI work.
- A pending request can be cancelled in the app.

## 2. Settings page (0.5.0, layout proposed)

Per-feature routing already exists (進階設定 · 各功能的 AI). The page is uneven
in another way: the first screen offers Claude, Codex and Gemini as three equal
buttons although Gemini is a billed API key, and other API endpoints sit in a
third dialog.

Proposed: one page, two parts.

**AI sources**, three groups whose rows have the same shape (name, state, one
action):

| Group | Rows | Billing shown |
| --- | --- | --- |
| Subscription sign-in (runs in the app) | Claude, Codex | Counts against the plan |
| Agent host (picks up tasks through MCP) | agy, Claude Code, Codex | The host's own account |
| API endpoint | Anthropic key; OpenAI-compatible endpoint | Billed per use |

**Features**, one table: feature, source, model. The first row is the default;
every other row follows it until changed.

- For an agent-host source the model column reads "chosen by the host".
- A feature without host tools cannot be assigned to a host; the option is
  disabled and says why.

### OpenAI-compatible endpoint

One form: name, base URL, API key, model. Presets fill the URL for OpenAI and
for a local Ollama server; anything else is typed. It covers local models and
self-hosted services.

### Gemini

- The "Gemini API 金鑰" button and preset are removed. No Gemini CLI or agy
  backend exists or will be added.
- A Gemini subscription is used from agy, as an agent host.
- A Gemini key connection saved earlier keeps working and is listed as an
  ordinary OpenAI-compatible endpoint.

### Connecting agy

Paperfact never handles the agy sign-in; the reader signs in inside agy. The
"agy" row offers:

- the MCP server entry to add to agy's configuration,
- a short instruction file for agy describing the queue and the tools,
- the time of the last request agy picked up, as the connection state.

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
