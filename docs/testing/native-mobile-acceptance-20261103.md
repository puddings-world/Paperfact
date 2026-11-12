# Native recovery and web/mobile acceptance — 2026-11-03

Status: isolated `0.5.0.dev` candidate. No installer, deployment or release.

## What was exercised

| User action | Verified outcome | Evidence |
|---|---|---|
| Find a completed highlight result after delivery storage fails | Its retained result appears in the actual native review window | New native test, English and Traditional Chinese |
| Edit it, close the app window, and reopen | Private appraisal survives; original research is unchanged before confirmation | Actual Qt controls and persisted database assertions |
| Inspect original A while reading PDF B | A opens for evidence inspection; B remains selected | Exact bytes and document identity assertions |
| Cancel confirmation, then explicitly Apply | Cancel changes nothing; Apply saves a complete two-mark group once | Saved text, mark count and one decision receipt |
| Reopen after Apply | Private text remains and cannot accidentally apply again | Actual reopened controls; no additional AI call |
| Read and write offline in the mobile client | Notes/drafts survive restart, retries remain idempotent, conflicts preserve stale edits | Mobile domain checks and actual Python HTTP fixture services |
| Transfer source PDFs and retire old sources | Resume verifies exact bytes; old source access is suppressed without replacing the selected PDF | Python publisher → authenticated local HTTP → JavaScript client |
| Sync reading state, list metadata and research output | Recorded positions, NULL/empty metadata, claims, questions, inbox and history retain their intended meaning | Service integration scripts executed by `mobile/check.mjs` |

## Exact selected results

- Native retained-result continuation: **2 passed**, 23.41 seconds including runner.
- Frontend: **24 passed**, zero failures/cancellations/skips.
- Mobile domain: **535 passed**, zero failures/cancellations/skips.
- All service integration scripts in `mobile/check.mjs` completed successfully;
  these PASS checkpoints are not additional pytest cases or physical devices.
- Combined frontend/mobile gate: 41.23 seconds including runner; privacy scan and
  Ruff passed; 1,160 frozen source/test/script/mobile inputs, zero drift.

Raw local evidence: `build/highlight-sidecar-native-result.json`,
`build/highlight-sidecar-native.xml`, `build/web-mobile-acceptance-20261103-result.json`
and their matching logs/input-hash receipts.

The mobile checks use synthetic local HTTP services and JavaScript client state.
They do not establish a production login service, physical browser persistence,
installed macOS behavior, mobile OS background execution or scholarly accuracy.
No real account, paid AI, private research, deployment or upload was involved.

## Required next gates

1. Resolve the owner-facing behavior choice for explicit AI continuation,
   verified-source completeness and unverifiable legacy reading links. Existing
   tests protecting the previous behavior have not been weakened.
2. Finish remaining data-format/writer/audit integration and merge the isolated
   candidate without overwriting concurrent work.
3. Pass the matching complete Python/frontend/mobile check, then build installers.
4. Run installed Windows → offline Apple Silicon Mac → reconnect and physical
   mobile acceptance; finalize production identity, pairing, hosting and recovery.

This verifies existing native behavior with a new regression test; no product
patch was needed for the retained-result entry. It reuses existing local-integration
patterns and introduces no new global skill rule.
