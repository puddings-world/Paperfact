# Reference sync service administration

These commands make isolated, self-host development tests reproducible. They do
not deploy a public service, issue Google/AI login or establish production identity.
The reference HTTP adapter binds only to literal loopback. A Mac cannot reach the
Windows machine through `127.0.0.1`; each machine's loopback points to itself.
A cross-machine pilot still needs a separately approved, authenticated HTTPS
service and device acceptance. Do not open a public HTTP port as a shortcut.

## Local setup

Run from an installed command environment or after the documented source setup.
Use a dedicated empty directory, separate from research and device credentials:

```sh
paperfact sync-admin init --state "$HOME/.paperfact-sync/service"
```

Success: `{"state":"initialized"}`. Repeating succeeds; an unrelated nonempty
folder is rejected. The marked directory contains authority SQLite state and
verified attachment storage, not the desktop research database.

Issue a new local test device and write its connection record outside that folder:

```sh
paperfact sync-admin issue --state "$HOME/.paperfact-sync/service" --endpoint http://127.0.0.1:8765 --workspace demo-workspace --device desktop-lab --output "$HOME/.paperfact-sync/desktop-connection.json"
```

Success: a JSON receipt with `state=enrolled` and the output filename. The token
is written only in the private file, not stdout. The record can be pasted into
the desktop's **Use connection details** flow, reviewed and explicitly verified.
Choose a different device ID and output file for each new device; never copy one
active device's identity into another installation.

Start the local service in a separate terminal:

```sh
paperfact sync-admin serve --state "$HOME/.paperfact-sync/service" --port 8765
```

Success: a JSON `state=serving` receipt with `url=http://127.0.0.1:8765`. Keep the
terminal running; Ctrl-C closes the listener. Existing local research remains
usable when it stops. The private file contains a credential: transfer only to
its intended device, keep it out of Git/issues/research packages and remove the
transport copy when no longer needed. Access from other programs running as the
same OS user is outside this file-permission boundary.

## Command reference

| Command | Required options | Optional options | Outcome |
|---|---|---|---|
| `sync-admin init` | `--state DIRECTORY` | `--help` | Initialize or validate a dedicated reference authority |
| `sync-admin issue` | `--state DIRECTORY --endpoint URL --workspace ID --device ID --output FILE` | `--help` | Issue one new device and save its connection record |
| `sync-admin serve` | `--state DIRECTORY` | `--port INTEGER` (default 8765; 0 chooses an ephemeral test port), `--require-mount DIRECTORY`, `--help` | Serve the reference protocol on 127.0.0.1 |

All commands support `--help` without initializing service state. URLs use the
same HTTPS/literal-loopback policy as the desktop; remote plain HTTP, query tokens
and credential-bearing URLs are rejected. Device and workspace IDs use the
existing bounded protocol identifier format.

## Failure and retry

- Repeating issuance with the same valid output, endpoint and IDs validates the
  stored credential and returns `already_enrolled`; no second device is created.
- An unrelated, malformed, mismatched or revoked output is never overwritten.
  Review it and choose a new device identity/output when appropriate.
- Issuance writes, flushes and closes its exclusive output before committing enrollment.
  A normal write/flush/close failure rolls back the database change and attempts to
  remove only the file this operation created. A replaced output is not removed.
- Abrupt termination is not a distributed transaction: a crash before database
  commit may leave an unusable connection file. Review it explicitly. A complete
  valid file after commit can be retried. Do not claim universal crash atomicity.
- POSIX outputs are created with owner-only mode; Windows inherits the selected
  directory's ACL. Use a user-private directory. The command does not change ACLs
  of existing directories, rewrite research data or upload credentials.
- Errors return exit code 2 and a bounded explanation without echoing tokens.
  An interrupted listener exits 0 after closing its socket.

## Local API

`sync_admin.initialize(state) -> dict`, `authority(state) -> ReferenceService`,
`issue(state, endpoint, workspace, device, output) -> dict`,
`require_mount(state, mount) -> Path`, and
`main(argv=None) -> int` support the CLI. Paths are explicit; no research default
is selected. `ReferenceService.enroll(workspace_id, device_id, *, before_commit=None)`
retains its trusted-admin boundary. An optional callback receives the new token
inside the enrollment transaction; a callback failure rolls enrollment back.
It is not exposed as an HTTP enrollment endpoint.

## Remaining deployment gates

Production authentication/issuance/recovery, HTTPS hosting, origin policy,
retention/quotas and operator monitoring must be selected and verified before an
internet pilot. Existing defaults are a local reference configuration, not a
capacity or security promise for public hosting. Installed Windows/Mac and real
mobile device tests remain separate from loopback fixture checks.

