# Development reference

## Maintenance and development branches

- `master` is the daily-use 0.4.x line. Fixes and UX polish land here first and
  ship as 0.4.4, 0.4.5, and subsequent maintenance releases.
- `feature/0.5-sync-foundation` holds unfinished 0.5 work and identifies itself
  as `0.5.0.dev`. Merge `master` into it regularly; merge it back only for 0.5.0.
- Use separate checkouts and virtual environments. A branch switch in the
  checkout used by a running app or MCP server is not a deployment method.
- Run development with `PAPERFACT_DATA` pointing to an independent copy. Use
  SQLite backup for a live database, real copies for attachments, and no shared
  writable links. Do not copy sync device identity or account credentials.
- Daily GUI, CLI, MCP and scheduled jobs must all use the maintenance executable
  and daily workspace. Explicit `--workspace` overrides also need review.
- Already-running processes keep their old paths and imported code. Save work
  and restart them after changing the checkout or data configuration.
- Published updates belong to installed maintenance copies. Development builds
  follow Git; they must not offer a released installer as a development update.
- A development snapshot is disposable and does not synchronize changes back.
  Move wanted research using reviewed list-package export/import, not by
  replacing the daily database with a development database.


This file describes the current implementation, including its bundled ML workflow.
See [the architecture](architecture.md) and [the workflow design](agent-workflows.md)
for the separation between working services and planned extension points.

## Architecture

```
src/paper_daily/
  config.py           paths, score weights, year range
  store.py            SQLite schema: papers, authors, refs, queue, reading_log
  http.py             cached, per-host throttled fetcher (+ POST for S2 batch)
  sources/
    virtual_site.py   rosters + oral/spotlight labels from iclr.cc / icml.cc / neurips.cc
    pmlr.py           ICML proceedings, with year -> volume auto-discovery
    neurips.py        NeurIPS proceedings
    arxiv.py          arXiv metadata and PDFs, for list papers with no proceedings
    cvf.py            CVF Open Access: CVPR / ICCV / WACV originals
    openalex.py       every other publisher, and the open-access link they do not give
    crossref.py       the reference list, with the numbers the paper printed
  resolve.py          the PDF hunt: CVF, then arXiv, then OpenAlex
  cites.py            what each reference is doing in the paper that cites it
  followups.py        what came after a paper across the field, and which of it to read
  enrich/s2.py        Semantic Scholar: citations, authors, references
  rank/
    classify.py       principle / method / system / application / benchmark
    canon.py          the guaranteed-reading list
    score.py          signal -> percentile -> weighted score
  queue.py            queue construction, canon injection, companion expansion
  fetch.py            lazy PDF download + text extraction
  figures.py          figures and tables rendered out of the PDF by caption
  pocket.py           the phone page: ticked papers, their PDFs, notes and analysis
  pocket_reader.html  its template (pdf.js viewer, tabs)
  share.py            a page for other people: draft Markdown, then build
  share_page.html     its template (marked.js, contents rail, note slips)
  lists.py            bibliography -> switchable reading list
  brief.py            assembles the briefing pack
  dive.py             writes deep dives ahead of the reading
  llm.py              model facade, task routing and local usage receipts
  ai_types.py         shared requests, completions and token usage
  ai_profiles.py      independent connections and per-feature AI selection
  ai_providers.py     CLI, vendor and custom service adapters
  translate.py        quick machine translation (Google, keyless), with the model as fallback
  repdf.py            swap a paper's PDF and re-anchor its notes by their quoted passages
  resources.py        a paper's code, data and models: from its text, Hugging Face, GitHub
  analyze.py          one call that makes whatever a paper lacks: PDF, dive, 承先, 啟後
  venues.py           short venue names, and where a preprint was published since
  pipeline.py         crawl -> enrich -> score -> queue
  cli.py              command line interface
  desktop/
    main.py           the window: queue screen + reading desk
    queue_view.py     the queue as a model/view list, so 5000 rows filter instantly
    add_dialog.py     ＋ 新增 → 加入論文: corpus search for the queue, citation lookup for a list
    pdfselect.py      mouse selection over Qt's PDF view, which has none of its own
    ai_style.py       the violet spark look shared by every button that starts AI work
    analysis_bar.py   深入分析 beside the tabs: what exists, and the button for the rest
    analysis_settings.py  分析排程: the nightly analysis settings, and the "ready" strip
    cites_pane.py     the 引用 tab: lineage on top, why each reference is cited below
    pdfpane.py        native Qt PDF view, with a PyMuPDF page-render fallback
    md.py             Markdown -> the HTML subset QTextBrowser renders correctly
    ask.py            background questions through the shared AI facade
    ai_dialog.py      connection profiles and per-feature AI settings
    figure_pane.py    the 圖表 tab: extraction on a worker thread; a click jumps the PDF
    fetcher.py        downloads the PDF of a paper opened outside the prefetch buffer
    import_dialog.py  ＋ 新增 → 建立清單: paste a bibliography, import it as a list
    pocket_dialog.py  帶出門: build the phone page from the ticked papers
```

