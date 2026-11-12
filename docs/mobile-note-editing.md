# Editable text notes across desktop and mobile

0.5.0.dev local candidate, 2026-11-02; unreleased.

An ordinary desktop note includes creation time, kind and nullable position fields.
The PWA previously treated every such payload as read-only, even a text note with
no PDF position. Receiving a desktop note therefore prevented continued phone edits.
The fix recognizes a closed unpositioned text-note contract, preserves its complete
metadata, and edits only the body. It adds no model calls or account dependency.

## Bounded write contract

- Existing two-field text notes remain supported.
- A validated six-field note is editable only when `kind == "note"`, `page == null`
  and `anchor == null`. Body saves preserve `paper_id`, `kind`, `created_at`, page
  and anchor exactly. Low-level builds reject metadata stripping or mutation.
- Positioned notes, quotations and unsupported kinds remain read-only. Their old
  flatten/delete rejection tests remain unchanged.
- Saves use the observed note and parent incarnation; competing edits preserve
  the draft and refuse stale overwrite. Identical body saves enqueue once.
- Explicit unpositioned-note deletion uses its observed identity and a tombstone;
  the canonical old operation remains available as history.

## Clean editors and unsaved drafts

Successful save clears only the matching view draft. If newer text was typed while
that save completed, it stays dirty. A clean view follows a received note revision
and captures its current observation. A local or persisted unsaved draft keeps its
original observation, text and stale-save warning; incoming content cannot rebase it.
This fixes a false conflict card and disabled Save after an otherwise normal update.

## Evidence

The actual Qt NoteEditor/Data journey, together with existing note-observation
checks, passes 22 cases. The complete maintained mobile gate passes 512 unit cases
and all 13 authenticated Python HTTP scenario programs. Its new desktop writer
fixture covers metadata-preserving phone saves, offline serialized reopen, duplicate
save, desktop return edits, both stale variants and synchronized deletion.

An owned headless browser also exercises actual PWA controls and IndexedDB: offline
typing, double Save, offline page reload, manual cached-workspace selection,
reconnect, desktop reply, another real phone save and a genuine unsaved draft during
an incoming desktop revision. Existing six browser groups remain intact; only their
Connection target now uses its visible name after header actions were added.
The offline shell cache advances from v13 to v14; its exact-version test advances
with it, retaining static-only cache/privacy assertions. Mobile gate discovery now
requires the new HTTP program and tests that its failure propagates.

## Remaining gates

At that note-editing checkpoint, reload required manually choosing the workspace
and narrow-header labels wrapped. Both are now addressed by the
[subsequent cached-startup/header candidate](mobile-workspace-startup.md).
The earlier case receipts remain scoped to their original snapshot.
This is not installed iPhone/Android/Mac or production login/service acceptance.
The complete application check remains red on the separately tracked citation
completion policy; no commit, installer or release is claimed.

[User actions, results and actual screenshots](testing/plain-note-editing-scenarios.md)
· [Mobile design and gates](mobile-0.5.md) · [Release status](status-0.5.0.md).
