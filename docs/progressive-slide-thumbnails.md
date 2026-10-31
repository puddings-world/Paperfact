# Progressive slide thumbnails

The outline immediately creates fixed-size placeholders. One real thumbnail is
painted per queued GUI turn, with the selected page first. The list and canvas
remain usable while the rest arrive. No decorative animation or extra control is
introduced.

- A new deck, reorder, hidden/closed pane or destroyed widget revokes old work.
  Reopening prepares the current deck. A stale render cannot install into a new
  paper, row, palette, size or generation.
- Repeated pending requests share one draw per page. A nested event pump cannot
  start another draw before the active frame finishes. Drawing failure leaves a
  sanitized placeholder; clicking the page retries. Other pages continue.
- The existing SlideCanvas performs Qt drawing on the GUI thread. Its guarded
  figure-byte reader, source ownership and recovery behavior remain unchanged.
  This does not remove existing per-image decode/source-read costs or promise a
  maximum duration for one complex slide.
- This first slice has **no rendered-image cache**. Each requested page is drawn
  from the current deck and existing figure-byte path. Mutable legacy assets are
  not trusted by filename, metadata or a path-only cache key. Changed asset bytes
  are read again on an explicit redraw; there is no new filesystem watcher.
- Placeholder reuse is local decoration only, never asset availability or research
  authority. No new PDF/figure hash, SQL/discovery loop or background model call
  is added to the queue.
- Rendering does not save, publish, restore, regenerate, create undo entries or
  change source selection. Existing observed save/conflict, undo and recovery
  paths remain responsible for edits.

Fixture coverage uses actual Qt queued drawing/icons and stored content/outbox,
plus controlled failure and reentrant render cases. Native desktop responsiveness
and a single slide's physical render cost still need platform acceptance. A full
project check remains required before committing or releasing.
