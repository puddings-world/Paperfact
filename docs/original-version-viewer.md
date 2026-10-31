# Original-version inspection

When a saved claim cites original A while the current reader contains B, the claim view offers
one **View original version** action. It opens a separate read-only PDF window. The guarded
in-place source jump stays disabled for B; a failed current-reader proof also offers the explicit
original action. Opening, paging, zooming and closing this window never accesses AI accounts,
starts a model, activates a different primary document or writes annotations/notes.

Preparation runs off the GUI thread. It checks the actual loaded paper owner and exact canonical
claim; the report's original paper alias is never navigation authority. An enrolled workspace uses
the exact desired original manifest, current paper incarnation and registered source closure.
An unbound workspace uses an existing generated receipt or receiver-local imported-source receipt,
matched to the current database, binding, paper lifetime and declared original hash. Both local
analysis and validated package imports can therefore inspect A while the primary reader holds B,
without authentication, synchronization or an applied-file receipt. Reading creates no identity,
source ownership, schema, applied-file state or research content.

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

The local service owns receipt validation and exact-byte hashing; the viewer parses the returned
immutable bytes in its worker without hashing them again. It retains the opaque local proof and
delegates short metadata checks to that service before display and while the window is open.
Portable damage/retirement does not silently fall through to a different cache. Matching bytes or
a hash-named file alone never authorize reading: unknown legacy files, missing/foreign receipts,
changed paper lifetimes and revoked receiver ownership stay unavailable. Repair/import is explicit.

Tests use actual synthetic A/B PDFs, isolated databases and simulated earlier claim generation.
They cover pending desired files without applied/auth, extensionless bytes, paging/zoom, unchanged
research/journal state, duplicate activation, missing/damaged retry, stale owner/claim/source,
restored-mtime writes, account/workspace switches, cancellation and closing during fallback work.
No private research, live account, paid model or running user app was used. Native fixture PDF
rendering is inspected separately; the parent integration owns the complete project gate.

The valid generated-unbound case now opens successfully; this deliberately replaces the previous
unsupported-mode outcome. Separate negative UI fixtures retain identical cached A bytes while
removing the generated/import receipt and assert refusal without identity/ownership creation.
The focused integration selected 149 passing cases: local/portable viewer behavior, all earlier
claim/menu regressions, source-inspection read-only guards and the frozen local-owner backend.
