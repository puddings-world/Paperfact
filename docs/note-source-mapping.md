# Explicit source and position mapping for recovered notes

Local `0.5.0.dev` candidate, 2026-11-01, unreleased. Native PDF/passage selection,
clearing invalid positions, durable private source pairs, restart verification and
repeated adoption are implemented with selected behavior evidence. This does not
complete all note recovery, transport, synchronization or release requirements.
See the [executed action guide](testing/note-source-mapping-scenarios.md) and
[full release scope](roadmap-0.5.0.md).

## Researcher flow

Continue a preserved draft, explicitly choose a receiver note, then use
**Confirm original and position…**. Choose a native PDF and select original words,
or make a plain manual note without a source association. A fitted PDF preview and
the exact selected passage are visible. Cancelling leaves canonical research and
the current reader unchanged. Private edits save before verification; final Apply
confirmation names the receiver, source and passage. No AI account/model call is
needed to store this human decision.

## Implemented boundaries

- A closed v2 private note observation separates historical `recorded_source` from
  the reviewed association. `mapped` and `plain` are explicit local decisions;
  `retained` carries an immutable archived decision into a new receiver without
  reusing the old receiver's file authority. Unknown attribution stays unknown
  through repeated backup/adoption.
- Native selections mint process-only inspections for one exact note base. Historical
  paths are never followed. PDF bytes, typed note/parent identity, file versions and
  active review lifetime are rechecked. Canonical note identity/creation stay fixed.
- Reviewed anchors preserve bounded original text and the actual `level_words` /
  PyMuPDF extractor version. Revalidation compares the actual selected words. Generic
  highlight/chat anchors remain closed and unchanged; legacy note positions remain
  readable without falsely claiming their old word order was verified.
- Private PDF/receipt pairs publish atomically by directory rename, then private
  drafts save with CAS. A failed/cancelled later save may leave a complete archival
  private pair, never a canonical original, note or sync job. Backup includes the
  declared bytes; detached records cannot grant new active ownership.
- Fresh verification after restart stages exact bytes, checking the current native
  store, its present binding and completeness as well as private receipt/source
  versions. Canonical source ownership, rich note, outbox and decision receipt share
  one final transaction; failed publication rolls back and identical retry deduplicates.
- Shared source verification still refuses known retired/deleted originals. A source
  choice does not bypass an explicit restoration boundary or substitute current B.
- UI inspection/selection runs in an owned background worker. Duplicate activation
  coalesces; close cancels and drains before returning without a late choice. Qt
  UTF-16 selections map to raw indexed PDF words, including surrogate pairs/gaps.
- Existing audit readers accept the new note metadata without treating human prose
  as a quotation or certifying semantic support. Pending private saves finish before
  opening an original so the app's own autosave cannot stale that initial proof.
- Unrepresentable active presentation closure produces the existing actionable
  recovery error and cannot publish a partial backup or overwrite an earlier file.

## Remaining acceptance and integration

- Offer bounded current/recorded source references and expose them through local
  operations/CLI/MCP; a native file picker is not arbitrary external filesystem access.
- UI passage selection currently covers one page. Backend cross-page selection is
  bounded, but a usable cross-page selector and further legacy-format guidance remain.
- Expand cancelled-after-publication, native parent/store replacement and larger
  nested/size/compatibility variations. Existing selected passes cover only their
  named scenarios, not every permutation in the original contract.
- Complete other typed recovery/history/writer formats, current-source navigation,
  grounded lineage/durable audits, canonical integration and matching full checks.
- Production identity/pairing, service operations/storage/retention/recovery, packaged
  Windows/Apple Silicon Mac/phone offline round trips and expert research evaluation
  remain separate release gates. No independent Claude session is currently assigned.

Reusable candidates: distinguish historical absence from a new human association;
do not convert lifecycle shutdown into a recoverable content error; finish owned
private writes before capturing read-only proofs. Selected evidence is local, not
a new universal skill or permission to publish, upload telemetry or access accounts.
