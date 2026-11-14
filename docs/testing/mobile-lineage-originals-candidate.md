# Mobile Lineage originals: isolated candidate

Status: originally tested in an ignored development copy; integrated into the
unreleased canonical development checkout on 2026-11-14 after the prior full run
ended. It is **not shipped or installed**. The preceding canonical full gate failed
at an old inactive-stage assertion (3,349 passed, one failed); its source/test
inputs had not been changed during that run. Integrated verification follows in
the continuation ledger; earlier isolated receipts below retain their scope.

## Observable behavior

The real PWA Lineage cards expose exact-original actions only after workspace
setup and when a matching active native source exists. The dialog reads a saved
verified source first; downloading is explicit. It preserves the primary PDF and
research outbox. An explicit browser PDF link carries the located page; inline
preview is optional and collapsed so unsupported viewers do not create a blank
mobile screen. Close/Escape revokes local object URLs and restores a still-current
opener; a changed paper/account cannot steal focus.

A process-local lease rechecks the scientific row, every selected source/parent
pin, current optimistic lifecycle and verified applied bytes. Imported read-only
metadata grants no source access. Pending local retirement, known deletion,
same-hash restoration, changed report/source operations, cancellation and delayed
account/view changes refuse stale delivery. Cached corruption does not silently
redownload a replacement. Source inspection does not certify scientific claims.

## Tests and receipts

| Scope | Evidence |
|---|---|
| Real engine/source tests | 16 cases in `lineage-originals.test.mjs`: explicit download, immutable delivery bytes, offline reopening, read-only projection without grants, paper/source/report retirement, new source incarnation, delayed account/view/cancel, changed operations/report, forged/cross-engine lease, corruption, pending local retirement and the actual selected peer's different PDF. |
| Dialog behavior | 10 cases in `lineage-source-view.test.mjs`: English/Chinese copy, exact/invalid page links, repeated clicks, busy state, held close, changed paper, failure/retry without raw errors, offline/no-grant state, retirement cleanup, native cancel and scoped focus restoration. |
| Earlier isolated mobile Node checkpoint | **642 passed**, zero failures/skips/cancellations, 7.759 s. `build/lineage-mobile-v19-final-node-20261113.log`. Includes shell v19 upgrade removing stale v18 static code while preserving research caches. |
| Earlier Chromium component and PWA checkpoint | **15 checks passed** at 390 x 844: source action, missing-byte state, verified PDF, repeated activation, exact page, unchanged outbox, width, scope revocation, read-only embedding, real browser Escape, URL revocation, focus restoration and actual PWA startup/open/close from synthetic IndexedDB. `build/lineage-mobile-browser-app-admission-20261113.log`. |

Latest isolated compatibility gate: **647 Node cases passed in 7.608 s**, zero
failures/skips/cancellations, `build/lineage-mobile-origin-offline-final-node-20261114.log`.
It includes five browser-origin cases for the actual credential-send boundary,
same-origin IPv6 request, retained low-level IPv6/HTTPS/IPv4 capabilities, existing
URL rejection and bilingual/CSP policy. Real Chromium runs on both IPv4 and IPv6
loopback each passed **18 checks**, including the actual PWA, same-origin API and
cached offline restore with an unusable saved network origin. JavaScript/CSP
console errors were zero; native offscreen GPU diagnostics remain separate.
Logs: `build/lineage-mobile-origin-restore-browser-20261114.log` (IPv4),
`build/lineage-mobile-origin-offline-ipv6-20261114.log` (IPv6). These selections
include earlier cases; do not add them into a total.

The Node checkpoint preceded the final `app.mjs` workspace/busy admission fix;
the final actual-PWA browser check verifies that change. These receipts overlap
and do not replace the canonical full gate, packaged acceptance or a real phone.
The screenshot is a verified original dialog/component, not the whole installed
app. Qt offscreen widget capture initially showed a stale loading frame; direct
renderer capture over a loopback-only DevTools connection produced the verified
frame. A blocking helper timed out; the corrected owned QProcess kept Qt's event
loop active. GPU diagnostics remain in the raw probe logs.

The earlier PWA probe exposed an invalid CSP source expression `http://[::1]:*`.
The isolated candidate removes it while retaining `connect-src 'self' https:
http://127.0.0.1:*`; no arbitrary HTTP permission was added. The observed behavior
agrees with the [current CSP source grammar](https://www.w3.org/TR/CSP3/#framework-directive-source-list)
(working draft inspected 2026-11-14), and real IPv6 same-origin requests were tested.

`browserTransport(origin, {pageOrigin=location.origin, ...HttpTransportOptions})`
is the browser-facing factory. Its request preflight refuses cross-origin HTTP
IPv6 before credentials reach fetch and supplies useful English/Chinese copy.
Construction remains local and does not reject a saved workspace merely because
its network origin is unusable. The actual PWA therefore restores cached research
and opens exact original bytes offline without a credential/network request.
The lower-level `HttpTransport` retains its existing Node/injected IPv6 behavior.
Same-origin HTTPS deployment and CORS/server identity remain separate gates;
these local tests do not establish public hosting or arbitrary cross-origin login.

## Preserved failures and next integration

The first two-peer fixture was rejected for wrong device, then for changing an
existing corpus's parents. The corrected fixture uses the authenticated device
and a **new** corpus, retains the old report and opens the peer's actual different
bytes. Protocol guards were preserved. The initial keyboard fixture clicked an
invisible collapsed-passage button; expanding the real action and using browser
input retains the original focus assertion. Native Qt key injection alone did not
establish browser Escape handling. Actual PWA probing then exposed early enabled
source actions during workspace setup; the admission fix passes the final check.

Candidate files, checksums and minimal review diff are in the ignored directory
`build/lineage-mobile-next-20261113/` (`candidate-manifest.json`, `candidate.patch`).
The manifest records current canonical before-hashes and candidate after-hashes.
Before integrating, wait for the existing full check to terminate, inspect its
result, and recheck **all** base hashes before any write. Preserve unrelated edits
and each existing file's line endings; the review patch normalizes EOL for clarity
and is not permission to rewrite whole files. New code/Node tests are listed in
the manifest; browser probe/harness files remain test tooling, not product APIs.
After integration, run affected HTTP/mobile checks and a new coherent full gate.
No cloud service, user research, credential, paid call, installer or release was
changed. iPhone/Android and installed Windows/Apple Silicon acceptance remain open.


## Canonical integration checkpoint (2026-11-14)

All sixteen reviewed paths were hash-checked before canonical integration, with
unchanged line spans preserved. Integrated Node tests: **647 passed in 5.079 s**,
lineage-mobile-integrated-node-20261114.log. The maintained entry point with an
absolute Python interpreter passed the same 647 cases plus **13 actual isolated
Python/HTTP programs**, lineage-mobile-integrated-services-absolute-20261114.log.
These overlapping checks are not an aggregated test total. An initial invocation
used a relative interpreter; its child cwd correctly exposed ENOENT. The command
was corrected, with no production source or test assertion change.

A byte-identical integrated-mobile browser copy passed **18 checks each for IPv4
and IPv6**, zero JS/CSP errors. Provenance hashes and synthetic fixture are in
build/lineage-browser-integrated-20261114/provenance.json. The first attempt
omitted that fixture and failed with 404/JSON error; it was corrected only in the
probe copy. GPU diagnostics and a disconnected socket on shutdown remain in raw
logs. Inspected screenshot: ../images/lineage-original-mobile.png. Exact logs and
remaining full/installed-device gates are in the continuation ledger.
