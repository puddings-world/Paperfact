# Sync device management

`DeviceManagementMixin` (`src/paper_daily/sync_device_management.py`) gives the
local `ReferenceService` authority a bounded, single-owner device catalog,
owner-entered labels and peer revocation. The reference HTTP transport and bounded
desktop Devices dialog expose those existing authenticated actions. Production
account identity and mobile pairing screens remain separate gates. The local
one-time pairing core is described below; administrative enrollment/revocation
remain private seams.

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
- No production account login or lost-access recovery flow; initial `enroll`
  remains a trusted admin seam. Desktop pairing requires an already trusted device.
- No device activity, last-seen or network metadata, by design.

Tests: `tests/test_sync_device_management.py`, `tests/test_sync_devices_http.py`,
`tests/test_workspace_devices.py` and `tests/test_devices_dialog.py`. These use
synthetic authorities/workspaces, actual loopback HTTP and simulated credentials.
They do not prove hosted deployment, real accounts, native vault access or
physical-device acceptance. Integration uses critical journeys plus affected
regressions; release/device gates remain separate.

The production pairing gap is unchanged: a trusted operator must issue the initial
workspace/device credential outside the public reference HTTP adapter. Listing
or revoking peers does not implement account login or recover lost access. An
already trusted device can explicitly authorize another device through pairing.


## One-time device pairing core

Status: local authority, Python SDK, desktop pairing screens and native receiver
retry storage implemented. Mobile pairing/reconnect/forget and HttpOnly browser
credential persistence are exercised in isolated Chromium; operator key loading
and same-origin HTTPS hosting remain pending.
No service was deployed and no real device was enrolled. The first trusted device
still requires operator-issued credentials. AI/Google Slides login is separate.

```mermaid
sequenceDiagram
    participant A as Verified owner device
    participant S as Private authority
    participant B as New device
    A->>A: Generate random invitation secret
    A->>S: Create invitation with existing device credential
    S-->>A: Workspace, issuer and fixed expiry
    A->>B: Explicitly share invitation through a private channel
    B->>B: Generate independent device ID and credential
    B->>S: Redeem invitation for that exact device
    S-->>B: Bound workspace and device identity
    B->>S: Verify with the new device credential
    Note over B,S: Joining local research and enabling sync are separate explicit actions
```

```python
service.create_pairing(device_token, code)
# {"workspace_id", "issuer_device_id", "expires_at"}
service.redeem_pairing(code, workspace_id, device_id, credential, label=None)
# {"workspace_id", "device_id"}

transport.create_pairing(device_token, code)
transport.redeem_pairing(code, workspace_id, device_id, credential, label=None)
client.create_pairing(code, ticket)  # DeviceClient, exact current enrolled session
```

Generate `code` and the independent `credential` with `secrets.token_urlsafe(32)`
in Python or 32 cryptographically random bytes encoded as base64url on a browser.
They must be distinct. An invitation may never become a device credential; the
service rejects collision with any invitation hash or existing device credential.
Use a fresh device identifier and preserve the same pending credential/label for
an exact retry. Lost-response retry is supported during the invitation lifetime;
desktop restart-safe receiver storage and cancellation-after-send behavior are
described below. After successful admission, the receiver can retry its independent
credential even when the invitation has expired.

The existing authenticated framing exposes:

| Route | Bearer | Closed request body | Closed success body |
|---|---|---|---|
| `/v1/devices/pairing/create` | Existing active device credential | `code` | `workspace_id`, `issuer_device_id`, `expires_at` |
| `/v1/devices/pairing/redeem` | One-time invitation code | `workspace_id`, `device_id`, `credential`, nullable `label` | `workspace_id`, `device_id` |

The mobile `HttpTransport` exposes the same names with an optional final
`AbortSignal`; create is `(token, code, signal)` and redeem is
`(code, workspace_id, device_id, credential, label = null, signal)`.
No secret is put in URLs. Responses use no-store; bodies/authorization must not
be logged by production infrastructure. TLS and literal-loopback rules are unchanged.

