# Create an editable copy of recovered research

Open **Workspace and recovery → Create editable copy…**. Select the *papers.db*
from an already restored backup. If this window just restored a backup, that
chosen database is prefilled; inspection still requires an explicit click.

1. **Inspect saved content.** The dated report shows research, current PDFs and
   editable decks, unlisted papers, retained history and attachment counts.
2. Choose a **new workspace folder** and a **separate independent backup**.
   Both destinations must be outside the restored source and outside each other.
3. Review the confirmation, whose default action is **Cancel**. Creation
   revalidates the original sealed inspection.
4. The prepared copy can be opened in a **separate window**, after another
   explicit confirmation. The current reader and unsent drafts remain open.

~~~mermaid
flowchart LR
    A[Recovery backup] -->|Restore| B[Detached workspace]
    B -->|Inspect saved snapshot| C[Reviewed content and closure]
    C -->|Explicit confirmation| D[New editable workspace]
    C -->|Same verified preparation| E[Independent recovery backup]
    D -->|Optional explicit action| F[Separate reader window]
~~~

The UI passes the native inspection object back to *RecoveryAdoptionService*.
It does not rebuild research through per-list exports, replay old device jobs,
change the active workspace, upload data, or call an AI service.

Progress shows actual service stages and elapsed time, without invented
percentages. Repeated clicks cannot start another job. Stop and Close request
ticket cancellation and keep the dialog alive until the worker finishes.
Source/reader identity and selected inspection are checked again after native
confirmations, at final publication, and before launching a new window.

Unknown or unsupported recovered content remains a blocker. Queue-scope pins,
until their typed migration is available, are reported before creation and are
preserved in the source. A failed or cancelled attempt retains destination
fields for retry; a changed saved snapshot requires another inspection.

The body scrolls on small windows while actions remain reachable. Native text
fields retain ordinary keyboard editing and copying. No SQLite connection or
source-content verification runs on the GUI thread.

Fixture coverage includes actual archive restoration and editable preparation,
exact saved notes, independent backup inspection, explicit launch, draft
preservation, unsafe paths, default-Cancel confirmations, duplicate activation,
failure/retry, cancellation, late scope changes, active-worker close and
responsive report visibility. Tests use isolated workspaces and simulated local
services. Release installation and real OS process launching are separate checks.
