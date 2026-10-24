# CLI reference

The desktop app can create/import/export lists and generate slides without terminal
commands. For installation and platform prerequisites, start with [Installation](install.md).
This reference is for diagnostics and automation after source setup.

## Choose the launcher for your terminal

Run from the cloned Paperfact folder. Both launchers use that checkout's `.venv`;
virtual-environment activation is unnecessary.

**Windows · PowerShell**

```powershell
.\scripts\dev.ps1 app
.\scripts\dev.ps1 doctor
.\scripts\dev.ps1 lists
.\scripts\dev.ps1 --help
```

**macOS / Linux · Terminal**

```bash
bash scripts/dev.sh app
bash scripts/dev.sh doctor
bash scripts/dev.sh lists
bash scripts/dev.sh --help
```

Append any command in the tables below to the appropriate launcher. For example,
`list-export my-list -o research.zip` exports the list identified by `my-list`;
`list-import research.zip` imports a research package. Use `lists` to find list IDs.
`doctor` is local-only; `doctor --ai` explicitly tests a model and can use quota.

Research packages are ZIP snapshots of a list's saved research. PDF or Google
Slides export is a separate presentation action in the desktop app.

The launchers forward Paperfact subcommands; they do not execute arbitrary Python
files. Run helper scripts with `.\.venv\Scripts\python.exe scripts/name.py`
on Windows, or `.venv/bin/python scripts/name.py` on macOS/Linux.

<details>
<summary>CLI inside an installed or unpacked build</summary>

Installers do not put a global `paperfact` command on your shell PATH. They contain
a console executable named `paperfact-cli`, separate from the desktop launcher.

```powershell
# Default Windows install location
& "$env:LOCALAPPDATA\Programs\Paperfact\paperfact-cli.exe" doctor
```

```bash
# macOS, when the app was copied to /Applications
/Applications/Paperfact.app/Contents/MacOS/paperfact-cli doctor
```

On Linux, use the AppImage's console mode (0.3.0+):

```bash
./Paperfact-0.3.0-linux-x86_64.AppImage --cli doctor
```

For automation, a source checkout or `paperfact-cli` in an unpacked build also
works. Neither method adds a global command to PATH.
With a source virtual environment explicitly activated, `paperfact` is also
available; `paper-daily` remains a compatibility alias.

</details>

## Everyday work and research packages

| Command | What it does |
|---|---|
| `app [--next] [--paper ID] [--restart]` | Open the desktop reader (`--next` jumps straight to the next unread; `--paper` opens one paper, in the running window if there is one, switching to the queue or a list that holds it; `--restart` saves drafts and restarts the running reader) |
| `import-list <name> --file F [--slug S]` | Import a bibliography as a switchable reading list |
| `lists` | Show the reading lists and how far through each one is |
| `list-add <list> "<citation>" [--file F] [--doi DOI]` | Resolve a title, citation, arXiv ID/URL or DOI and add the paper to the named list. |
| `analyze [<paper_id>...] [--list S\|all] [--ahead N] [--jobs N] [--retry]` | Generate missing PDF preparation, explanations, highlights, references and later-work analysis. Use `--list ID` for a list; `--retry` retries previously failed steps. See details below. |
| `list-remove <list> <paper_id>` | Drop a paper from a list (the paper stays in the corpus) |
| `repdf <paper_id> [--url URL] [--file PATH]` | Read a paper from another PDF (default: its arXiv copy; `--file` for one downloaded by hand, e.g. through a library proxy); figures and text are re-extracted and every note and question is re-anchored by the passage it quotes. The old file is kept in `data/pdf/replaced/` |
| `list-export <list> [-o file.zip] [--no-notes] [--without-pdfs]` | Pack a reading list with every locally available PDF, analysis, survey, figure, extracted text, slide deck, highlight and saved research question, plus the citation-graph metadata and optional notes/Q&A. Default export is offline. `--without-pdfs` creates a smaller URL-based package and verifies remote PDF versions; `--with-pdfs` remains accepted for compatibility |
| `list-import <file.zip> [--replace] [--no-pdfs]` | Validate and import a research bundle. Existing papers, analyses and files are kept unless `--replace`; different local PDFs retain their matching analyses. New list members arrive unread. Packed PDFs work offline; for legacy/link-only packages, verified URLs may be downloaded. `--no-pdfs` disables those downloads, not extraction of packed files |
| `survey <list> [--force]` | Read a whole reading list as one field: history, lines of work, datasets, progress, challenges, open research topics and a reading order (the 清單綜覽 dialog); `--force` replaces a hand-edited survey |
| `doctor` | Check local prerequisites, fonts/web assets and configuration. No network/model calls; an empty workspace and no AI login are valid. `--ai` explicitly makes a model test call (may use quota); `--sources` checks the optional scholarly services. |

