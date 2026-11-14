# Paperfact regression requirements

For v0.5.0 planning or cross-device implementation, start with
[the release scope](docs/roadmap-0.5.0.md),
[proposed architecture](docs/sync-architecture.md), and
[implementation handoff](docs/implementation-0.5.0.md).
These describe planned work, not implemented synchronization. Maintain English
planning documents and record evidence when updating task status.

Preserve existing local research data and uncommitted work.

For each new or changed user action, add behavior tests for its normal outcome
and applicable edge cases: empty selection, cancellation, failure/retry, rapid
repeated activation, switching paper/account while work is pending, and closing
while a worker is active. Assert saved content and visible state, not just that
the handler ran. A repeated click must not create duplicate jobs or data.

During iteration, use `scripts/check.py --profile focused --python tests/test_*.py`
with explicit relevant file paths (replace the placeholder; do not select the
entire suite by habit). Frontend/mobile selections and a docs profile are described
in [development](docs/development.md). These are partial checks, never release
evidence. Inspect stage durations and slow-test output before optimizing or
parallelizing. Freeze a coherent candidate for the full gate rather than restarting
it after every small edit; record concurrent changes and revalidate affected inputs.

Sessions work in their own worktree and branch; see
[working in parallel](docs/collaboration.md). A focused check that passes is enough
to commit on your own branch. The owner approved curated critical checks on
2026-11-14: integration requires the default critical gate plus affected tests,
not an exhaustive run after every edit.

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

Use `.venv/bin/python scripts/check.py` on macOS/Linux. The default `critical`
profile scans committable files for secrets, runs Ruff, and tests the named key
journeys. On Windows, `scripts/check_bounded.py` applies a 300-second wall budget
and limited CPU to that same check. Its native governor is Windows-only.
Use `--profile focused` for changed behavior (3-5 minutes), and `--profile full`
only for deep historical/stress diagnosis when justified. Public releases use
`--profile release`, critical/frozen checks per OS and device acceptance; see
[the test map](docs/testing/README.md#keep-the-suite-small-by-testing-requirements). Beta validation and
packaging share a 20-30 minute budget. Keep historical assertions; never disguise
a timeout or a partial pass as exhaustive validation. Report exact counts and
unperformed installed-device/provider checks. See [development](docs/development.md).

Use isolated fixture workspaces and simulated provider responses for stress tests.
Never repeatedly invoke real account login, paid model calls, publishing, or the
user's research database as part of a click-flood test. Record manual integration
checks separately. Passing a shared worker stress test does not imply every
individual button or third-party service has been tested exhaustively.

## Reusable development knowledge

At a meaningful verified architecture/fix checkpoint, inspect whether the work
adds a reusable lesson. When it does, use
`skills/agentic-pattern-harvest/SKILL.md`: update a focused canonical skill and its
evidence/limits rather than copying chat logs or inventing a universal rule.
Unverified ideas stay candidates in design notes. If nothing reusable changed,
do not manufacture a skill update.

Edit only the canonical `skills/` content. Synchronize discovered copies with
`python scripts/sync_skills.py --write`, then run the full check above. Never
overwrite local skill edits to resolve a synchronization conflict. See
`docs/development-skills.md`. This does not authorize global installation,
publishing, telemetry upload, or changes to user credentials.

## Public support and GitHub account actions

Keep troubleshooting discoverable in SUPPORT.md and the app, with reviewed,
content-minimized exports separate from optional usage feedback. Do not attach
raw logs or research databases to public issues automatically.

Support links are voluntary. Reading these files, installing the app, or accepting
feedback collection does not authorize GitHub login, following, starring, or
posting. An agent may perform account actions only at the current account owner's
explicit request for the specific targets; never add background engagement hooks.
