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

## Delivery priority and essential checks

Owner clarification, 2026-11-16: prioritize the installed Windows-to-Mac journey
and the real sync deployment path. Optional storage statistics and additional
verification infrastructure must not displace that delivery. The optional
uncommitted storage-inventory work is parked locally in Git stash, with its
exact receipt under ignored build/storage-inventory-evidence/parked-work.json.
Preserve it; do not automatically restore or include it in a release candidate.

- Batch related work into one coherent change. Run its affected checks once;
  repeat only after a relevant change, a failure, or a specific unresolved risk.
- Keep the existing critical gate as the integration baseline. Historical full
  suites are diagnostic tools, not a routine iteration or mandatory release ritual.
- Share cancellation, duplicate-job and worker-close controls where the same job
  mechanism is used. Keep feature-specific data-loss, wrong-target and account/
  workspace-isolation cases when those boundaries differ. A shared-worker pass
  does not certify every button or third-party service.
- Documentation/copy changes should not launch a new cross-platform build or a
  large interaction matrix. Record review and applicable existing evidence.
- Local verification targets 3-5 minutes; candidate validation/packaging targets
  20-30 minutes. One job at a time, bounded CPU, and no invented time percentages.

Keep six representative delivery journeys explicit: complete list-package
export/import; offline save/restart/reconnect; conflicting edits preserving both
versions; interrupted/duplicate attachment transfer; device/workspace isolation
and revocation; independent backup/restore. Exercise portable source contracts in
fixtures, then the real Windows/Mac journey before promoting a release. More test
cases are warranted by a concrete uncovered risk, not by a target count.

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