- Any active device may grant its own workspace only, following the existing
  single-owner trust model. Revoking the issuer prevents outstanding invitations
  from admitting a new device. It does not revoke independently paired devices.
- A grant expires after 600 seconds by server time. Exact create retries keep the
  original expiry; used or expired secrets cannot be renewed. Expired hash
  tombstones remain in the authority to reject reuse. Up to 100 unexpired grants
  (including consumed ones) may exist per workspace; this is not an abuse-rate limit.
- Claim and enrollment share one immediate SQLite transaction. Repeating the
  same device/credential/original-label returns its identity without overwriting
  a later label. A second claimant, changed request, wrong workspace, revoked
  device or invalid invitation is refused. Cancellation cannot retract a grant
  or device already committed remotely.
- Only secret hashes are stored; neither the old credential nor the invitation
  becomes the new device credential. Labels are explicit user metadata.
- Authorities created before pairing upgrade idempotently. Recovery accepts old
  backups without the new table, validates the optional table's exact columns,
  and creates a fresh authority with no previous devices or invitation grants.

Local evidence (2026-11-14): nine core/loopback cases passed in 4.9s including
checks; after wiring the guarded-session method, twelve core/context/old-new
backup cases passed in 6.6s. Mobile transport passed nine cases in 3.5s, followed
by the actual JavaScript-to-Python protocol program in 1.8s. The latter now covers
pair creation, exact retry, independent credential verification, second-claim
refusal and revocation as well as its existing research/file scenarios. These are
isolated synthetic fixtures under the Windows CPU governor, not real browser,
Keychain, hosted identity or installed Windows/Mac/phone acceptance.


### Pairing behavior map

| Selector | Observable requirement |
|---|---|
| `test_pairing_creates_independent_device_once_and_stores_no_raw_secrets` | A new device has its own credential; create retry retains expiry; claim retry preserves later labels; existing IDs and invitation-as-device-secret collisions make no writes |
| `test_pairing_refuses_changed_authority_without_creating_another_device` | Expiry, revoked issuer, wrong workspace and a different second claimant cannot enroll; a revoked receiver cannot be reactivated by retry |
| `test_pairing_claim_rolls_back_device_and_consumption_together` | A failure after device insertion rolls back both that device and invitation consumption; the original request can retry |
| `test_concurrent_claims_enroll_only_one_device` | Two different claimants race; exactly one new device is saved |
| `test_pairing_quota_and_restart_are_bounded` | Active invitation quota is enforced, expiry frees a slot, and reinitialization retains existing credentials |
| `test_actual_http_pairing_retries_and_revocation_keep_credentials_private` | Real loopback create/redeem/authenticate/revoke works; a second identity cannot reuse the grant |
| `test_pairing_uses_the_guarded_device_context_without_changing_local_research` | Desktop SDK shares the verified session fence; a disconnected context cannot issue a new grant; local research/outbox remain unchanged |
| `test_recovery_accepts_pre_pairing_backups_and_never_carries_device_grants` | Both old backups and active-grant backups restore without carrying previous devices or invitations |

The first six selectors are in `tests/test_sync_pairing.py`; the last two are in
`test_workspace_devices.py` and `test_sync_authority_restore.py`. The existing
mobile protocol program now includes pairing alongside research/file transfer;
one program is not one behavior or a completion percentage. No expanded stress
matrix or live login was used. The final core/compatibility/docs selection passed
**32 cases in 25.85s**, **29.2s including checks**. Selections overlap earlier
results; neither the historical full suite nor the complete release profile ran.

### Desktop pairing and retry

1. On an already connected and enrolled desktop, open **Devices**, choose
   **Pair another device**, then **Copy pairing details**. Copying is explicit;
   the old device credential is never copied. Share privately with your own device.
2. In the other desktop's unbound local workspace, open **Sync connection**, paste
   the details and choose **Pair and save on this device**. This explicitly uses
   the system credential store before contacting the authority. A new device ID
   and independent credential are retained for retry; no research is uploaded.
