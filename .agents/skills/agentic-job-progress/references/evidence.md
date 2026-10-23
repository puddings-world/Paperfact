# Evidence: desktop progress and completion navigation

- Pattern: `agentic-job-progress`, revision 1.
- Status: validated-local.
- Date / project: 2026-10-23, Paperfact.
- Trigger: a slow single-paper analysis discarded child-process output while the
  top row displayed only AI routing. Users could not tell which stage was running.
- Decision: use shared in-memory jobs and explicit process events; never derive
  percentages from elapsed time. Capture context and user interaction before
  work, then return focus only if that context still belongs to the initiating action.
- Boundary: desktop Qt threads/processes with callbacks that save data before
  reporting success. This is not a durable queue or a provider reasoning stream.
- Trade-off: a fixed-height notice avoids moving the reader. Long stage details
  are available in a tooltip and a bounded session history. Unknown duration remains
  indeterminate; there is no calibrated ETA.
- Implementation: `src/paper_daily/work_progress.py`,
  `src/paper_daily/desktop/activity.py`, shared `ask.py`, process adapters in
  `main.py`, `queue_view.py`, `survey_dialog.py`, and PDF export page events.
- Verification: `tests/test_activity.py` uses synthetic providers and isolated
  processes for actual worker delivery, focus/navigation, partial output,
  repeated activation, reopen, failure, and exported PDF contents.
  Existing regressions include `tests/test_ui_stress.py` and `tests/test_deep_analysis.py`.
- Command: `python scripts/check.py`; full result is recorded in the development
  handoff after execution. The targeted new tests ran as part of that full suite.
- Live limits: no paid provider generation or live Google upload is used for stress
  tests. Qt widget rendering is inspected separately. This does not claim exhaustive
  coverage of every button or system-level accessibility integration.
- Privacy: synthetic fixtures only; no credentials, prompts, research text or
  machine-identifying paths are captured in the skill. No telemetry upload.
- Promotion: only local project evidence; no global installation or cross-project
  reuse claim.
