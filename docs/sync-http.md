# Reference sync HTTP adapter

Status: local v0.5 integration boundary, not a public hosting solution.

`make_server(service, host="127.0.0.1", port=0)` returns a `ThreadingHTTPServer`.
The caller starts `serve_forever` and stops `shutdown`/`server_close`. Only literal
`127.0.0.1` and `::1` bindings are accepted. This standard-library server must not
be exposed as the production sync service.

## Routes

| Request | JSON body | Success body |
|---|---|---|
| `POST /v1/push` | `{"operation": <private operation envelope>}` | One reference-service event |
| `POST /v1/pull` | `{"after": 0, "limit": 100}` | A contiguous array of events after the cursor |

Both require `Authorization: Bearer <device token>`, an explicit content length
and JSON media type. Enrollment and revocation remain trusted administrative
Python calls; there are no HTTP endpoints for them. Workspace/device authorization
is enforced by `ReferenceService` for every operation.

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
