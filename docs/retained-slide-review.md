# Retained slide review

The isolated 0.5 integration now exposes an explicit path from a retained managed
slide candidate to an editable saved revision. This is not yet release acceptance
or complete draft/history portability.

## User flow

Open retained-work review, select retained slides, choose **Verify retained
slides**, compare the retained/current/original summaries, then confirm **Apply
reviewed slides**. Cancel and Keep current publish no new deck operation. The
comparison is plain text with slide titles, takeaways, bullets, speaker notes and
source labels; it is not an editable transport manifest. Large previews state
explicitly when abbreviated; the stored deck is unchanged.

Verification and application never call a model. The candidate remains immutable.
Application preserves its payload, selected source identity, layout, notes and
image bytes instead of rerunning generation or relabelling it with a current PDF.
Retargeting to another paper is not offered by this path.

## Transaction and retry boundary

Preparation validates body, PNG and evidence bytes from registered immutable
storage. It captures the current native database/binding, projected paper and
local lifecycle, deck/input observation, storage identities and exact file
versions. It does not add an outbox operation.

Apply materializes the planned immutable revision before the write lock. Inside
one write transaction it compares the displayed state again, verifies the planned
shared graph operation, writes the outbox/revision, activates the verified files
and records the idempotent decision receipt. Failure rolls back those database
changes. A materialized cache directory can remain after failure; it is not an
active deck and is reused safely on retry. Same-session repeated calls serialize;
receipts prevent a successful retry from rewinding later manual edits.

Changed inputs/current deck, replaced files/database/storage, changed parent
lifecycle, a closed owner or a changed request fail without overwriting research.
A refreshed review requires a separate confirmation.

## Evidence and limits

- A new test first failed because the explicit prepare API was absent.
- The managed storage main path passed after implementation. A subsequent native
  revision comparison failure exposed nested Windows tuples being serialized as
  lists; normalized local version observations fixed it without relaxing checks.
- Sixteen backend cases passed in 57.69 seconds, zero skips or source drift,
  with external calls blocked. Three actual offscreen Qt cases passed in 13.97
  seconds, zero skips or source drift. These are overlapping development evidence,
  not a whole-application pass.
- One newly added notes fixture initially used the wrong timestamp column; it was
  corrected to the existing created_at schema with assertions unchanged.

The coherent seven-file gate passed **105 cases, zero skipped, 252.51 seconds**
with 1,240 frozen inputs, no source drift and no unexpected external calls.
Its XML breakdown is 19 retained-deck backend, 3 retained-deck Qt, 4 plain-text
preview, 16 existing review, 15 existing draft, 10 existing dialog and 38 existing
managed file cases. The new historical-A/current-B and mid-materialization
change/closure cases are included.

After this gate, three new capture-enabled/storage-identity cases passed in
12.31 seconds, zero skips or source drift, with product source unchanged. Do not
add overlapping earlier gates together. Existing 505 test files remain unchanged.
ResearchReview preserves 28 other named methods and ReviewDialog preserves 28
other named methods. Current full-check and physical-device acceptance remain
unproven. See tests/test_research_file_review.py,
tests/test_research_file_review_ui.py and tests/test_review_deck_text.py.

This path currently supports staged managed deck candidates. Raw unpinned deck
rows, original-source files, detached recovery reattachment, complete draft/history
sharing and physical-device acceptance remain separate unfinished work. It does
not establish source-text semantic accuracy, live Google export or vendor login.

## Explicit restoration follow-on

A genuinely deleted deck initially failed at the maintained restore=True guard.
The prepared review now distinguishes replacement from restoration, labels the
restoration explicitly in English/Traditional Chinese and requires a separate
confirmation. A successful restore uses the shared graph operation to create a
fresh file incarnation; the retained candidate and historical revisions survive.
A stale displayed deletion or changed parent still refuses application.

The current backend file passed **23 cases, zero skipped, 106.48 seconds**.
The actual Qt file then passed **5 cases, zero skipped, 10.08 seconds**, including
both-language restoration confirmation/cancel and ordinary apply/late/close flows.
Both gates froze 1,240 inputs without drift or unexpected external calls. They
overlap the earlier105 gate; they are not additional whole-application totals.
Style-only cleanup after the UI gate preserves both module and test ASTs.
The latest integrated tree still needs its full check before commit or release.
