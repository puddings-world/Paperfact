# Workspace UX and approved analysis behavior — 2026-11-03

## Owner-approved behavior

The owner approved the proposed configurable continuation behavior: bounded
automatic completion, with a manual-confirmation option. Preserve partial results
and report what is missing when the bound is reached. This is approval to implement
the behavior and align its legacy tests, not evidence that it has been implemented.

The owner also approved distinguishing generated content from verified sources,
and preserving old notes while marking unverifiable links for renewed review.
Do not ask again for these same behavior decisions. A located quote is not proof
of semantic or scientific correctness. Paid calls are not authorized as tests.

## Workspace interface candidate

The native workspace entry now has three task tabs: Sync devices, Backup and
restore, Advanced. Sync setup is the first action. Local paths, diagnostic counts
and independent-copy tools are on Advanced. Backup selection is labeled as the
first restoration step. Existing worker, cancellation, verification and transaction
handlers remain unchanged.

The first regression run exposed horizontal overflow at 440px. Sizing was fixed
without modifying the old test. Final selected check: 15 passed, zero failures,
errors or skips, privacy/Ruff passed, 18.89 seconds including runner, zero input
drift. English/Traditional Chinese screenshots were rendered; the final Chinese
screenshot was inspected with readable system glyphs. Initial offscreen captures
had no usable font and are not accepted visual evidence.

This is the first navigation layer. The nested service-connection form still needs
progressive setup and saved-connection UX. There is no hosted Paperfact login
service yet; the UI explicitly states a deployed sync service is required. No
credentials or research files were accessed and no installed app was replaced.

## Maintenance integration

Local master is 1b44466. The isolated pending integration already contains the
maintenance merge through 8bc4a3b; the remaining difference is docs/ai-setup.md,
clarifying that each user's Claude sign-in uses their own subscription. That exact
documentation update is now included in the isolated candidate, after checking
that the file had no independent edits. This is not a completed Git merge/commit.
The public remote was not fetched in this check; these statements describe local refs.

## Remaining gates

Implement the approved completion/source policies; simplify nested sync setup;
finish remaining 0.5 integration and the full check; build installers and validate
installed Windows/Apple Silicon Mac and physical mobile flows. Selected green
tests do not establish release readiness. No commit, push or release was made.
