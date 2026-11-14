# v0.5 execution board

The integration line is `develop/0.5` in `Paperfact-develop`. Preserve its existing
uncommitted work before integrating checkpoints. Continue the agreed v0.5 scope in the existing worktree; do not add unrelated
features or more worktrees.

| Owner | Existing folder / branch | Scope |
|---|---|---|
| Codex | `Paperfact-stabilize` / `feature/0.5-workspace-stabilization` | Current-source Windows/Mac/Linux candidate delivery; Linux startup/display repairs verified; Windows mobile-artifact failure propagation and canonical TEMP fixture repair. Preserve native reports and failed-run evidence; remaining recovery/mapping, hosted identity and physical-device gates stay in current status. |

Existing v0.5 work has been checkpointed and integrated. Next complete the
remaining release scope in [the roadmap](roadmap-0.5.0.md). Do not open more task
boards or duplicate plans. Existing identity and fast-test branches require review
before integration; clean Git status alone does not authorize deleting them.

Focused checks: 3-5 minutes. Beta validation plus packaging: 20-30 minutes.
One bounded check at a time, no `-n auto`. Historical regressions stay available
through `--profile full`; integration uses critical journeys plus affected tests.
See [collaboration](collaboration.md) and [development](development.md).

Never delete temporary folders by a broad prefix. Preserve unknown/session-owned
and ignored source. Research data and launchers are outside this cleanup scope.
Historical dispatch notes remain in
[the archive](archive/parallel-work-before-stabilization-2026-11-14.md).
