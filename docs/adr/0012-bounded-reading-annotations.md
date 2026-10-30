# ADR 0012: Canonical bounded reading annotations

Status: implementation plan, 2026-10-27. Not yet enabled in the application.
Refines the storage choice in ADR 0008 without removing its observation and
retention requirements. PDFs, figures and editable decks continue to use ADR 0009.

## Decision

Store small, typed reading-analysis results as canonical SQL research content.
Keep their existing JSON files as repairable compatibility caches. The current
`paper_highlights`, `reading_links` and `research_questions` producers must use
the same captured-workspace publication boundary as other research operations.
Receiving a peer's analysis must not invoke an AI provider to reconstruct it.

| Feature | Proposed singleton table | Closed business payload |
|---|---|---|
| `highlight_analysis` | `paper_highlight_analysis` | Highlight text, page, kind, reason, source; bounded page coverage |
| `reading_links` | `paper_reading_links` | Highlight index, explanation section, explanation, analysis digest |
| `research_questions` | `paper_research_questions` | Up to six questions, reasons, exact supporting quotes and pages |

Each table has `paper_id`, `body_json`, `source_hash`, nullable `document_hash`
and `written_at`. The local `document_hash` survives ordinary bundle exports and
must equal the outer sync record's source hash; unknown legacy provenance stays
null. Keeping it only in private job receipts or sync metadata would lose source
identity when an unbound workspace exports its business rows. The outer
sync record's `source_document_hash` identifies the verified PDF bytes. The inner
`source_hash` identifies the complete analysis input; these hashes are not
interchangeable. Missing legacy PDF provenance remains explicitly unknown.

Python and JavaScript must enforce matching closed fields, text/array limits,
page types, nesting and the existing 240 KiB content limit. Limit allocations
before parsing legacy files. Do not expose a generic arbitrary-JSON operation.
Provider receipts, account identifiers, prompts and failure diagnostics are
device-local job metadata and are excluded from portable business payloads.

## Observation and publication

1. Capture the original workspace, database identity, local parent epoch, target
   absence/revision, exact input analyses and effective AI connection before work.
2. Resolve and verify the original PDF. A managed or enrolled missing PDF cannot
   fall back to an unrelated extracted-text cache or mutable filename alias.
3. Generate and validate outside the write transaction. Preserve exact accepted
   original quotes and source pages; synchronization cannot invent provenance.
4. Recheck the captured inputs and target in one publication transaction. Save
   research, outbox and retry receipt together. Changed targets retain completed
   output for review; retrying publication must not call the provider again.
5. Rebuild compatibility files only after acceptance. A failed cache write leaves
   the canonical SQL row intact and repairable. A cache must not resurrect a
   deleted canonical result or mask a newer received result.

Highlight preparation also maps quotes to PDF anchors. When an operation promises
both analysis and visible marks, commit the canonical analysis and its generated
`pdf_ai_highlights` mutations as one typed group, preserving manually hidden marks.
Linked explanation generation is a separate dependency phase with truthful partial
status. A direct analysis-only helper retains its explicitly narrower API contract.
Manual highlight add/remove must carry the displayed document version and parent
epoch through save; it must not resolve today's global paper at completion.

## Retained highlight review

The typed grouped adapter is documented in [annotation review](../annotation-review.md).
Generated requests and failed-publication sidecars use the existing sealed review
API. Analysis plus verified located marks share one displayed-base transaction;
text editing and remote single-row application are disabled for this group.
Manual marks remain independent, hidden preferences are observed inputs, and
restoring deleted content requires explicit target confirmation. Missing exact
PDF bytes never permit an anchor-bearing group to apply to a replacement.

## Compatibility and migration

- Preserve existing standalone helper fixtures and public return shapes. Introduce
  explicit workspace/connection seams rather than bypassing existing tests.
- Adopt legacy caches through bounded validation against an existing owner. Do not
  attach orphaned caches to a newly recreated parent with the same ID.
- Distinguish unknown legacy state from canonical deletion. Migration receipts and
  tombstones prevent repeated adoption from resurrecting removed content.
- Add tables to an explicit enrolled-schema migration and refresh capture triggers.
  Existing bound connections must not skip newly installed table capture.
- Sharing bundles include the business rows; old bundles remain importable. New
  optional research tables must not become mandatory in old recovery archives.
- Detached restore preserves private generation records as provenance and creates
  fresh local parent epochs; it never reactivates old-device jobs or credentials.
- The PWA stores and displays received questions, highlight reasons and explanation
  links offline. It does not need desktop cache files or a local AI account to read.

## Required evidence before completion

Tests must cover actual producers and readers, two-device delivery, offline mobile
reading, bundle re-export fidelity, old/new archive compatibility, duplicate jobs,
PDF replacement, delete/recreate, account/workspace switches, stale target edits,
storage/cache failures, retry without another model call, malformed oversized
payloads and deletion without cache resurrection. Python/JavaScript fixtures must
agree. Run the full project check after integration; isolated tests alone do not
establish complete writer enrollment. Physical-device and hosted-service gates
remain in the v0.5 roadmap.
