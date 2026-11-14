# GCS backup publication scenario map

The snapshot fixtures use actual SQLite events/conflicts and original bytes.
All cloud calls are simulated; tests forbid credential discovery by default.
The installed SDK's method signatures, exception classes and CRC32C vector
are checked; real multipart/resumable execution also uses only in-memory HTTP; no account, project, IAM, bucket or upload is used.

| Requirement | Observable acceptance |
|---|---|
| Complete snapshot | Exact files appear before the exact completion manifest; local snapshot bytes stay unchanged. |
| Retry | Same snapshot reuses every verified object without another creation. |
| Privacy (3) | Inherited/disabled PAP or disabled uniform access prevents any upload. |
| Partial failure | First object can survive; no completion is published; unchanged retry reuses it and finishes. |
| Wrong existing object (4) | Size, checksum, encoding or role/hash metadata mismatch refuses without overwrite. |
| Cancel | Cancellation after one verified object preserves partial data and permits exact retry. |
| Concurrent calls | Two publishers produce one generation per object and one completion, without duplicates. |
| Generation race | Changed earlier object generation refuses completion; explicit retry re-verifies it. |
| Invalid local input | Corruption fails before credential/bucket discovery. |
| Verification race | Database mutation immediately after inspection is not re-trusted. |
| Input mutation during send | SDK checksum corruption becomes a bounded publication failure, without a new completion. |
| Frozen final bytes | Even a late manifest-path change cannot substitute its completion bytes; any published marker still describes the exact verified remote data. |
| Invalid destination (6) | URL/space bucket names, traversal/absolute/empty/oversize prefixes fail before I/O. |
| Endpoint isolation | An emulator environment cannot redirect private publication. |
| Client lifetime | An explicitly owned SDK client is closed; no test logs in. |
| SDK contract | Actual upload/reload signatures support required generation/checksum fields; CRC matches the standard vector. |
| CLI | Offline help, one JSON receipt, bounded failure, throttled progress and quiet mode. |
| Budget/final cancel (2) | Expiry or cancel before final marker leaves no new completion. |
| Lost ACK | A created object is reloaded/verified after a precondition response instead of overwritten. |
| Missing SDK | A desktop without operator dependencies fails cleanly before credential discovery. |
| Two snapshots | Changed note creates a new authority snapshot/manifest but unchanged PDF bytes are shared; prior snapshot objects are untouched. |
| Headless runtime | Fresh subprocess publishes an actual empty snapshot through the fake cloud without importing Qt/desktop or creating default research. |
| Real SDK HTTP wire (2) | Anonymous SDK client uses only in-memory HTTP: small multipart and >8 MiB resumable chunks preserve exact snapshot bytes, generation headers and checksums. |
| Dependency/build boundary | GCP requirements are in the lock, absent from client runtime requirements and excluded from desktop Analysis. |
| Real setup script | A disposable checkout with a fake package installer creates a real isolated interpreter, executes offline CLI help, restores setup environment and leaves desktop/research untouched. Network dependency installation is simulated. |

The publisher file selects 32 cases, toolchain selects 3, and real SDK wire selects 2. Unchanged authority,
backup/restore, native research recovery, admin/mount and desktop-lock cases form
the broader integration selection. Exact terminal receipts live in the continuation
ledger; do not sum overlapping runs or interpret pytest progress as elapsed time.

Windows setup/process behavior is exercised here. POSIX setup/SDK wheels, Linux
service/mount behavior, real private GCS policy/CRC/generation/resumable transfers,
real network interruption, remote download/restore, capacity/cost and installed device
acceptance remain separate gates. The review-only manual unit has no timer and
no cloud deployment/RPO is claimed. Existing whole-application test-contract
conflicts remain unresolved; focused receipts cannot replace the failed full gate.


The first real-SDK HTTP fixture assumed content type was a JSON metadata field.
Installed SDK source shows multipart MIME and resumable initiation headers supply
it instead. The in-memory server fixture now reads those actual headers; exact
body, CRC and generation assertions stayed unchanged. No production behavior was
weakened and no cloud API was contacted to make the tests pass.


## Local checkpoint receipts

- First simulated publisher: **26 passed in9.11s**, `gcs-backup-first-20261114.log`.
- Expanded operator/setup selection: **33 passed in12.47s**,
  `gcs-backup-operator-20261114.log`.
- Content-addressed layout plus existing local backup/recovery/admin regressions:
  **109 passed in67.27s**, `gcs-backup-integrated-20261114.log`.
- Actual SDK wire fixture: initial1 failed1.41s due to its content-type assumption;
  fixture correction kept body/CRC/generation checks; **2 passed in2.21s**,
  `gcs-backup-sdk-wire-final-20261114.log`.
- Final coherent publisher/toolchain/wire/admin/mount/authority-backup/authority-
  recovery/native-research-recovery/desktop-lock scope: **112 passed in64.02s**,
  `gcs-backup-final-20261114.log`.

Selections overlap; do not sum them. The final scope includes37 new cases across
publisher32, toolchain3 and real-SDK-wire2. Real cloud execution, POSIX/operator
installation, actual installer contents and the whole-application full gate are
not established by these results. The full-gate status is retained separately.
