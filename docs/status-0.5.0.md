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
| Mobile PWA | Offline/domain/service and browser fixture evidence recorded in development ledgers | Durable pairing, hosted service and physical phone acceptance |
| Scientific audit and recovery UI | Focused source/Qt/transport candidates, including verified prepared-file hashes | Reviewed integration; remaining original-bound and typed decisions |
| Metadata recovery | Source-bound receipt reuse now rejects corrupted provenance for keep/replace; critical plus recovery integration passed 21 cases in 39.2s total | Guided desktop choices, original-bound recovery and new parent mappings |
| Tests and resource use | Curated release: 33 Python + 24 frontend + 87 mobile cases and one actual HTTP program passed in 34.3s; runner regressions 59 passed | CI/device execution; historical deduplication; native resource cap on Mac/Linux |
| Release | No new release, cloud deployment or installed Mac acceptance from this checkpoint | Identifiable artifacts, upgrade/reporting checks, Windows/Apple Silicon/phone journey |

Immediate priority is integrating this preserved checkpoint, completing recovery
UX and durable private pairing/hosting, then installed-device acceptance. Existing
release requirements are selected by behavior, not historical test count. The new
CI split is configured but has not been executed on GitHub Actions.

The exact inventory, preservation scope and migration prerequisites are in
[workspace stabilization](workspace-stabilization-2026-11-14.md).
The [execution board](parallel-work-0.5.0.md) records actual claims and current scope. Detailed older evidence remains in the development/continuation
ledgers; overlapping case counts are not summed into a completion percentage.
