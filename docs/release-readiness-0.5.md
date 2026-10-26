# v0.5.0 release readiness

Status: **acceptance plan, not release approval**, 2026-10-26. v0.4.1 remains the
published baseline. The local sync journal, reference service/client, research
adapter and attachment primitive are development foundations; their tests do not
establish complete writer coverage, hosted security, mobile support or installer
acceptance. Consult the [implementation ledger](implementation-0.5.0.md) for results.

## Evidence rules

- Record the exact source commit, clean/dirty state, command, platform/runtime,
  passed/failed/skipped counts and artifact/log location. Record skips with reasons.
- A passing fixture is not a live account, real-device or hosted-service check.
  Never reuse a prior version's pass result as evidence for this candidate.
- Use generated research and isolated profiles for automated acceptance. Real-user
  pilot data requires separate informed participation; do not upload the maintainer's
  workspace as a test fixture. Verify preserve/restore with hashes and content counts.
- Only mark a gate passed after attaching its evidence. All gates below are pending
  for v0.5.0 until the parent records a candidate result.

## Release gate matrix

| Gate | Required observation | Evidence target |
|---|---|---|
| Source checks | Privacy scan, Ruff, Python/desktop tests and all mobile/frontend tests pass | `scripts/check.py` log and exact counts for candidate commit |
| Write coverage | UI, CLI, MCP, imports, AI completion and PDF replacement capture supported mutations | Writer inventory with an adapter test per supported entry point |
| Desktop convergence | Two isolated workspaces exchange lists, memberships, notes, analysis, anchors and decks | Content/revision/hash comparison after offline edits and reopen |
| Retry/durability | Lost responses, duplicate delivery, partial saves and restart create no duplicate research | Synthetic interruption/concurrency tests with preserved outbox/cursor assertions |
| Conflicts | Edit/edit, edit/delete and concurrent resolutions retain recoverable versions | Both versions visible and resolvable; active drafts remain untouched |
| Attachments | PDFs/figures/deck assets resume, verify and respect ownership/PDF version | Corruption, mismatch, missing asset, quota and cancellation tests |
| Recovery | Consistent backup restores into a separate workspace without importing device credentials | Research counts, hashes, history and unsent-operation reconciliation report |
| Deletion/history | Tombstones obey retention; stale clients cannot resurrect deleted research | Offline-horizon and re-bootstrap tests, documented retention policy |
| Access isolation | Wrong user/workspace, revoked device and stale session are denied | Service integration tests plus deployment/session review |
| Mobile durability | Offline notes survive reload; storage failure is visible; reconnect reconciles | IndexedDB/browser tests and separately recorded physical-device journey |
| UI safety | Cancel/retry/repeated activation, account switch and close do not misapply results | Desktop/mobile state tests, focus/draft/selection assertions |
| Existing features | Import/read/own-AI/export, editable decks and local MCP retain their contracts | Existing full suite and frozen acceptance on every desktop platform |
| Hosting readiness | Auth, TLS, authorization, abuse limits, operator, cost/region and recovery are settled | Reviewed deployment decision record and synthetic hosted integration results |
| Privacy | Sync excludes AI credentials/telemetry; logs redact secrets and research bodies | Payload/log fixtures and consent boundary tests |
| Distribution | Source, binaries, version, license/notices and provenance match | Clean build info, source archive, checksums and three-platform artifacts |

## Platform acceptance

| Target | Required v0.5.0 evidence | Current claim |
|---|---|---|
| Windows x64 source/setup EXE | Full suite, frozen app, isolated clean install/reinstall/upgrade/uninstall, data preservation | Pending; no v0.5.0 platform acceptance recorded here |
| macOS Apple silicon source/DMG | Full suite, frozen app, install/update preservation, offline reading and sync | Pending; no live Mac result recorded here |
| Linux x86-64 source/AppImage | Full suite, frozen app, executable/update preservation and offline reading | Pending; no live Linux result recorded here |
| iPhone/Safari installed PWA | Offline launch, PDF/readability, note reload, foreground reconnect, storage/error recovery, touch/accessibility | Pending; simulation does not replace physical-device results |
| Android/Chrome installed PWA | Same journey, including suspend/foreground and failed-network recovery | Pending; no physical-device result recorded here |