<details>
<summary>Analysis options and progress</summary>

- `--jobs N` controls simultaneous papers (default 3).
- Already completed steps are reused. `--retry` retries steps that previously failed.
- `--ahead N` selects the next N unread papers still missing analysis, using the
  specified list or the legacy CLI queue when no list is supplied.
- `--scheduled` follows the app's analysis schedule and paper budget; it can do
  nothing when no run is due. Scheduling is optional, not an installation step.
- Output reports completed papers and the status of each research component.
  External sources can leave a paper partially complete even when the batch exits
  normally; review those reported gaps before sharing a package.

</details>

## Additional research operations

| Command | What it does |
|---|---|
| `venues [<paper_id>...] [--list S\|all]` | Check published venue metadata for preprints, using OpenAlex and Crossref. |
| `resources [<paper_id>...] [--list S\|all] [--force]` | Find and verify code, datasets, model and project links. Named papers and `--force` are rechecked. |
| `cites [<paper_id>] [--list S] [--limit N]` | Work out what each reference is doing in a paper, and whether to read it; `--list` does every paper in a list that has no analysis yet |
| `followups <id>... [--list S] [--ahead N] [--with-cites]` | What cites a paper across the whole field (OpenAlex and Semantic Scholar, merged), what each citing work does with it and whether to read it, and the research overview of both directions; `--with-cites` analyses the references first when missing |
| `close-read <id>... [--list S] [--jobs N] [--rewrite] [--force]` | 逐節精讀: walk every section after the front matter with the paper's figures and tables placed where they are discussed; `--list all` for every list, `--rewrite` for ones on an older specification |
| `cite-links <id>... [--list S]` | Which of a paper's references and citing works cite each other (Semantic Scholar batch, no model call), for the 引用圖 map; `followups` runs it too |
| `cites-ahead [n] [--rewrite]` | Do that for the next *n* explained papers that have no analysis; `--rewrite` redoes ones written under an older specification |
| `dive-ahead [n] [--paper ID] [--list S] [--rewrite] [--jobs N]` | Pre-write deep dives for the next *n* papers, one named paper, or a reading list; `--rewrite` redoes dives written before the current spec, in queue order; `--jobs` writes several at once |
| `set-dive <paper_id> [--file F]` | Attach a deep dive to a paper |

## Accounts, local storage and assets

| Command | What it does |
|---|---|
| `init` | Create the SQLite database |
| `find <text> [-n N]` | Search papers in the local workspace |
| `status` | Corpus and queue summary, per venue-year |
| `llm [--backend B] [--model M] [--key K] [--base-url U] [--test]` | Manage profiles and task routes, or test CLI, API, local-model or custom gateway connections |
| `storage [--cache-days N]` | Disk use of the data folder by folder and by list, and how much `prune` could give back |
| `prune [--cache-days N] [--yes] [--vacuum]` | Delete what can be fetched or rebuilt again: HTTP cache older than *N* days (default 30) and the PDF, figures and text of unclaimed papers. A paper is claimed when it is in a list, in the queue (not skipped), pinned, or has notes, highlights, a deep dive, citations, chat or a close reading; its files are never touched. Lists what it would delete unless `--yes`; `--vacuum` compacts `papers.db` afterwards |
| `web-assets` | Download KaTeX, highlight.js and Mermaid into `vendor/web/` (idempotent; the setup scripts call it) |
| `fonts` | Download the typefaces the reader ships with into `fonts/` (idempotent; the setup scripts call it) |

