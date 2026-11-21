# Mac v0.5 acceptance

## Start here on Apple Silicon

Use build **5a7c8bc** on both devices for a paired installation test.

| Device | Download |
|---|---|
| Windows x64 | [Windows installer](https://github.com/puddings-world/Paperfact/actions/runs/44879419382/artifacts/14697239521) |
| Apple Silicon Mac | [Mac disk image](https://github.com/puddings-world/Paperfact/actions/runs/44879419382/artifacts/14696938768) |

Extract the downloaded ZIP on each device, install the enclosed app and compare the build IDs before syncing. [The workflow](https://github.com/puddings-world/Paperfact/actions/runs/44879419382) passed packaged research checks on Windows, macOS and Linux. Real account and physical device checks follow below.

Follow [the desktop-to-laptop setup](../../README.md#sync-a-desktop-and-laptop-v05-preview) in disposable workspaces. Open a received guide on the Mac with PDF sync disabled, disconnect, then reopen the guide. Enable PDF sync on both devices and reconnect to test original transfer separately. Record both build IDs and the first failing step when reporting a difference. Installed Windows/Mac round-trip and sleep/wake with personal Drive still need physical acceptance.

## Exchange saved deep explanations

Use disposable workspaces on both machines and the same v6-capable build.
The first published explanation upgrades the shared directory to v6.

1. Select the same test list on Windows and Mac and enable explanation sync on
   both. Use two different papers with existing saved explanations, one per device.
2. Sync Windows, Mac, then Windows. Open each paper offline and compare its saved
   explanation with the original. Reading a received explanation needs no AI call.
3. On a build with the reader editor, open a saved explanation, click **編輯講解**, change a sentence and click **儲存講解**. Sync both devices and confirm the edit arrives.
   Then edit the same explanation differently on both devices before syncing.
   Open **Compare conflicting guides** on the device reporting the conflict. Verify the common text and both edits. Choose **Decide later** and confirm both survive. Reopen the comparison, choose one version, sync that device and then its peer, and check both show your choice.
4. Deselect the list and confirm subsequent edits do not transfer.

## Exchange original PDFs between readers

[Download the 9d995e8 Apple Silicon test package](https://github.com/puddings-world/Paperfact/actions/runs/44872907556/artifacts/14695051678).
The [macOS build and packaged acceptance](https://github.com/puddings-world/Paperfact/actions/runs/44872907556) passed.
Use the same original-sync candidate on every device that opens the private
Drive directory. Publishing the first PDF upgrades that directory to v5.
Use disposable workspaces and a test list with two different papers.

1. Add a readable PDF to the first paper on Windows and a different PDF to the
   second paper on Mac. Select the same list on both devices. Highlight it and
   enable **Allow PDF sync for this list** on each device.
2. Sync Windows, Mac, then Windows. Open both papers in each reader and compare
   the first pages. Disconnect the network, reopen the readers and check again.
3. In the disposable workspace only, replace a local PDF with a different valid
   PDF. Sync that device. Expect a review message and confirm each device still
   opens its own version. Deselect the list and confirm downloaded PDFs remain.
4. Record both commit IDs, the platform versions and the step that failed if you
   need to export a diagnostic report. Private Drive, real sleep/wake and installed
   hardware remain separate from the automated two-window transfer check.

## Resolve conflicting edits on a selected list

[Download the 01143a3 Apple Silicon candidate](https://github.com/puddings-world/Paperfact/actions/runs/44870894800/artifacts/14693348238).
Use this build or later on both devices. The Mac build and packaged workflow
passed in [run 44870894800](https://github.com/puddings-world/Paperfact/actions/runs/44870894800).
A physical two-device test with Google Drive is still pending.

1. Select the same test list on Windows and Mac. Enable notes for that list on
   both devices. If the previous grant covered new cards only, switch it off
   and on to enable edits. Sync a test card and confirm both devices see it.
2. Go offline on both devices and edit the same card differently. Add an
   unrelated card. Reconnect and sync Windows, Mac, then Windows. Verify the
   unrelated card travels and the conflicting copies keep their own text.
3. On the device reporting the conflict, open personal Drive settings, select
   the list and choose **Compare conflicting notes**. Check the paper title,
   card number, original shared text and both edits. **Decide later** keeps the
   conflict. Choose a version and sync again on both devices to verify it
   appears on both. A changed version requires a fresh comparison.
4. Transfer original PDFs and deep analyses with a research package for this
   candidate. Capture both build IDs and any failing step in a diagnostic report.

## New notes on a selected list

[Download the 566b8af Apple Silicon DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/44868532304/artifacts/14692799162).
DMG SHA-256: `390cd9a20a2c38583098006ec254215c2ebde074aa0522f6eb8078d4c21b7c81`.
The copied app passed three reader launches, second-launch handoff and clean exit.
Use **566b8af** or later on both machines. The first shared note upgrades the
account's private library directory to v4. Use a disposable Google account for
a trial if another device on your usual account still uses a v3 reader.

1. With bibliography sync already working, open personal Drive settings on each
   desktop. Highlight the same saved list. Turn on **Sync notes for this list**.
   Confirm on each device and enable session background sync (or use manual sync).
2. Close settings. On Windows add a new paper note anchored to a passage. On
   Mac add another card to the same paper. After a Windows/Mac/Windows exchange,
   verify both cards appear once on both machines. Verify the page and position
   with matching original PDFs; transfer the PDF separately with a list package.
3. Create a note on a paper that belongs only to an unselected list. It should
   stay local. Sync twice more and confirm that the shared cards stay single.
4. In this disposable workspace, disconnect both computers and edit the same
   shared card differently. After reconnecting, expect a review message and
   verify each local edit survives. This build does not merge those card edits.
5. Disable notes on the Mac, or deselect and save the list. Existing cards should
   remain readable there. Reselecting the list requires a fresh note opt-in.

## Background exchange with settings closed

[Download the 0a06ab1 Apple Silicon DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/44866074184/artifacts/14692485781).
The copied app passed three native reader launches after DMG detach. Image SHA-256:
`a09a93f50524e1f488db9aef1e9b18fa0d9f02f0add031f59620f014f05695b9`.
Use commit **0a06ab1** on both computers. Start with disposable workspaces,
one shared test account and one saved test list containing a single paper.

1. In personal Drive sync on each desktop, enable **Sync saved lists while
   Paperfact is open**, then close settings and leave both readers open.
2. Disconnect both computers. Add a different paper to the selected list on
   each while offline. Create a second local list on Windows. Reconnect without
   clicking Save or Sync. Let both background workers finish. A successful
   pass normally schedules the next check in 30 seconds; offline retries back
   off to five minutes. Check the reader on both devices for all three papers.
3. Reopen settings on Mac and disable background sync. Add a paper on Windows.
   Sign in again on Mac to inspect the directory: the private Windows list
   name should be absent. The new paper should arrive only after explicitly
   syncing or enabling background sync and closing settings again.
4. Restart Paperfact and confirm session-only sync is off. Sign in and opt in
   again. Record both build IDs, whether each device resumed, and how long
   convergence took. If sync pauses, open settings and use **Sync saved lists
   now** after signing in to inspect per-list review messages.

The Windows synthetic two-window journey uses the real Qt login/selection
buttons, timer events and separate SQLite databases against an in-memory Drive.
It verifies ordinary list convergence and private-name exclusion. Physical
network outages, Google consent and Mac sleep/wake still need device testing.

## Sync saved lists on Apple Silicon

[Download the 3ab306e Apple Silicon DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/44864991557/artifacts/14691935547).
DMG SHA-256: `bbc7d0586e025ac1d3d6ff82a1405055e241ca1a1148be96d20c47cca42bf449`.
The native runner opened the reader three times from the copied app after detaching
the image. Gatekeeper quarantine, notarization and upgrading an installed app
remain physical-device checks.
Download the `build-macos` artifact, unzip it, open its DMG and copy Paperfact.app to Applications.
Use a disposable workspace on each desktop and the same test Google account.

1. On Windows, create a test list with one paper. Sign in to personal Drive sync
   and save the list selection. On the Mac, select that list and save once.
2. Create a second, private list on Windows. While offline, add a different paper
   to the original list on each desktop. Reconnect both devices.
3. Click **Sync saved lists now** on Windows, then Mac, then Windows. Both readers
   should show the three original-list papers. Sync once more to check the count
   stays at three. The new private list name should be absent from the Mac directory.
4. On the Mac, change a checkbox. Immediate sync should remain disabled until
   you restore the saved selection or save the new choice. Deselect and save;
   the Mac should keep the papers it already received.

Record both commit IDs and the first failed step. Notes, analysis and PDF transfer
through this checklist, continuous background exchange, and physical-device
acceptance are still open. To take these materials offline now, use a list package.

## Add papers on both desktops

[Download the Apple Silicon DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/44863450300/artifacts/14690692504).
The arm64 runner launched the copied app three times. Use **05cdd9b** on both devices. First receive a disposable list with one paper
using the setup below. Disconnect both devices. Add a different paper to that
same list on each device, and mark the original paper read on the Mac.
Reconnect and save the device selection on Windows, then Mac, then Windows.
Each list should now have the same three papers. Save again on both; the count
should stay at three and the Mac read mark should remain. Concurrent appends
can retain different local order. Existing paper metadata edits, removals,
paper notes and PDFs remain outside this specific exchange.

## Selected bibliographies in the ordinary reader

[Download the Apple Silicon DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/44862445247/artifacts/14690378158).
The native report records clean 0d127b4, execution from the copied DMG app,
three reader launches and four preserved synthetic research files.
Physical devices and actual Google authorization still require acceptance.

Use source **0d127b4** on both desktops. The private Drive directory gains
a v3 record when a bibliography is published. Earlier readers can reject
the upgraded directory. For an isolated trial use a test Google account and
a disposable local workspace on each device.

1. Create two lists on Windows. Add different papers to each; put two papers
   in the list you will take. Sign in to Drive and save both selections.
2. On the Mac sign in to the same account. Select just the list you will take
   and save. Open it in the ordinary reader. Check both titles and their order.
   The other list may appear in the directory; its papers should stay off the Mac.
3. On the Mac mark one paper read. Leave the Mac Drive settings open. On Windows
   append another paper and save the selection. Save the selection on the Mac.
   The third title should appear after the first two; the read mark should remain.
4. Repeat the save. Confirm no extra memberships. Uncheck the list and save.
   Previously received local papers should remain available.
5. In a disposable second Mac workspace, pre-create a paper with the same DOI
   as a later incoming paper. Save the selection and confirm the review label.
   Check the local paper and notes survived and no partial batch was applied.

Save triggers transfer. Source appends are supported; later reorders, deletions
and receiver-side edits do not yet propagate. Use a research package for notes,
analysis and PDF originals. Record the two source revisions and the first failed
step for any physical-device report.

## Per-device list selection candidate

Source **fe82ae9**, [Mac build 44860029456](https://github.com/puddings-world/Paperfact/actions/runs/44860029456).
Use a separate test workspace on each device. Check the source revision in both apps.

1. In an ordinary desktop workspace create two disposable named lists. Open Drive
   settings, sign in, select both lists, and save the device selection.
2. On the Mac, sign in to the same Google account. Verify that both names appear.
   Select only the second list and save. Verify its name and description in the
   Mac reader and confirm the first list was not imported.
3. Rename the selected list on the desktop and edit its description on the Mac.
   Save the Mac selection, then the desktop selection, then the Mac selection.
   Both devices should show the new name and description.
4. Change the same description to different text on both devices. Save on the
   first device, then on the second. Verify the conflict is reported and that
   each device retains its version. Record the app revision and operation order.
5. Uncheck the list on the Mac, save, and verify that its existing local data
   and the desktop's selection are retained.

This checklist exercises list details when the device selection is saved.
Paper membership, notes and PDFs in the ordinary library still need scoped
replication. Use a research package for an offline copy of those materials.
The separate-workspace pilot below has its own enrollment and content checks.

## Personal Drive candidate: desktop to Mac

Drive candidate source: **052d9abff145317014c8321ac6eb454f70823160**.
[Mac-only build44134098189](https://github.com/puddings-world/Paperfact/actions/runs/44134098189)
**Succeeded.** Download the [Apple Silicon DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/44134098189/artifacts/14351978610).
Extract the installer ZIP, open the DMG and confirm source **052d9ab** in the app.
The job waited about 10 minutes for a runner, then took 7m03s. No public release
or auto-update was published. Keep the existing daily app/data until device acceptance.

The downloaded provenance ZIP was independently SHA-256 matched. Its report
confirms clean source, arm64, mounted/copied/verified/detached DMG, workflow from
the copy, three reader launches, foreground activation, four exact research
files, package retry/re-export and all 15 named sync-protocol outcomes.
Mac source selections passed critical14, first-enrollment1, authority54 and
Drive24 (five warnings per phase). Those fixture checks include synthetic
providers; they do not prove real Drive login or native Keychain behavior.
The native Drive dialog screenshot was also downloaded/hash-matched and viewed.
The 280 MB installer ZIP itself was not downloaded on the source workstation.
The older 66855cc download below has package transfer only.

1. Desktop: open the matching candidate, click the bottom-right sync button, sign
   in to Google, select the lists to take, and choose **Sync this workspace**.
   Review the upload consent.
   First enrollment prepares a separate copy/backup, then opens the new reader.
2. Wait for automatic sync to finish pending metadata/files in that reader.
3. Mac: open the matching candidate, click sync, sign in to the same Google account,
   select the workspace and choose **Open selected Drive workspace**.
4. In the new Mac reader verify a note, analysis and PDF. Edit a note offline,
   quit/reopen, reconnect and confirm the saved edit reaches the desktop.
5. Test a simultaneous edit on both devices; both versions must remain for review.
   Check offline preparation before taking the laptop out.

Each device keeps its Google/AI authorization. List sharing still uses a reviewed
package/link, not sharing the private workspace folder. The app must be open to sync.
A fixture pass is not physical-device acceptance.

## Start reading on your Mac

1. Download the **Apple Silicon Mac** artifact from the latest tested table below.
   Unzip this installer download and open the DMG. Keep the daily app; use the
   [separate test app and data folder](#prepare-a-separate-test-app).
2. On the desktop, open the list and choose **Export this list** (or
   **Research data > Export current list package**). Include PDFs and personal
   notes/Q&A/manual highlights. Check the result for missing original PDFs.
3. Transfer the research-package ZIP to the Mac. **Keep this ZIP zipped.** On the
   Mac list overview choose **Import research package**, inspect the preview and
   confirm. Existing receiver research is preserved unless replacement is chosen.
4. Open a saved analysis, a note, its PDF and an editable deck. Reading saved work
   needs no AI login. Before leaving, disconnect the Mac and reopen those items;
   a successful import alone does not prove every original was included.

The installer ZIP and the research ZIP have different purposes: extract the first,
import the second. This workflow transfers one snapshot, not a continuous sync
connection. To bring Mac edits back, export that list again and review its import
on the desktop; package import is not an automatic three-way merge. See
[sharing](../sharing.md#move-your-own-research-to-another-computer).

For a problem, record the bottom-right version/source, macOS version, exact action
and expected/actual result. Use **Diagnostics and support** to preview/export a
report, then decide where to send it. Do not send the whole research folder.
The [full acceptance record](#acceptance-record) below tracks release/device tests;
service-dependent cases stay **not run** until a reachable test service exists.

## Previous tested downloads (before personal Drive)

Latest Apple Silicon Mac: clean **66855cc9d12eeb8b9c0f163019cf3f7f9efe7d01**,
version `0.5.0.dev`, beta-candidate. [Run43881479241](https://github.com/puddings-world/Paperfact/actions/runs/43881479241)
passed in **5m35s**. No tag, release or auto-update was created.

| Platform | Exact source | Download | Native job duration |
|---|---|---|---|
| Apple Silicon Mac | `66855cc` | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43881479241/artifacts/14232986961) | 5m35s |
| Windows x64 | `30b5776` | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43859467437/artifacts/14222404200) | 8m06s |
| Linux x86-64 | `30b5776` | [AppImage artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43859467437/artifacts/14222013278) | 3m40s |

The Windows/Linux installers are older; they have not been rebuilt at66855cc.
The local integrated source is66855cc. Record the actual source on each machine;
a shared `0.5.0.dev` label does not mean identical code.

The Mac includes cancellable exact-original supply, an explicit pause for unreadable
newer research formats, and claim-card enrollment that preserves edited notes and
archives local regeneration controls without receiver-side deletion authority.
The native report confirms a read-only DMG mount/copy/verification/detach, three
reader starts, foreground activation and all15 named sync-protocol outcomes.
The small provenance ZIP was independently downloaded and hash-matched; the large
installer ZIP was not downloaded on this source workstation.

The Mac source stages pass core14, first-enrollment1 and selected54 cases, with
five warnings per phase and no failures. Their check totals are7.0s,3.3s and11.0s;
the full5m35s includes dependency preparation, packaging, frozen-app operations
and artifact upload. These are selected checks, not the historical full suite.
Physical keyboard/IME, native credential prompts, quarantine/notarization, older
installed upgrades, full dialogs and Windows/Mac/phone convergence remain open.
Hosted sync is undeployed; use the list-package handoff at the top of this page.
[Detailed identities and evidence](continuation-20261112.md#2026-11-16-66855cc-mac-candidate-and-readable-acceptance-guide).

## Previous common-platform candidate: 30b5776

All native candidates share clean source
`30b577601276fbccffa03b293f381d6d1a47f500`, version `0.5.0.dev`, beta-candidate.
[Run43859467437](https://github.com/puddings-world/Paperfact/actions/runs/43859467437)
succeeded; draft/release was skipped. Check source **30b5776** in support/version
information. Keep the existing isolated test-data directory and close an older
test app before opening this one. These are test installers, not an auto-update.

| Platform | Download | Native job duration |
|---|---|---|
| Apple Silicon Mac | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43859467437/artifacts/14223445465) | 6m35s |
| Windows x64 | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43859467437/artifacts/14222404200) | 8m06s |
| Linux x86-64 | [AppImage artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43859467437/artifacts/14222013278) | 3m40s |

Mac now mounts the actual generated DMG read-only, copies and verifies the app,
detaches that volume, then runs the existing frozen research workflow from the
copy. Downloaded/hash-matched provenance proves the exact clean source/arm64 host,
all five DMG stages, all15 sync flags, three reader launches and Launch Services
foreground. Its screenshot was visually inspected for Chinese, formula and code.
Windows isolated install/reinstall/uninstall preserves research; Linux AppImage
integration passes. All three source phases pass critical14, first-sync1 and
selected54 cases. Mac reports five warnings per phase, no failures.

All small native provenance ZIPs were independently downloaded/hash-matched;
large installer ZIPs were not downloaded locally. Quarantine/notarization, older
installed-binary upgrade, complete new GUI/live accounts/native vaults/IME and
physical two-device/phone acceptance remain open. Mobile artifact14223076072
was hash-matched and its54 assets/3983781 bytes verified in1.640s under the existing
CPU governor. Its content identity is unchanged; HTTPS/PWA deployment remains open.
Hosted continuous sync is undeployed: use the snapshot handoff above.
[Detailed identities and evidence](continuation-20261112.md#2026-11-16-30b5776-actual-dmg-copy-and-three-platform-candidates).

## Historical candidates

Older downloads, hashes and superseded failures remain in the
[immutable candidate catalogue at66855cc](https://github.com/puddings-world/Paperfact/blob/66855cc9d12eeb8b9c0f163019cf3f7f9efe7d01/docs/testing/mac-acceptance-0.5.md)
and the [dated evidence ledger](continuation-20261112.md). They are not current
installation instructions or proof for a newer candidate.

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
| `mac-dmg-preflight`, `mac-dmg-mount`, `mac-dmg-copy`, `mac-dmg-verify`, `mac-dmg-detach` | Newer verifier source: exact CI artifact/owned mount, complete copied app closure, and detach before the shared workflow uses the copy; not yet observed for d14c512 |

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
