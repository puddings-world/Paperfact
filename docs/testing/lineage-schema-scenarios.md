# Optional Lineage schema lifecycle

These isolated native-workspace tests use synthetic originals and simulated AI.
They do not use owner research, live login, cloud resources or paid model calls.

| Scenario in `test_lineage_schema_lifecycle.py` | Observable acceptance |
|---|---|
| Fresh native setup and saved reading | Synchronization metadata exists, but the report table stays absent; attaching the real native adapter and reading saved reports leaves the database unchanged. |
| First real report received | Actual source publication and journal synchronization create the report with the same scientific fingerprint. No model is invoked; no PDF byte ownership is granted before explicit transfer. Repeating sync leaves data unchanged. |
| Failure after scientific projection | A projector fails after the row was written. The exact database dump, absent report table and cursor are restored; retrying the same real events succeeds and repeated delivery is idempotent. |
| First explicit native analysis | An absent report table initializes through the actual loaded-owner workflow without a model call during preparation. Running analysis publishes a real report/outbox operation; repeating completion does not call the model again. |
| Cancellation or changed view after setup | Both cases cancel after actual DDL; the original database dump is restored and no model call or report store remains. |

The unchanged candidate-enrollment contract still requires an absent report table
when there is no canonical analysis. Existing native projector tests retain direct
DDL protection, explicit upgrade, read-only attach, foreign binding rejection and
caller-owned schema rollback. These are behavioral tests, not table removal after
initialization or weakened absence assertions.

The initial affected gate passed **21 cases in 145.67 s** (149.2 s overall).
The final schema/cancellation/enrollment/peer-download/editable-recovery gate
passed **38 cases in 349.57 s** (354.1 s overall). Both passed privacy/Ruff;
they overlap and are not a whole-application result.

Results and failures are recorded in the [continuation ledger](continuation-20261112.md).
Full release, hosted Linux operations and installed-device acceptance remain separate.

## Initialization boundaries

`lineage_projection.initialize_in(conn, *, include_report=True)` is internal
trusted setup in the caller transaction. Generic enrollment explicitly passes
`include_report=False`; explicit analysis uses the default. A Boolean choice and
an active transaction are required. It never commits the caller's work.

`lineage_projection.initialize_receive_in(conn, client, operation)` is the full
receive integration boundary, not a public arbitrary migration API. It validates
the typed operation, actual database path, native journal identity and local
research binding before initializing. Projection itself remains DDL-free.
