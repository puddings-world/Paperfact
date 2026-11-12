# Native reader test-port review

## Current integration result (supersedes historical diagnostics below)

The reviewed 13-file handoff finished with 111 explicitly selected cases passing,
zero skips. It was integrated into the isolated root candidate with exact file
hashes and nine contextual Main method transplants; 159 unrelated Main methods
were preserved. The source-pinned root integration selection then passed 28 cases,
zero skips, with 1,189 unchanged source inputs. Local receipt:
`build/merge-resolutions/reader-ui-root-result.json` and matching JUnit XML.

The actual UI now presents a held prepared request through a queued request-ID-only
notice, checks original reader/source/load ownership, renders idle unfinished work
honestly, and isolates failure from a paper the user has left. A pure prompt
projection includes only completed typed message pairs with the matching paper,
exchange, reply identity and exact source hash. Stored/raw captured history and
publication identity remain unchanged. Cached annotation reuse is labelled as
reuse; passive login is prompted once per actual window/pane session.

The old retry test still expects a new local row ID through an absent legacy
handler, while retained typed retry preserves request/message identity. That
unchanged node was explicitly outside these selections, not skipped or weakened.
A behavior decision and the coherent full integration gate remain open. These
results do not establish complete reader performance, real-provider availability
or installed-device acceptance.

## Historical diagnostic record

The text below retains the earlier failures and proposals as provenance; it is
not the current result. No earlier red receipt was relabelled as green.

This isolated test-only port retains the two standalone `OffThread` test functions
and their `_settle` helper unchanged. Actual reader fixtures use the owned
`ReaderPreparation` delivery boundary instead of an absent generic `reader.prepare`.
The analysis-status wrapper forwards the maintained `verify_sources` argument and
waits on the actual `LatestStatus` owner. The fixture uses two real local PDFs and
an isolated research database; it never reads an owner workspace.

The question fixture keeps the real `AskRunner`/`ChatJob` worker, source preparation,
captured route and retained publication. Only `llm.complete` is a held fake provider.
Its completion controls release that provider and wait for actual Qt delivery;
they do not call a fake UI completion to manufacture saved chat rows. Translation
fixtures likewise create actual stored-paper/document/native-load ownership and
execute the captured `Translation.call` on a worker with fake external translation
responses. Source/selection/current predicates are not mocked.

Every original observable assertion remains unchanged. The current diagnostic run
must finish before any result is assigned below. In particular, source inspection
identified the following semantic decisions; this document does not authorize or
implement them.

The preserved first diagnostic checkpoint is 8 passed / 9 failed in 647.77 seconds.
It ran concurrently with other native gates; three cases hit the new owned
readiness deadline, whose cause remains unclassified. Its source afterimages and
failure logs are retained separately under `build/stage1-after`. No test has been
rerun or timeout increased to hide that result.

The next, currently **unrun**, fixture revision uses an actual owned-QThread join
within the same ten-second deadline before queued GUI delivery. The page-context
inputs now use native A page/selection actions over physically present A-only
text before B navigation. Annotation inputs now bind actual stored paper/native
source ownership; prepared data is created by the maintained producer with a fake
external `Completion`, and no-generation guards sit at that external boundary.
No dispatcher, owner, resolver, source/current predicate or generated receipt is
fabricated. All old content/copy/prompt-count/retry-ID assertions remain in place.

The single serialized Stage2 selection completed **14 passed / 5 failed** in
159.54 seconds. All five preparation cases, the three held native controls, real
A-to-B publication, both native context cases and all translation cases passed.
The legacy retry case was explicitly deferred and not collected while its behavior
decision remains pending. No deadline failed in this run; that does not isolate
the cause of the earlier concurrent-run slowness.

Two actual user-facing failures remain: the chat body stays empty while a real
new model request is held, and an old paper's failure leaves its preparing status
behind. Three annotation cases stopped at new fixture admission errors before
their original outcomes: empty model selection is rejected by the maintained
producer, and a reparented pane can independently capture the same sealed owner
token in a different Python wrapper. The approved, currently **unrun**, correction
selects actual verified source index zero and requires one located mark; the
owner fixture compares database/paper/full opaque token and executes both real
owner checks on a read-only worker connection. It does not relax a product guard.

