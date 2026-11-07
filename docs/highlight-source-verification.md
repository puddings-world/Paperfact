# Highlight original verification and independent reading

Status: 2026-11-02, `0.5.0.dev`, isolated integration candidate, unreleased.
Typed private drafts now have backend exact-original quotation verification and
independent original reading. Confirmed [atomic Apply](highlight-draft-application.md)
is now available separately. Native highlight editing and CLI/MCP tools are **not
implemented**. Verification alone does not publish research.

## Separate operations and authority

| ResearchReview operation | Result and boundary |
| --- | --- |
| `verify_highlight_draft(preview, body, cancelled=...)` | Stage/recheck owned original A and the selected target/B; compare actual producer page-text provenance; rebuild every edited quote location. Return verified or needs_location with apply=false. |
| `highlight_draft_report(preview)` | Bounded content-only report for this process and exact edited-body digest; no serialized capability or academic support verdict. |
| `prepare_verified_highlight_original(preview)` | Read staged A through the current source verification; supports unresolved quotations so the researcher can inspect and repair them. |
| `prepare_highlight_original(preview, reference=...)` | Independently read this declared owned A, even after analysis/mark changes; an optional saved reference pins exact draft ID/revision. No modification authority. |

The shared `review_draft_originals` boundary handles independent claim/highlight reads
through explicit closed domain dispatch. Existing claim entry points retain their
signatures and domain checks. GUI admission uses bounded native observations only;
worker preparation/revalidation handles SQL, byte verification and PDF parsing.
No model call, provider login, remote service or current-PDF activation is required.

## Verification contract

- Keep A's byte identity distinct from current B and the retained analysis's extracted
  page-text digest. Recompute producer-compatible bounded page provenance from A.
  The digest is not a revision ID; complete target/body/mark observations still matter.
- Use the shared typed source-staging and current-target checks. Do not recapture
  a newer target, follow a sender path or reuse an unowned cache merely by hash.
- Missing/ambiguous/wrong-page/unselectable quotations remain visible issues. Any
  unresolved item prevents complete analysis/mark-plan output, while verified A can
  still be read. Retain prior coverage provenance without claiming a new AI analysis.
- Runtime verification stores only bounded content/metadata, not another full PDF
  copy. An edited-body digest, service and source object identity bind the result.
  Cancellation, explicit demotion or failed rechecking revokes the old result.
- The private codec still requires apply=false. Internal source-staging previews
  remain process-only; normal persistence drops runtime fields. Reload always needs
  fresh verification. Generic Decide/Keep still refuses this typed domain.
- Existing producer/evidence size/page limits remain explicit errors; no paid retry
  or automatic source substitution is introduced. Reasons and roles are human edits,
  not semantically verified claims. Reports identify manual work and no semantic check.

## Independent read contract

The declared source must belong to the current native database/binding, portable
paper and parent lifetime. Source retirement refuses without fallback. Complete
adopted private history may authorize independently owned recovered bytes; a cache
file alone or a historical owner path cannot. The old folder can be unavailable.

A new analysis, visibility change or unrelated note does not grant another Apply
permission and does not by itself prevent reading the original A. Native replacement,
modified bytes, retired source, changed private revision or lost owner refuses.
Proofs cannot be serialized. Claim/highlight wrappers reject cross-domain admission.

## Remaining complete journey

The confirmed atomic backend now covers restoration choices, complete group
rollback/retry and actual remote conflict/recovery/offline-peer/second-backup data
journeys; see its separate result receipt. Native fields/confirmation, shared
CLI/MCP, complete derived reading-link audit and their interrupted user journeys
remain open. Verify installed platforms and production separately; backend/source
checks and old claim transport tests do not prove these remaining outcomes.

[Executed local actions](testing/highlight-verification-scenarios.md) ·
[Private-state contract](highlight-draft-private-state.md) · [Full scope](roadmap-0.5.0.md)
