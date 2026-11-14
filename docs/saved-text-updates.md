# Saved text updates while reading

Development integration, 2026-11-13; unreleased.

When the open paper's saved explanations, Q&A or notes change through another
operation, the reader shows a compact **Load saved updates** notice. Detection
also covers unlisted open papers and ordinary SQLite writers. The notice does
not claim which device or person made the change.

![Saved text update notice using synthetic research](images/saved-text-updates.png)

- Detection never replaces the loaded PDF, moves its page, clears a draft,
  changes tabs or grabs keyboard focus. It does not log in, call AI or download.
- **Load saved updates** explicitly reloads saved text through the existing owned
  preparation path. The note/question composers and their source context remain.
  Controls disable while a supported text task or preparation is active; repeated
  activation coalesces through the same bounded worker coordinator.
- The notice clears a group only when the actual loaded content is acknowledged.
  Read failure retains the prior content and allows retry. A changed workspace
  or recreated paper cannot authorize reload through the old owner.
- **Later** hides that exact observed update. A newer saved content signature
  reappears. Reopening the paper loads current saved research normally.
- PDF replacements keep their existing separate original-version notice. Editable
  decks, source materials, Lineage dialogs and audit panels retain their own
  loading/refresh rules. This banner is not a whole-workspace recent-changes feed.

## Boundaries and API

`reading_change_inputs.read(conn, owner) -> dict[str, str]` runs inside the
caller's read transaction and verifies the actual captured `HighlightOwner`
before and after reading. It returns content hashes for `notes`, `chat` and
`dive`; `dive` includes close reading. It neither migrates schemas nor grants
source/write authority. Notes hash only the fields shown by cards; the owning
paper is checked separately. Chat includes maintained turn links and bounded
pending summaries, not account or usage polling.

`notes(rows) -> str` and `snapshot(saved_snapshot, targets) -> dict[str, str]`
produce the equivalent signatures from content actually accepted for display.
The existing saved-reader row and byte budgets apply: no silent truncation is
called a current view. Hashes stay in process memory; this is not telemetry.

`WorkspaceChanges.watch_research(owner, token)` attaches one loaded-paper request
to the window's existing single read worker. Passing `None` detaches it. The
`research` signal carries only token, paper ID and signatures. A late read for a
previous token is ignored; the ordinary list `changed` signal retains its
existing revision-only behavior. Repeated identical research observations still
allow comparison with a newly accepted display baseline. Observer close/replaced
workspace checks and executor draining remain shared rather than duplicated.

`SavedTextNotice.bind(owner)`, `reset()`, `accept_notes(rows)` and
`accept_snapshot(snapshot, targets)` connect actual reader lifetimes and delivery.
The reload action rechecks the loaded owner in a short read-only transaction.
Background observation is advisory; it is never permission to overwrite research.

## Validation

See [behavior scenarios](testing/saved-text-update-scenarios.md). The local tests
use isolated workspaces, actual synthetic PDFs and no real AI accounts. Hosted
sync delivery, installed-device timing and the full release gate remain separate.
