# Retained rescue proposal portability: bounded audit

## Proven earliest gap

One synthetic integration test uses actual `bundle.export(..., with_pdfs=True)`
then `PackageImporter.prepare/apply`, without model/network calls. Sender has a
real durable CAS rescue proposal, all three unique images (two used, one unused),
full scientific figure/paper evidence, exact owned original A and applied primary
B. Its ordinary list membership is created through graph operations.

Export succeeds with one packed current PDF; import succeeds as `applied_locally`,
`remote_sync=not_requested`. The package has no retained-draft capability/table,
none of the three PNG byte objects, and no exact original A. The enrolled receiver
has zero raw drafts and no Review entries. Sender draft, saved deck, outbox and
external rescue file remain unchanged. This is omission from the transfer, not
sender deletion. See carrier-observed.json and final RED log.

The receiving fixture is explicitly enrolled device B, a separate native database
with no selected target/deck beforehand. It is NOT an unenrolled local-only
receiver and is not acceptance for that required workflow.

The first failure was fixture admission: verified primary B had no configured
DocumentReader roots, so export correctly packed zero PDFs. The corrected fixture
uses maintained register_document_paths BEFORE any source capture; all assertions
were retained. A later unreachable follow-on DTO assertion was corrected to the
actual direct Deck Review DTO; evidence/all image bytes now require the genuine
receiver-owned receipt. All statements reached by the real RED are unchanged.

## Exact boundary

- bundle.py:43 PER_PAPER, :51 _required_capabilities and :98 _paper_files collect
  paper rows/current legacy files, not raw drafts/full-byte receipts. Export at
  :203 therefore has nothing to declare for this retained proposal.
- bundle.py:540 _validated, :738 legacy import and package_import.py:185 inventory,
  :708 content, :797 deck preparation/:904 apply have no closed proposal carrier.
- raw_deck_receipts.py:69/_owner/capture require real research sync binding and
  raw_deck_closure requires registered owned artifact storage. These are strong
  existing enrolled guards, not a local-only importer.
- research_file_review.py:84 _client rejects unenrolled receivers. Legacy
  presentations.save_deck/_save_legacy_deck writes the ACTIVE deck, keeps only used
  image bytes, and can replace a current slot; it is not a raw-proposal adapter.
  slide_revision is a real single-slide job/receipt with original instruction,
  source/slot observation and publication checks; do not fabricate such a job.

## Other carriers: evidence and limits

Existing sync_recovery registry covers raw rows, closures and synthetic full-deck
receipt recovery. Existing test_raw_deck_receipts.py:170 verifies byte-complete
backup/detached recovery. That archived-byte evidence was read, not rerun here.
It does not prove review in a freshly editable receiver.

Pinned in-memory registry observation confirms all three raw protocols are in the
FULL backup registry, but absent from initial-enrollment trusted schema and
closed enrollment_history formats. Enrollment's unknown-table refusal is safe;
it must not be bypassed. An initial unpinned metadata probe was discarded and is
not evidence; corrected probe records actual isolated module paths.

RecoveryAdoptionService preserves generic archive provenance, while _Baseline
publish(:692) builds current deck slots from applied/legacy decks(:713-734).
ResearchReview.prepare_file(:707) refuses detached recovery. Source inspection
therefore identifies a missing recovered-proposal-to-local-owner adapter; no new
fresh-editable-recovery journey was executed in this lane, and this is not a
claim that the archived bytes are lost. Parent's mixed backup journey remains
separate evidence.

## Minimal proposed adapter (not implemented)

1. Define one closed, bounded CONTENT-ONLY proposal envelope using the verified
   pending-deck scientific snapshot plus every used/unused image, full sanitized
   figure/paper evidence, and all declared target-owned original PDFs. Keep A and
   primary B separately described/owned. Preserve null/unknown producer inputs;
   never reuse sender observations, native IDs, lifecycle tokens or writer ops.
   Do not serialize paths that select receiver roots.
2. List packages declare a new required capability only when such proposals are
   present, unioned with existing sorted capabilities. Exact declared/actual
   capability checks and closed schemas must make old readers reject before SQL
   mutation/file installation/cursor changes. If carrier is unsupported, refuse
   export before replacing a prior archive rather than silently omitting drafts.
