"""Two isolated devices through the real authority/protocol, synthetic Drive only."""

import hashlib
import json
from email.parser import BytesParser
from email.policy import default
from types import SimpleNamespace

import httpx
import pytest
from test_sync_service import operation
from test_workspace_enrollment import source as source_fixture

from paper_daily.drive_sync_authority import DriveAuthority
from paper_daily.drive_sync_files import ABOUT, FORMAT, DriveFiles, DriveUnavailable, head_body
from paper_daily.drive_sync_transport import DriveTransport
from paper_daily.sync_blobs import BlobManifest

source = source_fixture


class Cloud:
    def __init__(self):
        self.description = head_body(dict(format=FORMAT, workspace_id="workspace-a",
                                          generation=0, commit=None)).decode()
        self.revision = self.serial = 0
        self.objects = {}
        self.lose_ack = False

    def reply(self, request):
        path, method = request.url.path, request.method
        identity = path.rsplit("/", 1)[-1]
        if str(request.url).split("?")[0] == ABOUT:
            return httpx.Response(200, json={"user": {"permissionId": "owner",
                                                     "emailAddress": "owner@example.test"}})
        if identity == "generateIds":
            count = int(request.url.params.get("count", 1))
            values = [f"id-{n}" for n in range(self.serial, self.serial + count)]
            self.serial += count
            return httpx.Response(200, json={"ids": values})
        if path.startswith("/drive/v2/"):
            if method == "PATCH":
                if request.headers["if-match"] != f'"{self.revision}"':
                    return httpx.Response(412)
                self.description = json.loads(request.content)["description"]
                self.revision += 1
                if self.lose_ack:
                    self.lose_ack = False
                    return httpx.Response(503)
            return httpx.Response(200, json={"id": identity, "etag": f'"{self.revision}"',
                                            "description": self.description})
        if method == "GET" and identity == "files":
            query = request.url.params.get("q", "")
            role = "head" if "parents" in query else "workspace"
            if "value='directory'" in query:
                role = "directory"
            values = [info for info, _ in self.objects.values()
                      if info["appProperties"]["pfRole"] == role]
            return httpx.Response(200, json={"files": [
                {**info, "ownedByMe": True, "shared": False} for info in values]})
        if (method == "POST"
                and request.headers.get("content-type", "").startswith("application/json")):
            info = json.loads(request.content)
            if info["id"] in self.objects:
                return httpx.Response(409)
            self.objects[info["id"]] = info, b""
            return httpx.Response(200, json={"id": info["id"]})
        if method == "POST":
            message = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + request.headers["content-type"].encode()
                + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.content)
            metadata, media = list(message.iter_parts())
            info = json.loads(metadata.get_payload(decode=True))
            identity = info["id"]
            if identity in self.objects:
                return httpx.Response(409)
            self.objects[identity] = info, media.get_payload(decode=True)
            if info["appProperties"]["pfRole"] == "head":
                self.description = info["description"]
            return httpx.Response(200, json={"id": identity})
        if identity in {"folder", "head"}:
            role = "workspace" if identity == "folder" else "head"
            value = dict(id=identity, ownedByMe=True, shared=False,
                         appProperties=dict(pfWorkspace="workspace-a", pfRole=role, pfVersion="1"))
            if role == "head":
                value["parents"] = ["folder"]
            return httpx.Response(200, json=value)
        if identity not in self.objects:
            return httpx.Response(404)
        info, raw = self.objects[identity]
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, content=raw)
        return httpx.Response(200, json={**info, "ownedByMe": True, "shared": False,
                                       "size": str(len(raw)),
                                       "sha256Checksum": hashlib.sha256(raw).hexdigest()})


def authority(cloud, root):
    session = SimpleNamespace(access_token=lambda: "synthetic-google-token")
    files = DriveFiles(session, client=httpx.Client(transport=httpx.MockTransport(cloud.reply)))
    return DriveAuthority(files, "folder", "head", "workspace-a", "owner", root)


def enroll(service, device, credential):
    return service.invoke("enroll", "workspace-a", device, credential=credential)


