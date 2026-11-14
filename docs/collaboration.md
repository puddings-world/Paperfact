# Working in parallel

Agreed with the owner on 2026-11-14. This page is the rule; `parallel-work-0.5.0.md`
holds the live table of who is working where.

## One session, one folder

- `Paperfact-develop` (`develop/0.5`) is the integration line. Nothing is developed
  in it directly; it only receives merges.
- Each session creates its own worktree and short-lived branch from `develop/0.5`:
  `git worktree add -b feature/0.5-<topic> ../Paperfact-<topic> develop/0.5`.
- `Paperfact-maintenance` (`master`) takes 0.4.x fixes only. `master` is merged into
  `develop/0.5`, never the other way before 0.5 is released.
- Remove your worktree and branch once the work is merged. Remove it with
  `git worktree remove`, so no tool keeps a record of a folder that is gone.

## Say where you are

Before the first edit, add one row to the table in `parallel-work-0.5.0.md`:
session, folder, branch, the directories you will change, date. Delete the row
when you finish. Two sessions do not edit the same directory at the same time;
if you need a file in someone else's row, ask the owner.

A session cannot message another session. The table and the commit history are
the only handoff, so commit often on your own branch.

## Checking without blocking development

- Own-branch checkpoint: focused checks for the changed behavior and its callers.
- Integration into `develop/0.5`: the default critical journeys plus affected tests.
- Release: critical and affected checks, package/device acceptance, and an explicit
  full run when broad changes warrant it. Record uncovered boundaries honestly.

The owner approved the curated critical gate on 2026-11-14. Historical tests are
retained, not weakened. Focused iteration has a 3-5 minute budget; beta validation
and packaging together have a 20-30 minute budget. Run one check at a time with
bounded CPU usage. A timeout is not a pass. See [development](development.md).
Device and hosted acceptance do not block a scoped development checkpoint.

## Keep the status short

`status-0.5.0.md` describes the present only. When a section is superseded, move
it to the dated continuation ledger instead of adding another section above it.
