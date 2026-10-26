# Observed dive and research-context publication

This slice extends `research_generation` to `dives` and `paper_context`, and
completes shared publication adoption for close readings and list surveys. It does
not enable workspace sync automatically or enroll the remaining citation,
followup, highlight, question and resource producers.

## Actual entrypoints

- `dive._generate_for`, `generate` and `dive_ahead` publish through the shared
  boundary. `generate` now returns an already published result; callers must not
  repeat its SQL write. The existing `(body, reason)` return interface remains.
  A caller transaction must end before direct `generate` starts external work.
- A worker freezes its database and AI connection selection, takes the per-owner
  OS job lock, captures target absence/existence and the briefing input snapshot,
  and prepares the exact PDF. It closes its connection before calling the model.
  The generated row, outbox and receipt commit together. Candidate-only output
  does not increase the accepted count or trigger the next analysis phase.
- `followups.overview` uses the same sequence and its own job lock. Its closed
  input reader records the paper metadata, the consumed dive excerpt, and the
  selected reference/followup fields and order. Owner-scoped inventories are
  bounded before reading. Publication compares these actual current inputs.
  This metadata-based overview does not claim to have read a particular PDF.
- `dive.edit_snapshot/save`, `Data.dive_for_edit/save_dive`, and
  `followups.overview_edit_snapshot/edit_overview` accept original target-only
  observations. A wrong owner is rejected. Immediate callers may capture inside
  the save function; an open editor must pass its loaded observation.
- CLI `set-dive` captures before reading the file or stdin. A delayed submission
  cannot replace an edit made during that read. Stale output is retained and the
  command returns nonzero.
- The overview dialog displays its captured row, saves before accepting the
  dialog, and retains the text on rejection or storage failure. Changing paper or
  workspace never changes the save destination or refreshes another workspace.
  Cancel performs no publication.

## Existing producer adoption

`closeread.write` and `survey.write` also use `publish_generated`; `survey.edit`
uses `publish_edit`. All four integrated model producers now retain completed
output on SQL failure. A modified stale survey draft receives its own stable
candidate identity, while repeated saves of identical content reuse that outcome.

Close-reading and survey jobs capture `llm.connection_scope` before preparing
inputs. The model facade resolves the task from that frozen account/configuration
snapshot, preserving the historical `llm.complete` injection interface. Close-reading
batch workers also receive the original explicit database and connection snapshot.
Legacy two-item close-reading packs and survey timestamp normalization remain intact.

## Durability and compatibility

`publish_edit` derives a retry identity from the original observation and exact
draft. Repeated Save retains one outcome; editing an already stale draft retains
the new variant without refreshing its original base.

`publish_generated` preserves successfully generated output under the existing
owned recovery namespace if its SQL transaction fails. An already committed
receipt takes precedence. The retained candidate is available through
`list_recovery_requests` and `retry_publication`; no model call is needed to inspect
or export it. Restoration/review is explicit, never an automatic rebase.

Unbound custom two-item briefing packs remain supported without claiming verified
PDF provenance. Enrolled generation requires `PreparedPack`. The optional legacy
automatic-highlight follow-on is not dispatched from an enrolled dive until its
separate compound artifact writer is implemented. Unbound behavior is unchanged,
and a workspace switch prevents that optional phase from running elsewhere.

Each canonical conflict still belongs to one feature, not the entire paper.
Research input snapshots and candidates remain private local research records;
provider accounts and credentials are not copied into them.

## Verification boundary

Fixture tests exercise actual producers, manual Data/CLI entrypoints, native Qt
dialog saves, empty-peer replication, concurrent edits/input and PDF replacement,
original workspace/account selection, duplicate jobs, storage rollback/retry,
durable failed output, changed stale drafts and cancellation. Tests use isolated
SQLite/files and simulated model responses. Whole-project integration checks and
release acceptance remain the parent checkpoint's responsibility.
