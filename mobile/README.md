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
