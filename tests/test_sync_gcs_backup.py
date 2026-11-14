"""Actual snapshots and SDK signatures, simulated GCS; never use credentials/network."""

import base64
import copy
import hashlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import google_crc32c
import pytest
from google.api_core.exceptions import Forbidden, NotFound, PreconditionFailed
from google.cloud import storage
from google.cloud.storage.exceptions import DataCorruption
from test_sync_authority_backup import state as state
from test_sync_service import operation

from paper_daily import sync_admin
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_gcs_backup as gcs


def crc(data):
    return base64.b64encode(google_crc32c.Checksum(data).digest()).decode("ascii")


class Bucket:
    def __init__(self):
        self.objects, self.calls = {}, []
        self.lock = Lock()
        self.iam_configuration = SimpleNamespace(
            public_access_prevention="enforced", uniform_bucket_level_access_enabled=True
        )
        self.hook = lambda *_args: None

    def reload(self, **options):
        self.calls.append(("policy",))
        self.hook("policy", None, None)

    def blob(self, name, **options):
        return Blob(self, name)


class Blob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name
        self.metadata = self.size = self.crc32c = self.generation = None
        self.content_encoding = self.cache_control = None

    def reload(self, *, if_generation_match=None, **options):
        self.bucket.hook("reload", self, None)
        with self.bucket.lock:
            item = self.bucket.objects.get(self.name)
            if item is None:
                raise NotFound("Synthetic absent object")
            if if_generation_match is not None and item["generation"] != if_generation_match:
                raise PreconditionFailed("Synthetic generation changed")
            for key in ("size", "metadata", "crc32c", "generation", "content_encoding"):
                setattr(self, key, copy.deepcopy(item[key]))
        self.bucket.calls.append(("get", self.name, if_generation_match))

    def upload_from_file(
        self,
        file_obj,
        *,
        size,
        content_type,
        if_generation_match,
        checksum,
        crc32c_checksum_value,
        **options,
    ):
        assert if_generation_match == 0 and checksum == "crc32c"
        assert content_type in {"application/json", "application/octet-stream"}
        assert self.cache_control == "no-store"
        self.bucket.hook("before_read", self, None)
        data = file_obj.read()
        self.bucket.hook("after_read", self, data)
        if len(data) != size or crc(data) != crc32c_checksum_value:
            raise DataCorruption(None, "Synthetic wrong uploaded checksum")
        with self.bucket.lock:
            if self.name in self.bucket.objects:
                raise PreconditionFailed("Synthetic concurrent create")
            self.bucket.objects[self.name] = dict(
                body=data,
                size=len(data),
                crc32c=crc(data),
                metadata=copy.deepcopy(self.metadata),
                content_encoding=self.content_encoding,
                generation=1,
            )
            self.bucket.calls.append(("put", self.name, if_generation_match))
        self.bucket.hook("stored", self, data)


class Client:
    def __init__(self):
        self.storage, self.closed = Bucket(), False

    def bucket(self, name):
        assert name == "fixture-private-backups"
        return self.storage

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    monkeypatch.setattr(storage, "Client", lambda *_a, **_k: pytest.fail("No ADC/client discovery"))


@pytest.fixture
def snapshot(state, tmp_path):
    output = tmp_path / "snapshot"
    backup.export(state[0], output)
    return output


def publish(snapshot, client, **kwargs):
    return gcs.publish(snapshot, "fixture-private-backups", client=client, **kwargs)


