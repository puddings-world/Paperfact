# Retained raw slide drafts: closure and restart plan

Status: partial local implementation, not shipped. Normal raw retention, original
restart review and owner backup/detached reading have local coverage; a confirmed
first-write failure and broader portability remain open. Read
[implementation and evidence](raw-slide-draft-implementation.md) first. The plan
below remains the required end state, not a completion claim.

## Observed gap

sync_deck_publication._retain_original_draft stores a bounded raw deck plus its
original observation when a worker outlives a workspace switch. The row remains
in the original native database. It does not independently pin every used image
or evidence byte. sync_recovery therefore accepts only images already pinned by
the observed prior artifact and explicitly refuses unpinned research assets.
ResearchReview can display the raw row, but cannot safely apply it as a deck.

Do not remove this refusal, drop figures or substitute the current PDF. Do not
reinterpret serialized paths or the old device binding as executable authority.

## Required storage seam

1. Preserve the existing research_file_drafts row and original strings unchanged.
   Add an explicitly versioned auxiliary closure keyed by the same candidate ID;
   initialize only inside an explicit draft-retention/migration transaction.
2. Encode the complete used deck through the maintained closed deck codec. Keep
   account settings/request receipts in the private original row, not portable
   deck data. Pin used PNGs and evidence bytes from the actual in-memory producer
   result or already verified artifact. Never open arbitrary context paths.
3. Carry the original evidence snapshot through the retained-draft call. An
   evidence asset digest is not a historical PDF/input digest. Preserve unknown
   historical identity as unknown. Find originals only through owned registries
   and explicitly trusted source roots.
4. Stage verified blobs before committing the draft plus closure atomically.
   A staged cache object without a row is not an active deck or current ownership.
   Preserve the open result and a truthful failure if original database/storage
   was replaced or byte closure is unavailable. Never redirect to global settings.
5. Existing rows need an explicit inspect/prepare/confirm migration using trusted
   original bytes. Do not silently retrofit old source or parent observations.

## Required consumer seam

- On restart, show retained drafts separately from the current applied deck.
  Explain available/incomplete assets and offer read/export without AI calls.
- Verified typed drafts use the same displayed-base operation boundary as managed
  candidates, preserving current manual edits and original sources. Known deletion
  needs an explicit restore choice and a fresh incarnation.
- A recovered/copied row never reuses an old job, native owner, epoch or device.
  It needs a fresh local review against the chosen current logical paper. Do not
  infer equivalence from a matching local ID/title or silently retarget a source.
- Keep the full scientific content even if the comparison view abbreviates text.
  Restart/cancel/failure must retain the original draft, not just the last editor.

## Portability is part of this feature

Add closed schema/row/asset validation to initial enrollment, list packages,
snapshots, full backup, detached restore and fresh editable recovery. Retain all
required originals and exact used PNG/evidence bytes. Sharing must not disclose
credentials, private executable contexts or arbitrary local paths. Raw private
history in a complete owner backup remains inactive provenance.

Live multi-device draft/history support needs a typed portable record and stable
semantic identities distinct from local review receipts. Implement the supported
operation and projection on desktop/PWA together; do not call archive-only copy
or blob availability live synchronization.

## Behavior matrix

| Scenario | Required observation |
| --- | --- |
| Workspace switches before a generated result is saved | Raw row and complete closure stay in original A; B unchanged. |
| A has been replaced or rebound | No write into the replacement; original result remains recoverable. |
| New generation introduces images absent from prior deck | All used bytes survive restart and explicit export/import. |
| Evidence/PNG is missing, changed or truncated | No partial publication; complete-backup refusal remains explicit. |
| Failure after staging or after first row | No half-record/ownership/outbox; retry does not duplicate. |
| Current manual deck changes while draft review waits | Preserve current and draft; fresh review required. |
| Deleted deck or deleted/recreated paper | Explicit typed restore only; never attach to a new parent silently. |
| Original A, current primary B, unavailable original C | Exact A/B remain distinct; unavailable C is not fabricated. |
| Backup/package to independent editable workspace | Full content/figures/notes restored; no old execution authority. |
| Repeated clicks, pending switch, closed view | One job, no wrong delivery, no late activation. |

Run affected behavior tests, then consumer/portable integration groups. Record
fixture and local HTTP evidence separately from physical Windows/Apple Silicon
Mac/mobile acceptance. Run the current complete check before commit or release.
