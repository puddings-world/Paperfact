# Install and open Paperfact

Choose an installer to use a released preview, or a source checkout to run the
current code. These are separate installations with separate default workspaces.

## Install a released preview

Open [Releases](https://github.com/puddings-world/Paperfact/releases) and expand
**Assets**. The published `v0.2.0` preview provides:

| Your computer | Download | Open it |
|---|---|---|
| Windows x64 | `Paperfact-0.2.0-windows-x64-setup.exe` | Run setup, then open Paperfact from Start. |
| macOS, Apple silicon | `Paperfact-0.2.0-macos-arm64.dmg` | Open the DMG, copy Paperfact to Applications, then open it there. |
| Linux x86-64 | `Paperfact-0.2.0-linux-x86_64.AppImage` | Allow the downloaded file to execute, then open it in your desktop session. |

For Linux, from the folder containing that download:

```bash
chmod +x Paperfact-0.2.0-linux-x86_64.AppImage
./Paperfact-0.2.0-linux-x86_64.AppImage
```

Use the matching filename if downloading a different version. The Linux binary
is built on Ubuntu 22.04; native libraries and AppImage support depend on your
distribution. Intel Mac and ARM Windows/Linux installers are not currently
published. Builds are unsigned and your OS may show a first-launch warning.
[Release acceptance status](release-readiness.md) distinguishes build evidence
from clean-machine and real-account testing.

The app bundles Python and Qt. You do not need Git, uv or the setup scripts for
these installers. A source ZIP contains code, not an installed app or a research
data package. Release binaries contain the tagged version; newer source changes
do not appear in an already downloaded installer.

## Run from source

You need Git, an internet connection, and PowerShell on Windows or Bash on
macOS/Linux. Linux needs a graphical desktop and Qt's system libraries; the
[Ubuntu build workflow](../.github/workflows/release.yml) lists the packages used
by this project's Linux build. Source execution on other architectures depends
on Python/Qt package availability and has not been verified on every machine.

Setup installs uv if missing, prepares Python 3.11 and `.venv`, and downloads
Python dependencies, fonts and offline web-rendering assets. Qt is a large
download, so the first setup takes time. Setup also includes Python development
dependencies; Node.js is needed only for the full development check below.

### Windows — PowerShell

```powershell
git clone https://github.com/puddings-world/Paperfact.git
cd Paperfact
.\scripts\setup.ps1
.\scripts\dev.ps1 app
```

Next time, open PowerShell in the cloned Paperfact folder and run:

```powershell
.\scripts\dev.ps1 app
```

### macOS / Linux — Terminal

```bash
git clone https://github.com/puddings-world/Paperfact.git
cd Paperfact
bash scripts/setup.sh
bash scripts/dev.sh app
```

Next time, open Terminal in the cloned Paperfact folder and run:

```bash
bash scripts/dev.sh app
```

The `dev` scripts are thin launchers for the same Paperfact CLI. You do not need
to activate a virtual environment, install a second copy, or learn the other
commands to open the app. If setup fails, resolve that error and rerun setup before
launching. On Windows, a managed execution policy may restrict local scripts;
follow your organization's policy rather than changing a system-wide setting.

Optional source-checkout shortcuts: Windows users can run
`scripts/make-shortcut.ps1`; macOS users can run `bash scripts/make-app-mac.sh`.
These shortcuts depend on the checkout and its `.venv`; keep that folder in place.

## First use and sharing

Start in the empty list overview. Create a list, or choose **研究資料 →
匯入研究資料包…** to load a colleague's saved research. To share it again, choose
**研究資料 → 匯出目前清單資料包…**, **清單總覽 → 匯出選取清單…**,
or **清單頁 → 匯出此清單…**. These controls share the same transfer flow.
This ZIP carries the list's available PDFs,
analyses, notes and editable decks; it is a list snapshot rather than a whole-app
backup. In the **簡報** tab, **匯出簡報…** creates a PDF by default;
**建立 Google Slides** creates an editable cloud copy.

These menu labels describe the current source; earlier previews may place the
research-package actions in **＋ 新增** or the list overview.

Reading/importing saved work needs no AI account. New AI work uses your own
provider account and requires that provider's supported official CLI or an API
connection. App setup does not install or log in to every AI provider. See
[AI setup](ai-setup.md) and [Google Slides setup](google-release.md).

No ML corpus download or nightly schedule is required for ordinary research lists.

## Troubleshoot or update a source checkout

Local diagnostics make no model or network calls:

```powershell
# Windows, from the checkout
.\scripts\dev.ps1 doctor
```

```bash
# macOS / Linux, from the checkout
bash scripts/dev.sh doctor
```

`doctor --ai` is a separate, explicit model test that can use quota. Close the app
before updating a source checkout. Preserve your local code changes, then run
`git pull` followed by your platform's setup command. Updating source does not
update a separately installed release app.

The default data folders are:

| Installation | Workspace |
|---|---|
| Source checkout | `data/` in the checkout |
| Windows installer | `%APPDATA%\Paperfact` |
| macOS installer | `~/Library/Application Support/Paperfact` |
| Linux installer | `~/.local/share/Paperfact` |

`PAPERFACT_DATA` can override the location. Back up the entire configured data
folder privately before migration; it contains original research and edits, not
just caches. Share selected research through packages, which omit AI credentials.

## Develop or build installers

Development requires Node.js in addition to source setup. Run the complete check:

```powershell
# Windows
.\.venv\Scripts\python.exe scripts/check.py
```

```bash
# macOS / Linux
.venv/bin/python scripts/check.py
```

See [Development](development.md) for tests, [CLI reference](cli-reference.md)
for automation, and [Releasing](releasing.md) for building installers.