def test_actual_snapshot_publishes_all_exact_bytes_before_completion_and_retry_reuses(snapshot):
    client = Client()
    before = {p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    progress = []
    receipt = publish(snapshot, client, progress=progress.append)
    assert receipt["state"] == "published" and receipt["files_created"] == 3
    root = receipt["remote_prefix"].split("fixture-private-backups/", 1)[1]
    writes = [call[1] for call in client.storage.calls if call[0] == "put"]
    assert writes[-1] == root + "/manifest.json"
    assert len(writes) == 3
    for name, data in before.items():
        payload = receipt["object_prefix"].split("fixture-private-backups/", 1)[1]
        key = (
            root + "/manifest.json"
            if name.as_posix() == backup.MANIFEST
            else (payload + "/" + hashlib.sha256(data).hexdigest())
        )
        actual = client.storage.objects[key]
        assert (
            actual["body"] == data
            and actual["metadata"]["sha256"] == hashlib.sha256(data).hexdigest()
        )
    again = publish(snapshot, client)
    assert again["remote_prefix"] == receipt["remote_prefix"]
    assert again["files_created"] == 0 and again["files_reused"] == 3
    assert len([call for call in client.storage.calls if call[0] == "put"]) == 3
    assert progress[-1]["completed"] == progress[-1]["total"] == 3
    assert progress[-1]["bytes_verified"] == receipt["bytes_verified"]
    assert before == {
        p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()
    }
    assert not client.closed


@pytest.mark.parametrize("privacy", ["inherited", "disabled", "uniform-disabled"])
def test_unverified_bucket_privacy_refuses_before_upload(snapshot, privacy):
    client = Client()
    if privacy == "uniform-disabled":
        client.storage.iam_configuration.uniform_bucket_level_access_enabled = False
    else:
        client.storage.iam_configuration.public_access_prevention = privacy
    with pytest.raises(gcs.PublicationError, match="public-access"):
        publish(snapshot, client)
    assert not client.storage.objects


def test_partial_failure_keeps_no_completion_and_retry_skips_verified_objects(snapshot):
    client, failed = Client(), Event()
    manifest = json.loads((snapshot / backup.MANIFEST).read_text())
    pdf = next(item["sha256"] for item in manifest["files"] if item["path"].startswith("blobs/"))

    def fail(stage, blob, _data):
        if stage == "before_read" and blob.name.endswith("/" + pdf) and not failed.is_set():
            failed.set()
            raise Forbidden("Synthetic credential and research must not be echoed")

    client.storage.hook = fail
    with pytest.raises(gcs.PublicationError, match="access/network") as error:
        publish(snapshot, client)
    assert "credential and research" not in str(error.value)
    assert len(client.storage.objects) == 1
    assert not any(name.endswith("manifest.json") for name in client.storage.objects)
    receipt = publish(snapshot, client)
    assert receipt["files_created"] == 2 and receipt["files_reused"] == 1


@pytest.mark.parametrize("field", ["metadata", "crc32c", "size", "content_encoding"])
def test_existing_different_object_is_never_overwritten(snapshot, field):
    client = Client()
    publish(snapshot, client)
    digest = hashlib.sha256((snapshot / "authority.sqlite").read_bytes()).hexdigest()
    key = next(name for name in client.storage.objects if name.endswith("/objects/" + digest))
    client.storage.objects[key][field] = {
        "metadata": {"unrelated": "private"},
        "crc32c": "wrong",
        "size": -1,
        "content_encoding": "gzip",
    }[field]
    before = copy.deepcopy(client.storage.objects)
    writes = len([call for call in client.storage.calls if call[0] == "put"])
    with pytest.raises(gcs.PublicationError, match="differs"):
        publish(snapshot, client)
    assert client.storage.objects == before
    assert len([call for call in client.storage.calls if call[0] == "put"]) == writes


def test_cancel_after_one_verified_object_stops_before_completion(snapshot):
    client, stopped = Client(), Event()

    def cancel(value):
        if value["stage"] == "verified_remote":
            stopped.set()

    with pytest.raises(backup.BackupCancelled):
        publish(snapshot, client, cancelled=stopped.is_set, progress=cancel)
    assert len(client.storage.objects) == 1
    assert not any(name.endswith("manifest.json") for name in client.storage.objects)
    assert publish(snapshot, client)["files_reused"] == 1


def test_concurrent_exact_publish_has_one_generation_for_each_object(snapshot):
    client = Client()
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: publish(snapshot, client), range(2)))
    assert receipts[0]["remote_prefix"] == receipts[1]["remote_prefix"]
    assert len(client.storage.objects) == 3
    assert all(item["generation"] == 1 for item in client.storage.objects.values())
    assert len([call for call in client.storage.calls if call[0] == "put"]) == 3


