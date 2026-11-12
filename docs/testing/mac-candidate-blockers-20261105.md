# v0.5 Mac candidate handoff — 2026-11-05

Status: NOT deliverable. No candidate commit, push, native build or v0.5 DMG.

## Integration

Candidate workspace: `C:/Users/user/AppData/Local/Temp/paperfact-master-reconcile-221acc1f60`.
HEAD: `3843894811bd0eed6102e33e06783a1a77d2bca6`.
Pending merge: `8bc4a3bbbf6f08cad37d888ea7c4c6cb6f491bd9`.
Latest fetched master: `1b44466a2aaf5a3ea17a3eba16f27777f0507a36`.
The latest master documentation delta is present in the candidate, but merge ancestry is not complete. Do not report master as fully merged or change MERGE_HEAD manually. Preserve canonical-worktree edits and the owner's research database.

## Evidence, not aggregate coverage

- Full audit: 6,842 passed, 38 failures and one worker crash/error; stopped before all collected tests ran. Full gate FAILED. Twelve workers caused contention; use lower concurrency for the next gate.
- Subsequent affected-module gate: 213 passed, zero failures/errors/skips, 371.36 seconds, no source drift.
- Deferred material lifecycle regression cases: 3 passed, zero failures/errors/skips, 14.59 seconds including privacy scan and Ruff; no source drift. Covers switching paper, switching workspace and closing during background collection.
- Focused audit repairs v4: 121 passed, 69.17 seconds, no source drift. Overlaps the module gate; do not add counts together.
- Independent frontend: 24 passed. Independent mobile: 535 passed. Neither establishes physical device acceptance or full-check success.

Receipts are in ignored build/: delivery-modules-v1-20261105-result.json, deferred-material-delivery-20261105-result.json, delivery-audit-repairs-v4-trace-20261105-result.json, delivery-web-20261105-result.json and v05-delivery-full-audit12-20261105 XML/logs. An earlier audit-repairs basename was inadvertently reused; its surviving receipt is the later 120-pass/1-failure run, not a separate historical artifact.

## Decisions required before changing existing expectations

1. Four producer-observation cases expect one total AI invocation. Master intentionally adds missing close reading after deep explanation, giving two distinct calls. Preserve that behavior, then assert one call per task and no additional AI on publication retry, plus original-workspace persistence. Owner confirmation was requested under AGENTS.md and remains pending.
2. Two legacy-primary backup cases require refusal, whereas the new backup implementation preserves those PDF bytes. Isolated integration verification confirmed both old/current document bytes, unchanged source SQL/PDF, detached restore, and rejection of unrepresented files (build/legacy-backup-contract-20261105.json). Seek confirmation before replacing the obsolete refusal expectations with stronger preservation/restore assertions.

An intermittent material-original reader failure has not been conclusively resolved. Later isolated and affected-module runs passed, but this alone is not proof of a fix. The full audit also had a note-draft worker crash. Recheck both in the full gate without weakening assertions or increasing timeouts to conceal failures.

## Remaining delivery steps

1. Resolve the two behavior decisions and update their regression assertions if approved.
2. Run scripts/check.py to completion, including all Python, frontend and mobile stages; fix remaining failures. Require no source drift.
3. Commit the pending merge and complete latest-master ancestry through a normal merge; preserve independent canonical edits. Revalidate any subsequent changes.
4. Push the feature candidate and dispatch release.yml on that exact commit without a stable release tag.
5. Download the native Apple Silicon build and provenance, verify checksum/commit and provide the DMG.
6. Physically verify foreground activation, isolated first use, import/read/own AI account, report export and subsequent update on the owner's Mac. Windows tests cannot establish these results.

The existing master 0.4.6 Apple Silicon artifact is a maintenance comparison baseline only, not this requested v0.5 package.

## Owner decision — 2026-11-07

The owner approved retaining automatic missing close reading after a deep explanation and complete backup of represented legacy PDFs. The three affected test modules now assert separate task calls, retry without extra AI, original-workspace persistence, exact original/current backup bytes, detached restore and refusal of unrepresented files. The initial focused run stopped on a test line-length error; that formatting error was corrected. The second focused run is in progress (approved-contracts-v2-20261107); it is not a full-check pass. No new candidate commit, push or Mac build has been made.

Immediate travel fallback: the existing master 0.4.6 Apple Silicon artifact, run 41268914149 / artifact 13068083973, remains distinct from the requested v0.5 package. Transfer saved per-list research using Export this list, a file transfer service, and Import research package on Mac. This is snapshot transfer, not automatic reconciliation of subsequent edits; retain both device exports before bringing changes back.
