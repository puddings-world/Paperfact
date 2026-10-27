# Typed compound retained-work review

The shared Review changes dialog can apply retained citation, followup and
resource groups produced by `research_compound`. The source request remains
immutable. Original inputs, current target rows, and retained puts/deletes are
shown separately. This is a typed group action, not an arbitrary SQL or JSON
editor. Opening, copying, exporting and applying never call an AI model.

## Supported origins and target choices

- `research_compound_requests` with candidate status.
- Owned `.paperfact-compound` sidecars.
- Archived compound request/recovery rows in a detached backup.

The selected paper's path/inode/binding, local epoch, graph parent, affected
entity observations, complete feature inventory, relevant completion flag and
desired/applied document targets are captured at preview. Apply compares that
exact snapshot; it does not silently obtain a newer base. The stored producer
record pins the original input metadata, prompts and source hash, even when the
review explicitly chooses a new target.

Foreign, restored or deleted parents require explicit paper selection and a
separate confirmation. Differing or unavailable historical PDFs are labeled as
historical provenance, not verified alignment with the current PDF. The original
source hash is retained on new typed operations. Archived path fields are never
used as instructions to open another directory. Missing bytes remain distinct
from a known hash.

Deleted synchronized reference keys also require explicit restoration. That path
uses the existing graph builder with `restore=True`, journal and research writer
inside the same transaction. Automatic SQL capture's no-implicit-restore rule is
unchanged. Protected manual/curated rows cannot be overwritten by a generated
phase merely because the user selected a target.

## Transaction and UI behavior

Normal groups use the producer's typed mutation validator/writer and loaded-base
capture expectations. Rows, local phase flag, outbox and existing review receipt
commit together. A failed child write, receipt or source check rolls back the
whole group. Exact request retries return the existing result; another window's
newer research invalidates a stale displayed group.

Local source PDFs are resolved and hashed once per snapshot; their captured file
identity is checked again before commit. Fallback source text has a 3 MiB read
bound. Group inventory is capped at 2,000 rows and 8 MiB before loading it into
Python; the complete preview has the existing 8 MiB bound. A transaction-local
graph snapshot is reused across observations and explicit restores.

The shared dialog disables Apply while working, keeps failed previews visible,
supports cancellation and explicit target confirmation, and labels grouped Apply
separately from editable text drafts. Group records stay read-only; existing
durable text drafts retain their own version/CAS/restore behavior. Keep current
creates only a local review decision, not a remote conflict resolution.

No new private table is added. Existing typed producer records and review
receipts use the existing recovery registry. Detached restore never reactivates
old operations; the user must select and confirm a target before new application.

## Remaining boundaries

Raw `research_capture_candidates` mutation lists remain read-only. They cannot be
treated as validated compound producer requests or replayed as generic SQL.
Typed file/deck candidate application and QA's separate typed dialog are separate
integration paths. Native macOS/Linux rendering and the merged full check remain
parent integration gates.

### Legacy PDF backup adoption remains open

An ordinary legacy PDF-backed compound candidate can be reviewed correctly while
its PDF has no registered document manifest. Current complete backup refuses this
workspace with `Research source PDF lacks a retained document manifest`, even if
the original PDF still exists and hashes correctly. This end-to-end case is NOT
completed by the registered-manifest roundtrip fixture.

Reproduce in an isolated workspace: create `papers.db` from `store.SCHEMA`, add
paper `paper`, save a fixture PDF as `pdf/paper.pdf`, then call
`research_compound.begin(... phase="citations", owner_id="paper")` and
`research_compound.read_text(context, pdf_root=pdf_dir, text_root=pdf_dir)`.
Change the paper title before publishing two valid citation rows (including
`basis="context"`), so publication retains a candidate. Call
`sync_recovery.create(database, destination)` without registering a document.
It fails before publishing the package; the candidate and PDF remain untouched.
`build/legacy-compound-backup-repro.py` provides this exact synthetic reproducer.

Required recovery seam: discover bounded legacy PDF references from validated
compound/file/generation provenance and current owned workspace mappings, verify
the original bytes against their SHA-256, and stage a declared archive-only blob
closure before `_Records.finish()`. Do not auto-enroll the workspace, fabricate a
live document operation, alter current bindings, or read an arbitrary archived
path. Missing/mismatched bytes must still block a complete backup explicitly.
The parent owns this cross-adapter recovery integration.
