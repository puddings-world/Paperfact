# Paperfact handbook

The full guide. The [README](../README.md) is the short tour.

*The perfect way to read papers, take notes, and share ideas.*

Paperfact is a desktop research workspace for organizing papers, building reading
lists, and keeping notes in your own local database. Bring papers from any field,
read at your own pace, and connect the AI service you prefer.

Its AI-assisted workflow starts with rough bibliography text: paste references,
let the configured AI help parse them, and let Paperfact look up metadata and
available originals. Questions, deep dives and research-context analysis use the
same configurable AI service.

The ML conference recommendation workflow is a specialized integration. It is not
a requirement for using your own reading lists. It is still bundled in this
version; making it independently installable and adding configurable tracking for
other conferences and journals are [planned work](agent-workflows.md).

## Start the desktop app

Use the [platform installation guide](install.md) to choose a released installer
or run the current source. It separates Windows PowerShell from macOS/Linux
Terminal instructions, first-time setup from later launches, and user setup
from developer checks. A fresh workspace starts empty; no ML corpus or nightly
task is required.

## Use your own reading lists

All desktop lists are peers. The current selection is only the list you are
working in; it is not a privileged main queue. Name a new list when creating it.
Imported research bundles retain their list name; select a list in the overview
and choose **重新命名…** (or F2) to change its label without changing its identity
or research records. Drag overview items to save their order.

Within a list, choose **自訂順序**, clear filters/search and unpin papers to drag
papers into a new reading order. Changes are saved immediately and used by
**下一篇**. Other sort modes are temporary views and do not overwrite that order.
The analysis schedule has one total paper budget across lists; optional analysis
while the app is open follows the currently selected list.

Existing desktop ML queues are adopted once as a normal **ML 頂會論文** list,
preserving membership, order and reading state. Legacy CLI ranking tables remain
available, but rebuilding those tables does not overwrite this editable list.

1. Select **＋ 新增 → 建立清單…**, name the list and paste references. Formatting does not need
   to be tidy; the importer attempts to repair wrapped lines and resolve entries.
2. Select the list and use **＋ 新增 → 加入論文到這份清單…** to add a title, citation or
   arXiv identifier.
   Search/select actions are also available in the paper table.
3. Open a paper to read its available PDF, write notes and track what you have read.
   Remove papers from a list without deleting their research records.
4. Configure AI when you want questions, translation, deep dives or reference and
   later-work analysis. Share/export actions are available from the desktop.

A fresh clone opens an empty list overview. **建立清單** supports a research topic,
pasted references, or an empty list; AI-based creation opens the account picker when
login is required. Retry after signing in; your input stays in the dialog. An AI
parsing failure is reported instead of silently creating a list from guessed lines.
Topic suggestions must match records retrieved from the academic search service.
An original is not always accessible, and ambiguous references can still resolve
poorly. Candidate previews, PDF drag-and-drop and resumable import jobs remain
future work. Switching lists does not automatically run background analysis.

Use **收合** at the right end of the toolbar to hide it and the paper details;
**展開頂部** restores them.
In the PDF, select text and choose **螢光筆**, or enable **螢光筆：開** to mark each
selection as you drag. Highlights save locally and survive reopening. Turn the pen
off, click a highlight and choose **移除標記** to remove it. They are app annotations
stored with the exact PDF version, not modifications to the original PDF file.
**自動重點** uses your configured AI on first PDF preparation; verified research
quotes appear as green highlights and in the presentation materials panel. Cached
analysis is reused on reopening. This checkbox starts off in a fresh workspace;
enable it to opt into automatic preparation. The main **深入分析** action also
generates highlights as part of the analysis.

## Paper presentations

