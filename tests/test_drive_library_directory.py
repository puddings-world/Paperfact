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
