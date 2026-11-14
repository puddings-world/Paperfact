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
| Saved desktop connection | Explicit reconnection and device-local startup opt-in; exact-credential/workspace fences, offline backoff and real MainWindow fixture delivery | Native vault prompts, installed restart/upgrade and hosted device pairing |
| Mobile PWA | Offline/domain/service and browser fixture evidence recorded in development ledgers | Durable pairing, hosted service and physical phone acceptance |
| Scientific audit and recovery UI | Typed choices, recorded parent mapping and explicit child restore verified locally; reference authority and a second native client preserve links/order | Original-bound/compound recovery, new parent mappings and audit integration |
| Metadata recovery | Recorded parent decisions preserve linked metadata, reading and ordering; explicit descendant restore and native peer delivery verified | Original-bound/compound recovery and unproved parent migrations |
| Tests and resource use | Startup/critical/affected checks: 56 passed in 74.5s; final scope guards/core/contracts: 29 passed in 17.6s. Selections overlap; expanded release profile awaits release execution | CI/device execution; historical deduplication; native resource cap on Mac/Linux |
| Release | No new release, cloud deployment or installed Mac acceptance from this checkpoint | Identifiable artifacts, upgrade/reporting checks, Windows/Apple Silicon/phone journey |

The preserved checkpoint is integrated locally. Immediate priority is completing recovery
UX and durable private pairing/hosting, then installed-device acceptance. Existing
release requirements are selected by behavior, not historical test count. The new
CI split is configured but has not been executed on GitHub Actions.

The exact inventory, preservation scope and migration prerequisites are in
[workspace stabilization](workspace-stabilization-2026-11-14.md).
The [execution board](parallel-work-0.5.0.md) records actual claims and current scope. Detailed older evidence remains in the development/continuation
ledgers; overlapping case counts are not summed into a completion percentage.