Record OS/browser versions, installed-versus-browser mode and hardware separately.
Minimum mobile support versions remain a decision gate; do not infer them from the
development machine's browser. Native app-store mobile packages are out of scope.

## Existing build pipeline and required extensions

The current [release workflow](../.github/workflows/release.yml) runs
`scripts/check.py`, generated screenshots, `scripts/build_app.py` and
`scripts/verify_built_app.py` on Windows, macOS and Linux. Its artifact families are
`acceptance-*`, `provenance-*`, `screenshots-*` and `build-*`.
`workflow_dispatch` builds candidates without creating a release; a version tag
creates a draft only after all build jobs pass. See [releasing](releasing.md).

Before v0.5.0, integrate mobile checks into the root full check and extend frozen
acceptance to supported sync/configuration boundaries. Keep a no-network fixture
path for packaged tests. Separately test the reviewed service and real devices;
frozen-app success alone does not exercise cloud/mobile synchronization.

Use an explicit disposable install directory for Windows acceptance with
`/ACCEPTANCETEST=1 /NOCLOSEAPPLICATIONS /DIR=<isolated-path>`. Use a separate fixture
data directory; never uninstall or update the user's active install to satisfy a
stress test. Retain onboarding smoke and acknowledged-reader smoke as distinct checks.

Expected installer names remain:

- `Paperfact-0.5.0-windows-x64-setup.exe`
- `Paperfact-0.5.0-macos-arm64.dmg`
- `Paperfact-0.5.0-linux-x86_64.AppImage`

Names are targets, not existing artifacts. Produce all platforms from one reviewed
commit, keep corresponding source/license notices, and verify artifact checksums.
Do not claim code signing/notarization unless completed and tested for the candidate.

## Upgrade, rollback and release sequence

1. Freeze the agreed scope and writer coverage. Preserve v0.4.1 for download.
2. Back up a synthetic v0.4.1 workspace containing PDFs, anchored notes, analysis,
   lists and editable slide layouts. Record data paths and hashes before upgrade.
3. Run source and installed upgrade paths. Preserve explicit `PAPERFACT_DATA` and
   legacy path overrides; no silent migration into an empty directory.
4. Verify research and device-local settings remain available. Snapshot sharing
   remains distinct from sync enrollment and does not transfer provider credentials.
5. Verify failed migration rollback. A downgrade must not open an incompatible newer
   schema for writing; recovery uses a known compatible backup in a separate folder.
6. Test update detection for beta/stable channels, source instructions and each
   platform's asset; cancel, repeated activation and close cannot launch a stale update.
7. Once gates pass, set the version only in `src/paper_daily/__init__.py`, build the
   release candidate and attach exact validation evidence. Publishing is a separate
   authorized action, not implied by this document.
8. Publish the initial v0.5.0 as a prerelease with supported/experimental features,
   service privacy/retention limits and known platform gaps stated clearly.

The updater currently recognizes numeric `vX.Y.Z` release tags and ignores drafts.
Do not invent `v0.5.0-beta.1` update behavior or remove the prerelease marker to work
around an older client's policy. Existing 0.x beta/stable channel behavior is
described in [releasing](releasing.md); revalidate it against candidate tests.

## Evidence record template

```text
Gate / scenario:
Candidate commit and tree state:
Platform, OS, browser/runtime and package type:
Fixture workspace / isolation method:
Command or manual steps:
Expected content, hashes and visible state:
Actual result; passed / failed / skipped counts:
Logs, screenshot/report and artifact checksum references:
Limitations, unresolved failures and responsible owner:
```

This plan does not authorize cloud deployment, telemetry upload, credential changes,
paid model calls, destructive real-workspace testing or publication.
