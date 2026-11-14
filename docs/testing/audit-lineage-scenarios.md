# Saved Lineage evidence audit scenarios

Development integration, 2026-11-13. Synthetic three-paper originals and simulated
model output establish real saved content before auditing; audits make no AI calls.

| Behavior | Evidence |
|---|---|
| Each statement and quotation keeps its own original version. Only quotations in the loaded PDF are located; others remain explicit source mismatches. | Real canonical publication -> AuditCapture -> same shared `analysis.audit` result; source database unchanged. |
| Separate corpora can contain identical statement IDs. | Two validated canonical corpora produce six distinct audit item IDs. |
| Invalid saved content cannot produce a partial clean report. | Mismatched stored input hash rejects capture without repairing/mutating it. |
| Removing saved Lineage invalidates the old report's capture. | Old report remains data; rerun refuses stale inputs and fresh capture sees no current statements. |
| Ordinary reading does not create optional Lineage storage. | Absent optional table remains absent after an empty read-only audit. |
| Desktop cards explain scope in English and Traditional Chinese. | Real Qt windows show all three statements, source mismatch/scope text, and navigation only for located quotations in the loaded original. |

Initial direct evidence: **5 backend cases passed in 17.03 s**, **2 real Qt cases
passed in 8.37 s**. The first Qt harness incorrectly waited only for idle before
the scheduled initial refresh began (1 failed in 3.64 s); it now waits for actual
report delivery. Production timing and old tests were not changed for that fix.

This is single-loaded-original deterministic checking. It does not verify
semantic support, automatically open/download the other originals, audit archived
versions, or complete the multi-paper analysis audit. Shared cancellation, stale
source, draft preservation and CLI/MCP behavior are covered by the adjacent
existing audit tests; see the continuation ledger for the maintained gate.


Maintained affected gate: **91 passed in 134.66 s**, 138.3 s overall,
privacy/Ruff passing, zero failures/errors/skips. Selection includes these
seven new cases plus the existing saved-input, SQL-output, linked-source,
Qt cancellation/source-staleness and actual JSON CLI/official MCP tests.
These overlapping scopes are not a release total. The only subsequent source
rewrite restored the edited files' original CRLF bytes; parsed source content
and behavior are unchanged. Full application/installed-device validation remains
required before release.
