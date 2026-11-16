# Reference sync HTTP adapter

Status: local v0.5 integration boundary, not a public hosting solution.

`make_server(service, host="127.0.0.1", port=0, *, browser=None,
allow_unverified_mutations=True)` returns a `ThreadingHTTPServer`.
This low-level reference API retains local prototype compatibility. The official
`sync-admin serve` entry always passes `allow_unverified_mutations=False`; hosted
integrators must do the same. There is no CLI bypass flag. See
[verified-only service policy](#verified-only-service-policy).
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
[Operator commands](sync-service-admin.md#enable-browser-pairing-explicitly) now
create a private versioned key file and enable the adapter with paired serve flags.
There is no built-in key or automatic startup rotation. The
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

The [mobile pairing/reconnect/forget screen](mobile-0.5.md#browser-pairing-and-offline-reconnection)
now uses this adapter through the existing guarded workspace adoption path. Actual
Chromium cookies, IndexedDB and offline reload pass locally. Operator key creation
and explicit serve loading are now implemented and restart-tested. Remaining:
same-origin HTTPS/static hosting, platform key permissions and physical
iOS/Android acceptance. Opening existing cached
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

A proxy HTTP 429 is now a temporary/retry condition: Python raises a sanitized
ConnectionError and the mobile transport reports `rate_limited`, preserving
existing outboxes and exact pairing identity. Neither client echoes an upstream
body or starts a hidden retry loop. The [review-only HTTPS handoff](sync-service-admin.md#same-origin-https-proxy-handoff)
uses that status for provisional rate/connection limits; live proxy acceptance is
still required.


### Unavailable retained history

An authenticated pull whose cursor is ahead of the authority returns HTTP 412
with only `{"error":"sync_history_unavailable"}`. No sequence count, operation,
workspace content or exception text is exposed. Authentication still runs first.
`HttpTransport.pull` maps this to `SyncHistoryUnavailable`; other endpoint errors
retain their existing meanings (including attachment HTTP 409). Mobile maps 412
only on pull to the same preservation guidance. The client-side retained-event
check also rejects an empty or different frontier before upload; see
[the client contract](sync-client.md#verify-retained-history-before-upload).


## Execution continuity during a transfer

`POST /v1/session/info` validates the device credential and returns the existing
closed workspace/device JSON plus `X-Paperfact-Sync-Instance`, one lowercase
32-hex opaque value generated when `make_server` creates the listener. It is not
a credential, workspace identity, stored journal field or persistent history epoch.

Updated Python/mobile transports validate payload bounds before any handshake,
validate the authenticated identity, and pin the value for that transport/session.
All subsequent research, attachment and device requests carry the exact header.
The receiver authenticates first, then requires the guard before calling a service
mutation/read; missing or changed guards return HTTP 428 with the closed body
`{"error":"sync_session_changed"}`. Malformed/duplicate guards are rejected.
Bootstrap identity, invitation redemption and browser pairing/forget routes are
exempt because a device is not yet connected or is explicitly forgetting access.
No CORS grant, anonymous research route or new authorization is introduced.

A changed, missing, malformed or duplicate response offer cannot silently replace
a pin. `session_info` on an unsupported old service cannot authorize later research
requests. Python creates a fresh transport to reconnect; mobile's explicit
`begin_session()` clears only its in-memory pin and increments a delivery generation.
`Engine.connect` invokes it before identity checking. Late responses from a prior
generation cannot pin an old execution. Cookie transport carries the same guard
without exposing its HttpOnly credential to JavaScript. Application history checks
still run before upload after reconnect. No cursor/outbox reset or operation replay.

Old 0.5 development peers must update the client, static PWA and service together;
headerless research requests are intentionally refused. Missing handshake support
is distinct from malformed JSON; low-level blob/pairing methods preserve their
typed unsupported-capability errors. Existing authorization, quota, rate-limit and
blob-unavailable errors retain their meanings. Proxies must preserve this header
in both directions; removing it fails rather than downgrading to unguarded writes.

This fences acceptance by a restarted/replaced HTTP listener. It is not a complete
persistent authority-generation/compatibility protocol, history commitment,
split-brain lease or protection against unsupported in-place DB rollback inside
a live process. HTTP can already have transmitted buffered request bytes before
a rejection; this is not a confidentiality guarantee. Private TLS deployment,
operator restore policy, durable history proofs and physical-device acceptance
remain separate release gates. Never overwrite a running authority database.

## Durable authority history commitments (backend foundation)

Source after candidate c1cbef2 connects durable history to the actual desktop
SyncSession and authenticated bounded HTTP transport. The delivered c1cbef2 app
and mobile v29 still use their earlier frontier/execution protocol. Current source
adds mobile proof persistence and transaction-bound attachment guards below.
Device-control and invitation guards are documented below. This is not durable
split-brain fencing, malicious-authority protection or installed/hosted acceptance.
No new server or daemon is added; this is a version1 proof subprotocol alongside
existing operation-envelope versions.

`ReferenceService` exposes:

| Method | Result and bound |
|---|---|
| `history_page(token, after=0, limit=100, *, checkpoint=None)` | Version1, authenticated workspace, starting checkpoint, exact canonical event strings, ending checkpoint and caught_up. At most 1000 events and 2 MiB of compact UTF-8 response, with bounded individual records. |
| `prepare_history(token, *, limit=100)` | Explicit legacy backfill; version1/workspace/checkpoint/ready/remaining_events. At most 1000 events and 2 MiB of raw event text per transaction. |
| `push_verified(token, operation, *, checkpoint)` | Exact canonical acknowledgment `record` plus its `checkpoint`, committed with the accepted/conflicted event. Requires the observed tip for a new write; an identical retry remains idempotent. |

A checkpoint is exactly `{sequence: nonnegative_integer, sha256: lowercase_hex64}`.
Cursors are bounded by SQLite signed 64-bit integer range.
The initial seed is SHA-256 of UTF-8 `paperfact.sync-history.v1`, one zero byte,
then the authenticated workspace ID. For each exact canonical event text:

```text
next_hash = SHA256(previous_32_bytes + unsigned_8_byte_big_endian_UTF8_length + UTF8_event)
```

Event strings preserve the authority's original Unicode and number representation;
a receiver must hash the supplied bytes, not parse/re-serialize through its own
number formatter. It must separately validate event semantics. Each positive
sequence commitment is retained in `sync_history`, in the same SQLite transaction
as the accepted/conflicted event, head and graph. A commitment failure rolls back
the write; identical retries create no second event or commitment. Workspace-scoped
seeds prevent reusing a proof after an explicit fresh-workspace recovery.

Continue with the exact preceding page's checkpoint. Nonzero cursors without a
retained checkpoint, different proofs, missing records, corrupt event text and
unprepared history fail closed. The page recomputes only its own bounded event
range against stored commitments. It does not scan all preceding records per
request. A proof is integrity/continuity metadata, never authentication or a grant
to another workspace. Existing per-request device authentication remains required.

Newly created histories receive commitments as they are written. For a pre-existing
service, construction creates the optional table but does not scan old history.
Its original API remains available until an operator explicitly starts preparing
that workspace. Coordinate a maintenance window before the first preparation
batch: partial preparation blocks new event writes until subsequent batches finish.
Retries continue from the stored prefix without rewriting research events. Other
workspaces have independent prefixes. This phase offers a Python operator seam;
a reviewed CLI/admin flow and active client negotiation remain to be implemented.

Authority backups verify every stored commitment against the retained event prefix,
reject gaps/orphans/different hashes without repairing the source, and preserve
legacy/unprepared prefixes. Recovery into a new workspace replays events and builds
new scoped commitments; it does not copy old sessions or proof authority.
These checks do not protect against a malicious authority, unchecked database
replacement, forged metadata, an in-place restore or two active service forks.
Desktop event/ack proof persistence and transaction-bound research pushes are
implemented below, followed by mobile proof persistence and attachment guards.
Durable authority identity/fencing and installed/hosted
acceptance remain gates.

### Verified desktop flow and wire contract

| Route | Closed request | Success |
|---|---|---|
| `POST /v1/history/pull` | `after`, `limit`, `checkpoint` | The closed history page above; at most four records and 2 MiB per HTTP response. |
| `POST /v1/history/push` | `operation`, `checkpoint` | `{record: canonical_event_text, checkpoint: {sequence, sha256}}`. The record is an exact string, not a receiver-reserialized object. |

Both bearer and same-origin browser route mappings use the existing authentication,
execution pin, strict JSON and request/response caps. The mobile engine now
requires these routes too. `HttpTransport.history_page(token, after=0, limit=100,
*, checkpoint)` and `push_verified(token, operation, *, checkpoint)` never retry
through legacy routes when support is missing. Missing support or an invalid
prefix stops with `SyncHistoryUnavailable`. HTTP425 reports a genuine concurrent
advance as `SyncHistoryAdvanced` (a retryable connection error), preserving work.

`SyncClient.sync_verified_once(transport, token, *, limit=100, prepare_push=None)`
is now used by the actual desktop SyncSession. The original `sync_once` remains
an explicitly legacy experiment API and is not a production fallback. A verified
pass performs bounded local-inbox proof preparation, receives remote records before
pushing, then sends unchanged observed operations with the latest verified anchor.
Remote reception does not rebase a pending edit. Competing edits retain conflicts.

For a new write, the authority checks prefix equality and unchanged tip inside the
same write transaction as event/head/graph/hash publication. A concurrent valid
writer causes a retry before the second operation is accepted. Every new
acknowledgment is then the next event, so the client can independently hash the
exact record from its anchor before storing it. It refuses malformed, skipped or
incorrect acknowledgment proofs instead of persisting an opaque higher digest.

`paperfact_sync_history_checkpoint` retains both received and acknowledged prefixes.
`receive_history(page)` validates all raw records and intermediate hashes, then
stores research/inbox/cursor/received proof together. Received matching local
intents are acknowledged in that same transaction, repairing a lost push response
without another upload. Acknowledgment and its proof use one journal transaction;
SQL/storage failure rolls back both. Binding/generation checks and existing single
job guards remain. Missing/corrupt pages do not advance research or discard outbox.
A page claiming caught_up must reach every retained acknowledgment. An older
empty or partial tail is rejected before any receive writes, even if preflight
proved that acknowledgment earlier in the pass. A valid subsequent retry remains
possible without discarding the accepted local content or its pending receipt.

An existing inbox starts proof preparation at zero, compares every bounded page
against actual retained local events and persists only the matched prefix. It
never initializes a higher checkpoint from an unverified remote digest. Incomplete
preparation returns history_preparing/history_remaining, keeps new work queued,
leaves last-success unchanged and does not claim caught_up. The existing connection
progress area shows remaining records, without a fabricated percentage or ETA.
A legacy acknowledgment beyond the received cursor without a retained proof stops
for explicit history review; that review/adoption UI is still a release gate.

Recovery archives retain checkpoint rows as inactive protocol records. Received
proofs are checked against the retained inbox; unreceived acknowledgment hashes
remain retained observations with matching original outgoing receipts. Detached
restore stores these in recovery_records, never as an active connection or device
permission. Research, pending operations, original observed proofs and source data
remain available for explicit recovery. No login, model call or upload is implied.

### Mobile verified flow and private recovery

Shell v30 uses `HttpTransport.history_page(token, after, limit, checkpoint, signal)`
and `push_verified(token, operation, checkpoint, signal)`, inherited by the existing
browser-cookie adapters. Unsupported proof routes stop synchronization; no legacy
write fallback is attempted. Existing single-event frontier checks are additional
semantic guards, not a substitute for the linked prefix proof.

`Engine.sync()` keeps the zero seed virtual until a verified transaction commits.
Legacy inbox preparation compares each bounded page to actual retained full event
receipts; it never installs an opaque higher remote hash. Legacy receipts retained
JavaScript numbers, not original numeric lexemes; their migration comparison is
semantic. New proofs always hash the exact canonical UTF-8 event strings, including
Python float spelling. Unsafe integer sequences are refused, never rounded.

The foreground pass shares a 25-page budget across preparation and reception,
receives before uploading, and reports remaining work instead of false completion.
Every new acknowledgment must be the next independently hashed event from the
observed anchor. A concurrent writer returns sync_history_advanced and leaves local
work available for retry. Received notes/receipts/cursor/proof and acknowledged
outbox/proof each commit atomically in the same workspace/device IndexedDB record.
A failed storage write or a late signed-out response cannot partially apply them.

Private recovery exports with proof observations use format version3 and required
capabilities reading_position/sync_history. They retain both received and newer
unreceived acknowledgment points and the original acknowledged outgoing event.
Imports keep these only inside inactive positionRecoveries archives; they cannot
set an active cursor/proof, enqueue old operations or connect an archived device.
Re-export also retains the current device's proof observations. Historical v1/v2
exports remain unchanged when no proof observations exist; v2 import remains valid.
Older importers must reject v3 instead of silently discarding proof metadata.

Validated on isolated Windows Chromium and loopback Python fixtures. This does not
establish physical Safari durability, native installed-device convergence, hosted
access or durable authority/device-control history fencing.
The delivered c1cbef2/v29 candidate has not been rebuilt for this source.


### Attachment history guards

Actual desktop SyncSession uploads and mobile original-source uploads use these
additional authenticated bearer/browser-cookie routes. No route fallback occurs
when a verified endpoint is unsupported. They require the existing execution pin
and the same closed checkpoint as verified research writes.

| Route | Closed request fields |
|---|---|
| `POST /v1/history/blobs/begin` | sha256, size, checkpoint |
| `POST /v1/history/blobs/append` | upload_id, offset, data (bounded base64), checkpoint |
| `POST /v1/history/blobs/commit` | upload_id, checkpoint |
| `POST /v1/history/blobs/cancel` | upload_id, checkpoint |

Python HttpTransport and reference blob_begin/append/commit/cancel accept an
optional keyword-only checkpoint. Supplying it selects the verified route and
requires a matching retained prefix inside every authority mutation transaction.
Concurrent valid suffix growth does not invalidate an existing prefix or require
re-uploading immutable bytes. The direct legacy APIs remain experiment seams;
the production desktop session supplies its current received/acknowledged point.

Begin checks before namespace persistence and again before upload reservation.
Append/cancel check before changing partial bytes/session state. Commit checks
before physical finalization and again inside the final ownership transaction.
If history changes during bounded verification, bytes may already exist privately,
but they remain unowned/unreadable until a valid explicit retry completes ownership.
History proof never replaces device authorization, quota, digest or file-identity
checks; it does not retract bytes already transmitted.

Mobile Engine.historyCheckpoint(generation) returns a copied higher retained point
only after received-prefix preparation reaches the local cursor. Its original-source
uploader receives that checkpoint explicitly and sends it on begin/append/commit.
Unrelated downloads remain independently usable. Device guards are described below;
durable authority fencing and installed/hosted acceptance remain separate gates.
The delivered c1cbef2 candidate and the earlier local v30 static artifact are unchanged;
these source changes require a matching future client/service/static deployment.


### Device controls and issuer-bound invitations

Actual desktop DeviceClient.rename/revoke/create_pairing pass the local
SyncClient.mutation_checkpoint() through the existing authenticated device context.
That read-only method requires the received proof to reach the cursor and the
retained acknowledgment to cover known unreceived acceptance. It neither syncs
research implicitly nor writes protocol state. Unprepared/legacy evidence stops
with guidance to preserve work and explicitly synchronize/review history.

| Route | Closed request fields |
|---|---|
| `POST /v1/history/devices/rename` | device_id, label, checkpoint |
| `POST /v1/history/devices/revoke` | device_id, checkpoint |
| `POST /v1/history/devices/pairing/create` | code, checkpoint |

HttpTransport/reference rename_device, revoke_peer and create_pairing accept the
optional keyword-only checkpoint. Supplying it requires the verified route and
checks the retained prefix in the authority write transaction. There is no fallback
to legacy control routes. Catalog reads and local Disconnect remain independent.

New verified invitations retain a bounded canonical history_checkpoint in the
existing sync_pairings row. Issuance retries preserve the original point and expiry,
even after a valid suffix advance; a legacy unproven invitation requires a fresh
code instead of being silently upgraded. Scope/issuer ownership is checked before
reading an existing invitation's proof. Fresh redeem_pairing and its exact claim
retries verify the issued prefix inside the transaction that admits the new device.
A mismatch leaves the code unclaimed and creates no credential; valid recovery can
retry the same code. Invitation packets/responses contain no additional credentials
or internal proof metadata. Browser completion uses the same admission boundary.
An already admitted credential still follows existing resume/expiry/revocation
semantics; research synchronization checks the client's own retained history.

SyncClient.prepare_history_checkpoint() is called only by explicit desktop sync.
It initializes a genuinely absent legacy proof table at the local zero seed, then
the existing bounded preparation compares actual inbox records before upload.
An existing table with missing/corrupt evidence is refused, never reset. Device
controls remain read-only even on an old schema; the suggested sync/retry path is
verified with a real legacy acknowledgment and retained inbox. This does not
silently adopt unreceived legacy acknowledgments that lack sufficient evidence.

Authority recovery accepts old seven-column and current proof-bearing invitation
schemas, as well as pre-pairing backups. It carries no device grants or invitations
into the new workspace. Existing old direct experiment APIs remain available;
guarded clients do not downgrade to them. Production compatibility policy must
refuse obsolete prototype writers when the host is hardened for release.

These are research-prefix checks, not a journal/version proof of every control
change. A rollback that preserves the research prefix can still undo device state;
durable authority identity, control-history continuity and split-brain fencing
remain release gates. No deployment, installed device or physical-phone acceptance
is implied by local bearer/cookie/Qt fixtures. New mobile shell v31 supplies matching
bilingual history-refusal guidance and discards old static shells without touching
research caches. The delivered native/v29 candidate remains unchanged.


## Local listener ownership and database lifetime

The reference HTTP service acquires an OS-backed local claim before binding its
socket. A second cooperating listener for the same canonical database is refused.
Failed bind releases the claim. Closing stops admission, interrupts protocol
sockets, and retains the claim until admitted backend work has drained. An accepted
write whose reply was interrupted remains retryable with the same operation ID.
Incomplete HTTP headers cannot keep the listener alive solely by retaining a socket.
The implementation uses documented [socket detach/close semantics](https://docs.python.org/3.11/library/socket.html#socket.socket.detach);
prompt interruption is locally verified on Windows, not yet on installed Mac/Linux.

The existing `.research-jobs` lock sidecar is process coordination, not replicated
research or proof that a process is currently alive. Never unlink it to bypass an
active service. Process exit releases OS ownership without deleting the sidecar.
Trusted administration and online backups remain possible; this claim does not
exclude every direct SQL writer.

Each initialized reference service pins its absolute database path and positive
native file identity, requires a regular single-link file, and rechecks the identity
around connection, transaction and commit. Existing connections use SQLite URI
`mode=rw`: a missing authority is refused rather than recreated as an empty database.
Ordinary replacement/removal produces HTTP 412 and recovery guidance, including on
session reads. Normal SQLite writes retain their file lifetime.

These are same-host cooperating-listener and observed-file-lifetime safeguards.
They do not authenticate database content, detect all same-inode SQL restores or
filesystem ABA, fence another host/copy, or prove durable device-control history.
Durable authority epochs, anti-rollback and distributed fencing remain release gates.
No installed-device, hosted or physical-phone acceptance is implied.


## Verified-only service policy

Source after897cd7a hardens the official `sync-admin serve` entry. Authentication,
workspace/device ownership and execution checks still run before mutation policy.
The following unverified POST routes return sanitized HTTP412 without invoking
the mutation, changing SQL or allocating transfer state:

- `/v1/push`;
- `/v1/blobs/begin`, `/append`, `/commit`, `/cancel`;
- `/v1/devices/rename`, `/revoke`, `/pairing/create`.

Use the existing `/v1/history/...` equivalents with a retained checkpoint.
The policy applies equally to `/v1/browser/...` cookie routes after normalization.
Authenticated session info, device catalog, legacy contiguous-event reads,
verified-history reads and blob reads remain available for preservation/review.
Successful guarded retry still returns the original result once.

Native pairing redemption and fresh browser completion also require the stored
invitation's issuer-history checkpoint in the enrollment transaction. An old
unbound invitation is refused without claiming it or creating a credential;
issue a new code through the verified route. An already authenticated browser
credential can resume without minting a new device. This does not restore a
revoked credential. Bootstrap, CSRF/origin, tab identity and cookie-storage rules
remain unchanged; no JavaScript credential or proof payload is added to cookies.

The low-level local reference factory's compatibility default remains for existing
explicit experiments; it is not the official service policy. Historical fixtures
may request `allow_unverified_mutations=True`. It does not turn the reference
server into a public TLS host or authorize production prototype writers.
Guarded desktop/PWA clients do not downgrade when a required route is missing.

These checks close official unverified-mutation entry points; they are not a
durable authority/control-state journal, independent anti-rollback anchor or
cross-host fencing lease. Supported backup restore still uses a fresh workspace
identity and new grants. Raw database/disk rollback remains unsupported.

The trusted adapter policy parameters are
`sync_device_protocol.request(service, path, token, value, *, require_history=False)`,
`BrowserSessions.complete(value, cookie, *, require_history=False)` and
`redeem_pairing(code, workspace_id, device_id, credential, label=None, *, require_history=False)`.
Strict HTTP selects them internally; JSON bodies cannot override receiver policy.

### Official authority lifetime and transactional control history

Current source (after the e26ec8f native candidate) initializes
`paperfact-reference-service-v4` in `.paperfact-sync-service.json`. Its exact native
`database_identity` and `control_sha256` bind actual device/pairing state to a fresh
authority UUID, dense history sequence and validated chain head. Marker JSON is
bounded, closed and duplicate-safe. `sync-admin`
carries the native pin into the pre-schema constructor check; replacement, missing
files, invalid control schemas and changed control state are refused on restart.
`init` never repairs or rewrites mismatched state.

`sync_control_history` stores canonical `paperfact.authority-control-event.v1`
records: authority UUID, sequence/previous hash, UTC observation time, before/after
state hashes and sorted closed row deltas. Issuance, revocation, labels and pairing
creation/claim/removal commit history in the same SQL transaction as controls.
Reads and unchanged intent add no events. Verification replays the complete chain
and compares it to actual controls. Even coherently rewritten history fails the
retained marker commitment. No plaintext tokens/pairing codes are recorded; hashes
and past labels remain sensitive private metadata, not anonymous telemetry.

Internal APIs take explicit SQLite connections: `snapshot(conn)` reads bounded
controls; `read(conn, *, check=lambda: None)` verifies/replays the history and
returns private authority ID/sequence/head/state; `initialize(conn)` creates a
fresh baseline in the caller's write transaction; `append(conn, before)` records
actual deltas in that same transaction, using the observed `read` result as its
baseline and refusing any replacement of that prefix. These functions live in
`sync_authority_history`; `sync_authority_control.fingerprint(conn)` binds their
verified state/history to the marker. Cooperative cancellation keeps its caller
signal. No research package, device-catalog response or public diagnostic includes
the private journal.

Limits are10,000 events,8 MiB per event,64 MiB total journal,10,000 current control
rows and8 MiB encoded state. Validation is bounded and linear in retained history;
large-history throughput is not certified. Capacity failures reject the new
mutation and preserve committed access. Back up and review fresh-identity recovery,
not history deletion.

Official transactions serialize through a bounded cooperating-process local lock.
They compare the retained checkpoint before use. A control mutation publishes and
flushes the new marker before committing SQLite. Failure before publication rolls
back controls and history together; process loss after publication and before SQL
commit leaves an explicit
mismatch and pauses access/backup. Preserve both files and review recovery into a
fresh service/workspace; do not repair the marker or revive old credentials.
A synthetic subprocess-exit test covers this window, not real power-loss durability.
Read transactions retain SQLite read semantics, including backup compatibility.

Legacy v1/v2/v3 markers are backup-only, never serving or issuing credentials.
Legacy v3 backup still verifies its actual control-state digest. Current backups
verify complete history/state under the SQL reservation and preserve the exact
journal. Fresh restore keeps old history in the unchanged source backup, identified
by recovery provenance, discards old grants and creates a new authority/history
baseline. Research, HTTP and backup formats are unchanged; no automatic migration
or client cursor reset is added.
Bare `ReferenceService` remains a trusted prototype; official entry enables guards.

This detects same-file control/history rollback while the current local marker is
retained. It is not an independent external anchor, distributed lease, protection
against jointly restored marker/database or copied hosts by itself. The next
section adds device-retained prefixes. Independent external anchoring, ambiguous
external commits, cross-host fencing, hosted restore and physical acceptance
remain release gates. File identity changes require recovery
review, not automatic repinning. Existing downloadable native candidates contain
v3 administration; this source-only v4 work is not a new installer or deployment.


### Device-retained authority control checkpoints

Official v4 responses advertise `X-Paperfact-Control-History: 1`. After verifying
`POST /v1/session/info`, clients call `POST /v1/control/checkpoint` with the closed
body `{"checkpoint": null}` on first use, or their previously retained point.
The authenticated response is the closed object `version: 1`, `identity` (the same
workspace/device), `accepted` (the exact submitted point), and `checkpoint`.
Each point has exactly `authority_id` (canonical UUID), `sequence` (integer1..10,000)
and `sha256` (64 lowercase hex digits). A known prefix must exist at its exact
sequence and digest in the current authority. A new head cannot change authority,
move backwards or change the digest at the same sequence.

Later official private requests include `X-Paperfact-Control-Checkpoint`: unpadded
base64url of compact UTF-8 JSON for that point, with fields in authority/sequence/hash
order. The receiver validates a single canonical header of at most512 characters.
Missing required guards return428; malformed/duplicate guards return400; unavailable
history returns412. First-use checkpoint challenges may omit this header; when
present it is checked too, alongside the body's prefix. Identity and pairing-redemption
routes remain bootstrap exceptions; credentials and research-history checks still
apply. Browser-cookie routes use the equivalent `/v1/browser/control/checkpoint`.
Proxies must preserve both control headers and the existing execution header.

Crucially, the prefix is checked inside the actual service transaction, not only
in earlier authentication. A rollback between authentication and the private read
is rejected. This guard covers control and research/file routes without making a
process nonce an authority history. Older clients without this handshake cannot
use an official v4 private route; update client/service together. The unmarked
`ReferenceService` remains a prototype compatibility seam, never a downgrade once
a device has retained control knowledge.

Desktop `SyncSession.connect` and each authorized job bind `ControlKnowledge` to
the exact workspace file/session and expected remote workspace/device. It stores
only the small closed `paperfact.device-control-knowledge.v1` record under a hashed
`ui.sync.control.*` key, excluded from research capture/sharing. Loads are bounded
to2 KiB. Writes use an immediate SQLite transaction, monotonic compare-and-swap,
capture-aware connection and live-session checks; failed/cancelled writes preserve
the prior point. Joining retains the point in the staging and published databases;
resumption challenges that stage prefix in addition to the source connection's
prefix. Tokens never enter this metadata.

Mobile `Engine.connect` binds equivalent scope-checked callbacks. `IndexedStore`
uses a separate `control:<scopeKey>` record in the existing `scopes` object store,
so per-request checks do not clone PDFs, drafts or the research cache. Control
writes use one IndexedDB compare-and-swap transaction. Research/outbox/cache export
stays separate. Existing offline research remains readable without connecting;
failed continuity leaves that research and pending work intact. Browser storage
clearance removes local knowledge and must not be described as verified recovery.

| Internal API | Contract |
|---|---|
| `sync_authority_history.validate_checkpoint(value) -> dict` | Closed bounded point validation |
| `checkpoint(conn, expected=None) -> dict` | Verify complete control chain and optionally an exact retained prefix |
| `ReferenceService.control_session(token, checkpoint=None) -> dict` | Authenticate and challenge in the same guarded SQL transaction |
| `ReferenceService.control_execution(point)` | Request-local context checked by every actual official transaction |
| `HttpTransport.bind_control_checkpoint(load, remember, identity)` | Bind explicit device-local callbacks; `remember(point, previous)` must commit or raise |
| `HttpTransport.control_checkpoint() -> dict or None` | Copy the current authenticated in-memory point |
| `HttpTransport.check_control_checkpoint(token, observed) -> dict` | Verify an additional retained join prefix alongside current connection knowledge |
| `ControlKnowledge(path, identity, live).load()` / `.remember(point, previous)` | Scope-bound private native persistence with monotonic compare-and-swap |
| `IndexedStore.readControlCheckpoint()` / `.writeControlCheckpoint(point, previous)` | Small private metadata transactions; no research-cache copy |

Low-level transports without callbacks retain only process memory. Desktop sessions
and mobile engines provide persistence; there is no global account credential or
implicit upload consent. A retained client point detects a jointly rolled-back
server database/marker only while that client knowledge survives. Simultaneously
rolling back all client copies and the authority, a fork beyond a common observed
prefix, copied-host fencing and independent anchors still require further work.
[Recovery comparison](device-recovery-review.md#device-held-access-history-in-recovery-review)
now observes device-versus-backup control knowledge; explicit fresh-authority
restore/join has actual HTTP fixture coverage without rebinding the old outbox. This source is not in the linked native
installers and has not been deployed or physically accepted on Mac/phone.


The packaged protocol acceptance client independently encodes the same control
handshake and headers. It requires one advertised capability, verifies the exact
workspace/device and returned point, tests rejection of absent/forged control
knowledge, and carries the retained point through listener restart. Its previous
research-history, retry, duplicate-listener, prototype-write and stale-execution
checks remain. The receipt adds `control_history`, `missing_control_refused`,
`wrong_control_refused` and `control_history_restart` to the existing eleven flags.
An old test client omitting the new header is correctly refused; it must complete
the handshake rather than disable official guards. The existing source CI stage
runs its one normal real-CLI case before packaging to catch protocol drift early.
