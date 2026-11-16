# Toolchain

Developer reference for Paperfact. For ordinary installation, use the
[platform guide](install.md). Source setup installs Python dependencies and
assets; AI CLIs, Node.js for tests, and Linux system libraries are separate
prerequisites where applicable.

```powershell
.\scripts\setup.ps1      # Windows
```
```bash
./scripts/setup.sh       # macOS / Linux
```

Verify with `.\scripts\dev.ps1 doctor` on Windows or
`bash scripts/dev.sh doctor` on macOS/Linux. It reports local prerequisites
without making AI calls.

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

Installer-building tools above are needed only to make installers
(see [Releasing](releasing.md)). Qt still depends on native desktop libraries;
the Linux build workflow lists the packages used on Ubuntu. The downloads outside `uv sync` are the fonts and the renderers
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

## Packaged local acceptance

The existing `scripts/demo_workspace.py` also exposes
`acceptance_package(destination) -> dict`: synthetic three-original Lineage material
for offline import/audit/re-export and manual cross-device reading. It uses the
installed PyMuPDF and production package validators, an explicitly bound empty
fixture workspace, and no provider/test-framework dependency. The packaged verifier
creates it automatically; manual commands are in the Mac acceptance guide.

Run `python scripts/verify_built_app.py <built-app-folder> <new-output-folder>`
from the matching development environment after building. This uses generated
research and isolated account/data homes. It checks local startup, package
roundtrip and CLI/MCP boundaries, plus Launch Services foreground behavior on
macOS (requires Apple Swift). It does not deploy sync or log into a real account.

