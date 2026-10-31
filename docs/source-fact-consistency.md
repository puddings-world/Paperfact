# Source fact and consistency core

Status: local v0.5 core candidate. This is not a wired audit UI/CLI, completed
A3 workflow, scientific evaluation, model extraction feature or release claim.

## Explicit inputs and ownership

`audit_facts.prepare(capture, proposals)` takes an actual current
`audit_inputs.AuditCapture`, not a path or a payload-supplied workspace. Its
already verified `EvidenceSnapshot` retains the exact PDF bytes and reader owner.
The capture's existing native DB observation, binding, parent lifecycle and saved
item snapshot remain authoritative; missing legacy bindings are not promoted.
No migration, lifecycle creation, global cache lookup or research write occurs.

The closed proposal is:
`{format, source: {paper_id, document_hash}, study_type, facts}`.
The source must exactly match the capture. Study type is empirical, theoretical,
qualitative, review, mixed or unknown; this classification is itself a proposal.
There are no discipline-specific required quotas or universal quality scores.

Each fact has exactly:
`id, category, statement, origin, scope, value, location, passages`.

- Category: design, assumptions, sample, materials, method, outcome, comparator,
  units, uncertainty or limitations.
- Origin: author_stated, reviewer_inferred, not_reported, not_applicable or unknown.
  The last three require a null value; an explicitly reported zero is a number.
  An omitted fact is not evidence of absence or proof that the author omitted it.
- Scope has exactly construct, outcome, comparator, population, time, unit,
  statistic and conditions. Each is a bounded explicit string or null. For
  theoretical work, an explicit non-applicable population/comparator can be
  supplied as text; the core does not invent it. Two nulls do not establish scope.
- Value is null, `{kind: "text", text}`, or
  `{kind: "number", decimal, rounded_places, derived}`. Decimal is an exact
  bounded decimal string, not a floating point approximation. Rounded places is
  null or 0–12; derived is a boolean. No formulas or derivations are executed.
- Location is `{kind: "source"}`, or
  `{kind: "output", item_id, start, end}`. Output offsets are zero-based Python
  string indices with an exclusive end, in the exact captured item text. That
  substring must equal the complete fact statement. No Markdown/text normalization
  is applied to those offsets. Missing items or mismatched offsets reject the
  whole batch.
- Passages retain each exact quote and its requested page/anchor. The existing
  closed evidence verifier returns located, missing, ambiguous or invalid-locator
  findings in the exact captured PDF. It never searches another PDF for a match.

The sheet preserves each saved item's actual document binding: exact, unknown or
different_original. A source quotation can be located without assigning that PDF
to a versionless saved note. An input digest is never a PDF document hash.
The derived owner observation hashes the actual captured owner state/local paper;
it distinguishes separate workspace records, including identical PDF bytes.
It is a diagnostic observation, not a portable source receipt or grant of authority.

The frozen process-local `FactSheet` exposes a defensive JSON report copy.
JSON serialization cannot recreate its sealed source authority, and rebinding it
to a different capture fails. Reports keep exact source, owner/input/proposal
identities, output offsets and all quote findings. All fact meanings,
attributions and scopes remain researcher-review proposals. **Quote located
does not mean the quote supports a fact or that a reported number is correct.**

## Bounded deterministic comparison

`audit_consistency.compare(sheet)` compares the explicit facts only. It returns
the facts and both location references for every pair, without rewriting research.
Only facts with exact source bindings, author-stated attribution, located evidence,
the same category and fully populated identical scope can receive value comparison.
Unknown study type, scope, origin, missing/ambiguous evidence and source mismatch
produce explicit not_comparable reasons. No synonym matching, unit conversion,
statistical inference or automatic scope alignment occurs.

Equal exact numbers yield same_value. Unequal exact numbers yield
numeric_disagreement requiring review. Rounded numbers use explicit closed
half-unit intervals at the supplied precision: rounding_compatible and
rounding_disagreement remain separate from exact numeric disagreement.
Closed endpoints deliberately preserve possible tie-rounding compatibility.
Derived values yield derived_value without recomputation or certification.
Text comparison is exact lexical same_text/text_difference only. None of these
states asserts scientific contradiction or semantic support; supplied values and
scope may themselves be wrong. Uncertainty and limitations can be explicit facts;
the core does not interpret confidence intervals or author limitations as failures.

Bounds are 256 KiB encoded proposal JSON, 32 facts, 64 total passages and four per
fact, with at most 2,000 characters per statement/text value, 256 per scope field,
4,000 per quote and 64 per fact ID. Decimal accepts at most 18 integer and 12
fractional digits. Duplicate IDs, unexpected keys, malformed scalars, mismatched
locations or exceeded limits fail the entire batch. No truncation or partial
success is returned. Thirty-two facts yield at most 496 pair findings.
Existing PDF limits and normalization are inherited unchanged from research_evidence.

Both functions accept explicit `cancelled` and `current` guards and recheck before
return. Cancellation, changed capture/source/native identity or stale supplied
context discards the result. The capture's conservative physical DB/WAL fence is
preserved; callers can explicitly capture again after an unrelated checkpoint.
No implicit refresh, retry, model route, completion or persisted cache is added.

## Execution and remaining boundaries

Call preparation/comparison from a worker. Existing source hashing, PDF extraction
and owner checks are not GUI work. This slice creates no scheduler or Qt widget,
and the worker fixture checks the actual extraction thread. Future UI/CLI adapters
must preserve workspace/paper/document/view epochs, native metadata delivery checks,
drafts and busy/close ownership; no current screen is claimed to use this core.

Extraction from arbitrary outputs, paid selection, atomic assertion extraction,
deck/list/lineage corpus adapters, retained multi-source comparison, source jumps,
persistence/sync/recovery and model routing are outside this five-file slice.
A future explicit model extraction job must capture the existing Audit route once;
reading these reports must still make no calls. No appraisal eligibility is changed.

Synthetic owned PDF/saved-output tests verify bounds, identities, exact locations,
ambiguity, cancellation, stale guards, immutability and deterministic arithmetic.
They do not establish scientific precision/recall. A rights-appropriate, manually
reviewed corpus and independent scholarly evaluation remain required.