Everything written lives under `data/` (gitignored): `papers.db`, `httpcache/`,
`pdf/`, `text/`, `briefs/<date>/`.

## Public API

```python
from paper_daily import pipeline, queue, brief
from paper_daily.store import connect

pipeline.crawl([2026, 2025], ["ICLR"])  # roster
pipeline.enrich([2026, 2025], ["ICLR"])  # citations, authors, awards
pipeline.rank_and_queue(per_year=400)  # score + build queue
pipeline.expand_lineage(paper_id)  # queue a paper's ancestors
pipeline.status()  # corpus + queue summary

with connect() as conn:
    rows = queue.next_papers(conn, 5)  # peek without consuming
    row, path = brief.deliver_next(conn)  # pop + build pack
    queue.mark(conn, row["id"], "read")
```

```python
from paper_daily import dive, figures, lists, llm

llm.settings()                       # resolved backend, model, key presence
llm.describe(); llm.probe()          # one line for a human; a live one-word check
body, reason = llm.complete(prompt, system=None, timeout=900)

dive.dive_ahead(3)                   # fill the buffer
dive.dive_ahead(paper_id=pid)        # rewrite one paper, read or not
figures.extract(paper_id, pdf_path)  # [Figure(label, caption, page, path, kind)]
lists.import_list("Quant refs", raw) # bibliography -> switchable list
lists.all_lists()
lists.add_paper("quant-vlm", "GPTQ: Accurate post-training quantization ...")
lists.remove_paper("quant-vlm", paper_id)

queue.add(conn, paper_id)            # by hand, at the front, role 'manual'
queue.remove(conn, paper_id)         # skipped, not deleted
store.search_papers(conn, "outlier quantization")   # the whole corpus
```

Every function that calls a model returns `(result, reason)` rather than raising or
returning a bare `None`: a whole night of dives once failed on an expired login and
every log line just said "failed", which reads the same as the model declining.

## Development

Reusable development patterns and their cross-agent synchronization are described
in [development skills](development-skills.md). Edit canonical `skills/` content;
the full test suite checks that discovered copies stay synchronized.

The default check protects the critical user journeys:

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

On macOS/Linux use `.venv/bin/python scripts/check.py`. On Windows use
`scripts/check_bounded.py` instead of `scripts/check.py` to enforce a 300-second
wall budget, at most two logical processors and a 25% CPU cap for the child tree.
The bounded entry currently fails closed on other operating systems; no equivalent
native resource cap has been verified there.

