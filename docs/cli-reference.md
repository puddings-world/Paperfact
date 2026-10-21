# CLI reference

Run these commands from the repository root. Ordinary desktop use does not require
learning them. Conference crawling/ranking commands belong to the bundled ML
workflow; they are not prerequisites for importing your own reading lists.

## Commands

All commands run via `scripts/dev.ps1` (Windows) or `scripts/dev.sh`, or as
`paperfact` once the venv is active (`paper-daily` remains an alias).
In an installed build the same commands are `paperfact-cli`, beside the app
(`%LOCALAPPDATA%\Programs\Paperfact\paperfact-cli.exe`,
`/Applications/Paperfact.app/Contents/MacOS/paperfact-cli`). `--version` prints
the version.

| Command | What it does |
|---|---|
| `init` | Create the SQLite database |
| `crawl --years <spec> [--venues <list>]` | Fetch paper rosters |
| `enrich --years <spec> [--venues <list>]` | Add citations, authors, abstracts, award labels |
| `rank [--per-year N]` | Score every paper and rebuild the pending queue |
| `bootstrap --years <spec> [--venues] [--per-year]` | `init` + `crawl` + `enrich` + `rank` |
| `refresh [--back N] [--venues] [--per-year]` | Re-crawl the newest years and re-rank |
| `app [--next] [--paper ID] [--restart]` | Open the desktop reader (`--next` jumps straight to the next unread; `--paper` opens one paper, in the running window if there is one, switching to the queue or a list that holds it; `--restart` saves drafts and restarts the running reader) |
| `today` | Pop the next paper, download its PDF, write its briefing pack |
| `prefetch [n] [--force]` | Download and extract the next *n* papers, so the reader can open them |
| `backfill [--limit N]` | Fill missing authors, abstracts and ids — conference pages first, then Semantic Scholar |
| `lineage [n]` | Record in-corpus references for the next *n* listed or queued papers |
| `import-list <name> --file F [--slug S]` | Import a bibliography as a switchable reading list |
| `lists` | Show the reading lists and how far through each one is |
| `list-add <list> "<citation>" [--file F] [--doi DOI]` | Add one paper to an existing list; a citation, a title, an arXiv id (`2608.17522`, `arXiv:…`, or the abs URL, read from arXiv itself so a paper posted last week works), or a DOI that names it outright |
| `analyze [<paper_id>...] [--list S\|all] [--ahead N] [--jobs N] [--retry]` | 深入分析: make everything a paper is missing: the PDF, venue and code links, then side by side the deep dive with its close reading and marked passages, and 承先 (reference analysis) followed by 啟後 (later work plus the 研究脈絡 overview). Papers that have it all are skipped; N papers run at once (default 3). `--ahead N` takes the next N unread papers still missing something, in reading order: the main queue, or the lists with `--list ID\|all` (what the reader's idle pass runs); a paper whose PDF no source has is passed over rather than retried every night. `--scheduled` is the nightly run: it does nothing unless the reader's 分析排程 says tonight is due (every night, every two days, weekly, or never), then analyses that many queue and list papers and records the ones that came out complete, which the reader announces once. A step that made nothing (no source had the PDF, an unreadable reference list) is not retried unless `--retry`. One line per finished paper: `[3/17] 原文✓ 講解✓ 承先✓ 啟後✓  <title>` |
| `list-remove <list> <paper_id>` | Drop a paper from a list (the paper stays in the corpus) |
| `venues [<paper_id>...] [--list S\|all]` | Look up where preprint-only papers were published (OpenAlex's published location; an LNCS chapter is named by its proceedings through Crossref). Semantic Scholar keeps "arXiv" long after publication: SASVi is IJCARS 2025, GLSFormer MICCAI 2023. Runs nightly over every list |
| `resources [<paper_id>...] [--list S\|all] [--force]` | Find each paper's code, data, models and project page: the links its text prints (a link counts as the paper's own when the words before it say so, when it is on the first page, or when the account looks like an author's), Hugging Face's paper page, and as a last resort a GitHub search for the paper's short name, kept only when the account is an author's or the description names the paper. Each repository is checked on GitHub for stars, licence and whether it exists. `list-add` runs it on what it added; nightly over every list. Papers already checked are skipped unless named or `--force` |
| `repdf <paper_id> [--url URL] [--file PATH]` | Read a paper from another PDF (default: its arXiv copy; `--file` for one downloaded by hand, e.g. through a library proxy); figures and text are re-extracted and every note and question is re-anchored by the passage it quotes. The old file is kept in `data/pdf/replaced/` |
| `cites [<paper_id>] [--list S] [--limit N]` | Work out what each reference is doing in a paper, and whether to read it; `--list` does every paper in a list that has no analysis yet |
| `followups <id>... [--list S] [--ahead N] [--with-cites]` | What cites a paper across the whole field (OpenAlex and Semantic Scholar, merged), what each citing work does with it and whether to read it, and the research overview of both directions; `--with-cites` analyses the references first when missing |
| `close-read <id>... [--list S] [--jobs N] [--rewrite] [--force]` | 逐節精讀: walk every section after the front matter with the paper's figures and tables placed where they are discussed; `--list all` for every list, `--rewrite` for ones on an older specification |
| `list-export <list> [-o file.zip] [--no-notes] [--without-pdfs]` | Pack a reading list with every locally available PDF, analysis, survey, figure, extracted text, slide deck, highlight and saved research question, plus the citation-graph metadata and optional notes/Q&A. Default export is offline. `--without-pdfs` creates a smaller URL-based package and verifies remote PDF versions; `--with-pdfs` remains accepted for compatibility |
| `list-import <file.zip> [--replace] [--no-pdfs]` | Validate and import a research bundle. Existing papers, analyses and files are kept unless `--replace`; different local PDFs retain their matching analyses. New list members arrive unread. Packed PDFs work offline; for legacy/link-only packages, verified URLs may be downloaded. `--no-pdfs` disables those downloads, not extraction of packed files |
| `survey <list> [--force]` | Read a whole reading list as one field: history, lines of work, datasets, progress, challenges, open research topics and a reading order (the 清單綜覽 dialog); `--force` replaces a hand-edited survey |
| `cite-links <id>... [--list S]` | Which of a paper's references and citing works cite each other (Semantic Scholar batch, no model call), for the 引用圖 map; `followups` runs it too |
| `cites-ahead [n] [--rewrite]` | Do that for the next *n* explained papers that have no analysis; `--rewrite` redoes ones written under an older specification |
| `find <text> [-n N]` | Search all 63,000 papers, not just the queue |
| `resolve-missing [n]` | Retry the PDF hunt for papers with no route to their original |
| `queue-add <id or title words> [--reason R] [--back] [--first]` | Put a paper into the reading queue by hand |
| `queue-remove <paper_id>` | Take a paper out of the reading queue |
| `dive-ahead [n] [--paper ID] [--list S] [--rewrite] [--jobs N]` | Pre-write deep dives for the next *n* papers, one named paper, or a reading list; `--rewrite` redoes dives written before the current spec, in queue order; `--jobs` writes several at once |
| `set-dive <paper_id> [--file F]` | Attach a deep dive to a paper |
| `peek [n]` | Show the next *n* papers without consuming them |
| `mark <paper_id> <state>` | Set state: `pending`, `read`, `skipped`, `deferred` |
| `status` | Corpus and queue summary, per venue-year |
| `llm [--backend B] [--model M] [--key K] [--base-url U] [--test]` | Manage profiles and task routes, or test CLI, API, local-model or custom gateway connections |
| `doctor` | Check local prerequisites, fonts/web assets and configuration. No network/model calls; an empty workspace and no AI login are valid. `--ai` explicitly makes a model test call (may use quota); `--sources` checks the optional scholarly services. |
| `storage [--cache-days N]` | Disk use of the data folder by folder and by list, and how much `prune` could give back |
| `prune [--cache-days N] [--yes] [--vacuum]` | Delete what can be fetched or rebuilt again: HTTP cache older than *N* days (default 30) and the PDF, figures and text of unclaimed papers. A paper is claimed when it is in a list, in the queue (not skipped), pinned, or has notes, highlights, a deep dive, citations, chat or a close reading; its files are never touched. Lists what it would delete unless `--yes`; `--vacuum` compacts `papers.db` afterwards |
| `web-assets` | Download KaTeX, highlight.js and Mermaid into `vendor/web/` (idempotent; the setup scripts call it) |
| `fonts` | Download the typefaces the reader ships with into `fonts/` (idempotent; the setup scripts call it) |
| `reader-doc [--date D]` | Write `data/briefs/<date>/reader-doc.json` for the reader page |
| `sync-queue [--limit N]` | Write `data/queue-sync.json` for the cloud routine |
| `sync-read <n>` | Mark the first *n* pending papers read, to catch up with the cloud |
| `export [n]` | Dump the upcoming queue as JSON |
| `share draft <id>... [--slug S] [--compare]` | Lay one or more papers out as an editable Markdown draft in `data/share/<slug>/`; `--compare` has the model write the side-by-side from the dives |
| `share build <slug>` | Turn the edited draft into `data/share/<slug>/index.html`, figures beside it |

`--years` accepts `2016-2026`, `2023,2024`, or `2024`.
`--venues` accepts any subset of `ICLR,ICML,NeurIPS`.

### Slash commands (Claude Code)

| Command | What it does |
|---|---|
| `/paper-today` | Deliver and deep-dive today's paper |
| `/paper-more` | Pop another paper immediately |
| `/paper-analyze <list \| ids> [--retry]` | Run `analyze` and report what is still missing, PDFs especially |
| `/paper-queue` | Show what is coming and how to change it |
| `/paper-note` | Append a note to today's brief |
| `/paper-pull-notes` | Pull the notes other readers wrote on the shared page into `papers.db` |
