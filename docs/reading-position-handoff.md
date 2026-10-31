# Source-bound reading position

Status: required v0.5 handoff, not implemented by the recorded-activity slice.
Recent note/reading-state activity is useful but is neither last-opened history
nor an observed PDF viewport. Do not rename it to imply either.

## First implementation boundary

- Record a one-based page for an exact paper lifetime and PDF SHA-256. A page
  number without the original identity must remain an unverified legacy hint.
- Separate `observed` positions from `entered` positions. Native observations
  come only from an actually loaded verified reader; a manual entry is labelled.
- Offer an explicit resume action. Receiving a position never changes the active
  paper, scroll, selection, draft or current source. Never auto-jump after an
  asynchronous PDF load completes.
- A different/missing original keeps the position visible but unavailable for
  direct resume; offer the existing exact-original/offline-preparation flow.
- Backward movement is legitimate rereading. Do not resolve competing positions
  with maximum page or an untrusted device clock.

## Proposed stored operation

Use a closed paper-scoped `research_content` feature `reading_position`, keyed by
the exact source hash. Data contains `{page, recorded_at, method}`; `method` is
`observed` or `entered`, page is a bounded positive integer, and recorded_at is
an aware timestamp. Source hash is required and must equal the key. The exact
paper parent/lifetime remains mandatory. This is a proposal until validators,
projections, migration and independent mobile verdicts are implemented.

Capture current owner, binding, reader epoch and loaded original before admitting
a debounced background save. Confirm the page against the verified PDF's actual
page count off-thread. Retain the source through the maintained source-ownership
boundary; extend that registry for the real position owner rather than inventing
a claim/generation receipt. SQL/outbox and position ownership must commit together;
file preparation never authorizes a later save into a replaced workspace.

Coalesce rapid viewport events before writing, retaining the latest observed
position per exact reader epoch. Distinguish capture from sync acceptance. A
position received from another device must not immediately echo as a new local
observation merely because its suggestion was rendered. Preserve both sides of
actual conflicts and expose a deliberate resolution using the existing CAS path.

## Actual reader interfaces

Desktop `pdfpane` has `current_page()` for Qt PDF and the image fallback. Its
native page navigator/scroll path can provide a genuine observation after
load; do not infer a page from opening a tab or a source hash alone. Cover both
backends and verify unloaded/failed/replaced originals never publish positions.

Mobile currently embeds a native PDF `<object>`; its internal page/scroll is
not available to this app. Choose an explicit entered-page UI for the first
honest slice, or add a separately tested same-origin PDF renderer with actual page
events. Browser-native viewport reporting must never be simulated. A future
renderer must preserve verified bytes, bounded page rendering, cancellation,
accessibility, offline assets and source changes; physical iOS/Android behavior
remains a separate acceptance gate.

## Transport and preservation

Desktop, supported local operations and mobile should use the same closed feature,
with independent validators. Older receivers must reject required capabilities
before cursor/state persistence. Add source-aware snapshot/bundle/backup/recovery
coverage, including old source A while current source B remains active. Never
lose positions during initial enrollment or recreate old device/job authority.
A browser renderer or a manual page entry is not permission to run AI or download
another paper automatically.

## Required acceptance

- Two desktops and mobile converge after offline/restart/retry without duplicate
  operations; genuine competing positions remain recoverable.
- Source A/B, missing bytes, wrong hash, invalid page, deleted/recreated parent,
  switched workspace/account, close-active and rapid scroll/save cases are safe.
- Explicit resume checks the actual currently loaded original and captured view
  again; new edits, a newer source or a changed selection prevent late navigation.
- Existing read state, annotation anchors, list custom order and ordinary paper
  opening retain their current behavior. No synthetic opened-at timestamp is
  produced by polling, rendering or accepted-history replay.
- Use fixture workspaces and simulated providers. Run the complete frozen gate
  before committing; record packaged and physical-device observations separately.