Open the right-side **簡報** tab to create a **研究筆記** or **論文導讀** version
from the paper, deep dive, citation analysis, questions and notes. Choose audience,
slide count and speaking time, then edit directly on the embedded slide canvas:
double-click text, drag and resize objects, change typography, and add original
figures. Thumbnails, autosave and speaker notes stay in the app. Versions save independently.
The **素材** panel lists the paper's own figures and tables, section headings and
quotable sentences with page numbers; double-click or drag them onto a slide. A table
the 逐節精讀 reproduced becomes an editable table object instead of a cropped image.

Export the canvas to PDF or an editable OpenDocument deck, plus HTML, Markdown
and JSON. Connect a Google Desktop OAuth client to export a new editable Google
Slides copy and get its link. Cloud editing opens in the browser; two-way sync
and PowerPoint export are not yet implemented. See the [presentation guide](presentations.md) for generation,
evidence coverage, editing and backups.

## Share a reading list with its analyses

A list's value is the analysis behind it: deep dives, close readings, what each
reference is doing, what came after, the list survey, checked slide decks and the
questions already asked. `list-export` packs all of that into one file, and a
colleague's `list-import` brings it into their own workspace, so they see what you
see without re-running hours of model calls.

```powershell
.\scripts\dev.ps1 list-export cataract              # → data/exports/cataract-<date>.zip
.\scripts\dev.ps1 list-export cataract --no-notes   # leave out your notes and Q&A
```

Use **研究資料 → 匯出目前清單資料包…** in the app, then send the ZIP privately.
Older preview installers may keep this action under **＋ 新增**. The bundle
holds all local PDF files, analyses, survey, rendered figures, slide decks (not their
history), verified highlights, research questions and optionally notes and Q&A.
The export reports any papers whose PDF has not been downloaded. All packed files
are checked before import; no AI accounts or application settings travel with them.
The recipient chooses **匯入研究資料包** on the empty home screen or in the toolbar.
They review the contents before importing; existing work is kept unless they choose
and confirm replacement. A different local PDF's page-linked analysis is kept with it.
For a smaller online package, CLI `--without-pdfs` retains verified download URLs.

Optional Windows CLI example (for macOS/Linux, use `bash scripts/dev.sh`):

```powershell
.\scripts\dev.ps1 list-import cataract-20261015.zip   # restores packed PDFs; no AI required
.\scripts\dev.ps1 app
```

Each PDF is kept only if its fingerprint matches; one that cannot be fetched is
named, and the app will not download another version of it in its place — add the
file you were sent with `repdf <id> --file <path>`.

Importing never overwrites their own work (`--replace` does), and the papers arrive
unread: reading state stays with whoever did the reading. The list's order and its
pinned papers are part of the list and come with it. Reading needs no AI
connection; asking questions, rewriting slides or analysing new papers needs one.

For a paper you will present, `/paper-guide <paper id>` in Claude Code rebuilds its
論文導讀 deck by a checked round: the field and the reasoning from the front matter,
the references it stands on, the problems still open after it, a review for gaps,
and every point verified against the original. See [guide decks](guide-decks.md).

## Bring an AI connection

Cloud AI-assisted features need a working connection. Open **AI 設定** in the toolbar
to choose a default or assign different profiles to individual research tasks.

The account picker shows usage inline for the selected connection. Official quota
snapshots and Paperfact's last seven days of local call/token receipts are separate;
missing token reports mean unknown usage, not zero. Claude quota uses the official
CLI's structured `get_usage` control request; Codex uses its official account
interface. Gemini uses the installed official CLI core's cached-login handling and
read-only `loadCodeAssist` / `retrieveUserQuota` methods. Valid responses show plan,
model buckets and percentages; buckets may share a quota and must not be added.
Unsupported CLI versions, rejected account access or unavailable quotas remain
explicitly unknown. A cached Google login does not prove current Code Assist access:
`UNSUPPORTED_CLIENT` is shown as an upstream rejection, not as zero usage.
At startup, the app preloads saved profiles and unsaved terminal agent accounts.
Opening the account picker shows available snapshots immediately. Completed AI
requests (including failed requests and subprocess analyses) invalidate only their
connection; the app polls for changes every two seconds, coalesces refreshes within
five seconds, and refreshes expired snapshots after five minutes. Refreshing or
browsing accounts does not change the active AI connection or invoke a paid model.

