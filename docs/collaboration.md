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

## Two levels of checking

| When | Check | Passing it means |
|---|---|---|
| Committing to your own branch | `scripts/check.py --profile focused` on the files you touched and the tests that use them | The commit may be made |
| Merging into `develop/0.5` | The full check on the merged result | The merge may be pushed |

The full check runs every test and reports every failure; it does not stop at the
first one. A failure found by the full check is fixed on a branch and merged, not
edited in the integration folder.

Device, installed-package and hosted acceptance are a release checklist. They do
not hold an item open during development.

## Keep the status short

`status-0.5.0.md` describes the present only. When a section is superseded, move
it to the dated continuation ledger instead of adding another section above it.
