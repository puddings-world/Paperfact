---
name: agentic-provider-routing
description: Design or refactor agentic-app features that select different providers, accounts and models per task while retaining a global default. Use for routing, account-switch isolation and unsupported capability handling, not for inventing vendor OAuth flows or implementing a full external agent runtime.
---

# Separate feature intent from AI connections

1. Trace a feature from UI action to model request. Give it a stable task ID.
   Keep document/list records independent of authentication and provider choice.
2. Resolve task override or inherited global default once per job. Capture the
   resolved provider, account identity, requested model and relevant options.
   Show the effective selection to users; "default" alone is not enough.
3. Send generation through one facade. Provider adapters own transport, credentials,
   timeouts and response normalization. Expose capability availability explicitly.
   Unsupported features should explain what is missing.
4. Keep credentials scoped to the selected account and endpoint. Switching
   providers must not carry the old key/model/base URL into a new connection.
   A missing explicitly selected profile must fail visibly, not silently fall
   back to a different account, model or paid service.
5. Distinguish login/discovery, read-only quota queries, and generation. Browsing
   accounts or quota must not change the active route or generate billable text.
   Use supported vendor authentication paths; verify current official interfaces.
   Prefer the selected account's model catalog to hard-coded family lists. Run
   discovery off the UI thread, deduplicate by account, and reject stale results
   after account changes. Preserve manual model choices on failure or refresh.
   Discovering a model is not proof that an inference request will be authorized.
6. Preserve requested model IDs. Label aliases/service-selected models honestly;
   use official account-scoped display names when available, without sending those
   labels as routing IDs. A missing version is not a reason to guess one; show a
   simple provider-default label until authoritative metadata arrives. Keep full
   account/task detail in settings instead of repeating it in a crowded toolbar.
   Do not invent exact model versions. Record returned model IDs separately when
   available. Model completion does not imply tool-executing agent capability.
7. Add behavior tests: global inheritance, override/reset, invalid profile,
   provider/endpoint switch without credential leakage, browsing without saving,
   failed login preserving state, and account switch while a request is pending.
   Test every entry point, including login prompts launched by a feature: a
   task-scoped picker must read its override and must not overwrite the shared
   account's model. Distinct routing IDs may share a display name; resolve the
   selected item by its identity, not the first matching label. Inherited UI rows
   need metadata refresh too, including after a hidden view becomes visible.
   Use fake adapters; keep real login or paid calls out of stress tests.

For an app supporting only one fixed backend, avoid adding a profile manager
without a concrete need. Authentication and capabilities remain vendor-specific
even when the facade is shared.

See [Paperfact evidence](references/evidence.md) for tested local examples.
