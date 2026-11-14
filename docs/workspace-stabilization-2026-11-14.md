# Workspace stabilization checkpoint

Observed 2026-11-14. This is a preservation and development-workflow checkpoint,
not a v0.5 release or permission to delete folders, change ACLs, migrate research,
repoint launchers, publish artifacts or provision cloud resources.

## Verified inventory

| Folder | Branch / short HEAD | Dirty paths at inventory |
|---|---|---:|
| `Paperfact` | `feature/0.5-sync-foundation` / `adcb1f9` | 118 |
| `Paperfact-develop` | `develop/0.5` / `9ab77e5` | 321 |
| `Paperfact-fasttests` | `feature/0.5-fast-tests` / `ee93633` | 0 |
| `Paperfact-identity` | `feature/0.5-paper-identity` / `7a25a0d` | 0 |
| `Paperfact-maintenance` | `master` / `1b44466` | 0 |

Develop contains every committed sync-foundation change and is 56 commits ahead.
Master is also fully contained in develop at this observation. Fast-tests has one
unique commit; identity has two unique commits. Clean status is not owner handoff.
The stale detached TEMP worktree registration points at an absent directory; its
reachable commit does not prove that former uncommitted content survived.

The 118 dirty Paperfact files were compared by SHA-256 against develop:

- 107 are identical.
- 10 differ. Four match develop HEAD while develop has local edits; three differ
  while develop equals HEAD; three differ from both. The blanket description
  "all ten are older" is not established. Preserve and review them.
- `docs/archive/canonical-status-before-rescue-2026-11-01.md` is absent from develop
  and is explicitly included in preservation.

## Preservation already performed

Local backup set `20261114-115154-preserve` contains:

| Artifact | Verified scope |
|---|---|
| Develop archive and manifest | 883 files, 24,467,809 source bytes; all 321 dirty paths plus explicitly scoped ignored code, fonts and evidence |
| Paperfact archive and manifest | All 118 dirty files, 1,643,367 source bytes |
| Git bundle | Complete local history and 29 refs; `git bundle verify` passed |

Each archived file was read back and SHA-256 checked; source HEAD/status and file
bytes were stable through capture. No skipped or unstable file was reported.
These private operator backups are not an installer or a public sharing artifact.
Exact host paths remain in the local operator record rather than portable docs.

Nine named draft receipts contain 69 historical references. Selecting the latest
applicable receipt per file verified 35 prepared source/test paths: all present,
all matching, none missing. This proves survival/integrity of those known files,
not that all deleted historical TEMP content was harmless or that the app passes.

No research data was migrated. No remaining TEMP directories or worktrees were
deleted. No permission takeover or source/daily-use launcher change was performed.

## Current delivery boundary

The develop working tree contains substantial uncheckpointed application work.
The ignored overlay additionally contains tested audit/recovery candidates and
an unfinished typed-recovery module with a known corrupt-receipt regression.
A clone of committed develop alone does not contain all of that work.

The latest full check was explicitly stopped for the owner's time/CPU policy.
Its runner recorded non-success after 13,583.908 seconds. That is not a completed
full-suite pass or evidence of an application assertion failure at termination.
Privacy/Ruff passed; frontend/mobile stages were not reached.

The Windows CPU/deadline prototype passed 55 selected cases in 8.54 seconds
(16.641 seconds including invocation) under a real job: 25% hard CPU quota,
at most two logical processors and below-normal priority. These figures are
focused evidence, not a beta validation/build time. The prototype still needs
single-entry enforcement, shared validation/build deadline, report/exclusivity
hardening and verified Mac/Linux support. Packaging is not yet governed by it.

## Next steps

Keep development on `develop/0.5`. Checkpoint its preserved dirty application work
before integrating more features; review ignored source deltas individually.
Use focused checks for changes and critical journeys for integration. Historical
full tests remain available explicitly. Do not open additional plans, worktrees
or test infrastructure as a prerequisite to ordinary v0.5 progress.

No folder retirement or launcher migration is part of this checkpoint. Complete
remaining v0.5 work from the existing roadmap, then validate identifiable Windows
and Apple Silicon packages. Hosted sync and physical-device acceptance remain
external gates, not claims inferred from fixture counts.

## Curated check evidence

The default critical gate passed: 14 cases in 47.66 seconds; privacy, Ruff and
selected tests together took 94.2 seconds. The native job enforced a 300-second
wall budget, a 25% CPU cap and at most two logical processors. Check-runner
regressions separately passed 57 cases in 4.16 seconds (5.219 seconds including
the bounded child invocation). These are local Windows fixture results, not
installed Mac acceptance, hosted sync or an exhaustive-suite pass.

The new profile reuses existing assertions; no historical test was deleted or
weakened. No additional global skill is warranted for this project-specific
selection policy. The preserved application work remains separate from this
workflow change and must not be declared integrated by its passing tests.
