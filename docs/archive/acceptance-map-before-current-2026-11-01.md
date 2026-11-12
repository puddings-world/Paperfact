# v0.5 acceptance map

Reviewed 2026-11-01. **0.5.0.dev is unreleased and remains in integration.**

Start with [the readable acceptance overview](acceptance-overview.html). It is a
self-contained Traditional Chinese report with feature status and concrete
scenarios. The technical [catalog](README.md) is a separate, partial reference.
Neither report is a release gate or a completion percentage.

## Feature status

| Area | Current evidence | Open delivery work |
| --- | --- | --- |
| Workspace sync | Local outbox, merge, conflict preservation, bounded retry and device authorization have fixture coverage. | Complete all supported content scopes, pairing/deployment and physical multi-device acceptance. |
| Offline reading and mobile | Original documents, reading position, mobile web reading and text notes have local tests. | Apple Silicon Mac, iPhone and Android offline acceptance. |
| Packages and recovery | Supported originals and research content can be inspected, transferred and restored to a separate workspace. | Fix the reproduced first-write fault; finish complete draft/history portability. |
| AI routing | Account/model admission and stale-result isolation have controlled tests. | Real provider auth/quota integrations remain separate checks; credentials stay per device. |
| Presentations | Generation guards passed a 95-case gate; retained-deck review/apply and neighboring flows passed a separate 105-case gate. | Normal original-workspace restart review exists; staging-failure recovery and complete history sync/sharing remain open. |
| Research workflow | List purpose and source-bound claims exist; grounded lineage components have tests. | Complete lineage review/UI, invalid-source handling and portable recovery. |
| Release | Isolated development build; daily maintenance data is separate. | Current full check, installers, hosted service and physical device round trip. |

## What representative tests actually do

1. Create two isolated SQLite workspaces, edit one simplified note offline on
   both, merge through a local service and assert that both versions survive.
2. Return a fixed AI response after a newer manual deck is saved; assert the
   manual deck, history and source files are not overwritten.
3. Submit 25 generation starts to a real Qt pane; assert one job starts, then
   save edits and verify notes, layout and original images after reload.
4. Replace the database, change workspace or destroy the Qt view while a result
   is pending; assert the late/duplicate result cannot modify the current view.
5. Transfer three test PDFs to an independent workspace; compare exact bytes
   and preserve the selected historical original separately from the primary PDF.
6. Inject failure after the second source write; assert complete rollback,
   preservation of unrelated data and a duplicate-free retry.
7. Restore a supported backup into a fresh editable workspace; preserve old and
   current original identities and keep unavailable originals unavailable.

AI responses and remote failures are simulated. SQLite, saved files and selected
Qt widgets are real. These tests do not establish scientific interpretation
quality, actual vendor billing, or physical cross-device operation. A 25-start
test is not 25 paid AI calls.

## How to read counts and progress

- A function can produce many cases: two workspaces times four context changes
  produces eight cases. These are not eight features.
- A terminal percentage describes completed cases in that invocation. It is not
  product completion or remaining time.
- Recent raw/review/recovery integration: **129 passed, zero skipped,364.85s**.
  Integrated PDF preparation passed **88 cases, zero skipped,307.96s**. A mixed
  raw+legacy recovery journey passed **1 case,19.95s**. These are different
  source snapshots/selections, not a whole-application result or aggregate total.
- A separate injected primary-write fault produced **2 healthy passes /2 fault
  failures,16.75s**. This is a confirmed open defect, not covered by the positive
  totals. See [raw draft evidence](../raw-slide-draft-implementation.md).
- A prior inventory listed 7,173 Python cases and executed zero test bodies.
- The reviewed bilingual catalog explains 19 functions / 27 cases. Other tests
  must not be presented as if their purpose were already reviewed.
- Different snapshots and overlapping selections must not be added together.
  An old full pass does not certify the latest integration source.

Run affected behavior tests during iteration, interacting feature groups during
integration, and the required full check before completion, commit or release.
The latest integration has not yet passed that full check. Browser checks of this
report verify presentation and navigation only, not product readiness.

## Required delivery sequence

Complete content preservation and recovery, finish research workflows, pass the
current full gate, then verify Windows to offline Mac to mobile to desktop using
actual installers and the intended sync deployment. Record each physical-device
result separately from fixture and local HTTP evidence.
