# Selected offline preparation UI

Open **Research data ? Prepare selected papers for offline reading** from the current paper
or a list selection (up to 100 papers). Actions apply to that captured selection.

1. **Sync connection?** opens the existing connection interface. It shares the process-memory
   session owned by the workspace window. No credentials or endpoint are loaded from files;
   connecting remains explicit and does not transfer research.
2. **Download missing selected files** fetches already-known current PDF and editable-deck
   attachments through `SyncSession.prepare_offline`. It does not push or pull metadata,
   upload local content, change retention marks, or contact an AI provider.
3. **Verify selected files** independently validates local bytes and current source relationships.
   Only this action can show a dated verified snapshot, scoped to the selected manifests.
   Recheck after source/file changes and before going offline.

Unknown manifests need a separate explicit metadata sync. A bounded transfer pass may be partial;
retry resumes saved progress. The progress bar is indeterminate for coordinator steps, or shows
actual bytes for the current file when its size is available. It is not a total-work estimate.

A download clears an earlier verification timestamp. Cancellation, connection replacement,
workspace changes and source replacement cannot produce a late success badge. Closing waits for
both download and nested connection workers at safe boundaries. Unsent parent drafts and table
selection are preserved. A disconnected user sees an explicit connection action, never an
unrequested login or background transfer.

Fixture evidence covers fake sessions and actual `SyncSession`/PDF/deck downloads, existing
connection-dialog regressions, session sharing, partial retry, cancellation, rapid repeat clicks,
workspace/source/connection races and nested worker closure. Native device transfer, production
endpoints and credential persistence are outside this UI check.
