# Source-grounded claim extraction

Status: isolated core implementation; reader controls and source-aware claim review
are separate integration work. A model proposes claims. Deterministic quotation
location verifies source coordinates, not whether an assertion is scientifically
supported, causal, generalizable, central or correct.

## Shared operation

```python
from paper_daily.claim_jobs import ClaimJob, ensure

job = ClaimJob.capture(database, paper_id, legacy_root=pdf_directory,
                       connections=captured_connections,
                       document=loaded_original_document,
                       owner=loaded_reader_owner)  # optional original view guard
outcome = job.run(cancelled=is_cancelled)
saved, reason = ensure(database, paper_id, legacy_root=pdf_directory)
```

The explicit workspace, original source and observed deep-dive/close-reading
versions are captured before remote work. `document` must belong to that workspace
and paper; omitting it resolves once at capture, never after AI completion.
An optional loaded owner is rechecked inside the capture transaction before any
lifecycle write and around cached reads. Textless PDFs fail before AI; saved
analysis never substitutes for unreadable original text or an unrequested OCR job. The
operation proposes a few central argument claims, preferably three to five, with
supporting quotes, comparison conditions and limitations. It accepts at most 16
claims and 48 passages, without padding a sparse result. Study-type checks and
language follow the research rather than machine-learning defaults.

One completion uses task `claims` through the existing captured-connection facade.
It inherits the global provider/account/model unless its per-feature selector
explicitly overrides them. Invalid selected profiles fail; no substitute provider
is tried. Requested and returned model IDs are stored separately, without account
IDs, credentials, endpoint URLs, usage logs or private configuration.

`ensure` reuses saved matching input/source versions without another AI call.
Canonical deletion remains known-empty without a separately confirmed restoration.
`force=True` alone neither restores it nor spends AI. Only an explicit
`restore_deleted=True` requests a new generation against the exact observed
tombstone; an active or newer claim set rejects that stale intent before AI.
A different source or saved analysis invalidates the cache. Repeated calls on one
completed job return its durable publication result. Concurrent active jobs for
the same workspace/paper are deduplicated. No source or model work occurs merely
because an imported claim set is read.

## Original bytes and publication

`research_evidence.capture` creates a process-sealed immutable original-byte
snapshot before AI. It is not wire authority and cannot be recreated from JSON.
`snapshot_pages` supplies bounded original pages; `verify_snapshot` returns
`verification_scope: original_snapshot`. Ordinary `verify` still checks that its
source remains intact before returning. A snapshot report never says that today's
open PDF is the original or that a model judgment was semantically verified.

The model cannot assign claim/source IDs or verification fields. Its closed
proposals pass the same deterministic quote/anchor validator as explicit caller
proposals. Located, missing, ambiguous and invalid coordinates stay distinct;
ambiguous/unlocated evidence has no active jump anchor. A proposed `supported`
judgment remains `authority: caller` with `semantic_validation: not_performed`.
External citation identity remains unresolved without a trusted reference mapping.

The canonical singleton is `paper_claim_sets`, annotation feature `claims`, using
`body_json/source_hash/document_hash/written_at`. Its closed body contains the
report, original input digests and noncredential model metadata. Observed generation
owns publication of research, outbox and retry receipt together. Changes to target,
input versions, paper lifecycle, source, database identity or workspace binding
retain completed original-source work instead of overwriting new content. Valid
completed work also survives a storage failure or cancellation after completion.
Empty generated claim lists fail with an actionable explanation and preserve the
existing set; they never publish a misleading completed state or trigger a paid
retry. Cancellation before generation spends no AI. Native provider termination is outside
this core cancellation seam; pending delivery is suppressed instead.

Confirmed deletion restoration creates a fresh graph incarnation in the same
publication transaction as the row, outbox and durable retry receipt. Concurrent
restoration, newer edits, source/input changes and stale owner/lifecycle state
retain the completed candidate rather than overwrite current research. Generic
JSON review remains keep/export-only; it cannot restore or apply claims.

Claim-set changes invalidate the existing list-visible workspace revision. An
unlisted paper has no list revision; the reader uses bounded background saved-state
checks to refresh it without disrupting ongoing work.

Existing notes, including edited legacy `kind=claim` cards, remain user-owned.
Extraction does not replace them. A future explicit note promotion should reuse
typed note operations rather than revive the maintenance branch's direct SQL
claim-card writer. There should be one reader-facing claims workflow.

## Exact source closure

Before AI, the original PDF is atomically retained under the explicit workspace's
`pdf/.claim-evidence/<owner-digest>/<document-hash>.pdf`. Its hash is declared by the
claim row and generation receipt. A compact private source-snapshot ownership
receipt is committed after the verified bytes, before the model call. It records
original database/workspace/owner/epoch and hash/size, without prompts, answers,
credentials or absolute paths. Failed creators never delete another pending job's
source; interrupted byte/ownership publication repairs on the same captured retry.

The registered `research_source_snapshot_recovery` protocol carries this local
provenance into complete backups, using the existing archive-only original-source
registry. Existing trusted-root source recovery finds A after the current alias
becomes version B. Detached restore archives the old receipt as provenance and
never reactivates its owner/job. It retains the original archive requirement for
reviewed re-export. No receipt path or hash alone grants remote/file authority.

Claim-capable list packages require `claim_evidence` capability and version 2.
The `claim_sources` manifest declares every claim owner's exact original hash and
owned relative asset path. Default complete packages carry that original even
when the current PDF differs. Deliberate link-only packages explicitly mark absent
original bytes; no source version is substituted. Unknown/stripped capabilities,
missing or changed original assets and mismatched ownership are rejected.
Imported original assets remain inspectable and do not activate an old PDF.

Report source IDs record the producer's original identity (portable when available,
otherwise local). Transport envelopes bind the receiver's current paper; that
original alias never authorizes navigation to another owner. Outer content hash,
row document hash and report document hash must agree. Mobile validates and reads
claim content without invoking AI or following source URLs.

Enrollment admits a deterministic duplicate cache file only after validating its
claim row, hashing its actual safe-root bytes and matching the selected verified
primary source. Its coverage is reported explicitly. Prior-version or unowned
source files remain blockers until owned extra-version transfer is implemented.
Owned source-snapshot history also remains an explicit enrollment-migration
blocker until its provenance is transferred. Other history/files may block it too. This slice does not establish
complete workspace synchronization or a released reader experience.

## Verification boundary

Tests use real generated PDFs, simulated completions, actual observed publication,
source replacement, closed claims fixtures, package re-export, private recovery and
mobile loopback/offline fixtures. No real provider, account login, production data,
public upload, autonomous experiment or code execution is involved. Focused tests
are partial evidence; the coherent candidate still needs the full project gate.
