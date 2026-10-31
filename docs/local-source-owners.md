# Receiver-local ownership of imported original PDFs

A claim may cite original A while the reader currently shows PDF B. Opening A must
not replace B, rewrite the claim, invent ownership from a filename, or invoke AI.
Portable enrolled workspaces use typed `original_source` artifacts. This separate
private adapter covers unbound imports and existing generated-source receipts.

## One receipt envelope, distinct authority

Imported receipts reuse the existing five fields: `request_id`, `owner_json`,
`sha256`, `size`, and `media_type`. The owner binds the receiver database inode,
workspace binding, local paper ID, and a fresh device-local paper epoch. Imported
`source_owner_id` is that receiver-local paper ID. Original semantic evidence IDs
inside the claim remain unchanged; sender IDs never become receiver authority.

`research_local_source_owners` is initialized lazily only for nonempty accepted
imports, inside the importer-owned SQL transaction. It is absent from global
`store.SCHEMA` and `_migrate`. Reading a paper or looking up an original creates no
table, epoch, receipt or portable identity. The actual reader supplies its already
captured `HighlightOwner`.

Generated evidence retains its existing 32 MiB receipt policy. A trusted explicit
validation/path policy permits imported original PDFs up to the primary-PDF limit
of 150 MiB. Passive provenance archives also permit that limit. Neither the wire
format nor a user-supplied field can raise the generated evidence budget.

## Import transaction

`prepare_import(database, archive, manifest, tables, excluded=...)` runs outside
SQL's write lock. It validates included claim originals, publishes only exact bytes
into the fixed immutable `.claim-evidence` cache, and captures native file proofs.
An existing mismatching cache file is a conflict and is never overwritten, even
with replace enabled. Cancellation or a crash can leave unowned cache bytes; they
are not a receipt and cannot satisfy the viewer.

The ordinary unbound `bundle.import_` then calls `ensure_import_in` before paper
SQL and `register_import_in` after file installation. Ownership is granted only
when the actual canonical SQL claim exactly matches the imported typed claim and
the receiver paper has its current epoch. SQL content, receiver epochs and active
ownership commit together. Failure rolls them back; ordinary bundle-installed
files retain their existing rollback behavior. Immutable cache bytes may remain
unowned for a safe retry. Repeated imports reuse the same owner/claim receipt.

Changing database files or any installed workspace binding between preparation
and SQL publication invalidates the proof. A newer canonical claim kept by the
ordinary importer receives no unrelated new ownership. Deleting and recreating
the same local paper ID does not reactivate an old receipt; an explicit new import
must observe and grant ownership for that new receiver epoch.

## Read-only viewer API

```python
proof = local_source_owners.prepare(loaded_owner, displayed_claim, cancelled=cancelled)
# None means cancelled; failures report unavailable without falling back to B.
if proof is not None:
    # Worker-only PDF parsing may use proof.data to count/render pages.
    # Do not hash it again on the GUI thread.
    still_current = local_source_owners.metadata_current(proof)
```

The sealed result exposes `.data`, `.source`, `.file_version`, and
`.document_hash`; its claim/receipt fields are opaque guard state. Preparation
checks the exact current canonical claim, loaded owner, receiver epoch, receipt,
and actual byte hash. It hashes one selected original in a worker. The final
metadata guard performs bounded read-only checks and native file-version checks;
it does not hash or parse PDFs on the GUI thread. It rejects replaced databases,
changed claims/epochs/receipts, missing files, and same-size byte changes with a
restored mtime.

Imported receipt lookup is scoped to the selected hash. Generated receipt fallback
scans at most 10,000 receipt metadata files and 16 MiB of metadata, then verifies
only a matching source. An unrelated malformed generated receipt cannot interfere
with a valid selected imported receipt. Full archival inventories remain strict.
The portable viewer branch remains first; damaged or retired portable ownership
must not silently fall back to a local cache.

## Sharing, recovery and limits

List packages share claim content and included original bytes, not these private
receiver identities or active receipts. A recipient grants its own new ownership
only through its explicit import transaction.

Independent recovery has an optional typed registry for these original receipt
observations. It retains exact source bytes and archives the old owner records in
`recovery_records`, never a new active ownership table. Restoring a backup alone
cannot make an old receiver inode/epoch valid on another machine. First enrollment
must likewise archive original observations and grant new portable artifact
authority through its reviewed adapter; it must not copy active local-owner rows.

This adapter does not make every unbound workspace backup complete. An untracked
current primary B, a legacy deck without accepted publication history, or other
unrepresented research files still require reviewed migration; existing recovery
coverage checks continue to reject partial archives. Desktop viewer integration
and the enrollment catalogue/archive adapter are separate integration steps.

No login, provider call, network request, current-PDF activation, synchronization,
pin, or cache-eviction guarantee is implied by retaining or opening an original.
