# Inactive lineage validation staging

This local staging slice adds three callable modules and standalone tests. It
registers no store, task, producer, UI, sync operation, projection, mobile
capability, history, source owner or recovery/export hook. It is not complete
lineage, and existing research reads make no model calls.

- `lineage_content` validates a closed serialized report: selected source labels,
  content/bibliography SourceIDs, stages, quote/locator shapes, proposal attribution
  and coverage. It does not verify PDF bytes or locate quotes. Located text is
  separate from semantic support, citation identity and influence; a syntactically
  valid source declaration is not ownership.
- `lineage_sets` separates corpus UUID, ordered paper bindings, report SourceIDs
  and source/input digest. Conversion reads existing paper mappings/existence;
  it mints no identity/lifecycle and never commits or rolls back caller work.
  `source_hash` is not a complete row/owner identity. `saved` uses explicit bounded
  read-only SQL, creates no missing database/table and never promotes a cache.
- `lineage_address` checks a closed lineage address and declared parent identity.
  It refuses known-address stripping/reparenting, including one-parent empty
  deletion, while leaving unknown untyped deletion unclassified. Same kind/ID with
  a fresh incarnation is not itself reparenting. It does not establish live graph
  incarnation, actor, workspace or source authority.

Canonical schema, feature/task registries and wire validation remain unchanged:
lineage operations still fail there. The schema string is executed only by test
fixtures. No application initializer registers it. Future consumers need actual
capture/parent/source proofs and typed operation guards before adoption/navigation.
Corpus UUID and matching title/PDF/hash never merge distinct paper records.

Bounds: four sources and 96 declared pages, 12 statements, 48 passages; quote
4,000 chars, statement/reason 2,000 chars, report 220 KiB and set 230 KiB. Saved
history permits 64 selected-owner rows, each independently bounded; explicit
corpus selection may choose one row from larger history. Invalid, duplicate or
nonfinite JSON and exceeded bounds fail without partial output or truncation.
Missing originals and absent stage coverage remain explicit, not a passed audit.

These helpers take an explicit caller database but do not seal native workspace
identity or parent lifecycle. Future UI SQL work belongs on a worker. Recorded
model metadata remains recorded; this slice generates no receipt. Future producers
must use actual `Completion.reported_model`, never a compatibility alias.

Fresh tests cover valid/invalid shape and budgets, source/paper/corpus separation,
registered-only alias conversion, no identity/lifecycle creation, deleted owners,
caller transactions, saved-read limits/no repair/no AI, native replacement after
closed read handles, retained-address semantics and explicit current nonactivation.
The synthetic golden set is from the preserved frozen fixture; exact provenance,
current dependency hashes and focused counts belong to the handoff. Historical
96/168/163 checks remain separate evidence. Source capture, producer, writable
review, packages/history/recovery, mobile and desktop activation remain outside
this slice. The two rejected hooks remain unapplied. Root owns later integration
and the full gate.
