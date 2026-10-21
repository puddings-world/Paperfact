# Agent-assisted lists and optional research workflows

Status: design proposal. The interfaces, list modes, module manager, job store and
external-agent bridge below are not implemented yet. Existing AI profiles and the
messy-bibliography importer are working foundations, not a complete agent runtime.

## Product boundary

Paperfact owns a researcher's library, lists, papers, notes and reading state.
Researchers choose what to read and which assistance to enable. An ML conference
queue is one optional workflow, not the definition of the application.

Four responsibilities must stay separate:

| Component | Responsibility |
| --- | --- |
| Core services | Lists, paper identity, files, notes, reading state, validated changes |
| Source connector | Search and metadata/PDF lookup for a supported scholarly source |
| Workflow module | A purpose-specific recipe: sources, filters, selection and optional schedule |
| Execution connection | A model endpoint, supported external agent, or future hosted service |

A module may use several source connectors and any compatible execution connection.
A connector can also support manual imports without the recommendation module.
Installing a module does not enable its schedule or background AI.

One workspace initially owns one database with many lists. A paper can belong to
several lists without duplicating its PDF and notes. List membership, order and read
state are distinct from paper identity. Removing membership is not deleting a paper.
Multiple workspace databases and shared storage are later storage concerns.

## Create a list without learning a configuration format

One "New list" dialog offers three entry paths:

- Empty list: name it and add papers yourself.
- Paste/import: paste rough references, titles, DOI/arXiv URLs, or choose supported
  import files. Dragging in a PDF starts the same intake flow.
- Track research: describe the topic in ordinary language, select sources and
  optionally enable updates.

Start with a name and input. For tracked lists, reveal topic, sources, date window,
update frequency and the destination list. Sorting, exclusions, maximum new papers
and AI preparation belong under advanced options.

Example natural-language request:

> Track recent surgical video research from MICCAI and relevant journals. Add at
> most ten new candidates each week. Let me choose before adding them.

The agent can propose structured settings; the UI displays the interpreted sources,
filters and update policy before activating them. Users can edit the form or the
description. Editing an explicit form field takes precedence over an older inferred
value. Keep the description alongside the effective settings so the user can see
what changed; a description is not an executable configuration.

A list has an optional automation attachment rather than a required "ML list" type.
The attachment references a module, supported source configurations, schedule,
selection policy and execution profile. Its fields are versioned and validated.
Authentication is referenced by connection ID, never copied into the list.

## Add, remove and reorder papers

Use the same "Add papers" action from the library and any list:

1. Paste text/links, choose an import file, or drop PDFs.
2. See candidates appear as parsing and lookup finish.
3. Correct ambiguous matches or uncheck unwanted entries.
4. Add selected candidates and optionally prepare their PDFs/AI analysis.

A candidate shows the original fragment, matched title/authors/year, identifiers,
source link and PDF status. States include verified identifier, likely match,
needs review, duplicate, original unavailable and lookup failed. Do not invent
numerical confidence unless it has a defined and calibrated meaning.

Users choose the automation level for each import: review first (default), or
automatically add verified identifier matches and leave ambiguous entries for
review. A complete beginner does not need to configure each pipeline step.

List rows support multi-select, remove, move/copy to another list, pin and drag
reorder. Undo restores membership/order. PDF deletion and deleting a paper from
the whole library are separate actions. A tracked list remembers exclusions and
ignored candidates so its next update does not undo the user's decisions.
Updating source metadata must not overwrite edited notes, reading state or manual
ordering. Disabling a module leaves all papers and notes available.

## Make agent work inspectable and resumable

A job belongs to Paperfact, independently of a model conversation or provider
session. Persist job ID, list ID, selected module/profile versions, effective
configuration, item states and checkpoints. Preserve the original input as private
workspace data; it does not belong in the metadata-only AI usage log.

The UI offers a compact job panel: finding references, matching papers, finding
originals, ready for review, importing and optional analysis. Users can inspect
items, cancel, resume or retry failed items. Closing a view need not lose the job.

The existing importer writes entries as it resolves them and has no staging
preview. Its blank-line fallback is approximate. The proposed importer stages
candidates first and commits selected validated results through core services.

