import sqlite3

from test_sync_files import codec as codec_fixture
from test_sync_files import pair as artifact_pair_fixture
from test_sync_files import save_current
from test_sync_transfers import attach
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_sync import Native

from paper_daily import presentations, store
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_documents import applied_document
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession

transfer_setup = transfer_setup_fixture
artifact_pair = artifact_pair_fixture
codec = codec_fixture


def enable(client):
    conn = sqlite3.connect(client.journal.path, factory=CaptureConnection)
    try:
        conn.execute("BEGIN")
        install(conn, workspace_id="workspace", device_id=client.journal.device_id)
        conn.commit()
    finally:
        conn.close()


def session(client, authority, token, endpoint):
    enable(client)
    result = SyncSession(
        client.journal.path, transport_factory=lambda value: Native(value, authority, [])
    )
    result.connect(endpoint, "workspace", client.journal.device_id, token, Ticket())
    return result


def test_actual_manual_sync_transfers_pdf_bytes_and_binds_correct_version(transfer_setup, tmp_path):
    a, b, authority, ta, tb, stores, _, _, identity = transfer_setup
    operation, manifest, data = attach(transfer_setup, tmp_path, large=True)
    sa = session(a, authority, ta, "http://127.0.0.1:1")
    sb = session(b, authority, tb, "http://127.0.0.1:1")
    uploaded = sa.sync(Ticket())
    assert uploaded["pending"] == 0 and uploaded["attachments"]["failed"] == 0
    downloaded = sb.sync(Ticket())
    assert downloaded["attachments"]["pending"] == 0
    assert downloaded["attachments"]["steps"] >= 2
    assert stores[1].verified_path(manifest).read_bytes() == data
    conn = sqlite3.connect(b.journal.path)
    try:
        assert applied_document(conn, identity)["operation_id"] == operation["operation_id"]
    finally:
        conn.close()


def test_manual_sync_keeps_editable_deck_assets_and_speaker_notes(
    artifact_pair, codec, monkeypatch
):
    authority, a, b, _, _, ta, tb = artifact_pair
    value, _, _ = codec
    operation = save_current(artifact_pair, value)
    sa = session(a, authority, ta, "https://fixture.invalid")
    sb = session(b, authority, tb, "https://fixture.invalid")
    sent = sa.sync(Ticket())
    assert sent["pending"] == 0 and sent["attachments"]["failed"] == 0
    received = sb.sync(Ticket())
    assert received["attachments"]["pending"] == 0
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    loaded = presentations.load_deck("sync:" + operation["payload"]["paper_id"], "guide")
    assert loaded.slides[0].speaker_notes == "Speaker explanation"
    assert loaded.slides[0].elements[2]["text"] == "Editable"
    assert presentations.figure_bytes(loaded, "figure:1")
