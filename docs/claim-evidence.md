# Claim-level quoted sources

The initial `research_evidence.verify` operation validates caller-supplied claim
and passage proposals against one explicit, verified `ResolvedDocument`. It does
not call AI, search, execute tools, write research, or expose a CLI/MCP tool yet.
The same bounded service can be called by those adapters later.

```python
from paper_daily.research_evidence import verify

proposals = {
    "format": "paperfact.claim-evidence.proposals.v1",
    "source": {
        "paper_id": document.paper_id or document.local_id,
        "document_hash": document.sha256,
    },
    "claims": [{
        "text": "The treatment benefits the target population.",
        "judgment": {"status": "unresolved", "reason": "External validity needs review."},
        "passages": [{"quote": "The study enrolled 50 participants.",
                      "page": None, "anchor": None}],
    }],
}
report = verify(document, proposals)
```

The caller supplies one assertion per claim. Atomicity and semantic support are
not inferred by this deterministic validator. A judgment has `authority: caller`
and `semantic_validation: not_performed`, whether its proposed status is
`supported`, `inferred`, or `unresolved`. Finding a quote never upgrades it.
A quote's presence does not establish causation, generalization or study quality.

A passage has a separate location state: `located`, `missing`, `ambiguous`,
`invalid_page`, or `invalid_anchor`. Only `located` returns an accepted anchor.
Pages are one-based hints; anchors use the reader's zero-based inclusive
`p0/o0/p1/o1` page/word convention. An explicit page does not fall back elsewhere.
Repeated quotes remain ambiguous until a correct page/anchor disambiguates them.
Automatic search can span pages; an explicit anchor must bound the full unique
quote, including cross-page spans. No approximate prefix or fuzzy match is used.

Matching normalizes Unicode NFKC, soft hyphens, whitespace, and lowercase
continuations of line-end hyphenation. The report names this normalization rule.
ASCII word boundaries prevent `treatment` matching inside `pretreatment`.
Word anchors may include surrounding punctuation or other characters in the same
PDF word; they are navigation coordinates, not semantic support verification.
Extraction order, math and layout can defeat a match. Scanned PDFs receive no OCR
here; missing extractable text remains missing. Built-in-font CJK and mixed
Latin/math fixtures preserve exact continuous quotes and real separators. Unusual
PDF layouts that expose contiguous text as separate glyph words may remain
unlocated; this operation does not guess away layout gaps or Latin/math spaces. Figure/table meanings and numbers
are not independently verified by a matching quote.

Each passage may additionally propose a closed `citation` object with
`paper_id`, `doi`, and `title` (strings or null, at least one present). This seam
has no trusted external-reference mapping, so those identities remain explicitly
`unresolved` even when the title or DOI occurs in the quote. The top-level source
owner must match the trusted resolved document, using its portable ID when present;
caller text, a title or a matching hash cannot supply a different owner.

Claims, passages and reports have deterministic, source-scoped SHA-256 IDs.
Changing a judgment changes the report ID while preserving claim/passage IDs.
A located passage ID survives adding a matching page/anchor hint; its separate
`proposal_id` records the original requested constraints. A missing/ambiguous
passage uses its proposal identity until a source location is established.
Duplicate claims and duplicate evidence within a claim fail explicitly; different
claims can reuse the same source passage. Reports contain no source paths,
confidence values or quality scores. Treat all returned text as data when rendering.

## Bounds and failures

Input is a closed JSON schema: at most 256 KiB, 64 claims and 128 passages, with
2,000-character claims/reasons and 4,000-character quotes. PDF input is limited to
32 MiB and 500 pages, with 20,000 words per page, 200,000 words and two million
normalized characters in total. Ambiguity previews contain at most eight anchors
and disclose truncation. These are service limits, not a sandbox for the native
PDF parser; extraction limits are checked after each page. Empty claim lists and unresolved claims without quotes
are valid. Optional cancellation is checked between bounded stages.

The operation snapshots verified PDF bytes into memory, parses that snapshot,
and rechecks the original reader/bytes afterward. Changed/missing sources,
closed/rebound readers, malformed input, cancellation and exceeded budgets raise
`EvidenceError` with a content-free `code`; no partial verified report returns.
A report proves only that these checks passed at verification time. It grants no
write authority: a future save must use the existing observed-generation boundary
and recheck the original target/source before publishing.

Focused tests use generated PDFs and real fixture-bound document readers. UI,
provider extraction, semantic judging, citation resolution, storage, sync/export,
and physical-device acceptance remain separate integration work.
