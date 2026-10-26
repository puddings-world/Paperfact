# Local database read projection

Status: v0.5 experimental read boundary. This is **not a sync bootstrap** or a
public/mobile HTTP endpoint. Database content and its local received-event cursor
are read from one SQLite snapshot; that does not mean all projected data has been
replicated or that unsent content may be discarded.

## API and bounds

`read_manifest(path, workspace_id=..., max_records=10000, max_bytes=8*1024*1024)`
opens an existing SQLite database in read-only mode and starts one read transaction.
The enrolled `research_sync_binding` must match. No database or identity mapping is
created. No files other than the selected SQLite database are followed; no source
PDFs, deck JSON, account directories, environment files or AI/network services are read.

The record limit counts source lists, papers, memberships, notes, analysis rows,
citations and highlights, including hidden highlights. Both a conservative source
text-size preflight and exact serialized UTF-8 output limit are enforced. Limits
are errors, never partial success/truncation. Supported upper configuration bounds
are 100,000 records and 64 MiB. Large workspaces need a later paginated snapshot API.

## DTO version 1

| Field | Exact content |
|---|---|
| `schema_version`, `workspace_id`, `cursor` | Version 1, enrolled workspace ID, stored received cursor (0 if not initialized) |
| `capabilities` | `database_read_projection: true`; `sync_bootstrap`, `assets`, `decks`: false |
| `local_state` | Counts `pending_operations`, `awaiting_receipts` and `deferred_entities` |
| `lists[]` | `id`, `name`, nullable `note`, `revision`, `sync_state`, ordered `members`, `analysis_sections` |
| `members[]` | `paper_id`, original integer `position`, `state`; sorted by position then paper ID |
| `papers[]` | `id`, `title`, string-array `authors`, `year`, nullable `doi`/`url`, `pdf_asset_id: null`, `analysis_sections`, `citations` |
| `analysis_sections[]` | `kind` (deep_reading/close_reading/context/survey), nullable `body`, `written_at` |
| `citations[]` | Nullable text `ref_key`, `title`, `doi`, `purpose`, `gist`, `verdict`, `why`, `basis`; nullable integer `year` |
| `notes[]` | Portable mapped `id`, `paper_id`, `body`, `kind`, legacy nullable `page`, `editable`, `revision`, `sync_state`, nullable `anchor`/`pdf_hash`, `anchor_status` |
| `highlights[]` | Stable derived `id`, `paper_id`, `origin` (manual/ai), `quote`, `reason`, `hidden`, nullable `pdf_hash`/`anchor`, `anchor_status` |
| `decks[]`, `assets[]` | Empty: file-backed attachment/deck projection is unsupported here |

Lists are ordered by creation timestamp and ID, not the device's `kv` preference.
Paper and note text is untrusted text; consumers must not insert it as HTML.
Authors are reduced to names; arbitrary author metadata is omitted. URLs are
optional HTTPS metadata hyperlinks without credentials, query/fragment, local
hosts or custom ports. They are not authorized attachment-fetch instructions.
No credential/configuration keys, raw `kv`, telemetry, local paths or arbitrary
anchor fields are serialized. Research text itself is not automatically redacted.

`revision` is the last nonnegative applied entity revision when known, otherwise
null. `sync_state` is `local`, `pending`, `awaiting`, `deferred` or `synced`.
Pending operations take precedence, then acknowledged edits whose receipt sequence
is beyond the local cursor, then deferred remote content; an internal deferred sentinel is never exported as revision -1.
Legacy/direct-writer data may be local even with a nonzero workspace cursor.
The caller cannot supply a replacement cursor. This projection must not be used
to skip outbox delivery or infer canonical server bootstrap completeness.

## Anchors, identity and missing data

Supported anchors are closed objects with `schema_version: 1`, `kind: word_range`,
and nonnegative `p0`, `o0`, `p1`, `o1`. Page indexes are zero-based; offsets are
inclusive source word indexes. Current storage does not supply rectangle geometry;
the projector does not invent rectangles or convert word offsets into PDF points.
Unknown/malformed anchor shapes become null with `anchor_status: unsupported`;
their note/highlight text remains available and read-only where appropriate.
Absent anchors use `anchor_status: absent`.

Highlight PDF hashes come from their stored document hash. A note has a PDF hash
only when its anchor explicitly contains a valid SHA-256 `document_hash`; no hash
is guessed from another highlight or the currently downloaded PDF. Consumers must
verify matching PDF bytes before placing any anchor, including `available` anchors.
Hidden AI highlights retain `hidden: true` so an importer cannot revive them silently.

Notes without portable mappings, changed mapping identities and missing paper/list
references cause errors instead of silently losing research. Anchored notes and
non-note records are readable, but `editable` is false because the write contract
cannot represent them. A true editable flag means the text-note shape is supported,
not that a browser is authenticated or the workspace has completed bootstrap.
Orphan list surveys left by legacy deletion require explicit recovery/reconciliation;
the projection does not discard them or mutate the database to repair them.

## Verification and gaps

`tests/test_sync_projection.py` uses the actual research schema and checks ordering,
content/anchors/reasons, portable identities, secret-field exclusion, safe URL
filtering, limits, missing references, read-only/no-create behavior, pending/deferred
states, and snapshot/cursor coherence during a concurrent WAL commit.

Remaining: authorized read-manifest delivery, canonical server bootstrap, file and
deck manifests, PDF availability verification, private mobile session integration,
all-entity revisions and complete runtime writer coverage. No mobile/cloud/live
research tests or actual attachment reads are claimed by this module.
