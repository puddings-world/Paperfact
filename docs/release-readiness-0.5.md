# v0.5.0 release readiness

Latest common-platform candidate: [0a64ec7 / run43784461643](https://github.com/puddings-world/Paperfact/actions/runs/43784461643).
Windows7m40s/Mac6m15s/Linux3m36s pass from the same clean source, version
`0.5.0.dev`. Hash-checked provenance confirms frozen report generation via the
production host QProcess handoff with disabled child disk settings, exact original/
quote/model identity, retained read and one-completion cache retry. Each OS also
passes critical14, first-sync preservation1 and authority/retention14 source cases.
[Downloads and limits](testing/mac-acceptance-0.5.md).

Status: **development candidate, not release approval**, updated2026-11-16.
Full frozen desktop dialogs, installed two-device/phone journeys, old installed
binary upgrades, complete runtime adoption and authority/hosting requirements
remain. Preserve the published maintenance app and research. Source, binaries,
physical devices and hosted acceptance are separate evidence boundaries;
[the current status](status-0.5.0.md) preserves the full milestone.

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

The current candidate's pinned0.4.3 source-format probe preserves original
research columns, list/order and PDF/deck bytes through backward export, current
initialization and another export. This is source-format preservation, not an old
installer/registration/GUI upgrade or downgrade. Earlier native delivery records
remain in the [continuation ledger](testing/continuation-20261112.md).

## Platform acceptance

| Target | Required v0.5.0 evidence | Current claim |
|---|---|---|
| Windows x64 source/setup EXE | Critical journeys, frozen app, isolated install/reinstall/upgrade/uninstall and data preservation | Native0a64ec7: critical14, first-sync1, authority/retention14; frozen report private handoff, reader/CLI/MCP, isolated install/reinstall/uninstall and research preservation pass. Old installed-binary upgrade, shortcut/registration and physical sync remain. |
| macOS Apple silicon source/DMG | Critical journeys, frozen app, install/update preservation, offline reading and sync | Native0a64ec7: same source selections, frozen private report CLI, three reader starts, original audit and foreground/close pass. Physical input/vault/upgrade/offline two-device journey remain. |
| Linux x86-64 source/AppImage | Critical journeys, frozen app, executable/update preservation and offline reading | Native CI `355382c`: critical 14, same-workspace handoff, reader/import/export/original audit and AppImage CLI/MCP/retry passed; installed update/offline two-device journey not run |
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


Source-only screenshot readiness waits for saved/rendered content and refuses
blank PNGs. Local plain/WebEngine capture checks pass; native Mac screenshot
changes await the next coherent candidate. App runtime is unchanged.

### Source-aware report acceptance gap (candidate88595d3)

The three-platform run43754647228 proves its named packaged checks, not every
new workflow. Source-aware generation has simulated source/IPC coverage; the
frozen new-report model path has not been exercised. Before closing this gate,
verify an isolated frozen CLI with a loopback synthetic provider: saved report,
exact original quotation/location, captured requested/returned model identity,
retained output and cached retry without another completion. Separately verify
the packaged desktop private handoff and installed-device focus/account behavior.
A direct CLI pass cannot establish that desktop transport.

The bounded `source-aware-report` helper now passes in the actual frozen CLIs
on all three platforms at e5eb093/run43776461463. Downloaded reports confirm saved
originals/quote location, distinct requested/returned models, retained read and
cached retry with one synthetic completion. This closes the named CLI gate only.
The source verifier/helper43 pass44.9s; desktop handoff, live provider/device,
reviewed retained-result application and pending-completion GUI gates remain.

A bounded local download stopped after45s with an incomplete ZIP; it supplies no
additional runtime evidence. Preserve the successful CI candidate rather than
rebuild unchanged source to work around a download. Physical devices, deployment,
runtime adoption and remaining recovery/authority gates are still open.


### Reviewed retained-result application (source)

The same-workspace desktop action now prepares existing native/local import,
asks before writing and preserves historical metadata, current goals and older
report versions. Source fixtures cover result equality, no extra AI, stale-target
refusal, repeat/nonreactivation, cancellation and close/drain. The88595d3 native
candidate predates this action; a passing old packaged report cannot certify it.

Interrupted native activation has the existing complete_pending backend. The
report reader now exposes Finish saved report for both first publication and an
updated pending version. Source fixtures prove close/reopen and local completion
without new AI or operation versions. Frozen/installed/device verification remains
required before closing the offline restart gate. Detached owner remapping, frozen/installed
review flow, physical devices and hosted operation remain separate requirements.
