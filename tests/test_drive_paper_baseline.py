"""Publish a real local reader's selected bibliography through an isolated Drive transport."""

import sqlite3
from contextlib import closing

import pytest
from test_drive_sync_authority import Cloud, authority
from test_library_selection import selection
from test_workspace_enrollment import STAMP
from test_workspace_enrollment import source as source_fixture

from paper_daily.drive_library_directory import DriveDirectory
from paper_daily.drive_list_history import DriveListPapers
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_paper_baseline import initial_batches, publish_initial
from paper_daily.library_directory import ListEntry
from paper_daily.workspace_service import Ticket

source = source_fixture


def test_shared_paper_identity_and_interrupted_source_publication(source, tmp_path, monkeypatch):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO lists VALUES('other','Other',NULL,?)", (STAMP,))
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('other','paper',0,?)",
            (STAMP,),
        )
        for i in range(51):
            key = f"extra-{i}"
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) "
                "VALUES(?,?,?,'Fixture',2026,'fixture')",
                (key, key, key),
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,?,?)",
                ("list" if i != 50 else "other", key, i + 1, STAMP),
            )
    store = selection(source, tmp_path / "settings")
    files = authority(Cloud(), tmp_path / "authority").files
    folder, head = files.new_ids(2)
    directory = DriveDirectory(files, folder, head, "library")
    cat = directory.upsert(
        directory.initialize("Library"),
        [ListEntry("list", "Selected", False), ListEntry("other", "Other", False)],
    ).directory
    store.save(cat, ["list", "other"], expected_revision=0)
    before = source.read_bytes()
    batches = initial_batches(store, "list", 1, Ticket())
    other = initial_batches(store, "other", 1, Ticket())
    assert [len(batch) for batch in batches] == [100, 2]
    assert batches[0][0]["entity_id"] == other[0][0]["entity_id"]
    assert batches[0][1]["entity_id"] != other[0][1]["entity_id"]
    original = DriveListPapers.append

    def lose_ack(self, expected, records, *, revision):
        result = original(self, expected, records, revision=revision)
        if expected is None:
            raise ConnectionError("lost acknowledgement")
        return result

    monkeypatch.setattr(DriveListPapers, "append", lose_ack)
    with pytest.raises(ConnectionError):
        publish_initial(directory, store, "list", 1, Ticket())
    monkeypatch.setattr(DriveListPapers, "append", original)
    accepted = publish_initial(directory, store, "list", 1, Ticket())
    history = DriveListPapers(directory, store, "list")
    actual, operations = history.changes(None, revision=1)
    assert actual == accepted and accepted.generation == 2
    assert operations == batches[0] + batches[1]
    assert all(op["payload"].get("title") != "extra-50" for op in operations)
    assert publish_initial(directory, store, "list", 1, Ticket()) == accepted
    assert source.read_bytes() == before
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE papers SET title='Offline edit' WHERE id='paper'")
    with pytest.raises(ListReviewRequired, match="reconcile"):
        publish_initial(directory, store, "list", 1, Ticket())
    assert history.changes(accepted, revision=1) == (accepted, [])


