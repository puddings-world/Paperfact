# Sync device management

`DeviceManagementMixin` (`src/paper_daily/sync_device_management.py`) gives the
local `ReferenceService` authority a bounded, single-owner device catalog,
owner-entered labels and peer revocation. The reference HTTP transport and bounded
desktop Devices dialog expose those existing authenticated actions. Production
identity, account and pairing flows remain separate gates; no public enrollment
or administrative revocation endpoint is introduced.

## Ownership model

Every device token enrolled in a workspace belongs to the same research owner.
Any active (non-revoked) device in a workspace may therefore list, label and
revoke its peers. The trusted administrative seams `enroll(workspace_id,
device_id)` and `revoke(token)` are unchanged and remain non-public.

## API

```python
service.device_catalog(token, *, after=None, limit=50)
# {"workspace_id", "current_device_id",
#  "devices": [{"device_id", "label", "revoked"}], "next_cursor"}

service.rename_device(token, device_id, label)
# {"device_id", "label", "changed"}

service.revoke_peer(token, device_id)
# {"device_id", "revoked": True, "changed"}
```

- `device_catalog` orders devices by device ID. `limit` must be an `int` (not
  `bool`) from 1 to 100; at most `limit + 1` rows are read. `after` is `None`
  or a sync identifier and is strict (`device_id > after`); it need not name an
  existing device. `next_cursor` is the last returned ID when more remain,
  otherwise `None`.
- `rename_device` sets or clears (`None`) a label on the caller or a peer,
  including revoked peers. Repeating the same label reports `changed: False`.
- `revoke_peer` refuses the caller's own device (`CurrentDeviceError`); stopping
  this device remains a local Disconnect. Revoking an already-revoked peer
  succeeds with `changed: False`.
- Unknown targets raise `UnknownDeviceError` (a `ValueError`) with the same
  message whether the device is missing or belongs to another workspace.
- Invalid, unknown or revoked caller tokens raise `PermissionError` before any
  input is validated.

## Labels

Labels are optional, nullable plain text of 1–64 Unicode code points with no
leading/trailing whitespace. C0/DEL/C1 controls (including tab, CR, LF, NEL),
surrogates, line/paragraph separators and bidirectional override/isolate
controls are rejected. Emoji ZWJ sequences and non-Latin scripts are accepted.
Labels are never inferred: the authority does not derive hostnames, accounts,
emails, IP addresses or activity, and none are stored or returned.

## Invariants

- Each method authenticates with the existing `_authenticate` inside the same
  `_transaction` that reads or writes, and scopes every query by the caller's
  workspace. Writes use `BEGIN IMMEDIATE`; any failure rolls back.
- Token values and token hashes are never selected or returned.
- Peer revocation only sets `revoked=1` on that workspace/device row. Events,
  heads, graph metadata, blob ownership, uploads and all pull cursors are
  untouched; a replacement device sees the full history. Revoked device IDs
  stay reserved, as with admin revocation.
- `session_info`, `push`, `pull` and blob contracts are unchanged.

## HTTP and current-workspace client

The exact authenticated POST routes are `/v1/devices/list` (`after`, `limit`),
`/v1/devices/rename` (`device_id`, nullable `label`) and `/v1/devices/revoke`
(`device_id`). They use the existing bounded JSON framing, bearer handling,
no-store responses and HTTPS/literal-loopback policy. Both request and response
fields are closed. Catalog responses validate identity, sorted unique IDs,
single-line labels, exact booleans, page size and strict continuation cursors.
Unknown/missing/revoked callers receive the same 401 response. Absent and foreign
targets receive the same 404 response. These claims concern response shape/status,
not timing indistinguishability or production abuse controls.

`HttpTransport` exposes `device_catalog`, `rename_device` and `revoke_peer`.
`DeviceClient` captures the current connection epoch and identity without copying
or exposing its token. Each action shares the session job lock, reauthenticates
the workspace/device, requires the current local binding, and checks cancellation,
database identity, active workspace and connection generation before/after work.
Revoked authorization invalidates the session and requires reconnecting. Device
actions do not consume the research outbox, reset a cursor or change local data.

## Desktop Devices dialog

The connection window enables **Devices** only for its current authenticated,
enrolled local binding. The dialog retains one page of at most 50 rows and offers
Refresh, Next page, optional label editing/clearing, and confirmed peer revocation.
The current device is identified and cannot revoke itself; use the connection
window's Disconnect action. Revoked rows remain visible. Labels, workspace/device
IDs and revoked state are the only displayed device data; no activity, IP, account,
token or token hash is inferred or exposed. New copy is English/Traditional Chinese.

Duplicate activation starts one worker. Empty selection, cancelled confirmation
and invalid labels send no action. Stop/close discards late results and waits for
the active worker; a changed connection/workspace cannot repaint or mutate another
view. A cancellation cannot retract a remote change already committed, so the
dialog asks the owner to Refresh to check sent changes. Label/revoke retries are
idempotent. Existing GUI credential-lifetime checks remain in place. No native
credential-store or AI operation is needed for these controls.

## Schema upgrade

Ordinary `ReferenceService` initialization adds a nullable `label TEXT` column
to `sync_devices` when it is missing. The check runs inside the existing
initialization write transaction, so it is idempotent and serialized across
concurrent openers. Existing device IDs, token hashes and revocations are
preserved; pre-existing devices have `label = NULL`.

## Limitations and follow-ons

- No mobile device-management UI.
- No multi-owner roles, per-device permissions, audit log or rate limiting.
- No production identity, account, pairing or recovery flow; `enroll` remains a
  trusted admin seam.
- No device activity, last-seen or network metadata, by design.

Tests: `tests/test_sync_device_management.py`, `tests/test_sync_devices_http.py`,
`tests/test_workspace_devices.py` and `tests/test_devices_dialog.py`. These use
synthetic authorities/workspaces, actual loopback HTTP and simulated credentials.
They do not prove hosted deployment, real accounts, native vault access or
physical-device acceptance. The combined candidate still requires the full gate.

The production pairing gap is unchanged: a trusted operator must issue the initial
workspace/device credential outside the public reference HTTP adapter. Listing
or revoking peers does not implement account login, prove who should receive a new
device credential, recover an owner's lost access or authorize remote enrollment.
