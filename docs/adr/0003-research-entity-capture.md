# ADR 0003: Capture and materialize the research graph

Status: **partially implemented**, 2026-10-26. The private v2 paper/membership
graph, parent lifecycle rules, dependency-aware client and shared-connection journal
are implemented in isolated workspaces. [Shared intake actions](../sync-operations.md)
create complete lists on an empty peer. Order/read-state, full research manifests,
existing writer capture and production enrollment remain planned below.
See [the graph contract](../sync-graph-contract.md) for implemented wire details.

## Original failure and remaining writer boundaries

The original `SyncClient._materialize` ordered latest entity heads by revision. That was insufficient
for related records: list creation at revision 1, membership at 2, and list rename at
3 leaves latest heads ordered membership-before-list on an empty client. Keeping
every event does not fix this if materialization collapses them into latest heads.

The application also has several transaction owners. `store.connect` commits its
connection; `lists.import_list` additionally commits every ten references;
`local_operations.py` writes research plus integration receipts; `bundle.import_`
stages files and imports dynamic tables. `presentations.save_deck` writes assets,
history and JSON outside SQLite. Merely adding outbox writes to desktop buttons
would miss CLI/MCP, import, background and file-only changes.

## First next slice: papers and membership

Choose explicit domain payloads and portable identities. Extend the private
protocol through validation, service, client and fixtures together before enabling
new kinds. Do not send SQLite column names or local integer IDs as a generic API.

| Kind | Identity | Closed payload and projection |
|---|---|---|
| `paper` | Immutable workspace-scoped UUID; explicit mapping to existing `papers.id` | `title`, `authors` array, `year`, `venue`, `abstract`, `doi`, `arxiv_id`, `s2_id`, `page_url`, `pdf_url`, `source`; strings/nullability and lengths specified in shared fixtures. Derive local `title_key` and `authors_json`. |
| `membership` | Stable ID derived from the normalized `(list_sync_id,paper_sync_id)` pair, with a separately tracked incarnation | `list_id`, `paper_id`, `citation`, `added_at`; references use portable IDs. Creating one appends it in the local ordering projection; removing it never deletes paper research. |
| Existing `list`/plain `note` | Retain prototype IDs where unambiguous; enroll legacy IDs explicitly | Add parent/lifecycle metadata before using them with new kinds. A note refers to the portable paper ID, mapped locally. |

First-slice paper operations are create/update only. Whole-paper deletion needs
the child-retention gate below. Bibliographic identity aliases are matching evidence,
not primary keys: DOI/arXiv/title changes must not rename the research entity.
Reuse an existing identity only after a deterministic unique match; ambiguous matches
remain separate for review. Preserve the application's paper IDs and file paths via
a mapping rather than rewriting the entire existing workspace during enrollment.

Do not sync ranking scores, crawl/enrichment timers, raw error strings, credentials,
or provider usage. Citation metrics and generated enrichment require a later explicit
provenance contract. URLs are metadata, never instructions to fetch during remote apply.

Ordering and reading state are separate conflict domains, not incidental fields in
a full membership replacement:

- `list_order`: one bounded ordered list of active membership IDs per list; validate
  the observed membership-set revision. Concurrent reorder/add/remove preserves a
  conflict instead of silently dropping members. Project dense `position` integers.
- `workspace_list_order`: the analogous list-ID sequence; replaces only the explicit
  `lists.order` projection, never replicates arbitrary `kv` keys.
- `reading_state`: one membership-scoped record with `state` and optional
  `delivered_at`/`read_at`. State has the existing enum; timestamps are display data,
  not conflict authority. A separate per-device resume record suggests a position
  without moving the active reader automatically.

Paper plus membership is the first deliverable; order/read-state are its immediately
following slice. Do not advertise full list synchronization before all three pass.

## Parent preconditions and deletion

