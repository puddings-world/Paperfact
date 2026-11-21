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
    assert sync(mac) == {}
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
    sync(win)
    assert sync(mac) == {}
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
