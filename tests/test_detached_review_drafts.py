"""Independent recovery exposes saved drafts without consulting their old workspace."""

import json
from contextlib import closing
from pathlib import Path

import pytest
from test_enrollment_review_draft_journey import decision as decision
from test_enrollment_review_draft_journey import draft_variants as draft_variants
from test_enrollment_review_draft_journey import prepare
from test_enrollment_review_draft_journey import source as source
from test_research_review import workspace as workspace
from test_review_dialog import app as app

from paper_daily import sync_recovery
from paper_daily.research_review import ResearchReview


def test_detached_draft_variants_remain_readable_without_the_old_workspace(
    draft_variants, tmp_path, monkeypatch
):
    import sqlite3

    value = draft_variants
    result = prepare(value, tmp_path)
    restored = tmp_path / "detached-readable"
    sync_recovery.restore_detached(result["backup"], restored)
    original_bytes = value["database"].read_bytes()
    native_connect, native_open = sqlite3.connect, Path.open
    old_root = value["database"].parent.resolve()
    old_database = value["database"].as_posix().lower()

    def connect(database, *args, **kwargs):
        if old_database in str(database).replace("\\", "/").lower():
            pytest.fail("Detached review followed the original database path")
        return native_connect(database, *args, **kwargs)

    def opened(path, *args, **kwargs):
        if path.resolve().is_relative_to(old_root):
            pytest.fail("Detached review opened the original workspace")
        return native_open(path, *args, **kwargs)

    with monkeypatch.context() as patches:
        patches.setattr(sqlite3, "connect", connect)
        patches.setattr(Path, "open", opened)
        review = ResearchReview(restored / "papers.db")
        try:
            page = review.page(limit=100)
            items = [row for row in page["items"] if row["origin"] == "archived_draft"]
            assert len(items) == 2
            exports = [
                review.export_text(review.preview(row["origin"], row["id"])) for row in items
            ]
            assert any("First saved human interpretation" in text for text in exports)
            assert any("Second independent draft" in text for text in exports)
            assert all(str(value["database"]) not in text for text in exports)
        finally:
            review.close()
    assert value["database"].read_bytes() == original_bytes


@pytest.fixture
def restored_drafts(draft_variants, tmp_path):
    result = prepare(draft_variants, tmp_path)
    folder = tmp_path / "restored-reader"
    sync_recovery.restore_detached(result["backup"], folder)
    return draft_variants, result, folder / "papers.db"


def _recovery_rows(database):
    import sqlite3

    with closing(sqlite3.connect(database)) as conn:
        return conn.execute(
            "SELECT table_name,row_number,data FROM recovery_records ORDER BY table_name,row_number"
        ).fetchall()


def test_mixed_live_and_recovery_carriers_are_deduplicated_and_paginate_without_writes(
    restored_drafts,
):
    import sqlite3

    from paper_daily import enrollment_history

    _value, result, recovered = restored_drafts
    database = Path(result["database"])
    carriers = _recovery_rows(recovered)
    draft_rows = [
        row
        for row in carriers
        if row[0] == enrollment_history.TABLE
        and json.loads(row[2])["protocol"] == "research_review_drafts"
    ]
    assert len(draft_rows) == 2
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "CREATE TABLE recovery_records(table_name TEXT NOT NULL,"
            "row_number INTEGER NOT NULL,data TEXT NOT NULL,"
            "PRIMARY KEY(table_name,row_number))"
        )
        conn.executemany("INSERT INTO recovery_records VALUES(?,?,?)", carriers)
        generic_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT rowid,data FROM recovery_records WHERE table_name=?",
                (enrollment_history.TABLE,),
            )
            if json.loads(row[1])["protocol"] == "research_review_drafts"
        }
    before = _recovery_rows(database)
    review = ResearchReview(database)
    try:
        keys, cursor = [], None
        for _ in range(100):
            page = review.page(after=cursor, limit=1)
            keys.extend((row["origin"], row["id"]) for row in page["items"])
            cursor = page["next"]
            if cursor is None:
                break
        else:
            pytest.fail("Historical draft pagination never reached its end")
        draft_ids = [identity for origin, identity in keys if origin == "archived_draft"]
        assert len(draft_ids) == len(set(draft_ids)) == 2
        assert not any(
            origin == "recovery" and identity in generic_ids for origin, identity in keys
        )
        bodies = {
            json.loads(review.export_text(review.preview("archived_draft", identity)))["content"][
                "body"
            ]
            for identity in draft_ids
        }
        assert bodies == {"First saved human interpretation", "Second independent draft"}
        assert [(row["origin"], row["id"]) for row in review.page(limit=100)["items"]] == keys
    finally:
        review.close()
    assert _recovery_rows(database) == before


