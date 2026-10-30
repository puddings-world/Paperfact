# Original-version inspection

When a saved claim cites original A while the current reader contains B, the claim view offers
one **View original version** action. It opens a separate read-only PDF window. The guarded
in-place source jump stays disabled for B; a failed current-reader proof also offers the explicit
original action. Opening, paging, zooming and closing this window never accesses AI accounts,
starts a model, activates a different primary document or writes annotations/notes.

Preparation runs off the GUI thread. It checks the actual loaded paper owner, bounded canonical
claim row and read-only local-to-portable mapping; the report's original paper alias is never
navigation authority. The typed source resolver verifies the exact desired original manifest,
current paper incarnation and complete registered source closure. A local accepted claim can
therefore be inspected before any applied receipt, authentication or synchronization exists.
No read operation marks a file applied or creates a portable identity.

The worker copies bounded PDF bytes, compares native file versions around the read, verifies the
full declared SHA256 and parses the PDF explicitly as PDF. A sealed immutable snapshot carries
its exact claim, registry and source-operation observation. Final GUI checks compare only owner,
source/claim metadata and file versions; PDF hashing/parsing never runs on that thread. Recreated
owners, retired sources, changed research and late workspace/paper switches reject the result.
An open window rechecks its owner and closes when that source intent becomes invalid.

Qt loads the verified bytes through a retained read-only QBuffer, so extensionless blob names or
a later path replacement cannot switch its content. One window is reused per claim view and
releases the PDF buffer on close. Without QtPdf, a coalesced worker renders one bounded page at
a time; rapid page changes keep only the final request. Closing waits asynchronously for active
workers instead of terminating them. The original reader's document, highlights and unsent
question/note drafts remain unchanged.

This first typed slice supports registered portable original manifests. Unbound private-pin and
validated imported-cache inspection require the separately tracked local-owner resolver; they
remain truthfully unavailable here without guessing a hash-named path, creating an identity,
publishing a cache or falling back to B. That common local flow is required follow-on work for
0.5, not a completed capability of this slice.

Tests use actual synthetic A/B PDFs, isolated databases and simulated earlier claim generation.
They cover pending desired files without applied/auth, extensionless bytes, paging/zoom, unchanged
research/journal state, duplicate activation, missing/damaged retry, stale owner/claim/source,
restored-mtime writes, account/workspace switches, cancellation and closing during fallback work.
No private research, live account, paid model or running user app was used. Native fixture PDF
rendering is inspected separately; the parent integration owns the complete project gate.
