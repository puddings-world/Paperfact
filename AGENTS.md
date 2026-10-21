# Paperfact regression requirements

Preserve existing local research data and uncommitted work.

For each new or changed user action, add behavior tests for its normal outcome
and applicable edge cases: empty selection, cancellation, failure/retry, rapid
repeated activation, switching paper/account while work is pending, and closing
while a worker is active. Assert saved content and visible state, not just that
the handler ran. A repeated click must not create duplicate jobs or data.

Run the full check before declaring a change complete, committing, or pushing:

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

Use `.venv/bin/python scripts/check.py` on macOS/Linux. This runs Ruff, all Python
tests (including desktop stress scenarios), and all frontend tests. Do not skip,
delete, or weaken an existing test to pass a change without user-approved behavior
changes. Report exact test counts and any live-only checks not performed.

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
