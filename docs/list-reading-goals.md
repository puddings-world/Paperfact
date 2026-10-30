# Per-list research purpose

Status: local v0.5 candidate; no public-release or cross-device acceptance claim.

Use **Research data → List research purpose** to write the question, intended
use, background or reading depth for a list. The field is optional, plain text,
and limited to 2,000 Unicode characters. Saving or clearing it never invokes AI,
reruns analysis, changes model routing, or edits the list description or notes.

**Research tasks** previews include this purpose when the open paper belongs to
the selected list. Review/edit the question, then send it explicitly through the
existing Q&A workflow. Changing lists, purpose, workspace or paper during preview
cannot insert a stale draft. Existing unsent questions still need replacement
confirmation.

The shared domain is a list-scoped `research_content` singleton:
`feature=reading_goal`, `key=main`, with `body` and `written_at`.
It has no PDF provenance. Desktop edits carry their observed target and parent
lifecycle through the existing generation boundary. Concurrent edits retain a
candidate; repeated identical saves reuse their receipt. Deleting a list removes
its current purpose and journals that deletion; recreating an ID cannot inherit
the old purpose. Synced tombstones still require explicit restoration.

Packages containing a purpose use package format 2 with a declared
`reading_goal` capability. Canonical reading annotations and deletion markers
also require format 2, with their own explicit capabilities. Older readers reject that
capability instead of silently discarding it. Packages without this extension
remain format 1. Default import preserves an existing local purpose; explicit
replacement may update it. This is a package capability version, not an app
release-version bump. Recovery includes the extension and accepts older archives
without the table. The mobile reader projects it separately from generated
surveys and renders plain text; mobile editing is not implemented.

All peers receiving the new research-content feature must run compatible v0.5
clients. No server, login, AI subscription or analytics credential is shared.
A prose research purpose does not establish claim grounding or lineage accuracy;
those retain their separate validation requirements.
