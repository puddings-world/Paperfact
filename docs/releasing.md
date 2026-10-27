# Releasing

How a version of Paperfact reaches the people using it: the installers, the
release notes that announce it, and the update banner that installs it.

## Cutting a release

For the first public beta, use a candidate branch and **workflow_dispatch** to
build without publishing. Run `scripts/verify_built_app.py` against the frozen app;
the workflow does this on all three platforms. Mark any eventual beta release
**pre-release** so existing installations do not treat it as stable.

The build includes license texts, upstream notices and `build-info.json` with its
source commit and dirty-tree flag. Publish only artifacts built from the reviewed
clean commit, accompanied by its corresponding source archive and dependency
source/notices required by their licenses. The initial project license is
AGPL-3.0-or-later because the PDF stack includes AGPL PyMuPDF/MuPDF.

Windows acceptance installs use `/ACCEPTANCETEST=1 /NOCLOSEAPPLICATIONS /DIR=<isolated-path>`:
no application registry entry, shortcuts, previous install directory, automatic
launch or closing of existing Paperfact processes. The destination must be an
explicit disposable test folder. Test reinstall and `unins000.exe` there while
keeping a separate test data folder; never point this at a user's real install.

```powershell
.venv\Scripts\python.exe scripts\release.py 0.2.0 --push
```

1. `scripts/release.py` sets `__version__` in `src/paper_daily/__init__.py` (the one
   place the version lives; `pyproject.toml` reads it), commits `Release v0.2.0`,
   tags `v0.2.0` and pushes both. It refuses a dirty working tree, a version not
   above the current one, or a tag that exists.
2. The tag starts `.github/workflows/release.yml`. On Windows, macOS and Linux it runs
   the full check, takes screenshots of a generated workspace, builds the app,
   starts the built app once with no screen (it must quit cleanly), and packages it.
3. When all three have built, the workflow opens a **draft** release with the
   installers attached and the commit list as notes.
4. Rewrite the draft's notes for readers, then publish it. Until it is published
   nobody sees it: the update check ignores drafts.

### The notes are the announcement

The app's update banner shows the first lines of the published notes, joined into
one line (headings, list markers and HTML comments removed). Put what a reader
should know first, in the language they read:

```markdown
## 這一版

- 引用分頁的條列和引用圖可以瞬間切換
- 新增自動更新：有新版時會在上方提示

## Changes
...
```

Everything after the first ~140 characters is only on the release page, which the
banner's **看更新內容** opens.

## What the build produces

| Platform | File | Built with |
|---|---|---|
| Windows | `Paperfact-X.Y.Z-windows-x64-setup.exe` | PyInstaller, then Inno Setup 6 (`packaging/windows/paperfact.iss`) |
| macOS (Apple silicon) | `Paperfact-X.Y.Z-macos-arm64.dmg` | PyInstaller `.app`, then `hdiutil` |
| Linux (x86-64) | `Paperfact-X.Y.Z-linux-x86_64.AppImage` | PyInstaller, then `appimagetool` 1.9.1 |

These names are part of the update contract: `updates.ASSET_SUFFIX` picks a
platform's file by its ending, and a test checks the workflow uploads those names.

Each build is one folder with two executables over the same libraries
(`packaging/paperfact.spec`): **Paperfact**, the windowed app people open, and
**paperfact-cli**, a console twin. The reader starts its background jobs
(深入分析, 清單綜覽, adding papers) through `paperfact-cli`, because a windowed
Windows executable has no stdout for them to report progress on. It is also the
command line for anyone who wants one (`paperfact-cli --version`, `paperfact-cli doctor`).

To build on your own machine (the platform you are on only):

```powershell
uv sync --extra app --extra dev --extra build
.venv\Scripts\python.exe scripts\build_app.py                 # app + installer in dist\
.venv\Scripts\python.exe scripts\build_app.py --no-installer  # just dist\Paperfact\
```

The Windows installer needs Inno Setup 6 (`winget install JRSoftware.InnoSetup`).
Its Traditional Chinese messages are an unofficial translation that Inno Setup
does not install, so a copy lives beside the script
(`packaging/windows/ChineseTraditional.isl`).

## How an installed copy updates

The desktop checks at launch and every 15 minutes while open. `updates.check`
caches results for 15 minutes per current version/channel; failed checks retry
later. **Version and updates** in the bottom-right footer provides an immediate
check that bypasses this cache and snoozing. An offline manual check says it
could not check, rather than claiming the app is current.
Only tags shaped `vX.Y.Z` count, because Releases can also carry research bundles.
Drafts are always ignored. Current 0.x builds default to the beta channel and
include published prereleases; stable-channel clients skip them. The cache key
includes the running version and channel, so two copies sharing a workspace do
not inherit an incompatible result. `PAPERFACT_UPDATE_CHANNEL` can override the
default with `stable` or `beta`.

The notice rotates its summary and update instructions every six seconds and
pauses on hover/focus. Checking is deduplicated. Downloading and a pending install
suppress polling and rotation; closing prevents late results from launching an
installer. Native CPU selection avoids offering Apple Silicon installers to Intel
Macs. Download length and GitHub's asset SHA-256 digest must match before an
installer can run. Missing digest metadata offers the release page instead.
This integrity check does not replace publisher signing/notarization.

Before installation, the window checks active work and saves restart/draft state.
If it cannot safely restart, the downloaded update stays ready for an explicit
retry. Retrying rechecks the file in the background. A newer release notice cannot
replace the identity of an update already waiting to install.

