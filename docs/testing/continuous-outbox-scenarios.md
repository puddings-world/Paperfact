# Automatic sync wakeup scenarios

Development integration, 2026-11-13. Tests use actual native journals, captured
note writes, a reference authority and public join/session flows. Clock advances
are simulated; account login, paid AI and real research uploads are excluded.

| Scenario | What the user can observe |
|---|---|
| Local note commit | With automatic sync explicitly enabled, a saved note schedules a short delayed pass and reaches the authority once. Repeated polls do not create duplicate writes. |
| Initial/own receipts | The first successful pass remains idle; observing its local projection updates does not schedule another pass. |
| Real peer receive | A separately joined device edits a note. The origin receives the same text on its normal poll and stays idle afterward. |
| Commit and rollback | A journal operation inside a held transaction produces no wakeup before commit or after rollback. Committing once wakes once; identical retry remains quiet. |
| Consent off | Even after verified connection, local writes do not enable sync or send research until the user opts in. |
| Offline retry | A newly saved note cannot defeat retry backoff. Restoring the transport sends retained content without duplicates. |
| Unavailable reader | A simulated expired reader observation cannot block an independent valid local journal change. |
| Manual sync race | If manual sync delivers a new operation before the observer runs, no additional automatic pass is scheduled. |
| Accepted before receive | A genuinely accepted operation acknowledged locally but not yet received still schedules receipt recovery; afterward repeated observation stays quiet. |

## Evidence and interpretation

The first loose note and peer tests passed, but lacked an initial-idle assertion.
Strengthening that precondition exposed the real defect: observing the initial
sync's projection changed state from idle to waiting. It failed before the
scheduling-source fix. The first local-only marker then exposed a separate manual
sync race; adding the outstanding-upload/receipt check fixed that failed case.
No existing tests were loosened or removed.

The eight final test cases passed directly in **18.17 s**. Some rows above share
a compound journey; case counts are not separate feature completion percentages.
The maintained adjacent gate is recorded in the continuation ledger. These are
local fixture checks; a full release and installed-device/hosted journey remain
required.


Maintained affected gate: **116 passed in 130.97 s**, 134.6 s overall,
privacy/Ruff passing, zero failures/errors/skips. Includes all eight new cases,
existing continuous sync/offline restart/attachment status, workspace revision
lifetime, saved-text signatures/notices and main-window scope. No source changes
followed this gate. Counts overlap prior checks and are not a release total.
