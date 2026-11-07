# Highlight CLI/MCP progress — 2026-11-03

Status: isolated `0.5.0.dev` candidate. Not released, installed or committed.
This is an action-focused account of selected validation, not whole-app acceptance.

## What the user or agent can do

| Action | Expected result | Executed evidence |
|---|---|---|
| Inspect a retained highlight analysis | Typed quotes/reasons and explicit receiver choices; no implicit Apply | Public operation workflow |
| Edit and save a reason | Private words survive reopening; formal research stays unchanged until confirmation | Operation test and real CLI process restarts |
| Read the original | Read version A while current PDF B stays selected; no caller-selected file path | Primary workflow and independent recovered workspace |
| Supply a quote absent from the original | Keep the private draft, allow original reading, refuse partial publication; accept after correction | Missing-quote repair journey |
| Confirm a complete revision | Save private revision, source ownership, analysis, marks and receipts atomically | Shared backend regression and public operation tests |
| Click or retry repeatedly | One private draft and one accepted decision; changed retry payload conflicts | Concurrent open/apply and accepted-replay tests |
| Lose storage during a write | Roll back research and private state; retry succeeds | Injected receipt failures for open/save/apply |
| Edit while verification runs | Preserve the later text and refuse the stale Apply | Delayed verification race |
| Restart the external agent | Reload private words and replay the same accepted result | Actual subprocess CLI and official MCP SDK |
| Use existing list imports and claim tools | Existing behavior remains intact with 35 discoverable tools | Existing local integration and claim transport cases |

The nine `review.highlights.*` operations are `list`, `inspect`, `targets`, `open`,
`read`, `save`, `verify`, `page`, and `apply`. `verify` checks quote locations,
not academic importance or semantic support. Apply requires explicit confirmation
and repeats its own current-source checks. These operations do not call a paid model.

## Test receipts

- `highlight-transport-recovery`: **38 passed**, 114.72 seconds; privacy scan and Ruff passed; zero failures/errors/skips/source drift.
  Selection: `tests/test_highlight_review_transports.py`, `tests/test_claim_review_transports.py`, `tests/test_local_integration.py`.
- `highlight-operations-final`: **68 passed**, 273.94 seconds; privacy scan and Ruff passed; zero failures/errors/skips/source drift.
  Selection: `tests/test_highlight_review_operations.py`, `tests/test_highlight_draft_application.py`, `tests/test_claim_review_operations.py`.

Earlier attempts are retained: the first run stopped on an overlong CLI guard;
the next broad run had 14 passes and one new transport-fixture failure. That fixture
used `research.sqlite`, while the real CLI opens the standard workspace database.
Transport tests now use an independently recovered/adopted workspace with its
original location unavailable. Assertions were preserved. Existing discovery tests
changed only their exact tool count from 26 to 35 for the nine new operations.

## Remaining release work

- Cancelled-result sidecar entry and remaining native format journeys.
- Validate reading-link provenance against the full explanation and highlight
  content, including reordering with unchanged PDF/page hashes.
- Integrate the isolated candidate into the development checkout, retaining other
  sessions' work; resolve existing full-suite failures and pass the complete check.
- Build and validate installers; run the Windows/offline Apple Silicon Mac/reconnect
  journey and physical-phone acceptance.
- Finalize production synchronization identity, pairing, hosting and recovery.

No research data, real accounts or paid AI were used. Source-level packaged-contract
tests do not constitute an installed Windows or macOS binary check. No release or
automatic update was published. The existing local-integration skill already covers
the reused transaction/retry/workspace patterns; no new global skill rule was added.
