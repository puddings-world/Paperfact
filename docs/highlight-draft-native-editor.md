# Native highlight draft editor

Status: 2026-11-02, isolated `0.5.0.dev`, unreleased. The directly interacting
selection passes 130 cases (24 new) in706.7s, with privacy/Ruff green and no
failures/errors/skips/input drift. [Actions and actual screenshots](testing/highlight-native-editor-scenarios.md).

`HighlightDraftDialog` and the unchanged `ClaimDraftDialog` entry share a
`StructuredDraftDialog` lifecycle through explicit typed modes. Native fields
edit quote, reason, research role and optional page hint; unresolved reports retain
per-quote issues. Explicit candidate selection stores an anchor and requires new
verification. Every quote must be located before confirmed whole-group Apply.
Deleted marks need explicit restoration. Reading A independently never grants Apply,
never uses a claim proof, and leaves current B selected.

Background operations capture the exact body, preview, private revision and
cancellation token. Autosave acknowledges only the words it saved; later typing
remains dirty. Close drains owned saves/reads/work. Failed saves retain words and
the window; failed Apply leaves formal research unchanged and permits retry.
Apply returns the private revision from the same transaction; a post-commit read
cannot turn an accepted save into a reported failure or silently advance CAS.

After accepted close, native review/editor widgets retire through `deleteLater`.
The retained Python handle supports repeated close/cleanup and `isVisible()==False` after
retirement. Test-only explicit DeferredDelete delivery verifies GUI-thread
destruction before unrelated worker collection; ordinary application event-loop
semantics are documented by [Qt QObject](https://doc.qt.io/qt-6/qobject.html#deleteLater).
This contract does not make arbitrary child-widget methods valid after deletion,
nor uniquely identify every earlier native abort. Existing tests stay unchanged.

Native text editing covers Ctrl+A/C/V/Z/Y and Delete. Bilingual 620/980px layouts
keep actions accessible; synthetic screenshots are captured from the actual Qt UI.
Original reading exposes indeterminate activity/cancellation, never a fabricated
percentage. Source admission stays native-only on the GUI thread; SQL/PDF work is
background-bound.

Complete recovered/remote-origin native journeys, highlight CLI/MCP, derived-link
audit, remaining formats, canonical product integration, complete checks, installers,
production and installed-device acceptance remain open. Source presence and this
selected pass do not close them. No live model or scholarly-quality certification.
