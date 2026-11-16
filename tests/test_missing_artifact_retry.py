"""Exact artifact availability repair preserves editable research and ownership."""

import pytest
from test_sync_files import codec as codec
from test_sync_files import drain, png, save_current
from test_sync_files import pair as pair

from paper_daily import presentations, store
from paper_daily.sync_artifacts import applied_file, desired_file
from paper_daily.sync_blobs import BlobError, BlobManifest


def received(pair, codec):
    server, a, b, fa, fb, ta, tb = pair
    operation = save_current(pair, codec[0])
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    b.sync_once(server, tb)
    drain(lambda: fb.download(operation["entity_id"]), "bound")
    return operation


@pytest.mark.parametrize("part", ["body", "figure"])
def test_explicit_retry_restores_exact_artifact_without_revising_deck(
    pair, codec, monkeypatch, part
):
    operation = received(pair, codec)
    _, _, b, _, fb, ta, tb = pair
    row = (operation["payload"]["body"] if part == "body"
           else operation["payload"]["assets"][0])
    manifest = BlobManifest(row["sha256"], row["size"])
    expected = fb.store.verified_path(manifest).read_bytes()
    pending = b.journal.pending(1000)
    path = fb.store._path(manifest)
    path.unlink()
    with pytest.raises(BlobError, match="missing"):
        fb.download(operation["entity_id"])
    fb.set_session(ta)
    with pytest.raises(PermissionError, match="workspace/device"):
        fb.download(operation["entity_id"], retry=True)
    assert not path.exists()
    fb.set_session(tb)
    drain(lambda: fb.download(operation["entity_id"], retry=True), "bound")
    assert path.read_bytes() == expected
    with b.journal.transaction() as conn:
        assert desired_file(conn, operation["entity_id"]) == operation
        assert applied_file(conn, operation["entity_id"]) == operation
    assert b.journal.pending(1000) == pending
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    reopened = presentations.load_deck("sync:" + operation["payload"]["paper_id"], "guide")
    assert reopened.slides[0].speaker_notes == "Speaker explanation"
    assert reopened.slides[0].elements[2]["text"] == "Editable"
    assert presentations.figure_bytes(reopened, "figure:1") == png("red")
    assert fb.download(operation["entity_id"], retry=True)["state"] == "bound"
    assert b.journal.pending(1000) == pending


def test_explicit_artifact_retry_keeps_corrupt_final_for_review(pair, codec):
    operation = received(pair, codec)
    _, _, b, _, fb, _, _ = pair
    row = operation["payload"]["assets"][0]
    manifest = BlobManifest(row["sha256"], row["size"])
    path = fb.store._path(manifest)
    path.write_bytes(b"corrupt final attachment")
    pending = b.journal.pending(1000)
    with pytest.raises(BlobError, match="size|hash"):
        fb.download(operation["entity_id"], retry=True)
    assert path.read_bytes() == b"corrupt final attachment"
    with b.journal.transaction() as conn:
        assert desired_file(conn, operation["entity_id"]) == operation
        assert applied_file(conn, operation["entity_id"]) == operation
    assert b.journal.pending(1000) == pending
