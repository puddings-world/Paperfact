# Historical original inspection scenarios

These are isolated generated-paper tests of the actual history reader and Qt
PDF windows. Reading history must not activate an old analysis, change the primary
PDF, grant a source, invoke AI or add a synchronization operation.

| Scenario | What the test does | Required visible/stored outcome |
|---|---|---|
| Generated original | Remove a real published report, then open each selected original | Each PDF hash matches the saved report; canonical analysis stays absent; the existing current-row reader still refuses the removed report. |
| Imported original | Import a real research package, remove its report and open its originals | Uses the receiver's actual import receipt and original grants without reconstructing sender credentials. |
| Peer-received original | Publish, synchronize, transfer PDFs to another workspace, remove the report and inspect it there | Uses actual peer-owned bytes and original source lifetimes; no extra outbox operation is created. |
| Newer report in the same slot | Import a newer source/report version while retaining the old version | Viewing the old version reads the old hash, preserves the newer canonical row and never substitutes today's primary PDF. |
| Same bytes under a new source lifetime | Retire a native source, optionally recreate it with the identical payload | Old proof invalidates and a fresh old-history read refuses, even when cached bytes still exist. |
| Lost permission or original | Remove a source association, recreate a selected paper, corrupt bytes or remove actual publication provenance | Cached proof no longer delivers; historical text remains data and is not a source grant. |
| Forged/different view | Replace proof bytes or deliver with a different loaded owner | Reject rather than treating JSON or an equal-looking owner as the verified native proof. |
| Cancel/wrong source | Cancel before admission or request a source outside the selected report | No file fallback, analysis mutation, model call or source grant. |
| Actual Qt PDF | Open the historical source at its quotation page | QPdfDocument loads real PDF bytes; the primary reader remains unchanged; closing releases the document/buffer/proof. |
| Delayed UI delivery | Hold a source worker, then cancel, switch paper, close, change selection or change only the selected origin | No PDF window appears in the wrong view; admitted workers drain safely. |
| Cancel after the worker finishes | Hold GUI signal delivery until the real source worker has completed, then stop before delivery | Both current and historical source windows remain closed and status says stopped; this failed before the delivery guard was fixed. |
| Permission lost while open | Remove a source grant after opening its historical PDF | Metadata guard closes the source window and releases its bytes. |
| Missing file then retry | Remove the local exact PDF, attempt open, repair the fixture cache, explicitly retry | First attempt reports unavailable; retry verifies fresh bytes without AI or restoration. |

Source coverage:

- `tests/test_lineage_history_originals.py`: genuine generated/import/native
  proof checks, invalidation, malformed provenance and previous-version reads.
- `tests/test_lineage_history_desktop.py`: generated-history Qt windows,
  cancellation/delivery guards, permission loss and explicit file retry.
- `tests/test_lineage_history_origin_desktop.py`: actual imported and peer-native
  Qt windows, each opening all three selected PDFs.
- Existing current-row original-reader tests remain independent. The temporary
  lifecycle assertion that historical source buttons were always disabled was
  changed only for this explicit feature transition; new independent proof tests
  guard the enabled path. Current-source permissions were not relaxed.

The [continuation ledger](continuation-20261112.md) records exact commands,
intermediate failures and terminal results. Test counts include parameterized
variants and overlap broader gates; they are not a count of product features.
Installed Mac/phone, hosted HTTPS, complete detached editable adoption and the
final coherent full check remain separate acceptance gates. No real owner
research/account/model or paid service is used by these fixtures.


Verification: the 130-case source/Qt/current-reader gate passed in 492.61 s.
A later targeted repro exposed queued cancellation (one failure in 4.66 s);
its delivery fix then passed the final affected 44-case Qt/origin gate in 223.56 s.
Both gates passed privacy/Ruff and overlap. The two extra imported/native Qt
journeys passed separately in 16.31 s before being included in the final gate.
This is incremental local evidence, not a full application or installed-device pass.
