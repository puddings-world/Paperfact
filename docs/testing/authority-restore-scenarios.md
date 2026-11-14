# Authority recovery behavior map

All fixtures are synthetic private authority/client databases. No cloud, owner
research, real account, paid model or installed application is used.

| Requirement | Behavior pinned |
|---|---|
| Exact recovery | Three note events, accepted head and retained conflict plus exact original bytes survive; input backup and old authority unchanged; temporary sessions cleared; explicit new issuance works; next edit continues only the new authority. |
| Rolled-back input | Old token is refused, ahead cursor is refused, an old-workspace operation cannot enter the fresh workspace. |
| Invalid selection (3 cases) | Old ID reuse, missing workspace and malformed ID create no output. |
| Workspace privacy | One selected workspace is recovered; another workspace's private bytes/events cannot be read or copied; another backed-up ID cannot be reused. |
| Native document lifecycle | Typed paper/document graph and new file integrity records are reconstructed; exact original remains readable. |
| Cancel/retry | Mid-event cancellation leaves no service marker, preserves input, refuses overwrite and permits fresh-path retry. |
| Semantic disagreement | A simulated changed conflict outcome prevents completed publication. |
| Unsupported/corrupt schema | Hash mismatch and a recomputed-checksum backup with an extra domain table both fail before target creation. |
| Publication failure | Final marker error leaves no live authority, no active reconstruction credentials and no pinned file handles. |
| Repeated activation | Concurrent requests for one output yield one restored result and one refusal. |
| Late change | Changing manifest during replay prevents completion. |
| Existing paths | Existing output and overlapping source/destination paths are never overwritten. |
| CLI | Explicit required mapping/help and bounded token-free success/failure output. |
| Actual desktop admission | Fresh credentials cannot rebind an old local journal or discard its pending outbox; no push/pull/upload occurs. |
| Empty/deadline | An empty known workspace retains no old device access; expiry before copying creates no output. |
| Verification handoff race | A database changed immediately after successful inspection cannot be re-trusted during restore; no output is created. |
| Ordering (2 cases) | Both list and workspace ordering re-key their workspace-scoped proof while retaining stale-set and opaque-proof conflicts. |
| Editable slide journey | Actual publish/export/restore/issue/bootstrap/download keeps speaker notes, citations, editable layout and exact figure bytes. |
| Native Lineage journey | Actual two-version imported scientific report replays; a newly joined workspace retains both history entries and all three exact source PDFs, accessible through the native source-proof interface. |

The core recovery file selects20 cases; the native journey file selects2. Adjacent
backup/admin/authority/blob/ordering/session tests run unchanged. Exact commands,
failures and terminal receipts are recorded in the continuation ledger. Counts
are selected test cases, not elapsed-time or release-completion percentages.

The first native fixture incorrectly expected full offline availability despite
not declaring primary PDFs for every source; source inspection showed the existing API explicitly
reports this as partial. The corrected new fixture pins one missing primary for the deck fixture and two
for the Lineage fixture, and asserts
zero remaining/failed artifact targets and each exact intended artifact. No old
assertion was weakened. A separate real native replay failure identified the
workspace-bound ordering digest; implementation now transforms only verifiable
scoped proofs and checks every original outcome instead of changing expectations.

Not covered: installed Apple Silicon/Windows/phone, hosted TLS/proxy, GCS backup
publication/retention, actual VM/disk loss and restore, large/custom-store capacity,
power-loss durability, automatic migration of newer unsent old-client work,
complete semantic research audit and the coherent whole-application gate.


Final affected scope: **194 passed in 87.11 s**,
`build/authority-restore-final-20261114.log` (20 recovery,2 native,31 backup,141
unchanged adjacent cases). Docs/distribution/check-script: **52 passed in1.46s**,
`build/authority-restore-docs-20261114.log`. Current committable privacy, whole-tree
Ruff and selected whitespace checks passed. These scopes overlap earlier runs;
never sum them. Whole-application full-check status remains failed/unresolved.
