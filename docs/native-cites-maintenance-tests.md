# Native citation maintenance preservation

Six maintenance regression names are retained in a new native test module:

- `test_every_work_is_on_the_page_once_and_flipping_never_reloads`: actual card
  counts, one displayed title, exact one list/map read and unchanged cards on flips.
- `test_the_tab_never_opens_a_window_of_its_own`: actual Qt Show events admit only
  the fixture pane, including initial creation and native view/side switches.
- `test_reordering_reorders_only_that_side`: actual reference order 1/2/3 and the
  unchanged later-card sequence, activated through the native order control.
- `test_a_slide_source_finds_its_card_on_the_other_side`: unfinished-side lookup
  makes the exact target card visible inside the viewport.
- `test_a_card_opens_lifts_or_adds_its_work`: native buttons deliver exact IDs and
  command arguments, show success feedback, deduplicate and reject a stale callback.
- `test_the_sides_and_orders_switch_from_their_links`: native side/order buttons
  show later works and place the most-cited work first; no HTML API is introduced.

The initial production change adopts the order controls and side holders into
their layouts before setting visibility. Typed editors, writers and the existing
card/map callback admission functions are unchanged. Existing tests, including
unresolved merge files, remain byte-identical.
The isolated gate selects owned Python paths and genuinely native tests explicitly;
it does not import conflicted/HTML tests or claim a resolved-tree full check.

The first affected selection was **45 passed / 1 failed**. The source-navigation
case exposed that the real delayed `ensureWidgetVisible` ran while the card was
only 8 pixels high and the scroll range is zero. After queued layout, the same
card is below the viewport (top 1022, viewport height 700) without a second native
scroll. The original red log and geometry receipt are retained. The two
adoption-order changes pass the actual Show-event
regression, which first failed with two extra top-level `QWidget` Show events.

The authorized follow-on retains a weak target and the exact admitted projection,
list, generation, view and side. A pane-owned, coalesced zero-delay callback waits
for existing idle construction and stable actual geometry before native reveal.
Layout/resize and completion wake it; no longer delay constant, manual scroll
fallback or event-loop pumping is introduced. Paper/list lifetime changes reject
it; view/side/order/team switches, close, wheel, navigation keys and scrollbar
interaction cancel it. A completed reveal clears the intent, so later layout
cannot take the reader back to the old card. Native Qt fixture cases retain the
viewport outcome after real completion and exercise these cancellation paths.

These are isolated offscreen native Qt checks with synthetic local citation data
and spies at process/network boundaries. They do not certify a resolved merge,
the whole suite, hardware touch input, or a live external lookup.

The conflicted lineage-team test is outside this candidate. Its semantic union
should retain the feature's exact filtered title sets, author explanation, count,
and restored 40-card outcome; additionally assert the filtered team notice is
visible, Reference 7 is displayed, and Reference 8 is absent. These are native
content assertions, not a reason to introduce private HTML helpers.
