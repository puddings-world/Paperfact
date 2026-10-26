# Exact-document derivatives

ADR 0005's derivative workers use the shared document resolver. They do not enroll
papers, download managed attachments, call models or replace a reader automatically.
Fixture integration is implemented; platform-native reader delivery is recorded
separately by the parent checkpoint.

`fetch.capture_document` checks managed history before legacy URL/cache access.
Managed missing, detached, unbound or invalid documents cannot fall through to an
old sanitized alias, text cache or publisher URL. The queue downloader performs
the same guard before and after legacy network work. Ambiguous legacy aliases
are blocked; ordinary un-enrolled downloads and existing legacy caches remain.

Managed text uses `(SHA256, text-v1, truncation options)` directories. Managed
figures use `(SHA256, figures-v1, crop/render options)` directories and include
`document_hash` and a relative `cache_key` in every index entry. Source capture is
rechecked before returning/publishing results. Text, figure indexes and managed
PNG writes publish atomically; previous hash/options directories remain intact.
Cached-only figure lookup uses metadata/cached verification status, never PDF
extraction or fresh hash verification on the UI thread.

`figures.cache_directory` identifies the current cache; `image_path` resolves only
bounded local entries. Current-source lookup requires matching provenance.
Historical lookup is explicit for an existing deck/material preview and retains
its old source hash. Saved deck assets remain preferred and are never migrated or
rewritten just because a PDF changes. Material insertion copies both hash and
cache key into the deck, and source citations retain the document hash. Managed
figure source IDs include the complete document hash (`figure:N:<sha256>`), so
a replacement PDF's Figure 1 can coexist with an old deck's retained Figure 1.
Legacy IDs remain unchanged; repeated insertion reuses only identical versioned
evidence, and conflicting/unproven provenance is rejected before deck mutation.

Material positions accept supplied rectangles only when their document hash
matches. Unproven/stale rectangles and anchors are removed from the navigation
payload without assigning the new PDF hash; text is retained with navigation
unavailable. Searching newly captured current headings is deterministic; old AI
analysis text is not automatically reanchored. Existing analyses stay stored and
AI regeneration remains an explicit action. FigurePane exposes the displayed
source hash; the parent compares it with the PDF actually rendered, allowing an
intentionally retained older version without relabeling its coordinates.

Managed pocket PDFs are separate derivatives. Their filenames include source
hash and compression options; a local JSON sidecar records both original and
compressed byte hashes. A compressed PDF is never presented as the original hash.
This records provenance, not proof that every original coordinate survives a PDF
rewrite. New quote lookup resolves the original exact source and tags its anchor.
Sharing/preview consumers use the same figure cache paths rather than legacy aliases.

`tests/test_document_derivatives.py` uses real synthetic PDFs with different
page/word/figure arrangements, same-paper replacements, colliding legacy aliases,
stale geometry, cached-only UI access, pocket derivatives, material previews and
deck evidence. It checks missing/detached source isolation and mid-extraction
replacement without publisher or model calls. Existing legacy suites remain
required. These fixtures do not prove live Windows/macOS viewer behavior, full
annotation synchronization, cache eviction, or production-scale performance.