def test_two_devices_reuse_conflict_engine_and_reopen_without_losing_versions(tmp_path):
    cloud = Cloud()
    a, b = authority(cloud, tmp_path / "a"), authority(cloud, tmp_path / "b")
    token_a, token_b = enroll(a, "device-a", "a" * 43), enroll(b, "device-b", "b" * 43)
    with DriveTransport(a) as left, DriveTransport(b) as right:
        assert left.session_info(token_a)["device_id"] == "device-a"
        assert right.session_info(token_b)["device_id"] == "device-b"
        first = left.push(token_a, operation(body="desktop observation"))
        competing = operation("op-mac", device="device-b", body="offline Mac observation")
        conflict = right.push(token_b, competing)
        assert first["outcome"] == "accepted"
        assert conflict["outcome"] == "conflict"
        assert conflict["head"]["operation"]["payload"]["body"] == "desktop observation"
        assert conflict["operation"]["payload"]["body"] == "offline Mac observation"
    reopened = authority(cloud, tmp_path / "b")
    with DriveTransport(reopened) as right:
        assert len(right.pull(token_b)) == 2
        assert right.push(token_b, competing) == conflict
    all_cloud_bytes = b"".join(raw for _, raw in cloud.objects.values())
    assert token_a.encode() not in all_cloud_bytes
    assert token_b.encode() not in all_cloud_bytes
    assert b"synthetic-google-token" not in all_cloud_bytes


def test_lost_commit_ack_reconciles_same_enrollment_without_duplicate_device(tmp_path):
    cloud = Cloud()
    a = authority(cloud, tmp_path / "a")
    cloud.lose_ack = True
    with pytest.raises(DriveUnavailable):
        enroll(a, "device-a", "a" * 43)
    token = enroll(a, "device-a", "a" * 43)
    with DriveTransport(a) as transport:
        assert transport.session_info(token)["device_id"] == "device-a"
        assert len(transport.device_catalog(token)["devices"]) == 1


def test_pdf_chunks_move_to_other_device_and_reads_do_not_republish(tmp_path):
    cloud = Cloud()
    a, b = authority(cloud, tmp_path / "a"), authority(cloud, tmp_path / "b")
    token_a, token_b = enroll(a, "device-a", "a" * 43), enroll(b, "device-b", "b" * 43)
    data = b"synthetic PDF bytes " * 220000
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    with DriveTransport(a) as left:
        left.session_info(token_a)
        upload = left.blob_begin(token_a, manifest.__dict__)
        for offset in range(0, len(data), 256 * 1024):
            left.blob_append(token_a, upload["upload_id"], offset, data[offset:offset + 256 * 1024])
        assert left.blob_commit(token_a, upload["upload_id"])["complete"]
    revision = cloud.revision
    with DriveTransport(b) as right:
        right.session_info(token_b)
        assert right.blob_read(token_b, manifest.sha256, manifest.size, 0) == data[:256 * 1024]
        tail = len(data) - 23
        assert right.blob_read(token_b, manifest.sha256, manifest.size, tail) == data[tail:]
    assert cloud.revision == revision


