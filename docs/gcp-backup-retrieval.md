# Retrieve a private GCS authority backup

Status: local v0.5 operator implementation. No live GCP request, credentials,
resource, upload, installed-device journey or cloud restore has been exercised.
This is disaster-recovery preparation, separate from ordinary workspace sync.

Use the [headless operator setup](gcp-backup-publication.md), then choose the exact
`snapshot_sha256` returned by publication. The command does not list backups or
silently choose the latest one. Use a trusted retained receipt, not an arbitrary
shared research-package link.

```sh
.venv-sync/bin/python -m paper_daily sync-admin download-backup --bucket REPLACE_WITH_PRIVATE_BUCKET --snapshot REPLACE_WITH_MANIFEST_SHA256 --output "$HOME/.paperfact-sync/retrieved-backup" --seconds 300
```

On Windows use `.\.venv-sync\Scripts\python.exe`. The parent directory must
already exist; output must be a new unused path. Uppercase placeholders deliberately
fail validation until replaced. Use separately approved operator ADC and bucket
access. This command neither logs in nor provisions anything.

Success prints one JSON receipt with `state=downloaded_verified`, exact
`snapshot_sha256`, logical `files` and `bytes`, and `restored=false`. It never
activates a service or imports a desktop workspace. After download, run the normal
[verify and fresh-workspace recovery](sync-authority-backup.md) commands. Recovery
requires a fresh workspace ID and explicit new device enrollment; old client
cursors and old tokens cannot silently reconnect to rolled-back state.

| Flag | Meaning |
|---|---|
| `--bucket NAME` | Required existing approved private bucket |
| `--snapshot SHA256` | Required lowercase 64-character completion-manifest digest |
| `--output DIRECTORY` | Required new private backup directory; parent must exist |
| `--prefix PREFIX` | Default `paperfact/authority-backups`, same as publication |
| `--seconds NUMBER` | Default 300; positive and at most 300, cooperative budget |
| `--max-bytes NUMBER` | Default/hard maximum 17179869184 (16 GiB), positive integer; sum of declared payload sizes |
| `--help` | Offline usage with no state or account access |

## Verification and failure behavior

- Require explicitly enforced public-access prevention and uniform bucket access,
  before retrieving private contents and before marking the output complete.
- Fetch the exact bounded manifest, pin object generations and use raw ranged
  downloads. Reject overlong or short range responses. Independently check full
  SHA-256 and CRC32C, including when the SDK cannot checksum a ranged response.
- Validate the manifest's closed schema, allowed relative paths, duplicates,
  file count and total byte budget before creating output or downloading payloads.
  SHA metadata alone never proves the actual downloaded bytes.
- Write exclusive private files, retain `.manifest.pending` until the ordinary
  authority verifier checks SQLite integrity, event/receipt/source coverage and
  all committed attachments. Recheck remote generations and local identities,
  synchronize files/directories, then rename the completion marker last.
- Failures return 2 with bounded guidance. Partial output is retained for operator
  inspection, without `manifest.json`. The public verifier refuses that directory.
  Retry into a new output path; there is no partial-directory resume or deletion.
- The cloud may become unavailable after a successful download; a locally verified
  backup remains independent. No remote object is overwritten, deleted or granted
  to a desktop workspace by this operation.

Public Python operator API:

```python
fetch(bucket_name, snapshot_sha256, output, *,
      prefix="paperfact/authority-backups", seconds=300,
      max_bytes=17179869184, cancelled=lambda: False,
      progress=lambda value: None, client=None) -> dict
```

`client` is an internal test seam, not public endpoint selection. Progress callbacks
receive categorical stages/counts without research or credentials. The CLI prints
only its final receipt or bounded error. Calls use bounded SDK retry/request options;
credential discovery and an active request can outlast cooperative cancellation.
This is not a sandbox against a malicious same-user process replacing local paths,
a cryptographically signed backup, end-to-end encryption, a retention policy,
an unattended restore, or a recovery-time guarantee.

See the [scenario map](testing/gcs-fetch-scenarios.md) for exact local evidence and
remaining gates. SDK semantics were checked against the installed 3.17.1 API and
[official Blob download documentation](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob).
