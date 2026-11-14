# Review old-device work before authority recovery

Status: local v0.5 comparison and explicit typed recovery choices; not automatic
post-disaster merging or complete recovery.
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
operation into the new authority. Guided comparison and supported keep/add/replace/restore or note-copy choices
are available below. Exact-original and compound reconciliation remain pending.

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
native-fixture coverage. Guided desktop comparison, note copy and supported
metadata/note keep/add/replace/restore use these APIs.
Old workspace/history remains intact; old envelopes are not blindly replayed.

| Entry | Contract |
|---|---|
| `sync_recovery_candidates.prepare(database, snapshot, workspace, *, seconds=30, cancelled=...)` | Read-only index; `.page(...)` and `.details(change_id, ...)` retain exact source identity |
| `sync_recovery_target.observe(index, target_database, *, seconds=30, cancelled=...)` | Prove fresh target history/binding; `.compare(change_id, ...)` exposes source/current state without writing |
| `sync_recovery_note_copy.prepare(observation, change_id, request_id, *, seconds=30, cancelled=...)` | Explicit unanchored note copy with a new native identity; `.apply(...)` commits atomically |
| `sync_recovery_choices.prepare(observation, change_id, choice, request_id, *, seconds=30, cancelled=...)` | Explicit keep/add/replace/restore for supported metadata, unanchored notes and order; `.apply(...)` is idempotent |

Saved decisions are checked against the exact source operation/fingerprint,
source and target identities, choice, native operation and sequence. Retrying a
corrupt receipt fails without writes, including keep-current (which emits no
research operation). Native research, outbox and decision receipt commit together;
interruption rolls them back. Cancel/stale bindings never authorize another target.

Original-bound/scientific content, arbitrary deletion, unproved parent changes, complete editable recovery UX, cloud recovery and installed-device
acceptance remain open. A successful subset does not mark recovery complete.


## Review and copy a recorded note

1. In **Workspace and recovery**, open **Recovery**, expand the existing service
   backup comparison, and choose the verified backup containing `manifest.json`.
2. Select **Review changes in a restored workspace** and choose the separate,
   already joined target folder containing `papers.db`. The app stays in the old
   reading workspace; this action does not initialize or switch a workspace.
3. Browse 20 recorded changes per page. Select a row and press Enter or choose
   **Compare selected change**. Resize the list and both read-only content panes
   with the splitters. The current pane includes the target's pending edits.
4. For an eligible unanchored v2 note, **Copy as new note** adds one distinct note
   to the target's native outbox. Existing notes and the old workspace stay intact.
   No AI call is made. An already-enabled target sync controller may send it.
5. Refresh after saving. Reopening the same review recognizes the recorded copy;
   repeated clicks, retry and reopening cannot create another copy. Later edits
   or deletion of the copy are retained.

![Synthetic old-device and restored-workspace comparison](images/recovery-changes.png)

Cancellation/close drains active work. Changing the workspace, source binding or
queued target observation blocks stale application. A save that already committed
is reported as saved even if cancellation or a target change occurs afterwards.
PDF-bound notes, unsupported scientific/file content and deletion remain visible
but pending; there is no generic flatten/replay action. Exact-original verification, unproved parent changes, compound recovery and
complete recovery/device acceptance remain outstanding.


## Choose how to recover supported content

After comparing a row, the **Action** selector lists only currently admissible
choices plus previously recorded choices. Lists and other metadata default to
**Compare only**. Unanchored notes retain **Copy as new note** as the default;
choosing a replacement instead preserves the original note identity.

| Choice | What it does |
|---|---|
| Keep current content | Records a local decision; writes no research operation or outbox item |
| Add old content | Creates a supported entity only when its target is absent |
| Use old version | Writes a new native version over the reviewed current entity; earlier history remains |
| Restore old content | Explicitly restores a known deleted entity, without silently restoring its children |
| Copy as new note | Creates a distinct unanchored note, preserving the original note |

Use/restore shows a confirmation dialog defaulting to **No**. Repeated activation
while confirming starts no job. Changing selection during the dialog cancels the
old choice; a later target edit is rechecked in the native transaction and cannot
be overwritten by the stale decision. Failure/retry reuses the prepared request.

Refreshing retains a completed add/replace/restore/keep decision even when its
success changed what is currently admissible. Selecting that already-recorded
action cannot apply it again or overwrite subsequent edits. Another explicit,
currently eligible choice requires a new review-bound decision.

The controls cover supported lists, paper metadata, membership, reading state,
order and unanchored notes, subject to exact parent-lifetime checks. Keep is a
local preservation decision, not proof of original ownership or complete recovery.
PDF-positioned notes and unsupported scientific/file operations cannot obtain a
generic write capability; unproved parent changes and original verification remain blocked.


## Recover related lists without losing their links

Recover the supported parent first, then review its children. For example:
**list > membership > reading state > paper order**, followed by list order.
Each step remains an explicit native action; it does not replay the old envelope.

A changed parent lifetime requires a recorded recovery decision, the exact old
operation/fingerprint, its actual native journal receipt, and the current target
lifetime. Unchanged parents are checked against the selected verified backup.
A same-named entity, matching ID or deliberate reuse of an old incarnation is not
an unrecorded recovery grant. Missing, corrupt or superseded proofs block writes.

Historical parent proofs are checked separately from current write eligibility.
After explicit list deletion/restore, a retained child needs explicit restore
under the verified new parent. Restoring the list alone never revives children.
Membership/order lifetimes and complete-set digests are rebuilt by the existing
native builders; the chosen order is preserved without dropping extra members.
A target edit after preparation invalidates the decision; refreshing can preserve
the newer parent name while recovering its children.

Local reference-service and second-native-client fixtures verify accepted list,
membership, reading time and order delivery. This is not installed-device/hosted
acceptance. Arbitrary parent migration, PDF/scientific ownership and compound
file recovery remain open. Copy-as-new also accepts a supported recorded paper
mapping: recover a missing post-backup paper through an explicit **Add old
content** decision, refresh the comparison, then copy its unanchored notes.
Both the old source operation and the native parent receipt must verify; matching
IDs or even reusing an old incarnation without a receipt cannot authorize copying.
Later paper metadata edits remain intact when retrying the same note-copy request.

The current protocol deliberately prohibits paper deletion. This flow recovers
missing papers; it does not weaken that retention rule or invent paper resurrection.
Notes carrying page/anchor references stay pending for exact-original verification;
no anchor is silently removed to make a copy succeed. A blocked copy still permits
read-only side-by-side review. Corrupt receipts for an already recorded copy fail
closed rather than being presented as a new unsupported action.