Add explicit parent references, distinct from same-entity `depends_on`. Each reference
names the parent's kind, portable ID and **incarnation** (its creation operation ID).
Renaming a live parent must not invalidate a child; deleting/recreating it must.
Persist incarnation and structural revision separately from its latest content head.

- Service acceptance requires all referenced parents to exist, be active, and have
  the specified incarnation in the same workspace. New offline parents must be
  uploaded before children; a missing parent is a retryable dependency failure.
  A tombstoned or replaced parent produces a preserved conflict, not a retry loop.
- A parent delete carries the observed structural revision. Accepted child mutations
  advance that revision. If a child edit wins first, the stale parent delete conflicts;
  if deletion wins first, the child edit conflicts and its content remains recoverable.
  Check and update these invariants inside the service's existing write transaction.
- List deletion hides its membership subtree but retains canonical/history records
  and paper research. Do not emit irreversible deletes for notes, PDFs or analyses.
  Existing membership heads remain archived under the old list incarnation; they
  cannot recreate the list during materialization.
- Explicit restore is a new incarnation and a reviewed restoration of selected
  children, not reuse of old pending operations. Paper deletion is deferred until
  notes, analyses, anchors and decks participate in this retention/restore contract.
- Membership removal and concurrent read-state edits use the same parent/child rule.
  Child versions surviving a deletion belong in recovery/conflict views, not an
  orphan row silently attached to a later incarnation.

An atomic local action may emit several operations. Parent-first transmission can
leave harmless paper metadata present before a membership arrives; it must never
leave a visible membership referencing a missing paper. Remote all-or-nothing batch
publication is not promised by this first extension. Large imports use bounded,
retryable batches and expose partial progress explicitly.

## Dependency-aware materialization

Replace revision sorting with a registry of each kind's required parents and projector:

1. Persist validated events, canonical heads and cursor transactionally, retaining
   the existing pending/acknowledged-but-unreceived protection.
2. Build readiness from active canonical incarnations and verified local prerequisites.
   Roots (`paper`, `list`) project first, then membership, then order/read-state and
   paper-owned content. A newer parent rename still projects before an older child.
3. Defer only affected dependency components when a parent is missing, an incarnation
   mismatches, local edits are outstanding, or required bytes are unavailable. Record
   a bounded reason; unrelated ready research can still materialize. Never fabricate
   stub metadata merely to satisfy a foreign-key-shaped reference.
4. Archive/hide children before removing a parent projection. Retained canonical
   children are ineligible while that parent is tombstoned. Reject unsupported cycles
   in required-parent relationships; citation links are data, not recursive prerequisites.

Keep each materialization transaction and its applied markers atomic. Separate the
received cursor from materialization progress so a missing PDF does not discard an
accepted note or imply that its attachment is ready. UI refresh still preserves drafts.

## Capture all supported writers through one transaction boundary

Introduce a workspace-bound research unit of work that **owns one existing connection**.
Typed repository functions accept it; they cannot open or commit nested connections.
The unit validates operations, writes research, captures identities, writes outbox
entries and integration receipts, and advances UI invalidation in one commit.
Network resolution and AI generation finish before acquiring the write transaction.

Use an explicit registry of syncable tables/fields plus transaction-local dirty-key
guards. Guards are capture-coverage checks, not the wire serializer: every relevant
SQL change must be accounted for by a typed domain operation or a documented local-only
projection. Before commit, an unaccounted write fails the enrolled operation instead
of silently creating unsynchronized research. Preserve a durable gap marker if an
unsupported external raw-SQL writer bypasses the unit; block claims of complete sync
until reconciled. CLI/MCP remain the supported external mutation interfaces.

`Journal.transaction` and `Journal.apply_in` now provide the tested shared-connection
seam. `ResearchOperations` uses it for compound list intake, including its retry receipt.
Existing app writers still need conversion; never call a separate `Journal.apply` after
`store.connect` has already committed. Convert inner commits in `lists.import_list` into explicitly
bounded unit-of-work batches with stable retry identities. Sync-disabled behavior
must continue working while adapters are migrated.