@pytest.mark.parametrize("change", ["extra", "duplicate", "wrong_identity"])
def test_damaged_recovery_draft_carrier_refuses_reading_without_rewriting_history(
    restored_drafts, change
):
    import sqlite3

    _value, _result, database = restored_drafts
    with closing(sqlite3.connect(database)) as conn, conn:
        identity, raw = next(
            (row[0], row[1])
            for row in conn.execute(
                "SELECT rowid,data FROM recovery_records "
                "WHERE table_name='research_history_archive'"
            )
            if json.loads(row[1])["protocol"] == "research_review_drafts"
        )
        packet = json.loads(raw)
        if change == "extra":
            packet["authority"] = "not an allowed carrier field"
            damaged = json.dumps(packet)
        elif change == "wrong_identity":
            packet["record_id"] = "0" * 64
            damaged = json.dumps(packet)
        else:
            damaged = raw[:-1] + ',"record_id":' + json.dumps(packet["record_id"]) + "}"
        conn.execute("UPDATE recovery_records SET data=? WHERE rowid=?", (damaged, identity))
    before = _recovery_rows(database)
    review = ResearchReview(database)
    try:
        with pytest.raises(ValueError):
            review.page(limit=100)
    finally:
        review.close()
    assert _recovery_rows(database) == before


@pytest.mark.parametrize("budget", ["carrier", "records", "bytes"])
def test_recovery_draft_inventory_bounds_refuse_without_truncation_or_mutation(
    restored_drafts, monkeypatch, budget
):
    from paper_daily import archived_review_drafts, enrollment_history

    _value, _result, database = restored_drafts
    before = _recovery_rows(database)
    if budget == "carrier":
        monkeypatch.setattr(archived_review_drafts, "MAX_CARRIER", 1)
    elif budget == "records":
        monkeypatch.setattr(enrollment_history, "MAX_RECORDS", 1)
    else:
        monkeypatch.setattr(enrollment_history, "MAX_TOTAL", 1)
    review = ResearchReview(database)
    try:
        with pytest.raises(ValueError):
            review.page(limit=100)
    finally:
        review.close()
    assert _recovery_rows(database) == before


def test_pretty_printed_recovery_wrapper_preserves_exact_draft_text(restored_drafts):
    import sqlite3

    _value, _result, database = restored_drafts
    with closing(sqlite3.connect(database)) as conn, conn:
        rows = list(
            conn.execute(
                "SELECT rowid,data FROM recovery_records "
                "WHERE table_name='research_history_archive'"
            )
        )
        for identity, raw in rows:
            if json.loads(raw)["protocol"] == "research_review_drafts":
                conn.execute(
                    "UPDATE recovery_records SET data=? WHERE rowid=?",
                    (json.dumps(json.loads(raw), indent=3), identity),
                )
    before = _recovery_rows(database)
    review = ResearchReview(database)
    try:
        items = [
            row for row in review.page(limit=100)["items"] if row["origin"] == "archived_draft"
        ]
        exports = [review.export_text(review.preview(row["origin"], row["id"])) for row in items]
        assert len(items) == 2
        assert any("First saved human interpretation" in text for text in exports)
        assert any("Second independent draft" in text for text in exports)
    finally:
        review.close()
    assert _recovery_rows(database) == before


def test_workspace_without_either_draft_carrier_is_empty_and_unknown_draft_is_unavailable(source):
    review = ResearchReview(source)
    try:
        assert review.page() == {"items": [], "next": None}
        with pytest.raises(ValueError, match="unavailable"):
            review.preview("archived_draft", "0" * 64)
    finally:
        review.close()


@pytest.fixture
def raw_restored_drafts(workspace, tmp_path):
    from test_research_review import candidate

    database, _client = workspace
    review = ResearchReview(database)
    try:
        identity = candidate(database)
        preview = review.preview("generation", identity)
        review.save_draft(preview, "Raw first draft", "shared-raw-request")
        review.save_draft(preview, "Raw second draft", "shared-raw-request")
    finally:
        review.close()
    package = tmp_path / "raw-review-backup.zip"
    sync_recovery.create(database, package)
    folder = tmp_path / "raw-review-restored"
    sync_recovery.restore_detached(package, folder)
    return database, folder / "papers.db"


