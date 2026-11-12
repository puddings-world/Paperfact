# Highlight draft continuation — integration contract

Status: 2026-11-02, `0.5.0.dev`, isolated integration candidate, unreleased.
The shared quote-location operation, closed manual revision core, typed receiver
selection, durable private variants/restart and independent private recovery are
implemented. Owned-reader material navigation includes queued-source handoff.
Exact-original verification, independent reading and confirmed whole-group Apply
are implemented as backend operations; see [source verification](highlight-source-verification.md)
and [atomic application](highlight-draft-application.md). Actual local recovery,
remote-analysis resolution, offline peer hiding/notes and second backup have focused
evidence. The native highlight editor and transport tools are **not implemented**;
their complete interrupted journeys and installed-device acceptance remain open.
See [private-state boundary](highlight-draft-private-state.md) for exact scope.

## End-to-end outcome

Retain a highlight analysis with its original PDF A and two human draft variants;
back up, recover without the old folder, explicitly select a receiver, inspect A while
current B remains selected, edit/verify/confirm the complete group, then carry an
offline peer's reviewed change back and recover another backup. Existing manually
drawn and hidden/deleted marks must retain their meaning. No paid call is necessary
for manual edits, source inspection, synchronization or recovery.

## Implemented content boundary

- `research_evidence.locate_quotes_snapshot` locates bounded quotations in immutable
  captured original bytes without fabricating a claim, judgment or write grant.
- `highlight_draft_revision` binds the entire saved highlight-analysis SQL row and
  original document hash, accepts at most32 editable quote/page/anchor/role/reason
  items, and rebuilds locations, source labels and compatible mark keys.
- Missing, ambiguous, wrong-page or reader-unselectable passages stay unresolved.
  Any unresolved item prevents analysis/mark-group output; no partial Apply plan.
- Preserve prior page/empty-page/chunk coverage as provenance of the old analysis.
  Selected quotes do not imply full-document coverage or a new model analysis.
- `revise_for_receiver` permits explicit content identity mapping only. It does not
  own or authorize a target, stage source ownership, change SQL or resolve conflicts.

## Required complete operation and storage integration

Backend portions of1–7 now have focused implementation evidence as documented
above. Native/transport delivery, complete derived-link audit, interruption and
installed-device requirements remain open. The numbered contract still defines
the invariants each entry point must preserve.

1. Add a typed `highlight_resume` domain only together with its closed snapshot codec,
   owner checks and saved-body validation. An allowlist change alone is insufficient.
   Observe the actual native database, enrolled binding, local/portable paper IDs,
   parent epoch, complete current analysis, AI marks and their causal observations,
   manual marks and hidden/deleted choices. A single mark is not the entire analysis.
2. Decode generation, sidecar, remote and archived inputs through their actual typed
   records. Preserve source/original/current separately. Remote conflicts require
   the complete causal conflict observation and the correct group closure contract.
3. Use the shared private draft journal and explicit variants with compare-and-save
   revisions. The typed body bound is220KiB; the generic200KiB limit must not silently
   truncate it. Reject duplicate/nonfinite/unknown/oversized data. Private saves do
   not publish research or sync credentials. Historical owner paths are provenance,
   never restore destinations. Backups validate the complete closed typed codec.
4. Reuse independently owned original sources and the existing bounded staging/cache
   path. Do not follow sender paths, silently recapture a newer target, activate B as
   A, serialize runtime proofs, or resurrect a retired original. Recovery may read
   only a complete independently verified recovered private source group.
5. Verification captures exact A, invokes the shared content core and rechecks source
   and receiver observations. Source hashes for PDF bytes and extracted page text
   are distinct. `source_hash` is not a content-revision hash. Whole-body/mark CAS is
   required even when the same PDF and extracted-text digest remain unchanged.
6. Human-hidden AI marks and deleted analysis/marks require explicit restoration
   choices, preserving tombstone history. Manual marks are not replaced by AI marks.
   The core's mark proposals deliberately cannot decide restoration or visibility.
7. One transaction owns source publication/ownership, complete analysis, AI mark
   group, outbox, decision receipt and private-draft receipt. Failure after an early
   write rolls everything back. Identical request retries return the committed
   result; changed payload or stale observation refuses without overwriting work.

## Native UX and shared transports

- Use fields for quotation, role, reason and page, plus explicit occurrence choice
  for repeated text. Ordinary users do not edit raw JSON. Show original A and
  current B clearly, retain unsaved edits and never move the primary reader to B
  as an implicit source choice. Separate private Save, Verify and confirmed Apply.
- Bind pending work to the exact variant/revision, source, paper, window and database.
  Deduplicate rapid activation. Refuse late delivery after selection/account/context
  changes; closing must drain owned workers and retain private content.
- Desktop, CLI and host-launched MCP call the same bounded typed operation. Add
  transport discovery/schema/packaged-inventory entries only with the real service.
  Verify actual CLI processes and the official SDK, restart and duplicate requests.
  Do not invent additional provider login or a model call to store a manual edit.
- Keep independent source reading available after a decision without reviving Apply
  authority. Parent status refresh must preserve current edits and navigation.

## Required evidence before completion

Prove private save/restart/competing variants; exact-A inspection while B stays current;
full backup/detached recovery/editable adoption without old-folder reads; atomic
Apply and injected rollback/retry; remote conflict resolution and peer offline
hide/edit/reconnect; second independent backup; actual native controls and shared
transports. Include source corruption/retirement, replacement database, deleted/
recreated parent, cancellation, held workers, rapid repeated activation and close.
The initial mobile scope remains reading/highlights display and text notes; this
contract does not silently add mobile highlight editing or full slide editing.

## Other v0.5 requirements remain

Finish deck-specific continuation and remaining writers/history/file formats;
grounded lineage and durable audit output; whole-application checks; canonical
product integration and platform installers; production identity/enrollment,
hosting/storage/retention/recovery decisions; installed Windows → offline Apple
Silicon Mac → phone → desktop acceptance. Local reference fixtures are insufficient
for these external gates. No production upload or deployment is authorized here.

[Release scope](roadmap-0.5.0.md) · [Executed local actions](testing/highlight-revision-scenarios.md)
