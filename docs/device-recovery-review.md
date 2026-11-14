# Review old-device work before authority recovery

Status: local v0.5 read-only implementation, not automatic post-disaster merging.
Use this when recovering an authority from an older backup while a device may
contain more recent work. Keep the old device workspace intact.

## Desktop

Open **Workspace and recovery > Advanced > Compare service backup (advanced)**.
Expand it, then choose the authority backup folder containing `manifest.json`.
This is an operator/service backup, not an ordinary research/list ZIP.
Unenrolled local databases have this action disabled. Reading remains available.

![Synthetic device recovery review](images/device-recovery-review.png)

The operation runs in the existing background worker. Repeated activation does
not create another job. Cancel and close drain admitted work; switching or
rebinding the workspace suppresses stale delivery. The source database and backup
are read-only. The result describes the checked point in time; repeat after edits.
Unsaved editor drafts, uncaptured research and attachment ownership are outside
this journal comparison. It is not a complete research or file audit.

## Interpret the result

| Field | Meaning and next action |
|---|---|
| Service backup sequence | Last event retained for the selected workspace in the verified authority backup |
| Device received sequence | Last contiguous retained received event on this device |
| Local operations already in backup | Exact operation fingerprints present in the backup, including a successful send whose acknowledgment was lost |
| Unconfirmed and absent from backup | Local operations without a saved acknowledgment that were not found in this backup; preserve and review them, do not assume never sent |
| Acknowledged but absent from backup | This device retained a server acknowledgment newer than the backup; preserve the local work |
| Received events after backup | Accepted/conflicted events this device received beyond the backup; preserve the old received history |

Categories overlap: one acknowledged operation can also be a received event. Do
not sum them into a unique change count. `device_behind_by` describes a received
prefix lag, not missing research or lost data. Zero uncovered journal work does
not certify complete backup coverage of the device's files, drafts or research.

Before any migration, save drafts and use **Create complete backup** while all
research producers are quiescent. Preserve the complete old workspace and verified
backup. Join the [fresh recovered authority](sync-authority-restore.md) into a
separate new local directory with newly issued device credentials. Review supported
research-package imports there; this comparison does not prepare/apply them.
Do not rewrite an old identity/cursor, discard an outbox or blindly replay an old
operation into the new authority. Guided per-change reconciliation remains pending.

## Operator CLI and API

```sh
.venv-sync/bin/python -m paper_daily sync-admin review-device-backup --database /private/old-device/papers.db --input /private/verified-authority-backup --workspace example-workspace --seconds 30
```

On Windows use `.\.venv-sync\Scripts\python.exe`. All paths/identities are explicit;
this uses no GCP SDK, credentials, network, login, AI or global research database.
It does not initialize missing databases. Success is one JSON receipt with
`state=reviewed`, identities, sequences, counts, `uncovered_journal_domains`,
`requires_preservation`, `replayed=false`, `research_and_files_fully_audited=false`.
The receipt contains no note bodies, titles, source paths or credentials.

| Flag | Requirement/default |
|---|---|
| `--database FILE` | Required existing old-device SQLite database with sync identity/cursor/journal |
| `--input DIRECTORY` | Required complete authority backup; all referenced bytes must verify |
| `--workspace ID` | Required backed-up workspace matching this device's stored binding |
| `--seconds NUMBER` | Default 30; positive and at most 300, cooperative budget |
| `--help` | Offline parser help; no account or state action |

```python
sync_device_recovery.review(database, snapshot, workspace, *,
                            seconds=30, cancelled=lambda: False) -> dict
```

The service checks exact shared received history, closed canonical operations,
local fingerprints and backed-up acknowledgments. It rejects missing/gapped or
changed inputs, contradictory receipts and oversized records rather than giving
truncated reassuring counts. The local record bound is 100,000; the time budget
also covers manifest/attachment verification. Existing read-only SQLite helpers
and file/WAL version guards are used; OS calls are not hard real-time cancellation.
It is not a sandbox against malicious same-user filesystem replacement. The result
is an observation, not a capability to replay, rebind, restore or upload anything.

[Scenario map](testing/device-recovery-review-scenarios.md) records exact local
checks and the unresolved full, hosted and installed-device gates.


## Per-change recovery core

The internal APIs below are integrated into the checkpoint source, with isolated
native-fixture coverage. They are not yet exposed as guided desktop decisions.
Old workspace/history remains intact; old envelopes are not blindly replayed.

| Entry | Contract |
|---|---|
| `sync_recovery_candidates.prepare(database, snapshot, workspace, *, seconds=30, cancelled=...)` | Read-only index; `.page(...)` and `.detail(change_id, ...)` retain exact source identity |
| `sync_recovery_target.observe(index, target_database, *, seconds=30, cancelled=...)` | Prove fresh target history/binding; `.compare(change_id, ...)` exposes source/current state without writing |
| `sync_recovery_note_copy.prepare(observation, change_id, request_id, *, seconds=30, cancelled=...)` | Explicit unanchored note copy with a new native identity; `.apply(...)` commits atomically |
| `sync_recovery_choices.prepare(observation, change_id, choice, request_id, *, seconds=30, cancelled=...)` | Explicit keep/add/replace/restore for supported metadata, unanchored notes and order; `.apply(...)` is idempotent |

Saved decisions are checked against the exact source operation/fingerprint,
source and target identities, choice, native operation and sequence. Retrying a
corrupt receipt fails without writes, including keep-current (which emits no
research operation). Native research, outbox and decision receipt commit together;
interruption rolls them back. Cancel/stale bindings never authorize another target.

Original-bound/scientific content, arbitrary deletion, new parent-lifetime
mapping, complete editable recovery UX, cloud recovery and installed-device
acceptance remain open. A successful subset does not mark recovery complete.
