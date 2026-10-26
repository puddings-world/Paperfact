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
certificate/ingress setup, abuse controls, browser session/CORS policy and attachment
transport are separate release gates. No CLI or app startup auto-launches this server.
