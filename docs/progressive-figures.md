# Source-owned progressive figures

This is a contextual adaptation of the worker image decode in maintenance
`bb7122d`, preserving 0.5 loaded-source, owner, draft and worker-lifetime rules.
The original 30-figure control observed its first GUI heartbeat only after all
30 widgets existed. The actual load path now hands one image at a time to the
GUI and waits for that insertion's acknowledgement before decoding the next.

## Boundaries

- Main captures the actual loaded highlight view/owner, native PDF completion
  witness, original document object, reader/paper epoch and explicit cache roots.
  GUI admission observes native metadata and caller intent; it does not query
  research SQL, hash PDFs or parse images/PDFs.
- A worker verifies the real owner through the maintained read-only connection,
  hashes the exact original and returns an immutable, process-sealed byte proof.
  It does not create lifecycle/device/position identities or write research SQL.
  The ordinary 150 MiB PDF verification bound remains; claim/lineage's 32 MiB
  bound is not reused. Loaded A can remain selected while B is desired.
- Extraction parses those original bytes and writes only the captured cache
  root, checking source/cancellation before publication. Image metadata binds
  generated PNG bytes to their SHA; a different stable PNG cannot borrow the
  original's label. Worker decoding reads bounded immutable PNG bytes into
  `QImage`. `QPixmap` and widgets stay on the GUI thread.
- There is one running worker, one latest pending request, and at most one
  unacknowledged decoded image. A complete TOC appears before row insertion;
  selecting an unbuilt row prioritizes that target on the same worker. Captions
  remain complete/selectable. Missing/oversized image decoding keeps the caption
  and shows an unavailable-image placeholder.
- Repeated identical running requests coalesce. Paper, loaded PDF, workspace,
  owner/native identity or source changes revoke old deliveries and navigation.
  Close/restart/update admission waits for real thread and queued-delivery drain.
  Vetoes retain editors/observers; only accepted normal/stale close disposes the
  pane. Decoder/render native calls cannot be interrupted mid-call.

## Deliberate limits

Owned loads regenerate local figures rather than trust a preexisting mutable
cache manifest. This improves GUI responsiveness, **not cached-reopen CPU or
latency**. No image-reuse cache is introduced. Managed sources retain their
canonical document/options directory; unbound originals retain the legacy paper
alias destination so existing cached-only consumers can see completed images.
Default extraction/current-source checks and cached-only behavior remain in
place; cached-only never initiates extraction, and aliases never acquire managed
source authority. Partial source-owned derivative files can remain after a late
cancel; they never authorize activation, publication or a different source.

DB/WAL native revisions are delivery interference, not proof that a figure's
owner or original changed. Reading-time and saved-note writes keep images,
selectable captions and TOC widgets. Navigation is suspended until one stable
read-only check proves the same original owner/lifecycle/binding and exact intact
native source. The check uses the same worker lane; it neither rereads/reparses
the PDF nor re-extracts/decodes figures. Parent/binding retirement, native database
replacement, loaded view/source/epoch changes still revoke hard. This is a
figure-only dependency rule: it does not relax saved-note-dependent Audit jobs.

An extraction can refresh one queued decoded row's lease without decoding it
again. Its first ready publication may wait for one verified original-source
check; already-ready frames never emit another ready or reload the deep dive.
A check that cannot establish a stable lease latches a visible read-only/retry
state. Repeated notices coalesce; there is no retry-until-stable loop. The same
close/update/restart barriers cover extraction, checking and queued delivery.
A single Qt widget/text layout can still consume GUI time; slicing cannot preempt it. All displayed pixmaps
remain in their widgets, as before; the bounded pipeline limits worker/queued
images, not the final view's total graphics memory. PNG input/pixel budgets keep
pathological image decoding bounded and may leave caption-only entries.

`ready(paper_id)` still fires once after a complete successful load; jump remains
page/caption plus the actual loaded source hash. **The existing Main callback
`_figures_ready -> _load_dive` still performs synchronous work, including SQL/cache
HTML preparation.** This slice does not claim that the whole end-to-end figure
action is off-GUI. Private direct `_show` compatibility remains synchronous and
keeps its existing desired-source filtering. Actual Main loads use the owned
worker path; no source proof means no legacy fallback.

Acceptance uses disposable real SQLite/PDF/native Qt fixtures and simulated
held decoder failures, with no model/account/network calls or owner data.
No runtime/font assets are copied and no device benchmark or packaged-browser
acceptance is claimed. Full repository acceptance remains the parent gate.
