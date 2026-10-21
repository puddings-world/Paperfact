---
name: agentic-usage-refresh
description: Implement responsive account usage displays with shared background polling, deduplication and invalidation after AI calls. Use for stale quota displays, account-switch races and unknown usage values. Do not assume every provider exposes plan or model quota APIs.
---

# Refresh account usage without blocking the UI

1. Define a normalized snapshot: account identity, observation time, plan if
   reported, quota windows/model buckets if reported, and error/stale state.
   Unknown is distinct from zero. Shared quota buckets must not be added together
   or misrepresented as independent model allocations.
2. Query only a supported read-only usage interface. Do not send a generation
   prompt to obtain quota, trigger onboarding, or impersonate a different client.
   Preserve login state and local usage receipts if remote quota is unavailable.
3. Scope cache identity to the connection and configuration namespace, excluding
   secrets. Deduplicate concurrent readers of the same account. Bound freshness
   and retry frequency; render cached data immediately with its observation time.
4. Start optional background prefetch from the application lifecycle, not widget
   constructors used in tests. Include known local CLI logins where supported,
   even if the user has not saved them as profiles; deduplicate identities.
5. Invalidate only the used account after completion, including failures that may
   have consumed quota. Capture the invalidation revision before the query.
   An AI call arriving during a query must leave the result eligible for refresh.
   If jobs use subprocesses, an in-memory dirty flag alone is insufficient.
6. Give each UI request an account/selection generation. Reject late results when
   the user has switched accounts or closed the view. Cache/worker ownership must
   outlive a transient dialog without allowing callbacks into destroyed widgets.
   Separate canceling a view's interest in read-only metadata from canceling an
   authentication or generation operation. A query can finish without the view;
   its worker must not touch UI objects. Discovery failure must remain retryable,
   not become a permanent successful-empty catalog. Display cached choices during
   refresh while preserving the selected routing ID.
7. Test concurrent refresh producing one query, query-time invalidation,
   account isolation, stale replies after switching, close while busy,
   unavailable/partial/zero/full quota, failure/retry, and startup prefetch.

Choose TTL/backoff based on provider cost and limits; Paperfact's values are not
universal defaults. Subscription quotas, local invocation counts and billing
receipts are separate measures.

See [Paperfact evidence](references/evidence.md).
