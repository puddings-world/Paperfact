# Existing-beta history repair scenarios

Status: locally integrated and fixture-verified, 2026-11-14; no release/full/device
acceptance is implied. Existing activation/refusal test expectations and the
previous failed full report remain unchanged.

The fixture first publishes two real scientific versions, synchronizes their
actual accepted events to a peer, then removes only the older native catalog row
to model the previous beta. Its real accepted inbox, graph receipts, current
report, cursor and source bytes remain unmodified before repair.

## Twenty new behavior cases

| Scope | Observable outcome |
|---|---|
| Bounded restart/resume | Two-event batches advance only their actual prefix; a new service resumes and restores both versions without current research/outbox/byte grants |
| Cancel inside batch | History insertion and checkpoint roll back together |
| Cancel between batches | Earlier progress remains; new ticket can continue |
| Workspace switch | Old database rolls back, new database is never created/written |
| Byte cap | Next event is not skipped and later resumes from the exact prefix |
| Corrupt gap/receipt/history (three) | Refused without overwriting saved data or claiming completion |
| Backup and detached restore | Scientific history travels; device scan checkpoint does not |
| Cold native database | Empty history creates no scan/report schema |
| Read-only inspection | Construction/status never open a write-capable journal connection |
| Actual History button | Two saved versions become visible; repeated clicks do not duplicate work; current index disables the button |
| GUI cancel/retry | Research stays intact; a fresh job can resume |
| Held close | Window waits for worker drain; canceled batch does not publish |
| Queued view change | Completed index remains local but cannot replace the other view's visible selection |
| Actual normal sync | Connected fixture session repairs the older catalog, without an AI call |
| Bounded automatic passes | Controller remains waiting while the real local index is incomplete, then returns idle; returned progress snapshots cannot mutate internal state |
| English/Chinese progress (two) | Actual saved-event counts, no invented percent or ETA |
| Invalid count | Cannot render made-up completion |

These live in `test_lineage_history_repair.py` (11 cases),
`test_lineage_history_repair_ui.py` (4), and
`test_lineage_history_repair_sync.py` (5). UI model settings are synthetic; a
provider call fails the fixture. The service itself has no provider/transport.

## Exact partial evidence

- Initial core scope: **5 passed in 57.43 s**,
  `lineage-history-repair-first-20261114.log`.
- Core provenance/backup/cold guards: **10 passed in 116.19 s**,
  `lineage-history-repair-guards-20261114.log`.
- Actual new history UI plus existing historical/native reader scope:
  **15 passed in 107.16 s**, `lineage-history-repair-desktop-20261114.log`.
- Existing session/controller regression: **32 passed in 52.25 s**,
  `lineage-history-repair-sync-regression-20261114.log`.
- Actual automatic repair, count formatting and existing connection/controller:
  **45 passed in 75.30 s**, `lineage-history-repair-automatic-20261114.log`.
- Final current-source new core/UI/automatic scope, including genuinely read-only
  inspection and disabled complete action: **20 passed in 182.59 s**,
  `lineage-history-repair-final-20261114.log`.

Scopes overlap and must not be summed. Setup uses real bounded ZIP/PDF/source
validation; no real login, paid call, owner research database or cloud resource.
The actual synthetic screenshot was visually inspected. No installed Mac, phone,
real beta database migration or hosted transport was exercised.

Development-script failures were guarded before tests: one exact-text patch
matched two history insertion sites and was narrowed to the private received-
history function; one desktop patch missed a context and left that file unchanged;
new local line wrapping and explicit fixture aliases corrected Ruff issues. No
old assertion was weakened, skipped or changed, and no failing runtime approach
was hidden by changing the expected behavior.

## Remaining scope

This proves the concrete local upgrade path, not full v0.5.0. Unowned result
adoption, complete audit/recovery, full verification, installer artifacts and
physical/hosted acceptance still require their own evidence. Actual derived-index
corruption is refused; repair does not certify arbitrary database health or
reconstruct missing raw events from guesses.
