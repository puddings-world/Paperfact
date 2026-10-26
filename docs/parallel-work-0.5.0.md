# v0.5.0 parallel work and Claude handoff

Status: **Claude dispatch awaiting workspace trust**, 2026-10-26.
An isolated `Paperfact-mobile` worktree on `feature/0.5-mobile-reader` exists.
The native Claude CLI refused launch with `Workspace not trusted`; the owner must
accept that folder's first-use trust prompt. No running Claude session or completed
mobile work is claimed. Parent continues core development while this gate is pending.

Card M is reserved for that Claude worktree. Cards R and U have completed their documentation
(`release-readiness-0.5.md` and `workspace-settings-0.5.md`), not runtime acceptance. The parent owns shared contracts and integration.

## Ready-to-paste task: mobile research reader

> Continue Paperfact v0.5.0 in the active `Paperfact` repository, not the archived
> `paper-daily` checkout. Read `AGENTS.md`, `docs/roadmap-0.5.0.md`,
> `docs/sync-service-contract.md`, `docs/sync-research-adapter.md`,
> `docs/sync-attachments.md`, and this document before editing. Inspect the current
> branch and working tree; preserve other sessions' files and local research.
>
> Own only a new `mobile/` directory and `docs/mobile-0.5.md`. Build an independent
> mobile reader shell with durable offline text notes, an in-memory fake transport,
> and tests. Do not edit Python sync/core modules, desktop code, root build/check
> scripts, package versions, root README/CLAUDE/AGENTS or the shared work ledger.
> Request a coordinated change when those boundaries need extending.
>
> Start with synthetic research and the proposed DTO below. Isolate transport,
> storage, domain semantics and UI; do not build around assumed HTTP endpoints.
> Return the file list, exact test command/results, a full-check integration entry
> point, contract questions and live-browser gaps to the parent. Do not deploy,
> upload private research, create accounts, publish, or commit another session's work.

## Deliverable and current integration boundary

- Responsive installable PWA shell: list overview, paper reader and text-note editor.
  Read PDF availability, explanations, citations, highlight reasons and slide previews.
  Full mobile slide editing and AI execution are outside this task.
- Pure JavaScript semantics and fixtures shared by the UI and fake transport.
  Match version-1 list/note operations and service events; reject unknown versions,
  changed retries, event gaps and wrong workspace identities.
- IndexedDB persistence, scoped by workspace and local device identity. Persist a
  note edit and its outbox entry in one transaction; preserve both through reload.
- Show separate local save, queued upload, synchronized, conflict, offline-file and
  failure states. A failed transaction must never display "Saved". Keep both versions
  of a conflicting note, with an explicit resolution path that can itself conflict.
- Refresh on launch, foreground return, reconnect and manual retry; deduplicate
  concurrent runs. Background sync is optional and never a delivery guarantee.
- Preserve selection, reading position and unsaved editor drafts during refresh.
  Offer resume on another device without automatically jumping the active reader.
- Touch-friendly controls, keyboard navigation, readable type, accessible status
  announcements and externalized English/Traditional Chinese strings.
- No automatic AI calls, PDF fetching or analytics consent from incoming research.
  Explicit offline download may fetch the selected authorized attachments only.

The Python reference service exposes **in-process methods**; a bounded loopback
HTTP adapter is being developed separately. Neither is a production browser-auth API. The client has a local journal, bounded push/pull, ordered events and retained
conflicts. The research adapter currently supports list metadata and **unanchored
text notes only**; paper metadata must already exist before a note can be applied.
Do not represent generated fixture papers as already replicated by that adapter.

Transport-facing methods may be `loadReadManifest`, `push`, `pull`, and `fetchBlob`
behind an injected interface. Their HTTP routes, bootstrap consistency, private
browser authentication and authorized attachment access remain integration work.
Do not expose reference `enroll` or `revoke` as unauthenticated web endpoints.
Do not claim public login, E2EE or production cross-device sync is shipped.

## Proposed read-manifest DTO (review before integration)

This is a **proposal for a read projection**, not an accepted server response or
replacement for the operation envelope. Keep a versioned synthetic fixture in
`mobile/`; send deviations to the parent rather than changing Python contracts.

| Field | Proposed content |
|---|---|
| `schema_version` | `1`; unsupported versions are read-only/error, never coerced |
| `workspace_id`, `cursor` | Workspace identity and consistent snapshot/event cursor |
| `lists[]` | `id`, `name`, `note`, `revision`, ordered `members[{paper_id, position, state}]` |
| `papers[]` | `id`, `title`, authors, year, DOI/URL, PDF asset reference, analysis sections and citation summaries |
| `notes[]` | Portable `id`, `paper_id`, `body`, `revision`, `editable`, optional read-only anchor/PDF hash |
| `highlights[]` | `id`, `paper_id`, quote, reason, PDF hash and versioned page/rectangle anchor |
| `decks[]` | `id`, `paper_id`, revision, ordered slide text/speaker notes and asset references |
| `assets[]` | Opaque attachment ID, SHA-256, byte size, media type and document-version association |

