# GCS backup retrieval scenarios

These tests use synthetic reference-authority state and simulated private cloud
responses. No account, ADC discovery, socket, cloud upload or owner research.

| Test file / case | Observable proof |
|---|---|
| `test_sync_gcs_fetch.py`: exact retrieval | Original manifest/database/PDF bytes match; closure verifies; no restore, remote mutation or borrowed-client close |
| Existing destination | Repeated invocation refuses overwrites and leaves a valid backup unchanged |
| Corruption, changed generation, cancellation, missing object, privacy change | No completed output; retry to a new directory succeeds |
| Traversal, duplicates, excessive bytes, missing database, extra fields | Refused before local output or payload download |
| Consistent hash with invalid SQLite | Hash is insufficient: authority verifier refuses and completion remains absent |
| Server ignores range | Sink bounds the actual response, not just claimed metadata |
| Invalid digest/budget/emulator | Admission fails before output or credentials |
| CLI help/error | Offline help and bounded next-step text; no raw cloud response |
| Early/final cancellation | Public verifier cannot accept partial output |
| Owned client failure | Client closes; private server response is not exposed |
| `test_sync_gcs_fetch_wire.py`: small and multi-range | Real Google SDK upload/download request code over in-memory HTTP; exact generation/range; recovered events/conflict/PDF; old credential rejected |

The new suite contains 22 parameterized cases (20 simulated-object cases and two
real-SDK transport cases). This is behavioral evidence, not production cloud or
installed-device acceptance. The initial wire fixture used `workspace` instead of
the real fixture's `workspace-a`; corrected the fixture, retaining restore checks.
An initial adjacent-suite command referenced a nonexistent dependency-test filename
and collected no tests; the corrected invocation has its own terminal receipt.

Pending gates: coherent full application suite, private bucket/IAM/network,
Linux process/disk/TLS operations, real cloud restore, retention/scheduling and
installed Windows/Apple Silicon/mobile recovery. Tests do not assert an RPO/RTO,
bandwidth/cost estimate or cross-process partial-download resume.

Final adjacent gate: `build/gcs-fetch-integrated-final-20261114.log`, **134 passed
in 77.35s**, including the 22 new retrieval cases and 112 adjacent checks. The
real-SDK-only receipt is `build/gcs-fetch-wire-final-20261114.log`, two passed in
2.83s, already included in 134. Docs gate: `build/gcs-fetch-docs-20261114.log`,
52 passed in 1.35s. Whole-repository Ruff, privacy scan and scoped tracked-file
whitespace passed. Source/test hashes: `build/gcs-fetch-integration-20261114.json`.
No full check was rerun; the authoritative full report remains failed.