def test_reader_selection_publishes_receives_and_preserves_local_edits(
    source, tmp_path, monkeypatch
):
    from paper_daily import drive_sync_setup
    from paper_daily import store as db

    laptop = tmp_path / "laptop" / "papers.db"
    laptop.parent.mkdir()
    with closing(sqlite3.connect(laptop)) as conn, conn:
        conn.executescript(db.SCHEMA)
    cloud = Cloud()

    def login(path, label):
        files = authority(cloud, tmp_path / label / "authority").files
        monkeypatch.setattr(drive_sync_setup, "DriveFiles", lambda *a, **k: files)
        service = drive_sync_setup.DriveSetup(
            path,
            profiles=tmp_path / label / "profiles",
            cache=tmp_path / label / "cache",
            authorize=lambda **kwargs: files.session,
        )
        service.sign_in(Ticket(), lambda _: None)
        return service

    def sync(device):
        return device.apply_library(["list"], Ticket(), lambda _: None)["reviews"]

    win = login(source, "desktop")
    assert sync(win) == {}
    mac = login(laptop, "laptop-settings")
    assert sync(mac) == {}
    with closing(sqlite3.connect(laptop)) as conn, conn:
        assert conn.execute(
            "SELECT title,position FROM papers JOIN list_papers ON papers.id=list_papers.paper_id"
        ).fetchall() == [("Research paper", 0)]
        conn.execute("UPDATE list_papers SET state='read'")
        conn.execute("UPDATE papers SET title='Offline local title'")
    # The confirmed head still gets checked. Re-saving a membership set already
    # published by this device must read neither old Drive batches nor paper payloads.
    from paper_daily import drive_paper_baseline

    read = mac.files.read_small
    history_reads = []

    def count_history(*args, **kwargs):
        raw = read(*args, **kwargs)
        if b'"format":"paperfact.list-paper-history.v1"' in raw:
            history_reads.append(len(raw))
        return raw

    def unexpected_snapshot(*args, **kwargs):
        pytest.fail("An unchanged bibliography was serialized again")

    with monkeypatch.context() as checks:
        checks.setattr(mac.files, "read_small", count_history)
        checks.setattr(drive_paper_baseline, "initial_batches", unexpected_snapshot)
        assert sync(mac) == {}
    assert history_reads == []
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('extra','Another','another','Fixture',2026,'fixture')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('list','extra',1,?)",
            (STAMP,),
        )
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO lists VALUES('private','Unreviewed local list',NULL,?)", (STAMP,))
    assert win.sync_saved_library(Ticket(), lambda _: None)["reviews"] == {}
    result = mac.sync_saved_library(Ticket(), lambda _: None)
    assert result["reviews"] == {}
    assert "private" not in {item["id"] for item in result["items"]}
    with closing(sqlite3.connect(laptop)) as conn:
        assert conn.execute(
            "SELECT title,state FROM papers JOIN list_papers "
            "ON papers.id=list_papers.paper_id ORDER BY position"
        ).fetchall() == [("Offline local title", "read"), ("Another", "pending")]
    # An overlap on the last record must roll back earlier rows and the checkpoint.
    with closing(sqlite3.connect(laptop)) as conn, conn:
        checkpoint = conn.execute("SELECT head FROM drive_library_bibliographies").fetchone()
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('independent','Overlap','overlap','Fixture',2026,'fixture')"
        )
    with closing(sqlite3.connect(source)) as conn, conn:
        for index, title in enumerate(("New record", "Overlap"), 2):
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) "
                "VALUES(?,?,?,'Fixture',2026,'fixture')",
                (str(index), title, db.title_key(title)),
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES('list',?,?,?)",
                (str(index), index, STAMP),
            )
    sync(win)
    assert "Possible existing paper" in sync(mac)["list"]
    with closing(sqlite3.connect(laptop)) as conn:
        assert (
            conn.execute("SELECT head FROM drive_library_bibliographies").fetchone() == checkpoint
        )
        assert not conn.execute("SELECT 1 FROM papers WHERE title='New record'").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM list_papers").fetchone() == (2,)
    # Put a received paper into a new list on the laptop. Its return to the
    # desktop must reuse the original paper even though the titles now differ.
    with closing(sqlite3.connect(laptop)) as conn, conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('return','Return',?)", (STAMP,))
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "SELECT 'return',paper_id,0,? FROM list_papers WHERE list_id='list' AND position=0",
            (STAMP,),
        )
    for device in (mac, win):
        device.read_library(Ticket())
        result = device.apply_library(["return"], Ticket(), lambda _: None)
        assert result["reviews"] == {}
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute(
            "SELECT p.id,p.title FROM list_papers m JOIN papers p ON p.id=m.paper_id "
            "WHERE m.list_id='return'"
        ).fetchall() == [("paper", "Research paper")]
        assert conn.execute("SELECT COUNT(*) FROM notes WHERE paper_id='paper'").fetchone() == (1,)
    # Both devices independently extend the same selected list while disconnected.
    for path, title in ((source, "Desktop discovery"), (laptop, "Laptop discovery")):
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) "
                "VALUES(?,?,?,'Fixture',2026,'fixture')",
                (title, title, db.title_key(title)),
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                "VALUES('return',?,1,?)",
                (title, STAMP),
            )
    for device in (win, mac, win, mac):
        assert device.apply_library(["return"], Ticket(), lambda _: None)["reviews"] == {}
    for path in (source, laptop):
        with closing(sqlite3.connect(path)) as conn:
            titles = conn.execute(
                "SELECT title FROM papers p JOIN list_papers m ON p.id=m.paper_id "
                "WHERE m.list_id='return'"
            ).fetchall()
            assert len(titles) == 3
            assert {("Desktop discovery",), ("Laptop discovery",)} <= set(titles)


