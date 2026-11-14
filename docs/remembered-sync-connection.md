# Remembering a device connection

Status: local v0.5 development; native platform acceptance remains open.
This stores one explicitly verified connection in this device's system credential
store. It is separate from AI accounts, research synchronization consent, device
issuance and production hosted login.

## User flow

- Enter service, workspace, device and credential; optionally select **Remember
  the verified connection on this device**, then **Verify and connect**.
- A successful handshake can store exactly that connection. A vault failure leaves
  the verified in-memory session usable and reports that saving was not confirmed.
- To pair a second desktop, follow [desktop pairing](sync-device-management.md#desktop-pairing-and-retry).
  Pairing explicitly saves a pending independent key before enrollment, then a
  verified connection. It does not grant startup upload consent.
- On another app session choose **Reconnect saved connection**. Paperfact first
  resumes any unfinished native pairing attempt; otherwise it reads
  the system credential store and verifies device identity in the background.
  The saved credential is never filled into a widget. Success enables **Sync now**;
  it does not upload research or enable continuous sync.
- After verification, optionally select **Reconnect and sync when this workspace
  opens on this device**. This remembers the exact verified connection and grants
  startup synchronization permission for this device. It also enables continuous
  sync now. Leave it unchecked for manual or session-only use.
- Clear that option to stop current automatic sync and future startup reconnects.
  The saved connection remains available for explicit reconnection. Disconnect
  alone ends the current session; it does not remove the future-startup preference.
- For manual inspection, open **Advanced** and choose **Load saved details without
  connecting**, inspect the service/IDs, then **Verify and connect**. Loading alone
  sends no network request and grants no background-upload consent.
- **Forget saved connection** removes the verified record and any unfinished
  pairing attempt for this local database. It does not revoke a remotely admitted
  device; revoke that peer from another trusted device when needed. An already
  connected in-memory session remains usable; Disconnect ends that session.

Opening the app or connection dialog does not access the credential store or
reconnect by default. Remembering credentials and permitting startup sync are
separate choices. After explicit startup opt-in, opening that exact local workspace
reads its native credential record in a background worker, reauthenticates the
device, then enables the existing sync controller. Offline authentication backs
off from 10 seconds to a five-minute maximum; unavailable vaults, rejected tokens,
changed bindings and changed credentials pause instead of silently switching
accounts. Hosted self-service signup and first-device issuance remain unimplemented.

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

Pending pairing and verified login occupy separate native slots. Complete the
verified save before deleting the pending attempt so a lost response or interrupted
cleanup remains retryable. Joining remembers the same independent device key for
the exact new database only after a fresh handshake and physical-file checks.
The startup preference is not copied. OS-store failures remain unconfirmed, not
transactional; an already created destination is retained for explicit retry.

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

## Device-local startup preference

Only a versioned connection fingerprint is stored under `sync-startup/` in the
platform's local [cache directory](../src/paper_daily/runtime.py). The filename is
bound to the vault account's hash of database path, physical file identity and sync
binding. The marker contains no endpoint, token, account ID or research content.
It is outside research, packages, backups and synchronized settings. Losing or
clearing that cache turns startup reconnect off; manual reconnection still works.

Permission applies to the exact saved connection, including its credential.
Copying/replacing/restoring the database, changing its binding, or replacing the
saved credential does not authorize a new connection. Forget removes the local
startup marker before native vault deletion, even if native deletion fails.

The GUI rechecks permission and workspace at delivery of a completed handshake,
not just inside the worker. Closing cancels and waits for the worker. Repeated
startup requests share the existing controller. Disabling during an in-flight
save requests cancellation; a setting already committed remains visible on the
next settings view and can be cleared explicitly. No worker is force-terminated.

## Evidence and remaining gates

Tests use an in-memory fake vault, a fixture authority and closed SQLite handles;
no real credential store, account, private research or paid call is accessed.
Behavior coverage includes opt-in, exact verified connection, loading without
network, forget without disconnect, replacement/binding/active-path changes,
malformed/oversized records, cancellation during access, rollback of the prior
record, UI close/retry and continuous-sync regressions. Packaging selection tests
are simulated. Native Windows/Mac/Linux prompts, installed binaries and production
identity still require separate acceptance. This document is not evidence of
release readiness. Use the curated critical gate plus affected regressions for
integration; see [the test policy](testing/README.md).

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
focused cases passed before the current reconnection work. The new reconnection
cases also cover missing/rejected records, retry, duplicate activation, held vault
access during cancellation/close/workspace change, and bilingual rendering.

Local evidence on 2026-11-14: the 16 existing and new connection UI cases passed
in 34.3 seconds including checks. A subsequent critical/consent/docs/bilingual
selection passed in 17.7 seconds under the Windows resource governor. These
selections overlap; they are not a full-suite result or installed-device proof.

The final integration selection passed **44 cases in 40.66 seconds**, with
privacy/Ruff and the bounded runner completing in **45.5 seconds**. It includes
all 14 critical cases, connection UI cases, three continuous-consent cases and
usage/documentation checks. Windows limited the job to two logical processors
and a 25% CPU cap; no historical exhaustive suite was run.


Startup consent evidence, 2026-11-14: 10 new boundary/behavior cases passed in
20.2 seconds including checks. The real MainWindow startup and both language
renders passed separately (3 cases, 15.2 seconds including checks). These use
synthetic native-vault records, isolated SQLite research and a fixture authority;
no native store, owner account or hosted service was accessed. The real window
successfully reauthenticated and delivered saved research through its existing
continuous controller. Native system prompts, installed upgrades and actual
Windows/Mac/phone synchronization remain external acceptance gates.


Implementation seams: `ConnectionVault.startup_record()` reads a bounded local
fingerprint; `set_startup(session, enabled, ticket=None)` explicitly saves or
withdraws permission; `reconnect_startup(session, expected, ticket)` authenticates
only the exact authorized record. The existing `ContinuousSync.resume_saved(vault)`
starts its guarded background flow. `resume_on_open(owner, database, *, current_path,
vault_factory=None)` installs that flow into the desktop's existing owner session;
its injection is for fixture tests, not an alternate plaintext backend.

Review also reproduced an incorrect cross-workspace handshake in the shared helper
(the regression failed before the guard). Startup now compares the session and
vault physical DB identities and the caller's current path before accessing the
stored record; session generation is checked again after vault access.

Final local integration evidence: 56 critical/affected/manual-consent/window/skill
cases passed in 74.5 seconds including checks. After adding explicit mismatched-
workspace refusal, 29 critical/scope/window/contracts cases passed in 17.6 seconds
including the bounded runner. These selections overlap and do not certify a
historical full run, a deployed authority or native installed-device acceptance.