def test_remote_generation_change_aborts_before_manifest_and_is_explicitly_retryable(snapshot):
    client, changed = Client(), Event()

    def replace(stage, _blob, _data):
        if stage == "policy" and len(client.storage.objects) == 2 and not changed.is_set():
            changed.set()
            next(iter(client.storage.objects.values()))["generation"] += 1

    client.storage.hook = replace
    with pytest.raises(gcs.PublicationError):
        publish(snapshot, client)
    assert not any(name.endswith("manifest.json") for name in client.storage.objects)
    assert publish(snapshot, client)["state"] == "published"


def test_corrupt_local_input_never_discovers_credentials_or_contacts_bucket(snapshot):
    (snapshot / "authority.sqlite").write_bytes(b"changed")
    with pytest.raises(ValueError):
        gcs.publish(snapshot, "fixture-private-backups")


def test_snapshot_change_after_inspection_is_refused_before_cloud(snapshot, monkeypatch):
    client = Client()
    inspect_snapshot = backup._inspect

    def change(*args, **kwargs):
        proof = inspect_snapshot(*args, **kwargs)
        (snapshot / "authority.sqlite").write_bytes(b"late change")
        return proof

    monkeypatch.setattr(backup, "_inspect", change)
    with pytest.raises(gcs.PublicationError, match="after inspection"):
        publish(snapshot, client)
    assert not client.storage.calls


def test_sdk_checksums_detect_bytes_changed_after_preflight(snapshot):
    client = Client()
    digest = hashlib.sha256((snapshot / "authority.sqlite").read_bytes()).hexdigest()

    def mutate(stage, blob, _data):
        if stage == "before_read" and blob.name.endswith("/objects/" + digest):
            (snapshot / "authority.sqlite").write_bytes(b"mutated during upload")

    client.storage.hook = mutate
    with pytest.raises(gcs.PublicationError, match="publication failed"):
        publish(snapshot, client)
    assert not any(name.endswith("manifest.json") for name in client.storage.objects)


def test_completion_bytes_stay_verified_even_if_input_changes_after_transmit(snapshot):
    client = Client()
    original = (snapshot / backup.MANIFEST).read_bytes()

    def mutate(stage, blob, _data):
        if stage == "after_read" and blob.name.endswith("manifest.json"):
            (snapshot / backup.MANIFEST).write_bytes(b"untrusted replacement")

    client.storage.hook = mutate
    with pytest.raises(gcs.PublicationError):
        publish(snapshot, client)
    marker = next(
        value for name, value in client.storage.objects.items() if name.endswith("manifest.json")
    )
    assert marker["body"] == original
    manifest = json.loads(marker["body"])
    for item in manifest["files"]:
        match = next(
            value
            for name, value in client.storage.objects.items()
            if name.endswith("/objects/" + item["sha256"])
        )
        assert hashlib.sha256(match["body"]).hexdigest() == item["sha256"]


@pytest.mark.parametrize(
    "bucket,prefix",
    [
        ("gs://bucket", "safe"),
        ("bad bucket", "safe"),
        ("fixture-private-backups", "../other"),
        ("fixture-private-backups", "/absolute"),
        ("fixture-private-backups", "nested//empty"),
        ("fixture-private-backups", "x" * 201),
    ],
)
def test_invalid_destination_refuses_without_credentials(bucket, prefix, tmp_path):
    with pytest.raises(gcs.PublicationError):
        gcs.publish(tmp_path / "not-opened", bucket, prefix=prefix)


def test_emulator_endpoint_cannot_redirect_private_backups(snapshot, monkeypatch):
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", "http://127.0.0.1:9191")
    with pytest.raises(gcs.PublicationError, match="emulator"):
        publish(snapshot, Client())


def test_owned_sdk_client_is_closed_without_login_during_tests(snapshot, monkeypatch):
    client = Client()
    monkeypatch.setattr(storage, "Client", lambda: client)
    assert gcs.publish(snapshot, "fixture-private-backups")["state"] == "published"
    assert client.closed


def test_actual_sdk_signatures_match_the_operator_adapter():
    parameters = inspect.signature(storage.Blob.upload_from_file).parameters
    assert {"if_generation_match", "checksum", "crc32c_checksum_value", "size"} <= set(parameters)
    assert "if_generation_match" in inspect.signature(storage.Blob.reload).parameters
    assert crc(b"123456789") == "4waSgw=="


