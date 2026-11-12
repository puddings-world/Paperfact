# Explicit grounded-lineage producer checkpoint

This is a reusable production **core**, not an activated or complete v0.5 feature.
No desktop entry, saved writer, task-registry change, sync domain, package,
enrollment, recovery or mobile integration is included. Research-task question
templates do not implement this workflow. The rejected historical lineage hooks
are not copied, applied or used as an alternative execution path.

`lineage_jobs.LineageJob.prepare` takes one actual `CorpusSnapshot` and an existing
`FrozenRoutes` value explicitly declaring `lineage`. It refuses an Ask-only map,
an undeclared/default fallback and backend `none`. The shared task registry does
not yet include Lineage; callers must explicitly supply the already resolved
private route. There is no route discovery, login or provider probe on prepare.
The facade receives the captured account/configuration and `task='lineage'`.
Credentials, account directories, source text and the route map are excluded from
job repr and report metadata. Future UI must show current intent separately from
the completed run's requested/returned models, leaving absent returned IDs absent.

## Core behavior and limits

- Prepare, run and result `current()` require a worker. Report/execution getters
  return defensive JSON copies without SQL, parsing or model calls.
- The selected corpus is exactly the existing one-to-four sources, focal first.
  Its current database identity, binding, paper lifetimes, selected identities and
  original byte ownership are checked before spending a call. The focal original
  is mandatory; a missing selected peer remains explicitly unavailable.
- Full bounded normalized page inputs come from `research_lineage.pages`; sources
  are not omitted or silently truncated to fit. The existing 64 MiB/96-page and
  240 KiB input-text limits apply. The total prompt cap is at most 256 KiB.
- One explicit facade completion is allowed. The requested output limit defaults
  to 4,000 tokens, may be explicitly chosen up to 8,000, and must fit the captured
  configuration. Invalid/insufficient limits refuse; no clamp occurs. This is a
  requested facade limit, not a universal provider billing/output guarantee;
  existing CLI adapters do not enforce the token setting. The local returned-text
  cap remains 200 KiB regardless of provider behavior.
- A job has a nonblocking single-flight guard; another call while it runs reports
  `already_running`. An existing database/corpus job lock also refuses simultaneous
  duplicate jobs. A successful repeated call returns the cached result. A failed
  attempted completion or malformed reply requires an explicit new job, never an
  automatic call. An unusable reply is released after its first validation error;
  the next run refuses with `explicit_new_job_required`.
- Cancellation before the call spends nothing. A completed response can remain
  privately bounded while quote verification stops. An explicit verification
  retry uses that response, spends no additional call and stays retained after
  cancellation. It does not turn Stop into automatic reactivation.
- Closed proposals pass the existing duplicate-key/nonfinite/schema/reference
  checks. Quotes are checked against the sealed original snapshots. Missing or
  ambiguous quotes stay missing/ambiguous; locating words does not certify the
  proposed interpretation. Relation citation identity remains unresolved and
  semantic validation remains not performed, even if a proposal says supported.
- Source, parent, account-route or supplied view-lifetime changes after completion
  produce an explicitly retained result. Such a result is nonadmissible for new
  installation. No result in this checkpoint is written or installed. Retention
  after a detected change is sticky for that job; returning to the old selection
  cannot silently restore admission.
- `result.current()` checks source ownership only. It does not depend on future
  model preferences and is not permission to publish or deliver into a GUI. An
  already held report keeps its original text/models when next intent changes.
- The `current` callback is a seam for an actual native/window epoch lease, not
  a native-PDF witness manufactured by this core. Backend tests exercise the lease
  callback and real PDF, parent and DocumentReader invalidations. Real Qt load/
  source/view/draft delivery acceptance still belongs to the later UI slice.
- Captured route/configuration does not detect an external vendor login change
  inside an unchanged CLI credential home. No credential-store probing, login or
  account verification is performed or claimed here.

The core retains no SQLite handles, invokes no search/download and writes no
research rows. Its explicit job lock uses the maintained `.research-jobs`
namespace. Reports are temporary process-owned proposals; losing the process can
lose this unsaved work. Durable retention and replay-safe publication are required
follow-on work, not implemented by an in-memory result cache.

## Proposed shared activation, not changes in this checkpoint

Exact current baseline hashes for these proposed shared paths are in
`build/lineage-activation-beforeimages.json`. A future owner must re-admit those
hashes and agree narrow hunks before editing. No whole-file prototype port is
appropriate.

1. **Task routing:** register `lineage` in `ai_profiles.TASKS` and the existing
   desktop task-choice labels. Capture that task's resolved `FrozenRoutes` at the
   explicit action. Missing selected accounts/capabilities fail visibly, with no
   Ask fallback. Opening saved reports reads only `lineage_sets.saved`.
2. **Observed target:** `research_generation.begin_generation` currently rejects
   keys other than `main`, `_target` selects by one owner column, and its closed
   registry lacks `paper_lineage_sets`. Add a narrow typed composite target
   `(focal paper, corpus UUID)`, exact prior target/absence and each selected
   parent's lifetime/identity/source observation. The existing main-key producers
   must retain their exact behavior. Do not force a corpus into a fake main-key
   claim or broaden arbitrary target/table validation.
3. **Typed publication:** use `lineage_sets.validate/validate_row/source_hash` for
   the body and `lineage_sets.convert` for registered local/portable paper IDs.
   Preserve report evidence IDs and source hashes. The ordered graph parents are
   the exact focal-first bindings (maximum four), not whatever papers share a
   title or PDF hash. `lineage_address` supplies the closed address/known-delete
   rules; registering it must not relax generic parents or infer unknown deletes.
   Exact target/source/lifetime CAS, row, outbox and request/candidate receipt must
   share one caller transaction, including rollback, retry and deletion/restore.
