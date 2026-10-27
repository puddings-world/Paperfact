# Observed paper questions

Desktop questions now use `research_chat` through `desktop.qa_job.ChatJob`.
The existing AI facade and login notifier remain responsible for provider access.
No account secrets or provider configuration are stored with research messages.

- Submission reserves the UI action before preparation. It captures the original
  database path/inode, workspace binding, paper lifecycle, question, selection,
  stable turn IDs and the selected AI connection. PDF extraction, history
  preparation, model execution and answer publication run on the worker.
- `begin_chat` captures the original target in a short transaction.
  `prepare_chat` reads at most the six preceding turns and extracts text from
  verified PDF bytes. It commits the user turn, portable link and request receipt
  before calling AI. A missing legacy PDF permits abstract-only questions;
  unavailable managed PDFs or invalid selections fail without alias fallback.
- An intentionally open, intact older PDF remains the question's source. Its
  hash is retained on both turns. A change to the desired PDF during generation
  makes the answer a candidate. Old text caches never stand in for verified bytes.
- `publish_answer` uses the original database, not the current screen. It checks
  the paper lifecycle, question/history and document provenance. A valid answer
  appends once with its receipt and outbox operation in one transaction. Exact
  delivery retries return the original result; changed content under the same
  request ID is rejected. Stale output is retained without replacing research.
- If the original database disappears, is replaced or rebound, output is retained
  in bounded `.paperfact-chat` sidecars, outside the replacement database. These
  are recovery records, not instructions to activate an old workspace.
- Failure before a durable turn lets the next click capture a newly selected
  login/route. A retry of a durable question retains its original inputs and
  account snapshot. A generated answer can be republished without another model
  call. `load_request(database, request_id)` is the explicit restart API.
- Navigation never transfers a question to another paper/workspace. Returning to
  the same paper refreshes its transcript without clearing a newer draft or
  stealing focus. Closing while the worker is active follows the existing wait
  guard. Delete actions compare the rows that were rendered and the original
  lifecycle under the deletion transaction.

## Portable conversation links

The existing `chat` table keeps its columns. Optional closed `exchange_id` and
`reply_to` fields extend the private research-content envelope. The message's
portable identity remains its content key. `research_chat_links` stores the local
integer mapping, exchange, parent turn and source PDF hash. Legacy payloads and
rows remain valid. An unknown or mismatching reference is shown as an orphan;
it is never paired with an unrelated preceding question.

Two-device replay and list bundle import preserve those portable identities.
Reimporting a known message is idempotent; conflicting content under its ID fails
without overwriting the receiver's work. Detached recovery restores chat links
alongside readable messages but archives QA job receipts and lifecycle records;
it does not activate the old device or run AI.

This is the unreleased private v0.5 contract. Older implementations with a closed
chat validator may reject the optional fields; no deployed compatibility promise
or automatic public-service rollout is implied.

## Validation and limits

Fixture tests cover the actual desktop handlers, a real Qt worker with a fake
model, account switches, reentrant submission, A→B→A navigation, close while busy,
transaction failures, retained candidates, restart/delivery retries, PDF version
changes, wrong anchors, two-device replay and bundle/recovery round trips.
No real account login, paid generation or user database is used.

The Ask tab exposes explicit pending-question resume and retained-answer review.
This does not claim coverage of unrelated translation, slide or other AI writers.
Shared lifecycle and retained-work integration must be merged with their own
validation before release.

## Mobile replay

The mobile reader accepts both legacy chat records and the closed optional link
pair. It groups linked turns by message and exchange IDs within one paper;
missing questions remain visible as orphan answers, including offline and
answer-before-question replay. Receiving or displaying chat never queues AI.
Conversation cards use text nodes, and the read-only module is in the offline shell.

`mobile/check.mjs --python <python>` includes a real desktop QA producer to
authenticated Python HTTP to mobile reader fixture. It compares stable turn IDs
with an exported list research package and checks repeated sync and offline
state reopening. The isolated Chromium browser check also verifies IndexedDB
reopen, interleaved pairing, actual cards and inert model-supplied markup.
These tests use synthetic workspaces and responses, with model calls disabled.


## Explicit restart and candidate application

Opening a paper lists pending questions without running AI. Resume confirms the
current ask account/model after restart. A failed job retried in the same session
keeps its captured route; an answer already produced is delivered without another
model call. The original database identity, parent lifecycle, question, history and
PDF are checked again. Other composer drafts remain untouched.

The read-only retained-answer dialog displays the question, answer and original
source hash. It can append the answer to an intact original question using the
same portable IDs. A removed/recreated parent, foreign workspace or selected
different paper requires explicit target selection and confirmation; that creates
a new linked exchange while retaining original provenance. Target observations
come from the displayed preview and are checked inside the write transaction.
Source records remain unchanged. Repeated application uses an atomic typed
receipt; reopening marks already-applied answers instead of submitting them again.

`research_chat_review.ChatReview` owns the typed preview/application boundary.
`validate_preview_snapshot` and `check_target` expose closed displayed-base hooks
for integration with the shared retained-work draft registry. The QA dialog is
read-only and does not create a second generic draft store; edited-answer draft
UI and a unified retained-work registry entry remain separate integration work.
Application receipts are local-only, bounded to 8 MiB, contain no provider config,
and are archived during detached restore. Their historical source hashes join
backup closure checks. Archived candidate receipts can be reviewed explicitly;
archived pending jobs never become automatically runnable.


### Unexpected answer-publication failures

The QA worker catches unexpected publication exceptions only after receiving a
bounded answer. It first recognizes an exact committed receipt (including a lost
success response); otherwise it retains the sealed request and answer in the
existing owned QA sidecar. Raw exception messages and provider configuration are
not stored. If retention itself fails, the operation reports failure rather than
claiming persistence. An abrupt process termination before any durable write is
not covered by this exception-recovery guarantee.

Explicit resume prefers a completed sidecar only when its request, captured
context and original question exactly match the prepared SQL receipt. Completed
output is reviewed or delivered without model/account calls; stale original
content requires the normal explicit candidate review. Replaced or rebound
databases cannot reactivate the old request. Exact already-accepted sidecars are
retained as recovery evidence but excluded from actionable review inventory.
