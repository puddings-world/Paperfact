"""Drive library metadata can travel in both directions without copying research."""

import pytest
from test_drive_sync_authority import Cloud, authority

from paper_daily.drive_library_directory import DriveDirectory
from paper_daily.drive_sync_files import DriveChanged
from paper_daily.library_directory import ListEntry


def test_partial_device_updates_shared_directory_without_losing_other_lists(tmp_path):
    cloud = Cloud()
    left_files = authority(cloud, tmp_path / "left").files
    right_files = authority(cloud, tmp_path / "right").files
    folder, head = left_files.new_ids(2)
    left = DriveDirectory(left_files, folder, head, "personal")
    initial = left.initialize("Personal library")
    first = ListEntry("a", "First list", True)
    second = ListEntry("b", "Second list", False)
    left.upsert(initial, [first, second])

    assert right_files.workspaces() == []
    (descriptor,) = right_files.workspaces(directories=True)
    right = DriveDirectory(right_files, descriptor["folder_id"], descriptor["head_id"], "personal")
    old = right.read()
    assert old.directory.lists == (first, second)
    changed = ListEntry("a", "Updated on laptop", True)
    right.upsert(old, [changed])
    assert left.read().directory.lists == (changed, second)
    objects = len(cloud.objects)
    right.upsert(right.read(), [changed])
    assert len(cloud.objects) == objects
    competing = right.read()
    snapshot = left.read()
    new_second = ListEntry("b", "Updated on desktop", True)
    left.upsert(snapshot, [new_second])
    with pytest.raises(DriveChanged):
        right.upsert(competing, [ListEntry("a", "Stale laptop edit", True)])
    assert right.read().directory.lists == (changed, new_second)


def test_login_and_device_choices_do_not_transfer_papers(tmp_path, monkeypatch):
    from test_library_selection import database

    from paper_daily import drive_sync_setup as setup_module
    from paper_daily.workspace_service import Ticket

    cloud = Cloud()
    desktop, mac = (database(tmp_path / "windows"), database(tmp_path / "mac", both=False))
    before = [path.read_bytes() for path in (desktop, mac)]
    files = [authority(cloud, tmp_path / name).files for name in ("left", "right")]

    def setup(path, i):
        setup = setup_module.DriveSetup(
            path,
            profiles=tmp_path / str(i) / "profiles",
            cache=tmp_path / str(i) / "cache",
            authorize=lambda **_: files[i].session,
        )
        monkeypatch.setattr(setup_module, "DriveFiles", lambda *a, **k: files[i])
        return setup, setup.sign_in(Ticket(), lambda _: None)["library"]["items"]

    def choices(items):
        return {item["id"]: item["selected"] for item in items}

    left, initial = setup(desktop, 0)
    assert choices(initial) == {"a": False, "b": False} and not cloud.objects
    left.save_library(["a", "b"], Ticket(), lambda _: None)
    right, rows = setup(mac, 1)
    assert choices(rows) == {"a": False, "b": False}
    assert choices(right.save_library(["b"], Ticket(), lambda _: None)["items"]) == {
        "a": False,
        "b": True,
    }
    count = len(cloud.objects)
    assert choices(right.save_library([], Ticket(), lambda _: None)["items"]) == {
        "a": False,
        "b": False,
    }
    assert choices(left.read_library(Ticket())["items"]) == {"a": True, "b": True}
    assert len(cloud.objects) == count
    assert before == [path.read_bytes() for path in (desktop, mac)]
    assert all(b"private research" not in raw for _, raw in cloud.objects.values())


