# ADR 0008: Observe research inputs before generation or editing

Status: first producer slice implemented in isolated fixtures, 2026-10-26.
`closeread.write` and the shared survey-compatible observation/publication registry
are wired; the remaining producer inventory below is still a plan. No automatic
workspace enrollment. See [the implemented contract](../research-generation.md).
Extends ADR 0007 and the document identity/reader contracts in ADRs 0004-0005.

## Decision

Use one immutable, workspace-bound observation context from input loading through
publication. Wire it into the actual producer functions below, so desktop, CLI,
nightly and agent callers share the protection. A new facade without those call
sites is not completion. Keep canonical conflicts scoped to individual features
or rows; do not introduce a whole-paper conflict domain.

The context records:

- A request/job ID, explicit database/workspace/device binding and portable owner
  identity. Local row IDs are lookup details, never cross-device identities.
- Each intended output's observed revision, local predecessor, incarnation and
  exact parent lifecycle. Capture absence for first generation, not a fresh base
  after the model returns. Capture the loaded row as well for unbound workspaces.
- The actual input document: resolved PDF hash and document/parent operation
  identity, or an explicit metadata-only/abstract-only input mode. Resolve and
  verify off the UI thread. A document hash describes bytes used by this job, not
  whichever PDF happens to be applied when it finishes.
- The bounded read set actually used: metadata, analysis revisions or local
  content digests, feature inventories, and producer/spec/options version. A list
  survey also observes membership set/order and its component analyses; its list
  parent alone does not identify the prompt. Multiple input PDFs need a local
  input manifest, not a fabricated single `source_document_hash`.

`sync_capture.observe_content(conn, table, row)` currently needs a row and captures
graph state, not document provenance. Add a target observation by portable
scope/feature/key for absent outputs. Do not manufacture a dummy row or timestamp
to observe first creation. Extend the publication seam to accept explicit captured
source hashes; `sync_content` retaining a previous projection hash is not proof
that a newly generated result used the same document.

For dynamically discovered citation/followup/resource keys, capture the bounded
owner-feature inventory at start. New keys carry observed absence. Before a
replacement/pruning phase, compare that inventory and the touched row bases;
concurrent additions or edits must not be silently erased. Avoid scanning unrelated
papers or all rich content for each operation.

## Capture, completion and retry

1. Prepare prerequisites without a write transaction. Build the prompt from one
   captured document and a consistent SQL input snapshot. Recheck the document
   after extraction; do not mix one version's text with another version's figures.
2. Run external lookup/model work without a database lock. Carry the context with
   the result, including across thread/process boundaries.
3. In one short write transaction, validate workspace, mappings, parent lifecycle,
   current document and the relevant input/output observations. Keep
   `sync_capture.expecting(...)` active through DML **and commit**. Do not refresh
   expected bases at completion. A source change retains a candidate rather than
   silently publishing an answer to a different input.
4. Retain rejected output, intended mutations, original observations/input hashes
   and reason durably. Preserve current research and drafts. A compound phase
   retains one candidate group; never report a partially committed phase as done.
   Previously completed independent pipeline phases may remain committed.
5. Retrying publication uses the retained candidate and request receipt without
   another model call. Explicit regeneration captures a new context/request.
   Repeated completion/save must not duplicate rows, jobs or candidates.

Unbound workspaces retain compatibility and can compare captured local row/input
digests. This does not auto-enroll them. An unavailable or detached managed document
must never fall back to an old alias, cache or paper URL. Historical content keeps
its original source hash; publication does not re-anchor it to the latest PDF.

## Actual producer seams

Paths below are relative to `src/paper_daily/`. These are required implementation
sites, not examples of optional callers.

| Producer and storage | Capture and publication changes |
|---|---|
| `dive.generate`, `_generate_for`, `_run`, `dive_ahead`; `dives` | `_generate_for` closes its input connection before the model call and currently returns only body/reason. Return context with the result through `_run`; consume it in the later `dive_ahead` UPSERT. Cover direct `generate` callers too. `_prepare_highlights` must use resolved document availability instead of its legacy PDF alias. |
| `brief.pack_text`; shared dive/close-reading inputs | Separate conference-page backfill/preparation from immutable prompt capture. Accept the captured document for `prepare`/exhibits, and record lineage/recent-reading inputs actually included. Preserve explicit abstract-only support where allowed. |
| `closeread.write`, `write_many`; `close_readings` | Carry the initial pack/document observation across the model call into the fresh output connection and explicit commit. Required-PDF failure differs from dive's abstract fallback. |
| `cites.analyse`; `cites` | Replace direct legacy `TEXT_DIR` reads with captured document text. Observe metadata and citation inventory before Crossref/S2/model work. Upserts and pruning form one phase. Current pruning lacks the upsert's `edited=0` guard; preserve manual rows and reject changed inventory instead of deleting them. |
| `followups.fetch`; `followups` | Metadata-only lookup can use null source hash. Observe existing/absent discovered keys and publish row changes plus `followups.checked.*` together. |
| `followups.judge`; `followups` | Observe selected rows and metadata before each model batch; carry those observations into that batch's commit. Count accepted results, not candidate-only completions. |
| `followups.overview`; `paper_context` | Observe target, paper metadata, dive, citations and followups before prompting. The current pre-call edited check does not protect an edit made during generation; its UPSERT must use the captured base. |
| `resources.find`, `refresh`, `needs_check`; `resources` | External lookup, although not an LLM call, has the same race. Replace legacy text/first-page reads with the captured document. Split collection from publication: `find` currently deletes/reinserts the scope and commits its caller connection. Atomically publish replacement plus completion flag without committing unrelated caller work. |
| `survey.build_input`, `write`; `list_surveys` | Observe target absence/existing row, list lifecycle, membership set/order and all input metadata/analyses. `force` permits replacement of the observed edit, not an edit made later. |
| `paper_highlights.generate`, `prepare_reading`; analysis JSON and SQL marks | Capture exact PDF bytes before extraction/chunking. The current page-text hash recheck is insufficient for PDF identity or output bases. Stage analysis JSON instead of publishing before mark creation. Use the same document in quote-to-coordinate mapping. |
| `pdf_highlights.sync_ai`; `pdf_ai_highlights` | Observe item bases and scoped inventory before generation. Publish upserts and stale-item removals together; preserve concurrent hidden/manual decisions. Document fingerprint checking alone does not protect those edits. |
| `reading_links.prepare`; JSON | Observe the highlight artifact and exact dive/close-reading inputs loaded by `_context`. Its cache key is useful input identity, but current final `_atomic_json` lacks completion-time dependency checks. |
| `research_questions.ensure`, `_ensure`; JSON | Capture `context` analyses and original PDF. Validate evidence against that captured version, then recheck inputs before activating output. A stale success or failure must not replace newer questions or their failure-cache metadata. |

