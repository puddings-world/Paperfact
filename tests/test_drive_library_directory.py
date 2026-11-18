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
