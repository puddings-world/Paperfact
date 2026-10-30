# Continuous workspace sync

Status: local development candidate; not a hosted service or production login.

After verifying a matching enrolled workspace/device, enable **Sync this workspace
automatically during this app session**. The toggle is off by default. Connecting
alone never sends research; closing settings preserves the explicit session choice.
Restarting the app requires reconnecting and opting in again. Credentials and this
choice stay in process memory, outside research, packages, backups and settings.

One background worker uses the same guarded SyncSession as manual sync and selected
downloads. Committed local changes request a debounced pass; remote changes are
polled every 30 seconds. Passes remain bounded by existing metadata/file budgets.
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