`analyze.analyse` orchestrates preparation/resources and parallel explanation and
placement chains. Keep observations at each actual phase start, after successful
dependencies, rather than one stale token for the entire pipeline. Its `has_pdf`
and required-PDF decisions currently use a legacy alias: use managed resolver
availability. `_record` must distinguish accepted publication, retained candidate
and failure; do not mark candidate-only output successfully analyzed.

## Editable UI and process handoff

- `desktop/cites_pane._edit_item` and `_edit_story` currently accept a modal before
  `followups.edit_reference/edit_followup/edit_overview` saves. Capture the displayed
  row and original paper identity at dialog load. Pass observations to the save
  function; do not use a potentially changed `self.paper_id` afterward.
- `desktop/survey_dialog._edit` and `survey.edit` need the same load/save boundary.
  Reuse `NoteEditor(save=...)` behavior from `main.Data.note_for_edit/update_note`:
  failed/stale saves keep the dialog and draft open. No separate close-reading
  editor was found in this audit.
- `main.Data.save_dive` and `cli.cmd_dive_save` are replacement writers and need
  an observed base or an explicit retained-candidate outcome; they cannot bypass
  the producer boundary as ordinary immediate commands.
- `desktop/research_questions.generate` and
  `desktop/presentation_pane._analyze_highlights` already run background workers.
  Their paper-switch checks protect rendering, not canonical publication; pass
  context into the underlying producers and preserve it in worker results.
- `main.MainWindow._spawn_job`, `desktop/cites_pane._spawn` and
  `desktop/survey_dialog._generate` launch CLI subprocesses using global runtime
  configuration. Persist a bounded local job context and hand off an opaque job
  ID plus explicit workspace binding. The child verifies that binding before
  loading inputs or saving. Never infer the destination from the current UI,
  working directory or a later global workspace switch.
- Standalone CLI/nightly/MCP invocations create the same context inside the actual
  producer when no parent job exists. Thread-pool workers open their own explicit
  workspace connections; never share a SQLite connection across worker threads.

## File-backed phases and recovery

SQL capture does not cover highlight analyses, reading links, research questions,
or presentation JSON/assets. Existing per-paper locks prevent some duplicate
local work but do not validate input versions, remote edits or lifecycle changes.

Stage bounded, typed output under an owned job location. Publish an accepted
artifact intent and related SQL mutations atomically, then activate the exact
accepted file revision with recoverable desired/applied state. Keep the last good
file until activation succeeds; recover interrupted publication by intent/request
identity. Do not overwrite the current cache via `_atomic_json` before acceptance.
If links are a separate dependent phase, expose that partial status explicitly.

This is a local publication requirement, not authorization to transport arbitrary
JSON through the PDF-only blob contract. A later typed artifact protocol must
allowlist business fields and exclude raw generation receipts/provider credentials.
Presentation generation/editing requires its own artifact scope and captured
inputs; it is not implicitly covered by the SQL research-content serializer.

## Implementation order and acceptance

Implement the shared target/input observation and candidate publication seam,
then wire SQL producers and their editors, then file-backed phases and subprocess
handoff. Retain explicit outcomes for accepted/candidate/failed work throughout
existing progress/result reporting. Each step must exercise actual entrypoints
with isolated fixtures and simulated provider responses, not only helper tests.

Required checks: first generation with no row; manual edit while running; exact
PDF A-to-B replacement; changed prompt dependency; parent delete/restore; same
local ID in another workspace; newly discovered key colliding with a concurrent
insert; compound replacement rollback; file activation failure/recovery; retry
without another model call; repeated launch; thread/process context round-trip;
paper/account/workspace switch; and editor draft retained on rejection. Include
unbound compatibility and managed unavailable/detached no-fallback cases. Run the
full project check before declaring producer enrollment complete. No real model
calls or user research files are needed for this coverage.
