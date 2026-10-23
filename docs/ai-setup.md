# AI profiles and setup

The connections below provide model calls. General external-agent integrations
are proposed in [the workflow design](agent-workflows.md). The handover/bootstrap
example near the end is for rebuilding the ML corpus, not a requirement for lists.
Run terminal examples from the repository root.

## Choose your AI

**Gemini consumer access is unavailable through the current adapter.** Google
ended Gemini CLI service for individual free, AI Pro and AI Ultra accounts on
June 18, 2026. A saved Google login does not restore that access. Google's successor
is Antigravity; Paperfact does not yet have an Antigravity adapter. For the personal
account workflow, choose Claude or Codex for now. Licensed Code Assist/API access
has separate eligibility; do not infer it from a saved email or model menu.
See [Google's deprecation notice](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals).

1. Click the toolbar's **全域 AI** button and choose **Claude**, **Codex**, or **Gemini**.
2. Press **新增帳號** and complete the provider's browser flow. If its official
   CLI is missing, the button opens the installation instructions. An existing local
   login can also be used; signing in again creates a separate account and keeps it.
3. Select a **模型**, then **設為全域預設**. No connection name is needed.
   Browsing services does not change the active AI until you press that button.

When a feature opens the login picker, the button instead says **僅套用至…**.
It shows that feature's saved model and writes only its task override, preserving
the global model and all shared account settings. Login alone does not activate
the added account. Existing jobs retain their captured connections.

**帳號選項** provides a nickname, logout for an independently signed-in account,
and removal of unused Paperfact connections. Nicknames keep the account identity
visible. Multiple profiles sharing one login appear as one account option.
Logout requires confirmation and retains saved routes; the account must be signed
in again before those features can run. Removal is blocked while the account is
used by the global default or an explicit feature route. Removing a connection
does not erase vendor-owned login files; sign out first if needed.

The compact toolbar button shows the saved service and model; clicking it opens
the account/model picker. Its short tooltip shows the account and number of task
overrides; **進階設定** shows each assignment. Long names shorten only on the toolbar.
Codex models come from the official `model/list` method; Claude models come from
the official CLI initialization response, including newly available aliases such
as `fable`. Both load in background workers for the selected account, not from a
fixed list of model families. Gemini currently offers common model IDs.
Availability still depends on the provider/account; discovery is not a successful
inference check. Ordinary model fields are read-only selections; **自訂 ID** or
**自訂模型 ID（進階）** enables manual entry. All selectors accept custom IDs, and
**使用 Claude / Codex / Gemini 預設模型** lets the CLI choose. Claude's official
`displayName` supplies readable names such as **Fable 5.1** while the saved routing
ID remains `fable`. When the default description matches a returned model name,
the label shows that name too. Metadata is cached per account/home; unavailable
metadata never causes a guessed version. Refreshing discovery preserves the
chosen model and never changes saved routes. A failed query leaves manual entry
available; **重新整理** in the account picker retries it.

The toolbar details and the line beneath it identify **全域 AI** by service, account and
model. The redundant profile dropdown has been removed. Account identity is
checked in the background; until confirmed it explicitly says **待確認**. An unset
model is shown as **使用該服務預設模型**, with a name when reported. In the reader,
the same line identifies the active feature's resolved connection. The task table
shows **沿用全域 · model** or **個別指定 · model** below each row, with full connection
details in its tooltip. The global card and account column carry the identities.
This includes unsaved edits. Background metadata can update the toolbar label without
changing the selected account, model or task assignments.

Paper-specific research questions use the **論文問答** connection. After the full
text, deep dive and close reading exist, analysis prepares and saves questions with
reasons and exact source quotations. Older papers prepare them in the background
when **問 AI** is first opened. Reopening reuses the result; failed automatic
attempts are retained until the source changes or **AI 更新問題** is pressed.
Manual refresh uses tokens. **帶入提問** only fills a draft; the user still presses
**問** to submit it. **核對原文依據** moves the left PDF to the quoted page.
The full-text request is capped at 240,000 characters; larger inputs report the
limit instead of silently generating questions from a truncated text.

Open **進階設定** for a table of features, AI accounts and models. For example,
translation and deep explanation can reuse one Claude login with different models.
Choose a service/account in the middle column, then its model in the right column.
Claude, Codex and Gemini are all offered even before a connection has been saved;
using one requires its installed official CLI and a valid login.
**帳號與用量** opens the simple login screen without changing the default AI
or discarding the table's unsaved choices. **儲存分配** applies choices together;
**全部跟隨全域** removes overrides when saved. Cancel leaves saved choices untouched.
When overrides exist, **只看個別指定** initially filters the table; uncheck it to
configure another feature. **變更全域預設** opens a scoped global picker while
preserving unsaved task edits. It explicitly saves the global choice independently.
**重新取得模型** retries discovery for selected accounts and the global default;
failed discovery is not cached as a successful empty list. Inherited rows refresh
their official version names too, including dialogs opened after metadata arrived.
Account checks and model discovery do not generate research content.

The normal account/model picker and task table can close while read-only metadata
queries run; late results cannot update a closed view or another selection. An
actual login/logout operation still waits for completion. Previously observed
model names appear immediately while fresh metadata loads. Equal display names
retain their distinct model IDs; hover over an option to inspect its ID.

If settings are malformed, **AI 設定** offers explicit backup and reset. Declining
leaves the file untouched. Accepting preserves the exact original file beside it
and resets AI to disabled; research and vendor login files remain unchanged.
Recovery backups may contain keys and must not be shared. A failed write preserves
the original settings; background quota polling tolerates malformed settings.

The inline **方案與用量** panel reads the selected connection without changing the default AI.
Codex account identity (email and plan, when provided) and quota windows come from
the official app-server `account/read` and `account/rateLimits/read` methods.
The quota panel shows used percentages, reset times and the snapshot time; refresh
it to check again. Missing data or a failed request is shown as unknown, never zero.
Claude uses the official CLI's usage control response; Gemini uses its existing
login and account/quota integration. Providers need not report plan names or
per-model windows, so unavailable fields remain unknown. The panel also links to
the provider's usage information. A browser usage page may have a different account
signed in; check its account before comparing it to Paperfact.

The separate local summary counts tagged Paperfact requests for this connection
over the past seven days, including failed calls and provider-reported tokens.
It excludes older receipts without connection tags. CLI responses may omit token
counts; these are marked unreported rather than treated as zero usage. This summary
is not the subscription balance and cannot predict how many papers remain. Shared
local CLI connections do not separate historical usage after an external account
switch. Independently signed-in Paperfact accounts have separate receipt tags.

Official usage references: [Codex app-server](https://learn.chatgpt.com/docs/app-server),
[Claude usage](https://code.claude.com/docs/en/costs),
[Gemini stats](https://geminicli.com/docs/reference/commands/#stats).

API connection forms are currently outside the everyday desktop flow. Existing API
connections and task assignments keep working; the CLI examples below remain
available for configuring keys, custom endpoints and local models. No API setup is
needed for the official CLI login paths.

Each new CLI account has a separate directory under `data/ai-accounts`. A second
feature can reuse that account directly in the task table. **本機連線** uses your
existing terminal login; Paperfact will not log it in or out. Claude accounts use
the official subscription login, not the
Console login. Codex accounts use the official Codex browser login. Gemini uses the
official CLI's ACP `authenticate` method for Google login, independently of Slides
authorization. Gemini's cached login status is local; it does not prove service
access, and the consumer CLI path has been discontinued as described above.
Work/school accounts have separate Code Assist eligibility and project requirements. Provider plan
eligibility and quota still apply; these logins do not turn into general API keys.

Official references: [Claude authentication](https://code.claude.com/docs/en/authentication),
[Codex authentication](https://developers.openai.com/codex/auth),
[Gemini authentication](https://geminicli.com/docs/get-started/authentication/).
These CLI adapters supply research answers. They do not yet provide a coordinated
multi-agent job system, external-host session resume, or arbitrary tool access.

Open **AI 設定** to choose the default account/model, then **進階設定** to assign
different models to questions, translation, deep dives and other research tasks.
Accounts are reusable; a task's model choice does not edit its account's default
model or other tasks. Reading lists and research records remain independent.

| Backend | Connection |
| --- | --- |
| `cli` | Claude CLI on PATH, signed in; an optional model is forwarded to the CLI |
| `codex` | Codex CLI on PATH, signed in; an optional model is forwarded to `codex exec` |
| `gemini` | Gemini CLI with Google login; model passed to headless generation with tools denied |
| `anthropic` | Anthropic Messages API with your own key and model |
| `openai` | OpenAI-compatible API, including explicitly configured local servers |
| `gateway` | A custom service with its own account token, endpoint and model |

All desktop and pipeline AI features go through `llm.complete`. Nightly generation
uses the selected profiles. Shared web readers use their embedding host's
replaceable AI capability and do not receive desktop credentials.

The CLI manages the same profiles. These examples use Windows PowerShell;
on macOS/Linux, replace `.\scripts\dev.ps1` with `bash scripts/dev.sh`
and keep the remaining arguments. See [CLI entry points](cli-reference.md).

```powershell
.\scripts\dev.ps1 llm --profile local --backend openai --model your-local-model --base-url http://localhost:11434/v1 --no-requires-key --token-parameter max_tokens
.\scripts\dev.ps1 llm --use local
.\scripts\dev.ps1 llm --list
.\scripts\dev.ps1 llm --for-task translate --use local
.\scripts\dev.ps1 llm --for-task translate --follow-default
.\scripts\dev.ps1 llm --profile local --test
```

To connect a hosted service, use its actual URL, model ID and customer token:

```powershell
.\scripts\dev.ps1 llm --profile hosted --backend gateway --base-url https://api.example.com/v1 --model research-default --key-env PAPERFACT_API_KEY
.\scripts\dev.ps1 llm --use hosted
```

The example URL is a placeholder. No Paperfact billing service is deployed yet.
`gateway` separates customer tokens from vendor keys and supplies request IDs and
reported usage for a future server-side credits system.

Existing `data/llm.json` settings are preserved and migrated when a named profile
is created. Legacy command-line profiles retain environment overrides: `PAPERFACT_PROFILE`,
`PAPERFACT_LLM`, `PAPERFACT_MODEL`, `PAPERFACT_BASE_URL`, and their legacy
`PAPER_DAILY_*` aliases. With no explicit configuration, auto-selection still tries
Claude CLI, then Anthropic credentials, then OpenAI credentials/configuration.

Profiles saved in the desktop dialog are isolated: global model, endpoint and
vendor-key environment variables cannot replace their settings. An explicitly
named key environment variable is still supported, but a missing value fails
instead of falling back to another key. Choosing a default in the UI makes saved
task routes/default take precedence over a global profile environment variable.
Desktop workers and noninteractive CLI jobs snapshot routes/settings/environment
at startup; changing the default affects the next job, not a later step of the
same job. Signing out of a shared account invalidates it for all connections using
that account; finish jobs before signing out.

CLI credentials remain in the official CLI's storage (file storage for isolated
Codex accounts). Never distribute `data/ai-accounts`, `llm.json`, or a personal
CLI configuration directory. The model registry accepts additional provider adapters;
an arbitrary service does not gain browser login merely by adding its name.

Keys entered in the dialog or with `--key` stay in the gitignored local settings
file in plain text. Prefer `--key-env` to keep credentials in environment variables.
`data/ai-usage.jsonl` records request metadata and reported usage with no prompts,
replies or credentials. Unknown usage stays unknown; the local log is not a bill.
Provider failures do not automatically switch to a different account.

The installed command is now `paperfact`; `paper-daily` remains a compatibility
alias. The Python module stays `paper_daily` so existing launchers and schedules
continue to work. After updating, run the setup script to refresh installed entry
points, and `scripts/make-shortcut.ps1` to create Paperfact shortcuts.
`PAPERFACT_DATA` selects a data directory; existing `PAPER_DAILY_DATA` still works.
In a source checkout these settings can also live in a gitignored `.env` at the
repo root (start from `.env.example`); the real environment wins over it.

See [architecture and the hosted API contract](architecture.md) for provider
extension points, task names and the server-side billing boundary.

### Rebuild the ML corpus or carry over your data

`data/` is gitignored in full, so a clone starts with no corpus, no PDFs and no
dives. To rebuild the optional ML corpus on a new machine:

```powershell
.\scripts\setup.ps1
.\scripts\dev.ps1 llm --test                     # or install the claude CLI
.\scripts\dev.ps1 bootstrap --years 2015-2026    # ~45 min
.\scripts\dev.ps1 dive-ahead 5
```

Everything is idempotent and resumable, so an interrupted bootstrap is re-run rather
than repaired. To move a whole workspace, close the app and privately back up
the entire configured data directory, including PDFs, figures and editable decks.
Copying only `papers.db` does not preserve all research files. To share selected
lists without account settings, use a research package; see [Installation](install.md).