## Reading pages

| Command | What it does |
|---|---|
| `reader-doc [--date D]` | Write `data/briefs/<date>/reader-doc.json` for the reader page |
| `share draft <id>... [--slug S] [--compare]` | Lay one or more papers out as an editable Markdown draft in `data/share/<slug>/`; `--compare` has the model write the side-by-side from the dives |
| `share build <slug>` | Turn the edited draft into `data/share/<slug>/index.html`, figures beside it |

## Optional ML corpus and legacy queue automation

These commands operate the bundled ML corpus or legacy CLI queue. They are not setup prerequisites for ordinary desktop lists. See [the optional ML workflow](ml-daily.md).

| Command | What it does |
|---|---|
| `crawl --years <spec> [--venues <list>]` | Fetch paper rosters |
| `enrich --years <spec> [--venues <list>]` | Add citations, authors, abstracts, award labels |
| `rank [--per-year N]` | Score every paper and rebuild the pending queue |
| `bootstrap --years <spec> [--venues] [--per-year]` | `init` + `crawl` + `enrich` + `rank` |
| `refresh [--back N] [--venues] [--per-year]` | Re-crawl the newest years and re-rank |
| `today` | Pop the next paper, download its PDF, write its briefing pack |
| `prefetch [n] [--force]` | Download and extract the next *n* papers, so the reader can open them |
| `backfill [--limit N]` | Fill missing authors, abstracts and ids — conference pages first, then Semantic Scholar |
| `lineage [n]` | Record in-corpus references for the next *n* listed or queued papers |
| `resolve-missing [n]` | Retry the PDF hunt for papers with no route to their original |
| `queue-add <id or title words> [--reason R] [--back] [--first]` | Put a paper into the reading queue by hand |
| `queue-remove <paper_id>` | Take a paper out of the reading queue |
| `peek [n]` | Show the next *n* papers without consuming them |
| `mark <paper_id> <state>` | Set state: `pending`, `read`, `skipped`, `deferred` |
| `sync-queue [--limit N]` | Write `data/queue-sync.json` for the cloud routine |
| `sync-read <n>` | Mark the first *n* pending papers read, to catch up with the cloud |
| `export [n]` | Dump the upcoming queue as JSON |

`--years` accepts `2016-2026`, `2023,2024`, or `2024`.
`--venues` accepts any subset of `ICLR,ICML,NeurIPS`.

## Repository slash commands (Claude Code)

These require Claude Code and the repository command definitions. They are
not PowerShell/Bash commands or built-in commands for every AI provider.

| Command | What it does |
|---|---|
| `/paper-today` | Deliver and deep-dive today's paper |
| `/paper-more` | Pop another paper immediately |
| `/paper-analyze <list \| ids> [--retry]` | Run `analyze` and report what is still missing, PDFs especially |
| `/paper-queue` | Show what is coming and how to change it |
| `/paper-note` | Append a note to today's brief |
| `/paper-pull-notes` | Pull the notes other readers wrote on the shared page into `papers.db` |

## Local agent and project integration

`mcp --workspace /absolute/data/folder` runs the local stdio MCP helper.
`integration OPERATION --workspace /absolute/data/folder --file arguments.json`
runs the same offline operation and prints one JSON result. Without `--file`, it
reads UTF-8 JSON from stdin. Neither command calls an AI provider.

Use `integration config --workspace /absolute/data/folder` for host settings, or
copy them from **研究資料 → 本地整合** in the desktop. The workspace must match the
desktop's data folder. See [tools, JSON examples and retry rules](local-integration.md).
