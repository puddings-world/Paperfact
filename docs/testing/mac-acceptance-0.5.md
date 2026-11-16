# Mac v0.5 acceptance

## Latest common-platform test build: 0a64ec7

[All-platform run43784461643](https://github.com/puddings-world/Paperfact/actions/runs/43784461643) passes from clean
`0a64ec7ed8c2aec8c435c12f285eae36d80d5d61`, version `0.5.0.dev`, beta-candidate.
Mac arm64:6m15s; Windows x64:7m40s; Linux x86-64:3m36s. All three
small provenance ZIPs were downloaded, independently hash-checked and inspected.

| Download | Artifact contents |
|---|---|
| [Apple Silicon Mac](https://github.com/puddings-world/Paperfact/actions/runs/43784461643/artifacts/14189674380) | build-macos |
| [Windows x64](https://github.com/puddings-world/Paperfact/actions/runs/43784461643/artifacts/14189183704) | build-windows |
| [Linux x86-64](https://github.com/puddings-world/Paperfact/actions/runs/43784461643/artifacts/14189797058) | build-linux |
| [Synthetic research fixture](https://github.com/puddings-world/Paperfact/actions/runs/43784461643/artifacts/14189893569) | research-fixture-macos |
| [Mac report](https://github.com/puddings-world/Paperfact/actions/runs/43784461643/artifacts/14190002815) | provenance-macos |

The candidate includes local authority v3 control checkpoints and offline-original
cleanup protection. Each OS passes critical14, first-sync preservation1 and
source authority/retention14. Actual frozen CLI report acceptance now uses the
production host desktop handoff and a real QProcess: a disabled child disk route
cannot override captured synthetic provider/model settings. Original/PDF/quote
identity, retained read and cached retry preserve exactly one model completion.
Windows additionally passes isolated install/reinstall/uninstall and research
preservation; Mac passes three reader launches and foreground; Linux passes
AppImage integration. This is not every frozen GUI dialog, physical two-device
sync, native vault/account, old installed-binary upgrade or hosted acceptance.
No release/tag or production deployment was created. Check source **0a64ec7**
when using the separate-app launch instructions below.

GitHub-reported installer ZIP metadata (installer payloads not downloaded here):

| Platform | ZIP bytes | ZIP SHA-256 |
|---|---:|---|
| macos | 279114356 | `e4370c5195f2357087996fd74c51d257d56bcd59f8f399fc6a563544004019a9` |
| windows | 184672050 | `a6289da8c804995adc6967881a9725f2f944d9c61c4b319e1f26f40eb14376ce` |
| linux | 282627999 | `0330e09f4b783331e094dd8d426d2b229261e3fc5dd9d939233306be5ad71e76` |

## Previous Apple Silicon test build: 2fb6923

[Mac run43774457806](https://github.com/puddings-world/Paperfact/actions/runs/43774457806)
passes in6m03s, from clean `2fb69238377a4a43d8cccae28eef78820494bf6a`,
version `0.5.0.dev`, beta-candidate channel. This is newer than the common-platform
baseline below; Windows/Linux have not been rebuilt at this exact source.

| Download | Purpose |
|---|---|
| [Mac DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43774457806/artifacts/14184844475) | Extract the ZIP, open the DMG, and copy the test app into a separate folder |
| [Synthetic research package](https://github.com/puddings-world/Paperfact/actions/runs/43774457806/artifacts/14185583010) | Import `original.zip` into the isolated test workspace |
| [Build identity and acceptance report](https://github.com/puddings-world/Paperfact/actions/runs/43774457806/artifacts/14185706911) | Match build2fb6923 when reporting a problem |
| [Actual Mac screenshots](https://github.com/puddings-world/Paperfact/actions/runs/43774457806/artifacts/14185632796) | Compare the saved reading page, list, notes and slide layout |

GitHub sign-in may be required. The DMG artifact ZIP is279,157,494bytes;
GitHub-reported ZIP SHA-256 is
`9d36a2e95a15b7383d2c8d28f8f9910480a3ca4ce62f3e57a1def2ca2ab23472`.
This is not an independently downloaded DMG payload hash. The small provenance
and screenshot ZIPs were downloaded and their hashes independently matched.
The report confirms clean source, arm64, three reader launches, foreground
activation, four research files preserved, CLI/MCP retry/restart and all11 packaged
sync protocol checks. The reading screenshot was inspected: Chinese explanation,
formula and pseudocode render with actual text, resolving the preceding blank-page
gate. Empty-to-content now loads directly; populated views retain incremental
updates. The screenshot tool keeps its exact-page, loaded-font and nonblank checks.

Start with the separate-app commands below. Verify build2fb6923, import the
synthetic package, read its PDF/explanation offline, save/reopen a note, then
export/import the list package. Use your own AI only for explicit account checks.
The new report review/completion flows have source/widget coverage; the standard
frozen report does not automate every new dialog. Physical M01-M21, real accounts,
old installed-binary upgrades, hosted sync and phone durability remain not run.
No public release/tag or service deployment was created.

## Previous common-platform candidate: 88595d3

Built from clean `88595d332eaf36d911e3d15521e8d3f07ae976ca`, version
`0.5.0.dev`, beta-candidate channel:
[all-platform run43754647228](https://github.com/puddings-world/Paperfact/actions/runs/43754647228).
Mac arm64 passed5m48s, Windows7m44s, Linux2m25s. All are the same source.

- [Mac DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43754647228/artifacts/14177314884):
  279,577,751 bytes; GitHub ZIP SHA-256
  `9180dfaf09dfbfc2e33777197ee938bfb294adcb81ac56e1cd296a3a975a5acf`.
- [Synthetic research fixture](https://github.com/puddings-world/Paperfact/actions/runs/43754647228/artifacts/14178077416).
- [Mac provenance/report](https://github.com/puddings-world/Paperfact/actions/runs/43754647228/artifacts/14177654011).
- [Windows installer ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43754647228/artifacts/14178142192).
- [Linux AppImage ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43754647228/artifacts/14177398894).

The small provenance/reports were downloaded and inspected: clean commit matches,
all pass. Mac includes three native reader launches and foreground activation;
Windows includes isolated install/reinstall/uninstall with research preserved.
Reported ZIP hashes are GitHub metadata, not independently downloaded installer
payload hashes. No public release/tag was created; the draft job was skipped.

This candidate includes the connected **Report & sources ? Generate with sources**
desktop/private-CLI flow, captured research goal/model, retained completed output,
read-only retained-result CLI and safe refresh/reopening. Its generation flow uses
simulated model/IPC evidence; the standard frozen acceptance is not proof that
your live provider account is authorized. Use a separate workspace/data copy and
the steps below. Do not point development at the only copy of your research.

Verify About/build info shows88595d3, import the synthetic fixture, read its PDF
and notes offline, then explicitly select your own AI and try the report action.
Confirm progress, one job after repeated clicks, source inspection and reopen.
Report actual results with build ID, platform and the app's reviewed diagnostic
export. Installed-device, physical-mobile, hosted sync and runtime-adoption gates
remain open; downloading this app does not deploy a sync service.

## Historical candidates

Historical 2026-11-15 Apple Silicon candidate:
[3b344c7 / run43714643158](https://github.com/puddings-world/Paperfact/actions/runs/43714643158),
clean `3b344c77cbea449f22767f35d5475b6ae2672bfc`, version `0.5.0.dev`.
Mac passed in5m30s; Linux passed in2m55s. The original Windows attempt failed
Git archive line-ending preflight; the corrected Windows-only follow-up below
passes. These are separate exact source commits, not a single all-platform run.
No public release was created.

Exact Mac downloads (GitHub sign-in may be required):

- [build-macos: DMG inside](https://github.com/puddings-world/Paperfact/actions/runs/43714643158/artifacts/14162371150),
  artifact ZIP279,874,743 bytes; GitHub-reported ZIP SHA-256
  `86b49f3cf499329141a581778dc4c2e4a5ba71ff77a09201836951dbad76eaa8`.
- [research-fixture-macos: synthetic original.zip](https://github.com/puddings-world/Paperfact/actions/runs/43714643158/artifacts/14161729979),
  GitHub-reported artifact ZIP SHA-256
  `cc42e04352baf05ca8786028e6b93077d64f07c4c0ddd7c5b235ab86c1aa516a`.
- [provenance-macos: build identity/report](https://github.com/puddings-world/Paperfact/actions/runs/43714643158/artifacts/14162615645).
- [acceptance-macos: synthetic logs](https://github.com/puddings-world/Paperfact/actions/runs/43714643158/artifacts/14161744952).

The provenance/report were downloaded and inspected; the DMG was not installed
on a physical Mac here. Archive hashes are not hashes of contained installers.
The prior355382c/run43705488673 remains the last all-platform passing candidate.
The new [Windows setup artifact](https://github.com/puddings-world/Paperfact/actions/runs/43715636579/artifacts/14163025642)
is clean4ee34278c463a25f6b40fc64e01b2286187c3c5e from
[run43715636579](https://github.com/puddings-world/Paperfact/actions/runs/43715636579),
passing7m34s. It has the same app runtime as3b344c7 plus the archive recipe,
regression and delivery-doc corrections. GitHub artifact ZIP184,308,740 bytes,
SHA-256 `ccedd3f1135bdfa5ecc42aca43bf0282c2698f45e671a3ce43d475eac86e5e08`.
Its separate setup payload SHA-256 is
`15c308826c35e64bc990d3d1541cd473864088d7a36cf5b00bf65376a27f6595`.
Both provenance reports were inspected. Use these exact identities in reports.

Packaged acceptance preserves four PDFs, verifies three reader starts/foreground,
same-workspace handoff and38 CLI/MCP tools with retry/restart. Eleven sync protocol
checks pass, including official-service refusal of unverified mutations, exact
retry and retained verified history after restart. This bundle includes explicit
legacy-history review and default-No adoption in the existing desktop dialog;
that dialog's physical Mac interaction remains untested.

The new old-source probe uses pinned0.4.3 writers to create synthetic research,
then the actual frozen CLI exports before/after schema initialization. All seven
old table families, PDF/deck bytes, positioned Unicode note, Q&A, highlight and
hand-edited deck survive. This is source-format preservation, **not old-installer
or GUI upgrade acceptance**. No live research or credentials were used.

Matching mobile shell v31 content ID:
`8b6f4eac84eeedabd025cfa2237cc18c3312a16834405313028e6f7263493229`.
The downloaded50-file artifact passes its existing hash verifier in0.219s; its
content ID matches the previously accepted offline Chromium artifact. This run
does not establish new Safari/physical-phone acceptance or deploy the PWA.

Keep the daily app/data unchanged. This experimental bundle does not auto-update
or provision a service. Use the separate test folder below. Physical M01-M21,
native credential prompts, input/IME, installed upgrade, hosted sync and durable
control-history/distributed fencing remain open. No public release was created.

## Prepare a separate test app

Keep the daily installation. Put the candidate bundle in a separate folder, such
as `~/Applications/Paperfact-v05-test/Paperfact.app`. Do not use the old
`make-app-mac.sh` launcher for acceptance: it points at a mutable checkout and
replaces its launcher destination. Obtain a macOS arm64 bundle built from the
accepted candidate; Windows cannot build or certify its native launch behavior.

On the Mac, first close other Paperfact windows. In Terminal:

```sh
app="$HOME/Applications/Paperfact-v05-test/Paperfact.app"
test_data="$(mktemp -d "$HOME/Desktop/Paperfact-v05-test.XXXXXX")"
"$app/Contents/MacOS/paperfact-cli" --version
PAPERFACT_DATA="$test_data" "$app/Contents/MacOS/Paperfact"
```

Keep this Terminal session and the generated directory for the whole journey.
Reopen with the same last command; creating another directory would test a new
workspace. Check the displayed workspace location before importing. This isolates
research, not the Mac's system credential store or independently installed AI CLIs.
Use your own account only for the explicit AI checks below.

## Acceptance record

Record `pass`, `fail`, or `not run`, with the exact step and expected/actual result.
No elapsed-time or percentage estimate substitutes for these outcomes.

| ID | Action | Expected result |
|---|---|---|
| M01 | Open, focus, type Traditional Chinese, switch apps, close normally | Dock/foreground activation works; composition and keyboard shortcuts work; no lost input. |
| M02 | Compare Windows/Mac version and candidate identity | Same candidate; arm64 Mac artifact; daily data folder is not selected. |
| M03 | Import a small synthetic research package containing a PDF, note, explanation and editable deck; import again | Saved content matches; repeat import does not duplicate papers or lists. |
| M04 | Open PDF, follow a saved source, edit a note, reopen the app | Correct original is displayed and local edits survive restart. |
| M05 | Export the list and import it into another empty test workspace | PDF and attachments survive; notes, list name and editable slides retain changes. |
| M06 | Sign into your own supported AI connection; select a model | Effective account/model is visible; other machines' credentials were not imported. |
| M07 | In References, select no auto followup, then explicitly test a maximum of one extra call | Chosen bound belongs to that job; repeated clicks create one job; partial content survives. Extra calls occur only if the response is incomplete. Real AI replies are nondeterministic; use fixture tests to prove the exact bound. |
| M08 | Open sync settings, paste this device's private connection record, load it, then verify | The input is masked and cleared after loading; fields identify this device. Loading alone does not connect, save credentials, enroll or upload research. Invalid input preserves the previous connection. |
| M09 | Connect each device with its own credential to the same test workspace/service | Authentication identifies the expected workspace/device; credentials never travel in a package. |
| M10 | On Mac disconnect network, edit `Mac offline note`, close/reopen | Local save survives; UI reports pending/offline, not fully synchronized. |
| M11 | On Windows edit a different note, then reconnect Mac and sync both | Both independent edits appear on both machines without duplicates. |
| M12 | Offline on both machines, edit the same note differently, then reconnect | Neither edit silently disappears; conflict/recovery keeps both versions and resolution converges. |
| M13 | Interrupt sync, reopen, retry; open another paper during background work | Progress can resume, no duplicated records, no result applied to the wrong paper. |
| M14 | Download/pin PDF on Mac, go offline, reopen it | Verified local original opens; a missing attachment is reported accurately. |
| M15 | Preview and export diagnostics after a reproducible failure | Report identifies this build and OS/CPU; preview matches export; upload requires your action. |
| M16 | While joining, test the default-off new-workspace automatic-sync option, then explicitly enable it and open/reopen that same new folder | Unchecked: no automatic reconnect/upload. Checked: the exact new device reauthenticates and syncs after opening/restart; local edits reach the peer. The original workspace remains unchanged. Disable startup sync and reopen to confirm it stops. Loading or pairing alone grants no startup permission. |
| M17 | Interrupt a large attachment transfer, reconnect, then run the offline file check | Pending/retrying file status remains distinct from metadata caught up; retry yields exact verified bytes. Disconnect only after offline verification passes, then reopen the PDF and editable deck. |
| M18 | From Windows, confirm revocation of the Mac test device; attempt another Mac sync | Future remote access is rejected; locally downloaded research and unsent edits remain. Do not reuse the revoked device ID or delete its outbox. |
| M19 | Create a complete recovery backup, restore into a new detached test directory, inspect both conflict variants and files | Source workspace remains unchanged; restored content and exact attachments are retained. Restore does not reconnect or reactivate the original device identity. A missing required file blocks complete backup rather than silently omitting it. |
| M20 | On a physical phone, open the private PWA, cache selected research, go offline, add a uniquely labeled note, close/reopen, reconnect | Cached research and saved note survive; explicit reconnect delivers the note once to Windows and Mac. Mobile background execution is not required. Test iOS and Android separately; an untested platform remains not run. |
| M21 | Import a dedicated synthetic package with a saved Lineage and its selected originals. Open Research lineage, choose Check all originals, inspect a quotation, cancel/retry and close during work | Source counts and per-quotation findings appear without AI. Exact-original viewing leaves the main PDF/drafts unchanged. Missing originals remain unchecked; stale/cancelled work cannot fill another selection. The frozen verifier does not automate this UI journey; record actual packaged Mac results and repeat on Windows. |


M09–M14 require a deployed, mutually reachable test service and two separately
issued device credentials. `127.0.0.1` on the Mac is the Mac itself. Package
import/export tests do not establish live synchronization. No hosted service is
provisioned by this document. Stop a journey on data loss and retain its test
workspace privately for diagnosis; do not delete/reinitialize to hide a failure.

## Saved startup connection (not run on a physical Mac)

After M09, explicitly enable **Reconnect and sync when this workspace opens on
this device**. Confirm the Keychain prompt identifies Paperfact, close the app,
then reopen the same test workspace. It must authenticate the same device and
sync without re-entering credentials. Repeat offline: local edits must remain
usable and reconnect must back off rather than repeatedly prompting. Clear the
option, close/reopen, and verify there is no automatic connection or upload.
Import or restore into another test database: that database must not inherit the
preference. Record actual Keychain denial and retry separately from fixture tests.

## Shared-service and recovery prerequisites

For M09-M14 and M16-M20, use a disposable workspace and a mutually reachable
service with separate device credentials. Provision a replacement test identity
before M18 so revocation does not prevent later cases. Never paste connection
records into the acceptance report. The [GCP pilot plan](../gcp-sync-pilot-plan.md)
is a proposal, not a deployed endpoint; its public-edge, backup and restore gates
must pass before treating that service as usable away from home.

M19 tests a detached client research backup through the app's recovery actions;
see [the recovery contract](../sync-recovery.md). It does not test restoration of
the cloud authority. Record cloud authority disaster recovery separately, including
fresh service/workspace identity when restoring older history; never reset a
client cursor to disguise lost server history.

For each run, record device/OS, artifact hash, candidate commit, case ID,
pass/fail/not run, expected/actual result and reviewed diagnostic filename.
Keep the Windows/Mac/phone records together. A passing automated test or a package
import cannot fill a physical-device result. Stop on data loss and preserve the
isolated workspace privately for diagnosis.

## Automated packaged-app checks (maintainer)

From the matching candidate checkout on the Mac, with its development environment
already installed and the built bundle available:

```sh
run_id="$(date +%Y%m%d-%H%M%S)"
.venv/bin/python scripts/verify_built_app.py   "$HOME/Applications/Paperfact-v05-test/Paperfact.app"   "build/mac-acceptance-$run_id"
```

The output directory must not already exist. The script generates synthetic data
and isolated account/data homes. It checks first use, duplicate import, export,
file fidelity, local CLI/MCP retries and native Launch Services foreground behavior.
The Mac foreground check requires Apple's Swift toolchain. `report.json` is
updated at each check, including failure, timeout or Ctrl+C. Only `status: passed`
and `passed: true` with exit code 0 mean this packaged local journey completed.
`running` is an incomplete record after a crash/kill, not proof a process is still
running. Missing/unwritable reports are not passes. Failure returns exit code 1;
Ctrl+C returns 130. Use a new output directory for every retry; an existing report
is preserved and is never reclassified as the latest attempt.
The closed `paperfact.packaged-acceptance.v1` report records completed checks,
the check where failure was detected, a categorical failure and host OS/architecture.
Its build version comes from the frozen CLI; commit/dirty state come only from
fixed packaged metadata. Unknown identity stays unknown; never substitute the
mutable checkout identity or omit the candidate artifact hash from the run record.
It contains no raw exception text, command/output, private path or account data.
Review and share `report.json` first; raw local `.log` files require separate
review. Do not send the entire output folder or generated research workspace.
The existing CI still captures its generated fixture logs separately.

| Report check | What it verifies |
|---|---|
| `isolation`, `version`, `doctor`, `first-use` | Separate fixture/account homes, actual frozen version, prerequisites and empty GUI startup |
| `first-use-privacy`, `credential-isolation` | No AI account configuration was created/imported into the fixture |
| `seed`, `share-link`, `share-link-checksum` | Generated research package and exact checksum-bearing sharing link |
| `import`, `import-again`, `reader`, `export` | Import twice, read, export; a duplicate import must not duplicate the list item |
| `lineage-audit`, `lineage-audit-result` | Actual frozen JSON CLI checks the imported synthetic corpus: three originals, five located quotations; no semantic-support claim |
| `file-fidelity`, `research-content` | Exact exported PDF/assets plus saved analysis and membership |
| `local-integration`, `appimage-integration` | Frozen JSON CLI and actual MCP stdio retry/restart behavior; AppImage variant when present |
| `instance-handoff` | Expected workspace endpoint is live; second launch returns while the primary stays open; primary then closes normally (passed for cb6ca66) |
| `sync-protocol` | Packaged CLI service init/issue, authenticated pull, restart, HTTP 428 for the old execution and successful reconnection; only synthetic state |
| `mac-foreground` | Native Launch Services/Cocoa activation through the Swift check |

`timeout` means a child exceeded its bounded limit (normally 90 seconds; the
second-instance launch has a 15-second limit); `missing_file` means a
required executable/tool or generated input was unavailable. `process_failed`
records a nonzero child exit; `background_traceback` or `app_traceback` detects
an error despite apparent process success. Validation/assertion failures stop
the workflow before acceptance. The reported check is where the problem was
detected, not a proven root cause. Keep the fixture privately; use a new output
folder for a retry and compare the actual candidate identities.

This does not run the physical two-device sync journey or real provider login.
Do not claim the full suite passed merely because packaged-app verification passes.

## Synthetic research material

The verifier's `original.zip` contains one list member, a saved explanation and
an explicitly authored synthetic lineage with two context papers, three originals
and five source-pinned quotations. All four packaged PDF files (main reader plus
three lineage originals) must survive import/export byte-for-byte. Generation
metadata says `synthetic-fixture`, with no requested/returned model. No AI,
account, download or private paper is required. The main paper's lineage passages
are on page 2, so M21 also checks source navigation across pages.

Copy `original.zip` to the other test machine and import it in the separate
candidate workspace. Do not copy account homes or the whole verifier directory.
Record the ZIP SHA-256 alongside candidate identity. The automated frozen CLI
check does not prove the GUI behavior in M21; record that result separately.

To generate the same kind of material without building an installer, run from a
configured source checkout. These commands bind only the child process to a new
empty fixture workspace; they do not change your app's data-location setting.
Choose a new output filename on a repeat run; existing outputs/data are refused.

Windows PowerShell:

```powershell
$fixtureData = Join-Path $env:TEMP ("paperfact-acceptance-" + [guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe -c "import os,sys; os.environ['PAPERFACT_DATA']=sys.argv[1]; sys.path.insert(0,'scripts'); from demo_workspace import acceptance_package; from pathlib import Path; acceptance_package(Path(sys.argv[2]))" $fixtureData (Join-Path $PWD "Paperfact-synthetic-research.zip")
```

macOS/Linux:

```sh
fixture_data="$(mktemp -d)"
.venv/bin/python -c 'import os,sys; os.environ["PAPERFACT_DATA"]=sys.argv[1]; sys.path.insert(0,"scripts"); from demo_workspace import acceptance_package; from pathlib import Path; acceptance_package(Path(sys.argv[2]))' "$fixture_data" "$PWD/Paperfact-synthetic-research.zip"
```

Success produces a validated ZIP at the named path. The helper API is
`scripts.demo_workspace.acceptance_package(destination) -> dict` (the manifest).
It requires an explicit absolute `PAPERFACT_DATA` matching the bound empty
workspace and a new absolute output path. It constructs portable fixture data;
it does not grant sender-native source ownership. Real receiver validation and
observed publication create the imported source context.

## Return a useful failure report

Use the candidate's **Diagnostics and support** entry to preview and export.
If its GUI cannot start, use the same Terminal variables:

```sh
PAPERFACT_DATA="$test_data" "$app/Contents/MacOS/paperfact-cli" diagnostics
PAPERFACT_DATA="$test_data" "$app/Contents/MacOS/paperfact-cli" diagnostics   --output "$HOME/Desktop/Paperfact-diagnostics-$(date +%Y%m%d-%H%M%S).zip"
```

Send the reviewed diagnostic ZIP, M-step ID, candidate version/hash, macOS version,
expected/actual behavior and a redacted screenshot if useful. Review generated
acceptance logs before sharing. Do not publish the whole research workspace,
raw app log, credentials, or private PDFs. Logs can contain earlier failures;
an empty diagnostics report does not prove a frozen UI is healthy.

## Newer source5945820: Mac package not yet available

[Run43771771878](https://github.com/puddings-world/Paperfact/actions/runs/43771771878)
builds source5945820f802bac8462d43dbb56719393b0792088. The Mac authority lifetime
gate now passes, but Screenshots times out on rendered reading page before
packaging. A single Mac-only retry at the identical source,
[run43772183133](https://github.com/puddings-world/Paperfact/actions/runs/43772183133),
fails at the same predicate. This is reproducible CI failure, not an accepted Mac
installer. The screenshot/rich-view/rich-HTML/demo inputs are unchanged from88595d3;
that comparison does not identify the cause. Do not skip rendering acceptance,
extend the timeout without evidence, or label88595d3 as containing newer source.

Local affected HTTP/admin76 and critical14 pass; those results do not certify
Mac rendering. Linux packaging passes; Windows is still running at this record.
The next step is to capture the exact rendered-page identity/readiness/font state
on failure before another retry. No new public release or research-data migration
was performed.