**AI 設定 → 使用資料與回饋…** offers optional, local product-event collection.
It starts off and never automatically uploads. Review the exact JSON before
exporting it for manual sharing. Events contain workflow/node IDs, feature and
provider categories, input-size buckets, duration and outcome; no prompts, answers,
paper content, filenames, email or credentials. Records are limited to 30 days and
10,000 events. Withdrawing clears local events and rotates the identity on the next
opt-in; copies already shared must be deleted by their recipients.
The proposed shared Cloud Run → GCS → Windows → DuckDB receiver is documented in
[collection architecture](collection-architecture.md); it is not deployed, and
local recording consent does not authorize uploading.

**服務自選（未固定模型）** leaves model selection to the service. Claude's
`sonnet`, `opus` and `haiku` options are explicitly labeled as aliases whose versions
can change. Enter a full model ID to request a specific version; availability still
depends on the signed-in account. Task-specific choices use the same labels and
preserve the original routing IDs.

| Available connection | What you supply |
| --- | --- |
| Claude CLI | An installed CLI and a valid signed-in session |
| Anthropic API | Your API key and chosen model |
| OpenAI-compatible API | Your endpoint, model and credential if required |
| Compatible local model | Your running endpoint and model; a key may be unnecessary |
| Custom service gateway | A service URL, model and customer token |

These connections provide model calls. They do not yet constitute a general
integration with arbitrary external agent applications. Additional agent adapters
and an optional tool bridge are described in the [workflow design](agent-workflows.md).

An agent subscription account is not automatically an API credential. Use a
supported integration for your host, or a compatible model API/local endpoint.
Reading available PDFs and writing manual notes do not require an AI account.
The app's extraction, lookup and analysis steps are built around these connections;
Paperfact does not include a universal agent account or model entitlement.

Two execution modes are part of the product design: **Academic / bring your own**,
where users pay their chosen provider, and **Commercial / Paperfact managed**, where
all official AI work goes through our service and consumes Paperfact credits.
The same lists, research tools and modules serve both modes. See
[MCP and the two execution modes](mcp-and-modes.md) for their boundaries.

No managed mode, hosted service, checkout or credit balance is deployed yet. The
current gateway adapter provides the connection foundation; local token receipts
are usage records, not bills.

Keys entered in the UI are stored in gitignored local settings in plain text.
Environment-based credentials are also supported. Background AI uses the configured
connection and can incur its normal charges. See [AI setup](ai-setup.md) for
profiles, routing, local models and connection tests.

## Optional research tracking

The bundled ML workflow crawls ICLR, ICML and NeurIPS, ranks candidates, interleaves
curated foundational papers and can prepare a nightly reading queue. Its selection
policy applies to that queue, not to ordinary imported lists.

Use it only if it fits your research. Conference sources, scoring and scheduling
are covered in the [ML workflow guide](ml-daily.md). General source selection
and independently installed workflow modules are still on the roadmap.

## More information

- [Reader, notes and sharing guide](reader-guide.md)
- [Paper presentations and exports](presentations.md)
- [Guide decks: the /paper-guide round](guide-decks.md)
- [AI profiles and setup](ai-setup.md)
- [CLI reference](cli-reference.md)
- [Current architecture and hosted API contract](architecture.md)
- [Proposed agent workflows and list interface](agent-workflows.md)
- [Academic/commercial modes and MCP design](mcp-and-modes.md)
- [Development reference](development.md)

Presentation drafts and assets live in `data/presentations/`; back up that folder
alongside your research database.

Research records live in the gitignored `data/` directory. Keep a backup of
`data/papers.db` to preserve lists, notes, conversations and reading history.
