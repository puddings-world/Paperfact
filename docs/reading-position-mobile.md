# Reading-position snapshot and mobile parser checkpoint

This checkpoint adds read-only mobile position metadata and exact-source snapshot
preservation. It does not activate entered-page controls or automatic mobile page
tracking. Phone-first primary retention and entered-page publication are the next
required slice; a desktop preparation roundtrip is not the final product design.

A version-2 snapshot includes closed `reading_positions` only when every row has
its current paper lifetime and exact `original_source` declaration. Both original
A and current primary B remain declared, independently keyed by SHA-256. Asset
metadata is unchecked unless independently verified; importing it creates no
bytes, active graph, outbox operation or cursor authority. Missing, retired or
malformed closures keep the existing refusal; version 1 still refuses positions.
The sorted required-capability set is the exact union of Inbox, queue pins and
reading positions actually present. Older receivers reject the unsupported
envelope or feature before persisting that incoming transaction.

Mobile independently validates the closed existing `research_content`
`reading_position` feature, including one-based pages, aware timestamps, exact
source key, owner, parent lifetime, known deletion and fresh restoration. A
received position never creates an observation or inferred last-opened state.
Known deletion suppresses stale snapshot rows. Original retirement suppresses
cached access without replacing primary B.

JavaScript domain values use `Number.isSafeInteger`. A domain value cannot
distinguish integer `1` from source token `1.0`. At the actual bounded HTTP or
snapshot-file ingress, a structural scanner checks original position-page tokens
before that distinction is lost. It recognizes escaped keys and JSON strings,
accepts whitespace, and leaves legacy ranks such as `1.0`, `-2.75`, `1e21` and
`-1e-7` unchanged. No lexeme metadata is persisted or added to the wire.

The count-only parser uses the matching official PDF.js 6.4.299 compatibility
display/worker pair and its original Apache-2.0 license. Release archive and file
SHA-256 hashes are pinned in `mobile/vendor/pdfjs-6.4.299/provenance.json` and
independent tests. The archive has no top-level NOTICE. No auxiliary font/CMap,
ICC, image/WASM or viewer assets are shipped in this count-only slice. Only a
private copy of verified bytes enters the owned real worker; no PDF URL is passed.
XFA, WASM and auxiliary worker fetching are disabled. The original buffer remains
available for its existing viewer. Unsupported workers, encryption, malformed
input, mismatched hashes, oversized PDFs and deadlines refuse count authority.

The parser reads genuine `numPages` and the last page, bounds input at 32 MiB and
count at 1,000,001, and returns a transient sealed local proof. A sender-provided or
restarted cached `page_count` cannot substitute for this parse. One worker is
admitted at a time; cancellation/deadline terminates it, and cleanup waits at most
250 ms before final termination. There is no main-thread fake-worker fallback.

The parser/worker/license are explicit service-worker shell entries (v10). A
fresh-profile Edge fixture verifies parsing with actual workers, unchanged product
CSP, inert PDF JavaScript, cancellation, timeout/retry and fresh-worker parsing
while network is offline. This is fixture browser acceptance, not served PWA,
installed-app, iOS/Android or native-viewer viewport acceptance. No scripting UI,
PDF rendering or guaranteed fragment navigation is implemented. The browser's
native `<object>` reports neither viewport nor page count.

Run the isolated parser fixture with an explicit browser executable:

```powershell
$env:PAPERFACT_TEST_PAGE = 'position-browser-test.html'
node mobile/browser-check.mjs 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
```

The default browser fixture page remains unchanged. The full project check still
owns release evidence; focused results belong in the accompanying frozen receipt.
