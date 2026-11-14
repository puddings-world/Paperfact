# v0.5 execution board

The integration line is `develop/0.5` in `Paperfact-develop`. Preserve its existing
uncommitted work before integrating checkpoints. No additional feature expansion
or worktree creation is part of stabilization.

| Owner | Existing folder / branch | Scope |
|---|---|---|
| Codex | `Paperfact-stabilize` / `feature/0.5-workspace-stabilization` | Desktop typed recovery choices; guarded confirmation, durable decisions and focused Qt checks |

Next: checkpoint existing v0.5 work, integrate reviewed changes, then complete the
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
