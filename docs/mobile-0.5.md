# Mobile reader implementation — v0.5

Status: isolated `0.5.0.dev` integration candidate, updated 2026-11-02. This is not
a public release or completed cross-device acceptance. The separately maintained
0.4.x line remains for daily use. See [current status](status-0.5.0.md) for exact
evidence and remaining gates.

## Local startup and header

The last successfully opened workspace reopens offline from existing IndexedDB,
with paper selection/drafts/outbox preserved and no cached credential or automatic
authentication. A metadata-only hint remembers workspace/device/origin. Missing or
corrupt cache refuses rather than initializing empty research. Narrow headers use
two rows with complete labels and touch targets. [Contract and exact limits](mobile-workspace-startup.md).

## Implemented slice

- Responsive list overview and paper reader, with English/Traditional Chinese
  controls, keyboard tabs, touch-sized buttons and accessible status announcements.
- Plain-text explanations, citations and highlight reasons render as text, never
  remote HTML. No AI, analytics, URL crawling or automatic PDF fetch is triggered
  by incoming research.
- Editable unanchored text notes and per-membership reading state use actual
  private v2 operation envelopes. Legacy DTO1 is read-only compatibility input.
- IndexedDB commits local content/outbox in one workspace/device transaction;
  failed writes never claim a saved note. Drafts remain separate from canonical
  content, with local recovery export and unsaved-edit close protection.
- An editor captures the note operation/incarnation, paper incarnation, base
  revision and causal predecessor it observed. That observation persists beside
  the draft and is required for existing-note saves/deletes. A remote edit during
  typing or after reload cannot silently rebase the old draft: save/delete rejects,
  both texts remain readable, and the user can save the draft as a separate note.
  Receiving an acknowledgement of the same observed operation is not a stale edit.
- Workspace changes flush dirty text and its observed revision atomically into
  the old scoped store before closing it or resetting the view. This also covers
  switching before the input debounce fires. Failed flushes leave the old workspace
  and editor intact; the next workspace is not opened as a false success.
- Stable operation IDs, causal offline chains, acknowledged receipt gaps,
  contiguous event application/cursor commits and retained conflicts. Explicit
  note resolution can conflict again; delete/restore never silently revives content.
- Session identity is checked against both workspace and device before sync or
  file access. Credentials exist only in memory, travel only in authorization
  headers and are excluded from storage, recovery export and service-worker cache.
- Foreground/reconnect/manual sync deduplicates simultaneous jobs. Disconnect
  cancels the current generation, drops late results, retains local research and
  does not pretend to revoke a server credential or erase downloaded copies.
- Each foreground pass is bounded to 100 outgoing operations and 25 incoming
  pages. Remaining queued work or an unexhausted page budget is reported explicitly;
  it is never labeled fully synchronized. Another foreground/manual pass continues.
- Explicit PDF download uses bounded authenticated blob reads, durable partial
  bytes and complete SHA-256 verification before publication. Corrupt bytes reset
  the failed transfer for explicit retry. Metadata advances independently of files.
  Opening a cached PDF rechecks its bytes and current exact document target.
- Static-only PWA shell caching. Private request responses, PDFs, credentials and
  research endpoints are never placed in the service-worker cache.

## Module boundaries

| Module | Responsibility |
|---|---|
| `store.mjs` | Atomic IndexedDB scope records; fault-injectable memory test adapter |
| `domain.mjs` | Envelopes, receipts, lifecycle graph, outbox, conflicts and projection |
| `content.mjs`, `ids.mjs` | Closed read-only SQL content/rich notes and Python-compatible UUID5 identities |
| `engine.mjs` | Session generations, foreground sync, note/progress operations, exact PDFs |
| `transport.mjs` | Fixed bounded session/push/pull/blob-read HTTP contracts |
| `view.mjs`, `app.mjs`, `i18n.mjs` | Preserved editor/selection state, responsive UI and translated copy |
| `fixture.mjs` | Synthetic authority and valid sample PDF; not production authorization |
| `sw-policy.mjs`, `sw.mjs` | Allowlisted static shell cache only |

The injected transport has `session_info(token, signal)`,
`push(token, operation, signal)`, `pull(token, after, limit, signal)` and
`blob_read(token, sha256, size, offset, limit, signal)`. Extra abort arguments are
browser coordination, not wire fields. HTTP paths exactly match the existing
reference adapter. There are no invented enrollment, login, bootstrap or manifest
HTTP endpoints.

## Bootstrap and version gates

