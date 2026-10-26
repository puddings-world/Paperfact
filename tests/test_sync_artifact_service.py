"""Owned, bounded artifact closure verification precedes authority publication."""

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_sync_blob_service import paper, upload
from test_sync_files import PAPER, codec  # noqa: F401
from test_sync_reading_state_service import op, ref

from paper_daily.sync_blob_service import BlobUnavailableError
from paper_daily.sync_files import file_id
from paper_daily.sync_service import ReferenceService


@pytest.fixture
def setup(tmp_path, codec):  # noqa: F811
    service = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "blobs")
    token = service.enroll("workspace", "a")
    # Keep the actual schema fixture while changing only the portable paper ID.
    source = paper(service, token)["operation"]
    source.update(operation_id="file-paper", entity_id=PAPER, incarnation="file-paper")
    service.push(token, source)
    _, payload, blobs = codec
    operation = op(
        "file-create",
        "research_file",
        file_id(PAPER, "deck", "guide"),
        payload,
        parents=[ref("paper", PAPER, "file-paper")],
    )
    return service, token, operation, blobs


def publish_bytes(service, token, blobs):
    for data in blobs.values():
        upload(service, token, data)


def test_owned_closure_required_and_retry_does_not_reread_bytes(setup, monkeypatch):
    service, token, operation, blobs = setup
    with pytest.raises(BlobUnavailableError):
        service.push(token, operation)
    assert len(service.pull(token)) == 2
    publish_bytes(service, token, blobs)
    event = service.push(token, operation)
    assert event["outcome"] == "accepted"
    monkeypatch.setattr(service, "_blob_owned_store", lambda *a: pytest.fail("retry read bytes"))
    assert service.push(token, operation) == event
    service.revoke(token)
    with pytest.raises(PermissionError):
        service.push(token, operation)


def test_known_hash_in_other_workspace_does_not_supply_ownership(setup):
    service, token, operation, blobs = setup
    other = service.enroll("other", "a")
    publish_bytes(service, other, blobs)
    with pytest.raises(BlobUnavailableError):
        service.push(token, operation)
    assert len(service.pull(token)) == 2


def test_full_closure_validation_runs_without_write_lock_and_reauthenticates(setup, monkeypatch):
    from paper_daily import sync_files

    service, token, operation, blobs = setup
    publish_bytes(service, token, blobs)
    original = sync_files.validate_closure

    def revoke(payload, reader):
        result = original(payload, reader)
        service.revoke(token)  # Would deadlock if closure held the authority write lock.
        return result

    monkeypatch.setattr(sync_files, "validate_closure", revoke)
    with pytest.raises(PermissionError):
        service.push(token, operation)
    assert service._prepare_research_file is not None


def test_bytes_changed_after_validation_cannot_publish(setup, monkeypatch):
    service, token, operation, blobs = setup
    publish_bytes(service, token, blobs)
    original = service._prepare_research_file

    def alter(*args):
        result = original(*args)
        path = next(iter(result[0].values()))[1]
        path.write_bytes(b"x" * path.stat().st_size)
        return result

    monkeypatch.setattr(service, "_prepare_research_file", alter)
    with pytest.raises(BlobUnavailableError):
        service.push(token, operation)
    assert len(service.pull(token)) == 2


def test_concurrent_same_operation_yields_one_stable_receipt(setup):
    service, token, operation, blobs = setup
    publish_bytes(service, token, blobs)
    with ThreadPoolExecutor(max_workers=4) as pool:
        events = list(pool.map(lambda _: service.push(token, operation), range(4)))
    assert events == [events[0]] * 4
    assert len(service.pull(token)) == 3
    changed = copy.deepcopy(operation)
    changed["payload"]["source_document_hash"] = "a" * 64
    with pytest.raises(ValueError, match="reused"):
        service.push(token, changed)


def test_hash_correct_invalid_body_has_no_event(setup):
    from paper_daily.sync_files import descriptor

    service, token, operation, blobs = setup
    invalid = b"{}"
    operation["payload"]["body"] = descriptor(invalid, "application/json")
    blobs[operation["payload"]["body"]["sha256"]] = invalid
    publish_bytes(service, token, blobs)
    with pytest.raises(ValueError):
        service.push(token, operation)
    assert len(service.pull(token)) == 2
