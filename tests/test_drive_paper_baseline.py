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
