# Mac v0.5 acceptance

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

## Latest tested downloads: d14c512

All native candidates share clean source
`d14c51253c348b921bfcb823ece22957e969cab7`, version `0.5.0.dev`, beta-candidate.
[Run43851985599](https://github.com/puddings-world/Paperfact/actions/runs/43851985599)
succeeded; draft/release was skipped. Check source **d14c512** in version/support
information. Close an older test app before opening the new one, and keep the
existing isolated test-data directory. These are test installers, not a public
release or automatic update.

| Platform | Download | Native job duration |
|---|---|---|
| Apple Silicon Mac | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14217833669) | 5m59s |
| Windows x64 | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14219496165) | 8m29s |
| Linux x86-64 | [AppImage artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14218331821) | 2m47s |

This candidate combines the previous source-observed PDF/reader/deck transfer
work with reviewed package missing-byte recovery, exact nullable list descriptions,
and saved-research cleanup protection. Preview remains separate from confirmation;
research retained outside a list still protects its declared legacy originals.
Immutable history/conflict/blob garbage collection remains a separate open item.

Every OS passes critical14, first-sync1 and54 selected authority/control/recovery/
offline/original cases. Mac reports five warnings per source phase, no failures.
Small provenance ZIPs for
[Mac](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14218397450),
[Windows](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14219681025)
and [Linux](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14218955314)
were independently downloaded/hash-matched and strictly inspected: exact clean
source/host, passed report and all15 named sync flags. Mac passes three reader
launches plus Launch Services foreground; its downloaded screenshot shows Chinese,
formula and code. Windows isolated install/reinstall/uninstall preserves research;
Linux passes AppImage integration. Large installer ZIPs were not independently
downloaded locally. This is not full new-GUI, live AI/Google/vault/IME, older
installed-binary upgrade or physical two-device/phone acceptance.

