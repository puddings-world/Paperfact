# Portable SQL research content

Private v2 adds `research_content` without changing existing list, paper or plain
note envelopes. Each entity belongs to exactly one paper or list incarnation.
Its ID is UUID5 over `(scope kind, portable scope ID, feature, key)`. Concurrent
edits to different citations, conversations or analysis features are independent.
This is not a whole-paper snapshot or arbitrary SQL/JSON replication interface.

A put payload has exactly `scope`, `feature`, `key`, `data` and
`source_document_hash`. Scope has exactly `kind` and `id`; `data` has the closed
feature-specific fields documented by `FEATURES` in `sync_content.py`. A delete
has an empty payload and retains the same graph parent/identity. Projection markers
prevent an old-incarnation retirement from erasing a restored local row.

| Feature | Actual local projection | Logical key |
|---|---|---|
| `dive` | `dives` | `main` |
| `close_reading` | `close_readings` | `main` |
| `citation` | `cites` | `ref_key` |
| `followup` | `followups` | `work_id` |
| `context` | `paper_context` | `main` |
| `resource` | `resources` | credential-free HTTP(S) URL |
| `manual_highlight` | `pdf_highlights` | stable mapped UUID |
| `ai_highlight` | `pdf_ai_highlights` | document hash + `source_key` |
| `chat` | `chat` | stable mapped UUID |
| `list_survey` | `list_surveys` | `main`, under a list parent |

Integer IDs never travel. `research_content_identity` preserves local chat and
highlight IDs and maps incoming items to new local integers when necessary.
Existing paper identity mappings translate every paper scope. No title/DOI merge
is guessed. SQL table names, paths, credentials, model configuration and unrelated
`kv` entries are not accepted as payload data.

The existing v2 note's exact `{paper_id, body}` form remains supported. Its explicit
rich form has exactly `paper_id`, `body`, `kind`, `created_at`, `page`, `anchor`.
It uses the existing stable note ID and a `research_rich_note_projection` marker;
legacy plain writes still cannot overwrite an anchored/non-text note. Rich notes
preserve creation identity and existing local integers. V1 behavior is unchanged.

## Validation and provenance

- The operation remains at most 256 KiB; content payloads are at most 240 KiB,
  and individual bodies at most 200 KiB UTF-8. Oversized content is rejected before
  projection, never truncated. Generic large-content manifests are a later extension.
- Timestamps are bounded timezone-aware ISO strings. Integer/boolean-like fields
  are explicitly typed and bounded. Citation context arrays and reading
  recommendations have closed bounded shapes; no arbitrary nested object is accepted.
- Text anchors contain only `p0`, `o0`, `p1`, `o1` and an optional document hash.
  Ranges must be ordered nonnegative integers. Unknown legacy provenance remains
  unknown; no current-PDF hash is invented. Conflicting hashes are rejected.
- Highlights require their exact source PDF hash. Analysis provenance is nullable
  and remains independent of the current primary PDF; an old analysis stays
  readable after replacement. Reader activation/anchor checks remain responsible
  for deciding whether coordinates can navigate the current document.
- Snapshot order is not a synchronized conversation-order contract. Existing chat
  rows retain their local IDs; a cross-device total conversation ordering UI remains
  a separate concern from retaining every individual message.

## Capture and projection API

All functions take an explicit caller SQLite connection and perform no network,
AI, filesystem discovery or commits:

- `initialize_content(conn)` creates only adapter tables in a caller transaction.
- `enroll_content_identities(conn)` records deterministic device/workspace-local
  integer identities without changing research content.
- `content_identity(conn, table, row)` and `content_payload(conn, table, row)` are
  read-only first-touch helpers. A newly inserted integer row receives the same
  deterministic identity that enrollment later persists.
- `snapshot_content(conn, tables=None)` returns `{(kind, id): payload}`; the optional
  table filter avoids scanning unrelated research. Notes use `kind='note'` and the
  rich payload. `CONTENT_TABLES` and `TABLE_FEATURES` enumerate the closed SQL scope.
- `write_content` and `write_rich_note` run through `research_writer` inside the
  journal transaction. They update only their own row, preserving unrelated data.
  Capture must run the projector under its own capture suppression even when local
  DML already ran, so projection markers are recorded. Already-deleted captured
  rows can retire safely; exact journal retries do not invoke the writer twice.

Capture/AI callers must retain the observed entity revision, pending predecessor,
parent incarnation and input-document identity from the start of an edit/job.
Do not construct a fresh base after a long-running AI response and thereby rebase
over a user's edit. Recheck observations in the write transaction; preserve a stale
candidate for explicit review. The ordinary journal enforces pending chains but
does not itself compare a local operation's base with every newly received head.
Authority-side stale-base conflicts and existing explicit resolution remain intact.

The registry is inert outside explicit enrollment/capture. Strict validation here
does not alter legacy unbound app reads. Incompatible existing content must be
reported for reconciliation, never silently rewritten or omitted during enrollment.

File-only scopes (`presentations`, figures/text caches, paper-highlights,
reading-links, material-positions and research-questions JSON) are explicitly not
enrolled by this SQL registry. The PDF-only document transfer is not a generic JSON
transport. Bundle ownership/hash checks are not substitutes for this closed schema.

For notes originating in the legacy two-field protocol, creation time was local
receiver metadata rather than shared identity. Reconciliation uses the verified
birth receipt to handle those old timestamps; native rich-note creation metadata
remains protected. Stable note IDs and parent bindings are preserved.
