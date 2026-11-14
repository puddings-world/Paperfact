# Reference sync service administration

These commands make isolated, self-host development tests reproducible. They do
not deploy a public service, issue Google/AI login or establish production identity.
The reference HTTP adapter binds only to literal loopback. A Mac cannot reach the
Windows machine through `127.0.0.1`; each machine's loopback points to itself.
A cross-machine pilot still needs a separately approved, authenticated HTTPS
service and device acceptance. Do not open a public HTTP port as a shortcut.

## Local setup

Run from an installed command environment or after the documented source setup.
Use a dedicated empty directory, separate from research and device credentials:

```sh
paperfact sync-admin init --state "$HOME/.paperfact-sync/service"
```

Success: `{"state":"initialized"}`. Repeating succeeds; an unrelated nonempty
folder is rejected. The marked directory contains authority SQLite state and
verified attachment storage, not the desktop research database.

Issue a new local test device and write its connection record outside that folder:

```sh
paperfact sync-admin issue --state "$HOME/.paperfact-sync/service" --endpoint http://127.0.0.1:8765 --workspace demo-workspace --device desktop-lab --output "$HOME/.paperfact-sync/desktop-connection.json"
```

Success: a JSON receipt with `state=enrolled` and the output filename. The token
is written only in the private file, not stdout. The record can be pasted into
the desktop's **Use connection details** flow, reviewed and explicitly verified.
Choose a different device ID and output file for each new device; never copy one
active device's identity into another installation.

Start the local service in a separate terminal:

```sh
paperfact sync-admin serve --state "$HOME/.paperfact-sync/service" --port 8765
```

Success: a JSON `state=serving` receipt with `url=http://127.0.0.1:8765`. Keep the
terminal running; Ctrl-C closes the listener. Existing local research remains
usable when it stops. The private file contains a credential: transfer only to
its intended device, keep it out of Git/issues/research packages and remove the
transport copy when no longer needed. Access from other programs running as the
same OS user is outside this file-permission boundary.

## Enable browser pairing explicitly

After initializing the dedicated service directory, create a separate signing key
outside it and outside research/Git. The parent directory must already exist:

```sh
paperfact sync-admin create-browser-key --output "$HOME/.paperfact-sync/operator-browser-key.json"
paperfact sync-admin serve --state "$HOME/.paperfact-sync/service" --port 8765 --browser-origin https://sync.example.org --browser-key-file "$HOME/.paperfact-sync/operator-browser-key.json"
```

```powershell
paperfact sync-admin create-browser-key --output "$env:USERPROFILE/.paperfact-sync/operator-browser-key.json"
paperfact sync-admin serve --state "$env:USERPROFILE/.paperfact-sync/service" --port 8765 --browser-origin https://sync.example.org --browser-key-file "$env:USERPROFILE/.paperfact-sync/operator-browser-key.json"
```

Replace the example domain with your reviewed same-origin HTTPS host. Successful
creation returns `state=created` and `key_file`, never the key. Repeating validates
the existing file and returns `already_exists` without rotating it. The serving
receipt adds `browser_origin`; the listener remains loopback-only. Without both
browser flags, browser routes are disabled. Supplying just one, an alias origin,
a missing/corrupt key or a key below authority state refuses startup before the
authority/listener opens. `--require-mount` still runs before either.

Serve the versioned PWA and `/v1/` through a separately reviewed same-origin TLS
proxy. These commands do not install that proxy, publish files, create GCP resources
or allow remote plain HTTP. Do not serve a Git checkout or the mobile test fixtures
as the production document root. Static artifact preparation, proxy limits and
hosted acceptance remain separate deployment gates. The review-only Linux unit
contains an optional browser invocation; no system service is installed here.

Keep the same private key across restarts. It is excluded from authority backup
and must remain outside research, packages, diagnostics and Git. POSIX loads require
a current-user-owned regular file with no group/other permission bits and one
hardlink. Symbolic links, junctions, oversized/ambiguous records and changed reads
are refused. On Windows, file creation inherits the selected directory's ACL;
this code does not certify or modify that ACL. Use an operator-private directory
and verify its ACL separately. No OS permission takeover is performed.

