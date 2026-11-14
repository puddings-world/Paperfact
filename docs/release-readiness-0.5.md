# v0.5.0 release readiness

Status: **development candidate, not release approval**, updated 2026-11-15.
Source checks, native CI, installed-device journeys and hosted acceptance are
separate boundaries. Keep the published maintenance app and research unchanged.
The candidate version is `0.5.0.dev`; its source commit identifies the actual build.
See [current implementation evidence](status-0.5.0.md) and the platform table below.
A native package pass does not prove complete writer enrollment, hosted security,
physical-phone durability or installed upgrade preservation.

## Evidence rules

- Record the exact source commit, clean/dirty state, command, platform/runtime,
  passed/failed/skipped counts and artifact/log location. Record skips with reasons.
- A passing fixture is not a live account, real-device or hosted-service check.
  Never reuse a prior version's pass result as evidence for this candidate.
- Use generated research and isolated profiles for automated acceptance. Real-user
  pilot data requires separate informed participation; do not upload the maintainer's
  workspace as a test fixture. Verify preserve/restore with hashes and content counts.
- Mark each boundary `passed`, `failed` or `not run` only from its actual evidence.
  Never turn a CI result into a physical-device pass or add overlapping test counts
  into a completion percentage. Open gates prevent release approval.

## Release gate matrix

Use [the curated test requirements](testing/README.md#keep-the-suite-small-by-testing-requirements).
Historical full-suite execution is not an automatic release prerequisite.


| Gate | Required observation | Evidence target |
|---|---|---|
| Source checks | Privacy/Ruff, curated release requirements and changed-domain regressions pass | `scripts/check.py` log and exact counts for candidate commit |
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
| Existing features | Import/read/own-AI/export, editable decks and local MCP retain their contracts | Curated critical journeys and frozen acceptance on every desktop platform |
| Hosting readiness | Auth, TLS, authorization, abuse limits, operator, cost/region and recovery are settled | Reviewed deployment decision record and synthetic hosted integration results |
| Privacy | Sync excludes AI credentials/telemetry; logs redact secrets and research bodies | Payload/log fixtures and consent boundary tests |
| Distribution | Source, binaries, version, license/notices and provenance match | Clean build info, source archive, checksums and three-platform artifacts |

Current common candidate: [4594626 / run 43640792668](https://github.com/puddings-world/Paperfact/actions/runs/43640792668),
full source `4594626421a925c8c8e2fec1ba8d89239fea9ee8`, clean `0.5.0.dev`.
All three desktop native reports passed; source critical is 14 per OS, not 42
unique journeys. Windows mobile artifact tests also passed 5/5 with 0 failures.
The earlier green-job/failed-mobile result is retained in the dated ledger;
canonical TEMP allocation and fail-fast shells now have actual Windows CI evidence.
Installed upgrades, real provider login, physical phones and hosted sync remain not run.
The curated `release` selection has not been run for this manual candidate.

## Platform acceptance

| Target | Required v0.5.0 evidence | Current claim |
|---|---|---|
| Windows x64 source/setup EXE | Critical journeys, frozen app, isolated clean install/reinstall/upgrade/uninstall, data preservation | Native CI 4594626: critical 14 and frozen reader/import/export/audit/CLI/MCP passed; setup install/reinstall/upgrade/uninstall and physical sync not run |
| macOS Apple silicon source/DMG | Critical journeys, frozen app, install/update preservation, offline reading and sync | Native CI `4594626`: critical 14, three reader starts, original audit and Launch Services foreground/close passed; physical input/upgrade/offline two-device journey not run |
| Linux x86-64 source/AppImage | Critical journeys, frozen app, executable/update preservation and offline reading | Native CI `4594626`: critical 14, reader/import/export/original audit and AppImage CLI/MCP/retry passed; installed update/offline two-device journey not run |
| iPhone/Safari installed PWA | Offline launch, PDF/readability, note reload, foreground reconnect, storage/error recovery, touch/accessibility | Pending; simulation does not replace physical-device results |
| Android/Chrome installed PWA | Same journey, including suspend/foreground and failed-network recovery | Pending; no physical-device result recorded here |

Record OS/browser versions, installed-versus-browser mode and hardware separately.
Minimum mobile support versions remain a decision gate; do not infer them from the
development machine's browser. Native app-store mobile packages are out of scope.

## Candidate pipeline and remaining acceptance

The current [release workflow](../.github/workflows/release.yml) runs
`scripts/check.py`, generated screenshots, `scripts/build_app.py` and
`scripts/verify_built_app.py` on Windows, macOS and Linux. Its artifact families are
`acceptance-*`, `provenance-*`, `screenshots-*`, `research-fixture-*` and `build-*`;
the Windows job also verifies/uploads the shared mobile web artifact. Only the
synthetic research ZIP is shared, never a whole fixture account/workspace.
`workflow_dispatch` builds candidates without creating a release; a version tag
creates a draft only after all build jobs pass. See [releasing](releasing.md).

Manual candidates run the curated `critical` selection per OS, not the historical
suite. Tag releases additionally run the curated `release` selection once on
Windows: named Python/frontend/mobile-domain checks and the mobile/Python protocol
program. Preserve affected regression checks and the 30-minute per-job budget.
The opt-in historical `full` profile is diagnostic, not a ritual release prerequisite.

The frozen verifier uses generated research and isolated homes: duplicate import,
reader, four-PDF export fidelity, three-original/five-quote audit, credential
isolation and CLI/MCP restart/retry. Mac requires three consecutive reader starts
and native foreground/close; Linux also exercises AppImage CLI/MCP. It does not
install/reinstall the setup EXE or mount/upgrade the DMG on an owner's machine.
Separately test the reviewed service, native credential stores and real devices.
Frozen success alone does not exercise hosted multi-device or phone synchronization.

Use an explicit disposable install directory for Windows acceptance with
`/ACCEPTANCETEST=1 /NOCLOSEAPPLICATIONS /DIR=<isolated-path>`. Use a separate fixture
data directory; never uninstall or update the user's active install to satisfy a
stress test. Retain onboarding smoke and acknowledged-reader smoke as distinct checks.

Expected installer names remain:

- `Paperfact-0.5.0-windows-x64-setup.exe`
- `Paperfact-0.5.0-macos-arm64.dmg`
- `Paperfact-0.5.0-linux-x86_64.AppImage`

These are final release targets. Development candidate filenames use `0.5.0.dev`
and require their exact source commit. Produce platforms from one reviewed commit,
keep corresponding source/license notices, and record artifact checksums. GitHub's
artifact ZIP digest is not the contained installer payload's SHA-256.
Do not claim code signing/notarization unless completed and tested for the candidate.

## Upgrade, rollback and release sequence

1. Freeze the agreed scope/writer coverage; retain the selected published maintenance build.
2. Back up a synthetic workspace from that recorded maintenance version, containing PDFs, anchored notes, analysis,
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

`0.5.0.dev` candidates do not auto-update to release installers; replace the test
bundle explicitly while retaining its separate `PAPERFACT_DATA` directory.
The updater recognizes numeric `vX.Y.Z` release tags and ignores drafts.
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
