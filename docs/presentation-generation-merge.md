# Presentation generation: maintenance reconciliation

Status: implemented in the isolated 0.5 integration candidate, not committed,
fully checked or released. This document describes backend behavior, not completed
native-editor lifecycle acceptance.

## Behavior

- The existing default `generate(..., save=True)` still publishes in the worker.
  The retained maintenance parser accepts one fewer slide and trims bounded extra
  slides before the closing slide; unreadable model output receives the maintained
  safe message. The 29 original backend tests remain byte-identical.
- `save=False` returns a draft without writing a deck or evidence. Its private
  original workspace/slot and evidence accompany the in-process draft, outside
  `Deck.to_dict()`. Explicit save validates those original owners before writing.
- Saving refuses a changed native database, persisted workspace binding, paper,
  mode, deck directory or newer saved deck. A generated draft remains available
  to the caller after refusal; the implementation does not overwrite newer work.
- Evidence must retain the draft's exact source hash and self-consistent snapshot.
  Managed publication uses the existing source-observation and retained-candidate
  mechanism; a changed research input cannot silently become a current result.
- A storage failure can be retried on the same draft without another model call.
  Retry after an already committed atomic write acknowledges the exact draft and
  does not duplicate history. Successful save clears pending-generation metadata
  so subsequent ordinary edits use the maintained editor path.
- Initial generation and bounded repair use the same captured model settings.
  Invalid save modes refuse before any model invocation.

## Observable tests and current evidence

`tests/test_generated_drafts.py` exercises actual local deck/evidence files,
SQLite workspaces and the production publication path with simulated model
responses. It covers deferred writes, failed-save retry, changed owner/slot,
tampered evidence, fixed repair routing, newer manual edits, lost-response retry,
subsequent editing, and managed publication with an actual saved explanation.
No paid call or owner workspace is used.

The four original backend failures were reproduced before the merge. A later
source-pinned 83-case selection finished with 81 passes and two failures in new
managed test setup (notes alone were insufficient generation input). The fixture
was corrected to include an actual saved explanation, with all existing assertion
ASTs preserved; both cases then passed. The 15-case deferred/backend selection
also passed earlier. These selections overlap and must not be summed or called a
single current 83-case pass. A coherent affected gate and full application gate
were required. The corrected current source was then frozen and checked with
all original backend tests, all deferred-draft tests and both report-tool modules:
**89 passed, zero skips**, 67.60 seconds in pytest (69.775 seconds including the
import probe/wrapper). All 1,190 admitted source inputs were unchanged. This is
a coherent current backend/report selection, not the full application gate.

Local receipts, under ignored `build/merge-resolutions/`:

- `presentation-merge-before.xml`: original four failures.
- `presentation-joint-pinned.xml`: 81 passed, two new fixture failures; exact source
  path and 1,184 unchanged inputs recorded alongside the result.
- `generated-drafts-managed.xml`: corrected managed pair, two passed.
- `backend-evidence-current.xml` and `backend-evidence-current-result.json`: current
  coherent 89-case selection.
- `presentation-merge-preservation-proof.json`: byte-identical original test file;
  only `generate`/`save_deck` among original top-level symbols changed, with all
  other 18 original function/class ASTs preserved.

An earlier wrapper omitted `PYTHONPATH` and loaded the canonical checkout instead
of this candidate. That run was stopped after confirming the exact owned process;
its logs remain, but its results are excluded from candidate evidence. Child
runners must pin the candidate source and use UTF-8 logs.

## Still open

- The native generation delivery now retains the actual published Deck and its
  managed metadata. The autosave fixture uses real worker-side publication while
  keeping its stale UI timer pending; all four original assertions remain and a
  fifth was added. The coherent 86-case gate includes all original pane tests.
  Arbitrary callback JSON is still not a publication API. See
  [native delivery and acceptance map](desktop-generation-delivery.md).
- A deferred draft is currently an in-process API, not a durable restart-safe
  generation inbox. No serialized private draft authority is introduced here.
- Verified file-candidate/draft Apply, complete asset/history enrollment, and
  package/sync/recovery continuity remain separate release requirements.
- Native keyboard/editor, Google Slides and physical-device acceptance are not
  proven by this backend selection.

## Retained-draft SQLite lifetime follow-on

`sync_deck_publication._retain_original_draft` now uses explicit `closing` around
the connection as well as its transaction context. SQLite transaction exit alone
does not close the native handle. Three real-handle cases failed before the fix;
all four lifetime cases pass afterward, including saved/refused/write-failure
paths and rejection of a replaced database. A coherent 24-case selection also
passes with no source drift (receipt `draft-lifetime-joint-result.json`). These
fixture results do not establish the cause of every earlier Windows lock or
complete deferred-draft restart, file Apply or device acceptance.