def test_cli_help_upload_and_bounded_error_never_print_cloud_response(
    snapshot, monkeypatch, capsys
):
    client = Client()
    original = gcs.publish
    monkeypatch.setattr(gcs, "publish", lambda *a, **k: original(*a, client=client, **k))
    args = ["upload-backup", "--input", str(snapshot), "--bucket", "fixture-private-backups"]
    assert sync_admin.main(args) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "published"
    client.storage.iam_configuration.public_access_prevention = "inherited"
    assert sync_admin.main(args) == 2
    result = capsys.readouterr()
    assert not result.out and "Traceback" not in result.err
    with pytest.raises(SystemExit) as result:
        sync_admin.main(["upload-backup", "--help"])
    assert result.value.code == 0


@pytest.mark.parametrize("stage", ["verified_remote", "complete_manifest"])
def test_budget_or_cancel_never_creates_a_fresh_completion_marker(snapshot, monkeypatch, stage):
    client, stopped = Client(), Event()
    now = [0]
    monkeypatch.setattr(backup.time, "monotonic", lambda: now[0])

    def stop(value):
        if value["stage"] == stage:
            if stage == "verified_remote":
                now[0] = 2
            else:
                stopped.set()

    with pytest.raises(backup.BackupCancelled):
        publish(snapshot, client, seconds=1, cancelled=stopped.is_set, progress=stop)
    assert client.storage.objects
    assert not any(name.endswith("manifest.json") for name in client.storage.objects)


def test_uncertain_successful_create_is_verified_without_overwrite(snapshot):
    client, lost = Client(), Event()
    digest = hashlib.sha256((snapshot / "authority.sqlite").read_bytes()).hexdigest()

    def uncertain(stage, blob, _data):
        if stage == "stored" and blob.name.endswith("/objects/" + digest) and not lost.is_set():
            lost.set()
            raise PreconditionFailed("Synthetic retry after a lost successful ACK")

    client.storage.hook = uncertain
    receipt = publish(snapshot, client)
    assert receipt["state"] == "published" and receipt["files_reused"] == 1
    assert len([item for item in client.storage.calls if item[0] == "put"]) == 3


def test_missing_operator_sdk_is_bounded_and_never_discovers_credentials(snapshot, monkeypatch):
    import builtins

    original = builtins.__import__

    def without_sdk(name, *args, **kwargs):
        if name == "google_crc32c":
            raise ImportError("Synthetic desktop package has no operator SDK")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sdk)
    with pytest.raises(gcs.PublicationError, match="operator dependencies"):
        gcs.publish(snapshot, "fixture-private-backups")


def test_cli_quiet_keeps_one_machine_readable_receipt_without_progress(
    snapshot, monkeypatch, capsys
):
    client, original = Client(), gcs.publish
    monkeypatch.setattr(gcs, "publish", lambda *a, **k: original(*a, client=client, **k))
    assert (
        sync_admin.main(
            [
                "upload-backup",
                "--input",
                str(snapshot),
                "--bucket",
                "fixture-private-backups",
                "--quiet",
            ]
        )
        == 0
    )
    receipt = capsys.readouterr()
    assert json.loads(receipt.out)["state"] == "published" and receipt.err == ""


def test_two_different_snapshots_share_exact_pdf_objects_and_keep_both_manifests(
    snapshot, state, tmp_path
):
    client = Client()
    first = publish(snapshot, client)
    first_objects = copy.deepcopy(client.storage.objects)
    root, service, token, _pdf, _data = state
    service.push(token, operation("new-backup-state", base=2, body="Changed researcher note"))
    second_snapshot = tmp_path / "later-snapshot"
    backup.export(root, second_snapshot)
    second = publish(second_snapshot, client)
    assert second["snapshot_sha256"] != first["snapshot_sha256"]
    assert second["files_created"] == 2 and second["files_reused"] == 1
    assert len(client.storage.objects) == 5
    for name, record in first_objects.items():
        assert client.storage.objects[name] == record
    assert len([name for name in client.storage.objects if name.endswith("manifest.json")]) == 2