4. **Every original, before activation:** `source_snapshots._owner` is currently
   focal-generation-specific; `local_source_owners._claim/_owner_matches` are
   claim-specific. Calling either with a peer pretending to be the focal paper,
   minting fake claims/generation receipts, or retaining only the focal PDF would
   be incorrect. Add reviewed typed lineage source ownership bound to actual
   corpus, source paper/hash and that paper's captured lifetime. Stage and verify
   every available exact original; grant each ownership beside the lineage row/
   outbox in the publication transaction. Cancelled preparation grants no active
   authority. Missing originals have no invented artifact. Completed stale output
   needs all of its exact originals retained with its candidate provenance.
5. **Saved-first desktop:** add one bounded modeless `Why this paper exists...`
   entry under the existing Research tasks surface. Opening lists saved corpus
   reports without search/model work. The researcher chooses at most three peers,
   sees unavailable originals and current Lineage account/model/budget, then
   generates explicitly. Present the prior gap, current change and later
   development with original words, separate interpretation and unresolved checks.
   Source buttons reuse the approved source verification/navigation contract for
   the actual loaded source/hash/epoch. They do not jump to a desired replacement
   or use an AI title as identity. Preserve question/note drafts, reuse a child on
   repeated open, reject stale paper/account/native deliveries, and drain actual
   workers before accepted close/restart/update releases captures. No new tab,
   settings wizard, automatic corpus search or quality score is needed.
6. **Complete preservation before shipping:** enroll the new table/known state,
   bounded producer/request histories, every peer original and private retained
   provenance in capture, initial enrollment, backup and detached recovery. Export
   packages must include the declared corpus/source closure or refuse before
   output with an actionable explicit include-corpus choice; they cannot silently
   omit peer papers or attach same-hash bytes to another paper. Source A must
   survive while primary B stays distinct. Restore/import maps fresh receiver
   owners and never revives old device/job authority. Previously blocked recovery/
   export hooks remain unapplied pending their separately reviewed exact contract.
7. **Projection, sync and mobile:** register strict typed payload/graph/materializer
   and retained-history validators; preserve active and known-deleted exact corpus
   addresses. Add closed source-preserving snapshot/display projection and exact
   `required_capabilities` union with Inbox, queue pins and positions. Old clients
   refuse unsupported closure before cursor/state mutation. A nonempty lineage
   table must never silently disappear from a snapshot. Mobile independently
   validates/displays reports and authenticated exact original assets; no mobile
   AI execution or fake native viewport support follows from this core.

Required later acceptance includes real observed publication/rollback/retry,
concurrent target edits, peer deletion/recreation, all-source retirement, source
A/current B transfer, independent package/backup/restore and mobile HTTP/offline
round trips. The current backend checkpoint does not close those release gates.

## Concrete ownership seams for the next review

The proposed private `paperfact.lineage-source-owner.v1` can reuse the maintained
`research_local_source_owners` columns, with an explicit closed owner branch:
database identity/binding, actual source paper/lifetime, actual source-owner ID,
focal paper/lifetime, corpus UUID and report source ID. Also capture nullable
exact paper-graph and original-artifact incarnation references when synchronized;
unknown lifetime cannot be replaced with hash equality. The canonical association
must validate `paper_lineage_sets` via `lineage_sets.validate_row`, locate that
exact ordered `source_id/paper_id` binding and require its declared PDF hash.
Retained historical candidates must use archive-only proof, not active ownership.
This is a proposal for review, not a newly accepted private schema in this core.

The actual existing file domain is `sync_source_files.py`, not a new generic
source publisher. Its `encode`, `validate_manifest` and `validate_source_closure`
already describe immutable original bytes under the actual paper graph parent.
Its convenience `publish` owns transactions; calling it repeatedly and then
committing the lineage row would not be one atomic compound operation. The
maintained `PreparedSource`, `prepare_source` and `publish_source_in` already
provide sealed staging and caller-owned installation. Reuse that exact seam for
every peer, with typed lineage row/outbox/receipts in the same transaction; no new
generic installer is needed. The lineage association/observations still require
separately reviewed activation.
Known original retirement must refuse automatic republish or same-hash ABA reuse.
Existing `source_provenance.wrap/retain_in` is archive-only and cannot grant an
active lineage source owner.

The actual closed envelope module is `sync_schema_v2.py`; the package file helper
is `bundle_files.py`, while typed package ownership/publication is in
`package_import.py`. Mobile projection is in `domain.mjs::projection` and typed
row projection in `content.mjs::projectContent`. These exact existing paths are
hash-pinned in the proposal receipt. No nonexistent module or old rejected patch
is treated as an implemented seam.

## Root integration evidence

The exact three-file core handoff was admitted to the isolated integration tree.
The independent helper union passed 169 selected cases; the root then passed all
35 new producer cases with zero skips, Ruff clean and 1,193 admitted inputs
unchanged during that gate. See ignored `build/merge-resolutions/lineage-core-root-result.json` and matching XML.
The six root differences from the fork were four reviewed documentation updates
and the independently tested collector source-isolation pair; production lineage
dependencies were exact. No existing source/test file was replaced.

This original-pages-only producer has not used deep/close reading text. Future
`lineage_sets.inputs.dive/close_reading` must stay null unless a separately
approved recipe actually includes that input. A target compare-and-save observation
is distinct from provenance of model-used material.

These are partial backend checks. Shared activation, native UI, durability and
complete portable closure remain open, and the full application gate is required.
