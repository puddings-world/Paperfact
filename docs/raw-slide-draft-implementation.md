# Raw slide drafts: local implementation and open gates

Status: isolated 0.5.0.dev integration, unreleased. This is not a claim of complete
portability or fault-safe retention. A reproduced primary-write failure remains
open and blocks release.

## Local behavior implemented

- Late raw results keep their original deck/observation strings and request ID in
  the original native database. A closed auxiliary record binds those strings to
  a portable deck body, evidence and every declared PNG, including unused figures.
- Used figures/evidence use the maintained deck codec; extra raw figures have a
  separately validated inventory. Account/execution metadata is not a portable
  deck or replay capability. Unknown historical PDF identity stays unknown.
- Original-workspace restart review verifies the complete closure and file
  witnesses, captures the displayed base and requires confirmation. Application
  uses the shared operation, activation and receipt transaction. A first-ever
  version directory is created during materialization, not preview.
- Complete owner backups validate raw/closure identity, all objects and declared
  originals. Detached readers return inactive read/export data. Fresh editable
  recovery retains raw records and their complete bytes as private provenance;
  it does not turn an archived draft into a current deck or runnable old job.
- Same-ID changed scientific evidence/images refuse; simultaneous identical
  requests recheck identity inside the write transaction and create one record.

Bounds: each existing raw/body/evidence field retains its 8 MiB limit; up to256
PNG descriptors, each at most8,000,000 bytes, total raw PNG inventory64 MiB.
These are validation limits, not throughput or completion figures.

## Evidence at current checkpoints

| Gate | Result | What it actually verifies |
| --- | --- | --- |
| Raw/review/file/recovery group |129 passed,0 skipped,364.85s;1,244 frozen inputs, no drift or unexpected external calls | New raw positive/negative cases plus existing managed deck, UI, handle lifetime and recovery behaviors. |
| Integrated local PDF controller |88 passed,0 skipped,307.96s;1,248 frozen inputs, no drift or unexpected external calls | Discovery/staging/confirmation, source A/current B, cancellation/retry, actual Main/compact UI and complete backup/editable recovery. |
| Mixed raw + legacy dataset |1 passed,0 skipped,19.95s;1,249 frozen inputs, no drift or unexpected external calls | One workspace with raw slides and historical A/current B survives backup, detached read and a fresh editable copy with exact raw/image provenance. |
| Primary first-write fault |2 healthy passed,2 fault cases failed,16.75s;1,250 inputs unchanged | Actual publication and simulated-model generation return a retained status but fail the image-persistence invariant. |

These scopes and snapshots must not be summed. Model calls are simulated; SQL,
PNG/PDF bytes, selected native Qt widgets and independent recovery directories
are real. No owner data, real provider or physical second device was used.
Existing508 test files remain unchanged by the raw integration.

## Confirmed defect, not a passing capability

Injecting failure before the first BlobStore.begin mutation leaves one raw row,
zero closure rows and no durable copy of three unique captured PNGs. Generation
returns no deck, the status still says the original draft was retained, and an
exact captured-byte retry makes zero staging attempts. Review and complete backup
correctly refuse the incomplete data; they do not repair the missing producer bytes.

The first newly-authored reproduction mixed assertions about that observed bug
with the opposite desired invariant, so it cannot serve unchanged as a passing
regression after repair. Its exact baseline evidence is preserved. The maintained
regression must consistently require durable verified bytes, safe repair and
truthful status; no legitimate prior behavior test is removed or relaxed.

The reviewed repair design uses a distinct owner-bound, verified full-deck
sidecar before primary staging, an exact no-model repair and backup/read support.
Both-storage failure also needs an actual-result holding state with explicit
retry/export/discard and normal close/restart/switch guards. Receipt data alone
must never grant sender execution or receiver writer authority. The repair is
not yet integrated. See [the remaining plan](retained-slide-draft-closure.md).

## Remaining release requirements

1. Fix and verify the primary-write failure and total-storage-failure UI contract.
2. Add explicit preparation for existing incomplete drafts without trusting paths
   or hash-only ownership from serialized observations.
3. Add first-enrollment and optional list-package draft/history adapters with full
   inventories and closed capabilities.
4. Add recovered-provenance discovery and explicitly reviewed fresh receiver
   application; archived byte preservation is not an editable draft interface.
5. Define and implement live draft/history sync, conflicts and desktop/mobile
   projection. Neither backup nor current-deck sharing fulfills that requirement.
6. Finish grounded lineage/audit integration, pass the current complete check and
   record installation, hosted-service and physical-device acceptance separately.

No current whole-project pass, commit or release is claimed.
