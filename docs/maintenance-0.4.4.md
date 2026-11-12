# v0.4.4 maintenance candidate

Status: unpublished candidate based on `hotfix/0.4.4` (`f13599c`), on top of v0.4.3.
Completed daily-use changes are backported through `a786cb9`; active v0.5 work
continues separately. Windows and Apple Silicon macOS use this same candidate.

## Included

- Version/build identity in the bottom-right footer, with copy, update and support actions.
- Published-update checks every 15 minutes, explicit offline status and manual retry.
- Platform/CPU selection, download length and SHA-256 verification before installation.
- Draft preservation and active-job checks before updating; failed launches keep the app usable.
- Mac replacement rollback when moving or copying the replacement fails.
- Previewable, minimized diagnostic exports with bounded crash and UI-stall summaries.
- Working note/Q&A cards and Gemini through the user's own AI Studio key.
- Research package sharing through the sharer's own Google Drive, with resumable upload.
- Editable per-list paper reasons and tags, layered sorting, and recently opened paper sorting.
- Responsive window sizing, keyboard navigation, background list refresh and queued view preferences.
- The renamed research-context tab and its author/team filter.

The unfinished v0.5 research workspace synchronization and mobile client are excluded.
The small filesystem publication helper is used only for exclusive diagnostic ZIP export.
Diagnostics stay local until the user reviews and shares them. Installation is user initiated.

## Release gate

Run the full check and build unpublished workflow artifacts for Windows, Apple
Silicon macOS and Linux. Accept Windows and an M-series Mac on real devices with
fixture research before publishing a release. Verify upgrade, draft restoration,
version identity and diagnostic export. Preserve the existing research data folder.
Fixture tests and generated shell tests do not establish native installer acceptance.
