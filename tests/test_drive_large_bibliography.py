"""Exercise the large bibliography with two independent databases and synthetic Drive."""

import sqlite3
from contextlib import closing

import pytest
from test_drive_sync_authority import Cloud, authority
from test_library_selection import selection
from test_workspace_enrollment import STAMP
from test_workspace_enrollment import source as source_fixture

from paper_daily.drive_library_directory import DriveDirectory
from paper_daily.drive_list_history import DriveListPapers
from paper_daily.drive_paper_baseline import publish_initial
from paper_daily.drive_paper_receive import receive_initial
from paper_daily.library_directory import ListEntry
from paper_daily.store import SCHEMA
from paper_daily.workspace_service import Ticket

source = source_fixture


def add_paper(conn, number):
    key = f"example-{number}"
    conn.execute(
        "INSERT INTO papers(id,title,title_key,venue,year,source,abstract) "
        "VALUES(?,?,?,'Fixture',2026,'fixture',?)",
        (key, key, key, "Synthetic abstract. " * 40),
    )
    conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                 "VALUES('list',?,?,?)", (key, number, STAMP))


def titles(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT p.title FROM list_papers m JOIN papers p ON p.id=m.paper_id "
                            "WHERE m.list_id='list' ORDER BY m.position").fetchall()


def test_large_list_resumes_and_accepts_offline_addition(source, tmp_path, monkeypatch):
    laptop = tmp_path / "laptop" / "papers.db"
    laptop.parent.mkdir()
    with closing(sqlite3.connect(laptop)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO lists VALUES('list','Example',NULL,?)", (STAMP,))
    with closing(sqlite3.connect(source)) as conn, conn:
        for i in range(1, 5010):
            add_paper(conn, i)
    files = authority(Cloud(), tmp_path / "authority").files
    directory = DriveDirectory(files, *files.new_ids(2), "library")
    catalog = directory.upsert(directory.initialize("Library"),
                               [ListEntry("list", "Example", False)]).directory
    desktop = selection(source, tmp_path / "desktop-settings", device_id="desktop")
    mac = selection(laptop, tmp_path / "mac-settings")
    for store in (desktop, mac):
        store.save(catalog, ["list"], expected_revision=0)
    append = DriveListPapers.append

    def interrupt(self, expected, records, *, revision):
        head = append(self, expected, records, revision=revision)
        if head.generation == 2:
            raise ConnectionError("Lost acknowledgment")
        return head

    with monkeypatch.context() as patch:
        patch.setattr(DriveListPapers, "append", interrupt)
        with pytest.raises(ConnectionError):
            publish_initial(directory, desktop, "list", 1, Ticket())
    head = publish_initial(directory, desktop, "list", 1, Ticket())
    assert head.generation == 21
    assert directory.read().directory.lists[0].extended_papers
    for store in (desktop, mac):
        assert receive_initial(directory, store, "list", 1, Ticket()) == head
    expected = titles(source)
    assert len(expected) == 5010 and titles(laptop) == expected
    with closing(sqlite3.connect(laptop)) as conn, conn:
        add_paper(conn, 5010)
    changed = publish_initial(directory, mac, "list", 1, Ticket(), append_new=True)
    assert changed.generation == head.generation + 1
    assert receive_initial(directory, desktop, "list", 1, Ticket()) == changed
    assert titles(source) == expected + [("example-5010",)]
