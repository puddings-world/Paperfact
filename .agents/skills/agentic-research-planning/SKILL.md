---
name: agentic-research-planning
description: Build bounded, source-grounded discovery workflows that preview an AI research plan before committing selected records. Use for topic-to-literature routes and similar evidence discovery, not exhaustive-review claims or unverified model bibliographies.
---

# Discover, review, then commit

1. Treat research questions, seed papers and pasted bibliographies as distinct
   input intents. Give question-driven discovery a visible entry point instead
   of requiring the user to supply titles they do not yet know.
2. Separate the desired output from search depth. A reading route, per-item
   annotations and a review protocol need different evidence and validation,
   even at the same retrieval budget. Label abstract-level analysis and planning
   honestly; a protocol is not completed screening or quality assessment.
3. Bound depth by search rounds, candidate count and request timeouts. Additional
   rounds should inspect gaps and counterevidence, not merely repeat the query.
   Show stages and elapsed time when a provider exposes no true progress total.
4. Retrieve identities and source links through source adapters. Models select
   only IDs from that retrieved set and explain relevance; reject unknown IDs,
   duplicates and unsupported relationships before writing any collection.
5. For annotations, validate references to retrieved passage IDs and copy source
   excerpts from those passages. Do not trust model-generated quotation strings.
   Passage provenance does not establish that every interpretation is correct.
   Missing abstracts stay marked; no verified candidates means a retryable error.
6. Capture the provider/account/model route for the whole discovery job. A fallback
   between scholarly indexes is separate from choosing a different AI provider.
7. Keep previews free of collection mutations. Let users inspect evidence and
   deselect candidates. Changed requirements invalidate stale previews; cancelling
   discards results after an in-flight call returns. Do not promise immediate
   provider cancellation if the adapter cannot perform it.
8. Commit the selection and its provenance atomically with an idempotent preview
   ID, without new model calls. Preserve existing curated records. Carry the
   explanation through the normal sharing/export boundary. User-confirmed scope
   must remain distinguishable from an unreviewed model draft.
9. Offer costly follow-up analysis as a separate explicit action after saving.
   Bind it to the created collection ID, guard repeated activation, and reuse
   existing task authentication and job handling. Creating a list alone must not
   imply authorization to analyze every full text.
10. Keep public document retrieval separate from AI analysis. Preserve source
    URLs from discovery, bound parallel downloads, and key jobs by document identity
    across views. Use real byte totals for progress; unknown totals stay unknown.
    Validate temporary files before publishing and coordinate reader/background
    downloads with a shared lock. Cancellation must clean up before shutdown;
    failures need a visible retry rather than an automatic retry loop.
11. Test unknown IDs, invalid passages, partial failures, cancellation, changed
    input, connection changes, repeated actions and write rollback with fixtures.

See [local evidence and limits](references/evidence.md). This skill does not
authorize network calls, credential access or global installation.
