# Inactive lineage source capture

This callable library stages one explicit local focal paper and zero to three
related records. It activates no task, store, producer, model call, UI, sync,
source-owner, package, history or recovery path. The two rejected lineage hooks
remain unapplied. This is not complete lineage or release acceptance.

`capture(database, focal_id, related_ids, legacy_root=..., documents=...)` requires
existing paper lifecycle observations. It creates no schema, lifecycle, portable
paper identity or persistent corpus UUID. A process-sealed `CorpusSnapshot` binds
the exact selected local records, bibliographic snapshots, current workspace/device
binding when installed, native database identity and sealed original PDF bytes.
Report SourceIDs digest bibliography and PDF content; they do not merge records
or establish paper/citation identity. A future typed set supplies separate corpus
UUID/parent ownership; this helper does not substitute for that authority.

Pass actual loaded `ResolvedDocument` objects to retain loaded A even after desired
B changes. `current` means those captured sources and owners remain intact, not
that A is the latest desired version. Source bytes, native file revision, reader
lifetime, parent lifecycle, bibliography, binding or native database replacement
invalidate current verification. Initial native database identity is observed
before the first connection and checked through final source verification; an
unknown identity is refused. WAL/checkpoint timestamps are not workspace identity.
The SQL operations reuse the existing read/write-capable research connection but
issue reads only, never initialization or publication. Actual byte/outbox controls
and handle-close replacement tests cover this behavior; no general SQL sandbox is
claimed. Missing databases are not created.

`pages` and `verify_snapshot` use immutable captured bytes and remain available
after the live source changes, with `original_snapshots` scope. `verify` checks
current ownership/source integrity before and after quote location. Exact located
text is not semantic support, influence, verified citation identity or correctness
of the researcher's proposal. Citation-only attribution cannot supply the related
paper's own characterization; later development needs the later citing passage.
Missing/unavailable/ambiguous/invalid-locator findings stay explicit. No search,
download, directory scan, model routing or AI calls occur on capture/read/verify.

Bounds: four selected records; 32 MiB per PDF, 64 MiB aggregate and 96 aggregate
pages; 240 KiB extracted producer input; 200 KiB proposal JSON, 12 statements,
48 passages and 4,000 characters per quotation. Invalid/duplicate/nonfinite or
oversized input fails without truncation or partial reports. Same PDF+bibliography
on distinct records may be captured separately with exact distinct local owner
bindings; selecting both together is refused as `duplicate_source`, never merged.
Cancellation leaves capture/source bytes unchanged. No retry or identity minting
occurs. Persistent corpus, retained original lifecycle, package/recovery/source
ownership and UI worker/delivery guards remain required future integration.

Capture/current/verification perform bounded SQL, PDF reads/hashing and parsing.
Future UI wrappers must schedule that work off the GUI thread and apply their own
view/lifetime/native metadata delivery guards. The library imposes no generic
main-thread restriction on non-UI callers. Focused fixture evidence belongs to the
frozen handoff; no live accounts, owner research or complete full gate was run here.
The original frozen 33 tests are preserved byte-identically; modern controls add
actual managed A/B, native admission/final-check races, read-only/outbox/lifecycle,
closed-reader/native source revision, cancellation and actual byte bounds.
