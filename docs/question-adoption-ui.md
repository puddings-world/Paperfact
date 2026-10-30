# Explicit legacy question adoption

This desktop flow uses `question_legacy_adoption.prepare` and the exact returned
operation's `adopt`. It never captures AI connections, starts a model, or treats
browsing historical suggestions as permission to regenerate them.

1. Only unverified legacy suggestions expose **核對舊版來源**. Canonical questions,
   canonical deletions, an empty list and unrelated papers have no adoption controls.
2. Verification opens the existing bounded question browser and runs PDF and
   analysis checks off the GUI thread. Existing question text remains visible.
3. A successful preview shows the confirmed question, reason, verbatim evidence,
   page and exact PDF SHA-256. Source navigation carries that hash. The preview
   says it has not been adopted yet. **採用已核對建議** is the explicit write action;
   no extra confirmation dialog or account login is needed.
4. Acceptance stores canonical workspace questions. A changed source, target or
   parent lifecycle retains the operation's candidate instead of overwriting newer
   research. A storage failure retains the prepared preview for an exact retry.

The prepare worker pins the requested workspace path and file identity before
starting. Delivery checks the current workspace selection, paper, load epoch and
file identity. Adoption uses the prepared context, not a new observation. A worker
already publishing to the original workspace may finish there after navigation;
its callback cannot repaint the newly opened workspace or paper.

Only one local operation runs at a time, and AI refresh is disabled while it runs.
Closing the browser does not cancel an already authorized write or reopen the
browser on completion. Pure Python worker threads hold no Qt objects; results are
polled on the GUI thread. Parent-window close and restart additionally wait on
`adoption_busy`, alongside the existing question AI runner. A destroyed widget
detaches result delivery, while the non-daemon publication thread finishes its
original operation. This is not a durable resume promise for a killed process.

Tests use synthetic PDFs/workspaces and no account or model calls. They cover
unbound and enrolled workspaces, exact text/PDF provenance, repeated activation,
failure/retry, source and parent changes, replaced database files, paper/workspace
switches, late callbacks, dismissed/deleted widgets, and the actual main close and
restart guards. The browser is rendered at 940px and 600px widths. Native macOS
and Linux window behavior remains for release platform checks.

## Integration boundary

Owned changes are the question widget, the dedicated local worker, its test file,
this document, and the two-line-condition close/restart patch in
`build/question-main-guard.patch`. Do not copy the whole isolated `main.py`.
`build/question-baseline.json` identifies annotation source dependencies copied
only to run tests. The previous compound-review eight-file handoff is unchanged.

Run the targeted checks with:

```sh
python -m pytest tests/test_question_adoption_ui.py tests/test_question_workspace_ui.py tests/test_question_legacy_adoption.py tests/test_question_generation.py tests/test_question_browser.py tests/test_question_layout.py
```

The parent integration still runs the complete repository check before release.
