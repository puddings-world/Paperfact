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

The desktop checks at launch and hourly while open. `updates.check` asks GitHub
at most once per day per current version/channel; failed checks retry later.
Only tags shaped `vX.Y.Z` count, because Releases can also carry research bundles.
Drafts are always ignored. Current 0.x builds default to the beta channel and
include published prereleases; stable-channel clients skip them. The cache key
includes the running version and channel, so two copies sharing a workspace do
not inherit an incompatible result. `PAPERFACT_UPDATE_CHANNEL` can override the
default with `stable` or `beta`.

The notice rotates its summary and update instructions every six seconds and
pauses on hover/focus. Checking is deduplicated, downloading suppresses polling
and rotation, and closing prevents late results from launching an installer.
`tests/test_update_notices.py` covers preview selection, cache isolation, old-cache
migration, snooze, repeated activation, failure/retry and window closure. The
targeted update suite passed 34 cases locally; platform installers still need
their separate acceptance checks for each new release.

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


### Startup layout shutdown regression

The v0.4.2 candidate passed the full test suite on all three release runners, but
its Windows/macOS screenshot processes crashed after producing their final reports.
An active startup-fit event filter queried native window ownership during teardown.
The v0.4.3 correction inspects ownership only for input events. The regression
exercises real WebEngine subprocess shutdown and native window deletion while the
startup timer is pending; it fails before the correction and exits cleanly after it.
Release runners provide WebEngine and Xvfb where needed. Local environments without
those optional facilities report these new integration cases as skipped rather than
claiming native coverage. The original layout and input behavior tests remain.

The failed v0.4.2 tag is retained for provenance; no installer release was published
from it. v0.4.3 still requires the full check and all platform packaging gates.