A failed write is unconfirmed and retained for review; an invalid existing file
is never overwritten. Use a new output path when needed. Replacing the configured
key logs out existing browser cookies after service restart; it does not revoke
devices or delete research. Authority disaster recovery requires fresh enrollment;
do not carry an old browser connection into a restored authority. There is no
automatic rotation, key recovery service or production secret-manager integration.

The file is closed JSON `paperfact.browser-signing-key.v1` with one `key`: exactly
32 random bytes in canonical base64url. `create_key(output)` returns a safe receipt;
`load_key(path)` returns private bytes only to the in-process adapter. Both APIs are
in `sync_browser_key.py`. The commit scanner rejects this record even if renamed,
without printing its contents. Conventional `*-browser-key.json` paths are ignored;
neither safeguard makes a checkout a private key store.

Seven behavior scenarios in `tests/test_sync_browser_key.py` cover stable creation
and receipts/backup exclusion, invalid existing files/hardlinks, the POSIX ownership
contract, changed-read refusal, fail-before-authority configuration, actual CLI
restart with the same pending cookie/device, and renamed-key privacy scanning.
On Windows the read-race fixture uses an allowed in-place update because replacing
an open file is refused by the OS. POSIX mode/rename and Windows ACL acceptance
remain platform-specific observations; simulated ownership checks are not a live
Linux/macOS result. Existing browser, bearer and mount regressions remain selected.

## Build and verify the public PWA artifact

Build once on a source/CI machine with the existing Node 22+ tooling. The service
host needs the resulting files, not Node or the Git checkout:

```sh
node scripts/build_mobile.mjs --output build/mobile-web
node scripts/build_mobile.mjs --verify build/mobile-web --expect TRUSTED_ARTIFACT_SHA256
```

Use the first command's actual `artifact_id` from a trusted build receipt for
`--expect`; the placeholder is deliberately unusable. Success is a JSON
`state=verified` receipt with version, content ID, file/byte counts and directory.
`--help` makes no changes. `--output` and `--verify` are mutually exclusive;
`--expect` is optional for local integrity inspection and requires `--verify`.
Without a trusted pin, verification checks integrity, not publisher authenticity.

```text
mobile-web/
  artifact.json             version, shell revision, hashes and content ID
  nginx-static-map.conf     generated approved static paths; default deny
  public/                   only runtime/service-worker assets and vendor license
```

The source of truth is the existing service-worker `SHELL` plus `sw.mjs`, not a
recursive directory copy. Test pages, test/service fixtures, Python, environment
files, research databases, issued credentials and signing keys are not copied.
The runtime `fixture.mjs` contains the intentional synthetic demo only. Known
private JSON record formats are refused even if substituted into a declared public
JSON asset. Symlinks/junctions, hardlinked files, path traversal, case-colliding or
nonportable names and oversized assets are refused. This is a bounded allowlist,
not a claim to detect every secret encoded in reviewed source code.

The output must be a new nonoverlapping directory; existing paths are never
replaced or cleaned up. Assets/maps are flushed before a completion manifest is
written. Source asset edits during staging leave an incomplete directory with no
manifest; retry at a new path. Verification is read-only, checks the content pin,
exact file inventory, file bytes and generated-map hash, and rejects extra files
or corruption without deleting/repairing them. Keep deployed release directories
read-only and retain the previous verified artifact for rollback. No command
switches a running host or migrates browser research.

Library APIs: `buildMobile({output, sourceRoot, version, onProgress})` and
`verifyMobile(directory, {expectedId})`, exported by `scripts/build_mobile.mjs`.
Defaults use the repo's mobile root and `__version__`; progress reports a staged
file count without file contents. Format `paperfact.mobile-artifact.v1` has limits
of 256 files, 16 MiB per asset and 64 MiB total. Builds over identical input bytes
are deterministic; different checkout line endings can legitimately change IDs.

The Release workflow runs the five focused artifact cases and builds/verifies
this shared artifact once (Windows job,
two-minute step budget) and uploads `mobile-web-<commit>`. It does not deploy it or
attach it implicitly to the native installer release. Download/unzip, independently
verify the expected content ID, then stage the unchanged directory through the
approved operator process. Workflow execution has not been observed here.

