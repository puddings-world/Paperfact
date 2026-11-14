# Desktop Lineage: observable acceptance scenarios

Updated 2026-11-13. Generated PDFs, isolated workspaces, fake accounts/completions
and actual offscreen Qt widgets; no owner data, real login or paid model calls.

| Scope | Expanded cases | What a person/caller observes |
|---|---:|---|
| `test_lineage_desktop.py` | 13 | Opening/refreshing reads only; one generation saves and renders exact requested/returned metadata, with a real original window whose bytes match its source hash. Rapid clicks do not duplicate calls. Confirmation cancellation preserves saved research. Late results cannot fill another paper or destroy an active worker on close. Failed calls require explicit retry. Too many sources and missing login stop before generation. Searching retains selected papers. The actual menu reuses one window and preserves an unsent question. Changed account retains a proposal, and changing the exact saved row closes its old original window. An owner from another visible paper/workspace refuses before any worker or AI call. |
| `test_lineage_workflow.py` | 4 | Actual unbound publication/retry preserves exact sources, rejects an old retry after a later edit, retains a changed-view result, spends nothing when cancelled and single-flights concurrent activation. |
| `test_lineage_workflow_native.py` | 3 | Actual native source/scientific outboxes reach another workspace without using unbound receipts. Missing registration or a missing blob index refuses before AI and does not recreate storage or alter pending research. |

Additional origin/receiver cases:

| Scope | Expanded cases | Observable result |
|---|---:|---|
| `test_lineage_import_desktop.py` | 7 | All three actual imported source PDFs open with exact hashes and no database changes. Broken receipts/associations refuse both viewing and re-export without an alternate reader. Cancellation or a changed view cannot open a late original. |
| `test_lineage_native_desktop.py` | 1 | A genuine second native workspace receives the report, downloads verified originals and opens the selected peer PDF in the actual Qt view without new AI, data or outbox writes. |

The 50-case all-origin gate and 76-case package/bundle gate include overlapping
existing tests; exact dates/times and failed intermediate runs are in the ledger.

These 20 cases supplement the [17 native core scenarios](lineage-shared-scenarios.md).
They are not 37 separate product features or whole-application acceptance. Related
existing original-proof and research-menu regressions are included in focused gates;
their counts overlap prior receipts. Exact dated results are in the continuation
ledger. No old table-existence assertion was edited to make a gate green.

The GUI harness processes Qt events and releases the Python GIL between polls.
An initial QTest-based polling loop starved Python worker source checks; a thread
trace identified the live work. The timeout and content assertions were retained.
The fixture includes an explicitly unavailable fourth paper, not just three PDFs.
Visual capture loads the same pinned bundled fonts and Fusion style as startup;
a bare offscreen font environment is not evidence of the installed UI's appearance.

The screenshot in the reader guide is a rendered synthetic Qt example, not a
production-data or real-device capture. Mac/phone, signed installers, hosted HTTPS,
complete reviewed adoption and semantic/scientific evaluation remain unverified.
