# Structured claim draft continuation

2026-11-02, isolated `0.5.0.dev`, unreleased. The **content revision core** has
selected local evidence. Receiver selection and durable private draft storage now
also have [separate backend evidence](claim-draft-private-state.md). Atomic source
application and the desktop editor remain required. There is no new
user-facing claim editor yet. This does not complete the recovery milestone.

## Implemented content operation

`claim_draft_revision.editable(baseline)` extracts editable assertions, proposed
judgments and quoted passages from a bounded, validated claim-set JSON baseline.
`parse(baseline, raw)` validates a closed draft without file or database access.
`revise(snapshot, baseline, raw, cancelled=...)` rebuilds scientific content using
the existing exact-original quote verifier. The process-owned evidence snapshot
is never deserialized from a research package.

The closed draft contains only `format`, `baseline_digest`, `source` and `claims`.
It is bound to the **whole saved baseline**, including its original inputs and
generation metadata, not merely a PDF hash. It accepts at most 16 claims, 48
passages and 220 KiB encoded JSON. Duplicate fields, nonfinite values, unknown
fields and empty groups refuse. Deleting the whole set needs a separate explicit
deletion action; an empty editor must not silently erase research.

Editable passages contain quote/page/anchor and an optional proposed citation.
Saved report IDs, location flags and semantic authority are not editable inputs.
All locations and identities are rebuilt from the captured bytes. An unlocated
old passage starts without asserted coordinates; a new explicit verification may
find it. A changed quote with obsolete coordinates does not inherit its old
located status. Missing and ambiguous quotations retain their honest states.

The result contains only `body`, `baseline_digest` and `draft_digest`. It is
**a proposal, never permission to write**. The new body records `backend=manual`
with no requested/returned model, retaining original analysis-input digests.
The original baseline must remain immutable in private history. Locating words
does not establish scholarly support; judgments remain caller proposals and
external citation identities stay unresolved.

An original-A snapshot can produce a review proposal even after current B is
selected or the old path changes. The publication adapter must independently
revalidate source ownership, the exact displayed target and the current reader
context. It must not substitute B, open an old sender path, or treat this result
as authority to publish. The core calls no model or database writer.

## Complete workflow contract (partial)

The local generation/archived private baseline, fresh receiver observations and
private storage slices now have selected coverage. Source verification/application
has since gained [local interacting evidence](claim-draft-application.md). The list
below retains the whole contract; UI and other lanes remain incomplete.

1. **Typed archived baseline.** Read the actual generation/conflict history using
   its closed protocol. Preserve original analysis inputs separately from the
   receiver's current content. Do not coerce claims into the generic text route,
   whose existing refusal tests remain unchanged.
2. **Explicit receiver target.** Capture its native database identity, binding,
   paper lifecycle, portable identity, claim-set observation and selected PDF.
   Handle cross-copy identity mapping explicitly; this core does not grant
   arbitrary source/owner retargeting. Preserve both old and current variants.
3. **Private structured drafts.** Add a distinct typed resume origin and closed
   validator to the existing private draft/history boundaries. Save two variants,
   restart, back up, adopt and recover without old paths or live retry authority.
   Adding an origin to an allowlist alone is insufficient.
4. **Source verification and application.** Reuse source staging only after the
   typed claim base is validated. Verify A without replacing selected B. Keep
   source publication, accepted claim set, outbox and decision receipt in one
   transaction. Failure rolls back; retry cannot duplicate or overwrite newer
   research. Rechecking a failed source revokes earlier permission.
5. **Desktop form.** Show assertion, proposed judgment/reason and quoted passages
   as editable fields, with source status and original/current comparison.
   Keep raw JSON out of the ordinary user flow. Separate private Save, Verify
   original and Confirm Apply; coalesce work and retain drafts through cancel,
   switch, close, error and two-window races.
6. **Full journey.** Actual producer -> two private variants -> independent backup
   and adoption -> receiver with B -> choose target -> inspect A -> edit -> verify
   -> confirm once -> offline peer -> return -> backup again. Keep this journey
   unaccepted until it actually passes, followed by full checks and device gates.

The core covers content revision; the separate private backend covers locally
tested target/storage/recovery slices. Source application now has selected backend
evidence; native UI and remaining transport/peer claim-edit paths remain incomplete. Highlights and decks need their own
typed contracts, not this claim schema. No new AI account or login is required
for manual editing; credentials never travel with research.

## Evidence

22 new actual-PDF cases and 91 existing source/schema/claim-refusal cases pass
together: 113 passed, zero failures/errors/skips, 92.37s pytest / 93.44s runner.
979 source/test/script inputs stayed unchanged during execution. These are
selected fixtures, not a complete application or installed-device pass.

The first absent-operation check failed at import as expected. The first
implementation run had 20 passes and one oversized-parameter setup/teardown error:
its default pytest ID exceeded Windows' environment-variable length. The new test
uses short descriptive IDs, preserving its payload and assertions; the final
selected run passes. No older test file or expectation changed.

[Human scenarios](testing/claim-draft-revision-scenarios.md) ·
[Full resumption contract](review-draft-resumption.md) ·
[Release scope](roadmap-0.5.0.md).

## Subsequent native UI

The source-application and native-editor slices now have matching selected local
evidence. Earlier core-only scope statements above are historical. Broader native
and typed-history boundaries, claim CLI/MCP and full peer/device/release acceptance
remain open. [Current operation/UI contract](claim-draft-application.md).
