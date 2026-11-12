# Resume an archived note draft

v0.5 acceptance contract, 2026-11-01. **Implemented in the isolated local candidate; release gates remain open.**
This extends the text-draft/source-viewer work with a separate note observation. It does not
replace the remaining [full draft contract](review-draft-resumption.md) or
[release scope](roadmap-0.5.0.md). No independent Claude session is assigned.

## Researcher outcome

Recover a human-edited note, choose the receiver's existing note, inspect its
recorded original A alongside current B, continue editing and explicitly apply.
Retain the archived variant and both source versions. Retry creates one accepted
change. This flow performs no model call, cloud login or implicit note creation.

## Maintained schema boundaries

- SQL notes have an autoincrement integer identity and paper/body/kind/created_at/
  page/anchor fields. Portable rich notes use stable `research_note_identity`
  mappings and a parent incarnation, not an integer copied from another device.
- `sync_content.validate_rich_note` validates the closed rich-note payload. A
  visible page is one-based and must agree with the anchor's zero-based `p0`.
- `write_rich_note` refuses moving an existing note to another paper or changing
  its creation identity. Preserve the receiver target's ID, paper and created_at.
  Body/kind/page/anchor come from the reviewed draft; never retain B's anchor while
  replacing its body with A's text. Original creation metadata remains archived.
- A remote note draft is not a generation-table row. Use a separate typed origin
  and closed observation, not a fabricated `GenerationContext` for `notes`.

## Proposed typed observation

- Explicit current database path/native identity and local workspace/device binding.
- Receiver local note ID, stable note UUID, full displayed SQL note and actual
  `sync_capture.observe_note` token, including note and parent incarnations.
- Receiver paper ID, current parent row/local epoch and observed selected PDF B.
- Immutable archived draft ID/hash and its exact recorded source/anchor A.
- Process-only staged-original proof. It is never serialized into draft JSON.

A managed editable workspace is local and works offline without a sync login.
Detached history requires explicit editable adoption; do not reactivate old jobs,
bindings or note mappings. Define a durable local-note observation before allowing
an unbound legacy store to write; a copied integer/timestamp is not enough.

## Operations and atomic save

1. List bounded existing note targets with their paper and a short readable excerpt.
   Empty selection/cancellation leaves research and private state unchanged.
2. Capture only the explicitly selected current note. Show the current body/anchor,
   retained body/anchor and A/B versions. Missing recorded source stays unknown;
   never infer it from the current target. Contradictory recorded hashes refuse.
3. Save edited variants privately with CAS and the displayed base. Restart retains
   that base and requires fresh source verification; it never silently rebases.
4. Verify A through receiver-owned bytes on a worker. Reuse the common prepared-
   source validation/staging seam, not a deck/claim/text-draft permission. Add a
   separate note observation adapter to the read-only original capability.
5. In one caller-owned transaction, recheck archive, note identity/incarnation,
   parent, binding, displayed row and source. Publish original-source ownership,
   typed manual note, outbox and retry receipt together. Carry the actual note
   observation through commit. Source association is the reviewed anchor A; do not
   pass a research-content source override for an entity of kind `note`.
6. Re-backup and transfer the accepted rich note/A to an isolated peer. Private
   drafts and receipts remain local archive history, absent from public wire.

## Required evidence

- A real remote note conflict and saved human draft, not a hand-built arbitrary map.
- Plain and anchored notes; exact A/current B; no source; malformed or contradictory
  anchors; page conversion; protected creation identity and parent ownership.
- Two variants/restart/two-window CAS; target removal/recreation; parent lifecycle;
  empty/cancel; source failure/retry; concurrent duplicate activation.
- Hold preparation, switch draft/workspace or close, then release the same worker;
  no late viewer or write. Inject failure after source publication and verify all
  ownership/research/outbox/receipt rollback, with private edits retained.
- Actual bilingual UI, source viewing, second backup/detached inspection and peer
  note/source round trip. Preserve every existing assertion; no paid calls or owner DB.
- Explain each action/outcome/limit in the maintained test catalog. Run affected and
  interacting selections, then the full gate before commit or release. Installed
  Mac/phone, hosted identity/service and scholarly quality remain separate gates.

## Previous local verification checkpoint

Current frozen selected gates: **24 passed** for new note/report-default scenarios (474.38s runner); **100 passed** for existing text/source/draft interactions (422.83s). Both use the same 957 inputs with zero drift/failure/error/skip. These are selected checks, not a complete app pass. Report/catalog/docs verification is recorded separately.

The real journey covers conflict, two human variants, editable adoption,
restart, exact A/current B, atomic apply/retry, reference-service peer and
second detached recovery. All older test inputs remain unchanged.
Additional malformed/partial/nested-carrier controls, source page/anchor
boundaries, other target/lifecycle variations and unsupported legacy/unbound
note observations remain required. This contract is not declared complete.
[Action-by-action explanations](testing/note-resumption-scenarios.md).

## Source location and owner continuity checkpoint

Actual selectable PDF word indices are checked against the recorded original, not
character offsets or the current PDF. Endpoints use the reader's indexed word
stream; rotated labels are not selectable. A private recovered cache observation
pins native index identity, workspace/device/database binding and source size.
Apply and original revalidation recheck that observation; unrelated cache writes
can revalidate the same base. Observations are process-only, absent from drafts
and public sync payloads. Explicit failed verification revokes old Apply permission;
the real English/Chinese UI retains text and disables Apply until successful retry.

Positioned drafts without a recorded PDF version remain private and need an
explicit source-mapping flow; no B attribution is inferred. Plain source-less
notes remain supported. Basic corrupted/incomplete provenance, other existing
note creation identity and source/page bounds have focused coverage. Deeper
recovery/legacy/cross-paper/parent controls and the full release gates remain open.
[Executed actions and durations](testing/note-source-check-results.md).
