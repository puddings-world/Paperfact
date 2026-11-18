"""Whole-library discovery and independent device intent without data transfer."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest

from paper_daily.device_list_selection import DeviceSelection, SelectionChanged
from paper_daily.library_directory import Directory, ListEntry, checklist, inspect_lists
from paper_daily.workspace_enrollment import _inventory_entries
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged


def database(root, *, both=True):
    root.mkdir()
    path = root / "papers.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE lists(id TEXT PRIMARY KEY,name TEXT)")
        conn.execute("INSERT INTO lists VALUES('a','Cataract')")
        if both:
            conn.execute("INSERT INTO lists VALUES('b','Quantization')")
        conn.execute("CREATE TABLE notes(body TEXT)")
        conn.execute("INSERT INTO notes VALUES('private research must not travel')")
    return path


def selection(path, root, **kwargs):
    return DeviceSelection(
        path,
        root=root,
        owner_id=kwargs.pop("owner_id", "owner"),
        library_id=kwargs.pop("library_id", "library"),
        device_id=kwargs.pop("device_id", "mac"),
        **kwargs,
    )


def test_remote_directory_lists_all_without_copying_research_or_claiming_sync(tmp_path):
    desktop = database(tmp_path / "desktop")
    mac = database(tmp_path / "mac", both=False)
    before = hashlib.sha256(desktop.read_bytes()).hexdigest()
    directory = inspect_lists(desktop, "library", generation=1, published=["a"])
    wire = directory.to_bytes()
    received = Directory.from_bytes(wire, library_id="library")
    assert [row.id for row in received.lists] == ["a", "b"]
    assert b"private research" not in wire and b"papers.db" not in wire
    assert hashlib.sha256(desktop.read_bytes()).hexdigest() == before
    local = inspect_lists(mac, "library")
    assert [row.id for row in local.lists] == ["a"]
    rows = checklist(received, ["b"], local_ids=["a"])
    assert [(row["id"], row["state"]) for row in rows] == [
        ("a", "retained_local"),
        ("b", "waiting_source"),
    ]
    ready = replace(
        received,
        generation=2,
        lists=(
            ListEntry("a", "Renamed cataract", True),
            ListEntry("b", "Quantization", True),
        ),
    )
    assert checklist(ready, ["b"], local_ids=["a"])[1]["state"] == "pending_download"
    with pytest.raises(ValueError):
        Directory.from_bytes(wire, library_id="different-library")
    with pytest.raises(ValueError):
        Directory.from_bytes(
            wire.replace(b'"published":true', b'"published":1'), library_id="library"
        )


def test_each_device_selects_independently_and_deselect_keeps_research(tmp_path):
    path = database(tmp_path / "research")
    before = path.read_bytes()
    directory = inspect_lists(path, "library", generation=1, published=["a", "b"])
    root = tmp_path / "settings"
    mac, desktop = selection(path, root), selection(path, root, device_id="desktop")
    assert not root.exists() and not mac.load().selected
    saved = mac.save(directory, ["b"], expected_revision=0)
    desktop.save(directory, ["a"], expected_revision=0)
    assert selection(path, root).load() == saved
    assert desktop.load().selected == {"a"} and mac.load().selected == {"b"}
    assert selection(path, root, owner_id="other-owner").load().revision == 0
    mac.save(directory, [], expected_revision=saved.revision)
    assert not mac.load().selected and desktop.load().selected == {"a"}
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="outside the research"):
        selection(path, path.parent / "library-sync")
    assert list(_inventory_entries(path.parent, Ticket())) == [path]


def test_duplicate_activation_is_idempotent_and_stale_intent_cannot_overwrite(tmp_path):
    path = database(tmp_path / "research")
    root = tmp_path / "settings"
    directory = inspect_lists(path, "library", generation=2, published=["a", "b"])
    stores = [selection(path, root), selection(path, root)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda store: store.save(directory, ["b"], expected_revision=0), stores)
        )
    assert results[0] == results[1] and results[0].revision == 1
    with pytest.raises(SelectionChanged):
        stores[0].save(directory, ["a"], expected_revision=0)
    assert stores[0].load().selected == {"b"}
    with pytest.raises(SelectionChanged):
        stores[0].save(replace(directory, generation=1), ["b"], expected_revision=1)
    renamed = replace(
        directory,
        lists=(
            ListEntry("a", "Changed", True),
            ListEntry("b", "Quantization", True),
        ),
    )
    with pytest.raises(SelectionChanged):
        stores[0].save(renamed, ["b"], expected_revision=1)
    with pytest.raises(ValueError):
        stores[0].save(directory, ["unknown"], expected_revision=1)


def test_cancel_failure_and_late_workspace_switch_preserve_saved_selection(tmp_path):
    path = database(tmp_path / "research")
    other = database(tmp_path / "other")
    current = [path]
    store = selection(path, tmp_path / "settings", current_path=lambda: current[0])
    directory = inspect_lists(path, "library", generation=1, published=["a", "b"])
    saved = store.save(directory, ["a"], expected_revision=0)
    cancelled = Ticket()
    cancelled.cancel()
    with pytest.raises(Cancelled):
        store.save(directory, ["b"], expected_revision=1, ticket=cancelled)

    class LateSwitch(Ticket):
        def publish(self, action):
            current[0] = other
            super().publish(action)

    with pytest.raises(WorkspaceChanged):
        store.save(directory, ["b"], expected_revision=1, ticket=LateSwitch())
    current[0] = path
    assert store.load() == saved
    # A failed publication rolls back and can be explicitly retried.
    restored = store.save(directory, ["b"], expected_revision=1)
    assert restored.revision == 2 and restored.selected == {"b"}
    replacement = path.with_name("replacement.db")
    with closing(sqlite3.connect(replacement)) as conn:
        conn.execute("CREATE TABLE lists(id TEXT,name TEXT)")
    replacement.replace(path)
    assert not store.current()
    with pytest.raises(WorkspaceChanged):
        store.load()