The matching [mobile artifact](https://github.com/puddings-world/Paperfact/actions/runs/43851985599/artifacts/14217163768)
was independently downloaded/hash-matched and all54 assets/3983781 bytes, proxy
map and cache identity verified under the existing governor in0.375s. Content ID
remains `5a55483512ff75d5a09b676b865b721e07ce9390f8f882a6f858243400f54246`.
It is built, not deployed HTTPS/PWA or physically accepted on Safari/phones.
Hosted continuous sync remains undeployed; use the snapshot handoff above.
[Detailed hashes and evidence](continuation-20261112.md#2026-11-16-d14c512-three-platform-candidate-acceptance).

## Previous tested downloads: 8252010

All native candidates share clean source
`8252010ad4a0d72fef84e9e1622d0a48b88056ba`, version `0.5.0.dev`, beta-candidate.
[Run43843383556](https://github.com/puddings-world/Paperfact/actions/runs/43843383556)
succeeded; draft/release was skipped. These are test installers, not an automatic
update or public release. Check source **8252010** in version/support information.

| Platform | Download | Native job duration |
|---|---|---|
| Apple Silicon Mac | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14213973245) | 4m09s |
| Windows x64 | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14214746277) | 8m01s |
| Linux x86-64 | [AppImage artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14213464829) | 3m36s |

This candidate includes reader/analysis first-original intake, list PDF preservation,
exact known-original supply without a new version/AI call, and explicit missing
deck/body/image retry. Earlier native replacement, atomic successful-URL publication,
retention guards and mobile storage-protection behavior are retained. A different
PDF remains explicit replacement; corrupt finalized files are never overwritten.

Each OS passes critical14, first-sync1 and53 selected authority/control/recovery/
offline/original cases within the existing budgets. Mac reports five warnings
per source phase, not failures. Small provenance ZIPs for
[Mac](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14214786054),
[Windows](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14214626637)
and [Linux](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14214197426)
were independently downloaded, hash-matched and inspected: exact clean source,
expected host, `passed=true` and all15 packaged sync flags. Large installer ZIPs
were not independently downloaded on the source workstation.

Mac passes three reader launches/foreground activation; its downloaded screenshot
shows Chinese/formula/code. Windows isolated install/reinstall/uninstall preserves
research; Linux passes AppImage integration. Source-format0.4.3 preservation is
not an installed-old-binary upgrade. Full new-action GUI, native vault/IME, live
AI/Google and physical two-device/phone acceptance remain open.

The matching [mobile web artifact](https://github.com/puddings-world/Paperfact/actions/runs/43843383556/artifacts/14214850454)
was downloaded/hash-matched and all54 assets, proxy map and cache identity verified
under the existing governor in0.813s. Its content ID remains
`5a55483512ff75d5a09b676b865b721e07ce9390f8f882a6f858243400f54246`.
It is built, not deployed HTTPS/PWA or physically accepted on Safari/phones.
Hosted continuous sync remains undeployed; use the snapshot handoff above.
Detailed ZIP hashes/counts are in the [continuation ledger](continuation-20261112.md#2026-11-16-8252010-three-platform-candidate-acceptance).

## Previous tested downloads: 2021103

All three native candidates now share clean source
`20211036cea31cc7d0764c28946926870617a7f4`, version `0.5.0.dev`, beta-candidate.
[Run43820427097](https://github.com/puddings-world/Paperfact/actions/runs/43820427097)
succeeded; its release/draft job was skipped. These are test builds, not an
automatic-update offer or a public release.

| Platform | Download | Native job duration |
|---|---|---|
| Apple Silicon Mac | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14203933161) | 5m52s |
| Windows x64 | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14204657506) | 9m09s |
| Linux x86-64 | [AppImage artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14203983233) | 3m32s |

Sign into GitHub to download; extract the ZIP and open its installer. Keep the
existing daily app/data. Follow the separate-app/workspace steps below and check
source **2021103** in version/support information. Export a list research package
on the desktop, include PDFs and personal notes/Q&A, transfer its ZIP, then choose
**Import research package** on the Mac list overview. Import preview preserves
existing receiver research by default. Reading needs no AI login. This is a
snapshot handoff; hosted continuous synchronization is not deployed.

The candidates include source-observed native PDF replacement, first-original
list prefetch with atomic successful URL/outbox/binding/receipt publication,
retention-safe legacy cleanup and explicit mobile origin-storage protection.
Existing legacy files are not automatically migrated. A missing managed original
uses attachment transfer, not a replacement source search. Source tests verify
these new writer paths; the packaged acceptance below is not a full frozen GUI
certificate for every new action.

Each OS passes critical14, first-sync preservation1 and48 named authority/control/
recovery/offline/original source cases, without a historical full suite. Frozen
apps pass all15 sync-protocol flags, CLI/MCP retries and source-aware cached model
handoff. Mac passes three reader launches and foreground activation; its downloaded
screenshot shows readable Chinese/formula/code. Windows passes isolated actual
install/reinstall/uninstall with research preserved; Linux passes AppImage
integration. Source-format0.4.3 preservation is tested; older installed-binary
upgrade, native account login/IME/vault, full GUI and physical two-device/phone
acceptance remain open.

Small provenance ZIPs for [Mac](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14204521558),
[Windows](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14204014268)
and [Linux](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14204860735)
were independently downloaded/hash-matched and inspected: exact clean source,
expected arm64/amd64/x86_64 hosts, `passed=true`, all15 flags true. Large installer
ZIPs were not independently downloaded on this source workstation. The following
ZIP hashes are GitHub-reported artifact metadata:

| Platform | ZIP bytes | ZIP SHA-256 |
|---|---:|---|
| macos | 280939951 | `b48e1c095de465412cf2256ad3603cab1fd6081fb0b21487586ca190696c8440` |
| windows | 184738912 | `3354bd2275e4c2b988267b3142b97473a5e0cdfd09d358f689b1f35b81b045d8` |
| linux | 282713093 | `8bd3830f6a3bdfbd441c06f757ea2abe408ee7f5eb412a5e7a0cce76d0adff19` |

The [matching mobile web artifact](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14204845490)
was downloaded/hash-matched and verified against all54 assets, proxy map and cache
identity in0.453s under the two-processor/25% CPU governor. Content ID
`5a55483512ff75d5a09b676b865b721e07ce9390f8f882a6f858243400f54246`.
It includes the storage-protection module but is **not deployed HTTPS/PWA** and
has not passed physical Safari/iOS/Android acceptance.

## Previous tested downloads: 1875db5

Windows and Apple Silicon Mac now share clean source
`1875db595b7df510a851a2d44ea5157cc994689f`, version `0.5.0.dev`, beta-candidate.
These are test builds, not a public release or an automatic-update offer.

| Platform | Download | Exact job | Duration |
|---|---|---|---|
| Apple Silicon Mac | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43808973671/artifacts/14199876771) | [Mac run](https://github.com/puddings-world/Paperfact/actions/runs/43808973671) | 3m54s |
| Windows x64 | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43808976905/artifacts/14199523450) | [Windows run](https://github.com/puddings-world/Paperfact/actions/runs/43808976905) | 7m48s |

Download the ZIP while signed into GitHub, extract it, then open its DMG/setup.
Keep the daily app and research. Use the separate Mac app/workspace commands below;
import an exported list research package to read your desktop research on Mac.
Check source **1875db5** in the bottom-right version/support information before
reporting a problem. Your own supported AI login is separate from package import.
Hosted continuous synchronization is not deployed; export/import is the available
cross-machine handoff. Do not paste one device's credentials into another device.

Both jobs pass critical14, first-sync preservation1 and45 named authority/control/
recovery/offline source cases. Their actual frozen applications pass all15 sync
protocol flags, including control-history challenge, absent/forged control refusal
and restart, plus report/source handoff, exact originals, cached model completion,
CLI/MCP retry and source-format0.4.3 preservation. Mac passes three reader launches
and foreground activation; actual screenshots show readable Traditional Chinese,
formula and code. Windows passes isolated install/reinstall/uninstall with research
preserved. This does not certify every frozen dialog, live AI/Google login, native
vault/IME, older installed-binary upgrade or physical two-device/phone journey.

Small [Mac provenance](https://github.com/puddings-world/Paperfact/actions/runs/43808973671/artifacts/14199338423)
and [Windows provenance](https://github.com/puddings-world/Paperfact/actions/runs/43808976905/artifacts/14200082064)
ZIPs were independently downloaded, SHA-256-matched and inspected: both are clean,
exact1875db5, `passed=true`, and have the expected arm64/amd64 host. Mac screenshots
and [synthetic research fixture](https://github.com/puddings-world/Paperfact/actions/runs/43808973671/artifacts/14199872015)
were also hash-matched; the reading screenshot was visually inspected.

Installer ZIP hashes below are GitHub-reported metadata; large installer payloads
were not independently downloaded on this Windows source workstation.

| Platform | ZIP bytes | ZIP SHA-256 |
|---|---:|---|
| macos | 277900881 | `8a9e615a9c1532407b958cf137acc36aef650a32cfe49c2b7404e9a81a262a6f` |
| windows | 184769284 | `7d3d20c4b212ebbe6684c86259750e0764c10245a583d81b4b6b2744ed778653` |

[Mobile artifact](https://github.com/puddings-world/Paperfact/actions/runs/43808976905/artifacts/14199263514)
uses the same source. Its downloaded ZIP hash and all53 assets, proxy map and cache identity
were independently verified; content ID
`dae60b2ab54a12460d51065b76711d5668647ca26c8eccf601a05c5d55ecd2b3`.
It is built, not deployed HTTPS/PWA or physically accepted on Safari/phones.
Linux remains the older88b2497 baseline below and lacks this new official-v4 control
handshake. Do not mix it with these candidates for v4 sync acceptance.

The earlier7a95b31 Mac attempt failed because the packaged test client omitted the
new handshake; it published no installer. The repaired independent verifier adds
refusal checks and retains all earlier assertions. This successful exact-source
build supersedes that failed attempt; see the continuation ledger for evidence.

## Previous downloads: e26ec8f / 88b2497

All builds are `0.5.0.dev`, beta-candidate, not a public v0.5 release.

| Platform | Download | Exact clean source | Job duration |
|---|---|---|---|
| Apple Silicon Mac | [DMG artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43796990188/artifacts/14195365154) | e26ec8fef7cabacba91af9c982b3011cc7eda4ca | 4m27s |
| Windows x64 | [Setup artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43795810511/artifacts/14194602606) | 88b24974f985fbd8832940cdd15ad3be3af4f649 | 8m40s |
| Linux x86-64 | [AppImage artifact ZIP](https://github.com/puddings-world/Paperfact/actions/runs/43795810511/artifacts/14194043098) | 88b24974f985fbd8832940cdd15ad3be3af4f649 | 3m22s |

Mac source adds only the screenshot helper/diagnostics repair and its tests/docs
on top of88b2497; app research code is the same. The original all-platform run
failed its Mac screenshot step before packaging. The Mac-only follow-up passes
that actual gate and frozen acceptance; successful Windows/Linux were not rebuilt.
All three small provenance ZIPs were independently downloaded/hash-matched and
checked against their exact source. [Mac provenance](https://github.com/puddings-world/Paperfact/actions/runs/43796990188/artifacts/14195061327),
[Mac screenshots](https://github.com/puddings-world/Paperfact/actions/runs/43796990188/artifacts/14195160887),
[synthetic research package](https://github.com/puddings-world/Paperfact/actions/runs/43796990188/artifacts/14195096086).

Each OS passes critical14, first-sync preservation1 and17 authority/offline-delivery
source representatives. The new dialog guard clears stale readiness if a PDF,
research or storage ownership changes after worker completion. Frozen CLI checks
include report generation, exact originals/located quotes, private captured-model
handoff, retained/cached retry and read-only list-report audit. Mac passes three
reader launches and foreground; its actual reading screenshot shows Chinese,
formula and code. Windows install/reinstall/uninstall preserves research; Linux
AppImage integration passes. This is not full frozen-dialog or physical-device
acceptance. Hosted continuous sync is not deployed: use list-package export/import
for now. Follow the separate-app launch steps below and verify source **e26ec8f**.

GitHub-reported installer ZIP metadata (installer payloads not downloaded here):

| Platform | ZIP bytes | ZIP SHA-256 |
|---|---:|---|
| macos | 279959043 | `3d8be8c88343881db70ffa37f3d44184a1f618a4c98a36f9dab3145e451b64af` |
| windows | 184644327 | `4f26cc61ce12e1d2fc1eeff909049bec79af5d74bff035b1ec1d1d8ebd12a7f7` |
| linux | 282645955 | `cd630eabdda4c800bd13c09bd7d06d0b09010546697e81bafdd39ff98004626b` |

No public tag/release, production deployment or daily research migration.
The preceding same-source0a64ec7 candidate remains recorded in the
[continuation ledger](continuation-20261112.md).

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

## Historical failed candidate5945820 (superseded)

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