The `critical` default selects existing behavior tests for startup, list packages
and PDFs, notes and durable Q&A, AI configuration isolation, offline convergence
and conflicts, and backup/restore. The exact selectors live in
`scripts/check.py` (`CRITICAL_JOURNEYS`). The console names these journeys and
`build/check-latest.json` records their selectors, stage outcomes and durations.
This is a curated regression gate, not exhaustive coverage or installed-device
acceptance. Missing selected tests fail rather than silently reducing coverage.

For an edit, run only the affected behavior and its failure boundaries:

```powershell
.\.venv\Scripts\python.exe scripts/check_bounded.py --profile focused --python tests/test_check_script.py
```

Python selectors accept `::test_name`; `--frontend tests/test_name.mjs` and
`--mobile` select frontend or mobile checks. `--profile docs` checks documentation
contracts. Explicit selectors require `--profile focused`. Every profile also
scans committable files for secrets and runs Ruff.

A focused pass permits a scoped development checkpoint. Integration requires the
critical gate plus affected tests. Use `--profile release` for the curated release requirements described in
[the test map](testing/README.md#keep-the-suite-small-by-testing-requirements).
Keep historical regressions available through explicit `--profile full` for deep
diagnosis when warranted; it is not a mandatory release gate. It includes every Python, frontend and mobile test and
requires Node.js. The Windows bounded entry allows at most 1800 seconds for release/full
profiles, including child processes. A timeout is incomplete validation, never a pass; investigate the slow
area rather than silently extending the limit. Beta validation and packaging
must fit a shared 20-30 minute budget. Do not run parallel full checks or use
`-n auto` on the owner's machine.

Report the actual selected cases, results and untested boundaries. Critical or
focused success never sets `full_check_passed`. Native Windows/Mac installation,
upgrade and real-provider checks remain separate release acceptance.

The runner stops on the first failing test and prints actual stage durations and
pytest's 20 slowest test phases. After 60 seconds in one test, pytest prints thread
stacks to help diagnose a stall; this is a diagnostic warning, not an estimated
completion time or an automatic pass. Keep those raw debugging logs local.
The latest report is marked running before work starts, so a forcibly killed
process cannot leave the previous run's success looking current.
Pytest percentages count completed cases within its own phase, not elapsed time,
coverage, or completion of the whole check. `build/check-latest.json` records the
latest run's scope, durations and outcome, including failure or interruption.
It contains no environment values or raw test output and is ignored by Git.
This local report is a debugging aid, not a signed certificate or a substitute
for recording the tested commit and test counts. Preserve the terminal log when
investigating slow cases. Profile first; only parallelize tests after proving
their isolation, especially Qt application state and subprocess fixtures.

A Windows reproduction on 2026-10-27 exposed worker starvation in the activity
test's repeated Qt event pumps: the unmodified fixture failed after 317.06s.
Yielding Python execution between pumps let both worker outcomes pass in a
diagnostic experiment; adding `time.sleep(0)` to that test helper then passed all
30 activity cases in 11.27s. The visible-result assertions, loop bound and worker
timeout were unchanged. This is local evidence for that helper, not proof that
every slow UI test has the same cause; do not extend timeouts or patch every wait
without reproducing the relevant failure.

The check starts with a privacy scan of every file a commit could pick up (tracked,
plus new files that are not ignored). It fails on common credential shapes
(Anthropic, OpenAI, GitHub, Google, Slack and AWS keys, private key blocks) and on
your own identifiers, listed comma-separated as `PAPERFACT_PRIVATE_TERMS` in the
ignored `.env`, so the check itself never publishes them:

```
PAPERFACT_PRIVATE_TERMS=you@example.org,your-username
```

A finding is reported as `path:line: kind`, never with the matched text. Binary
files are skipped, so check screenshots by eye before adding them.

Desktop action tests use isolated databases and simulated provider responses.
`tests/test_ui_stress.py` exercises repeated clicks during list creation/export,
AI login/usage work, background AI failures/retries, subprocess startup failures,
panel toggles, slide navigation, and global/per-feature model changes. It asserts
visible recovery and saved data, including no duplicate jobs. Related presentation,
reader, navigation, and transfer tests cover their normal and error paths.

For every changed button or shortcut, add tests for the observable result and
applicable cancellation, repeated activation, retry, and stale-result cases.
Shared-worker tests alone are not exhaustive coverage of every button. Real OAuth,
provider availability, native drag/drop, and external publishing still need separate
manual integration checks; never stress-test those against a user's live account.

List management regression coverage lives in `tests/test_list_management.py`:
identity-preserving rename, repeated list ordering, a 5,000-paper permutation,
stale/filtered drag rejection, failed writes, and one-time legacy queue adoption.
Windows native drag/drop was also checked on 2026-10-19 in an isolated workspace
with three lists and eight papers: moving the first list to the end saved
`[1, 2, 0]`; moving paper 1 below paper 3 saved `[2, 3, 1, 4, 5, 6, 7, 8]`.
The list remained visible after the drop. No research account or live list was
used for that manual check.

AI account picker checks on 2026-10-19: after a safe Windows app restart, the live
Claude account page displayed the existing 15 local calls inline, with unreported
tokens explicitly unknown. The model dropdown showed service selection and
unversioned alias labels. Browsing did not save a different account or model.
Codex's two quota bars were visually checked with fixture responses; this check
did not validate live Codex/Gemini quotas, run OAuth login, or call a paid model.
Picker/usage/task tests cover alias IDs, stale account results, retry, missing and
partial usage, and visibility of both standard quota windows. The stress suite
also floods inline refresh and close requests while a simulated query is running.

On 2026-10-20, the installed Claude Code 2.1.304 control protocol was checked live
with no user prompt: `get_usage` returned a Max plan with five-hour and seven-day
utilization (5% and 68% in that snapshot). The fixture-based quota tests pin this
shape without credentials or transcript content. Cache tests cover deduplication,
per-account invalidation, startup prefetch and updates arriving during a query.
Product-event tests cover opt-in/withdrawal, closed fields, parent/child trace links,
worker context propagation, retention, and reviewed-export cancellation/failure/retry.
After a safe native Windows restart, opening AI settings showed the prefetched
Claude quota immediately (6% / 68% in the later snapshot), both bars and the update
time. The feedback page showed consent unchecked, no events, and export disabled.
Browsing these pages did not enable collection or change the selected AI/model.
No paid generation or central upload was performed in this manual check.

Later on 2026-10-20, Gemini CLI 0.38.2 cached OAuth loaded successfully but the
official Code Assist account response contained only allowed/ineligible tiers:
`UNSUPPORTED_CLIENT`, no current/paid tier and no project. The app therefore shows
the rejection rather than inventing model percentages. This also appears in the
[upstream report](https://github.com/google-gemini/gemini-cli/issues/28846).
Quota fixture tests cover valid per-model fractions (including zero/full),
missing buckets, invalid values, sanitized failures and no onboarding/generation.
Monitor tests cover unsaved terminal accounts as well as saved profiles.
Native Windows UI checks after restart showed Claude Max with both quota windows,
Codex prolite with its returned weekly window, and Gemini's explicit upstream
rejection. The account picker and task routing page use the workspace palette.
Browsing providers and cancelling the routing page kept the global Claude setting.
The final quota layout removes duplicate text over the coloured bar and bounds
single-window height; percentage values remain in the text label above each bar.
Gemini's successful per-model display is fixture-tested, not verified on this
rejected live account. The receiver document is a design, not a deployed service.

Set `S2_API_KEY` for a much higher Semantic Scholar rate limit (free, from
semanticscholar.org/product/api). Without it the crawl still works, just slower.

GitHub answers 60 anonymous API calls an hour, which one `resources` pass over a
reading list uses up. Set `GITHUB_TOKEN` (or `GH_TOKEN`), or be logged in with the
`gh` CLI, whose token is picked up automatically, for 5,000.
