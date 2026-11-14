# Explicit model appraisal of claims

Status: local v0.5 candidate, unreleased. This is a bounded second opinion on
selected source-pinned claims, not certification of a paper or a complete audit.

## Researcher flow

1. Open **Research tasks > Check saved evidence**; this deterministic read is free.
2. Choose **AI appraise claims**. Opening it loads only local saved reviews.
3. Inspect the exact original version and select 1-16 saved claims.
4. Use **Account and model** to choose the existing per-feature Audit route.
5. Press **Appraise selected claims** explicitly. This makes at most one model call.
6. Compare the proposed judgment, its reason and located original passages.

The next route is visible before starting. Each saved result separately records
the requested and provider-reported model; an unreported model stays unreported.
Changing the next route does not relabel an older result. No account or paid
fallback is selected implicitly. Normal local reading still needs no AI account.

## Boundaries

Retrieval ranks lexical matches in the sealed original, including CJK tokens;
it is not semantic search, OCR, an exhaustive search or evidence of absence.
At most six 100-word spans are supplied per claim, with 96 distinct spans overall.
The model proposes `supported`, `not_found` or `contradicted` and at most four
quoted spans. Every quotation is located independently within its supplied span.
An invented or ambiguous quotation remains unusable for navigation. Even a located
quotation does not establish semantic support. No numeric quality/confidence score
is produced, and no research text is rewritten.

This first slice accepts already source-pinned claims, not arbitrary compound
explanations, decks, list syntheses or lineage stories. Atomic assertion extraction,
complete adapters, source-bound fact sheets, cross-output comparison and an
independently human-checked evaluation corpus remain required audit work.

## Saved results and interruption

Completed valid results are derived local history outside the research database,
research bundles and sync. The platform cache is `LOCALAPPDATA/Paperfact/Cache`
on Windows, `~/Library/Caches/Paperfact` on macOS, and
`$XDG_CACHE_HOME/Paperfact` (or `~/.cache/Paperfact`) on Linux. `PAPERFACT_DATA`
does not redirect this private cache. Reading or constructing an archive creates
no folder. It stores source/input/model/result identities and proposed evidence,
never tokens, login credentials or account IDs.

Archives are scoped to the actual database identity, binding and paper lifetime.
Loading a current review matches exact selected inputs/source and revalidates its
quoted anchors against the sealed PDF. A changed paper, database, source or saved
input disables further work in the old view. A completed result from an in-flight
call is retained under its original snapshot; it is not applied to a new paper.

The archive is bounded to 128 results and 512 KiB per result. It never deletes old
reviews automatically. Full/read-only/unsupported storage leaves the completed
result visible with **Retry saving result**; this retry makes no model call.
Closing an unsaved result asks explicitly, defaulting to Cancel. Closed review
views release their sealed PDF captures after workers drain, while retaining the
completed result and saved history. Cache retention
controls and portable review history remain follow-on UX; this local cache is not
a backup or a research authority.

Retrieval, model waiting, quote verification and saving are separate visible
stages. There is no fabricated percentage or remaining-time estimate for the
model call. Repeated presses do not start another job. Stop/close waits for an
already-running call and retains completed work before allowing disposal.

## Verification scope

Synthetic provider responses and fixture PDFs exercise captured routes, budgets,
malformed responses, invented quotes, source/input changes, concurrent jobs,
private archive validation, bounded storage, source navigation, cancellation,
close-active, save-only retry and preservation of unsent notes/questions.
English/Traditional Chinese, light/dark and 440px native dialogs are rendered
without an account call. Physical Mac/phone acceptance and scientific precision
are separate gates. Exact focused/full counts belong to the integration ledger.

Escape follows the same close guard as the window close button. An active call
drains before the view closes; an unsaved result requires an explicit discard
decision with Cancel as the default. Accepted closure releases dialog modality
and the sealed PDF capture while retaining the small saved report. Native
keyboard regressions cover unbound and enrolled workspaces.


A saved item's explicit source_paper_id must match the sealed original's paper
identity before appraisal can capture an account/model route. Matching PDF bytes
from another paper are insufficient. Read-only deterministic audit shows the
source_owner_mismatch finding, and retrieval does not borrow focal passages for
that foreign owner. Opening an audit still makes no model call. This owner check
is separate from semantic support and complete multi-source corpus appraisal.