3. Stage/verify bytes off-lock, then adopt into the explicit package paper mapping
   with fresh receiver-native/parent/slot observations and a fresh deck identity.
   In enrolled PackageImporter, write proposal/catalog/decision metadata in ITS
   existing transaction; never call independently committing rescue.run inside it.
   Preserve source originals through an observed source-owner adapter in that same
   commit. Stable package+proposal+target request IDs make exact retries idempotent;
   changed source/parent/target must refuse. No active-deck/outbox publication.
4. Provide an actual unenrolled local-only proposal owner/catalog and explicit
   review/apply branch before calling the carrier complete. Local owner means the
   real native DB, explicit local paper and local lifecycle, with actual binding
   None; do not mint sync enrollment, fake a portable paper UUID, or downgrade a
   malformed present binding. Reuse the legacy file lock/staging/rollback and
   original-slot checks for explicit Apply, not bare save_deck during import.
5. Reuse that same proposal adoption primitive for explicit initial enrollment
   and fresh editable recovery. Preserve sender records as archive-only provenance
   and remint only fresh receiver ownership from verified bytes and real target
   mappings. Keep detached preview read-only; never reactivate archived writer
   observations or refresh a stale epoch. Current full-byte receipt storage is
   enrolled-only, so local-only collector/catalog coverage is genuinely new work.

Acceptance: local-only AND enrolled receivers; all scientific metadata/three PNGs
and A/current B preserved; no auto-activation; explicit Review then Apply; exact
retry/no duplicates; unknown capability/metadata/source, mixed source owners,
parent/native changes, cancellation and transaction/file rollback. Full backup ->
detached -> fresh editable proposal review must be separately demonstrated.

No shared implementation, full suite, native UI, real provider/account/user data,
commit or root source edit occurred. This one intentional RED is not part of the
parent's passing187-case gate. Existing frozen NEW2 and final7 packets remain.


## Current integration update (2026-11-01)

The original omission RED above is now repaired in public package journeys.
The common codec and complete ZIP archive preserve sanitized full scientific JSON,
union deck/evidence images and exact declared originals. Local-only catalog,
package transaction grant, Review/Apply and actual native rescue import are now
integrated without enrolling the receiver or restoring sender writer authority.
Explicit replacement may update only same-epoch metadata through the caller grant;
its captured before-state remains separate from actual adopted owner metadata.

The original design text remains historical evidence, not a current missing-carrier
claim. A distinct genuine RED remains: enrolled raw-v1 import explicitly refuses a
fourth image present only in evidence.figures. Local export preserves it exactly;
receiver research/outbox stay unchanged. The raw-v1 deck-only inventory contract
must not be weakened or repaired by mutating scientific catalogs. A separate closed
general enrolled proposal adapter is required. Independent audit evidence is frozen
under ignored build/handoffs/proposal-evidence-only/audit in the archive exchange.

Complete backup/fresh-editable recovery, initial enrollment, live history/mobile,
active source/material navigation and matching full/installed checks remain open.


## Enrolled general adapter update (2026-11-01, later integration)

The previously recorded evidence-only union RED is repaired in actual public
import -> ResearchReview verification -> complete re-export. A separate closed
enrolled catalog preserves exact common codec science, all4PNGs and originalA;
raw-v1 checks remain unchanged. Actual receiver-native/binding/store/mapped parent
and exact target-owned originals are checked; caller-owned before-write grants
make research/outbox/proposal adoption atomic. Public cancellation/SQL rollback,
retry, missing-index readonly behavior and no-PDF refusal are covered.

The full-content Review helper/real bilingual Qt path publishes one observed
research_file and receipt atomically only after confirmation, with unchanged full
retained science and unknown producer input_versions. Used-only active wire assets
are not the full retained material catalog. Sources/captions and A/B version mismatch
are visible without editable JSON or sender job/observation replay.

Independent actual FULL backup now refuses BOTH local and enrolled catalog tables
at its strict unknown-schema boundary.2RED, source unchanged/no archive; restore,
fresh editable adoption and verify are not reached. The next carrier must be closed
content manifests/objects plus archive-only original provenance. Collectors must
compare snapshot rows to the actual original-native owner, not the snapshot inode.

Enrollment publishes final paths before creating transfer_binding. Do not grant
anticipated-final authority in a temporary stage or replay stage-native catalog
rows across relocation. Prefer an archive-only carrier through publication and
explicit final-path Review verification/adoption against real receiver mappings
and already owned originals, with stable replay/link to avoid visible duplicates.
No shared registry/adoption integration is yet claimed for that carrier.
