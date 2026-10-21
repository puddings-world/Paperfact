# Release readiness — 2026-10-21

The next useful milestone is a **colleague preview**, followed by a public beta.
This is a readiness assessment, not a published release or a guarantee that every
provider works for every account.

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
This link requires access while the repository is private.

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

The version is currently `0.1.0`, prepared on `beta/0.1.0`. Keep the first release
marked as a prerelease. A public repository and a stable installer are separate decisions.

## Installation details for eventual binaries

The build produces a Windows per-user setup EXE, an Apple silicon DMG and a Linux
x86-64 AppImage. It bundles Python and Qt; provider CLIs are separate prerequisites
for AI. Unsigned Windows/macOS builds can trigger platform first-launch warnings.
See [building and publishing](releasing.md).

Installed data lives in `%APPDATA%\Paperfact` on Windows,
`~/Library/Application Support/Paperfact` on macOS, and
`~/.local/share/Paperfact` on Linux. `PAPERFACT_DATA` overrides the location.
Back up the whole data directory privately; share selected research with bundles.