def test_each_device_receives_only_its_selected_list_history(tmp_path):
    from test_library_selection import database, selection
    from test_sync_service import operation

    from paper_daily.drive_list_history import DriveListHistory

    cloud = Cloud()
    windows = authority(cloud, tmp_path / "left").files
    mac = authority(cloud, tmp_path / "right").files
    folder, head = windows.new_ids(2)
    left = DriveDirectory(windows, folder, head, "library")
    right = DriveDirectory(mac, folder, head, "library")
    first, second = ListEntry("a", "A", False), ListEntry("b", "B", False)
    catalog = left.upsert(left.initialize("Catalog"), [first, second]).directory
    desktop = selection(database(tmp_path / "win"), tmp_path / "win-settings")
    laptop = selection(database(tmp_path / "mac"), tmp_path / "mac-settings")
    desktop.save(catalog, ["a", "b"], expected_revision=0)
    laptop.save(catalog, ["b"], expected_revision=0)

    def edit(identity, list_id, text, device):
        return dict(
            operation(identity, workspace="library", device=device, entity=list_id),
            entity_type="list",
            payload={"name": list_id, "note": text},
        )

    a = DriveListHistory(left, desktop, "a")
    b = DriveListHistory(left, desktop, "b")
    private = a.append(None, [edit("private", "a", "Unselected research", "win")], revision=1)
    op = edit("win-edit", "b", "First text", "win")
    initial = b.append(None, [op], revision=1)
    changes = DriveListHistory(right, laptop, "b")
    read = []
    original = mac.read_small

    def record(ref, *args):
        read.append(ref["id"])
        return original(ref, *args)

    mac.read_small = record
    assert changes.changes(None, revision=1) == (initial, [op])
    edited = edit("offline-edit", "b", "Edited on Mac", "mac")
    updated = changes.append(initial, [edited], revision=1)
    count = len(cloud.objects)
    assert changes.append(initial, [edited], revision=1) == updated
    assert count == len(cloud.objects)
    assert b.changes(initial, revision=1) == (updated, [edited])
    with pytest.raises(DriveChanged):
        b.append(initial, [op], revision=1)
    assert private.id not in read
    laptop.save(right.read().directory, [], expected_revision=1)
    before = list(read)
    with pytest.raises(ValueError, match="selection"):
        changes.changes(initial, revision=1)
    assert read == before


def test_selected_list_records_arrive_in_original_reader_database_and_return(tmp_path):
    import sqlite3
    from contextlib import closing

    from test_library_selection import database, selection

    from paper_daily.drive_list_records import exchange_list
    from paper_daily.workspace_service import Ticket

    cloud = Cloud()
    files = authority(cloud, tmp_path / "authority").files
    folder, head = files.new_ids(2)
    remote = DriveDirectory(files, folder, head, "library")
    cat = remote.upsert(
        remote.initialize("Library"), [ListEntry("a", "A", False), ListEntry("b", "B", False)]
    ).directory
    win_path, mac_path = database(tmp_path / "win"), database(tmp_path / "mac", both=False)

    def db(path, query, params=()):
        with closing(sqlite3.connect(path)) as conn, conn:
            return conn.execute(query, params).fetchall()

    for path in (win_path, mac_path):
        db(path, "ALTER TABLE lists ADD COLUMN note TEXT")
        db(path, "ALTER TABLE lists ADD COLUMN created_at TEXT")
    win = selection(win_path, tmp_path / "ws")
    mac = selection(mac_path, tmp_path / "ms")
    win.save(cat, ["a", "b"], expected_revision=0)
    mac.save(cat, ["b"], expected_revision=0)

    def sync(store, list_id="b"):
        return exchange_list(remote, store, list_id, store.load().revision, Ticket())

    db(win_path, "UPDATE lists SET note='Windows list description' WHERE id='b'")
    db(win_path, "UPDATE lists SET note='Unselected description' WHERE id='a'")
    sync(win, "a")
    sync(win)
    sync(mac)
    assert db(mac_path, "SELECT id,note FROM lists ORDER BY id") == [
        ("a", None),
        ("b", "Windows list description"),
    ]
    db(mac_path, "UPDATE lists SET note='Changed offline on the Mac' WHERE id='b'")
    sync(mac)
    sync(win)
    assert db(win_path, "SELECT note FROM lists WHERE id='b'") == [("Changed offline on the Mac",)]
    count = len(cloud.objects)
    assert sync(win) == "current" and len(cloud.objects) == count
    db(win_path, "UPDATE lists SET note='Local candidate' WHERE id='b'")
    db(mac_path, "UPDATE lists SET note='Remote candidate' WHERE id='b'")
    sync(mac)
    with pytest.raises(ValueError, match="both versions"):
        sync(win)
    assert db(win_path, "SELECT note FROM lists WHERE id='b'") == [("Local candidate",)]
