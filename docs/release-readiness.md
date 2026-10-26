# Release readiness

## 0.4.0 public beta

This candidate adds HTTPS research-package sharing to the common desktop/CLI
transfer service, beta-aware update notices, and refresh after external SQLite
writers. Source and binaries are built from the same release tag. Accounts and
model settings remain local to each recipient; packages are research snapshots.

The release gate runs the full suite and frozen-app research/MCP acceptance on
all three platforms. Frozen acceptance also checks share-link SHA-256 output
without uploading data. Final platform counts, artifact hashes and Windows
install/upgrade preservation evidence belong to the release validation asset,
not an unverified claim in this candidate document.

Limitations: unsigned builds; direct HTTPS links only (browser download for
cloud login/preview pages); no hosted research database or live synchronization;
real recipient AI login and Google OAuth remain separate manual checks.
[Sharing guide](sharing.md) · [v0.4.0 release](https://github.com/puddings-world/Paperfact/releases/tag/v0.4.0)

## 0.2.0 preview — 2026-10-24

This candidate includes topic research routes, parallel PDF downloads, shared
background progress, list-scoped transfer controls and clearer cross-platform
installation instructions. The tag workflow runs the full check and frozen-app
research round trip separately on Windows, macOS and Linux before creating a draft.
See the [0.2.0 release](https://github.com/puddings-world/Paperfact/releases/tag/v0.2.0)
for its final artifact and acceptance evidence. Builds remain unsigned previews;
automated acceptance does not verify real provider accounts or Google OAuth.

## Historical 0.1.0 assessment — 2026-10-21

The **v0.1.0 colleague preview is published** on
[Releases](https://github.com/puddings-world/Paperfact/releases/tag/v0.1.0).
The table below records the release assessment made on 2026-10-21; it is not
acceptance evidence for later source changes or every platform/account.
For current installation instructions and architectures, see [Installation](install.md).

## Verified status

| Area | Evidence | Remaining work |
|---|---|---|
| Repository | Public since 2026-10-21 with a fresh history; v0.1.0 published as a preview; AGPL-3.0-or-later | Binary acceptance on clean machines |
| Installer pipeline | The three-platform Release workflow passed for commit `0248274` | Build and test the final candidate; newer AI/settings work is not in that run |
| Current source | Beta branch includes AI routing, account UI, bundle transfer, consent and packaging checks | Verify the candidate commit and artifacts before tagging |
| Independent workspaces | Fixture tests cover install/import/read/own-AI/export boundaries | A colleague should complete the journey with their own real account |
| Gemini | Google discontinued consumer Gemini CLI access | Antigravity integration is not implemented; keep this limitation visible |
| Google Slides | Optional desktop OAuth integration exists | Confirm the distributed app identity, Cloud audience status and a second account's authorization |
| Signing | Builds are unsigned | Validate install/update/uninstall on clean machines |
| Privacy | Research bundles exclude account settings; aggregate feedback is opt-in | Review the complete Git history and screenshot redistribution rights before publication |

GitHub build evidence: [successful Release workflow](https://github.com/puddings-world/Paperfact/actions/runs/39463606993).

A local pattern scan covered 935 reachable historical blobs of at most 2 MB and
the Git-visible working tree. No configured credential pattern matched. Two older
`config.py` blobs contain the maintainer's email; the current tree did not match
that personal-email rule. This is a limited preflight, not exhaustive secret
scanning or approval to publish the history. All README local image/document links
resolve. The two AI screenshots use synthetic identities and usage.

## Candidate acceptance

1. Review the final diff and run `python scripts/check.py` on that exact tree.
2. Check tracked files **and history** for credentials, personal data and private
   research. `.gitignore` alone does not remove previously committed material.
3. Review the initial AGPL-3.0-or-later license and bundled third-party notices.
   Existing README screenshots show published papers; verify attribution and reuse
   permissions, or replace them with a generated demo workspace.
4. Build the candidate on Windows, macOS and Linux. Test a clean install, import a
   bundle with PDFs, read offline, sign in to a recipient-owned supported AI, save a
   new analysis, export and re-import. Check update and uninstall preserve data.
5. If advertising Google Slides, test authorization and deck creation with a second
   account. Publishing the GitHub repo does not publish Google's OAuth application.
6. Prepare release notes listing supported and experimental integrations. Publish a
   preview/beta only after these checks; retain a stable-release gate for unresolved
   cross-platform and live-account checks.

The initial `0.1.0` candidate was prepared on `beta/0.1.0`. Keep preview releases
marked as a prerelease. A public repository and a stable installer are separate decisions.

## Installation details for preview binaries

The build produces a Windows per-user setup EXE, an Apple silicon DMG and a Linux
x86-64 AppImage. It bundles Python and Qt; provider CLIs are separate prerequisites
for AI. Unsigned Windows/macOS builds can trigger platform first-launch warnings.
See [building and publishing](releasing.md).

Installed data lives in `%APPDATA%\Paperfact` on Windows,
`~/Library/Application Support/Paperfact` on macOS, and
`~/.local/share/Paperfact` on Linux. `PAPERFACT_DATA` overrides the location.
Back up the whole data directory privately; share selected research with bundles.