The Mac GitHub job passes `--dmg dist/Paperfact-<version>-macos-arm64.dmg`.
This CI-only option requires the matching clean repository/workspace/commit and
exact generated artifact paths. It hashes the bounded image and complete app
closure, mounts the image read-only at its fresh owned output path, copies
`Paperfact.app`, verifies exact content/execute permissions/internal links, then
detaches the owned volume. The existing research/CLI/MCP/foreground workflow runs
once from that copy, after detaching; it is not duplicated against the build app.
Bounds are 1 GiB for the DMG, 20,000 bundle entries and 2 GiB total bundle files.
Unexpected mount replies, changed bytes/owners, copy/detach failure and interruption
cannot produce acceptance. Cleanup preserves a primary failure stage; a secondary
cleanup failure is a separate categorical `cleanup_failure`, with raw logs local.
`mac_dmg` records image/bundle hashes and copy/detach/workflow completion. It keeps
quarantine, notarization and older-installed-upgrade checks explicitly false.
Native commands (`hdiutil`, `ditto`) are already used by the Mac build; no new SDK
or CI job is introduced. Programmatic mount output uses Apple's supported
[`-plist` interface](https://developer.apple.com/forums/thread/721232).
[Run43859467437](https://github.com/puddings-world/Paperfact/actions/runs/43859467437)
accepts this actual native route for clean30b5776 on macOS/arm64. Its report
records `copied`, `detached` and `workflow_from_copy` as true; quarantine,
notarization and older-installed-upgrade checks remain false. Windows controller
fixtures are separate from that native result.

The Windows GitHub job additionally passes
`--installer dist/Paperfact-<version>-windows-x64-setup.exe`. This option refuses
non-Windows/nonmatching CI checkouts, dirty or mismatched build identities,
unexpected paths and existing install destinations. It creates only
`build/<new-output>/installed-app`, uses the setup acceptance mode (no shortcuts,
registration or automatic launch), then checks installed CLI/reader/MCP behavior,
same-version reinstall and uninstall. Each installer action checks that the
bounded synthetic research tree is unchanged; the report records the setup
payload SHA-256 and exact failure stage. Before taking each snapshot, it waits
at most 30 seconds for recognized local research producers to release their
native locks. Unknown lock entries, a timeout or unreadable research still fail;
no coordination file is deleted or omitted from the final fingerprint. Links/reparse points and changed owned
paths are refused. No reboot, application closing or application restart is
requested. Do not use this flag for an owner's installed app. It does not test
0.4-to-0.5 upgrade, registry/shortcut integration or physical-device acceptance.

`report.json` records the active/completed checks, frozen build identity when
available and categorical failure. It is written during the run, not only on
success; only `status: passed`, `passed: true` and exit code 0 accept the checked
local journey. A hard kill may leave an incomplete `running` record. Failed
checks exit 1; Ctrl+C exits 130. Every retry needs a new output directory.
Failed runs also keep a bounded `failure-detail.log` with private exception
context for local diagnosis; it is not part of the categorical report.
Review the report before sharing; raw `.log` files are separate local diagnostic
material. See [release checks](releasing.md) and [Mac acceptance](testing/mac-acceptance-0.5.md).

## Diagnosing a slow window

The app always records freezes over 0.25 s, with the code location only, to
`ui-stalls.log` in the data folder. For slowness made of many short busy moments,
start the app with `PAPERFACT_PROBE=1`: once a minute it appends to
`<data>/diagnostics/main-thread-<date>.log` how busy the window's thread was, its CPU
use and the busiest code locations. It is off unless set, never uploads and records
no paper content.

```powershell
$env:PAPERFACT_PROBE = "1"; .\scripts\dev.ps1 app
```

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
lazy. The data folder also holds original notes, edits and analysis: back it up
privately rather than treating the entire folder as a disposable cache.

`prune` previews legacy cleanup; `--yes` deletes only old HTTP cache files and
unclaimed PDF/text/figure paths. Saved SQL annotation reports, follow-ups,
context/resources, reading events/positions, later outcomes and Lineage owners
also retain their original files. Citation edges retain both local endpoints;
paper-scoped citation-graph presence retains its owner without parsing/rebuilding
its body. The annotation domain supplies its own closed table registry; other
positive owner tables are explicitly classified in storage. Unknown optional
owner-table shapes, substituted owner views or invalid owner identities stop
cleanup for review.
Current local offline intent and owners in native
document desired/applied/intent tables keep their legacy files, including inactive
or superseded records. Before each removal, claims are re-read under a SQLite
writer reservation held until that target's removal completes. A claim committed
during earlier filesystem observation protects all remaining files of its paper;
a preview is not durable permission to delete. A caller-owned open transaction
is refused without committing/rolling back its research. Each target releases its
read-only reservation; the entire file tree is not one long SQL transaction.
Invalid/unmapped retention found initially stops before any deletion. Late invalid
metadata, a busy writer or filesystem failure pauses the remaining plan. The
storage API raises `RetentionReviewError(cleanup_started=...)`; CLI exit2 reports
whether earlier cleanup may have completed, without claiming an all-or-nothing
filesystem rollback. Inspect storage and retry a fresh preview; completed removals
are not repeated. No raw SQL/path traceback is printed for these pauses. Removing offline intent allows ordinary cleanup only if no other
research/document owner remains. This is not a synchronized research deletion.

Each supplied entry must match its actual cache/PDF/text/figure category; root
directories, disguised claimed-paper entries and linked/reparse paths are refused.
The immutable blob store, versions, pending/history/conflict assets and arbitrary
research directories are never scanned for deletion by this command. Automatic
reference-aware eviction, retention expiry and concurrent external filesystem
replacement are separate lifecycle work; no reclamation guarantee is claimed.

## Scheduled run

The nightly job runs `refresh` (to pick up newly published papers) then `today` (to
build the briefing pack), and a Claude session turns the pack into the deep dive. See
the [optional ML workflow](ml-daily.md) for setup.

The reference sync administration commands use the same locked Python runtime,
SQLite and HTTP dependencies as the app; no additional service SDK is required.
Run `paperfact sync-admin --help` for the explicit local setup entry point. This
is loopback development tooling, not a production hosting installation.


## Headless sync-service/operator environment

Run `scripts/setup-sync-service.ps1` on Windows or
`bash scripts/setup-sync-service.sh` on macOS/Linux. It uses `uv.lock`, Python 3.11
and the optional `gcp` extra in `.venv-sync`, leaving desktop `.venv` separate.
The Google Cloud Storage SDK and google-crc32c are locked operator/dev dependencies,
not ordinary client requirements. Setup only installs/shows offline help; it does
not discover ADC or create service/cloud state. [Publication/API and limits](gcp-backup-publication.md).
The desktop build configuration excludes cloud operator namespaces; real installer and Linux
operator acceptance remain separate from static/fixture checks.

## Static PWA deployment artifact

`scripts/build_mobile.mjs` uses the existing Node 22+ runtime and built-in modules
only: no bundler or npm dependencies. Exported worker/cache identities derive from
asset content; verification also checks the identity against the actual worker.
The source worker remains unchanged and older numeric-cache exports stay readable.
Export normalizes first-party CRLF to LF with strict UTF-8 and BOM preservation;
`vendor/` bytes stay opaque and exact. Raw source observations still reject edits
during export, even newline-only edits. Older CRLF-built artifacts remain verifiable.
CI supplies Node through setup-node. Build
with `node scripts/build_mobile.mjs --output build/mobile-web`, then verify against
the trusted content ID using `--verify build/mobile-web --expect SHA256`. The
output contains only the runtime allowlist, manifest and generated Nginx static
map; the host does not need Node. [Flags/API/limits and operator handoff](sync-service-admin.md#build-and-verify-the-public-pwa-artifact).
The Nginx example is a review artifact; Nginx/certificate provisioning and Linux
validation are external operator gates, not part of ordinary desktop setup.


Frozen acceptance also runs `instance-handoff`: the primary synthetic reader uses
its ordinary 20-second smoke close, while a second launch must exit within 15
seconds with the primary still alive. The second launch has a 60-second smoke
limit, so a duplicate window cannot pass by closing itself before the check.
The source-side Qt probe waits for the expected workspace instance endpoint;
primary/secondary logs stay private in the chosen output folder. Failure reaps
only the verifier-owned primary; no unrelated app or data directory is stopped.
This is a native packaged same-workspace check, not cross-version compatibility,
first-use consent acceptance, a different-workspace check or a physical Mac result.

The packaged verifier also runs `sync-protocol` through
`scripts/verify_sync_protocol.py`: `verify(command, folder, env) -> dict` starts the
provided CLI's `sync-admin init`, `issue` and two `serve --port 0` executions.
It verifies authenticated empty pull, a fresh execution identity after restart,
HTTP 428 for the stale identity, and a successful explicit handshake/pull. It also
pushes synthetic paper/citation-graph operations through verified-history routes,
independently checks acknowledgment hash steps, refuses an incorrect proof, checks
exact graph content and idempotent retry, and verifies retained history after
restart. A second same-authority listener must exit with code2 and guidance within
15 seconds while the first remains available. Each
listener has a 20-second startup limit and only its owned process is terminated
in `finally`, including failed assertions. Init/issue each have a 25-second limit;
HTTP calls have a five-second limit. Readiness and response reads are bounded.

`report.json` contains only `authenticated_pull`, `stale_execution_refused` and
`reconnected`, `citation_graph`, `citation_graph_retry`, `citation_graph_restart`,
`duplicate_listener_refused`, `verified_history`, `wrong_history_refused` and
`verified_history_restart` and `prototype_writes_refused` booleans under `sync_protocol`. The result contains no research or credentials.
CI uploads only the four named synthetic protocol logs (`init.log`, `issue.log`,
`first-listener.log`, `second-listener.log`), alongside its existing exact log paths.
It never uploads `device.json`, the authority database or the whole protocol folder.
This proves the packaged service boundary, not the frozen GUI client's sync flow,
proxy/HTTPS, physical devices, persistent authority epochs or production hosting.

Native candidate CI additionally runs the existing first-sync preservation
representative once per OS (three-minute cap). The Windows tag release selection
already includes it and therefore does not repeat it. This exercises native
file/version and private-text copy/restore behavior before packaging.


Candidate CI also runs six explicit source lifetime journeys per OS, with a
three-minute step cap: duplicate/bind-failure ownership, held-worker drain/lost
reply retry, actual process exit, database replacement/removal, incomplete-header
shutdown, and actionable CLI refusal with online backup. These share the existing
behavior tests; they do not expand the daily critical or release selector lists.


Frozen protocol acceptance additionally sends one valid operation to the old
unverified write route and requires HTTP412 before guarded admission/retry. The
negative verifier case injects false legacy-write success and must fail. Source-
only `python -m paper_daily` fixtures explicitly pin this checkout's `src`, because
the isolated environment intentionally drops inherited PYTHONPATH. A shared venv's
editable install may point at another worktree. The frozen binary verifier keeps
its clean environment and receives no source override.


## Pinned old-source upgrade preservation

Optional verifier flag: `scripts/verify_built_app.py BUILT NEW_OUTPUT
--legacy-source build/upgrade-baseline-0.4.3`. Existing `--installer FILE` remains
Windows CI-only; `--help` lists both. Output must be new; no owner install/data is
selected. The baseline is exact commit3abdf434555583ca4a6827892d54b487e9e40671
(version0.4.3, the published preview inspected2026-11-15), not a mutable latest tag.

Release CI fetches that exact commit, archives only `src` and the old
`scripts/demo_workspace.py` into a new ignored build folder, and passes the folder
to every native verifier. The verifier compares the complete source closure with
Git object bytes, rejects unknown/linked/changed files before execution, and uses
isolated homes/data/proxy settings. Only the old source child receives its explicit
PYTHONPATH; the candidate CLI receives no source override.

The old code creates a renamed list, saved reading flag, PDF, positioned Unicode
note/Q&A, manual highlight, deep reading and edited text-canvas deck. Old export
is the reference. The new CLI must first export the untouched old schema, then
run `init` (the desktop's schema initialization) and export again. Compare every
old research-column value, list/order, exported research and exact PDF/deck bytes;
new schema columns are allowed without treating them as old data. Do not substitute
row counts or a fixture initialized by the new code.
The probe observes new schema tables after init; a zero exit without those tables
is refused rather than reported as successful initialization.

`report.json.legacy_upgrade` contains baseline version/commit, categorical
preservation results and counts. `source_format_only=true`,
`older_binary_install_checked=false` and `gui_upgrade_checked=false` distinguish
this from an actual older EXE/DMG/AppImage upgrade. Without the flag the field is
null, not an implied pass. Local logs stay separate from the shareable report.
Git/source closure:4096 files/64 MiB total,4 MiB per source file; fixture snapshot:
100 rows/table and bounded files. This is a synthetic acceptance probe, not a
migration tool for arbitrary user directories or a same-user filesystem sandbox.

This probe exposed bundle export querying absent0.5 optional tables in0.4 data.
Known absent extensions now export as empty; an existing view or malformed table
is still refused rather than hidden. Export does not initialize or rewrite the
source merely to make a snapshot shareable.


Pinned source archives must use `git -c core.autocrlf=false archive ...`, even on
Windows. Git's archive conversion otherwise changes LF to CRLF and invalidates
exact blob provenance. The acceptance verifier deliberately refuses converted
bytes; never normalize its input to make a changed baseline pass. The workflow
recipe has a regression under inherited Windows autocrlf settings.


### Screenshot readiness

`scripts/screenshots.py OUT --demo` waits for saved reading preparation and the
exact WebEngine page/fonts, with a10-second deadline per stage. It refuses a
blank reading PNG instead of treating a widget grab as content acceptance. This
is diagnostic output, not an installed two-device UI test. CI screenshots use
Cocoa on macOS; the software `--disable-gpu` flag is scoped to that step only
([Qt diagnostic arguments](https://doc.qt.io/qt-6/qtwebengine-debugging.html)).
The daily app's graphics settings are unchanged. Local source captures with no
web assets use the plain view and must not be reported as typeset acceptance.

Screenshot rendering failures report only readiness booleans (page identity,
document completion, main element/text presence and loaded fonts), or a missing/
invalid callback category. The ten-second rendering gate and blank-surface refusal
remain unchanged; no research text is included in this diagnostic.
Unanswered rendering probes may be reissued once per second within that same
deadline, or when the exact page changes. Probe generations discard late replies;
a missing callback cannot permanently suppress the next probe. All original
page/text/font and nonblank-surface checks remain mandatory. This does not retry
an entire failed screenshot/build or certify the installed Mac reader.

The screenshot-only render trace retains at most24 load/patch state events, with
content-presence booleans rather than HTML or text. It records whether Python
still considers the requested body shown, distinguishing refused delivery from
an accepted patch without weakening readiness or publishing a blank image.

## Source-aware report package acceptance

`scripts/verify_source_report.py` is an internal helper invoked by the existing
`scripts/verify_built_app.py` workflow. It receives the actual packaged CLI and
the generated synthetic research ZIP. Its `source-aware-report` stage uses a fresh
workspace, a synthetic local profile and one loopback-only OpenAI-format endpoint.
No real login, account key, paid provider or external scholarly service is used.

It runs import, source-aware report generation, package export, retained-result
reading and cached generation through that executable. It checks the exact
original PDF hash/quotation location, separate requested/returned model IDs,
retained/exported report equality and no second model completion. One subprocess
has a45-second deadline; the fixture endpoint bounds request bytes and read time.
The report records named outcomes in `source_report`. A pass does not certify
every new report dialog, live scientific support, installed-device behavior or
hosted synchronization.

Source after 4cdca19 adds `scripts/verify_private_report.py` to that same stage.
It drives the production `JobHandoff` with a real QProcess and the selected CLI's
private stdin protocol. The child disk route is deliberately disabled; only the
captured synthetic task route can succeed. It checks unchanged disk settings,
no credential in argv/environment/user output, then restores the local fixture
route for cached CLI retry. Output is bounded to 1 MiB and the owned child is
stopped at its deadline. Invalid handshake/zero exit and timeout are explicit
failure cases. Named outcomes are `private_handoff` and
`child_disk_settings_ignored`. No new command, tool installation or product hook.
The host desktop component is source code; only the selected CLI may be frozen.
Delivered e5eb093 artifacts predate this extension. Actual frozen execution of
the new stage and the full desktop dialog journey remain separate gates.


The existing native authority-lifetime CI stage also selects the source same-file
revocation regression, the bounded control publication/restart/crash cases, and
stale-preview offline/retained-document cleanup representatives on every desktop
OS. It retains its three-minute stage budget; it does not add a full suite or a
second build. These synthetic cases exercise platform-specific file replacement,
locking and process exit. They do not prove real power-loss or device/hosted sync.


## Offline GCP pilot review preparation

`deploy/gcp/prepare.py` uses only the existing Python3.11+ toolchain and standard
library. It renders the adjacent three deployment templates from the closed
`pilot.example.json` shape, retaining template/output hashes and open gates in
`review.json`. It has no cloud, subprocess, credentials, service installation or
scheduling dependency. Existing review directories are never overwritten;
interrupted output is retained. [Command/options and field meanings](gcp-sync-pilot-plan.md#prepare-one-offline-configuration-review).
Run `scripts/check_bounded.py --profile focused --python tests/test_gcp_pilot_prepare.py`
for the small renderer/actual CLI selection; this is not Linux/GCP acceptance.