def test_create_sync_and_join_preserves_private_source_and_saved_reading(tmp_path, source):
    import sqlite3
    from contextlib import closing

    from test_drive_sync_files import GrantStore

    from paper_daily import store
    from paper_daily.drive_sync_setup import DriveSetup
    from paper_daily.workspace_service import Ticket

    cloud, vault = Cloud(), GrantStore()
    before = source.read_bytes()
    def make_setup(path, label):
        setup = DriveSetup(path, backend=lambda: vault, profiles=tmp_path / label,
                           cache=tmp_path / (label + "-cache"),
                           startup_dir=tmp_path / (label + "-startup"))
        setup.files = DriveFiles(SimpleNamespace(
            access_token=lambda: "synthetic-google-token",
            client={"client_id": "synthetic.apps.googleusercontent.com"},
            token={"refresh_token": "synthetic-refresh"}),
            client=httpx.Client(transport=httpx.MockTransport(cloud.reply)))
        setup.account = setup.files.account()
        return setup
    desktop = make_setup(source, "desktop")
    created = desktop.create("My research", Ticket(), lambda _: None)
    assert source.read_bytes() == before
    assert created["copied"]
    sent = created["session"].sync(Ticket())
    assert sent["pending"] == 0
    empty_root = tmp_path / "mac-source"
    empty_root.mkdir()
    empty = empty_root / "papers.db"
    with closing(sqlite3.connect(empty)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    mac = make_setup(empty, "mac")
    joined = mac.join(created["descriptor"], Ticket(), lambda _: None)
    with closing(sqlite3.connect(joined["database"])) as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("A research note",)]
        assert conn.execute("SELECT name FROM lists WHERE id='list'").fetchone() == (
            "Reading route",)
        assert conn.execute("SELECT value FROM kv WHERE key='auth.secret'").fetchone() is None
    # An offline save survives a new session built solely from native records.
    from paper_daily.connection_vault import ConnectionVault
    from paper_daily.drive_sync_factory import TransportFactory
    from paper_daily.sync_capture import CaptureConnection, expecting, observe_note
    from paper_daily.workspace_service import WorkspaceService
    from paper_daily.workspace_sync import SyncSession

    with closing(sqlite3.connect(joined["database"], factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        note_id = conn.execute("SELECT id FROM notes").fetchone()[0]
        observed = observe_note(conn, note_id)
        with expecting(conn, [observed]):
            conn.execute("UPDATE notes SET body=? WHERE id=?", ("Mac offline observation", note_id))
            conn.commit()

    def restored_files(session):
        assert session.token["refresh_token"] == "synthetic-refresh"
        return DriveFiles(SimpleNamespace(access_token=lambda: "synthetic-google-token"),
                          client=httpx.Client(transport=httpx.MockTransport(cloud.reply)))

    factory = TransportFactory(WorkspaceService(joined["database"]), backend=lambda: vault,
                               cache_root=tmp_path / "mac-restarted-cache",
                               files_factory=restored_files,
                               client_reader=lambda: {
                                   "client_id": "synthetic.apps.googleusercontent.com"})
    restarted = SyncSession(joined["database"], transport_factory=factory)
    saved = ConnectionVault(restarted.workspace, backend=lambda: vault).load()
    restarted.connect(saved.endpoint, saved.workspace_id, saved.device_id, saved.token, Ticket())
    assert restarted.sync(Ticket())["pending"] == 0
    created["session"].sync(Ticket())
    with closing(sqlite3.connect(created["database"])) as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Mac offline observation",)]
    reconnected = make_setup(joined["database"], "mac-reconnected").create(
        "My research", Ticket(), lambda _: None)
    assert not reconnected["copied"]
    assert reconnected["descriptor"] == created["descriptor"]
    assert source.read_bytes() == before
    assert b"must-not-leak-token" not in b"".join(raw for _, raw in cloud.objects.values())



def test_deltas_cross_checkpoint_boundary_and_missing_prefix_is_refused(tmp_path, monkeypatch):
    from paper_daily import drive_sync_authority as module
    from paper_daily.sync_journal import SyncHistoryUnavailable

    monkeypatch.setattr(module, "CHECKPOINT_EVERY", 3)
    cloud = Cloud()
    a = authority(cloud, tmp_path / "a")
    token = enroll(a, "device-a", "a" * 43)
    for index in range(5):
        op = operation(f"op-{index}", base=index, body=f"saved version {index}")
        assert a.invoke("push", token, op)["outcome"] == "accepted"
    reopened = authority(cloud, tmp_path / "reopened")
    events = reopened.invoke("pull", token)
    assert [item["operation"]["payload"]["body"] for item in events] == [
        f"saved version {index}" for index in range(5)]
    # The first device's durable anchor refuses a cloud head moved behind it.
    current = json.loads(cloud.description)
    cloud.description = head_body(dict(format=FORMAT, workspace_id="workspace-a",
                                      generation=0, commit=None)).decode()
    with pytest.raises(SyncHistoryUnavailable):
        a.invoke("pull", token)
    cloud.description = json.dumps(current)