Use references instead of embedded file bytes. Do not accept local paths, provider
credentials, unrestricted HTML, scripts or arbitrary fetch URLs in this DTO.
Render research text safely; remote markup is untrusted. A hash proves byte
integrity, not ownership authorization. Verify the PDF hash before displaying its
anchors. Show missing/corrupt assets honestly rather than marking a deck offline.
Bootstrap must eventually bind the manifest and cursor to one consistent snapshot.

## Existing text-note operation shape

```json
{
  "version": 1,
  "operation_id": "op-example-1",
  "workspace_id": "workspace-example",
  "device_id": "device-example",
  "entity_type": "note",
  "entity_id": "note-example",
  "action": "put",
  "base_revision": 0,
  "depends_on": null,
  "payload": {"paper_id": "paper-example", "body": "A synthetic observation"}
}
```

For deletion use `action: "delete"` and `payload: {}`. Identifiers and envelope
limits must match `sync_journal.canonical_operation`; do not add anchor, timestamp
or credentials fields. Preserve an operation ID for retries. Consecutive offline
edits depend on the latest pending edit; do not issue every edit against revision 0.
An anchored note can be read from a projection, but cannot be edited through this
limited write contract. Reading-position writes need a separate agreed entity type.

Explicit resolution adds optional `resolution_of` with the original conflicting
operation ID. Only an accepted resolution event closes that conflict on every
device. This private unreleased protocol is evolving; read the latest service
and client contracts before integration and reject unrecognized fields.

Service events contain exactly `sequence`, `outcome`, `operation`, `head` as defined
in [the reference contract](sync-service-contract.md). Store remote application,
receipt and cursor atomically, without generating a new local operation. Keep
conflicted branches in local history; a canonical head must not erase a draft.

## Required acceptance and handback

1. Automated pure-JS tests: duplicate/reordered delivery, wrong workspace/version,
   offline chains, lost response after commit, edit/edit and edit/delete conflicts.
2. Storage tests: note plus outbox atomicity, reload, write/quota failure, unsent
   content export and account/workspace switch while a request is pending.
3. UI tests: empty lists, cancel/delete, repeated saves/retries, failed downloads,
   stale responses, focus/draft preservation and accessible status changes.
4. Service-worker/cache tests: app shell loads offline; private data and credentials
   are not indiscriminately cached across accounts. Sync sign-out must stop work;
   do not silently delete unsent notes or imply revocation erases downloaded copies.
5. Browser evidence: record actual IndexedDB/offline reload behavior separately from
   fake-storage tests. Label any untested Safari/iPhone or Android path explicitly.
6. Return a single deterministic command for mobile automated tests and its dependency
   requirements. The parent integrates it into `scripts/check.py`; do not leave the
   mobile suite as an optional, undiscovered test command.

Use fixtures only. Never collect real prompts, access live AI plans or repeatedly
invoke real login as a stress test. Ask the parent for the approved transport/auth
contract when the shell reaches that boundary; continue independent fixture work.

## Other independent task cards

| Card | Reserved ownership | Deliverable | Depends on |
|---|---|---|---|
| M — Mobile reader | `mobile/`, `docs/mobile-0.5.md` | Shell, IndexedDB notes, fake transport, tests, integration questions | Existing journal/service semantics; real transport/auth later |
| R — Release readiness | New `docs/release-readiness-0.5.md` only | English OS/mobile acceptance matrix, source/install upgrade and backup/restore checklist, evidence placeholders | Scope now; actual packaging only after core gates |
| U — Workspace/storage UX | New `docs/workspace-settings-0.5.md` only | Wireflow/copy for location, storage, offline pinning, devices, backups, conflicts and recoverable deletion | Attachment and lifecycle contracts; no desktop implementation yet |

Card M awaits the trust gate; R and U documentation is complete. Coordinate
with the parent before editing another card. R and U must not mark checks passed or invent shipped
behavior. No task owns root documentation or another card's files implicitly.

| Integration gate | Core owner provides | Independent task can do now |
|---|---|---|
| Read projection | Agreed entity shapes, consistent snapshot/cursor | Versioned synthetic projection fixtures and UI |
| Note synchronization | Stable identities, semantic fixtures, conflict contracts | Durable note/outbox and matching fake transport |
| Attachments | Authorization, hash manifests, repair/pinning lifecycle | Missing/downloaded/error UI and hash-bound fixtures |
| Private browser access | Reviewed identity/session/CSRF and revocation flow | Injected session state; no production-auth claim |
| Release | Full check integration and platform artifacts | Test command, reproducible fixture journey and gap list |

Progress and accepted contract changes belong in the parent
[implementation ledger](implementation-0.5.0.md). A handoff file is not evidence
that a Claude session received, accepted or completed the task.


## Core handback available to the mobile owner

- [Client and resolution semantics](sync-client.md): includes awaiting-receipt causal
  protection and explicit `resolution_of` events; ordinary edits do not clear conflicts.
- [Loopback HTTP](sync-http.md): bounded transport for developer integration only;
  public browser sessions, hosted TLS and read/blob authorization remain separate.
- [Local read projection](sync-projection.md): implemented DTO with `capabilities`
  and `local_state`; distinguishes unsent/deferred content and is not server bootstrap.
- [Next entity contract](adr/0003-research-entity-capture.md): draft parent/child
  identities and capture rules; do not implement draft kinds as if already accepted.
