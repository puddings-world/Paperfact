# Material source UI integration contract

Updated 2026-11-01. The pure read/collection foundations are locally verified;
the UI sequence below is implemented with selected local integration evidence.
Root owns this unreleased integration; see [actions/results/limits](testing/material-ui-scenarios.md).

## Current implementation boundary

- `material_sources.py`: sealed Collection/Selection/OriginalProof; exact worker
  projection and small GUI selection/status. Managed original_source and genuine
  local catalog/source receipts remain independent of any deck/claim.
- `materials.collect`: optional explicit database/MaterialPaths, verified loaded
  bytes via existing figures.capture_loaded; retains actual A when B is desired.
  Compatibility defaults stay unchanged. Derived cache writes are source-scoped.
- `manual_highlight_ops`: existing-parent readonly observation and opt-in readonly
  mark loading; original editing defaults remain. It does not bootstrap a missing
  lifetime or incomplete desktop capture binding as a side effect of a read.
- `desktop/original_controller.py`: source-neutral owned worker/view lifecycle.
  ActiveOriginalController keeps only saved-deck admission/preparation;10 moved
  lifecycle methods have identical ASTs. The common base grants no source access.
- `original_version.py` has a distinct material_proof branch beside active/local/claim/retained proofs. Material and deck authority never substitute for each other.

Exact current evidence: [material core scenarios](testing/material-core-scenarios.md).
The original native missing-UI audit is retained; its adapted real-click regression now passes in the selected candidate;
its[gap map](material-source-navigation-audit.md) distinguishes absent fresh
history enumeration from a still-selectable old A item lacking a read route.

## 1. Owned asynchronous collection

Create a focused desktop MaterialPreparation bound at ReaderPage construction to
its WindowWorkspace/native database, with one running worker and at most the
latest pending request. Bind PresentationPane._load_materials to that controller
in the real app; keep compatibility shells explicit.

Before queuing, capture the actual Paper object/id, genuine earlier
ReaderPage._highlight_owner, PDF position identity/native source version,
fingerprint, active document object, private panel epoch and MaterialPaths.
Never observe a new parent epoch on the worker as a substitute for the original
loaded-owner observation. Invalid/incomplete reader ownership asks to reopen;
no hidden migration, schema creation, identity grant or paid work.

Worker: check the earlier owner; readonly-load its real source/marks; use the
existing figures.capture_loaded proof; call materials.collect with explicit
database, paths, loaded_source and cancellation; then capture_collection on the
actual document used. Recheck the SAME earlier owner/source after capture.

Legacy ReaderPage normally has active_document=None. Resolve a typed legacy
document only against the captured explicit database/path parent; require its
path/hash to equal the actual loaded PDF. Do not activate it or recapture latest
B. If a format cannot provide a typed historical context, keep scientific items
and current-reader navigation without a historical capability; no loose-alias
ownership fallback.

Attach `_source_collection` and worker-projected items only as NON-dataclass
private Materials attrs; to_dict/asdict/MIME remain scientific. Missing retained
original has Collection.historical_available=False and preserves the list.

Before GUI install, verify weak/current reader, exact earlier owner/object,
paper, actual PDF native/version/fingerprint, panel epoch and workspace native
binding. Use a worker-issued source lease/fence (existing figures lease helpers)
for semantic parent/source recheck after DB interference; at most one bounded
recheck of the same lease, not a recapture/recollect loop. No SQL/hash/PDF/full
JSON in GUI delivery. Keep previous visible items on failure/cancel.

## 2. Panel provenance and refresh

Retain the private Collection on MaterialsPanel and advance a collection epoch
on clear/load. Use worker MaterialItem.payload as plain UserRole and item.key in
a separate role. collection.item(group,index,variant) supports main rows and
table children. Manually supplied compatibility Materials may remain plain.

Keep source_requested(dict) as the legacy/current-reader notification and expose
a separate typed selection signal from the ACTUAL selected tree row/collection.
Use material_sources.select(collection,key,payload); reject modified items. MIME,
clipboard, JSON and manually emitted bare dictionaries never carry permission.
Matching-current navigation keeps the final anchor guard; explicit unavailable
navigation must not be misreported as a successful locate.

Add a compact refresh action and source-version status. Repeated refreshes
coalesce and display owned work; errors permit explicit retry. On PDF B arrival,
cancel in-flight A collection but retain a published A list and show its source
version. Refresh explicitly produces B. Paper changes clear the old collection.

## 3. Distinct material original view

Create MaterialOriginalController using the common OriginalController lifecycle,
not ActiveOriginalController's deck admission. Its context binds the real Panel
Collection/epoch, selected item key and exact payload, paper/window native
lifetime, current reader B/native version/fingerprint, and cancellation.

Worker prepare uses the sealed Selection; no fake deck, claim or retained preview.
Add OriginalSnapshot.material_proof and material-specific native status/worker
revalidate adapters. The existing shared read-only viewer may dispatch ready /
recheck / revoked for this proof just as for active_proof, but keep authority
types distinct. Recheck preserves the same collection/selection. Pages/declared
geometry are not certified exact quotations or scientific support.

Duplicate clicks share one preparation/view. Different latest selection can
queue once behind draining work; closing or changing source/context clears that
queue. A closing viewer is not reusable. Already-published A can remain valid
after its old primary alias becomes B, because retained-original ownership is
independent; GUI result must still belong to the currently selected material.

## 4. App lifetime and acceptance

Register both collection and material-original jobs at MainWindow's actual
close/restart/update/installer admission barriers, and ReaderPage close/source /
paper hooks. Workers remain owned until terminal delivery/discard/render drain;
forced widget destruction cancels with a process-held worker reference.

Admit the exact frozen native audit with its original assertions intact. Because
the new read request needs actual desktop loaded-owner setup, use the real
desktop CaptureConnection/install and ReaderPage.load initialization in that NEW
fixture, before its unchanged data assertions. Record the fixture admission;
do not invent an owner or loosen source/B/SQL/byte invariants. Add bounded waits
for actual asynchronous collection and original-view delivery/teardown.

Turn that real collect-A -> UseLatest-B -> tree-click journey green. Add actual
Qt cases for duplicate refresh/open, failure/retry, missing/retired/foreign
original, different selected item/paper/PDF/workspace during work, queued GUI
delivery, unrelated note interference, renderer drain, and parent launch before
actual close. Existing plain material insert/drag/preview/current-source tests
stay intact. Use genuine initialized fixtures, simulated providers, no real
account/network or owner research. Explain each new user action and limits.

This local read integration does not satisfy complete sync writer/history,
detached recovery, deployed identity/service, phone or installed Mac acceptance.
Full scripts/check.py is still mandatory before completion/commit/release.
