# Usage data choices

Paperfact's research workspace works without participating in improvement data
collection. Importing someone else's research does not import their consent,
credentials, account settings or background schedules.

## Current behavior

- First desktop launch requires acknowledgement of the usage explanation before
  opening the reader or starting account/quota checks. This is a product explanation,
  not a claim of comprehensive legal terms. Closing it exits without saving choices.
- Improvement statistics are a separate, unchecked optional box. Accepting only
  the usage explanation opens the app without recording or another same-version prompt.
- Usage acknowledgement and the analytics choice save atomically and have separate
  policy versions. Withdrawing analytics does not revoke the usage acknowledgement.
- When an analytics policy changes, an optional notice can appear after the reader opens.
- **同意並繼續** is enabled only after checking the agreement box. Checking a box
  without pressing that button is not acceptance.
- **暫不參與，繼續使用**, Escape and closing the notice do not accept collection.
- **不再詢問這一版說明** remembers a reminder preference for the current policy.
  It never grants consent. Otherwise a declined notice waits at least 30 days.
- A current acceptance suppresses reminders. A new policy requires a new choice;
  a previous purpose/version cannot authorize collection under a new version.
- **使用資料與回饋** at the bottom of the window is available without AI login. Users can review,
  change or withdraw their choice and inspect the exact manually exported data.
- Saving withdrawal clears local events and the random participant identifier.
  Rejoining creates a new identifier. Repeated acceptance of the same policy
  preserves the current identifier and acceptance record.

The in-app improvement notice is `feedback.CONSENT_TEXT`, versioned by `feedback.POLICY`
(`product-statistics-v2`). The separate usage explanation is `onboarding.TEXT`.
The current version authorizes local recording only. Its record contains the
policy version and acceptance time. Reminder preferences are stored separately.

## What is collected

Only an allowlist of workflow metadata: event/feature name, AI provider and model
family, coarse input-size bucket, duration, outcome, app/OS version, and random
identifiers linking workflow nodes. The recorder rejects arbitrary text fields.
It does not store prompts, model answers, papers, notes, account emails, keys or
file paths. Random identifiers are not a promise of complete anonymity.

Local retention is capped at 30 days and 10,000 events. Recorder failures do not
block research. Product events are distinct from local AI usage receipts and
diagnostic logs, which have separate purposes and must not be silently uploaded.

## Shared schema v2

The default preview is a readable summary; the second tab contains the exact JSON
export. `feedback.local_snapshot()` remains an internal local ledger. It is never
the shared export. `feedback.export_payload()` allowlists and aggregates it:

| Table | Fields | Improvement question |
| --- | --- | --- |
| `feature_usage` | feature, count | Which instrumented entry points get used? |
| `outcomes` | feature, kind, outcome, count | Which observed operations fail? |
| `durations` | feature, kind, duration_bucket, count | Where do users wait? |
| `model_usage` | provider, model_family, count | Which provider families need attention? |
| `input_sizes` | feature, size_bucket, count | What input scale should tests cover? |
| `workflow_edges` | from_feature, to_feature, count | Which nested capabilities are combined? |

Time buckets: <10 seconds, 10–<60 seconds, 1–<5 minutes, >=5 minutes, unknown.
Input buckets: empty, <1,000, 1,000–9,999, >=10,000 characters. Model families are
closed categories, never custom model IDs. Unknown text is reduced to `other`.
AI starts count model/input use; completed AI calls and workflow completions are
separate kinds, so summing both is not a meaningful success rate. Missing completions
are not failures or abandonment. Edges describe observed parent/child operations,
not navigation history. Coverage remains limited to instrumented actions.

Exports contain no participant/session/event/trace/node identifiers, sequence,
event date, consent timestamp, account, app/OS fingerprint or raw text. The fixed
retention policy is included; it is not an observation timestamp. These totals
cannot measure unique users, retention cohorts or individual journeys. Repeated
30-day exports overlap and must not simply be summed. A future sender needs a
separately designed deduplication contract before enabling background delivery.
Removing identifiers reduces linkability; a manually shared single-person file
can still be associated with its sender. Do not promise absolute anonymity.

## Sharing and future background submission

There is no receiver or automatic uploader in this release. Users can preview
and export a JSON aggregate snapshot, then decide whether to send it to a developer.
An export saves the reviewed snapshot, not additional unseen events. If consent
changes while the file chooser is open, export is refused.

A future background submission feature needs its own explicit consent. Before
enabling it, identify the recipient/operator, data categories, purpose, endpoint,
server retention, withdrawal and deletion contact/process. Local-recording consent
or a hidden reminder cannot authorize upload. Bundle import cannot configure an
upload destination. Never embed a confidential service credential in the desktop.

Withdrawal from a future online service must stop queued sends and define how
server/raw/derived copies are deleted. Already manually shared files are held by
their recipients; deleting local records does not delete those copies.

This document describes implemented product behavior, not certification of legal
compliance in every jurisdiction.
