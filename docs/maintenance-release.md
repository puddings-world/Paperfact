# Maintenance release acceptance

Scope: make installed copies identifiable and updates/reporting dependable before
expanding workspace sync. These changes are being prepared on the development
branch; they are not a published release or evidence of native Mac acceptance.

- Always-visible version footer; copy app/build/OS/CPU identity without account data.
- Automatic release checks and an explicit immediate check, with truthful offline status.
- Architecture-aware downloads, SHA-256 verification and retry without losing drafts.
- Local diagnostic preview/export with bounded crash and UI-stall summaries.
- No automatic report upload, account login, installation or research-data migration.
- Include completed daily-use features through `a786cb9` in the isolated 0.4.4 candidate:
  Drive sharing, list reasons/tags/sorting, queued view state and reading UX.
- Reject incomplete AI reasoning envelopes before storage; hide explicit preambles
  when rendering legacy explanations without rewriting stored research.

## Candidate gate

1. Select a reviewed maintenance base and port the fixes and completed daily-use features.
   Do not label unfinished 0.5 sync work as a 0.4.x maintenance release.
2. Set the intended version once, in `src/paper_daily/__init__.py`, before building.
   Record the clean source commit. A source checkout displays its development
   line and commit; the installed candidate displays v0.4.4 and its build commit.
3. Run `scripts/check.py` on the frozen candidate tree and retain its result.
4. Use the release workflow's manual dispatch to build unpublished Windows,
   Apple Silicon macOS and Linux candidates. Keep native/frozen acceptance
   separate from Python fixture tests.
5. On Windows and an M-series Mac, install into an isolated location with a
   fixture workspace. Verify first launch, import, reading, note/Q&A edits, export,
   copy-version and diagnostic preview/export. Test AI login with the tester's own
   account only as a deliberate manual check, not a stress loop.
6. Upgrade an older fixture installation: verify matching asset, interrupted
   download/retry, busy-job deferral, unsent question/draft restoration and unchanged
   research files. Check the reopened footer and exported diagnostic build agree.
   Exercise macOS copy failure/rollback and OS security prompts on real hardware.
7. Publish only after both native acceptance records pass. Existing installations
   receive the published notice; draft releases and local changes are invisible.

## Reporting from an existing Mac installation

Use Diagnostics and support if present, otherwise report the installed release tag,
asset filename, macOS version, Apple Silicon model and reproduction steps. Keep
`~/Library/Application Support/Paperfact` intact. A newly built maintenance
candidate must be installed on that Mac before its new footer/reporting can help.
See [SUPPORT.md](../SUPPORT.md) for the console fallback when the GUI cannot open.
