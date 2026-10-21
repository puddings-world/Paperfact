# Toolchain

Everything needed to build, test and run `paper-daily`. After `git clone` plus one
setup command the project is fully functional; no manual tool hunting.

```powershell
.\scripts\setup.ps1      # Windows
```
```bash
./scripts/setup.sh       # macOS / Linux
```

Verify with `.\scripts\dev.ps1 doctor`, which checks each item below and reports what
is missing.

## Tools

| Tool | Version | What it does | Installed by | Used in |
|---|---|---|---|---|
| Python | >= 3.11 | Runtime. 3.11 is pinned by the setup script. | `uv venv --python 3.11` | everything |
| uv | any recent | Package manager and venv creator. The only dependency installer this project uses. | setup script (downloads it if absent) | setup |
| httpx | >= 0.27 | HTTP client behind the cached fetcher. Chosen over `requests` for its timeout semantics and HTTP/2. | `uv sync` | `src/paper_daily/http.py` |
| PyMuPDF | >= 1.24 | PDF text extraction. Fast, no external binary, handles the two-column conference layouts these venues use. | `uv sync` | `src/paper_daily/fetch.py` |
| pytest | >= 8 | Test runner. | `uv sync --extra dev` | `tests/` |
| ruff | >= 0.5 | Formatter and linter. | `uv sync --extra dev` | development |
| PyInstaller | >= 6.10 | Turns the app into one folder with its own Python: `Paperfact` (windowed) and `paperfact-cli` (console). | `uv sync --extra build` | `packaging/paperfact.spec`, `scripts/build_app.py` |
| Inno Setup | 6 | Windows installer (per-user, no admin). Only for building installers. | `winget install JRSoftware.InnoSetup`; the release workflow installs it with choco when missing | `packaging/windows/paperfact.iss` |
| `hdiutil`, `iconutil` | built in (macOS) | The `.dmg` and the `.icns` icon | ships with macOS | `scripts/build_app.py` |
| appimagetool | 1.9.1 (pinned) | Packs the Linux build into one AppImage | downloaded by `scripts/build_app.py` into `build/` | `scripts/build_app.py` |

No SDKs, JARs or native binaries are required to run or develop, so there is no
`tools/` directory to download into; the build-only tools above are needed only to
make installers (see [Releasing](releasing.md)). The downloads outside `uv sync` are the fonts and the renderers
the reading views typeset with:

| Asset | What it does | Installed by | Used in |
|---|---|---|---|
| Noto Sans TC, JetBrains Mono (`fonts/`, gitignored, 12 MB) | The reader's UI and mono faces on every platform, so Windows and macOS wrap text the same way; Noto Sans TC is also the face slide exports name | `paperfact fonts` (called by the setup scripts), pinned to a google/fonts commit and checked by sha256 | `src/paper_daily/fonts.py`, `src/paper_daily/desktop/fonts.py` |
| KaTeX 0.16.11, highlight.js 11.10.0, Mermaid 10.9.1 (`vendor/web/`, gitignored, 5 MB) | Typeset formulas, highlight code and draw diagrams in 深度講解, 筆記 and 問 AI (a Qt WebEngine view), and in the pocket page | `paperfact web-assets` (called by the setup scripts), pinned versions checked by sha256 | `src/paper_daily/web_assets.py`, `src/paper_daily/desktop/rich_html.py`, `src/paper_daily/pocket.py` |
| markdown-it-py, mdit-py-plugins | Markdown with `$…$` maths for those views | `uv sync --extra app` | `src/paper_daily/desktop/rich_html.py` |
| `iconutil` (macOS, built in) | Turns the drawn icon into `Paperfact.icns` | ships with macOS | `scripts/make-app-mac.sh` |

Without the fonts the app still runs on each platform's own CJK font; without
the renderers (or without pyside6-addons, which carries Qt WebEngine) the reading
views fall back to Qt's plain rich text, showing formulas as their source.
`doctor` reports either missing. Tests set `PAPERFACT_PLAIN_VIEWS=1` (in
`tests/conftest.py`) so no Chromium starts per test; `node --test tests/*.mjs` runs
the JavaScript tests.

## External services

The paper sources require no account; one benefits from a free key. The language
model is the one place that needs either a subscription or a paid key -- see
**Language model backends** below.

| Service | Used for | Auth | Limit |
|---|---|---|---|
| `iclr.cc`, `icml.cc`, `neurips.cc` | Accepted-paper rosters, oral/spotlight labels, per-paper authors and abstracts | none | throttled to ~2 req/s locally |
| `proceedings.mlr.press` | ICML proceedings and volume index | none | ~3 req/s |
| `raw.githubusercontent.com` | ICML PDFs | none | generous |
| `papers.nips.cc` / `proceedings.neurips.cc` | NeurIPS proceedings and PDFs | none | ~3 req/s |
| `api.semanticscholar.org` | Citations, authors, h-index, reference graph, ICLR PDFs | optional API key | **~1 req/s without a key**, much higher with one |
| `arxiv.org` | Fallback PDFs | none | 1 req/3s (their published policy); answers **406** when it wants you to slow down, which is retried, not treated as "no such paper" |
| `api.github.com` | Whether a newer Paperfact is out (the update banner), at most once a day | none | 60 req/hour per IP, unauthenticated |
| `api.openalex.org` | Venue, year, authors and the open-access PDF for everything that is not an ML conference paper | none (a `mailto` gets the polite pool: set `PAPERFACT_EMAIL` to your address) | ~100k/day, no practical limit here |