Operator examples store private state/connection files outside the checkout.
Conventional `*-connection.json` files and local authority directories are ignored
by this repo. The pre-commit full check also rejects complete version-1 connection
records containing credentials, even under another filename; it does not print
the credential. The explicit `REPLACE_WITH_NEW_DEVICE_TOKEN` placeholder and
empty templates are allowed. These guards do not make a Git checkout a private
credential store or detect every possible secret encoding.

## Reviewed deployment starting point (not installed)

The [GCP pilot proposal](gcp-sync-pilot-plan.md) includes an inert
[systemd template](../deploy/gcp/paperfact-sync.service.example). No command here
provisions a VM, formats a disk, creates users or enables a service.

For an approved Linux host, the operator must first mount the dedicated disk at
`/mnt/paperfact` using its approved UUID, install the pinned application at
`/opt/paperfact`, create the unprivileged `paperfact-sync` user, and explicitly
initialize `/mnt/paperfact/service` as that user. Review ownership and disk identity
before initialization; neither `serve` nor the unit initializes an authority.

The template adds mount dependencies, a read-only application tree, owner-only
file creation, bounded failure restarts and an interrupt-based stop. Its absolute
paths are example Linux server paths, not desktop data defaults. If the mount
path changes, update the mount unit name, dependencies, writable path and CLI
arguments together. Review the host's systemd version with `systemd-analyze verify`
on the adapted unit before installing it.

```sh
paperfact sync-admin serve --state /mnt/paperfact/service --require-mount /mnt/paperfact --port 8765
```

Success: the usual loopback-only `state=serving` receipt. A missing/unmounted
volume, relative mount path, state outside the volume or state equal to the mount
fails with exit code 2 before opening the authority/listener. An ordinary directory
is not sufficient even if a valid authority was accidentally left beneath it.
Restoring the correct mount permits an explicit retry. Existing local commands
without `--require-mount` retain their development behavior.

This startup guard uses the OS mount check. It does not authenticate the mounted
disk, hold a mount lock, detect storage failure during every request or provide
backup/recovery. The UUID-pinned host configuration, mount dependency, disk
monitoring and tested restore are separate requirements. systemd mount dependencies
and stop/restart semantics are described in the official
[unit manual](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
and [service manual](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
The unit has not been launched on Linux/GCP. Verify stop during an active transfer,
restart, disk absence, permission errors and reboot there before pilot acceptance.
It does not provide the TLS proxy or same-origin PWA hosting.


## Local authority backup commands

`sync-admin backup --state DIRECTORY --output NEW_DIRECTORY [--seconds 30]`
exports a bounded, consistent authority snapshot and verified committed objects.
`sync-admin verify-backup --output DIRECTORY [--seconds 30]` inspects it read-only.
Both support `--help`; the budget is positive and at most 300 seconds. Success
returns actual file/byte counts; failures return 2 without overwriting existing
output. A snapshot is private operator data, not a research package or live
restore. See [backup workflow/API/limits](sync-authority-backup.md), including the
writer pause, omitted partial transfers, fresh-path retry and remaining GCP gates.


## Isolated fresh-identity recovery

`sync-admin restore-backup --input BACKUP_DIRECTORY --state NEW_DIRECTORY
--workspace OLD_ID --as-workspace NEW_ID [--seconds 30]` reconstructs exactly one
selected backed-up workspace. All four path/ID options are required; the time
budget is positive and at most300 seconds. It supports `--help`, returns actual
counts and `requires_enrollment=true`, and never overwrites existing state or
starts a listener. Old credentials are not restored. See [exact recovery,
re-enrollment, Python API and limits](sync-authority-restore.md).


## Private GCS publication (source operator environment)

`sync-admin upload-backup --input DIRECTORY --bucket NAME [--prefix
paperfact/authority-backups] [--seconds 300] [--quiet]` publishes only a verified
authority snapshot, with create-only shared content and a completion manifest last.
Input/bucket are required; seconds must be positive and at most300. Offline
`--help` makes no cloud call. Use the independent locked operator setup and review
access before intentionally running it. [Workflow, API, failure/retry and gates](gcp-backup-publication.md).
No command provisions a bucket, changes IAM or configures a timer.

## Retrieve an exact cloud backup

`download-backup --bucket NAME --snapshot SHA256 --output NEW_DIRECTORY` retrieves one exact private authority backup. Optional `--prefix`, `--seconds` and `--max-bytes` bound the operation. See [complete flags, API and failure behavior](gcp-backup-retrieval.md). This does not restore a service or reconnect devices.

## Compare an old device with an authority backup

`review-device-backup --database FILE --input DIRECTORY --workspace ID [--seconds 30]` is a bounded read-only comparison, not device migration. See the [full CLI/API and desktop workflow](device-recovery-review.md). It does not use credentials, GCP, research contents in output or implicit database initialization.
