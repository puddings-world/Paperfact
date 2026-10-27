# Archive-only adoption of original legacy PDFs

Complete recovery now handles an ordinary un-enrolled workspace whose compound,
generation, QA or slide receipt references an original PDF by SHA256 while the
live database has no document manifest. This is an archive operation, not live
enrollment or a fabricated `paper_document` event.

`sync_recovery.create` searches only these trusted PDF roots:

- `<explicit-database-directory>/pdf`;
- `<explicit-legacy-root>/pdf`, when supplied;
- explicitly supplied `pdf_roots=[...]` directories, or repeated CLI `--pdf-root`.

Embedded receipt paths, current URLs and unrelated machine directories are never
followed. Only required source hashes from validated research provenance are
adopted. The source must match the exact digest and any retained size; matching
filenames or paper titles are insufficient. Unknown legacy files still block a
complete backup instead of being omitted.

```sh
python -m paper_daily.sync_recovery create /workspace/papers.db /backups/research.zip --pdf-root /owned/research-pdfs
```

The scanner is bounded to 20,000 entries, 10,000 PDFs, 150 MiB per PDF and 8 GiB
total scanned bytes. It never follows symlinks/junctions. Matching bytes are copied
to private staging, rehashed after copying, and opened as a readable, unencrypted
PDF before publication. Changed, missing, unreadable or wrong-source bytes fail the
whole archive. A source file that changes between inventory and copying is rejected.

Identical hashes across trusted roots produce one archive object and one typed
`research_legacy_source_recovery(sha256, size, media_type)` row. Verified duplicate
aliases are accounted for without adding duplicate research. The live database,
source files, outbox, canonical document identity and account settings remain
unchanged. Source metadata from generation receipts now contributes to the same
complete source closure as compound, QA and slide research.

During inspection and detached restore, the archive-only PDF manifests and bytes
are validated again. The synthetic rows stay in `recovery_records`, and the exact
PDF versions stay in `objects/<sha256>`. No live binding, document operation,
transfer job or default current-PDF alias is invented. Research provenance retains
its original paper/version associations and paths as inert historical data;
readers/review code select the retained hash explicitly. Ordinary live-workspace
document enrollment remains separate from this complete-backup path.

The review agent's existing-user reproducer now completes: a real local PDF backs
a two-reference compound candidate, backup includes both candidate and PDF, and
the source database and original bytes remain unchanged. Behavior tests also cover
missing/changed PDFs, an outside-root receipt path, explicit root authorization,
same-hash deduplication, staging races, quotas, invalid PDFs and shared generation
provenance. No tests use the owner's research, a real provider or the network.
