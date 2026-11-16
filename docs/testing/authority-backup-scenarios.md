# Authority backup behavior map

Scope: `tests/test_sync_authority_backup.py`, isolated synthetic authority/PDF
fixtures. No real account, research workspace, paid model, network upload or GCP.

| User/operator outcome | Observable acceptance |
|---|---|
| Export and inspect | Exact event history, conflict body and committed original bytes survive; source SQL is unchanged; incomplete bytes absent; output cannot serve as a live authority. |
| WAL | A retained read snapshot keeps actual committed WAL frames open; exported SQL includes the later edit without requiring checkpoint. |
| Storage failure (3 cases) | Missing/damaged committed object or missing namespace produces no completed manifest and preserves source SQL. |
| Cancel/retry | Cancellation during copy leaves no completion, releases writer lock, permits enrollment and export to a fresh pathname. |
| Manifest publication failure | A failed pending manifest is not completion; retry cannot overwrite its directory; a fresh output succeeds. |
| Concurrent write | Actual SQLite writer reservation rejects a competing immediate transaction, then queued enrollment succeeds; snapshot excludes the later device. |
| Repeated output | Concurrent activations produce exactly one completed snapshot and one refused reservation. |
| Invalid backup (5 cases) | Altered bytes, omitted coverage, path traversal, extra file and duplicate manifest entry are rejected. |
| Read-only/late change | Successful inspection changes no backup file bytes; a later changed object is refused. |
| Invalid budget (6 cases) | Zero, negative, too large, NaN, infinity and boolean budgets create no output. |
| CLI | Shared commands return bounded JSON/help, no token, no traceback on missing backup. |
| Actual console entry | Subprocess module invocation exports and verifies without creating its configured unused research directory or printing a token. |
| Scope | Authority/descendant/ancestor destinations are refused. |
| Retained event closure (2 cases) | Removing attachment ownership is rejected during export and during inspection even after recomputing the database checksum. |
| Deadline | Deterministic mid-copy expiry publishes no manifest and releases the actual writer reservation. |
| Invalid manifest encoding (3 cases) | Invalid UTF-8, excessive JSON nesting and duplicate fields return bounded CLI failure. |
| Empty/missing authority | Empty authority remains empty; missing source is never initialized. |

Thirty-one new cases are selected by this file. Adjacent existing admin, mount,
reference authority and authenticated blob-service tests are run unchanged in the
integration scope. Exact receipts are in the dated continuation ledger; do not
sum overlapping scopes or treat them as a full application gate.

Live-only gates: Linux/POSIX directory fsync and service supervision, Windows
power-loss behavior, large-store capacity/lock timing, HTTPS proxy traffic,
private GCS publication/retention, coherent isolated restore/new identity and
physical Windows/Apple Silicon/phone convergence. A locally verified backup is
not a tested restore or release.

### Official service restart/lifetime boundary

`tests/test_sync_admin.py` adds a revoked-token snapshot replacement regression
that fails before the source fix. It also covers normal re-open, v1 backup/fresh
restore with new credentials, replacement/removal between marker admission and
constructor, and malformed/extra/duplicate/noninteger marker refusal before writes.
The selected service/admin/mount/HTTP and backup/restore/native suite189 passes
59.19s pytest/62.7s stages under the two-core/25% governor. These overlap earlier
focused runs; they are not new feature counts or installed/cross-host evidence.

### Retained local control checkpoint (v3 source)

`tests/test_authority_control.py` covers pairing/rename/concurrent enrollment and
restart, refusal and rollback of unsupported schema mutation, pairing tampering,
failed checkpoint publication with explicit retry, and an actual subprocess exit
between marker publication and SQLite commit. That last case rolls SQL back,
refuses subsequent access/export, and gives sanitized CLI recovery guidance.
`tests/test_sync_admin.py` adds same-file revoked-device resurrection refusal.
Legacy recovery fixtures now construct explicit old-format files directly;
research preservation and old-grant rejection assertions remain unchanged.

Affected admin/control/mount/backup/restore/native/HTTP/service and source CLI
selection: **195 passed, 66.46s pytest, 70.1s total** with bounded CPU. These are
source fixtures, not new installer, physical power-loss or hosted acceptance.
