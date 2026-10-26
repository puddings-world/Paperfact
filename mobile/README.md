# Paperfact mobile reader

Dependency-free PWA implementation for the private v0.5 development protocol.
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
