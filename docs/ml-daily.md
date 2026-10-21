# Bundled ML daily reading workflow

This guide describes the current ML-specific integration. The code is still
bundled; independent installation and a module manager are proposed, not shipped.
Its corpus, ranking and schedule are optional for researchers using their own
reading lists. Run terminal examples from the repository root.

## Purpose

The ML workflow includes a queue over a decade of ICLR, ICML
and NeurIPS, and a nightly deep dive on whatever is at the front of it.

The three conferences accept roughly 40,000 papers across 2015-2026 — ICLR 2026
alone lists 5,468 and ICML 2026 lists 6,628. One a day would take a century, so the
selection challenge for this workflow is deciding what deserves the next slot.

## Quick start

```powershell
.\scripts\setup.ps1                          # Windows
.\scripts\dev.ps1 doctor                     # verify prerequisites and sources
.\scripts\dev.ps1 bootstrap --years 2015-2026   # ~45 min, builds the corpus
.\scripts\dev.ps1 prefetch 30                # download the next papers' PDFs
.\scripts\make-shortcut.ps1                  # Desktop + Start menu launcher, no terminal
.\scripts\register-nightly.ps1               # have it open itself at 00:00 daily
```

Then double-click **Paperfact** on the Desktop.

```bash
./scripts/setup.sh                           # macOS / Linux
./scripts/dev.sh doctor
./scripts/dev.sh bootstrap --years 2015-2026
./scripts/dev.sh prefetch 30
./scripts/dev.sh app
```

In Claude Code, `/paper-today` writes the deep dive for the delivered paper; the app
picks it up on next launch.

## How a paper is chosen

Five signals, combined into one score per paper. Weights live in `ScoreWeights` in
`src/paper_daily/config.py`.

| Signal | Weight | What it is |
|---|---|---|
| `award` | 0.30 | oral / spotlight, scraped from the conference programme |
| `citation_velocity` | 0.25 | citations per year since publication, percentile-ranked |
| `author_strength` | 0.15 | highest h-index on the paper, percentile-ranked |
| `paper_type` | 0.20 | principle > method > system > application > benchmark |
| `recency` | 0.10 | newer years nudged up within a block |

Two deliberate distortions sit on top of the score:

- **Canon papers** (`src/paper_daily/rank/canon.py`) are injected on a fixed cadence
  regardless of score. Attention Is All You Need is cited so universally that its
  velocity percentile understates it, and a purely score-driven queue would bury
  foundational work for years.
- **Lineage expansion**: a paper's references that are already in the corpus are
  pulled forward as companion reading. This is what makes the queue a path through
  an idea rather than a ranked list, and the reader shows it directly — see the
  research context at the top of 引用 below. `lineage` walks ahead of the reading to
  build the graph; leaving it to grow one paper at a time on delivery meant it was
  empty exactly when it was needed.

Ordering is **year-block descending, score descending inside the block**: you finish
what mattered from 2026 before starting 2025. Each year contributes the same quota,
so a year takes a predictable number of days no matter how many papers it accepted.
New conference years appear at the front automatically — `refresh` re-crawls the
frontier, and a 2027 paper outranks everything from 2026 by construction. Papers
already delivered or read keep their state, so nothing is ever served twice.

### Why citation *velocity* and not citation count

Raw counts make it structurally impossible for a recent paper to outrank an old one,
which would defeat the whole point of reading newest-first. Velocity normalises for
age. Author strength does the same job one step earlier: a paper from three months
ago has no citations at all, but you already know who wrote it.

## Where the data comes from

| Venue | Roster (authoritative) | PDF |
|---|---|---|
| ICLR | conference virtual site | Semantic Scholar open-access / arXiv |
| ICML | virtual site + PMLR proceedings | `raw.githubusercontent.com/mlresearch` |
| NeurIPS | virtual site + `papers.nips.cc` | `proceedings.neurips.cc` |

Semantic Scholar supplies citations, authors, abstracts and the reference graph for
all three.

Three findings shaped this layout, all verified against the live services:

- **OpenReview is not usable anonymously.** Its `/notes` API returns
  `ChallengeRequiredError` (403) and `openreview.net/pdf?id=...` 403s as well. ICLR
  therefore has no open proceedings site, which is why its roster comes from the
  virtual site and its PDFs from Semantic Scholar's open-access links (100% coverage
  on ICLR 2024, with arXiv at 83% as a second route).
- **The virtual sites are ahead of the proceedings sites.** NeurIPS 2025 lists 5,858
  papers on `neurips.cc` while `papers.nips.cc` still has only a 64-paper Creative AI
  track. Without the virtual site the newest year — exactly where reading starts —
  would be missing.