3. Choose **Join in new folder**, then **Open created workspace**. The metadata
   workspace is created separately and its verified connection is remembered for
   that exact database. Attachment availability remains a separate sync step.
   The original workspace and research remain unchanged.
4. In the joined workspace, choose **Reconnect saved connection**. Enable
   **Reconnect and sync when this workspace opens on this device** only if you
   want automatic research transfer on later opens. Pairing does not enable it.

If a reply is lost or the dialog closes after admission, **Reconnect saved
connection** resumes the same native attempt, not a second device. The receiver
first verifies its independent key; an already admitted device can recover after
invitation expiry. An unused expired invitation still requires fresh details.
A different packet cannot silently replace an unfinished attempt: resume or
explicitly forget it first. Forgetting locally does not revoke a device already
admitted remotely; use the originating device's catalog to revoke it.

Creating another invitation while one is active requires confirmation, defaulting
to No. A confirmed replacement does not revoke the earlier grant: it remains
valid until consumed, expired or its issuer is revoked. Copy is blocked when the
local binding/connection changes. Repeated clicks share one worker. Close cancels
and drains the worker; remote commits cannot be retracted by closing.

Unsupported old pairing endpoints report an actionable update/manual-setup
message. Native-store failure prevents first enrollment through this flow;
manual session-only setup remains available under Advanced. A joined workspace
whose native save fails is preserved and reports the need to retry that same
destination, rather than pretending creation rolled back.

The packet is closed JSON `paperfact.device-pairing.v1` (endpoint, workspace,
issuer, expiry, one-time code). Treat it as private access material. Pending
`paperfact.device-pairing-attempt.v1` records stay only in the native store under
a separate slot scoped to the exact source database. See
[remembered connections](remembered-sync-connection.md) for storage limits.

| Behavior tests | Requirement |
|---|---|
| `tests/test_sync_pairing_flow.py` (6 cases) | Exact lost-response/restart retry; independent keys; conflicting packets; copied-database isolation; cancellation/store failure before enrollment; refusing an enrolled identity replacement; joined-database save and file-replacement fences |
| `tests/test_pairing_dialog.py` (6 cases) | Actual create/copy/pair/join/open controls; duplicate prevention; saved retry; close after remote commit; stale binding blocks clipboard; English/Traditional Chinese rendering |
| `test_pairing_unsupported_route_is_actionable_without_changing_legacy_requests` | Pairing-only 404 becomes an update/manual-setup message; legacy request behavior remains unchanged |

These use synthetic research, fake native storage and local authority transports.
Rendering fixtures do not prove platform focus, native prompts or installed apps.
The [same-origin browser boundary and pairing screen](mobile-0.5.md#browser-pairing-and-offline-reconnection)
now use HttpOnly cookies; no token is put in IndexedDB or localStorage. Shell v21
includes the mobile pairing view. Initial issuance, hosted identity and
physical Windows/Apple Silicon/phone acceptance remain open.

Local desktop checkpoint: **29 affected cases passed in 44.56s**, **47.7s
including privacy/Ruff** under the 25% CPU/two-core/300-second governor. This
selection includes the 13 new receiver/UI/unsupported-endpoint cases and existing
vault, join, Devices lifecycle and usage-document regressions. The first combined
run found an older Devices fixture missing the existing `startup_record()` seam;
its two stubs now return no startup preference. Assertions/timeouts are unchanged.
No historical/full or release profile was run for this checkpoint.

The reusable local observation is durable receiver intent before a remote side
effect, followed by verified-save-before-pending-cleanup and exact destination
binding. Evidence is limited to this native flow and fake storage; it does not
establish browser persistence, transactional OS vaults or a general OAuth design.
Keep this evidence here rather than promoting an unverified global skill rule.

After merging the current `develop/0.5` UI-performance changes, the merged source
passed **16 cases in 16.85s**, **20.3s including checks**: all 14 critical
selectors, the actual clipboard/pair/join journey and actual MainWindow startup
consent. The earlier 29-case affected selection remains scoped evidence; these
overlapping counts must not be added as distinct coverage. No conflicts occurred
and no native credential store, private research or cloud service was accessed.
