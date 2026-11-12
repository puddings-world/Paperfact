# Local proposal packages and complete rescue copies

Status: implemented in the isolated 0.5 integration candidate; unreleased.
The matching joint execution receipt is described in acceptance-map.md. No current
whole-application check, installer or physical-device acceptance is claimed.

## Observable scenarios

| Test file | Actions | Required observable outcome |
| --- | --- | --- |
| test_local_deck_proposals.py | Prepare existing or genuinely absent targets; retain, restart/read, replay, cancel, replace native DB/CAS, update or recreate a parent; enter a caller-owned import transaction before paper writes. | Full codec content survives. Native/null binding/source/parent checks remain strict. Ordinary same-lifetime metadata updates require the explicit import option; standalone pending work does not gain that option. A failed transaction grants no proposal ownership. |
| test_local_proposal_packages.py | Public list export/import into an empty local-only receiver, explicit Review/Apply, repeated import, existing metadata preserve/replace, and failure after proposal adoption. | Complete images/evidence/original A survive beside primary B. Manual notes persist; existing slides change only after explicit Apply. Repeat import is idempotent; research/catalog/files roll back together and retry works. |
| test_local_deck_review.py | Confirm/cancel Apply, repeat 25 times, deny the SQL receipt after file installation, manually save or touch the slot, rename, delete/recreate, or close. | Active files/history/receipt are atomic; the old deck is byte-exact in history. Own verified rollback permits exact retry; an external same-byte rewrite does not. Changed parent/base refuses without replacing current slides. |
| test_local_proposal_review_ui.py | Use actual English/Traditional Chinese Qt review controls, cancel then confirm, rapidly repeat Apply, close during held verification. | Paper titles identify candidates; status is localized and local-only. All PNGs/notes survive; one history and one decision are saved. Closing cannot deliver into the obsolete view or apply research. |
| test_local_rescue_import.py | Read a complete ZIP, retain/replay, fail after catalog insert, retry through app-owned PendingDeckResults, recreate parent, remove original file/DB, export, deny flush, overlap actions, and recreate parent during actual source staging. | No auto-enrollment or active deck write. Unsaved actual output remains app-owned, exact retry preserves its Deck, and complete science exports even after the original file/database disappears. Existing destination and pending result survive export failure. No stale target adoption or duplicate action. |
| test_local_rescue_import_ui.py | Open/preview all PNGs, select a real local paper, retain then Review, cancel/confirm Apply; close after failure or during an admitted worker. Add an evidence-only fourth image citing a separate original, recognize ZIP content despite its filename, cancel then export through the actual PendingDeckPanel controls. | Actual native flow preserves full science; current slides stay unchanged until confirmation. Pending result is held before late GUI delivery. Evidence-only PNG/caption/original survive without modifying the scientific deck catalog. |
| test_portable_deck_archive.py | Actual ZIP roundtrip, closed object list/hash checks, malformed/path/symlink/repeated members, cancellation, overwrite refusal and explicit overwrite. | Complete originals/images/scientific JSON; no writer authority. Bad bytes refuse. Failed publication preserves prior user files and removes its own stage. |
| test_portable_deck_proposal.py | Encode/decode sanitized scientific metadata, union of deck/evidence figures, exact original set, unknown source and malformed/oversized data. | Preserve complete scientific fields and all used/unused PNGs. No current-PDF substitution, source ownership, paths, account credentials or sender writer observation. |

Adjacent controls in the joint selection retain the enrolled raw-v1 rescue,
ordinary list packages, pending generated results and existing review/dialog flows.
The first exact selection lives in ignored build/local-rescue-joint-result.json,
XML/log/inputs:299passed/1failed. The legacy-call repair and two new controls are
bounded by local-rescue-fix-scope.json; final affected21cases pass in
local-rescue-affected-final-result.json with matching XML/log/inputs. This is not
a new full300 pass; do not add historical overlapping counts.

## What is not proven

- The enrolled raw-v1 package bridge still explicitly refuses a valid evidence-only
  fourth PNG. The independent genuine RED is recorded in the portability design;
  it is not included in this joint passing selection or hidden as a skipped case.
- Complete ZIP rescue into an enrolled workspace is not implemented by the new
  null-binding local adapter. A present malformed/partial binding cannot opt out.
- Local retained proposals are not yet enrolled into complete live sync/history,
  independent backup/fresh editable recovery or the applied source/material resolver.
- App-owned memory rescue does not survive forced process termination when no
  durable storage is available. These tests are not arbitrary power-loss testing.
- Native Qt fixture execution is not an installed Apple Silicon Mac or real phone.
  Synthetic model results do not certify provider auth/quota, billing or science.

## Verified fixes encountered in this integration

- The actual Windows fsync call rejected a read-only stage descriptor. The owned
  stage now opens read/write for the flush; archive roundtrip and failure controls
  retain the complete-export requirement.
- The maintained Deck decoder supplies four text-style defaults. Validation now
  compares its UI projection with the same decoder, while catalog/export preserve
  exact original scientific JSON. The original JSON/evidence equality assertions
  are explicit; this is not permission to normalize away scientific fields.
- Confirmed metadata replacement originally conflicted with its own before-state
  guard. The ephemeral import grant permits same-epoch updates only when the public
  importer explicitly passes replace=True. Original capture and actual post-import
  ownership remain separate; standalone retain and parent recreation remain strict.
