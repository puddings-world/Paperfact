# Editable copies of detached recovery

Status: isolated development candidate; no desktop action or release claim. Legacy
queue and delivery-log writer migration remains a required gate. Unknown future
protocols remain blockers until their maintained typed validators exist.

A detached restore retains research, exact files and previous protocol records.
Those records are observations, not a device identity or authority to replay jobs.
Opening a restored deck remains read-only. Creating an editable copy is a separate,
explicit operation and never replaces the restored source or a daily workspace.

## Service contract

```python
service = RecoveryAdoptionService(restored_database, current_path=current_path)
inspection = service.inspect(ticket=ticket, progress=progress)
report = inspection.report
result = service.prepare(
    inspection, new_workspace_directory,
    backup_output=new_independent_backup,
    request_id=canonical_uuid, ticket=ticket, progress=progress,
)
```

The inspection is privately sealed and belongs to that service and database
lifetime. The report is a small copied value, not mutable provenance. Preparation
rejects caller JSON, another service's inspection, source changes, unsupported
canonical modes, existing outputs, overlapping source/output paths and concurrent
preparations. No login, provider, vault, network, upload, source activation or AI
call is involved.

A successful result is `prepared_for_review`, with a new workspace/device identity,
a separately verified backup, `editable_copy=True`, and `adopted=False`/
`uploaded=False`. Opening the new workspace is a later explicit action.

## Exact recovery inspection

The adapter validates `recovery.json`, the detached identity, every registered
canonical table, ordered archived records, and the complete original object
closure using the maintained recovery validators. Canonical rows must still match
the original manifest, including row counts and digests. Unknown records, columns,
writers/views or extra files cannot disappear silently.

The exact maintained private KV namespaces and top-level private filenames from
ordinary enrollment are excluded from new research. KV filtering happens inside
SQLite before private values are fetched or serialized; credential file contents
are never opened/copied. Only exclusion counts are reported. Unknown KV or
settings-like filenames remain blockers. Existing private-file/DB native versions
and complete file inventory remain freshness guards; private changes after an
inspection can require inspecting again.

The adapter additionally applies the stricter generation input/source validators.
It verifies typed deck/PNG/evidence closures and parses declared PDF sources in a
worker. This proves readable original bytes and preserves the recorded quote
locations; it does not re-adjudicate or certify an AI proposal's semantic support.

Saved reader projections are regenerated from the verified original objects and
compared against the recovered files. Context paths and URLs in old jobs are never
followed. Native DB/WAL/file versions bind the inspected bytes and catch late
changes, replacement and restored-mtime edits. Final guards use metadata without
rehashing all PDFs repeatedly. Source mutation never grants new authority.

## Preservation and new authority

All supported canonical rows are copied together: every list and its custom order,
membership, unlisted papers, notes, reading annotations and saved research. Sharing
individual list packages is not a substitute for a workspace recovery.

A typed `research_recovery_provenance` archive retains the exact original manifest
and complete ordered rows. Group validation reuses the closed recovery registry,
including complete old journal/receipt/source/deck closures. Independent groups
keep separate identities. Nested prior groups are validated independently rather
than merged or replayed. The optional archive table is initialized only during
explicit accepted preparation; it is absent from global schema initialization.

Fresh baseline projection uses `EnrollmentService` and its ordinary losslessness,
backup and publication checks. A private sealed hook retains old object bytes in
the new owned store, archives old protocol records, and re-encodes current saved
**applied** deck slots with their layout, notes, figures and saved evidence. Missing
saved evidence remains absent; no fresh research inputs are substituted. New
operations use the new paper parent and deliberately incomplete input-version
metadata rather than old job capabilities. Fixture acceptance includes loading the
new managed deck, manually changing its title and speaker notes, saving/reopening
through the real editor publication path, and verifying the restored source stayed
unchanged. This manual edit requires no AI call.

Current applied primary B remains primary. Current typed annotation original A, nonhidden applied originals and exact saved
deck originals become typed original-source artifacts against the new paper epoch.
Pending, conflicted, hidden/deleted and retired file operations stay historical;
the adapter never silently promotes a pending old file into the current reader.
Their complete declared object closure remains in the archive and backup.

A backup of the new workspace is inspected before candidate/backup publication.
Failure rolls back only this operation's own newly published paths. Cancellation
and final publication share the existing Ticket arbitration. Repeated restore/copy
cycles retain previous provenance without installing old live identities.

## Bounds and remaining gates

The maintained recovery bounds apply (10000 blobs, each at most 150 MiB; metadata,
row and total byte limits). Native immutable source checks must be available on the
filesystem. Provenance nesting is explicitly bounded to eight validation layers;
exceeding a bound refuses editable adoption instead of truncating history. Existing
first-enrollment bounds also apply to the active baseline. A large supported archive
can therefore require a future reviewed capacity increase, never silent omission.

Nonempty legacy `queue` and `reading_log` rows are preserved in the original archive
but currently block editable adoption. Their rank/state/role/parent/reason/times,
individual log identities and brief-file closure require the separate typed legacy
workflow migration. They must not be dropped, guessed into lists/notes or declared
finished by this covered-subset service. Future lineage/chat records remain
blocked until their typed adapters are present.

Desktop selection/cancel/close interaction, physical cross-platform devices and the
project's final complete gate remain parent integration work. Focused fixture counts
and exact hashes are recorded in the isolated delivery manifest, not inferred here.