def test_direct_backup_drafts_use_the_same_readable_identity_without_activating_old_state(
    raw_restored_drafts,
):
    import sqlite3

    from paper_daily import enrollment_history

    original, database = raw_restored_drafts
    with closing(sqlite3.connect(original)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM research_review_drafts")]
    expected = {enrollment_history.wrap("research_review_drafts", row)["record_id"] for row in rows}
    before = _recovery_rows(database)
    review = ResearchReview(database)
    try:
        page = review.page(limit=100)
        items = [row for row in page["items"] if row["origin"] == "archived_draft"]
        assert {row["id"] for row in items} == expected
        bodies = {
            json.loads(review.export_text(review.preview(row["origin"], row["id"])))["content"][
                "body"
            ]
            for row in items
        }
        assert bodies == {"Raw first draft", "Raw second draft"}
        with closing(sqlite3.connect(database)) as conn:
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_review_drafts'"
            ).fetchone()
    finally:
        review.close()
    assert _recovery_rows(database) == before


@pytest.mark.parametrize(
    "language,label", [("en", "Saved historical draft"), ("zh-TW", "已存歷史草稿")]
)
def test_detached_window_reads_copies_exports_and_cancels_without_creating_edit_state(
    restored_drafts, tmp_path, app, monkeypatch, language, label
):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog
    from test_review_dialog import opened, wait

    value, _result, database = restored_drafts
    before = _recovery_rows(database)
    view = opened(app, database, language=language)
    try:
        entries = [
            index
            for index in range(view.list.count())
            if view.list.item(index).data(Qt.ItemDataRole.UserRole)[0] == "archived_draft"
        ]
        assert len(entries) == 2
        seen = set()
        for position, index in enumerate(entries):
            item = view.list.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)[1]
            assert item.text().startswith(label + " · ")
            view.list.setCurrentRow(index)
            wait(app, lambda key=key: view.preview is not None and view.preview.data["id"] == key)
            assert (
                view.draft.isReadOnly() and not view.keep.isEnabled() and not view.apply.isEnabled()
            )
            body = view.draft.toPlainText()
            seen.add(body)
            view.copy.click()
            assert json.loads(app.clipboard().text())["content"] == body
            output = tmp_path / f"draft-{position}.txt"
            monkeypatch.setattr(
                QFileDialog,
                "getSaveFileName",
                lambda *_args, output=output, **_kwargs: (str(output), "Text"),
            )
            view.export_button.click()
            exported = output.read_text(encoding="utf-8")
            assert json.loads(exported)["content"] == body
            assert str(value["database"]) not in exported and "database_identity" not in exported
        assert seen == {"First saved human interpretation", "Second independent draft"}
        existing_files = {path.name for path in tmp_path.glob("draft-*.txt")}
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
        for _ in range(3):
            view.export_button.click()
        assert {path.name for path in tmp_path.glob("draft-*.txt")} == existing_files
        assert not view.busy
    finally:
        view.reject()
        wait(app, lambda: view.disposed)
    assert _recovery_rows(database) == before


def test_closing_during_detached_draft_load_drains_without_late_delivery_or_writes(
    restored_drafts, app, monkeypatch
):
    import threading

    from test_review_dialog import wait

    from paper_daily.desktop.review_dialog import ReviewDialog

    _value, _result, database = restored_drafts
    before = _recovery_rows(database)
    service = ResearchReview(database)
    entered, release = threading.Event(), threading.Event()
    original = service.preview

    def held(origin, identity):
        if origin == "archived_draft":
            entered.set()
            release.wait(5)
        return original(origin, identity)

    monkeypatch.setattr(service, "preview", held)
    view = ReviewDialog(service=service)
    view.show()
    try:
        wait(app, entered.is_set)
        future = view.jobs[-1][0]
        view.reject()
        release.set()
        with pytest.raises(ValueError, match="closed"):
            future.result(timeout=5)
        assert view.disposed and view.preview is None
    finally:
        release.set()
        view.reject()
    assert _recovery_rows(database) == before
