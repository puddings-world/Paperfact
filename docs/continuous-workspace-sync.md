# Continuous workspace sync

Status: local development candidate; not a hosted service or production login.

## Choose session-only or remembered synchronization

A reachable private sync service and an enrolled workspace/device are required.
The current candidate does not include a deployed service. AI or Google login
alone does not connect a research workspace.

- **Sync now:** explicitly exchange changes after verifying the connection.
- **Sync this workspace automatically during this app session:** enable the
  existing background worker until stopped or the app closes. Off by default.
- **Reconnect and sync when this workspace opens on this device:** separately
  opt in to remembering the exact verified connection in the native credential
  store and reconnecting automatically for this local workspace. It enables
  continuous sync now and on later opens after successful authentication.

Remembering a connection alone does not authorize background synchronization.
Without startup permission, reconnect explicitly after reopening the app.
Clearing startup permission stops automatic synchronization and future startup
reconnects. Disconnect ends this session; it does not remove startup permission.
See [remembered connections](remembered-sync-connection.md) for the exact controls,
native-store failure behavior and workspace-copy isolation.

For another computer, use [desktop pairing](sync-device-management.md#desktop-pairing-and-retry)
and join into a new folder. The join option **Keep the new workspace synchronized
when I open it on this device** grants startup permission only for that new folder.
Neither pairing nor joining switches or uploads the original local workspace.
Without an available sync service, use reviewed list-package export/import;
that creates an independent snapshot rather than ongoing synchronization.

## Background behavior

One background worker uses the same guarded SyncSession as manual sync and selected
downloads. New committed local journal entries request a debounced pass,
including note/AI/CLI/MCP writes that do not change a list view. The existing
workspace observer checks the journal every two seconds; the default debounce
is another two seconds, with busy work and offline backoff taking precedence.
Remote changes are polled every 30 seconds. These are scheduling intervals,
not a delivery deadline. Passes stay within existing metadata/file budgets.
Do not describe polling as instantaneous delivery or guaranteed mobile background
execution. The footer and connection panel distinguish waiting, working, offline,
paused and connection changed. Transfer counters represent actual completed work,
not an estimated percentage or whole-workspace offline readiness.

Offline failures back off from 10 seconds to at most five minutes; local changes
remain in the journal. Authentication, storage and incompatible-data errors pause
for explicit action. A new connection generation needs new consent even when IDs
match. Busy research/file/backup jobs defer another pass. Switching a workspace
cannot redirect an old worker. Stop/close can retain an already committed server
prefix; retry deduplicates it. Window close waits for the worker, and updater
restart preparation stops sync before proceeding.

The controller does not itself provision a server, issue the first device,
complete arbitrary legacy enrollment or evict cached files. Remembered startup
and trusted-peer pairing are implemented by the linked shared connection flows;
native vault prompts, hosted service operation and installed two-device acceptance
remain separate release gates. Tests use fixture workspaces and credentials,
not the owner's research or paid providers.

## Evidence and remaining acceptance

The controller checks cover local save wakeup, offline retry, duplicate activation,
connection replacement, cancellation and closing with work pending. These protect
the shared worker behavior; they do not prove hosted or installed-device success.
See [current delivery status](status-0.5.0.md) and the
[remembered-connection evidence](remembered-sync-connection.md#evidence-and-remaining-gates)
for scoped results. Historical overlapping case counts are not coverage percentages
and are not a reason to rerun every suite after a documentation change.

Automatic-sync status includes unfinished attachment work: **Files pending**
continues bounded passes; **Retrying files** uses backoff after file failures.
The connection panel shows file counters separately from metadata. Run the
workspace offline file check before disconnecting; metadata catch-up or an idle
sync controller is not proof that every PDF and asset is locally readable.


## Incoming saved text in the desktop reader

The [saved-text update notice](saved-text-updates.md) compares the open paper's
actually loaded text with committed current records. It uses the existing owned
workspace observer, including for unlisted papers. Changes are announced without
moving the PDF or replacing drafts. Explicit reload uses normal saved-content
preparation; source replacement and editable-deck controls stay separate. This
local observation also works for CLI/MCP/import writes and is not proof that a
remote service or every attachment has synchronized.


## Local writes versus received changes

The current desktop connects automatic-sync wakeup to the observer's separate
local_operations signal rather than its list-rendering changed signal. An indexed
journal sequence marker is read in the same short read-only transaction. The
observer inspects only operations appended since its previous observation.

- Uncommitted writes and rollback do not wake a pass. Exact operation retry does
  not append another entry and does not produce another wakeup.
- The workspace/device binding must stay the same and sequence must advance.
  A changed identity or rolled-back journal is not silently treated as a new local
  write; normal session/recovery validation remains required.
- A new entry still needing upload or whose server receipt is ahead of the local
  receive cursor wakes synchronization. Remote acceptance alone is not completion.
- Received peer changes and acknowledgment/cursor updates do not append local
  operations. A manual pass that already delivered a new entry before observation
  leaves no outstanding work and does not cause an extra automatic pass.
- A stale or unavailable open-paper text read does not suppress journal observation
  for other work. The text notice remains advisory and never grants write authority.
- The signal cannot enable synchronization or bypass login, explicit session
  consent, active-job barriers, retry backoff or close/reconnect guards.

No new worker, persistent counter, trigger, database migration or model call is
needed. Existing older custom observer integrations without local_operations keep
their former changed-signal fallback; the current desktop uses the dedicated path.
See [actual scheduling scenarios](testing/continuous-outbox-scenarios.md).
