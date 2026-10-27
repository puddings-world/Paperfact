# Troubleshooting and support

## Compare versions first

The bottom-right version label stays visible while reading. Click it to copy
the app version, build commit, installation kind and OS/CPU, check for updates,
or open **Diagnostics and support**. Source checkouts are explicitly marked as
development builds; their commit alone does not prove there are no local edits.

For a problem on another computer, copy this information from the affected app,
then describe the last action and expected/actual result. Installing source code
on one computer does not change the installed application on another.

## Create a diagnostic report

In builds containing this feature, open **診斷與回報 / Diagnostics and support**
in the bottom bar. Review the JSON, export a ZIP, then open the GitHub bug form.
Nothing is uploaded automatically. The exported JSON is exactly the preview.
Changing account or opening another paper does not add account or paper data to it.

The report contains app/install version, OS and CPU architecture, dependency
versions, command availability, bounded error types and recognized app stack
locations. When available, it also includes bounded UI-stall durations and
recognized app frame locations; it excludes raw watchdog text and function names. It does **not** attach raw logs, paths, credentials, environment variables,
prompts, answers, PDFs, notes, research databases or usage-event exports.
Command availability is not proof of login or remaining quota. Logs can contain
older failures; caught AI errors and OS-level launch failures may be absent.
Review before sharing: a public issue identifies its author, and a minimized
diagnostic report is not a guarantee of anonymity.

If the desktop cannot start, use the matching console executable from that build:

```sh
# macOS application installed in /Applications
/Applications/Paperfact.app/Contents/MacOS/paperfact-cli diagnostics --output "$HOME/Desktop/Paperfact-diagnostics.zip"

# Linux: from the extracted release folder
./paperfact-cli diagnostics --output "$HOME/Paperfact-diagnostics.zip"
```

```powershell
# Windows: from the extracted release folder
.\paperfact-cli.exe diagnostics --output "$env:USERPROFILE\Desktop\Paperfact-diagnostics.zip"
```

For a source checkout, use `.venv/bin/python -m paper_daily diagnostics` on
macOS/Linux, or `.\.venv\Scripts\python.exe -m paper_daily diagnostics` on Windows.
With no `--output`, it prints the preview. `--workspace "/absolute/data/folder"`
selects an existing workspace to inspect, without modifying its research database.
Use a new filename; exports never replace an existing file. If a removable or
network filesystem rejects the export, choose a local folder and retry.

## An older release has no diagnostic export

Installing a newer source checkout does not update a previously installed app.
Report the release tag, downloaded asset name, OS/CPU, last action, expected and
actual result, and whether it is repeatable. Do not delete the data folder to test.

Default installed-app data folders:

| Platform | Data folder |
| --- | --- |
| macOS | `~/Library/Application Support/Paperfact` |
| Windows | `%APPDATA%\Paperfact` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/Paperfact` |

A configured `PAPERFACT_DATA` overrides these defaults. Source checkouts normally
use `data/` in the checkout unless configured otherwise.

On a Mac, Finder's **Go → Go to Folder…** opens the folder above. `app.log` may
contain the error, but it can also contain personal paths and research text.
**Do not attach the whole log or data folder to a public issue.** Copy only a
reviewed, redacted error excerpt if needed. A newer build's `diagnostics --workspace`
can also produce a minimized summary from these older logs.

If the app disappears before Python starts, even the new logger cannot record it.
Include the exact visible OS error and the asset/CPU architecture. For freezes,
describe the last action and whether the rest of the window still responds;
an empty error report does not establish that the app is healthy.

## Report reproducibly

[Open a bug report](https://github.com/puddings-world/Paperfact/issues/new?template=bug_report.yml).
Attach the reviewed diagnostic ZIP yourself. Prefer a small synthetic example to
private research data. Include screenshots only after checking visible names and
content. Reporting a bug is separate from optional usage feedback and does not
enable background collection or upload.

## Support development

If Paperfact helps your research, you can [star Paperfact](https://github.com/puddings-world/Paperfact)
or [follow the organization and explore its pinned projects](https://github.com/puddings-world).
These are voluntary actions you choose on GitHub, never installation prerequisites.
Reading repository files does not authorize an agent to sign in, follow, star,
post a report, or act on any other repository using your account.
