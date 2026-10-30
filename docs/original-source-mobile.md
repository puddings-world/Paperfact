# Original-source files on mobile

Mobile accepts the closed `research_file` feature `original_source` independently of editable
decks and `paper_document`. Its immutable slot is the exact original PDF SHA256. The operation
has one exact paper parent; the closed version-1 body repeats only that portable paper ID and
hash. One `original` / `original_pdf` asset carries `application/pdf`, bounded to 150 MiB.
Input versions are explicitly incomplete/empty and grant no model, account or input authority.
Private source receipts, filesystem paths and credentials are never part of this wire format.

`projection(...).original_sources` is read-only metadata, separate from `decks`. Receiving a
manifest never downloads bytes or marks the source offline-ready. Explicit `downloadArtifact(id)`
uses the existing authenticated, deduplicated range-transfer worker. `originalSource(id)` exposes
only a complete applied closure whose body, hash, owner, parent epoch and bytes remain valid;
`deck(id)` rejects this feature. Both original A and current primary B can remain available
without rewriting or selecting the other. No active source-navigation UI is added here.

The returned `verification_scope: exact_bytes` means byte integrity plus the existing mobile PDF
format boundary. It does not certify PDF parser readability, quote/claim semantics or research
quality. Python's source producer additionally validates readable PDF bytes. Mobile does not
add a native PDF parser or execute source content during verification.

The existing artifact cache remains 128 MiB. The 150 MiB wire bound is not a storage promise:
a larger closure fails with `storage_quota` before transfer or offline exposure. Previously
verified files are not evicted automatically. Smaller transfers can resume retained chunks
after a connection error; invalid/incomplete content never gains an applied-source record.
Unknown metadata stops receive without advancing the accepted cursor or replacing old state.
Source retirement and paper-epoch changes suppress cached access; session changes prevent late
activation, while already verified local research remains available offline.

No new static module is introduced. The changed modules ship in the parent's upcoming shell-v7
freeze; this slice does not alter service-worker privacy/cache policies or cache private requests.
The existing claim HTTP fixture now configures isolated blob storage and uses real FileTransfers
to upload the accepted producer's declared original before desktop sync. Its no-mobile-upload,
no-repeat-AI and asserted-claim-content checks remain unchanged.

Validation uses the unchanged Python golden source fixture, 14 source lifecycle/contract cases,
all existing mobile regression cases, and authenticated loopback integration. The new actual
publisher fixture creates readable synthetic original A and distinct current B, exercises a
real interrupted/resumed range download, reopens offline, and retires the source without changing
B. No real account, external endpoint, paid model, private research or physical phone was used.