| Failure | Required behavior |
| --- | --- |
| Invalid agent result | Validate schema, attempt bounded repair, then show unresolved items |
| Several plausible papers | Show candidates; do not silently choose an original |
| Source unavailable/rate limited | Preserve progress and retry only failed lookups |
| PDF missing/paywalled | Keep the metadata, show status, allow a user-provided original |
| Agent session lost | Keep local job state; resume supported steps with the chosen connection |
| Cancelled work | Stop new work and reject late mutations using the job cancellation state |
| Repeated result or resume | Deduplicate operation/item IDs and paper identifiers |
| Budget exhausted | Pause AI steps and retain completed work; do not change billing account |

A model may propose candidates and tool calls. Core services validate arguments,
allowed list scope and current job state before accepting changes. Model output
must not supply SQL or arbitrary commands to mutate the database.

A committed candidate records the identity evidence, source, originating input
fragment and operation ID. Identifiers take priority; title similarity is a
candidate-generation tool, not a guarantee of identity. Resuming must not create
duplicate memberships or overwrite a researcher's corrections.

Source retrieval and database transactions stay deterministic. Do not hold a
database transaction open while waiting for models or networks. Generate notes or
deep dives only when selected; a basic metadata import should not automatically
start every expensive analysis step.

## Different models and different agents

The existing llm facade returns text and usage. That contract is enough for parsing
or summarizing, but it does not promise browser access, arbitrary tools, progress
events, cancellation or resumable agent sessions.

Support two execution paths over the same validated core services:

1. Embedded workflow: Paperfact executes lookup and import steps, using the selected
   model profile for structured extraction and analysis. This works with a compatible
   model API without requiring a separately purchased agent application.
2. External agent: a supported agent host uses Paperfact tools to inspect jobs,
   search papers, propose candidates and submit results. Its adapter translates the
   host's event/result format into the same local job model.

The external path needs a real host integration. An account name or API key is not
an implementation. A host may require a configured launcher/SDK; a tool bridge alone
does not make Paperfact able to start conversations inside that host. A skill can
provide instructions for using the tools, but does not replace their validation,
state storage, or the host integration.

Capability discovery precedes dispatch. Track, for example, structured extraction,
tool execution, progress, cancellation and session resume. A host that lacks resume
can restart unfinished steps from local checkpoints without claiming to resume its
old conversation. Disable unsupported actions or explain which connection is needed.
Keep the same visible workflow regardless of the host.

Proposed adapter contract: inspect capabilities, start a job, emit versioned events,
cancel if supported, and resume if supported. Events identify job/item/operation,
stage, progress, proposed candidates and typed errors. Provider-specific session
IDs are opaque optional metadata. Completion-only providers continue using llm;
do not force every provider into a full agent interface.

## Expose tools without binding the product to one agent

Start with narrow core service operations: list/create a list, search local papers,
inspect a paper, search supported sources, resolve identifiers, inspect a job,
submit candidate results and commit an approved selection. Keep destructive actions
separate. Tool results use stable IDs and versioned schemas, with limits on result
size and allowed workspace/list scope.

An optional MCP server can expose these services to compatible external hosts.
MCP defines how hosts access tools and context; it does not supply the user's model
account or dictate the host's agent execution. Test each supported host and negotiated
protocol version; do not advertise universal compatibility.

The desktop invokes the same services directly. MCP is an adapter at the boundary,
not a dependency required to create a list or open a PDF. Do not build the workflow
around host sampling as a universal way to borrow a subscription.

