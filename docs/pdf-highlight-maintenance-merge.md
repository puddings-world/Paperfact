# Saved highlight display during an immediate manual edit

The feature's ten original highlight cases, fixture and outcome assertions are
retained. The incoming maintenance scenario uses the existing owned
`ReaderPreparation` lane, a real resolved original, completed native PDF load and
observed `HighlightView`. It does not introduce the master's generic `prepare`
worker into the source-bound reader.

Initial native original arrival may request a marks display target on that lane.
The worker reads the existing saved-input snapshot, verifies an actual highlight
view against the captured original, and extracts words for its marked pages with
the existing `pdfselect.words_in`. The GUI primes those words and installs the
overlay only while the captured paper/workspace/native source and exact edit-view
identity still match. The existing semantic, database-file and delivery guards
remain in force. Successful publication installs the verified fresh edit view.

An immediate explicit add/remove keeps the existing transaction and immediate
refresh. That refresh replaces the edit-view identity, so the older queued display
cannot erase a new mark or resurrect a removed one. Overlapping saved chat/dive
and initial-mark requests use the same bounded running/latest-pending owner.
Repeated identical requests coalesce. A failed display retains the prior overlay;
an explicit retry reads it again. Source/paper/workspace changes and close cancel
or reject late delivery, retaining ownership through the actual native join.

The initial synchronous `HighlightView` authority read is deliberately retained;
this is not a claim that the whole PDF/SQL initial-load path is asynchronous.
Legacy readers lacking a real resolved original retain their existing synchronous
compatibility path. Word priming moves the saved overlay's page-word extraction
off the GUI; it does not redesign interactive selection on other pages. Nothing
adds AI calls, inferred source ownership, new receipts, note writers or sync kinds.

The new coalescing control observes one worker and one page-word extraction, plus
two public saved reads: initial capture and mandatory `saved.current` semantic
revalidation. Each saved read retains its own internal double-read consistency
check. The original one-read-after-drain expectation was incorrect; its RED and
the source-free forwarding trace remain as evidence, and the corrected expectation
was explicitly approved. Before release, exactly one saved read is still required.

Checks use isolated unbound/enrolled fixture databases, real native Qt/PDF controls,
held saved-input workers and fake external boundaries. The original feature tests
remain unchanged, including draft, manual/AI hidden-state, materials, retry and
collapse outcomes. The unresolved unrelated deep-analysis test is preserved and
excluded from the finite affected gate. The parent owns merged-tree full checks;
no full-suite, live account, hardware or owner-data acceptance is claimed here.
