# Full-deck producer result and pending UI contract

Status: producer/UI and receipt backend are now integrated in the isolated tree.
A current combined root gate remains pending; no full/release claim. Earlier
independent native UI/storage results are scoped evidence, not all-path acceptance.
See [concrete scenarios](testing/pending-generation-scenarios.md).

## Required observable states

| State | Durable content | UI behavior |
| --- | --- | --- |
| Applied | Verified active operation/files and decision receipt | Deliver the actual published Deck; normal editor may mark it saved. |
| Retained in primary storage | Complete raw result and verified closure; not applied | Announce a reviewable retained draft in its original workspace; do not replace current edits. |
| Retained in owned fallback | Complete verified sidecar independent of failed primary staging | Announce saved recovery content and local no-model repair; Apply stays gated by fresh source/parent review. |
| Complete result held only in memory | Neither persistence path succeeded | Show unsaved attention state; hold actual deck/evidence/images and require retry/export or explicit discard before normal close/restart/switch. |
| Invalid result / no model result | No valid complete scientific result | Preserve old saved content and report validation/failure; never invent a pending valid Deck. |

A transport JSON string, status message or restored sender observation cannot
construct a published result. The result carrier must remain typed and private
inside the accepted job. Do not overload an ordinary returned Deck as if its mere
presence meant persistence succeeded. Existing ordinary validation/failure callers
and tests remain compatible; new incomplete-result behavior needs an explicit
producer contract with its observable changed semantics documented.

## Actual current seams

- presentations.generate currently catches retention failure and returns no deck.
  A specific valid-but-unpersisted result must survive this boundary. Generic
  validation errors must not be reclassified as valid research results.
- GenerationDelivery.run owns the actual result. It must capture the typed
  incomplete outcome before converting anything into a transport reason/string.
  It performs no QWidget operations on the worker.
- done/failed currently drop result when _owner() is absent or current() is false.
  Pending valid results need an owned holding path before those display guards;
  stale results must never install original A in current B.
- PresentationPane._generated/_show_deck reset dirty state. They must remain
  reserved for actual published results. A pending result is separate from the
  current deck and from manual edits, with its own retry/discard identity.
- Pane.busy/_producer_busy and save_changes are existing caller seams used by
  paper navigation, Main close and restart/update guards. Reuse them for unresolved
  pending work where appropriate; a new Main/Reader hook needs exact source review
  only if actual tests show these seams cannot preserve the result lifetime.

## Pending result interaction

Present a clear completed-but-unsaved state, not a running AI progress bar. Show
original paper/workspace, local failure reason and three explicit actions:
retry saving the already completed result, export complete verified content to a
new chosen destination, or discard with confirmation. A failed retry keeps the
same actual result and older saved deck. No action reruns the model or resolves a
new provider/account/model route.

A pending result cannot be stored solely in a weak view reference. It must survive
queued delivery, paper/workspace changes and controlled owner teardown. Use an
owned host/job holding seam. Never keep a strong reference to a deleted Qt view
or perform late widget access. If a view is gone, retain a discoverable result
without calling it applied or silently clearing it.

Normal close, restart, verified update, paper switch and workspace switch must
consult the unresolved state. A detached held result must remain associated with
its original source. Do not deadlock the user by keeping busy=true while disabling
all retry/export/discard actions. Do not claim protection against forced process
termination or power loss when every storage target is unavailable.

## Required behavior tests

1. Inject failure in primary and fallback persistence after a valid fake model
   response. Assert the actual complete result is held, old disk/editor content is
   unchanged and the visible state says unsaved, not generated/saved.
2. Retry after storage becomes available: zero additional model calls, identical
   byte declarations, one durable result/receipt, pending state cleared only after
   verification. Failed retry preserves the held result.
3. Close/restart/update/switch while pending: normal controls refuse or request
   explicit disposition; cancellation preserves every byte and the current edits.
4. Late failure after paper/workspace switch or QWidget destruction: no wrong
   display/write, no deleted-widget access and no silent actual-result discard.
5. Explicit discard: confirmation cancellation retains content; confirmation clears
   only that result and never deletes earlier saved research.
6. Export: destination cancellation/existing file/storage failure preserves pending
   content; successful complete export is verified and excludes sender writer
   authority. Text export is not an image-preserving substitute.
7. Existing managed successful delivery, source changes, duplicate callbacks,
   autosave and native close barriers keep their original assertions.

All provider responses are simulated. Use disposable workspaces and actual Qt for
lifetime/navigation acceptance. Physical installers and devices remain separate
gates. Run the current full check before commit or release.

## Implemented and remaining boundaries

App-owned pending results now survive deleted panes and stale delivery. Retry
uses the original captured result without another model call. Read-only context
labels are precomputed at worker hold and tolerate queued result settlement.
Verified rescue export preserves all captured image bytes and scientific figure
metadata/evidence, excludes local writer/account/cache fields, and refuses unknown
metadata rather than settling a lossy copy. Export data has no automatic writer
authority. Full rescue-file import/review remains required.

Normal close/restart/update preparation is covered with an actual MainWindow;
forced process termination and power loss when all storage fails are not covered.
Current-source combined checks, existing durable-receipt/source-refusal exception
carrier extensions, full portability and installed-device acceptance remain open.