| Incoming case | User contract and native mapping | Decision boundary |
|---|---|---|
| `test_only_the_newest_request_of_a_kind_is_applied` | Standalone latest-kind/cancel behavior. | Entire function/helper retained. |
| `test_a_failure_on_the_worker_is_raised_on_the_windows_thread` | Standalone failure reaches GUI hook. | Entire function/helper retained. |
| `test_a_paper_opens_before_its_dive_is_typeset_and_never_shows_the_last_one` | Open native B immediately, clear old A, then display saved B after owned delivery. | Readiness/API adapter only; content/timing assertions retained. |
| `test_a_paper_left_before_its_dive_was_ready_does_not_overwrite_the_next` | Old A typesetting cannot install into B. | Owned delivery adapter; new held-worker control proves actual overlap. |
| `test_the_analysis_bar_reads_its_status_off_the_windows_thread` | Real source/status work stays off Qt. | Current status-owner/keyword adapter; thread/visible-label assertions retained. |
| `test_an_answer_is_saved_to_the_paper_it_was_asked_about` | Real publication stays with A; B never shows A's answer; returning to A displays it. | Actual producer fixture replaces fake callback-only storage. |
| `test_a_failed_question_is_retryable_and_left_out_of_later_prompts` | Visible pending work becomes honestly unfinished after failure; incomplete exchanges stay out of subsequent prompts. | Renderer currently labels every unanswered record `思考中`; prepared-request resume action differs from master's `未完成，可重試`. A potential representation seam needs a separate reviewed implementation, not fabricated failure receipts. |
| `test_retrying_an_unanswered_question_replaces_it_when_sent` | Retry preserves user text and avoids duplicate questions. | Master's absent `_retry_question`/changed local-row-ID expectation conflicts with retained stable typed request/user identity. Native resume uses explicit confirmation and the existing request; keep the assertion until the parent makes an explicit behavior decision. |
| `test_a_failure_for_a_paper_left_behind_does_not_touch_the_open_one` | B stays usable and does not display A's error. | Current `_qa_current` rejects any A failure repaint into B; master additionally requires a `先前論文` courtesy status. Decide whether that notice belongs in the current status or source-owned activity view. |
| `test_page_and_passage_context_do_not_follow_the_reader_to_another_paper` | A's page/passage must not enter B's prompt. | Private `(paper_id,page,text)` assignment is no longer the input contract. The unrun native adapter uses actual A page/selection actions, then B navigation; every content/chip/storage assertion remains. |
| `test_a_page_context_is_used_only_for_its_own_paper` | An abandoned page context cannot attach to B. | The unrun adapter uses native A page capture followed by actual B load; it does not inject an invalid tuple or infer ownership from matching bytes. |
| Three translation cases | Abandoned selection/paper results drop; unchanged selection permits free-to-AI fallback. | Actual resolved source and worker verification replace missing proof in legacy raw-widget inputs. All output assertions retained. |
| `test_prepared_highlights_are_not_analysed_again_on_open` | Opening prepared research must not generate again. | Old legacy-cache spy and mocked dispatcher are not the typed annotation pipeline. Proposed fixture seeds a closed source-bound prepared group and guards the external model boundary. |
| `test_cached_analysis_does_not_claim_the_ai_is_reading_the_paper` | Cached reuse must not claim new paid generation. | Old fake dispatcher emits an AI-reading status unconditionally. Proposed fixture runs actual typed cached admission; preserve both visible-copy assertions. |
| `test_missing_ai_prompts_for_login_once_per_session` | Passive opening should avoid repeated login prompts; explicit retry remains available. | Each switched paper must have actual current ownership. Existing typed UI refuses unowned/replaced inputs; inspect real owned annotation behavior before proposing any session-prompt change. |

The existing feature contracts that prevent silently replacing typed retry
identities include:

- `test_research_chat.py::test_prepare_retry_keeps_one_question_and_stable_prompt`:
  identical encoded request and one question on repeat preparation.
- `test_chat_resume.py::test_live_resume_retry_retains_route_and_question_after_failure`:
  one question after failure and the original captured route on retry.
- `test_reader_chat.py::test_failure_retry_keeps_question_and_uses_original_account`:
  retained question, original account, then one accepted answer.
- `test_reader_chat.py::test_login_required_retry_captures_new_account_without_duplicate_question`:
  missing-login retry may capture a newly selected account while avoiding duplicate
  questions.

For prepared annotation reuse the maintained typed reference is
`test_reading_annotation_ui.py::test_two_phase_success_is_reused_without_accounts_or_models`.
The missing-owner refusal is independently pinned by
`test_reading_annotation_ui.py::test_missing_owner_never_uses_legacy_fallback`.

The new native module adds actual held saved-input/renderer overlap, GUI heartbeat,
next-paper rejection and question/note draft preservation. It is not yet execution
evidence until its own admitted run completes. No production compatibility shim,
new wire state, source bypass, expectation change, skipped case or full-suite claim
is part of the fixture-only checkpoint.

The later approved product delta uses an optional, nonserialized prepared observer
on the actual ChatJob. Only a request about to invoke the model can notify it;
cached answers awaiting publication do not claim the model is thinking. The worker
checks the sealed receipt and captured paper/source. A QObject receiver gets only
the request UUID and rechecks the original workspace, paper, reader epoch and
native source witness before requesting the existing read-only preparation lane.
One bounded mailbox holds no prompt, answer, provider configuration or PDF. The
observer is optional: its failure cannot retry or lose durable model output.

Active, unfinished and retained question labels are ephemeral display state. They
do not change saved requests, retry identity, sync, packages or recovery formats.
Failure on a paper left behind replaces only its still-owned preparing status;
it cannot overwrite a new current action or current drafts. Accepted window close
clears the mailbox and display leases after the existing native-worker drain.

The initial product diagnostic passed 10 cases and reached one deeper original
prompt assertion: an unanswered typed question was included in the next request.
The approved fix projects completed typed pairs for prompt text only. It matches
message/reply/exchange/paper identities and exact compatible source hashes. The
raw bounded captured history and its bytes, CAS and lifecycle checks remain
unchanged. Unlinked legacy rows retain their existing prompt treatment; they do
not acquire identity pairing or a claim of completion. The old replacement-local-
row retry expectation remains deferred without a shim or assertion change.

Cached annotation copy uses the captured no-model task decision. Passive login
notification is remembered only for the existing pane/window session; actual
availability is checked on every attempt, and an explicit retry prompts again.
This does not cache credentials or permission. Final results and exact source
hashes belong to the separate build receipt; this document makes no whole-suite
or exhaustive per-button claim.
