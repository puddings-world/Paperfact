# Native Lineage synchronization: what the tests do

Updated 2026-11-13. Development only; not installed-device or release acceptance.
The scenarios below use temporary databases, generated PDFs, simulated model
responses and fake local credentials. They never use the owner's research,
cloud service, actual login or paid model quota.

## User-observable scenarios

| Test module | Expanded cases | Actions and observable acceptance |
|---|---:|---|
| `test_lineage_live_journey.py` | 7 | Publish a real analysis once; retry before/after synchronization; a peer receives the full report before downloading PDFs, then opens exact original bytes. Back up/restore the actual report and candidate without reactivating device identities. Fail at the second source, a late paper change, or cancellation: all action writes roll back while earlier caller work remains. Two concurrent retries create one scientific action. An old retry cannot overwrite a later generated edit. |
| `test_lineage_live_conflicts.py` | 6 | Two peers edit the same report. Choose incoming or canonical content and retry the decision without duplication. Source deletion invalidates the displayed review and can retire obsolete science. Explicit report restoration creates a new report lifetime; same-hash source restoration cannot revive old evidence. Missing pins are rejected and an unknown source lifetime produces a retained conflict. |
| `test_lineage_live_http.py` | 1 | Use a real loopback HTTP server and native transport to upload authenticated original files before the scientific child. A peer receives the report; the existing mobile projection consumes genuine accepted service events. Neither receiving metadata nor mobile rendering activates PDF bytes or calls AI. |
| `test_lineage_live_capacity.py` | 3 | Reject an extra corpus locally without changing saved research/outboxes and refuse analysis observation before a model call. Permit editing an existing corpus at capacity. Two devices compete for the last slot: retain the losing proposal as a conflict, advance the receive cursor, retry deferred materialization on an empty page, then resolve after an explicit retirement frees capacity. |

The 17 expanded cases are not 17 separate product features. Parameterized choices
and failure locations exercise distinct outcomes of the same action. Capacity
fixtures reduce the constant to one/two slots; production remains 64 per focal
paper. No test deletes/skips another case to obtain a passing count.

## Run and interpret

```sh
python scripts/check.py --profile focused --python tests/test_lineage_live_journey.py tests/test_lineage_live_conflicts.py tests/test_lineage_live_http.py tests/test_lineage_live_capacity.py
```

Use the project's virtual-environment Python. Success says `Focused checks passed`;
it explicitly does not certify the whole application. `build/check-latest.json`
is the latest invocation, not a cumulative report; retain dated logs for earlier
receipts. Pytest percentages count selected cases, not elapsed time or percentage
of v0.5 completion. Current dated receipts and failures are in the
[continuation ledger](continuation-20261112.md).

The broader Lineage suite covers source capture, candidate retention, native
projections, packages, recovery, visibility and mobile wire contracts. It also
currently contains an older enrollment assertion requiring the absence of an
empty Lineage table; that expectation is under owner review, not silently
removed. A failed run remains failed regardless of other passing cases.

## Limits and next gates

These tests do not validate scientific reasoning, public analysis UI/task wiring,
reviewed stored-result/package adoption, cloud hardening, network behavior on a
physical Mac/phone or final installers. Source bytes are verified separately from
scientific semantics. A new coherent full check is required before commit/release;
hosted and installed-device acceptance must record actual versions and checksums.
