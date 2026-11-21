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


def test_pdf_position_directory_requires_matching_reader_and_bibliography():
    from paper_daily.library_directory import ScopeHead
    from paper_daily.sync_journal import SyncFormatUnsupported

    head = ScopeHead(1, "position_object", "a" * 64, 123)
    paper_head = replace(head, id="papers_object")
    base = ListEntry("a", "List A", True, papers_head=paper_head)
    directory = Directory("library", 2, (base,))
    assert b"library-directory.v3" in directory.to_bytes()
    published = replace(directory, lists=(replace(base, positions_head=head),))
    wire = published.to_bytes()
    assert b"library-directory.v11" in wire
    assert Directory.from_bytes(wire, library_id="library", positions=True) == published
    with pytest.raises(SyncFormatUnsupported):
        Directory.from_bytes(wire, library_id="library", membership_restores=True)
    with pytest.raises(ValueError, match="bibliography"):
        replace(directory, lists=(replace(base, papers_head=None, positions_head=head),))


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


def test_pdf_position_grant_follows_device_list_and_selection_lifetime(tmp_path):
    db = database(tmp_path / "research")
    directory = inspect_lists(db, "library")
    root = tmp_path / "settings"
    desktop, mac = (selection(db, root, device_id=device) for device in ("desktop", "mac"))
    for device in (desktop, mac):
        device.save(directory, ["a", "b"], expected_revision=0)
    desktop.set_reading_sync("a", True, revision=1, ticket=Ticket())
    assert not desktop.position_lists()
    desktop.set_position_sync("a", True, revision=1, ticket=Ticket())
    first = desktop.position_grant("a", 1)
    assert first and desktop.position_lists() == ["a"]
    assert not mac.position_lists() and not desktop.pdf_grant("a", 1)
    desktop.set_position_sync("a", True, revision=1, ticket=Ticket())
    assert selection(db, root, device_id="desktop").position_grant("a", 1) == first
    desktop.save(directory, ["b"], expected_revision=1)
    with pytest.raises(SelectionChanged):
        desktop.position_grant("a", 1)
    desktop.save(directory, ["a", "b"], expected_revision=2)
    assert not desktop.position_grant("a", 3)
    desktop.set_position_sync("a", True, revision=3, ticket=Ticket())
    assert desktop.position_grant("a", 3) != first
    desktop.set_position_sync("a", False, revision=3, ticket=Ticket())
    assert desktop.position_lists() == []


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


def test_confirming_new_lists_enables_content_without_resetting_existing_choices(tmp_path):
    path = database(tmp_path / "research")
    store = selection(path, tmp_path / "settings")
    directory = inspect_lists(path, "library", generation=1, published=["a", "b"])
    first = store.save(directory, ["a"], expected_revision=0, include_new_content=True)
    grant = store.note_grant("a", first.revision)
    assert grant.startswith("edits-v1:")
    store.set_pdf_sync("a", False, revision=first.revision, ticket=Ticket())
    second = store.save(directory, ["a", "b"], expected_revision=first.revision,
                        include_new_content=True)
    assert store.pdf_lists() == ["b"]
    assert store.note_grant("a", second.revision) == grant
    for scope in (store.note_lists, store.dive_lists, store.reading_lists, store.position_lists):
        assert scope() == ["a", "b"]
    store.save(directory, ["a"], expected_revision=second.revision, include_new_content=True)
    assert store.pdf_lists() == [] and store.note_lists() == ["a"]
