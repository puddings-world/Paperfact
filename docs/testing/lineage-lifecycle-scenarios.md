# Lineage lifecycle behavior scenarios

Scope: explicit backend removal/restoration and portable history evidence in the
v0.5 development worktree. These tests use isolated research databases, generated
PDFs and simulated model responses. Lifecycle actions are forbidden from invoking
AI. Passing this scope does not certify desktop lifecycle controls or hosted sync.

| Cases | User-observable scenario | What must remain true |
|---|---|---|
| 1 | Remove, retry, restore, retry an unbound generated report | Exactly one receipt per request, exact content restored, originals unchanged; a later target change invalidates an old retry. |
| 2 | Two workers submit the same removal request | One action applies, one returns the original result; no duplicate history. |
| 3 | Writing the action receipt fails after removing content | Original content remains; earlier caller work commits independently. |
| 4-5 | Cancel before or after the local write | No content or action receipt changes. |
| 6 | Content changed after observation, or a request ID is reused | Refuse without overwriting the newer target or changing the previous intent. |
| 7-8 | An original grant disappears or a selected paper is deleted and recreated | Restore refuses; removed history remains inspectable. |
| 9 | A selected paper is renamed | Restore preserves its continuous identity and the new title. |
| 10-11 | Back up a removed or restored local report | The archive includes history and original PDF bytes; detached restoration keeps archive data without live action/device authority. |
| 12 | Removed history has lost its actual publication receipt | Backup refuses with no partial output instead of silently losing provenance. |
| 13 | Native removal/restoration synchronizes to another workspace | Real typed events converge; restore has a new scientific incarnation, original source pins and no new source grants/model call. Backup retains both actions. |
| 14-15 | A native source is retired, optionally recreated with identical bytes | Old analysis cannot attach to the replacement source lifetime; refusal adds no outbox action. |
| 16 | Remove/restore a report imported from another researcher | Exact receiver import provenance and source grants remain unchanged. |
| 17-18 | An imported source grant disappears or selected paper is recreated | Restore refuses and keeps historical content without granting another source. |

Sources:

- `tests/test_lineage_lifecycle.py`: cases 1-12.
- `tests/test_lineage_lifecycle_native.py`: cases 13-15, using the actual journal,
  authority service, attachment transfer and a second local workspace.
- `tests/test_lineage_lifecycle_import.py`: cases 16-18, using a real imported
  research package and receiver-owned original associations.

A separate nineteenth case in `tests/test_lineage_lifecycle_sharing.py` exports a
real list after removing its report. The package must exclude removed analysis,
private action/candidate tables and peer-only original files; local history stays
available. Its result is recorded separately in the continuation ledger.

The focused archive/enrollment regression also includes existing generated,
imported and native recovery scenarios. Counts in that gate include those cases;
they are not additional product features or installed-device acceptance.

The backend-only checkpoint above was followed by the Qt, full live-version
catalog and native rollback coverage described below. Remaining end-state gates:
complete detached editable adoption and final coherent full check. Historical
original-PDF inspection now has [independent scenarios](lineage-historical-original-scenarios.md). Installed Apple Silicon and hosted Linux/PWA acceptance are
separate external gates. Exact commands and outcomes are retained
in the [continuation ledger](continuation-20261112.md).

Verification receipt: the 18 backend cases plus selected existing archive and
enrollment regressions passed as a 97-case gate in 339.24 s. The nineteenth
sharing-only case passed separately in 3.20 s. Privacy/Ruff passed; these are
focused local checks, not the whole application. See the dated ledger for exact
commands, intermediate failures and remaining release gates.


## Desktop and full-version continuation

Additional new behavior is covered by these maintained modules:

| Module | Concrete outcomes |
|---|---|
| `test_lineage_versions.py` | Real generated versions remain readable across removal/restoration; distinct generation history, paging and target occupancy are preserved; lost provenance never becomes restore permission; invalid pages do not read/write. |
| `test_lineage_versions_shared.py` | Replaced imports keep distinct receiver receipts; a peer receiving an edited native report can browse and explicitly restore its older version without calling AI. |
| `test_lineage_lifecycle_native.py` (three added cases) | Late receipt failure, pre-write cancel and late cancel roll back science/history/outbox together while earlier caller notes and their independent outbox event survive. |
| `test_lineage_lifecycle_desktop.py` | Real confirm/cancel/remove/history/restore; duplicate activation; pending cancel/view/close; changed target during confirmation; failed restore and explicit repair/retry; saved-write/failed-refresh reporting; empty selection and page boundaries. |

These extend the previous 19 backend/sharing scenarios, not replace their evidence.
Exact new counts and terminal selected-gate receipts belong in the continuation
ledger. Historical original-PDF inspection is now independently implemented;
full editable detached adoption remains open. Current-row source readers were
not weakened to enable historical reads.


Latest UI receipt: after the stale-view guard, all 32 selected Qt/origin cases
passed in 128.51 s (131.9 s overall), privacy/Ruff passing. This includes the
stronger historical-source explanation/screenshot layout check and both new
context/selection changes while confirmation is open. The earlier 48-case gate
also covers the unchanged catalog/native backend. Counts overlap; a complete
release pass is still required. Screenshot uses generated fixtures and simulated
AI only, with the actual app font/style loaded.