### Semantic Scholar API key

Optional but worth it: without a key the crawler spends most of its wall-clock time
waiting out the rate limit, and 429s are frequent.

1. Request a free key at <https://www.semanticscholar.org/product/api>.
2. Set it before running:

```powershell
$env:S2_API_KEY = "your-key"
```
```bash
export S2_API_KEY=your-key
```

Or put `S2_API_KEY=your-key` in the checkout's gitignored `.env` (see `.env.example`).

`doctor` reports whether the key is set.

### Not used: OpenReview

OpenReview would be the natural source for ICLR, and is deliberately not used. Its
`/notes` API returns `ChallengeRequiredError` (HTTP 403) to anonymous clients, and
`openreview.net/pdf?id=...` 403s as well. Both were verified against the live service.
ICLR is served from the conference virtual site plus Semantic Scholar instead.

## Language model backends

Three features need a model: `dive-ahead` (writing a deep dive), `import-list`
(parsing a pasted bibliography), and the reader's 問 Claude tab. All three call
`paper_daily.llm.complete`, which resolves one of three backends.

| Backend | Selected by | Transport | Auth | Cost |
|---|---|---|---|---|
| `cli` | the `claude` binary on PATH | `claude -p`, prompt on stdin | the CLI's own signed-in session | included in a Claude subscription |
| `anthropic` | `ANTHROPIC_API_KEY`, or `llm --backend anthropic --key ...` | `POST https://api.anthropic.com/v1/messages` via httpx | `x-api-key` header | per token |
| `openai` | `OPENAI_API_KEY` (+ `--base-url`) | `POST <base>/chat/completions` via httpx | `Authorization: Bearer` | per token, or free against a local server |

Neither vendor SDK is a dependency: between them the two API backends need one POST
and one JSON path, which is not worth two more packages in the lockfile.

Resolution order: `PAPER_DAILY_LLM` → `backend` in `data/llm.json` → auto (CLI, then
`ANTHROPIC_API_KEY`, then `OPENAI_API_KEY`, then nothing). `paper-daily llm` prints
what resolved; `--test` and `doctor` both probe it with a one-word question, because
being configured is not the same as being able to answer.

Prompts are sized for a 200k-token context: a briefing pack with the full text runs
to ~50k characters, and `DEFAULT_MAX_TOKENS` is 16k because a dive plus its reasoning
needs the room. A small local model will fit the prompt but tends to ignore the
ten-section structure; the `cli` and `anthropic` backends are what the prompts are
tuned against.

The prompt carries the paper's text, which is public, plus the reader's own notes
history in the lineage section. Nothing is sent anywhere except the selected backend.

## Pipeline stages and which tool each uses

| Stage | Command | Tools / services |
|---|---|---|
| Roster | `crawl` | virtual sites, PMLR, papers.nips.cc (httpx) |
| Enrichment | `enrich` | Semantic Scholar bulk + author batch (httpx) |
| Scoring | `rank` | pure Python |
| Delivery | `today` | PDF host + PyMuPDF |
| Refresh | `refresh` | same as crawl + enrich, newest years only |

## Caching and disk

All network responses are cached under `data/httpcache/`, keyed by URL. Re-running any
stage is therefore cheap, and a failed run can be resumed by rerunning the same
command.

| Path | Contents | Rough size |
|---|---|---|
| `data/papers.db` | SQLite corpus, queue, lineage | ~80 MB for 2015-2026 |
| `data/httpcache/` | Raw HTTP responses | ~500 MB after a full bootstrap |
| `data/pdf/` | Downloaded PDFs, lazily | ~5 MB per delivered paper |
| `data/text/` | Extracted text | ~30 KB per delivered paper |
| `data/briefs/<date>/` | Briefing packs, deep dives, notes | small |
| `data/figures/<paper_id>/` | Figures and tables rendered from the PDF, plus an index.json | ~1 MB per paper |
| `data/llm.json` | Model backend and key, if not taken from the environment | tiny |

Downloading every PDF in the corpus would be 400-600 GB, which is why fetching is
lazy. Deleting `data/` is a clean reset; every stage rebuilds it idempotently.

## Scheduled run

The nightly job runs `refresh` (to pick up newly published papers) then `today` (to
build the briefing pack), and a Claude session turns the pack into the deep dive. See
the "Nightly schedule" section of the README for setup.
