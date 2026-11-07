# Reading maintenance: actions, saved results and test limits

Updated 2026-11-01. Isolated v0.5 integration candidate; unreleased. This map explains
actual assertions and fixtures. It does not certify a release, real AI accounts,
scientific accuracy or cross-device operation.

## What the checks do

| Reader situation | Actual exercise | Required saved or visible result | Source |
| --- | --- | --- | --- |
| AI refuses one paper | Run the batch with a simulated policy refusal, then select again; explicitly select the refused paper too. | Automatic selection moves on; explicit manual retry remains possible. | `test_dive.py`, `test_dive_scoped_maintenance.py` |
| Service is temporarily busy | Simulate HTTP 429, sanitized CLI server errors, timeouts and a duplicate in-progress job. | No permanent per-paper give-up flag or exhausted retry count; account/quota failures remain distinct from temporary throttling. | `test_cli_failure_categories.py`, `test_dive_scoped_maintenance.py` |
| Repeated ordinary failures | Fail the same document three times. | Earlier retries remain possible, then automatic selection moves on; a successful explicit retry clears both counters. | `test_dive.py`, `test_dive_scoped_maintenance.py` |
| Workspace/account changes after selection | Generate for A, switch global settings to B, then run the follow-up. | The saved explanation and actual follow-up retain A's database/account snapshot and original paper lifetime; B gets no result or retry marker. | `test_dive_scoped_maintenance.py`, `test_dive_annotations.py` |
| A queued paper is deleted and recreated | During the first real simulated model call, delete/recreate the second selected ID. | Only the first model call runs; the replacement gets no old result or failure marker. | `test_dive_scoped_maintenance.py::test_selected_lifetime_is_rechecked_before_the_next_paper_uses_ai` |
| Section reading fails | Store two explanations, then make the follow-up reject its source. | Both explanations remain stored, both papers are attempted, and the failure is reported; existing manual section notes are not regenerated. | `test_dive_scoped_maintenance.py` |
| Highlight reply contains invalid items | Return prose-wrapped JSON and mixed valid/invalid selections. | Only verifiable original passages survive; unusable replies have a short retryable error and preserve prior saved highlights. | `test_paper_highlights.py` |
| Long-paper analysis fails late | Complete the first chunk, time out on the second, then retry. | Retry starts at the unfinished chunk, final results include both pages, and actual prior/current provider receipts remain attributed; progress is removed only after the complete result saves. | `test_paper_highlights.py`, `test_highlight_maintenance_scope.py` |
| Cached chunk or route changes | Tamper with a cached quote/receipt or choose another route before retry. | The chunk is regenerated; forged quotes and invalid attribution are not reused. | `test_highlight_maintenance_scope.py` |
| Original changes before annotation | Replace the source or delete/recreate the paper while work is pending. | No marks/failure status attach to a different owner or wrong PDF version. | `test_dive_annotations.py`, `test_reading_annotation_jobs.py` |
| Pure producer is reused | Call generation with captured pages and prohibit global file/cache helpers. | It returns verified selected content without reading/saving a global workspace. Progress I/O belongs to the explicit adapter. | `test_annotation_producer_seams.py`, `test_highlight_maintenance_scope.py` |

## Evidence and unresolved policy

The selected check uses real disposable SQLite/files/PDFs and simulated providers.
It does not call real account login or paid models. The final selected run passed175 cases,0 failures/errors/skips in105.03s pytest
(106.77s wrapper),895 source/test/script inputs unchanged. Exact terminal results
are recorded in the matching ignored `build/checkpoint-maintenance-final-*` receipts.
The acceptance map records the terminal result; overlapping selections are not summed.

Two additional behavior regressions were replayed against exact pre-fix module
copies in a disposable source directory. Both failed their behavior assertions:
the queued replacement incurred another model call, and the failed long-paper run
had no resumable progress. They pass in the repaired integration selection.
Receipt: `build/checkpoint-maintenance-before-result.json` plus XML/log.

An earlier 174-case interacting selection had four failures from two producer
functions parameterized for local-only/enrolled workspaces: those cases expect
one total AI call, while maintained batch continuation fills a missing section
reading with a second call. The owner was asked whether continuation should be
automatic or explicit. Those four assertions remain unchanged. They are not in
the selected maintenance gate and still prevent a complete-application claim.

The original `test_dive.py` assertion ASTs remain exact. Its old private mocks now
accept scoped parameters; the highlight fixture uses a real valid disposable PDF
and mocks the current captured annotation seam. New tests assert the actual
database, account snapshot, paper owner and document checks. The initial new
manual-note fixture used positional columns incorrectly; it now names the fields
and supplies a valid timestamp. No old behavior assertion was loosened.

## What the numbers do not mean

- Parameter combinations are cases, not separate product features.
- A selected pass does not replace `scripts/check.py` before completion or commit.
- A test percentage counts completed cases, not version progress or remaining time.
- Windows/macOS installers, actual provider quota/authentication, expert assessment,
  phone offline/reconnect and deployed multi-device synchronization remain separate.
- The structured bilingual catalog is still partial; this reviewed prose map does
  not pretend every test in the repository already has a human explanation.