For file-backed research, stage and verify immutable bytes first. Commit the manifest,
research reference and outbox in the same unit; rebuild compatibility JSON/path
projections from that committed manifest. A crash before commit leaves a collectible
unreferenced blob; a crash after commit must not leave a reference to unpublished bytes.
Do not claim SQLite makes legacy file overwrites atomic. Garbage collection needs
history, pending-operation and offline-pin references before deleting any blob.

## Expansion and concrete handoff

| Slice | Writers to route through shared operations | Required gate/tests |
|---|---|---|
| Papers + membership | `store.upsert_papers`; `lists._store_entry`, add/remove/import; `list_create.py`; `research_plan.py`; `local_operations.py` | Empty peer receives paper/list/membership then parent rename in adverse revision order; restart/retry; ambiguous aliases; missing/deleted parent; no AI or download on apply |
| Order + reading state | `lists.reorder`, `reorder_papers`, `remove_paper`; `desktop/main.py:set_state`; optional queue adoption | Concurrent reorder/add/remove; per-list state isolation; full permutation validation; delete/read race; unchanged legacy queue module behavior |
| Notes + analyses | Desktop note/dive/chat writers; `pocket.py` note import; `dive.py`, `closeread.py`, `survey.py`, `cites.py`, `followups.py`, `resources.py` | Stable IDs; generated-vs-curated provenance; preserve edits; interrupted AI completion capture; received analysis never runs AI |
| Anchors + source material | `pdf_highlights.py`, `repdf.py`, `paper_highlights.py`, `reading_links.py`, `research_questions.py`, `materials.py` | Paper/document SHA-256 + anchor schema/version; replacement-PDF mismatch stays unresolved; reanchor is explicit; hidden highlights and reasons survive |
| Decks + attachment manifests | `presentations.save_deck`, presentation pane; `fetch.py`, `pdf_downloads.py`, `figures.py` | Stable deck/slide IDs and editable layout; immutable asset references; missing/corrupt bytes; save interruption; concurrent deck edits preserve both |
| Imports + remaining integrations | `bundle.import_`, mobile imports, pipeline/venue/enrichment persistence, module-specific research writers | All changes use capture; imported identity decisions repeat safely; no receipt/credential import; mutation inventory has no unexplained gap |

Analysis records use paper/list identity plus analysis kind and schema version; large
bodies become verified content manifests rather than exceeding an envelope limit.
Anchors bind to the exact document hash. Deck records reference stable slide/source
identities and content hashes, never machine-local paths. Each new kind needs shared
service/client semantic fixtures before its writer is enabled.

## Join, import and release gates

- Enrolling a nonempty workspace requires an independent backup, immutable identity
  map and explicit baseline reconciliation. Existing integer IDs or equal list names
  do not prove common origin. Never import another device's binding or retry receipts.
- A research bundle is a snapshot import into the receiver's workspace. Preserve
  curated receiver data and the established `replace` choice; map imported identities
  explicitly, then emit **new local operations** for the actual changes. Sender sync
  cursor, device ID, resolution intents and credentials are never adopted.
- Rejoining the same private workspace uses authenticated bootstrap/history and its
  identity map, not the bundle import path. Restored backups get a new device identity.
- Enable production enrollment only after the writer inventory maps every supported
  mutation to a tested capture path. Audit SQL and file writers separately; UI-only
  tests cannot establish coverage. Run the full repository check plus two-workspace
  mixed-operation, failure/retry and parent-delete/child-edit fixtures at each slice.

Implemented upstream: shared-connection journal seam, versioned parent/incarnation
contract, service structural preconditions and dependency-aware projection. Remaining
gates: order/read-state, audited writer capture, typed analysis/file manifests,
backup/restore, UI conflict/recovery views and real-device acceptance. Passing the
prototype tests does not enable production enrollment or complete this ADR.
