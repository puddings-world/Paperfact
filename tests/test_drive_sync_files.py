"""Personal Drive transport contracts; no OAuth, vault or live research."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from paper_daily.drive_sync_files import (
    ABOUT,
    FILES,
    FORMAT,
    DriveChanged,
    DriveFiles,
    DriveMissing,
    DriveUnavailable,
    decode,
    head_body,
)


class Cloud:
    def __init__(self):
        self.description = head_body(dict(format=FORMAT, workspace_id="workspace",
                                          generation=0, commit=None)).decode()
        self.revision = 1
        self.shared = self.trashed = False
        self.media = b"research operation"
        self.requests = []

    def handle(self, request):
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-only"
        if str(request.url).split("?")[0] == ABOUT:
            return httpx.Response(200, json={"user": {
                "permissionId": "owner", "emailAddress": "a@example.test"}})
        file_id = request.url.path.rsplit("/", 1)[-1]
        if request.url.path.startswith("/drive/v2/"):
            if request.method == "PATCH":
                if request.headers.get("if-match") != f'"{self.revision}"':
                    return httpx.Response(412)
                self.description = json.loads(request.content)["description"]
                self.revision += 1
            return httpx.Response(200, json={"id": file_id, "etag": f'"{self.revision}"',
                                            "description": self.description})
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, content=self.media)
        role = {"folder": "workspace", "head": "head", "object": "commit"}[file_id]
        metadata = {"id": file_id, "ownedByMe": True, "shared": self.shared,
                    "trashed": self.trashed,
                    "appProperties": {"pfWorkspace": "workspace", "pfRole": role, "pfVersion": "1"}}
        if role != "workspace":
            metadata["parents"] = ["folder"]
        if role == "commit":
            metadata.update(size=str(len(self.media)),
                            sha256Checksum=hashlib.sha256(self.media).hexdigest())
        return httpx.Response(200, json=metadata)


def files(cloud):
    return DriveFiles(SimpleNamespace(access_token=lambda: "synthetic-only"),
                      client=httpx.Client(transport=httpx.MockTransport(cloud.handle)))


def reference(raw=b"research operation"):
    return {"id": "object", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def test_competing_writes_preserve_winner_and_require_reload():
    cloud = Cloud()
    with files(cloud) as left, files(cloud) as right:
        a = left.read_head("head", "folder", "workspace")
        b = right.read_head("head", "folder", "workspace")
        accepted = left.publish_head(a, reference())
        with pytest.raises(DriveChanged):
            right.publish_head(b, reference(b"other candidate"))
        current = right.read_head("head", "folder", "workspace")
        assert current.body == accepted.body
        assert current.value()["commit"] == reference()
        assert current.value()["generation"] == 1


def test_wrong_account_receipt_and_newly_shared_folder_cannot_publish():
    cloud = Cloud()
    with files(cloud) as first, files(cloud) as other:
        observed = first.read_head("head", "folder", "workspace")
        before = len(cloud.requests)
        with pytest.raises(ValueError, match="account"):
            other.publish_head(observed, reference())
        with pytest.raises(ValueError, match="account"):
            first.publish_head(replace(observed), reference())
        assert len(cloud.requests) == before
        cloud.shared = True
        with pytest.raises(PermissionError, match="private"):
            first.publish_head(observed, reference())
        assert cloud.revision == 1


def test_immutable_download_checks_location_metadata_and_actual_bytes():
    cloud = Cloud()
    with files(cloud) as drive:
        captured = reference()
        assert drive.read_small(captured, "folder", "workspace") == cloud.media
        with pytest.raises(ValueError, match="workspace"):
            drive.read_small(captured, "folder", "another")
        with pytest.raises(ValueError, match="metadata"):
            drive.read_small(reference(b"changed"), "folder", "workspace")
        original = cloud.handle
        def corrupt(request):
            if request.url.params.get("alt") == "media":
                return httpx.Response(200, content=b"truncated")
            return original(request)
        with (DriveFiles(drive.session, client=httpx.Client(
                transport=httpx.MockTransport(corrupt))) as bad,
              pytest.raises(ValueError, match="verification")):
            bad.read_small(captured, "folder", "workspace")


def test_repeated_immutable_reads_check_live_access_without_downloading_again():
    cloud = Cloud()
    captured = reference()
    with files(cloud) as drive:
        for _ in range(2):
            assert drive.read_small(captured, "folder", "workspace") == cloud.media
        assert [r.url.params.get("alt") for r in cloud.requests] == [None, "media", None]
        cloud.shared = True
        with pytest.raises(PermissionError):
            drive.read_small(captured, "folder", "workspace")
        cloud.shared, cloud.trashed = False, True
        with pytest.raises(DriveMissing):
            drive.read_small(captured, "folder", "workspace")
        cloud.trashed = False
        cloud.media = b"modified"
        with pytest.raises(ValueError, match="metadata"):
            drive.read_small(captured, "folder", "workspace")
        assert drive.read_small(reference(cloud.media), "folder", "workspace") == cloud.media


def test_verified_bytes_bound_eviction_and_large_objects(monkeypatch):
    from paper_daily import drive_sync_files

    monkeypatch.setattr(drive_sync_files, "CACHE_ENTRIES", 2)
    monkeypatch.setattr(drive_sync_files, "CACHE_ENTRY_BYTES", 16)
    cloud = Cloud()
    with files(cloud) as drive:
        for raw in (b"a", b"b", b"c", b"b", b"a", b"x" * 17, b"x" * 17):
            cloud.media = raw
            assert drive.read_small(reference(raw), "folder", "workspace") == raw
        assert sum(r.url.params.get("alt") == "media" for r in cloud.requests) == 6


def test_drive_rate_limits_retry_without_treating_access_denials_as_transient():
    with files(Cloud()) as drive:
        for status, reasons, expected in (
            (403, ["rateLimitExceeded"], DriveUnavailable),
            (403, ["userRateLimitExceeded"], DriveUnavailable),
            (401, ["rateLimitExceeded"], PermissionError),
            (403, ["storageQuotaExceeded"], PermissionError),
            (403, ["rateLimitExceeded", "forbidden"], PermissionError),
            (403, [], PermissionError),
        ):
            error = {"error": {"errors": [{"reason": reason} for reason in reasons]}}
            with httpx.Client(transport=httpx.MockTransport(
                lambda _, code=status, body=error: httpx.Response(code, json=body)
            )) as client:
                drive.client = client
                with pytest.raises(expected):
                    drive.account()


def test_offline_missing_and_revoked_are_not_empty_remote_state():
    cloud = Cloud()
    with files(cloud) as drive:
        assert drive.account()["id"] == "owner"
        observed = drive.read_head("head", "folder", "workspace")
        for status, expected in [(404, DriveMissing), (401, PermissionError),
                                 (429, DriveUnavailable), (503, DriveUnavailable)]:
            drive.client = httpx.Client(transport=httpx.MockTransport(
                lambda _, status=status: httpx.Response(status)))
            with pytest.raises(expected):
                drive.publish_head(observed, reference())
        assert cloud.revision == 1


def test_cancelled_or_untrusted_destination_sends_no_credentials():
    from paper_daily.workspace_service import Cancelled

    cloud = Cloud()
    with files(cloud) as drive:
        with pytest.raises(ValueError, match="official"):
            drive.request("GET", "https://example.test/drive/v3/files")
        with pytest.raises(ValueError, match="authorization"):
            drive.request("GET", FILES, headers={"AUTHORIZATION": "another"})
        drive.cancelled = lambda: True
        with pytest.raises(Cancelled):
            drive.read_head("head", "folder", "workspace")
        assert cloud.requests == []


def test_protocol_rejects_duplicate_fields_and_noncanonical_head():
    with pytest.raises(ValueError, match="Duplicate"):
        decode(b'{"generation":0,"generation":1}')
    with pytest.raises(ValueError, match="Nonfinite"):
        decode(b'{"value":NaN}')
    with pytest.raises(ValueError, match="disagree"):
        head_body(dict(format=FORMAT, workspace_id="workspace", generation=1, commit=None))
    cloud = Cloud()
    with files(cloud) as drive:
        original = cloud.handle
        def weak(request):
            if request.url.path.startswith("/drive/v2/"):
                return httpx.Response(200, json={"id": "head", "etag": 'W/"weak"',
                                                "description": cloud.description})
            return original(request)
        drive.client = httpx.Client(transport=httpx.MockTransport(weak))
        with pytest.raises(ValueError, match="strong"):
            drive.read_head("head", "folder", "workspace")


def test_small_create_retry_verifies_bytes_without_replacing_object():
    cloud = Cloud()
    received = []
    original = cloud.handle
    def already_created(request):
        if request.method == "POST":
            received.append(request.content)
            return httpx.Response(409)
        return original(request)
    with DriveFiles(SimpleNamespace(access_token=lambda: "synthetic-only"),
                    client=httpx.Client(transport=httpx.MockTransport(already_created))) as drive:
        drive.put_small("object", "folder", "workspace", "commit", cloud.media)
        drive.put_small("object", "folder", "workspace", "commit", cloud.media)
        assert received[0] == received[1]
        assert b"\r\nContent-Type:" in received[0]
        with pytest.raises(ValueError, match="bytes differ"):
            drive.put_small("object", "folder", "workspace", "commit", b"wrong")
        assert not any(r.method == "PATCH" for r in cloud.requests)


class LedgerCloud(Cloud):
    def __init__(self):
        super().__init__()
        self.objects = {}

    def handle(self, request):
        file_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "POST":
            from email.parser import BytesParser
            from email.policy import default

            message = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + request.headers["content-type"].encode()
                + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.content)
            metadata, media = list(message.iter_parts())
            info = json.loads(metadata.get_payload(decode=True))
            file_id = info["id"]
            if file_id in self.objects:
                return httpx.Response(409)
            self.objects[file_id] = media.get_payload(decode=True)
            return httpx.Response(200, json={"id": file_id})
        if file_id in self.objects:
            raw = self.objects[file_id]
            if request.url.params.get("alt") == "media":
                return httpx.Response(200, content=raw)
            return httpx.Response(200, json={
                "id": file_id, "ownedByMe": True, "shared": False, "parents": ["folder"],
                "appProperties": {"pfWorkspace": "workspace", "pfRole": "commit", "pfVersion": "1"},
                "size": str(len(raw)), "sha256Checksum": hashlib.sha256(raw).hexdigest()})
        return super().handle(request)


def test_incremental_log_publishes_only_winner_and_survives_receiver_restart():
    from paper_daily.drive_sync_log import DriveLog

    cloud = LedgerCloud()
    with files(cloud) as a, files(cloud) as b:
        left = DriveLog(a, "folder", "head", "workspace")
        right = DriveLog(b, "folder", "head", "workspace")
        observed = left.head()
        anchor = observed.body
        stale = right.head()
        left.append(observed, "tx1", {"note": "first retained version"})
        with pytest.raises(DriveChanged):
            right.append(stale, "losing", {"note": "offline candidate"})
        # The immutable losing candidate is not part of accepted history.
        page = right.read_since(anchor)
        assert len(page.transactions) == 1
        assert decode(page.transactions[0])["payload"] == {"note": "first retained version"}
        left.append(left.head(), "tx2", {"note": "second retained version"})
    with files(cloud) as restarted:
        log = DriveLog(restarted, "folder", "head", "workspace")
        full = log.read_since(anchor)
        assert [decode(raw)["payload"]["note"] for raw in full.transactions] == [
            "first retained version", "second retained version"]
        assert log.read_since(full.anchor).transactions == ()
        # Same captured anchor can be reused until application commits atomically.
        assert log.read_since(page.anchor).transactions == full.transactions[1:]


def test_log_refuses_changed_prefix_corruption_and_excessive_work():
    from paper_daily.drive_sync_log import DriveLog
    from paper_daily.sync_journal import SyncHistoryUnavailable

    cloud = LedgerCloud()
    with files(cloud) as drive:
        log = DriveLog(drive, "folder", "head", "workspace")
        initial = log.head().body
        first = log.append(log.head(), "tx1", {"note": "first"}).body
        log.append(log.head(), "tx2", {"note": "second"})
        with pytest.raises(SyncHistoryUnavailable, match="bounded"):
            log.read_since(initial, limit=1)
        cloud.description = initial.decode()
        with pytest.raises(SyncHistoryUnavailable, match="behind"):
            log.read_since(first)
        cloud.description = first.decode()
        cloud.objects["tx1"] = b"changed after publication"
        with pytest.raises(ValueError, match="metadata"):
            log.read_since(initial)


class GrantStore:
    def __init__(self):
        self.rows = {}
        self.after_write = lambda: None

    def get_password(self, service, account):
        return self.rows.get((service, account))

    def set_password(self, service, account, value):
        self.rows[service, account] = value
        self.after_write()

    def delete_password(self, service, account):
        self.rows.pop((service, account))


def grant_workspace(tmp_path):
    import sqlite3
    from contextlib import closing

    from paper_daily.workspace_service import WorkspaceService

    path = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE paperfact_sync_identity(workspace TEXT,device TEXT)")
        conn.execute("INSERT INTO paperfact_sync_identity VALUES('workspace','device')")
        conn.commit()
    return WorkspaceService(path)


def test_drive_grant_is_native_only_and_client_pinned(tmp_path):
    from paper_daily.drive_sync_credentials import DriveVault

    workspace, store, cloud = grant_workspace(tmp_path), GrantStore(), Cloud()
    before = workspace.path.read_bytes()
    vault = DriveVault(workspace, backend=lambda: store, startup_dir=tmp_path / "startup")
    assert store.rows == {} and vault.load() is None
    with files(cloud) as drive:
        drive.session.client = {"client_id": "synthetic.apps.googleusercontent.com"}
        drive.session.token = {"refresh_token": "synthetic-refresh-only"}
        grant = vault.remember(drive, "folder", "head", "workspace")
    assert vault.load() == grant
    assert "synthetic-refresh-only" not in repr(grant)
    assert workspace.path.read_bytes() == before
    assert not (tmp_path / "startup").exists()
    restored = grant.session(client_reader=lambda: {"client_id": grant.client_id})
    assert restored.token == {"refresh_token": "synthetic-refresh-only"}
    with pytest.raises(PermissionError, match="client changed"):
        grant.session(client_reader=lambda: {"client_id": "another.apps.googleusercontent.com"})
    vault.forget()
    assert vault.load() is None


def test_drive_grant_cancellation_binding_change_and_missing_refresh_do_not_save(tmp_path):
    from paper_daily.drive_sync_credentials import DriveVault
    from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged

    workspace, store = grant_workspace(tmp_path), GrantStore()
    vault = DriveVault(workspace, backend=lambda: store)
    cloud = Cloud()
    with files(cloud) as drive:
        drive.session.client = {"client_id": "synthetic.apps.googleusercontent.com"}
        drive.session.token = {}
        cancelled = Ticket()
        cancelled.cancel()
        with pytest.raises(Cancelled):
            vault.remember(drive, "folder", "head", "workspace", cancelled)
        assert cloud.requests == []
        with pytest.raises(PermissionError, match="local workspace"):
            vault.remember(drive, "folder", "head", "another")
        with pytest.raises(ValueError, match="reusable"):
            vault.remember(drive, "folder", "head", "workspace")
        drive.session.token = {"refresh_token": "synthetic-refresh-only"}
        late = Ticket()
        store.after_write = late.cancel
        with pytest.raises(Cancelled):
            vault.remember(drive, "folder", "head", "workspace", late)
        assert store.rows == {}
        store.after_write = lambda: None
        workspace.current_path = lambda: tmp_path / "another.sqlite"
        with pytest.raises(WorkspaceChanged):
            vault.remember(drive, "folder", "head", "workspace")
    assert store.rows == {}



def test_google_gzip_response_is_decoded_once_and_keeps_actual_byte_bounds():
    import gzip

    cloud = Cloud()
    def compressed(request):
        original = cloud.handle(request)
        raw = gzip.compress(original.content)
        return httpx.Response(original.status_code,
                              headers={"Content-Encoding": "gzip",
                                       "Content-Length": str(len(raw))},
                              stream=httpx.ByteStream(raw))
    with DriveFiles(SimpleNamespace(access_token=lambda: "synthetic-only"),
                    client=httpx.Client(transport=httpx.MockTransport(compressed))) as drive:
        assert drive.account()["id"] == "owner"
        assert drive.read_small(reference(), "folder", "workspace") == cloud.media
