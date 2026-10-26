# Sync mutation inventory

Status: reviewed baseline, 2026-10-26 (S01). The existing application is v0.4.1.
This is a source audit, not a claim that these writers now participate in sync.
Opt-in store capture now exercises existing SQL writers in fixtures; full runtime
enrollment remains gated. See ADR0007 and the implementation ledger for the current
tested boundary; the table below preserves the original inventory and remaining scope.

## Research and identity map

| Data | Current identity/storage | Mutation entry points | Sync work required |
|---|---|---|---|
| Paper metadata | `papers.id`; SQLite | `store.upsert_papers`, `pipeline.py`, `brief.py`, `venues.py`, `pdf_downloads.py`, `repdf.py`, `rank/score.py` | Separate shared metadata from ranking/cache state; reconcile external identifiers |
| Named lists and membership | `lists.id`, `(list_id,paper_id)` | `lists.py`, `list_create.py`, `research_plan.py`, `local_operations.py`, `bundle.py` | Stable IDs, membership tombstones, names/order and read state; preserve import semantics |
| Manual notes | Local integer `notes.id` | `desktop/main.py` add/update/delete, `pocket.py` note import, `bundle.py`, `repdf.py` reanchor | Introduce portable note IDs without changing existing references; include anchors and PDF version |
| Conversation | Local integer `chat.id` | `desktop/main.py`, `scripts/guide_deck.py`, `bundle.py`, `repdf.py` | Stable thread/turn IDs, order and deletion semantics; no implicit AI calls |
| Deep/close reading and surveys | Paper/list key | `dive.py`, `closeread.py`, `survey.py`, desktop save handlers, `research_plan.py`, `bundle.py` | Capture generated and edited content; preserve both on concurrent edits |
| Citations, follow-ups, context | Paper + reference/work key; `paper_context` | `cites.py`, `followups.py`, `bundle.py` | Keep curated edits, provenance and graph relationships |
| Resources and pins | `(paper_id,url)`, `(scope,paper_id)` | `resources.py`, desktop pin handlers, `lists.py`, `bundle.py` | Normalize scope IDs and distinguish removal from deletion |
| Manual/AI highlights | Integer local IDs; PDF hash + anchor/source key | `pdf_highlights.py`, `bundle.py` | Stable identity, PDF-version binding, user hide/remove state |
| Authors/reference edges | External IDs/composite keys | Pipeline/enrichment and `bundle.py` | Decide canonical metadata vs rebuildable cache |
| Optional daily workflow | `queue`, `reading_log` | `queue.py`, `brief.py`, list conversion, desktop state handlers | Separate optional module data, delivery state and local paths |
| Mixed key/value state | `kv` | `store.set_kv` and direct SQL in modules | Explicit research-key allowlist; never replicate all keys |

`workspace_revision.py` currently tracks lists, membership, paper metadata, dives,
close readings, citations, pins, resources and selected keys. It does not capture
all notes, chat, highlights or files. It has no previous content, operation identity,
causal dependencies or retained deletions. Reuse it for UI invalidation only.

## Files and compound writes

| Store | Writers | Classification and capture boundary |
|---|---|---|
| PDF and extracted text | `fetch.py`, `pdf_downloads.py`, `repdf.py`, bundle/pocket helpers | PDF is an immutable, hash-addressed attachment; extracted text is version-bound derived content |
| Figures and indexes | `figures.py`, bundle import | Figure bytes and extraction metadata must retain source PDF identity |
| Presentation decks, history, assets, evidence | `presentations.py`; desktop pane saves | Commit a versioned manifest referencing durable assets; current local history is not sync conflict history |
| Ranked key sentences | `paper_highlights.py` | Preserve selected content, reasons and analysis/PDF provenance |
| Reading links and research questions | `reading_links.py`, `research_questions.py` | Versioned derived research linked to its source; failure diagnostics stay local |
| Material positions | `materials.py` | Coordinates/signature are meaningful only for the matching document |
| Presentation recovery drafts | `desktop/presentation_pane.py` | Local draft until explicitly saved; remote apply must not clobber an open draft |
| Pocket/share exports and brief output | `pocket.py`, `share.py`, export modules | Generated transfers are not canonical sync writes; imported edits enter the research boundary |

`repdf.py` changes both files and anchored note/chat records. `bundle.import_`
stages files and imports multiple tables, including dynamic table writes. Neither
can be made atomic across SQLite and the filesystem by wrapping only its SQL.
Plan immutable blob staging followed by a database manifest transaction; retain
orphan cleanup and recovery as separate work. Cache eviction in `storage.prune`
must not emit a research deletion and must respect future pinned/history references.

## Explicit exclusions

- Provider accounts, `llm.json`, vendor CLI homes, API tokens and Google OAuth files.
- AI usage logs, feedback/consent databases, onboarding agreements and telemetry queues.
- Device UI state (`ui.*`), local URLs/paths, update downloads, error logs and schedules.
- HTTP caches, generated exports, unsaved recovery drafts and process-local job state.
- Integration previews/receipts, revision counters and device sync receipts as research payloads.

Allowlist research keys such as `lists.order` deliberately. Review graph and
follow-up cache keys individually; a key prefix or a bundle whitelist does not
automatically establish sync semantics. Consent and AI credentials remain local.

## Coverage limits and next actions

- Audited schema, direct SQL sites and principal file writers with source reads
  and searches for SQL mutation, `write_text`, `write_bytes`, `_atomic_json`, save,
  replace and unlink. Dynamic SQL and indirect helpers require adapter-level tests.
- Production integer note/chat IDs still need a migration and backup compatibility design.
- UI, CLI, MCP, bundle import, phone import, AI completion, PDF replacement and
  optional daily workflow must each prove atomic capture before being marked supported.
- External tools that write SQLite directly bypass application contracts. Decide
  detection/reconciliation or explicitly unsupported behavior; do not promise capture.
- The experimental v2 graph validates list/paper metadata, membership and plain
  notes. Shared compound intake is tested, but none of the existing writers above
  is automatically enrolled; order/read-state and other research kinds remain.

Verified foundations: shared graph intake, empty-peer replication, retry/rollback
and concurrent-edit protection. Next: order/read-state and typed research/file
contracts, then route the audited writers through complete capture coverage.
See [the local journal decision](adr/0001-local-sync-journal.md) and
[the implementation ledger](implementation-0.5.0.md).
