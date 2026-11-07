"""Local review applies exact science explicitly; active files/receipt rollback together."""

import sqlite3
from contextlib import closing

import pytest
from test_local_deck_proposals import local as _local
from test_local_deck_proposals import prepared
from test_portable_deck_proposal import scientific as _scientific

from paper_daily import local_deck_proposals as catalog
from paper_daily import presentations
from paper_daily.research_review import ResearchReview, validate_receipt

local, scientific = _local, _scientific


def begin(local):
    database, _manifest, _blobs, saved, _before = local
    identity = catalog.retain(prepared(local))
    service = ResearchReview(database, presentation_root=saved.parents[1])
    preview = service.preview("local_deck", identity)
    assert not preview.data["apply"]
    verified = service.prepare_file(preview)
    assert verified.data["apply"] and verified.data["requires_confirmation"]
    return service, verified


def test_actual_local_review_cancel_apply_restart_and_exact_retry_preserve_science(
    local, scientific
):
    database, _manifest, _blobs, saved, before = local
    service, view = begin(local)
    try:
        assert view.data["current"]["title"] == "Prior saved deck"
        with pytest.raises(ValueError, match="Confirm"):
            service.decide(view, request_id="local-apply")
        assert saved.read_bytes() == before
        result = service.decide(view, request_id="local-apply", confirm_target=True)
        assert result == {"decision": "applied", "operation_id": None}
        current = presentations.load_deck("local-paper", "guide")
        assert current.title == scientific[0].title
        assert current.paper_id == "local-paper"
        assert current.slides[0].speaker_notes == scientific[0].slides[0].speaker_notes
        for key, value in scientific[2].items():
            assert presentations.figure_bytes(current, key) == value
        history = list((saved.parent / "history").glob("guide-review-*.json"))
        assert len(history) == 1 and history[0].read_bytes() == before
        snapshot = saved.read_bytes()
        for _ in range(25):
            assert service.decide(view, request_id="local-apply", confirm_target=True) == result
        assert saved.read_bytes() == snapshot
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory = sqlite3.Row
            receipts = conn.execute("SELECT * FROM research_review_receipts").fetchall()
            assert len(receipts) == 1 and validate_receipt(dict(receipts[0]))
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
            ).fetchone()
        info = database.stat()
        loaded = catalog.read(database, view.data["id"], expected_native=(info.st_dev, info.st_ino))
        assert loaded.content["image_bytes"] == scientific[2]
        assert loaded.content["original_bytes"] == scientific[3]
    finally:
        service.close()


def test_sql_receipt_denial_rolls_back_every_active_file_and_allows_retry(local, monkeypatch):
    database, _manifest, _blobs, saved, before = local
    service, view = begin(local)
    connect = service._connect
    try:

        def denied():
            conn = connect()

            def authorize(action, first, *_rest):
                return (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_INSERT and first == "research_review_receipts"
                    else sqlite3.SQLITE_OK
                )

            conn.set_authorizer(authorize)
            return conn

        prior = {
            str(p.relative_to(saved.parents[1])): p.read_bytes()
            for p in saved.parents[1].rglob("*")
            if p.is_file()
        }
        monkeypatch.setattr(service, "_connect", denied)
        with pytest.raises(sqlite3.DatabaseError):
            service.decide(view, request_id="receipt-retry", confirm_target=True)
        after = {
            str(p.relative_to(saved.parents[1])): p.read_bytes()
            for p in saved.parents[1].rglob("*")
            if p.is_file()
        }
        assert after == prior and saved.read_bytes() == before
        monkeypatch.setattr(service, "_connect", connect)
        assert (
            service.decide(view, request_id="receipt-retry", confirm_target=True)["decision"]
            == "applied"
        )
    finally:
        service.close()


@pytest.mark.parametrize("change", ["manual-save", "recreate", "close", "same-bytes-touch"])
def test_changed_local_review_context_preserves_current_deck(local, change):
    database, _manifest, _blobs, saved, before = local
    service, view = begin(local)
    try:
        if change == "manual-save":
            deck = presentations.load_deck("local-paper", "guide")
            deck.title = "Newer manual edit"
            presentations.save_deck(deck)
        elif change == "same-bytes-touch":
            saved.write_bytes(saved.read_bytes())
        elif change == "recreate":
            with closing(sqlite3.connect(database)) as conn, conn:
                row = conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone()
                conn.execute("DELETE FROM papers WHERE id='local-paper'")
                conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", row)
        else:
            service.close()
        expected = saved.read_bytes()
        with pytest.raises(ValueError):
            service.decide(view, request_id="stale-apply", confirm_target=True)
        assert saved.read_bytes() == expected
        if change == "same-bytes-touch":
            with pytest.raises(ValueError):
                service.decide(view, request_id="stale-apply", confirm_target=True)
    finally:
        service.close()


def test_same_lifetime_rename_can_be_reviewed_but_later_rename_invalidates_display(local):
    database, _manifest, _blobs, saved, before = local
    identity = catalog.retain(prepared(local))
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE papers SET title='Renamed local receiver' WHERE id='local-paper'")
    service = ResearchReview(database, presentation_root=saved.parents[1])
    try:
        view = service.prepare_file(service.preview("local_deck", identity))
        assert view.data["target"]["title"] == "Renamed local receiver"
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("UPDATE papers SET title='Newer name' WHERE id='local-paper'")
        with pytest.raises(ValueError, match="paper changed"):
            service.decide(view, request_id="renamed", confirm_target=True)
        assert saved.read_bytes() == before
    finally:
        service.close()
