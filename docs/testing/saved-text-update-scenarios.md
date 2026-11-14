# Saved text update scenarios

Development evidence, 2026-11-13. Read this map by behavior, not case count.

| Scenario | Observable acceptance |
|---|---|
| Shared signatures in unbound and native workspaces | Actual saved-reader snapshots and note-card rows produce the same signature; observing does not mutate SQL content. |
| Independent text groups | Changing a note, chat turn or explanation changes only its group signature. Native analysis uses real journal operations, preserving observed-write requirements. |
| Unlisted open paper | A committed note is observed without causing a list refresh; repeated polling creates no extra worker/data. |
| Old queued result | Rebinding the same paper with a new view token discards the prior token's queued result. A workspace change inside delivery prevents later list refresh. |
| Background notice | A real reader with a synthetic PDF keeps the original instance/page, focus and unsent note/question text while an external transaction changes saved research. |
| Explicit reload | Current saved explanation, answer and note appear only after the action; the original and drafts remain. |
| Rapid repeated action | A held real preparation worker receives one admitted job despite 25 repeated activations. |
| Failed read and retry | A simulated SQLite failure exposes no private error details, retains the notice/drafts and succeeds on retry. |
| Later | The exact dismissed signature stays quiet; a newer saved note reappears. |

Direct initial evidence: signature/observer scope **12 passed in 16.43 s**;
actual-reader notice scope **5 passed in 9.42 s**. These predate the final
reentrant-delivery case and are not release totals. The maintained adjacent gate
and exact remaining limits are recorded in the continuation ledger.

Early native fixture writes first used an invalid timestamp, then omitted the
required observed analysis base. The fixture was corrected to use a real native
content operation; production validation was preserved. The actual UI also
exposed a real adapter mismatch: note cards omit paper_id. The production hash
now uses their actual displayed fields while owner checks remain separate.

The banner covers saved explanations/close reading, chat and note cards. Other
research surfaces keep their own explicit refresh controls. The full application
gate and actual hosted/Windows/Apple Silicon/phone journey remain open.


Maintained adjacent gate: **180 passed in 167.39 s**, 171.4 s overall,
privacy/Ruff passing, zero failures/errors/skips. This includes the new reader
and signature cases, existing revision-watcher lifetime, main-window scope and
saved-reader preparation/input contracts. It predates the Chinese-label correction.

Visual QA used the actual isolated reader and PDF. The first offscreen capture
lacked the normal style/CJK font initialization. Applying the real app style
and loading its Windows font fallback then exposed question marks in the new
labels: terminal Unicode transport had corrupted them at source-write time.
The labels now use ASCII-safe Unicode serialization, with exact Chinese-text
assertions. Final direct GUI scope: **6 passed in 8.01 s**. The corrected
screenshot was inspected; its compact message and both controls are readable
without clipping. The image contains only synthetic test labels.

These are overlapping development checks. No hosted/installed-device pass or
full application green is implied.


Final affected gate after the label fix: **20 passed in 26.47 s**, 29.6 s
overall, privacy/Ruff passing. This covers all 14 signature/observer cases and
all 6 actual-reader/language cases. An initial final-gate attempt stopped at
Ruff because ASCII-escaped Chinese strings exceeded line length; reserialized
the identical parsed strings as UTF-8 source without changing text or logic.
No source change followed the passing gate.
