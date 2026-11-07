# Material refresh and original-source reading

Updated 2026-11-01. Isolated `0.5.0.dev`, unreleased. This describes actual
disposable SQLite/PDF/Qt actions and saved/visible assertions, not a complete app
pass or installed-device acceptance.

## What changed for the reader

Opening the material panel now starts an owned background collection instead of
doing PDF/SQL work in the click handler. A compact refresh button is disabled
while running. Stage messages use the existing activity notice, and the local
status shows actual elapsed seconds, not an invented completion percentage.
Refresh failures retain the previous material list and allow explicit retry.

The panel keeps each item's source version privately. If its A material is still
selected after the reader explicitly activates B, clicking opens independently
retained, verified A read-only. The current B and unsent drafts remain intact.
Current-document materials retain ordinary left-reader navigation. A missing
retained original leaves the scientific material visible and explains why the
historical original cannot be opened. Drag/copy/export data remains plain content;
private in-process source permissions do not enter JSON or MIME.

## The actions tested

| Reader situation | Actual action | Required visible or saved result |
| --- | --- | --- |
| Old material after Use Latest | Collect A, activate B, click the actual A tree row, with no deck or proposal grant. | Exactly one byte-exact A viewer; B focus/scroll, draft, SQL and nonjournal files unchanged. |
| Repeated refresh | Hold the collector, submit 50 duplicate requests and click the disabled button, then release. | One off-GUI collection, button recovers, matching source payload and plain scientific MIME; no draft save or SQL change. |
| Failed refresh | Preserve a real collection, raise an error containing private test text, restore the helper and explicitly retry. | Old content remains, raw error is hidden, retry installs a fresh verified collection. |
| Context changes during collection | Hold work, reopen the paper, activate B, change workspace or request close, then release. | Old work does not publish; a reopened reader accepts only its new owner's collection. Another workspace's bytes and drafts survive. Close remains blocked until drain. |
| Repeated source clicks and reopen | Hold A preparation and click 25 times, release, reuse the viewer, close it and click again. | One off-GUI preparation/view before close; a fresh exact-A viewer after close; B, SQL and notes unchanged. |
| Unretained old original | Collect A without an independent retained source, activate B and click A. | No source worker or wrong-original view; exact material payload remains and missing-original status is shown. |
| Changed row content | Alter the actual tree payload after collection, then click it. | No historical worker/view; feedback appears and draft remains. |
| Failed original preparation | Fail with private raw text, then restore real verification and click again. | Busy state releases, raw text is hidden, content/SQL stay intact; explicit retry opens A. |
| Context changes during original preparation | Hold source work, change selection, reopen paper, activate C, change workspace or request close, then release. | No late A viewer; notes and the unrelated workspace remain intact. |
| Rapidly choose another material | Hold the first read, click the second heading 25 times, release. | Old worker drains before exactly one latest request runs; viewer corresponds to the second selection. |
| Distinct material snapshot | Prepare A after B replacement and forbid SQL/JSON/hash/PDF parsing during GUI admission. | Exact A with only material provenance; GUI admission uses small native metadata. Runs in local and enrolled modes. |
| Unrelated note changes | Add a real note and revalidate the existing material snapshot. | Same selection, same collection and same A; no refreshed authority for another source. |
| Source mutation or mixed permissions | Mix material/deck proofs, then rewrite the retained source bytes. | Mixed proofs refuse; mutation revokes the source and revalidation cannot reopen it. |

The shared integration selection also reruns existing slide-source navigation,
material double-click/drag/drop, previews and presentation editing/persistence.
Existing test assertions remain unchanged.

## Results and limits

Current shared UI integration: **97 passed, 0 failures/errors/skips**, 268.91s pytest / 270.14s wrapper. Source/scoped collection and parent lifecycle selection: **59 passed, 0 failures/errors/skips**, 106.51s pytest / 107.73s wrapper. Both use the same 929 unchanged source/test/script inputs. They are separate selected gates, not a full application pass. The separate native screenshot check passed 1 case in 6.28s pytest / 7.53s wrapper; 260/360px material panels and the 620px original viewer were visually inspected. Ruff passes.

The preceding initial UI audit failed after actual clicking: its worker object
had been deleted while the controller still held it. A separate finite Qt probe
reproduced loss of `sender()` when a subclass overrides the decorated slot.
The source-neutral controller now keeps sender lookup in its base Qt slot and
passes explicit worker/view identities to ordinary subclass completion hooks.
The exact audit then passed; existing slide-source controls are included in the
shared selection. This is a project-local PySide observation, not a new global
agent instruction.

The independent pre-UI audit reaches the original zero-viewer assertion after
its B/draft/SQL/file guards pass. All 26 original assertions remain in order;
the adapted asynchronous fixture adds one typed-selection observation. Genuine
desktop capture setup and actual `ReaderPage.load` establish the earlier owner;
an idle host method matches the maintained MainWindow contract. Only new fixture
drains use the maintained yielding event-pump pattern, with a five-second budget;
the initial/post-activation generic waits and their earlier failures are retained.

The first new paper-reopen control incorrectly assumed the panel would stay empty.
Actual reopening legitimately schedules fresh collection. Its recorded revision
now proves two different earlier reader owners, cancellation of the old request,
and delivery from only the new owner. No existing test was weakened. Failure and
setup receipts remain in ignored build artifacts.

Not proved: exact passage focus in the independent original viewer, semantic
claim support, installed Mac/phone operation, real accounts/models, production
sync identity/hosting, all writer/history/recovery scopes or an installer. Opening
the declared page is not matching an exact quotation. The latest full check is
still failed; selected passes do not permit a commit or release.

## Trace the actual tests

- `tests/test_material_original_navigation_audit.py`: the original real-click regression.
- `tests/test_material_reader_ui.py`: nine reader actions expanded to sixteen cases.
- `tests/test_material_original_snapshot.py`: three snapshot controls in two modes.
- `docs/testing/catalog.json`: bilingual steps, outcomes, limits and exact collected IDs.
- [Core provenance and scoped collection](material-core-scenarios.md).
- [Existing saved-slide source reading](active-source-scenarios.md).
- [Current status](../status-0.5.0.md) and [historical receipts](acceptance-map.md).
