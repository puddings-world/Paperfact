# Joining existing lists across devices, and previewing list changes (v0.5)

Status: requirements, 2026-10-28. Owner: the sync implementation (Codex). Depends on
[paper-identity.md](paper-identity.md) (Claude, `feature/0.5-paper-identity`).

Sync already replicates list edits as operations, gives a list/paper pair one
membership id on every device, and retains conflicting versions. Two gaps remain
where a reader's lists can still be duplicated or overwritten.

## 1. Nonempty join

**Situation.** A second device already holds research when it joins a workspace:
the same bibliography imported on both, the same list edited on both, or a list
received earlier as a shared package. [sync-operations.md](sync-operations.md)
leaves "legacy adoption and nonempty join" as explicit workflows.

**Requirements**

- Joining never replaces either device's lists, memberships, notes or analysis, and
  never runs without the reader seeing what it will do.
- Lists: match by sync/bundle identity first, then propose same-named lists as one
  list; the reader confirms each pairing or keeps them separate.
- Papers: map the joining device's records to the workspace's with
  `paper_identity` rules. `same` maps after preview; `likely` and `check` need
  the reader's confirmation; unmatched papers are added as new. Never match by
  title alone outside those rules.
- A paired list is the union of both memberships. Order: the workspace's order,
  then the joining device's extra papers in their own order. Per-membership
  conflicts (reason, reading state) follow the merge table in paper-identity.md.
- The join is one atomic, retry-safe operation set with a receipt; interruption
  leaves both sides as they were. A backup precedes it.
- Tests: two populated fixture workspaces with overlapping lists (shared DOI,
  identical title, a `check` pair, a same-named but unrelated list) converge with
  no lost notes, no duplicate memberships and no silent merges.

## 3. Preview before applying list changes

**Situation.** Applying another device's changes, a join, or a shared package
(`bundle import`, which today either keeps the receiver's rows or `--replace`s
them) gives the reader no view of what will change.

**Requirements**

- Before applying, show per list: papers added, removed, reordered; reasons and
  reading states changed; and conflicts, each with both versions.
- Routine sync of independent edits applies without a prompt; the preview is for
  joins, package imports and any batch with conflicts or removals.
- Conflicts keep both versions until resolved; resolving is itself an operation and
  may conflict. Removals are recoverable.
- The same preview serves the 0.4 package import, replacing the all-or-nothing
  `--replace` choice with per-change acceptance.
- Previews are computed without writing; applying uses the previewed set exactly,
  refusing if the target changed in between.

## Interface between the two branches

`paper_identity.find(conn, within=ids)` returns groups (`kind`, `papers`,
`reasons`, `research`, `keep`) and is read-only today. The planned
`paper_identity.merge(conn, keep, drop)` is local-only; for enrolled workspaces the
join needs a sync operation that aliases a dropped portable paper id to the kept
one. Agree that operation's shape before either side implements merge for synced
papers.
