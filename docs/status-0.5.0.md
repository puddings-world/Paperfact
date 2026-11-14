# v0.5.0 current status

Updated 2026-11-14. **Development, unreleased; no complete beta acceptance.**

The integration line is `develop/0.5`. Current consolidation preserves the
existing development work from base `9ab77e5`; the exact snapshot records 323
paths. Four recovery modules and their tests are now in ordinary source/test
paths in the consolidation candidate. Other ignored scientific-audit/desktop
candidates remain preserved separately, not silently promoted or released.

| Area | Current evidence | Remaining gate |
|---|---|---|
| Offline sync, history/conflicts and attachments | Implementations and scoped local fixture evidence in the preserved development work | Coherent source checkpoint, critical journeys, affected regressions and installed-device journey |
| Saved desktop connection | Explicit reconnection and device-local startup opt-in; exact-credential/workspace fences, offline backoff and real MainWindow fixture delivery | Native vault prompts, installed restart/upgrade and hosted first-device issuance |
| Device pairing | Desktop create/copy/pair/join controls, native pending retry before enrollment, independent keys and verified destination storage; local fixtures pass | Real native vaults, hosted first-device issuance and installed/physical-device acceptance |
| Mobile PWA | Scoped deck inputs survive authenticated transfer and offline reopen; rebuilt v23 artifact verified locally. Offline/domain/service evidence plus actual JS/Python pairing, verification and revocation; same-origin cookie UI, per-tab binding and four actual Chromium journeys pass; operator key creation/loading and CLI restart verified; pinned static artifact and review-only HTTPS template prepared | Live HTTPS host, platform key permissions, Safari and physical phone acceptance |
| Scientific audit and recovery UI | Typed metadata/note, complete native deck and portable claim-group recovery; exact historical input pins from local/accepted history, original passage checks, atomic receipts and independent peer delivery verified locally | Highlight/link/Lineage groups, related-paper deck mapping, legacy/source-lifetime mapping, unavailable originals and audit integration |
| Metadata recovery | Recorded parent decisions preserve metadata, reading/order and note copies; positioned notes can atomically include verified post-backup originals, with native peer delivery verified locally | Scientific-group recovery, legacy source mapping, unavailable originals and unproved parent migrations |
| Tests and resource use | Deck recovery and adjacent UI: 18 in 103.1s; final editable-table/peer/UI plus all 14 critical cases: 17 in 42.1s. Earlier scopes remain in the dated ledger; counts overlap. Full historical/release profiles not run | CI/device execution; historical deduplication; native resource cap on Mac/Linux |
| Release | No new release, cloud deployment or installed Mac acceptance from this checkpoint | Identifiable artifacts, upgrade/reporting checks, Windows/Apple Silicon/phone journey |

The preserved checkpoint is integrated locally. Immediate priority is completing recovery
UX and durable private pairing/hosting, then installed-device acceptance. Existing
release requirements are selected by behavior, not historical test count. The new
CI split is configured but has not been executed on GitHub Actions.

The exact inventory, preservation scope and migration prerequisites are in
[workspace stabilization](workspace-stabilization-2026-11-14.md).
The [execution board](parallel-work-0.5.0.md) records actual claims and current scope. Detailed older evidence remains in the development/continuation
ledgers; overlapping case counts are not summed into a completion percentage.
