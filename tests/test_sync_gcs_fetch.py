"""Private snapshot download with actual authority closure and simulated cloud."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from test_sync_authority_backup import state as state
from test_sync_gcs_backup import Blob, Client, crc
from test_sync_gcs_backup import snapshot as snapshot

from paper_daily import sync_admin
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_gcs_backup as publication
from paper_daily import sync_gcs_fetch as retrieval


class DownloadBlob(Blob):
    def download_to_file(
        self, stream, *, start, end, raw_download, if_generation_match, checksum, **_options
    ):
        assert raw_download is True and checksum is None
        self.bucket.hook("download", self, None)
        item = self.bucket.objects[self.name]
        if item["generation"] != if_generation_match:
            raise PreconditionFailed("Synthetic replaced object")
        body = item["body"][start : end + 1]
        self.bucket.hook("download_bytes", self, body)
        stream.write(body)
        self.bucket.calls.append(("download", self.name, start, end, if_generation_match))


@pytest.fixture(autouse=True)
def no_account(monkeypatch):
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    monkeypatch.setattr(storage, "Client", lambda *_a, **_k: pytest.fail("No ADC/client discovery"))


@pytest.fixture
def cloud(snapshot):
    client = Client()
    receipt = publication.publish(snapshot, "fixture-private-backups", client=client)
    client.storage.blob = lambda name, **_kwargs: DownloadBlob(client.storage, name)
    return SimpleNamespace(client=client, digest=receipt["snapshot_sha256"], snapshot=snapshot)


def fetch(cloud, output, **kwargs):
    return retrieval.fetch(
        "fixture-private-backups", cloud.digest, output, client=cloud.client, **kwargs
    )


def test_exact_download_is_verified_and_does_not_restore_or_change_remote(cloud, tmp_path):
    output = tmp_path / "recovered snapshot"
    remote = {key: dict(value) for key, value in cloud.client.storage.objects.items()}
    progress = []
    receipt = fetch(cloud, output, progress=progress.append)
    assert receipt["state"] == "downloaded_verified" and receipt["restored"] is False
    assert backup.verify(output)["files"] == receipt["files"] == 2
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()} == {
        p.relative_to(cloud.snapshot): p.read_bytes()
        for p in cloud.snapshot.rglob("*")
        if p.is_file()
    }
    assert not (output / retrieval.PENDING).exists()
    assert progress[-1]["stage"] == "verify_authority"
    assert cloud.client.storage.objects == remote and not cloud.client.closed
    with pytest.raises(ValueError, match="unused"):
        fetch(cloud, output)
    assert backup.verify(output)["files"] == 2


@pytest.mark.parametrize("failure", ["corrupt", "generation", "cancel", "privacy", "missing"])
def test_failure_never_publishes_completion_and_new_path_retry_succeeds(cloud, tmp_path, failure):
    bucket = cloud.client.storage
    name = next(key for key in bucket.objects if "/objects/" in key)
    original = dict(bucket.objects[name])
    cancelled = [False]

    def hook(stage, blob, _data):
        if stage == "download" and blob.name == name:
            if failure == "corrupt":
                bucket.objects[name]["body"] = b"!" + original["body"][1:]
            elif failure == "generation":
                bucket.objects[name]["generation"] += 1
            elif failure == "cancel":
                cancelled[0] = True
            elif failure == "privacy":
                bucket.iam_configuration.public_access_prevention = "disabled"

    bucket.hook = hook
    if failure == "missing":
        del bucket.objects[name]
    output = tmp_path / "interrupted"
    with pytest.raises(ValueError):
        fetch(cloud, output, cancelled=lambda: cancelled[0])
    assert not (output / backup.MANIFEST).exists()
    bucket.hook = lambda *_a: None
    bucket.objects[name] = original
    bucket.iam_configuration.public_access_prevention = "enforced"
    assert fetch(cloud, tmp_path / "retry")["state"] == "downloaded_verified"


def rewrite_marker(cloud, raw):
    bucket = cloud.client.storage
    old = publication.PREFIX + "/snapshots/" + cloud.digest + "/manifest.json"
    marker = dict(bucket.objects.pop(old))
    cloud.digest = hashlib.sha256(raw).hexdigest()
    marker.update(
        body=raw,
        size=len(raw),
        crc32c=crc(raw),
        metadata={
            "paperfact-layout": publication.LAYOUT,
            "sha256": cloud.digest,
            "paperfact-role": "manifest",
            "paperfact-snapshot": cloud.digest,
        },
    )
    bucket.objects[publication.PREFIX + "/snapshots/" + cloud.digest + "/manifest.json"] = marker


@pytest.mark.parametrize("invalid", ["traversal", "duplicate", "too-large", "missing-db", "fields"])
def test_untrusted_manifest_refused_before_local_output_or_payload_download(
    cloud, tmp_path, invalid
):
    value = json.loads((cloud.snapshot / backup.MANIFEST).read_bytes())
    if invalid == "traversal":
        value["files"][0]["path"] = "../outside"
    elif invalid == "duplicate":
        value["files"].append(value["files"][0])
    elif invalid == "too-large":
        value["files"][0]["size"] = retrieval.MAX_BYTES + 1
    elif invalid == "missing-db":
        value["files"] = [item for item in value["files"] if item["path"] != "authority.sqlite"]
    else:
        value["extra"] = True
    rewrite_marker(cloud, json.dumps(value).encode())
    with pytest.raises(ValueError):
        fetch(cloud, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists() and not (tmp_path / "outside").exists()
    downloads = [call for call in cloud.client.storage.calls if call[0] == "download"]
    assert downloads and all("/snapshots/" in call[1] for call in downloads)


def test_self_consistent_hashes_do_not_replace_authority_schema_and_closure_checks(cloud, tmp_path):
    value = json.loads((cloud.snapshot / backup.MANIFEST).read_bytes())
    entry = next(item for item in value["files"] if item["path"] == "authority.sqlite")
    old_key = publication.PREFIX + "/objects/" + entry["sha256"]
    body = b"not a sqlite authority"
    record = dict(cloud.client.storage.objects[old_key])
    entry.update(size=len(body), sha256=hashlib.sha256(body).hexdigest())
    record.update(
        body=body,
        size=len(body),
        crc32c=crc(body),
        metadata={
            "paperfact-layout": publication.LAYOUT,
            "sha256": entry["sha256"],
            "paperfact-role": "object",
        },
    )
    cloud.client.storage.objects[publication.PREFIX + "/objects/" + entry["sha256"]] = record
    rewrite_marker(cloud, json.dumps(value).encode())
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError):
        fetch(cloud, tmp_path / "bad-schema")
    assert not (tmp_path / "bad-schema" / backup.MANIFEST).exists()


def test_oversized_response_is_bounded_even_if_server_ignores_range(cloud, tmp_path, monkeypatch):
    def oversized(_self, stream, **_kwargs):
        stream.write(b"x" * (backup.CHUNK + 1))

    monkeypatch.setattr(DownloadBlob, "download_to_file", oversized)
    with pytest.raises(ValueError, match="range exceeded"):
        fetch(cloud, tmp_path / "oversized")
    assert not (tmp_path / "oversized").exists()


@pytest.mark.parametrize("option", ["digest", "budget", "emulator"])
def test_invalid_admission_never_discovers_credentials_or_creates_output(
    cloud, tmp_path, monkeypatch, option
):
    kwargs = {}
    if option == "digest":
        cloud.digest = "../escape"
    elif option == "budget":
        kwargs["max_bytes"] = True
    else:
        monkeypatch.setenv("STORAGE_EMULATOR_HOST", "http://untrusted.invalid")
    with pytest.raises(ValueError):
        fetch(cloud, tmp_path / "unused", **kwargs)
    assert not (tmp_path / "unused").exists()


def test_cli_help_and_bounded_failure_have_no_account_or_raw_response(
    tmp_path, capsys, monkeypatch
):
    assert (
        sync_admin.main(
            [
                "download-backup",
                "--bucket",
                "fixture-private-backups",
                "--snapshot",
                "invalid",
                "--output",
                str(tmp_path / "unused"),
            ]
        )
        == 2
    )
    result = capsys.readouterr()
    assert not result.out and "No service was restored" in result.err
    with pytest.raises(SystemExit) as exit_info:
        sync_admin.main(["download-backup", "--help"])
    assert exit_info.value.code == 0
    assert "--max-bytes" in capsys.readouterr().out


@pytest.mark.parametrize("moment", ["before", "final-verification"])
def test_cancellation_keeps_output_unpublished_and_default_verifier_refuses_it(
    cloud, tmp_path, moment
):
    stopped = [moment == "before"]

    def progress(value):
        if value["stage"] == "verify_authority":
            stopped[0] = True

    output = tmp_path / "cancelled"
    with pytest.raises(backup.BackupCancelled):
        fetch(cloud, output, cancelled=lambda: stopped[0], progress=progress)
    assert not (output / backup.MANIFEST).exists()
    with pytest.raises((ValueError, OSError)):
        backup.verify(output)


def test_owned_sdk_client_is_closed_on_failure_without_leaking_cloud_response(
    cloud, tmp_path, monkeypatch
):
    from google.api_core.exceptions import Forbidden

    monkeypatch.setattr(storage, "Client", lambda: cloud.client)

    def forbidden(*_args):
        raise Forbidden("PRIVATE RESPONSE MUST NOT LEAK")

    cloud.client.storage.hook = forbidden
    with pytest.raises(retrieval.RetrievalError, match="verify access/network") as error:
        retrieval.fetch("fixture-private-backups", cloud.digest, tmp_path / "failed")
    assert "PRIVATE RESPONSE" not in str(error.value)
    assert cloud.client.closed and not (tmp_path / "failed").exists()