Source and host documentation:
- [MCP architecture and scope](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP tools and schemas, version 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

## Modules for different research fields

The module UI shows installed workflows, supported sources and enabled attachments.
An ML Daily module can select ICLR/ICML/NeurIPS, add curated foundations and create
a daily reading view. A medical or language-research module can choose different
implemented connectors and selection rules without modifying the library schema.

Prefer data recipes for the first modules: ID/version, description, configuration
schema, required connectors/capabilities and permitted actions. Credentials live
in connection settings. A source's form can be generated from its schema, with
human-readable source names and defaults.

Selecting an arbitrary journal name does not guarantee a connector can query it.
Use supported connector identifiers/venue mappings and show unsupported sources.
A researcher can still add papers manually while another connector is developed.
A new Python library adapter is an implementation extension, not just a prompt.

Do not build a marketplace before one independently disableable module works.
Initially ship ML support as an optional package/extra or separately loadable module;
ordinary startup must work with that module absent. Version compatibility and
dependency handling must be tested. Third-party executable modules are not
automatically sandboxed just because they use the tool API.

Schedules trigger a module job against a chosen list; reminders are delivery
preferences, separate from research selection. Store exclusions and prepared-paper
state per attachment. Existing ML venue fences and manual/companion protections
remain intact during migration.

## Connections and required execution modes

Academic/BYO and commercial/managed are both product requirements. They reuse the
same tools, workflow modules and local job state. Managed mode routes all official
AI through the Paperfact service; BYO uses the user's chosen connection. The mode
policy and paid service remain unimplemented. See
[MCP and the two modes](mcp-and-modes.md) for the execution and billing contract.

Present connection choices as:
- Supported signed-in agent host, when a working adapter is installed.
- Personal model API key and endpoint.
- A compatible local model endpoint.
- A future Paperfact hosted service and customer token.

A subscription account is usable only when that host supports the intended
integration. Do not imply that every chat/agent subscription includes API access
or that its credentials are interchangeable with a vendor API key.

The app can provide an agent-assisted experience by combining its own workflow
executor with a model API. A user does not necessarily need a separate agent account.
Users of cloud-powered workflows need a functioning execution connection.
Basic reading and manual notes need no AI connection.

The current gateway is a completion API adapter, not a deployed job service.
A hosted workflow service would also need job endpoints/events, customer
authentication, quotas, cancellation semantics and authoritative credit accounting.
Its results must use the same validation/provenance contract as local execution.
Use idempotency keys and server-side settlement; editable local usage receipts
cannot determine a balance. Background spending should be off by default, with
explicit per-workflow limits. See [current AI architecture](architecture.md).

## Planned reading features

Recorded so the reader's direction is written down in one place; each entry says
how much of it exists.

- **A deeper 深度講解.** More sections and finer ones, including a set of reviewer
  questions prepared with the dive (what a strict reviewer would attack, what is
  unproven, what the baselines miss) offered as ready-made choices that send the
  question to 問 AI in one click. Exists in part: 深入分析 now also prepares
  research questions grounded in the full text (`research_questions.py`), offered
  in the 問 AI tab. Not built: a reviewer-oriented set and a deeper dive.
- **The paper's web presence, in the analysis.** A 線上 tab listing the paper's
  pages (arXiv versions, Google Scholar, OpenReview, alphaXiv, Hugging Face) in an
  embedded browser was tried and removed: it was a page of bookmarks beside 引用,
  which already holds what those sites say about citations, analysed. What would
  add something is pulling their content into the analysis itself (OpenReview
  reviews and author replies as reviewer questions, Scholar's citing list feeding
  啟後). Not built; OpenReview refuses anonymous API reads and Scholar has no API.
- **Topic lists from a research question.** Exists in a first form: ＋ 清單 accepts a
  research topic, the model turns it into one to three searches, Semantic Scholar
  returns real candidates, and the model picks and orders up to twelve of them
  (`list_create.topic_papers`). Not built: a multi-step agent deep research that
  follows citations and stages a larger list for review.

## Implementation order and acceptance

1. Core entry: empty-list creation without AI, a useful empty-library screen and
   manual add/remove/undo. New-user startup performs no conference crawl or paid AI.
2. Robust intake: validated candidate staging, visible per-item progress, identity
   evidence, cancellation, retry and idempotent commit. Preserve rough-text input.
3. Optional ML module: move its setup/schedule/policy out of generic onboarding.
   Verify a clean workspace works without it; preserve existing users' queues.
4. General tracking: source-specific forms, per-list updates/exclusions and budgets.
   A second field demonstrates that the contract is independent of ML.
5. Agent bridge: integrate one host, then a second host against the same contract
   tests. Add MCP exposure when needed, independently of desktop operation.
6. Hosted service: account/credit ledger and workflow endpoints after local
   behavior is reliable; keep vendor secrets on the server.

Contract tests must cover malformed results, mismatched originals, duplicate
delivery, partial failure, resume, cancellation with late results, preserved
user edits and no unexpected account switching. Avoid paid live-provider calls
in default tests. Documentation must distinguish working features from this plan.