Five focused cases in `tests/test_mobile_artifact.mjs` protect reproducibility and
private-file exclusion, no-overwrite/excess-file refusal, interrupted build/new-path
retry, corrupt bytes/maps/wrong pins, and linked/private-JSON source refusal.
The existing browser acceptance harness can use an exported artifact instead of
source assets by setting `PAPERFACT_TEST_ARTIFACT` and `PAPERFACT_TEST_ARTIFACT_ID`
in addition to the [pairing fixture variables](mobile-0.5.md#focused-browser-acceptance).
Only the harness's two explicit test-entry files stay outside the artifact; the
actual app, worker/cache and runtime modules load from `public/`.

## Same-origin HTTPS proxy handoff

The [review-only Nginx template](../deploy/gcp/paperfact-nginx.conf.example) is an
`http {}`-context include. Adapt its approved domain, certificate paths and release
root; include the matching artifact's generated map. Serve only `public/`, never
research, the authority directory, signing keys, the repo or mobile test fixtures.
The Python service stays on loopback with the matching `--browser-origin`.

The template maps `/v1/` to the bounded authenticated adapter, preserves original
Origin/Cookie/Authorization/expected-device headers, allows static GET/HEAD and
API POST, and rejects undeclared static paths. It sets MIME types for ES modules,
no-store API responses, revalidated static shell, CSP/referrer/nosniff headers,
bounded headers/bodies/timeouts and provisional 20 requests/s, burst 40, eight
active API connections per IP. These are pilot starting limits, not measured
capacity; verify large bootstrap, shared-NAT devices and interrupted file transfers
before deployment. API throttles return 429: desktop treats it as a retryable
connection error; mobile keeps local work and reports a busy service, including
bilingual pairing feedback. No hidden retry loop or arbitrary progress estimate
is introduced.

Response disk buffering/cache and access logs are disabled. Error logs can still
contain operational IP/path data; choose their private retention separately. Static
and API cache headers are set at server scope so child add_header declarations do
not accidentally drop the security headers. No certificate issuance, firewall,
public DNS, Nginx installation, service reload or GCP permission change is performed.

**Unperformed deployment gates:** Linux `nginx -t` with the actual certificates and
artifact; HTTPS header/MIME and cookie persistence; native desktop plus browser
large-file/429/restart traffic; service-account permissions; external mobile and
Apple Silicon acceptance. Nginx is not available on this session's PATH. Template
source review and loopback/browser fixtures do not fill those results.

Directive references checked 2026-11-14: [map](https://nginx.org/en/docs/http/ngx_http_map_module.html),
[proxy buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[header inheritance](https://nginx.org/en/docs/http/ngx_http_headers_module.html),
[request limits](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html) and
[connection limits](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html).

## Command reference

| Command | Required options | Optional options | Outcome |
|---|---|---|---|
| `sync-admin init` | `--state DIRECTORY` | `--help` | Initialize or validate a dedicated reference authority |
| `sync-admin issue` | `--state DIRECTORY --endpoint URL --workspace ID --device ID --output FILE` | `--help` | Issue one new device and save its connection record |
| `sync-admin create-browser-key` | `--output FILE` | `--help` | Exclusively create or validate a private operator signing key; no authority needed |
| `sync-admin serve` | `--state DIRECTORY` | `--port INTEGER` (default 8765; 0 chooses an ephemeral test port), `--require-mount DIRECTORY`, paired `--browser-origin URL --browser-key-file FILE`, `--help` | Serve the reference protocol on 127.0.0.1; browser routes are opt-in |

All commands support `--help` without initializing service state. URLs use the
same HTTPS/literal-loopback policy as the desktop; remote plain HTTP, query tokens
and credential-bearing URLs are rejected. Device and workspace IDs use the
existing bounded protocol identifier format.

## Failure and retry

- Repeating issuance with the same valid output, endpoint and IDs validates the
  stored credential and returns `already_enrolled`; no second device is created.
- An unrelated, malformed, mismatched or revoked output is never overwritten.
  Review it and choose a new device identity/output when appropriate.
- Issuance writes, flushes and closes its exclusive output before committing enrollment.
  A normal write/flush/close failure rolls back the database change and attempts to
  remove only the file this operation created. A replaced output is not removed.
- Abrupt termination is not a distributed transaction: a crash before database
  commit may leave an unusable connection file. Review it explicitly. A complete
  valid file after commit can be retried. Do not claim universal crash atomicity.
- POSIX outputs are created with owner-only mode; Windows inherits the selected
  directory's ACL. Use a user-private directory. The command does not change ACLs
  of existing directories, rewrite research data or upload credentials.
- Errors return exit code 2 and a bounded explanation without echoing tokens.
  An interrupted listener exits 0 after closing its socket.

## Local API

`sync_admin.initialize(state) -> dict`, `authority(state) -> ReferenceService`,
`issue(state, endpoint, workspace, device, output) -> dict`,
`require_mount(state, mount) -> Path`, and
`main(argv=None) -> int` support the CLI. Paths are explicit; no research default
is selected. `ReferenceService.enroll(workspace_id, device_id, *, before_commit=None)`
retains its trusted-admin boundary. An optional callback receives the new token
inside the enrollment transaction; a callback failure rolls enrollment back.
It is not exposed as an HTTP enrollment endpoint.

## Remaining deployment gates

Production authentication/issuance/recovery, HTTPS hosting, origin policy,
retention/quotas and operator monitoring must be selected and verified before an
internet pilot. Existing defaults are a local reference configuration, not a
capacity or security promise for public hosting. Installed Windows/Mac and real
mobile device tests remain separate from loopback fixture checks.

Operator examples store private state/connection files outside the checkout.
Conventional `*-connection.json` files and local authority directories are ignored
by this repo. The privacy scan in every check profile also rejects complete version-1 connection
records containing credentials, even under another filename; it does not print
the credential. The explicit `REPLACE_WITH_NEW_DEVICE_TOKEN` placeholder and
empty templates are allowed. These guards do not make a Git checkout a private
credential store or detect every possible secret encoding.

## Reviewed deployment starting point (not installed)

The [GCP pilot proposal](gcp-sync-pilot-plan.md) includes an inert
[systemd template](../deploy/gcp/paperfact-sync.service.example). No command here
provisions a VM, formats a disk, creates users or enables a service.

For an approved Linux host, the operator must first mount the dedicated disk at
`/mnt/paperfact` using its approved UUID, install the pinned application at
`/opt/paperfact`, create the unprivileged `paperfact-sync` user, and explicitly
initialize `/mnt/paperfact/service` as that user. Review ownership and disk identity
before initialization; neither `serve` nor the unit initializes an authority.

The template adds mount dependencies, a read-only application tree, owner-only
file creation, bounded failure restarts and an interrupt-based stop. Its absolute
paths are example Linux server paths, not desktop data defaults. If the mount
path changes, update the mount unit name, dependencies, writable path and CLI
arguments together. Review the host's systemd version with `systemd-analyze verify`
on the adapted unit before installing it.

```sh
paperfact sync-admin serve --state /mnt/paperfact/service --require-mount /mnt/paperfact --port 8765
```

Success: the usual loopback-only `state=serving` receipt. A missing/unmounted
volume, relative mount path, state outside the volume or state equal to the mount
fails with exit code 2 before opening the authority/listener. An ordinary directory
is not sufficient even if a valid authority was accidentally left beneath it.
Restoring the correct mount permits an explicit retry. Existing local commands
without `--require-mount` retain their development behavior.

This startup guard uses the OS mount check. It does not authenticate the mounted
disk, hold a mount lock, detect storage failure during every request or provide
backup/recovery. The UUID-pinned host configuration, mount dependency, disk
monitoring and tested restore are separate requirements. systemd mount dependencies
and stop/restart semantics are described in the official
[unit manual](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
and [service manual](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
The unit has not been launched on Linux/GCP. Verify stop during an active transfer,
restart, disk absence, permission errors and reboot there before pilot acceptance.
It does not provide the TLS proxy or same-origin PWA hosting.


## Local authority backup commands

`sync-admin backup --state DIRECTORY --output NEW_DIRECTORY [--seconds 30]`
exports a bounded, consistent authority snapshot and verified committed objects.
`sync-admin verify-backup --output DIRECTORY [--seconds 30]` inspects it read-only.
Both support `--help`; the budget is positive and at most 300 seconds. Success
returns actual file/byte counts; failures return 2 without overwriting existing
output. A snapshot is private operator data, not a research package or live
restore. See [backup workflow/API/limits](sync-authority-backup.md), including the
writer pause, omitted partial transfers, fresh-path retry and remaining GCP gates.


## Isolated fresh-identity recovery

`sync-admin restore-backup --input BACKUP_DIRECTORY --state NEW_DIRECTORY
--workspace OLD_ID --as-workspace NEW_ID [--seconds 30]` reconstructs exactly one
selected backed-up workspace. All four path/ID options are required; the time
budget is positive and at most300 seconds. It supports `--help`, returns actual
counts and `requires_enrollment=true`, and never overwrites existing state or
starts a listener. Old credentials are not restored. See [exact recovery,
re-enrollment, Python API and limits](sync-authority-restore.md).


## Private GCS publication (source operator environment)

`sync-admin upload-backup --input DIRECTORY --bucket NAME [--prefix
paperfact/authority-backups] [--seconds 300] [--quiet]` publishes only a verified
authority snapshot, with create-only shared content and a completion manifest last.
Input/bucket are required; seconds must be positive and at most300. Offline
`--help` makes no cloud call. Use the independent locked operator setup and review
access before intentionally running it. [Workflow, API, failure/retry and gates](gcp-backup-publication.md).
No command provisions a bucket, changes IAM or configures a timer.

## Retrieve an exact cloud backup

`download-backup --bucket NAME --snapshot SHA256 --output NEW_DIRECTORY` retrieves one exact private authority backup. Optional `--prefix`, `--seconds` and `--max-bytes` bound the operation. See [complete flags, API and failure behavior](gcp-backup-retrieval.md). This does not restore a service or reconnect devices.

## Compare an old device with an authority backup

`review-device-backup --database FILE --input DIRECTORY --workspace ID [--seconds 30]` is a bounded read-only comparison, not device migration. See the [full CLI/API and desktop workflow](device-recovery-review.md). It does not use credentials, GCP, research contents in output or implicit database initialization.

Local operator checkpoint (2026-11-14): all 14 critical selectors plus affected
key/browser/admin/mount/privacy/documentation cases passed **53 Python cases in
11.55s**, **14.8s including privacy/Ruff**. The initial affected-only selection
passed 25 cases in 9.1s including checks; scopes overlap and are not additive.
Every process stayed inside the existing Windows 25% CPU/two-core/300-second
governor. No historical full, release matrix, POSIX host, real Windows ACL,
production key, GCP account or TLS deployment was tested or changed.

The validated-local evidence is explicit stable key loading before authority
startup, separate backup scope and format-aware non-echoing commit scanning.
This extends the project's existing private-output safeguards; no new global
skill or automatic provisioning rule was introduced.

Local static-artifact checkpoint (2026-11-14): **32 Python cases passed in 8.48s**,
**11.6s including privacy/Ruff** (all 14 critical selectors plus browser/throttle/docs).
Five affected artifact/mobile files passed **23 Node cases in 6.55s under the
governor**, including the five artifact scenarios. The actual exported public
assets passed **four Chromium pairing/offline/reconnect/forget journeys in 4.75s**;
the content pin verified separately in 0.23s. All used Windows 25% CPU/two logical
cores; no full historical suite or complete release profile ran. The new 429 test
initially supplied a consumed mock body; its fresh-stream fixture correction did
not change production stream checks or weaken assertions.

The inspected candidate has 50 public files, 3,911,049 bytes, version `0.5.0.dev`,
and content ID `5a6f81dc23460775653bdf2c864eaed1a85103e3c1a6b2569f2cd73290c3b470`.
That is a dated local content pin, not a published/signed release or a guarantee
about later builds. The CI step is source-reviewed but unexecuted; no YAML parser
or Nginx binary was available in this session. Live Linux config/TLS/permissions,
capacity/large-file traffic and installed/physical device acceptance remain open.

A final source/output containment review also covered child names beginning with
`..` that are not parent traversal. The five artifact scenarios passed again in
3.55s after that guard correction; unaffected mobile/browser evidence was reused.
TEMP cleanup is limited to each exact test-owned allocation after real-path and
file-identity checks, with no prefix enumeration or deletion of other sessions.