DTO2 explicitly declares `sync_bootstrap=false`. Importing DTO1/DTO2 therefore
does **not** set a synchronization cursor, create writable graph prerequisites,
copy credentials or assume local filesystem attachments exist. Allowlisted
explanations/highlights supplement readable canonical paper metadata; imported
notes remain read-only. Deleted canonical notes cannot reappear from an old DTO.

Authenticated synchronization starts at cursor zero and requires complete retained
service history. Missing/noncontiguous history is an explicit error. New entity
kinds or unsupported operation versions stop the receiving transaction without
advancing its cursor; they are never silently dropped. The later parent SQL
`research_content` and rich notes support closed receipt/projection with historical
source hashes preserved. Canonical unpositioned text notes also support guarded
body edits while retaining their desktop metadata.

The implementation supports the baseline list/paper/membership/note/reading-state/
ordering/primary-document/research-content event kinds. Rich notes preserve
kind/time/page/anchor. Validated `kind=note` rows without page/anchor can be edited
or explicitly deleted; anchored/quotation and unsupported kinds remain read-only,
with their flatten/delete rejection guards unchanged. Singleton analyses, citations and highlights project into the
reader; chat, resource and followup records have read-only cards. Canonical content
tombstones suppress old imported singleton/citation rows. Where legacy highlight
snapshot IDs cannot be matched to portable content IDs, the retained snapshot is
shown separately without enabling coordinates, instead of reviving a deleted
canonical highlight. It does not advertise anchored/quotation note writes,
research-content writes, retirement of every conflict kind, or a complete
server-side validation reimplementation. The actual authority remains responsible
for authorization and canonical graph acceptance. Reading-state conflict history
is retained/exportable; its full resolution editor remains a follow-up UI slice.

## PDF and reader limits

The browser limit is 32 MiB per PDF in this preview, with 256 KiB read chunks. This
is an explicit resource limit, not the authority's larger manifest limit. Bytes
remain private IndexedDB data. Current desired manifests and verified files are
separate; document replacement cannot activate a late old download. Existing
older immutable bytes may remain in local storage for future retention controls.

The reader uses the browser's native PDF presentation. Hash verification plus PDF
header/EOF checks are not a full PDF parser or a security sandbox. Word-range
anchors are not converted into invented rectangle geometry: matching verified
hashes may expose a source-page link, while unknown/mismatched source locations
remain disabled. Accurate in-page highlight rendering and Safari PDF behavior
need a dedicated reader integration. No source-anchor migration is performed.

Deck/file projection is still unsupported by the baseline DTO, so the Slides tab
states that limitation. It does not fabricate synchronized slide previews. Public
PWA login, device pairing, hosted HTTPS/CORS policy, account recovery, install
packaging, storage eviction/pinning and cross-device reading-position resume are
still integration gates. The connection form is a developer seam, not shipped
browser authentication. The app starts in a clearly labeled synthetic workspace.

## Verification and parent handback

Required parent full-check entry point (Node 22+ and the project's Python):

```sh
node mobile/check.mjs --python <project-python>
```

This runs deterministic Node behavior checks, then JavaScript through the actual
Python loopback authority: authenticated identity, six-entity seed history,
offline note chains, reading state, immutable retry receipts, verified PDF reads,
concurrent edit conflict, explicit resolution and immediate edit-then-delete.
The Python authority/database/blob root are temporary synthetic fixtures.
While this isolated worktree remains based on the older core, append
`--core-root <active-Paperfact-checkout>` to run interoperability against the
parent's newer SQL-content schema. After integration, the default relative core
path is correct. This flag only selects importable fixture implementation code;
it never opens that checkout's research database.

`node mobile/browser-check.mjs <chromium-or-edge>` runs actual browser IndexedDB
rollback/reopen, note/outbox durability and retry, scope isolation, UI note save,
draft/focus/selection retention and static-shell service-worker cache checks.
An optional output directory captures desktop and phone-sized screenshots.

Evidence at handback: **58 Node checks** and actual Python HTTP interoperability passed;
four real headless Edge browser checks passed on Windows. Desktop 1320×900 and
phone-sized 390×844 screenshots were inspected: readable layout, visible actions,
no horizontal clipping. This is browser emulation, not physical iPhone/Android
acceptance. Background delivery, installed standalone mode, operating-system
eviction, private browsing, real offline restart, screen readers and live accounts
were not tested. No deployed service, real research, paid calls or account login
was used. Parent must integrate this command into `scripts/check.py` and run the
full repository check after merging the isolated worktree; this slice alone does
not claim that acceptance.

Current unpositioned text-note behavior and exact limits: [desktop/mobile editing](mobile-note-editing.md).
