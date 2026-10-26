"""Authenticated attachment transfers use isolated bytes and databases only."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_sync_reading_state_service import PAPER, op, ref

from paper_daily.sync_blob_service import BLOB_CHUNK_BYTES, BlobDisabledError, BlobUnavailableError
from paper_daily.sync_blobs import BlobError, BlobQuotaError
from paper_daily.sync_service import ReferenceService


def manifest(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


@pytest.fixture
def ready(tmp_path):
    service = ReferenceService(
        tmp_path / "authority.sqlite",
        blob_root=tmp_path / "bytes",
        blob_quota_bytes=1024,
        blob_max_bytes=512,
        blob_max_uploads=4,
    )
    a, b = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    other = service.enroll("other", "a")
    return service, a, b, other


def upload(service, token, data):
    declared = manifest(data)
    session = service.blob_begin(token, declared)
    if not session["complete"]:
        if data:
            service.blob_append(token, session["upload_id"], 0, data)
        service.blob_commit(token, session["upload_id"])
    return declared, session["upload_id"]


def read(service, token, declared, **kwargs):
    return service.blob_read(
        token, declared["sha256"], declared["size"], kwargs.pop("offset", 0), **kwargs
    )


def paper(service, token):
    return service.push(
        token,
        op(
            "paper-create",
            "paper",
            PAPER,
            {
                "title": "Fixture",
                "authors": [],
                "year": None,
                "venue": None,
                "abstract": None,
                "doi": None,
                "arxiv_id": None,
                "s2_id": None,
                "page_url": None,
                "pdf_url": None,
                "source": None,
            },
        ),
    )


def document(declared, identity="document", **kwargs):
    return op(
        identity,
        "paper_document",
        PAPER,
        {"paper_id": PAPER, **declared, "media_type": "application/pdf"},
        parents=[ref("paper", PAPER, "paper-create")],
        **kwargs,
    )


def test_explicit_configuration_and_auth_precede_storage_use(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "a")
    with pytest.raises(BlobDisabledError):
        service.blob_begin(token, manifest(b"fixture"))
    with pytest.raises(PermissionError):
        service.blob_begin("invalid", manifest(b"fixture"))
    assert set(p.name for p in tmp_path.iterdir()) == {"authority.sqlite"}


def test_workspace_namespace_isolation_and_known_hash_is_not_authorization(ready):
    service, a, b, other = ready
    data = b"synthetic document"
    declared, _ = upload(service, a, data)
    assert read(service, b, declared) == data
    with pytest.raises(PermissionError):
        read(service, other, declared)
    other_session = service.blob_begin(other, declared)
    assert other_session["offset"] == 0 and not other_session["complete"]
    with pytest.raises(PermissionError):
        read(service, other, declared)
    service.blob_append(other, other_session["upload_id"], 0, data)
    service.blob_commit(other, other_session["upload_id"])
    assert read(service, other, declared) == data
    with closing(sqlite3.connect(service.path)) as conn:
        namespaces = conn.execute("SELECT workspace,directory FROM sync_blob_namespaces").fetchall()
        dump = "\n".join(conn.iterdump())
    assert len({directory for _, directory in namespaces}) == 2
    assert all(
        len(directory) == 32 and directory not in ("workspace", "other")
        for _, directory in namespaces
    )
    assert a not in dump and b not in dump and other not in dump


def test_active_upload_device_binding_and_no_session_takeover(ready):
    service, a, b, other = ready
    declared = manifest(b"abcdefgh")
    session = service.blob_begin(a, declared)
    identity = session["upload_id"]
    assert service.blob_begin(a, declared) == session
    with pytest.raises(PermissionError):
        service.blob_begin(b, declared)
    for token in (b, other):
        for action in [
            lambda token=token: service.blob_append(token, identity, 0, b"abcd"),
            lambda token=token: service.blob_commit(token, identity),
            lambda token=token: service.blob_cancel(token, identity),
        ]:
            with pytest.raises(PermissionError):
                action()
    assert service.blob_begin(a, declared)["offset"] == 0


@pytest.mark.parametrize("method", ["begin", "append", "commit", "cancel", "read"])
def test_revoked_device_rejected_on_every_phase_and_retry(ready, method):
    service, a, _, _ = ready
    declared, identity = upload(service, a, b"abcdefgh")
    service.revoke(a)
    calls = {
        "begin": lambda: service.blob_begin(a, declared),
        "append": lambda: service.blob_append(a, identity, 0, b"abcd"),
        "commit": lambda: service.blob_commit(a, identity),
        "cancel": lambda: service.blob_cancel(a, identity),
        "read": lambda: read(service, a, declared),
    }
    with pytest.raises(PermissionError):
        calls[method]()


def test_resumable_offsets_overlap_retries_restart_and_commit_are_idempotent(ready):
    service, a, _, _ = ready
    data = b"abcdefghijk"
    declared = manifest(data)
    identity = service.blob_begin(a, declared)["upload_id"]
    assert service.blob_append(a, identity, 0, data[:4]) == {"offset": 4}
    restarted = ReferenceService(service.path, blob_root=service.blob_root)
    assert restarted.blob_begin(a, declared)["upload_id"] == identity
    assert restarted.blob_begin(a, declared)["offset"] == 4
    assert restarted.blob_append(a, identity, 0, data[:8]) == {"offset": 8}
    with pytest.raises(BlobError, match="differs"):
        restarted.blob_append(a, identity, 0, b"XXXX")
    with pytest.raises(BlobError, match="gap"):
        restarted.blob_append(a, identity, 10, b"k")
    assert restarted.blob_begin(a, declared)["offset"] == 8
    restarted.blob_append(a, identity, 8, data[8:])
    committed = restarted.blob_commit(a, identity)
    assert committed == {**declared, "complete": True}
    assert restarted.blob_commit(a, identity) == committed
    assert restarted.blob_append(a, identity, 0, data[:4]) == {"offset": len(data)}
    assert restarted.blob_begin(a, declared) == {
        **declared,
        "upload_id": None,
        "offset": len(data),
        "complete": True,
    }
    assert read(restarted, a, declared, offset=3, limit=4) == b"defg"
    assert read(restarted, a, declared, offset=len(data)) == b""


def test_cancel_is_idempotent_releases_reservation_and_cannot_remove_history(ready):
    service, a, _, _ = ready
    declared = manifest(b"abcdefgh")
    identity = service.blob_begin(a, declared)["upload_id"]
    service.blob_append(a, identity, 0, b"abcd")
    assert service.blob_cancel(a, identity) == {"cancelled": True}
    assert service.blob_cancel(a, identity) == {"cancelled": True}
    with pytest.raises(BlobError, match="cancelled"):
        service.blob_append(a, identity, 4, b"efgh")
    with pytest.raises(BlobError, match="cancelled"):
        service.blob_commit(a, identity)
    restarted = service.blob_begin(a, declared)
    assert restarted["offset"] == 0 and restarted["upload_id"] != identity
    service.blob_append(a, restarted["upload_id"], 0, b"abcdefgh")
    service.blob_commit(a, restarted["upload_id"])
    with pytest.raises(BlobError, match="history"):
        service.blob_cancel(a, restarted["upload_id"])
    assert read(service, a, declared) == b"abcdefgh"


def test_quota_reserves_full_sizes_and_concurrent_begins_cannot_overbook(tmp_path):
    service = ReferenceService(
        tmp_path / "authority.sqlite", blob_root=tmp_path / "bytes", blob_quota_bytes=10
    )
    token = service.enroll("workspace", "a")

    def reserve(data):
        try:
            return service.blob_begin(token, manifest(data))
        except BlobQuotaError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [b"123456", b"abcdef"]))
    assert len([result for result in results if result is not None]) == 1
    reserved = next(result for result in results if result)
    service.blob_cancel(token, reserved["upload_id"])
    assert service.blob_begin(token, manifest(b"new-reserve"[:10]))["offset"] == 0


def test_duplicate_concurrent_begin_has_one_session_and_one_reservation(ready):
    service, a, _, _ = ready
    declared = manifest(b"abcdefgh")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.blob_begin(a, declared), range(8)))
    assert len({result["upload_id"] for result in results}) == 1
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT SUM(size),COUNT(*) FROM sync_workspace_blobs").fetchone() == (
            8,
            1,
        )


def test_session_and_file_limits_apply_before_more_reservations(tmp_path):
    service = ReferenceService(
        tmp_path / "authority.sqlite",
        blob_root=tmp_path / "bytes",
        blob_max_uploads=1,
        blob_max_bytes=4,
    )
    token = service.enroll("workspace", "a")
    with pytest.raises(BlobQuotaError):
        service.blob_begin(token, manifest(b"12345"))
    first = service.blob_begin(token, manifest(b""))
    with pytest.raises(BlobQuotaError):
        service.blob_begin(token, manifest(b"a"))
    service.blob_cancel(token, first["upload_id"])
    service.blob_begin(token, manifest(b"a"))


def test_full_hash_mismatch_never_grants_ownership(ready):
    service, a, _, _ = ready
    declared = manifest(b"correct")
    identity = service.blob_begin(a, declared)["upload_id"]
    service.blob_append(a, identity, 0, b"corrupt")
    with pytest.raises(BlobError, match="hash"):
        service.blob_commit(a, identity)
    with pytest.raises(PermissionError):
        read(service, a, declared)
    service.blob_cancel(a, identity)
    upload(service, a, b"correct")
    assert read(service, a, declared) == b"correct"


@pytest.mark.parametrize("repair", ["begin", "commit"])
def test_crash_after_physical_finalize_before_authority_commit_stays_private(
    ready, monkeypatch, repair
):
    service, a, b, _ = ready
    paper(service, a)
    declared = manifest(b"fixture-pdf")
    identity = service.blob_begin(a, declared)["upload_id"]
    service.blob_append(a, identity, 0, b"fixture-pdf")
    original = service._blob_mark_committed

    def fail(*args):
        original(*args)
        raise RuntimeError("simulated ownership transaction interruption")

    monkeypatch.setattr(service, "_blob_mark_committed", fail)
    with pytest.raises(RuntimeError, match="interruption"):
        service.blob_commit(a, identity)
    with pytest.raises(PermissionError):
        read(service, b, declared)
    with pytest.raises(BlobUnavailableError):
        service.push(a, document(declared))
    assert len(service.pull(a)) == 1
    with pytest.raises(PermissionError):
        service.blob_begin(b, declared)
    restarted = ReferenceService(service.path, blob_root=service.blob_root)
    if repair == "begin":
        assert restarted.blob_begin(a, declared)["complete"]
    else:
        assert restarted.blob_commit(a, identity)["complete"]
    assert read(restarted, b, declared) == b"fixture-pdf"
    assert restarted.push(a, document(declared))["outcome"] == "accepted"


def test_manifest_requires_owned_commit_but_old_receipt_replays_after_byte_loss(ready):
    service, a, _, other = ready
    paper(service, a)
    data = b"fixture-pdf"
    declared, _ = upload(service, other, data)
    operation = document(declared)
    with pytest.raises(BlobUnavailableError):
        service.push(a, operation)
    identity = service.blob_begin(a, declared)["upload_id"]
    service.blob_append(a, identity, 0, data)
    with pytest.raises(BlobUnavailableError):
        service.push(a, operation)
    service.blob_commit(a, identity)
    event = service.push(a, operation)
    assert event["outcome"] == "accepted"
    with service._transaction() as conn:
        path = service._blob_owned_path(conn, "workspace", service._manifest(declared))
    path.unlink()
    assert service.push(a, operation) == event
    with pytest.raises(BlobUnavailableError):
        read(service, a, declared)
    changed = document(declared, "replacement", incarnation="document", base=event["sequence"])
    with pytest.raises(BlobUnavailableError):
        service.push(a, changed)
    assert len(service.pull(a)) == 2


def test_manifest_conflict_and_delete_keep_owned_history_bytes(ready):
    service, a, b, _ = ready
    paper(service, a)
    first, _ = upload(service, a, b"first")
    second, _ = upload(service, a, b"second")
    accepted = service.push(a, document(first))
    conflict = service.push(b, document(second, "competing", device="b"))
    assert conflict["outcome"] == "conflict"
    deletion = op(
        "detach",
        "paper_document",
        PAPER,
        {},
        incarnation="document",
        base=accepted["sequence"],
        structure=accepted["sequence"],
        action="delete",
        parents=[ref("paper", PAPER, "paper-create")],
    )
    assert service.push(a, deletion)["outcome"] == "accepted"
    assert read(service, a, first) == b"first"
    assert read(service, a, second) == b"second"
    assert service.pull(a)[2] == conflict


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"sha256": "a" * 64, "size": 0, "path": "extra"},
        {"sha256": "A" * 64, "size": 1},
        {"sha256": "a" * 64, "size": True},
        {"sha256": "a" * 64, "size": -1},
        {"sha256": "../escape", "size": 1},
    ],
)
def test_closed_manifest_validation_does_not_create_sessions(ready, value):
    service, a, _, _ = ready
    with pytest.raises(ValueError):
        service.blob_begin(a, value)
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_uploads").fetchone()[0] == 0


@pytest.mark.parametrize(
    "offset,data",
    [(-1, b"a"), (True, b"a"), (0, b""), (0, "text"), (0, b"x" * (BLOB_CHUNK_BYTES + 1))],
    ids=["negative", "boolean", "empty", "not-bytes", "oversize"],
)
def test_invalid_append_bounds_leave_offset_unchanged(ready, offset, data):
    service, a, _, _ = ready
    declared = manifest(b"abcdefgh")
    identity = service.blob_begin(a, declared)["upload_id"]
    with pytest.raises(ValueError):
        service.blob_append(a, identity, offset, data)
    assert service.blob_begin(a, declared)["offset"] == 0


@pytest.mark.parametrize(
    "offset,limit", [(-1, 1), (True, 1), (9, 1), (0, 0), (0, True), (0, BLOB_CHUNK_BYTES + 1)]
)
def test_invalid_read_bounds_fail_closed(ready, offset, limit):
    service, a, _, _ = ready
    declared, _ = upload(service, a, b"abcdefgh")
    with pytest.raises(ValueError):
        read(service, a, declared, offset=offset, limit=limit)


def test_committed_corrupt_bytes_are_never_exposed_or_republished(ready):
    service, a, _, _ = ready
    declared, _ = upload(service, a, b"original")
    with service._transaction() as conn:
        path = service._blob_owned_path(conn, "workspace", service._manifest(declared))
    path.write_bytes(b"tampered")
    with pytest.raises(BlobUnavailableError):
        read(service, a, declared)
    with pytest.raises(BlobUnavailableError):
        service.blob_begin(a, declared)


def test_failed_begin_keeps_namespace_and_physical_reservation_recoverable(tmp_path, monkeypatch):
    from paper_daily.sync_blobs import BlobStore

    service = ReferenceService(
        tmp_path / "authority.sqlite", blob_root=tmp_path / "bytes", blob_quota_bytes=10
    )
    token = service.enroll("workspace", "a")
    declared = manifest(b"123456")
    original = BlobStore.begin

    def interrupted(store, item):
        original(store, item)
        raise RuntimeError("simulated begin interruption")

    monkeypatch.setattr(BlobStore, "begin", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        service.blob_begin(token, declared)
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_namespaces").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sync_workspace_blobs").fetchone()[0] == 0
    monkeypatch.setattr(BlobStore, "begin", original)
    # Even the unacknowledged reservation remains counted in physical quota.
    with pytest.raises(BlobQuotaError):
        service.blob_begin(token, manifest(b"abcdef"))
    resumed = service.blob_begin(token, declared)
    assert resumed["offset"] == 0
    service.blob_cancel(token, resumed["upload_id"])
    assert service.blob_begin(token, manifest(b"abcdef"))["offset"] == 0


def test_committed_bytes_remain_reserved_and_deduplicated_within_workspace(tmp_path):
    service = ReferenceService(
        tmp_path / "authority.sqlite", blob_root=tmp_path / "bytes", blob_quota_bytes=10
    )
    token = service.enroll("workspace", "a")
    declared, _ = upload(service, token, b"123456")
    assert service.blob_begin(token, declared)["complete"]
    with pytest.raises(BlobQuotaError):
        service.blob_begin(token, manifest(b"abcdef"))
    assert read(service, token, declared) == b"123456"


def test_session_info_proves_exact_binding_without_storage_or_state_changes(ready):
    service, a, b, other = ready
    with closing(sqlite3.connect(service.path)) as conn:
        before = list(conn.iterdump())
    assert service.session_info(a) == {"workspace_id": "workspace", "device_id": "a"}
    assert service.session_info(b) == {"workspace_id": "workspace", "device_id": "b"}
    assert service.session_info(other) == {"workspace_id": "other", "device_id": "a"}
    changed = service.session_info(a)
    changed["workspace_id"] = "forged"
    assert service.session_info(a) == {"workspace_id": "workspace", "device_id": "a"}
    with closing(sqlite3.connect(service.path)) as conn:
        assert list(conn.iterdump()) == before
    assert not service.blob_root.exists()


@pytest.mark.parametrize(
    "token",
    [None, 123, "", "bogus", "x" * 4097],
    ids=["none", "numeric", "empty", "unknown", "oversized"],
)
def test_session_info_rejects_bogus_credentials(ready, token):
    service, _, _, _ = ready
    with pytest.raises(PermissionError):
        service.session_info(token)


def test_session_info_reauthenticates_after_revocation_and_when_blobs_disabled(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "device")
    assert service.session_info(token) == {"workspace_id": "workspace", "device_id": "device"}
    service.revoke(token)
    with pytest.raises(PermissionError):
        service.session_info(token)