def test_two_windows_exchange_offline_additions_after_closing_drive_settings(
    source, tmp_path, monkeypatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
    from test_sync_connection_dialog import wait

    from paper_daily import drive_sync_setup, store
    from paper_daily.desktop.drive_sync_dialog import DriveSyncDialog
    from paper_daily.workspace_sync import SyncSession

    app = QApplication.instance() or QApplication([])
    cloud = Cloud()
    laptop = tmp_path / "mac-research" / "papers.db"
    laptop.parent.mkdir()
    with closing(sqlite3.connect(laptop)) as conn:
        conn.executescript(store.SCHEMA)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    windows = []
    try:
        for label, path in (("win", source), ("mac", laptop)):
            files = authority(cloud, tmp_path / label / "authority").files
            monkeypatch.setattr(drive_sync_setup, "DriveFiles", lambda *a, f=files, **kw: f)
            setup = drive_sync_setup.DriveSetup(
                path, profiles=tmp_path / label / "profiles", cache=tmp_path / label / "cache",
                authorize=lambda f=files, **kw: f.session,
            )
            owner = QWidget()
            view = DriveSyncDialog(SyncSession(path), owner, owner=owner,
                                   service_factory=lambda *a, s=setup, **kw: s)
            windows.append((owner, view))
            view.show()
            view.login.click()
            wait(app, lambda v=view: not v.busy)
            for i in range(view.directory_lists.count()):
                row = view.directory_lists.item(i)
                if row.data(Qt.ItemDataRole.UserRole) == "list":
                    row.setCheckState(Qt.CheckState.Checked)
            view.save_selection.click()
            wait(app, lambda v=view: not v.busy)
            assert view.notes_toggle.isVisible() and not view.notes_toggle.isChecked()
            with monkeypatch.context() as cancel:
                cancel.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
                view.notes_toggle.click()
                assert not view.notes_toggle.isChecked()
            view.notes_toggle.click()
            wait(app, lambda v=view: not v.busy)
            assert view.notes_toggle.isChecked()
            view.keep_syncing.click()
            assert view.background.service is setup, (label, view.status.text())
            assert view.close()
            view.background.timer.stop()

        for path, key in ((source, "desktop-add"), (laptop, "laptop-add")):
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute(
                    "INSERT INTO papers(id,title,title_key,venue,year,source) "
                    "VALUES(?,?,?,'Fixture',2026,'fixture')", (key, key, key),
                )
                conn.execute(
                    "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                    "VALUES('list',?,1,?)", (key, STAMP),
                )
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("INSERT INTO lists VALUES('private','Keep local',NULL,?)", (STAMP,))

        with closing(sqlite3.connect(laptop)) as conn, conn:
            conn.execute(
                "INSERT INTO notes(paper_id,body,created_at,page) "
                "SELECT paper_id,'Laptop note',?,5 FROM list_papers "
                "WHERE list_id='list' AND position=0", (STAMP,)
            )
        for index in (0, 1, 0):
            runner = windows[index][1].background
            # Deliver a real timer event now instead of waiting half a minute.
            runner.timer.start(1)
            wait(app, lambda r=runner: r.state == "working")
            wait(app, lambda r=runner: r.worker is None)
            assert runner.state == "waiting" and runner.timer.interval() == 30000
        for path in (source, laptop):
            with closing(sqlite3.connect(path)) as conn:
                assert conn.execute(
                    "SELECT title,body,page FROM notes JOIN papers ON paper_id=papers.id "
                    "ORDER BY body"
                ).fetchall() == [
                    ("Research paper", "A research note", None),
                    ("Research paper", "Laptop note", 5),
                ]
                assert sorted(row[0] for row in conn.execute(
                    "SELECT title FROM papers JOIN list_papers ON papers.id=list_papers.paper_id "
                    "WHERE list_id='list'"
                )) == ["Research paper", "desktop-add", "laptop-add"]
        visible = windows[1][1].service.read_library(Ticket())
        assert all(item["id"] != "private" for item in visible["items"])
        owner, closed = windows[1]
        setup = closed.service
        monkeypatch.setattr(setup, "authorize", lambda **kwargs: pytest.fail("Repeated OAuth"))
        import threading

        entered, release = threading.Event(), threading.Event()
        exchange = setup.sync_saved_library

        def held(ticket, progress):
            entered.set()
            assert release.wait(8)
            return exchange(ticket, progress)

        monkeypatch.setattr(setup, "sync_saved_library", held)
        closed.background.tick()
        wait(app, entered.is_set)
        reopened = DriveSyncDialog(closed.session, owner, owner=owner)
        try:
            reopened.show()
            app.processEvents()
            assert reopened.directory_lists.count() == 0 and not reopened.login.isEnabled()
            release.set()
            wait(app, lambda: reopened.directory_lists.count() > 0 and not reopened.busy)
            assert reopened.account.text() == setup.account["email"]
            assert reopened.keep_syncing.isChecked()
            for i in range(reopened.directory_lists.count()):
                row = reopened.directory_lists.item(i)
                if row.data(Qt.ItemDataRole.UserRole) == "list":
                    assert row.checkState() == Qt.CheckState.Checked
                    row.setCheckState(Qt.CheckState.Unchecked)
            reopened.save_selection.click()
            wait(app, lambda: not reopened.busy)
            assert not reopened.keep_syncing.isChecked()
            assert not reopened.background.timer.isActive()
            assert reopened._saved_ids == set()
            assert not setup._library_view[1].load().selected
            with closing(sqlite3.connect(laptop)) as conn:
                assert conn.execute(
                    "SELECT count(*) FROM list_papers WHERE list_id='list'"
                ).fetchone() == (3,)
        finally:
            release.set()
            reopened.close()
    finally:
        for owner, view in windows:
            view.background.stop()
            wait(app, lambda v=view: v.background.worker is None)
            view.close()
            owner.close()


def test_ordinary_note_publication_keeps_anchor_scope_and_identity(source, tmp_path):
    import json

    from paper_daily.drive_list_history import DriveListNotes
    from paper_daily.drive_reader_notes import publish_reader_notes

    anchor = {"p0": 2, "o0": 4, "p1": 2, "o1": 9, "document_hash": "1" * 64}
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE notes SET page=3,anchor=?", (json.dumps(anchor),))
        conn.execute("INSERT INTO lists VALUES('other','Other',NULL,?)", (STAMP,))
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('other','paper',0,?)", (STAMP,))
        conn.execute("INSERT INTO papers(id,title,title_key,venue,year,source) "
                     "VALUES('private','Private','private','Fixture',2026,'fixture')")
        conn.execute("INSERT INTO notes(paper_id,body,created_at) VALUES('private','Private',?)",
                     (STAMP,))
    store = selection(source, tmp_path / "settings")
    cloud = Cloud()
    files = authority(cloud, tmp_path / "authority").files
    folder, root = files.new_ids(2)
    directory = DriveDirectory(files, folder, root, "library")
    keys = ["list", "other"]
    catalog = directory.upsert(directory.initialize("Research"), [
        ListEntry(key, key, False) for key in keys
    ]).directory
    store.save(catalog, keys, expected_revision=0)
    ids = []
    for key in keys:
        publish_initial(directory, store, key, 1, Ticket())
        with pytest.raises(PermissionError):
            publish_reader_notes(directory, store, key, 1, Ticket())
        store.set_note_sync(key, True, revision=1, ticket=Ticket())
        head = publish_reader_notes(directory, store, key, 1, Ticket())
        count = len(cloud.objects)
        assert publish_reader_notes(directory, store, key, 1, Ticket()) == head
        assert len(cloud.objects) == count
        history = DriveListNotes(directory, store, key, revision=1)
        _, records = history.changes(None, revision=1)
        assert len(records) == 1
        payload = records[0]["payload"]
        assert (payload["body"], payload["anchor"], payload["page"]) == (
            "A research note", anchor, 3
        )
        ids.append(records[0]["entity_id"])
    assert ids[0] == ids[1]
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE notes SET body='Offline edit' WHERE paper_id='paper'")
    count = len(cloud.objects)
    with pytest.raises(ListReviewRequired, match="retain both"):
        publish_reader_notes(directory, store, "list", 1, Ticket())
    assert len(cloud.objects) == count
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT body FROM notes WHERE paper_id='paper'").fetchone() == (
            "Offline edit",
        )
