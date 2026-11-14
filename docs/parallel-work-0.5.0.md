# v0.5 execution board

The integration line is `develop/0.5` in `Paperfact-develop`. Preserve its existing
uncommitted work before integrating checkpoints. Continue the agreed v0.5 scope in the existing worktree; do not add unrelated
features or more worktrees.

| Owner | Existing folder / branch | Scope |
|---|---|---|
| Codex | `Paperfact-stabilize` / `feature/0.5-workspace-stabilization` | Mac-only candidate selection in the existing release workflow, synthetic fixture download and source/frozen acceptance; explicit current-corpus audit shared by CLI/MCP; independent generated/imported/bound original readers verified. Daily critical stays 14; no release selectors added. Desktop whole-corpus action verified in Qt; source-complete synthetic acceptance ZIP generated and actual source CLI roundtrip verified, with new frozen audit report stages; confirmed manual retirement and known-deleted identity restore share native decisions/Qt confirmation, exact original proofs and later-decision-safe retries; remaining recovery/mapping/list-survey audit and hosted/device gates stay open; cloud inputs requested |

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
