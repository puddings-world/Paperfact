# Paperfact mobile reader

Dependency-free PWA implementation for the private v0.5 development protocol.
Native Lineage cards offer exact-original PDF links, verified offline reading and
explicit download. Imported saved-report metadata alone grants no source bytes.
See [source-reading evidence and limits](../docs/testing/mobile-lineage-originals-candidate.md).
This directory is an isolated implementation slice, not a public sync deployment.

From the repository root:

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory mobile
```

Open `http://127.0.0.1:8000`. The initial workspace contains synthetic research.
It supports reading, local text notes, progress changes and an explicitly requested
sample PDF. Nothing connects to a research account or model automatically.
IndexedDB stores each workspace/device separately; the synthetic authority also
persists its test history separately so demo reloads retain accepted changes.

Node 22+ automated semantics, transport and static checks:

```sh
node mobile/check.mjs
```

**Parent full-check integration entry point:** invoke the same command with the
project's Python executable. It also starts an isolated temporary Python authority
and checks real HTTP service interoperability. No package installation is needed.

```sh
node mobile/check.mjs --python .venv/bin/python
# Windows
node mobile/check.mjs --python .venv/Scripts/python.exe
```

Actual Chromium/Edge IndexedDB and reader UI regression (explicit browser binary;
creates an isolated temporary browser profile, no real profile or credentials):

```sh
node mobile/browser-check.mjs /path/to/chromium
```

An optional second argument is a screenshot output directory. It captures desktop
and phone-sized reader views. Browser test routes are local fixture tools and
should be excluded from a future deployment artifact.

See [implementation and remaining gates](../docs/mobile-0.5.md). The reference
authority has no CORS grant or browser login endpoint. The developer connection
form does not bypass that boundary. Production pairing, browser authentication,
hosting and secure deployment remain required integration work.


Portable development read snapshots now retain complete saved Lineage metadata
and show it in bilingual, read-only overview cards. Unsupported clients refuse
the required capability before writes. Original snapshots are not current-byte or
scientific-verdict authority; these cards do not activate PDFs or call a model.
See the [format and API](../docs/sync-projection.md#saved-lineage-read-projection).


The development receiver also understands closed typed Lineage events with exact
paper/original-file lifetime pins. Source retirement and corpus tombstones
suppress stale cards while retaining scientific history; receipt alone grants no
PDF activation or scientific certification. This closes a consumer compatibility
gap, not the still-gated authority publication/enrollment path. See the
[event contract](../docs/sync-projection.md#mobile-lineage-event-consumer).

The [same-origin browser-session adapter](../docs/sync-http.md#same-origin-browser-adapter-development)
and `CookieTransport` now provide a local HttpOnly-cookie protocol foundation.
The Connection form now offers Pair and remember, Reconnect and confirmed Forget;
manual bearer setup is under Advanced. Browser persistence and offline reload are
verified in isolated Chromium. Operator signing-key creation/loading is now
[available explicitly](../docs/sync-service-admin.md#enable-browser-pairing-explicitly);
HTTPS/static deployment, platform permissions and physical phones remain open. The static preview above does not provision a service.
Shell v21 includes the pairing view; research caches are retained.

[User flow, API, browser-test command and exact limits](../docs/mobile-0.5.md#browser-pairing-and-offline-reconnection).

For hosting, use the [verified static artifact](../docs/sync-service-admin.md#build-and-verify-the-public-pwa-artifact),
not a recursive copy of this development directory. CI prepares one shared artifact;
it does not configure a host. The actual app pairing/offline checks can load
`public/` from that artifact using `PAPERFACT_TEST_ARTIFACT` and its trusted
`PAPERFACT_TEST_ARTIFACT_ID`. Shell v22 also makes HTTP 429 a busy/retry state.


Source after candidate c1cbef2 uses shell v30 and requires verified history on the
actual sync entry. The local IndexedDB transaction retains received and accepted
prefixes; private recovery v3 preserves them as inactive observations on import.
See [wire contract, migration and limits](../docs/sync-http.md#mobile-verified-flow-and-private-recovery).
The v29 delivered candidate is unchanged. Hosting and physical-device acceptance
remain pending; a successful loopback fixture is not a production deployment.


The existing engine module also exposes the shared fixture/protocol primitives:

| Function | Result |
|---|---|
| `historyPoint(value)` | Validate a closed safe-integer sequence/lowercase SHA-256 checkpoint; return it or throw. |
| `historySeed(workspace)` | Async native-compatible zero-prefix SHA-256 string. |
| `historyStep(previous, record)` | Async next SHA-256 over the previous digest, length and exact bounded UTF-8 record. |

These helpers do not authenticate a service or save research independently.


Actual original-source uploads also pass Engine.historyCheckpoint(generation) to
HttpTransport.uploadOriginalBody(token, payload, bytes, signal, checkpoint).
The matching service validates the retained prefix at begin/append/commit, including
its final ownership transaction. Unsupported verified routes preserve pending work;
see [attachment guards and remaining gates](../docs/sync-http.md#attachment-history-guards).
