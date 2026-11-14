# Continuous workspace sync

Status: local development candidate; not a hosted service or production login.

After verifying a matching enrolled workspace/device, enable **Sync this workspace
automatically during this app session**. The toggle is off by default. Connecting
alone never sends research; closing settings preserves the explicit session choice.
Restarting the app requires reconnecting and opting in again. Credentials and this
choice stay in process memory, outside research, packages, backups and settings.

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

This does not implement secure remembered login, device issuance, production
hosting, first-enrollment adoption or cache eviction. Test credentials, fixture
authorities and copied workspaces were used; no paid provider or research upload.

Focused evidence: 61 tests passed in 128.21 seconds, including the new controller,
existing connection/dialog/session behavior, actual captured journal/authority,
offline retry, revocation, session replacement, source change, cancellation,
repeated activation, close/restart and bilingual labels. A combined full gate
is still required before commit.


Merged evidence: 85 controller/session/dialog/claim-entry cases passed in 83.44s;
23 controller/status cases passed in 64.32s after marking new edits Waiting and
labeling historical counters. These overlap with the isolated selection above.
No complete-gate claim is made by those focused runs.

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
