# Reference sync HTTP adapter

Status: local v0.5 integration boundary, not a public hosting solution.

`make_server(service, host="127.0.0.1", port=0, *, browser=None)` returns a `ThreadingHTTPServer`.
The caller starts `serve_forever` and stops `shutdown`/`server_close`. Only literal
`127.0.0.1` and `::1` bindings are accepted. This standard-library server must not
be exposed as the production sync service.

## Routes

| Request | JSON body | Success body |
|---|---|---|
| `POST /v1/push` | `{"operation": <private operation envelope>}` | One reference-service event |
| `POST /v1/pull` | `{"after": 0, "limit": 100}` | A contiguous array of events after the cursor |

Both require `Authorization: Bearer <device token>`, an explicit content length
and JSON media type. Administrative enrollment/revocation remain private Python
calls. Authenticated device controls and explicit one-time invitation routes are
specified in [device management](sync-device-management.md#one-time-device-pairing-core).
Workspace/device authorization is enforced by `ReferenceService` for every operation.

- Requests are bounded to 512 KiB; responses to 2 MiB. Pull materializes at most
  four events per request, then returns the largest contiguous prefix within the
  byte limit. Continue using the last durably applied sequence, including when a
  response contains fewer events than requested. A single over-limit event returns
  an error rather than falsely claiming the workspace is caught up.
- Duplicate JSON fields, nonfinite JSON values, unknown root fields, invalid pull
  bounds, query paths, ambiguous lengths, compressed/chunked request bodies and
  unsupported methods are rejected. Each response closes the connection.
- Errors use fixed codes without exception text, URLs, submitted research or tokens.
  Request/body logging is disabled. Responses have `no-store` and no CORS grant.
- Socket reads have a 10-second timeout. This is a bounded local test boundary, not
  a substitute for production concurrency limits, rate limiting or request admission.

## Client transport

`HttpTransport(base_url, timeout=10)` exposes `push(token, operation)`,
`pull(token, after=0, limit=100)`, `close()` and a context manager. Constructing it
does not contact the service. It is compatible with `SyncClient.sync_once`.

Remote URLs require HTTPS. Plain HTTP accepts only literal loopback addresses.
Credentials, query strings, fragments and additional base paths are prohibited
in URLs. Environment proxies and redirects are disabled, TLS validation remains
enabled, and response bytes are streamed under the cap without decompression.
Tokens travel only in authorization headers and are never persisted by this module.
Timeouts and connection errors are sanitized. `SyncClient` still validates the
semantic event envelope and applies the research/cursor transactionally.

The adapter was checked against the installed httpx 0.28.1 `Client.stream`,
`Response.iter_raw`, timeout and redirect/proxy configuration interfaces.

## Acceptance and remaining work

`tests/test_sync_http.py` uses temporary reference databases and real loopback HTTP
servers. It covers replay, workspace isolation, revoked devices, request/response
bounds, pagination, malformed bodies, non-leaking errors, forbidden enrollment
routes, redirect suppression, proxy independence and clean server shutdown.

No cloud, real account, public deployment, native/mobile client or TLS deployment
was exercised. Production hosting/authentication, secure device enrollment,
certificate/ingress setup, abuse controls, browser session/CORS policy and managed
attachment UI/reader activation are separate release gates. No CLI or app startup auto-launches this server.


## Private attachment routes

When the reference authority has an explicit `blob_root`, five additional fixed
POST routes expose its authenticated native blob API. They use the same bearer
header, closed JSON parsing, body caps, no-store responses and non-logging server.

| Route | JSON body | Success body |
|---|---|---|
| `/v1/blobs/begin` | `{sha256, size}` | `{upload_id, sha256, size, offset, complete}` |
| `/v1/blobs/append` | `{upload_id, offset, data}` | `{offset}` |
| `/v1/blobs/commit` | `{upload_id}` | `{sha256, size, complete: true}` |
| `/v1/blobs/cancel` | `{upload_id}` | `{cancelled: true}` |
| `/v1/blobs/read` | `{sha256, size, offset, limit}` | `{data}` |

`data` is canonical strict base64. Raw append/read chunks are bounded to 256 KiB,
so the encoded request stays below the existing 512 KiB cap. Append requires a
nonempty chunk; a read exactly at EOF returns empty bytes. Query paths, duplicate
fields, malformed/padded alternate encodings, traversal-shaped upload IDs, boolean
offsets and oversized ranges are rejected. Workspace ownership is enforced by the
service on every phase; knowing a digest or an upload ID grants no access.

`HttpTransport` exposes `blob_begin`, `blob_append`, `blob_commit`, `blob_cancel`
and `blob_read` with the same arguments as the native service (`blob_read` returns
bytes). It validates closed response shapes, manifest identity at begin, offset
bounds, completion booleans and exact read-range length before returning results.
The caller must compare commit's hash/size to its original manifest and perform
full local hash verification before publishing downloaded bytes. The transport
stores neither credentials nor upload progress and does not automatically retry.

HTTP 409 maps to retryable `BlobUnavailableError`; an absent blob configuration
maps to `BlobDisabledError` (503), as does a missing route on an older server (404).
Quota/transfer rejection on blob routes maps to `BlobQuotaError` (413). Revocation
remains `PermissionError`; connection/timeouts retain the existing sanitized
exceptions. No public deployment, blob redirect support or URL fetching is added.

`tests/test_sync_blob_http.py` covers real loopback upload/resume/commit/read/cancel,
workspace isolation, revocation, malformed bounds, unavailable/disabled/quota
responses and strict client reply validation. Connection-error handling uses an
injected httpx error around an otherwise real upload/resume fixture. These tests
do not exercise a public service, real accounts or native/mobile platform delivery.


## Session identity before byte transfer

`POST /v1/session/info` requires the bearer header and the exact empty JSON object
`{}`. It returns only `{workspace_id, device_id}` for the authenticated token;
neither field is selected by the request. It remains available when blob storage
is disabled. Revoked/unknown tokens fail authorization, and query-token paths are
rejected without echoing credentials.

`HttpTransport.session_info(token)` validates the closed response and both bounded
identifiers. A transfer coordinator must compare this identity with its bound
journal before sending any PDF bytes, and repeat the handshake for a new session
generation. Possessing a valid token for a different workspace/device is not a
valid binding for the current local research. Every subsequent blob request still
reauthorizes independently; a successful handshake is not a revocation bypass.
Peers without this endpoint fail closed rather than assuming token ownership.


## Bounded rejection cleanup

An error response is written and flushed before cleanup. The server then
half-closes its output and discards unread input in chunks of at most 64 KiB,
with a total 512 KiB cap and a 200 ms absolute deadline. This discard does not
interpret or trust the rejected request's framing. A timeout, reset or EOF ends
cleanup without replacing the original response. Successful requests keep their
existing behavior; authorization, route matching and body limits are unchanged.
Cleanup cannot guarantee delivery when the peer exceeds these limits or resets
its connection. This remains a loopback reference adapter, not a public server.

Windows loopback evidence: before this fix, 300 unknown-route POST requests
produced 78 connection errors (one normal request, 71 requests with headers/body
split by 2 ms, and six with a 64 KiB body). The same experiment with bounded
cleanup returned the complete 404 JSON response for all 300 requests. The full
suite's two unknown-route failures independently reported WinError 10053. This
was a connection-close race, not evidence of invalid credentials or a slow API.

`tests/test_sync_http_rejection.py` covers delayed bodies on unknown/query routes,
missing authorization, unsupported methods and invalid framing; buffered unread
input; absent bodies; EOF/reset/timeout; and deterministic byte/deadline limits.
These use local fixture sockets and fake streams, without accounts or external
services. The observed transport failure and experiment are Windows-specific;
native Linux/macOS validation is still separate from these fixture checks.

## Same-origin browser adapter (development)

`BrowserSessions(service, origin, key, *, clock=None)` in `sync_browser.py` adds an
explicit optional browser boundary to `make_server(..., browser=sessions)`.
Default servers expose none of these routes. `key` is a dedicated private 32-byte
signing key supplied by the embedding operator, stable across process restarts.
There is no built-in key, automatic key generation or signing-key CLI yet. The
adapter must use the exact authority object passed to the server.

Serve the PWA and `/v1/browser/` on the same canonical HTTPS origin. Every browser
POST requires exactly that `Origin`, `X-Paperfact-Browser: 1`, JSON framing and,
when present, `Sec-Fetch-Site: same-origin`. Every research request also requires
`X-Paperfact-Workspace` and `X-Paperfact-Device` matching the signed cookie. Complete
requires the same match when the tab already observed a prepared identity. This
prevents a shared cookie changed by another tab from changing the caller's scope.
An explicit initial resume can discover identity before any research request.
Reject mixed Authorization headers,
ambiguous cookies and origin aliases. No CORS/preflight exception is added and
forwarded Host/Origin headers do not select the trust boundary. Literal-loopback
HTTP is a local fixture exception with a separate cookie name, never remote HTTP.

| Browser POST route | Body | Result |
|---|---|---|
| `/v1/browser/pairing/prepare` | `invitation`: the private desktop pairing JSON string | Workspace/device IDs and a pending HttpOnly cookie; no enrollment or research write |
| `/v1/browser/pairing/complete` | Empty object | Same workspace/device IDs and a verified cookie after admission/authentication |
| `/v1/browser/session/forget` | Empty object | `forgotten: true` and expired local cookie; no research deletion or implicit remote revocation |
| `/v1/browser/session/info`, `/push`, `/pull`, `/blobs/...`, `/devices/...` | Existing closed protocol bodies under `/v1/browser/` | Existing protocol results; cookie authorization rechecks revocation and exact identity |

The ordinary device-pairing redeem route is excluded from the cookie facade.
Device invite creation and management remain authenticated single-owner actions.

The cookie is HMAC-SHA-256 signed and bounded, with a fixed 14-day lifetime. HTTPS
uses `__Host-paperfact-device`, `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`
and no Domain attribute. It contains access secrets: signing is integrity, not
encryption. Never log or export Cookie/Set-Cookie, request bodies or signing keys.
JavaScript gets only workspace/device IDs; credentials never enter IndexedDB,
localStorage, service-worker cache or research exports. Keep the signing key in a
separate private operator store, outside research and authority recovery packages.
Changing the key invalidates cookies; device revocation is checked independently.

Prepare must finish before complete: a browser that never stored the pending
cookie cannot enroll. An exact prepare retry reuses the saved identity. Complete
first authenticates that independent key, so an already admitted device can resume
a lost response after invitation expiry or issuer revocation. An unused expired
invitation cannot enroll. Active-cookie retries retain expiry; they do not mint
another device. Forget a conflicting/expired saved attempt explicitly before
preparing another invitation. Forget cannot retract an admission already sent.

The mobile `CookieTransport(origin, {pageOrigin, fetch})` reuses the existing
bounded parser. `preparePairing(invitation, signal)`, `completePairing(signal)` and
`forgetSession(signal)` use the routes above. Inherited Engine operations accept
only the non-secret `COOKIE_SESSION` handle and send no Authorization header;
fetch uses `credentials: same-origin`, no redirects and no response caching.
Legacy `HttpTransport` and `browserTransport` retain bearer-only, omit-cookie use.

This is a local adapter/transport checkpoint, not end-user browser login. Remaining:
pairing/reconnect/forget screens, guarded mobile workspace adoption, private key
loading/operator configuration, same-origin HTTPS hosting, actual browser cookie
persistence tests and physical iOS/Android acceptance. Opening existing cached
research still sends no request or cookie automatically. A broad security/hosting
review remains required; these fixtures do not certify resistance to XSS or theft
by another process using the browser profile.

### Browser-session behavior map

`tests/test_sync_browser.py` groups eight scenarios: prepare/complete and bearer
coexistence; lost-reply restart after expiry; competing claimants and unused
expiry; CSRF/origin/media-type refusal; tampering/key/origin/expiry/duplicate-cookie
refusal; revocation/forget; opt-in/exact-authority configuration; and a competing-tab
cookie change that cannot enroll/read under the wrong observed identity. These use
actual loopback HTTP and synthetic secrets. `mobile/tests/browser-session.test.mjs`
covers cookie-only Engine framing, same-origin/error boundaries and cancellation
with legacy bearer compatibility. The existing shell-upgrade scenario now verifies
v19 transport eviction while preserving research caches. No combinatorial stress
matrix or real account is used.

Design references checked 2026-11-14:
[MDN cookie attributes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)
and [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

Local checkpoint evidence (2026-11-14): all 14 critical selectors plus affected
browser, pairing, bearer/framing and usage-doc scenarios passed **50 Python cases
in 13.63s**, **16.8s including privacy/Ruff**. The four named mobile files passed
**18 cases in 3.04s**, **3.19s under the governor**. Both used the Windows 25% CPU,
two-logical-core, 300-second bound; no full/release matrix ran. The mobile fetch
adapter is simulated, while Python scenarios use actual loopback HTTP. Neither
proves browser cookie persistence, TLS/proxy configuration or physical phones.

The locally validated lesson is request-time workspace/device binding when
cookies are shared across tabs. Existing bearer isolation alone did not establish
that boundary. Keep this evidence scoped here: browser and hosted acceptance are
pending, and no global skill/authentication policy was promoted from it.
