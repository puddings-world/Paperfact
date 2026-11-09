# Paperfact

Read `AGENTS.md` for the full regression check and shared knowledge-capture
workflow. Portable development skills are maintained in `skills/`; see
`docs/development-skills.md`. Do not edit generated `.claude/skills` copies.

A desktop workspace for papers, reading lists, notes and research context, with
configurable AI providers. The bundled ML workflow maintains a reading queue over
ten-plus years of ICLR / ICML / NeurIPS and prepares nightly deep dives.

## v0.5.0 planning handoff

For cross-device work, read `docs/roadmap-0.5.0.md`, then
`docs/sync-architecture.md` and `docs/implementation-0.5.0.md`.
They separate agreed scope, proposed architecture, unresolved decisions, and
implementation tasks. Sync and the independent mobile PWA are not implemented.
The S01 baseline is in `docs/sync-write-inventory.md`; `docs/adr/0001-local-sync-journal.md`
records the journal foundation. The reference client/service and explicit list/note
adapter are in development; existing app writers are not enrolled yet. Follow the
updated ledger and `docs/parallel-work-0.5.0.md` for ownership; do not overwrite another
session's files. Production identity/hosting and full research coverage remain gated.
Use the active `Paperfact` checkout; the old `paper-daily` checkout is an archive.
Keep repository planning documentation concise and in English.

## Intent

The product is field-independent: researchers bring papers, maintain multiple lists
and keep their own notes. AI-assisted intake and analysis use configurable execution
connections. Ordinary startup must not require a conference corpus or agent account.

The bundled ML recommendation workflow has its own selection policy: programme
labels, citation velocity, author strength and a principle-over-application bias,
plus curated foundations and lineage expansion. This policy is not a default for
all user lists. See docs/ml-daily.md for its current behavior and
docs/agent-workflows.md for the proposed list UI and optional-module boundaries.
Do not describe planned module/agent features as already implemented.

## Conventions

- Package manager: **uv** only. Never `pip install` at user level.
- Run: `./scripts/dev.ps1 <cmd>` or `./scripts/dev.sh <cmd>`.
- The desktop reader (`app`) is the primary interface: PySide6, reading papers.db
  directly. Notes, deep dives and the paper chat all live in that one file.
- Setup: `./scripts/setup.ps1` or `./scripts/setup.sh` (idempotent).
- Tests: `pytest tests/`. Format: `ruff format && ruff check --fix`.
- Workspace data includes original notes and edits. Source defaults to `data/`;
  installed apps use platform data directories, and `PAPERFACT_DATA` overrides
  either. Never treat a real workspace as disposable generated output. Use
  isolated fixture directories for resets and migration/sync tests.
- Deep dives, close readings and answers are written in Traditional Chinese with
  English technical terms. They are read in the app, which typesets them, so maths
  is LaTeX (KaTeX), diagrams are mermaid and algorithms are ```pseudocode blocks.
  Everything shown elsewhere (slides, terminal, share pages) stays plain Unicode.

## Sources, and why

- **Conference virtual sites** (iclr.cc / icml.cc / neurips.cc) are the roster of
  record: accepted-papers-only, months ahead of the proceedings sites, and the only
  place oral/spotlight labels exist.
- **OpenReview is unusable anonymously** (`/notes` and `/pdf` both 403 behind an
  anti-bot challenge). ICLR PDFs come from Semantic Scholar open-access links.
- **Semantic Scholar files papers under first-posting year**, so venue queries always
  use a ±1 year window and match back by exact normalised title. Without the window
  the ICLR 2024 match rate is 42% instead of 94%.

## The nightly path

Windows Task Scheduler runs `scripts/nightly.ps1` at 00:00 and the app opens itself
on the delivered paper. A cloud routine was tried and abandoned: it cannot reach
papers.db, and its `write_db` raises an approval prompt that nothing answers at
midnight (`auto_mode_allow` / `permission_mode` are dropped by the API). Do not
re-plumb the nightly job through the artifact store without solving that first.

## Reading lists

`import-list` turns a bibliography into a switchable list. Those papers share the
`papers` table but live in `lists` / `list_papers`, with their own read state, and
`queue.build` is fenced to venue IN ('ICLR','ICML','NeurIPS') so they can never be
ranked into the nightly queue.

## The model call

`llm.py` is the model service for generation features, including list parsing,
questions, translation and research analysis. It resolves per-task profiles for
CLI, Anthropic, OpenAI-compatible and custom gateway connections. Features must
not bypass it with direct provider calls. These are model adapters; an external
agent integration requires its own capability and job contract, as described in
docs/agent-workflows.md.

## Finding an original

`resolve.fill_gaps` is the PDF hunt: the MICCAI page a row links, CVF, arXiv, OpenAlex,
after Semantic Scholar has had its turn on the citation. The reader's 查找原文 runs
`pdf_sources.discover` for one paper on the shared download queue. Matching a
paraphrased citation is allowed (see `openalex.same_paper`) but the thresholds are load-bearing: a wrong match hands the
reader an explanation of a different paper. A lookup that fails is never final --
`resolve-missing` runs nightly, because both APIs refuse when busy.

## Taboos

- No comments explaining WHAT (names do that). Comments only for WHY.
- Do not add an S2 roster fallback for years from 2018 on: an empty roster there
  means "not announced yet", and S2 will happily invent ~90 mis-filed preprints that
  then sit at the front of a newest-first queue.
- Do not switch ranking back to raw citation counts; it makes recent papers
  unrankable and defeats newest-first reading.
- Do not drop the venue fence in `queue.build`: imported list papers sit in the same
  table, and without it a re-rank sweeps NAACL and CVPR into the nightly queue.
- No speculative abstractions. No try/except around code that cannot fail.
- Do not loosen `openalex.same_paper` without a test for the case you are loosening.
  It renamed a GitHub project's row to a real paper that merely mentioned it.
- Do not let `queue.build` delete or re-rank rows whose role is in `PINNED_ROLES`
  ('companion', 'manual'). The rebuild owns what ranking produced, nothing else: a
  paper added by hand or promoted from the lineage block must survive the night.
- Do not call `claude -p`, an SDK, or an HTTP endpoint directly from a feature. Go
  through `llm.complete`, and return its `(result, reason)` rather than a bare None.
- Do not rewrite `figures.py` around `page.get_images()`: ML figures are vector
  drawings, so there is no raster to extract and it returns almost nothing. Caption
  text plus a rendered region is the only approach that works on this corpus.

## AI architecture

- All generation goes through llm.complete / llm.complete_result with a task name.
- Profiles and credentials belong to the AI service, not reading-list records.
- See docs/architecture.md for adapters, routes and the future hosted API contract.
- Keep vendor keys out of exports. Local usage receipts are observability, never a bill.
- Shared HTML readers obtain AI through a host capability, not desktop credentials.