`tests/test_updates.py`, `tests/test_update_notices.py` and
`tests/test_maintenance.py` cover these behaviors with fixture files and simulated
network/installer responses. Native installers still need separate acceptance
checks for each release. This is automatic discovery with a user-initiated update,
not unattended forced installation.

Existing v0.3.0 and older installers skipped *all* prereleases. Their users need
one manual installation of a corrected build before beta notifications can work.
Do not remove a beta's prerelease flag just to bypass an old client's policy.

**更新並重啟** downloads this platform's file, then:

- **Windows** runs the installer with `/SILENT /CLOSEAPPLICATIONS`. It installs over
  the old copy and starts the new one. The install is per-user, so no administrator
  prompt appears.
- **macOS** writes a short script that waits for the app to quit, mounts the disk
  image, and moves the old `Paperfact.app` aside. It copies the new one in, deletes
  the old one only once the copy succeeded, and opens the new one.
- **Linux** downloads beside the running AppImage. Once the app has quit it renames
  the download over the old file and starts it.

A source checkout cannot replace itself: its banner offers **怎麼更新** (git pull,
then the setup script) instead.

User data is outside the install folder. See the data locations in
[release readiness](release-readiness.md) and validate preservation when testing
each platform's installer and update flow.

## Not signed yet

The builds are not code-signed. Windows SmartScreen warns on first launch, and
macOS refuses the first open until the user allows it in Privacy & Security. The
release instructions must explain those prompts when binaries are published.
Signing needs an Apple Developer account
(US$99/year, for notarisation) and a Windows code-signing certificate. When those
exist, the places to add them are the end of `pyinstaller()` (macOS
`codesign --deep` and `notarytool`) and after ISCC in `windows_installer()`
(`signtool`). Both are in `scripts/build_app.py`.

## Checking the layout on every platform

Packaging checkpoint: a first-use modal runs before Qt's outer application loop,
so a smoke-test deadline must close that dialog without recording consent. A
second test uses an explicitly acknowledged **fixture workspace** to exercise the
actual reader and import/export flow. The first check alone is not proof that the
reader starts. `test_smoke_onboarding.py` guards this distinction. Generated `shots/`
workspaces stay ignored so the provenance report does not mistake screenshots for
uncommitted application source. These are project-specific verified practices,
not new global development rules.

Captured stdout/stderr are also checked for Python tracebacks even when a process
returns zero: a native-output reader thread can fail without changing the parent
exit code. The Windows task-scheduler diagnostic only needs the return code, so it
does not decode localized command output. `test_doctor_local.py` and
`test_built_app_verification.py` guard this observed failure.

Run the workflow by hand (**Actions → Release → Run workflow**). It does
everything except the release. Each platform's `screenshots-*` artifact holds
`list.png`, `reader.png`, `reader-laptop.png` (a 1180×760 window), `citemap.png`,
`slides.png` and `report.txt` (the fonts and shortcut labels the platform
resolved). The same pictures locally:

```powershell
.venv\Scripts\python.exe scripts\screenshots.py shots --demo
```

`--demo` builds a throwaway workspace (`scripts/demo_workspace.py`): one list and
one paper with a generated PDF and a deep dive, written for the purpose.

## macOS foreground-app acceptance (0.4.5)

A console helper in a GUI bundle must not turn the enclosing app into a background
process. PyInstaller's COLLECT inherits `console` from the last EXE; BUNDLE then
uses it to default `LSBackgroundOnly` to true. Paperfact 0.4.4 collected the CLI
last, so offscreen startup and data round-trip checks passed while macOS treated
the installed reader as background-only.

- Set `LSBackgroundOnly=false` and `LSUIElement=false` explicitly in the bundle
  spec, before PyInstaller signs it. Keep `CFBundleExecutable=Paperfact`; retain
  `paperfact-cli` for background operations.
- `build_app.py` validates the emitted and DMG-staged Info.plist and both entry
  points. Invalid flags stop packaging before an existing candidate is replaced.
- `verify_built_app.py` additionally launches the generated reader fixture through
  Launch Services with Cocoa. `verify_mac_app.swift` requires a regular activation
  policy, actual active-app state, and normal termination. The macOS job fails if
  these checks fail; an offscreen pass cannot substitute for them.
- `tests/test_mac_packaging.py` covers explicit foreground overrides, invalid or
  missing flags, wrong entry points, missing executables, and corrupt staging.
- On the owner's Mac, still check Finder launch, Dock/Cmd-Tab activation, typing
  into Q&A, switching away/back, and normal quit/reopen. CI activation is not proof
  that every input method or existing workspace behaves correctly.

Evidence status: unit checks validated locally; native release acceptance is
recorded in `acceptance-macos/mac-foreground.log` for each built commit. This is a
project packaging lesson, not a new global skill. Do not modify installed signed
bundles as the permanent fix or overwrite the already-tested version's tag.

References: [PyInstaller bundle generation](https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/building/osx.py)
and [Apple Launch Services keys](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/LaunchServicesKeys.html).


The first 0.4.5 Mac CI run also exposed two existing concurrency problems. The
PDF progress fixture now waits for the selected paper's progress event, retaining
all its original assertions. More importantly, a deterministic regression test
reproduced a stale background preference write committing after a newer flush.
0.4.6 serializes snapshot/commit operations while keeping UI saves and reads
nonblocking. Do not dismiss repeated cross-platform failures as runner noise;
preserve the failure evidence and pin the actual interleaving in a small test.
