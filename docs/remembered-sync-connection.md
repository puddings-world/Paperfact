# Remembering a device connection

Status: isolated development candidate; native platform acceptance remains open.
This stores one explicitly verified connection in this device's system credential
store. It is separate from AI accounts, research synchronization consent, device
issuance and production hosted login.

## User flow

- Enter service, workspace, device and credential; optionally select **Remember
  the verified connection on this device**, then **Verify and connect**.
- A successful handshake can store exactly that connection. A vault failure leaves
  the verified in-memory session usable and reports that saving was not confirmed.
- On another app session choose **Use saved connection**, inspect the populated
  service/IDs, then **Verify and connect**. Loading alone sends no network request,
  starts no sync and grants no new background-upload consent.
- **Forget saved connection** removes the device's saved record. An already
  connected in-memory session remains usable; Disconnect ends that session.

All vault access runs in the existing guarded worker. Repeated clicks do not
create another job. Closing or changing workspace rejects late loads, clears
visible credentials and waits for active work. Native authorization prompts can
still need the user's system-level decision; the app never terminates that worker.

## Storage and safety boundaries

Production lazily accepts only the exact supported keyring native backend:
Windows Credential Manager, macOS Keychain, or Linux Secret Service. Disabled,
chained, plaintext and unknown backends remain unavailable; manual session-only
connection continues to work. Windows persistence is local-machine, not enterprise
roaming. Keyring package metadata and the native backend are included by packaging.
No actual system vault is queried by construction, preview, tests or packaging.

The vault account key hashes the exact local path, database file identity and
binding. A copied/restored database does not inherit the prior connection. These
observations stay private; raw paths are not stored in connection records. Tokens
are omitted from repr, diagnostics, SQL, app settings, packages and backups. The
closed record has a bounded UTF-16 size; larger credentials work in memory but are
not remembered. This does not claim protection against another program running
as the same operating-system user.

Before and after native access, recheck the actual source and cancellation.
Remembering requires the exact successful session endpoint/device/token. A stale
or cancelled write attempts to restore the previous vault record; an unavailable
rollback is reported for explicit system-store review. OS storage failures may
leave an operation unconfirmed; do not promise a transactional guarantee from the
native vault. Old opaque records from removed/moved databases may require manual
cleanup in the system credential manager.

## Evidence and remaining gates

Tests use an in-memory fake vault, a fixture authority and closed SQLite handles;
no real credential store, account, private research or paid call is accessed.
Behavior coverage includes opt-in, exact verified connection, loading without
network, forget without disconnect, replacement/binding/active-path changes,
malformed/oversized records, cancellation during access, rollback of the prior
record, UI close/retry and continuous-sync regressions. Packaging selection tests
are simulated. Native Windows/Mac/Linux prompts, installed binaries and production
identity still require separate acceptance. The parent owns integration and the
complete project gate; this document is not evidence of release readiness.

Primary API references checked on 2026-10-30:
[keyring documentation](https://keyring.readthedocs.io/en/latest/) and
[Windows backend](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py).


A review reproduced a queued-delivery race: the worker returned valid saved
connection details, then the same database's binding changed before the GUI
received them. The old dialog filled the old token (synthetic regression red).
The corrected dialog rechecks captured local metadata before accepting a vault
completion and again before explicit verification; failure disconnects and clears
the form. This check reads bounded local metadata only, without a native vault
lock/access, hash or network call, and is not added to the periodic poll. Three
focused cases passed before merged revalidation; full integration remains required.