- **Semantic Scholar files papers under the year of first posting.** Matching an
  ICLR 2024 roster against `year=2024` hits 42% of it; widening to `2023-2025` hits
  94%. The crawler always searches a ±1 year window and matches back by exact
  normalised title.

PDFs are fetched lazily, only for papers that reach the front of the queue. The full
corpus would be 400-600 GB; the queue will consume a few thousand papers over several
years.

Which copy is read: a conference's own camera-ready PDF first (PMLR, NeurIPS, CVF,
ACL, OpenReview, MICCAI's open-access site), then arXiv, then any other link. A
journal's or publisher's link comes after arXiv because it is often not the typeset
article: Cataract-LMM's link on nature.com was the accepted manuscript, stamped
ARTICLE IN PRESS across 44 pages of sixteen sizes, where arXiv had the authors' own
copy. `repdf` switches a paper already downloaded and finds every note's passage again
in the new copy.

## Nightly schedule

```powershell
.\scripts\register-nightly.ps1
```

Registers `scripts/nightly.ps1` with Windows Task Scheduler for 00:00 daily. Each
night it refreshes the frontier, delivers the next paper, prefetches the ten after
it, runs the whole 深入分析 through the selected AI profile on the next papers
(`analyze --scheduled`: deep dive and close reading, marked passages, 承先 and 啟後
with the 研究脈絡), and opens the reader — so the window is already showing tonight's
paper, explained and placed in its field, the next time you touch the machine. The
three parts used to be scheduled separately with different budgets, so a paper
could arrive explained with an empty 引用 tab.

How often and how much is the reader's **分析排程** (top bar): every night (the
default), every two days, weekly, or only on request; how many queue papers (4) and
list papers (3); and whether the window says which papers are ready. The task itself
still fires every night and the run decides whether it is due, so changing the
setting never needs the task re-registered.

`-StartWhenAvailable` is set, so a night the machine spent asleep runs when it wakes
rather than being skipped. Nothing is ever served twice: a delivered paper keeps its
state through every re-rank.

```powershell
Get-ScheduledTask -TaskName 'paper-daily nightly' | Get-ScheduledTaskInfo   # check
Start-ScheduledTask -TaskName 'paper-daily nightly'                        # run now
Unregister-ScheduledTask -TaskName 'paper-daily nightly'                   # remove
```

Logs land in `nightly.log` in the data folder (`data/`, or `PAPERFACT_DATA`), as UTF-8: the script sets the console output
encoding first, because PowerShell otherwise decodes Python's output with the
console code page and the Chinese progress lines came out as mojibake.

### Why not a cloud routine

A scheduled cloud agent would run with the machine off, and it was tried. It cannot
reach `papers.db` — over 100 MB, local only — so it has to work from a synced slice;
and more decisively, writing its result back raises an approval prompt that nothing
answers at midnight, so the run parks with the deep dive written and unsaved.
`auto_mode_allow` and `permission_mode` are accepted by the RemoteTrigger API and
then silently dropped, so there is no pre-approval path through it.
`docs/nightly-routine-prompt.md` keeps the prompt, and `sync-queue` / `reader-doc`
still feed the web reader, if you want that route anyway.

One RemoteTrigger trap worth recording: an `update` whose `job_config` omits `events`
wipes the routine's prompt. Always resend the whole `job_config.ccr`.

The full toolchain — every tool, service, rate limit and cache path — is documented in
[`docs/toolchain.md`](toolchain.md).

## When a crawl goes wrong

Semantic Scholar rate-limits hard without an API key, and a full bootstrap walks
straight into it. Two things follow:

- **`enrich` never aborts on one bad venue-year.** A failure is logged and skipped,
  because author lookup and scoring run *after* the venue loop — an exception there
  would leave the corpus with no scores and no queue at all.
- **Re-running is cheap and is the fix.** Every HTTP response is cached, so a second
  `enrich` replays from disk and only retries what actually failed:

```powershell
.\scripts\dev.ps1 enrich --years 2015-2026   # picks up whatever was skipped
.\scripts\dev.ps1 rank
```

`status` shows the `enriched` and `scored` counts per venue-year, which is how you
tell whether a year is genuinely done.

## Known limitations

- Award labels are best-effort. The virtual sites are inconsistent across years —
  NeurIPS 2022 exposes spotlights but no orals — so some years contribute no award
  signal and ranking falls back to its other components.
- Paper-type classification is keyword-based and deliberately shallow. It sorts a
  ranked list; it is not reliable for any single paper.
- Abstract coverage is about 75%. The extracted PDF text covers the gap for any
  paper that actually gets delivered.
- Pre-2018 ICLR has no virtual site and no open proceedings, so those years use a
  looser Semantic Scholar roster that admits some workshop papers.
