# Explicit fact extraction seam

Status: bounded local v0.5 extraction with a modeless desktop comparison view.
No CLI activation, persisted fact sheets, sync/recovery or completed A3 scientific
evaluation is claimed.

## Explicit operation

`ExtractionJob.prepare(actual_capture, selected, connections=..., max_calls=1,
max_tokens=4000, max_prompt_bytes=96000, route_current=...)` captures the existing
Audit task settings once inside the existing captured connection scope.
If connections are omitted, the existing facade captures them once at this
explicit preparation operation. The job copies that connection snapshot and
retains its frozen Settings. A missing/unsupported route or invalid bound fails;
there is no new account discovery, login, vendor adapter or global fallback.
Changing global defaults later does not change this job's account/model.

Selected IDs must identify 1–8 actual outputs in the sealed AuditCapture. Each
selected text is at most8,000 characters, and selected item JSON is at most32KiB.
The complete prompt, including system instructions, is at most96,000 UTF-8 bytes.
Caller prompt budgets can be smaller, never larger. Token budget is 1–8,000,
must fit the captured route's configured token limit, and is supplied explicitly
to the facade. Actual output-limit enforcement depends on the provider; current
CLI adapters ignore this setting. The facade call budget is exactly1. These are
request bounds, not token-price estimates or promises about service availability.

`job.run(cancelled=..., current=..., progress=...)` uses the existing bounded
lexical local source retriever: at most six100-word/2,400-character spans per
selected output, within its existing96-distinct-span limit. A job with eight
outputs therefore supplies at most48 snippets. PDF parsing remains bounded by
the existing sealed source verifier. Whole-document oversized prompts, global
paths or additional retrieval/model calls are not fallback options. Over-budget
input fails instead of truncating selected saved output or silently dropping facts.
No snippet ranking is a scientific quality or confidence score.

Prepared selection is a deeply immutable tuple of validated string IDs; caller
list changes cannot alter it. Captured scalar budgets and public job fields are
frozen through the actual call. Private attempted/result/lock state is separate,
and connection data is privately copied rather than shared with the caller.

A nonblocking instance lock owns the operation through verification/discard.
Repeated/concurrent runs of the same job cannot duplicate its completion.
At most one `llm.complete_result(..., task="audit", cfg=captured_settings)` call
is made. After an attempted failed/malformed call, a new explicit job is required;
there is no automatic extraction retry. This does not change existing provider
transport policies inside the shared facade or assert one HTTP transmission.
Separate explicitly created jobs are separate requests; no durable request journal
or cross-process deduplication is introduced by this three-file slice.

## Closed model proposal and deterministic mapping

The response has exactly `study_type, facts, empty_reason`. Study type uses the
frozen core's applicable empirical/theoretical/qualitative/review/mixed/unknown
choices. A valid empty facts list requires a nonempty reason of at most500 chars.
Missing/null/scalar facts, missing reason, duplicate JSON keys, nonfinite JSON,
unknown headers and oversized responses are errors. For nonempty facts the
empty_reason must be null. Response JSON is bounded to128,000 UTF-8 bytes.

Each fact has exactly:
`id, category, statement, origin, scope, value, output, evidence`.
The frozen core validates all category/origin/scope/value, size, count, passage,
rounding and absent-versus-zero rules unchanged. There are no fact quotas, ML-only
design assumptions, universal quality scores or model-generated source authority.

For an original-source fact, output is null. Its statement and classification
remain model proposals. For a saved-output fact, output is exactly
`{item_id, excerpt}`. The item must be selected, the excerpt must occur exactly
once in its complete captured text, and statement must equal that exact excerpt.
Offsets are calculated locally, without text normalization; model offsets are
forbidden. Missing or ambiguous excerpts reject the entire batch.

Evidence entries are exactly `{item_id, span_id, quote}`, at most four per fact.
Each span must belong to that selected item's supplied retrieval. The exact quote
must occur in the supplied span and resolve uniquely inside its actual original
word range. The existing source index maps it to a page/word anchor. The frozen
fact core then verifies that exact quote/locator against the captured owned PDF.
Invented, outside-span, ambiguous, malformed or mismatched evidence causes an
explicit whole-batch error; none is silently discarded or attached to today's PDF.
Multiple original occurrences are usable only through a uniquely mapped supplied
span, not by guessing a first global occurrence.

The model cannot supply/replace source, PDF digest, workspace, original owner or
the saved-output corpus. Source identity comes only from the actual AuditCapture.
Versionless/other-version saved output bindings remain unknown/different_original,
even if a quotation from the captured PDF is located. The model's stated/inferred,
not_reported/unknown classifications, numeric meaning and scope remain proposed.
A null/not-reported value is not zero, and a located quote is not semantic support.
The extraction can propose facts about bounded input only; no fact does not prove
that the complete paper omits it.

## Result, guards and boundaries

After strict mapping, the entire batch passes unchanged frozen
`audit_facts.prepare` and `audit_consistency.compare`. A result retains its
process-local source-bound FactSheet and defensive copies of consistency/execution
metadata. Execution metadata is separate from fact proposals: request ID, selected
IDs/hash, captured backend/requested model, token bound and actual
`Completion.reported_model`. A requested/default compatibility model is never
labelled as reported. Missing returned identity stays null. Credentials, account
IDs, endpoint URLs and native paths do not enter the execution metadata.

Cancellation, caller context, captured route predicate and actual capture/source
are guarded before/after the completion and before result delivery. A completed
stale/cancelled response becomes no accepted result and triggers no write or retry.
Cached run reads recheck currentness, and result.current() can reject later route
or context changes. Result properties make no model calls. Guard predicates must
be safe on the worker; future consumers must supply real captured epochs/lifetimes,
use metadata-only GUI delivery checks and retain busy ownership until actual drain.
The desktop view supplies those lifetime hooks without invoking a model on open.
Its optional `reading_owner` permits a bounded read-only recapture while work is
pending, with unchanged original ownership, source and complete captured research
inputs. The default remains strict. See [reading continuity](audit-reading-continuity.md).

All source/SQL/hash/PDF and consistency work belongs on a worker. No raw completion
is persisted, research is rewritten, old validator is relaxed or provenance is
minted. Existing facade bookkeeping remains its own contract; tests simulate
complete_result and use isolated synthetic workspaces only. Source text is never
added to telemetry by this module.

The focused suite checks captured one-call behavior, current source/rows, route
and token bounds, malformed/empty batches, exact excerpt/quote mapping, cancellation
and held stale completions. Frozen core72 and unchanged audit/appraisal controls
remain intact. This is local contract evidence, not human scholarly evaluation,
precision/recall or a full release check.
