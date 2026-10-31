# Legacy reading workflow migration

The optional legacy daily queue is a separate workflow. Migration does not create a list, infer memberships, change list reading state, or change daily selection rules.

## Preserved content

- Every queue row retains its finite numeric rank, state, role (including `manual`), explicit parent, reason, and all original timestamps.
- Every reading-log row keeps its integer identity in the prepared local copy, delivery timestamp, optional role and note. Its new workspace receives a fresh portable reading-event identity; remote devices allocate their own local integer IDs.
- Declared UTF-8 Markdown briefs retain exact bytes, including CRLF and literal HTML text. Their dates come from an explicit original date directory, never a guessed timestamp conversion. Sender filesystem paths are passive archive observations and never wire or activation authority.
- Orphan papers and workflow rows remain independent of list membership. Current workflow content is rebuilt with fresh authority; prior operations, conflicts, pending/deleted artifacts, sources and histories stay in the independent recovery archive.

An initial local copy and each `backup -> detached restore -> prepare editable copy` cycle use the same typed validators and independent inspected backup. They do not activate a workspace, upload anything, replay old jobs, select an account or call AI.

## Closed wire formats

`research_content/queue_entry` has the fixed owner/main identity. Its ordered parent closure contains the owner paper and, when distinct, its explicitly declared secondary paper. `research_content/reading_event` has a fresh UUID key, one paper parent, immutable delivery timestamp, optional role/note and an optional exact Markdown descriptor.

`research_file/legacy_brief` uses the event UUID as its slot. Its closed body is `{version: 1, paper_id, event_id, event_incarnation, legacy_day}`. The manifest contains one `markdown` asset with media type `text/markdown`, bounded to 8 MiB. It has no source-PDF assertion and uses the existing incomplete input-version envelope. Body metadata is bounded to 4 KiB. File transfer validates SHA, exact size and native file identity; this is byte integrity, not a claim that prose or embedded content is trustworthy.

Metadata can arrive before file bytes. An unavailable brief remains unavailable while notes remain editable. Activation requires the current paper lifetime, current reading-event incarnation, exact descriptor and the sealed materialized closure. Event deletion or clearing the brief prevents a late download attaching it again. Markdown is projected as read-only text on mobile and never executed as HTML.

## Companion-context changes

The existing `queue.add_companions` action can change the optional parent of a pending queue item. A sealed observation from that actual writer authorizes a new queue incarnation, preserving the fixed owner and deterministic main identity. It does not authorize a raw SQL parent rewrite.

The shared graph adds only this active queue transition: a fresh incarnation equal to the new operation ID, unchanged exact owner reference, changed optional root identities, active old and new roots, an accepted queue creation receipt, and exact data-head plus structural CAS. Same-incarnation reparenting, changed owners, unrelated dependencies and unknown identities remain rejected. Existing generic explicit restoration of the same parent identities is unchanged; refreshing an epoch is not an active context transition.

## Older experimental enrolled workspaces

Opening an older experimental database never creates just one missing capability table. Legacy actions and incoming projections require the complete closed file/content schema and, when capture is enrolled, all six exact queue/log capture triggers. Missing or changed capability metadata produces a migration-required error before delivery; raw legacy mutations are denied and incoming batches roll back inbox, cursor and projections together.

The tested upgrade is explicit: create a complete backup, restore into a new detached folder, inspect it, then prepare a new editable copy and an independent backup. This preserves source bytes and SQL and creates fresh authority. Fresh unbound 0.4 data follows the normal initial-copy path. Unsupported source closure still blocks this upgrade; there is no partial-table repair or old-job replay.

## Unsupported inputs remain visible blockers

Unknown schemas/records/files, nonfinite ranks, unsupported states, naive timestamps, unresolved owners/parents, missing or outside-owned brief bytes, invalid UTF-8, and unsupported queue pins do not become silently partial editable copies. Initial brief staging is bounded to 512 MiB; backup collection spools one bounded brief at a time rather than accumulating all text in memory. A missing pending declared blob blocks a complete recovery package.

Queue pins still require their own typed migration. This is a remaining legacy workflow capability, not permission to archive-and-drop those rows. Unregistered future lineage/chat formats remain blockers until their maintained validators are integrated.

## Explicit test-intent change

The previous valid-row blanket blockers in `test_workspace_enrollment.py` (queue/reading-log cases) and `test_recovery_adoption.py` now assert positive lossless migration and fresh live authority. This is the approved newly supported behavior. Unsupported-scope, queue-pin, malformed-state/time and missing/outside-byte negative tests remain. New fixtures cover exact bytes, relative declared paths, late mutation, cancellation, repeated adoption, rollback/retry, actual daily production, companion transitions, two-device transfers and cross-language graph/CAS vectors.

This candidate is fixture-tested. Release installation, real accounts, live research, full application acceptance and the repository-wide gate are separate checks owned by the integrating maintainer.
