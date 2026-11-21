"""Drive library metadata can travel in both directions without copying research."""

import pytest
from test_drive_sync_authority import Cloud, authority

from paper_daily.drive_library_directory import DriveDirectory
from paper_daily.drive_sync_files import DriveChanged
from paper_daily.library_directory import ListEntry


def test_chat_head_survives_peer_rename_and_rejects_stale_publication(tmp_path):
    from dataclasses import replace

    from paper_daily.library_directory import Directory, ScopeHead
    from paper_daily.sync_journal import SyncFormatUnsupported

    cloud = Cloud()
    left = authority(cloud, tmp_path / "desktop").files
    right = authority(cloud, tmp_path / "laptop").files
    folder, head = left.new_ids(2)
    desktop = DriveDirectory(left, folder, head, "personal", chat=True)
    mac = DriveDirectory(right, folder, head, "personal", chat=True)
    older = DriveDirectory(right, folder, head, "personal", positions=True)
    initial = desktop.initialize("Library")
    first = ScopeHead(1, "conversation_object", "a" * 64, 64)
    paper = ScopeHead(1, "paper_object", "b" * 64, 64)
    entry = ListEntry("a", "Shared", True, papers_head=paper, chat_head=first)
    with pytest.raises(ValueError, match="bibliography"):
        Directory("personal", 1, (replace(entry, papers_head=None),))
    with pytest.raises(ValueError, match="conversation"):
        older.upsert(older.read(), [entry])
    desktop.upsert(initial, [entry])
    with pytest.raises(SyncFormatUnsupported):
        older.read()
    before = mac.read()
    newer = replace(first, generation=2, id="next_object")
    desktop.upsert(desktop.read(), [replace(entry, chat_head=newer)])
    with pytest.raises(DriveChanged):
        mac.upsert(before, [replace(entry, name="Renamed")])
    mac.upsert(mac.read(), [ListEntry("a", "Renamed", True)])
    assert desktop.read().directory.lists == (replace(entry, name="Renamed", chat_head=newer),)


def test_selected_chat_exchange_keeps_reply_identity_and_requires_a_current_grant(tmp_path):
    from uuid import uuid4

    from test_library_selection import database, selection
    from test_sync_graph_research import PAPER, STAMP, membership, metadata, operation, parent

    from paper_daily.drive_list_history import DriveListChat, DriveListPapers
    from paper_daily.sync_content import content_id
    from paper_daily.workspace_service import Ticket

    cloud = Cloud()
    files = [authority(cloud, tmp_path / device).files for device in ("win", "mac")]
    folder, head = files[0].new_ids(2)
    directories = [DriveDirectory(f, folder, head, "personal", chat=True) for f in files]
    first, second = directories
    cat = first.upsert(first.initialize("Library"), [ListEntry("a", "Shared", False)]).directory
    stores = [selection(database(tmp_path / label), tmp_path / (label + "-settings"),
                        library_id="personal") for label in ("desktop", "laptop")]
    for store in stores:
        store.save(cat, ["a"], expected_revision=0)
    paper = dict(operation("paper", PAPER, metadata()), workspace_id="personal")
    member = dict(membership("a"), workspace_id="personal")
    DriveListPapers(first, stores[0], "a").append(None, [paper, member], revision=1)
    with pytest.raises(PermissionError):
        DriveListChat(second, stores[1], "a", revision=1)
    for store in stores:
        store.set_chat_sync("a", True, revision=1, ticket=Ticket())
    sender, receiver = (DriveListChat(d, s, "a", revision=1)
                        for d, s in zip(directories, stores, strict=True))
    question_id, exchange_id = str(uuid4()), str(uuid4())

    def message(key, reply, text):
        scope = {"kind": "paper", "id": PAPER}
        data = dict(role="assistant" if reply else "user", body=text, created_at=STAMP,
                    page=None, anchor=None, exchange_id=exchange_id, reply_to=reply)
        payload = dict(scope=scope, feature="chat", key=key, data=data, source_document_hash=None)
        return dict(operation("research_content", content_id(scope, "chat", key), payload,
                              parents=[parent("paper", PAPER)]), workspace_id="personal")

    question = message(question_id, None, "How was the outcome measured?")
    first_head = sender.append(None, [question], revision=1)
    assert receiver.changes(None, revision=1) == (first_head, [question])
    answer = message(str(uuid4()), question_id, "By independent assessment.")
    next_head = receiver.append(first_head, [answer], revision=1)
    assert sender.changes(first_head, revision=1) == (next_head, [answer])
    assert sender.changes(next_head, revision=1) == (next_head, [])
    from paper_daily.sync_journal import SyncFormatUnsupported

    old = message(str(uuid4()), None, "A historical question")
    del old["payload"]["data"]["exchange_id"], old["payload"]["data"]["reply_to"]
    with pytest.raises(ValueError, match="historical"):
        sender.append(next_head, [old], revision=1)
    modern = DriveDirectory(files[0], folder, head, "personal", chat=True, unlinked_chat=True)
    writer = DriveListChat(modern, stores[0], "a", revision=1)
    legacy_head = writer.append(next_head, [old], revision=1)
    assert writer.changes(next_head, revision=1) == (legacy_head, [old])
    with pytest.raises(SyncFormatUnsupported):
        second.read()
    renamed = modern.upsert(modern.read(), [ListEntry("a", "Renamed", True)])
    assert renamed.directory.lists[0].unlinked_chat
    stores[1].set_chat_sync("a", False, revision=1, ticket=Ticket())
    with pytest.raises(PermissionError):
        receiver.changes(None, revision=1)


def test_position_head_is_opt_in_and_survives_list_rename(tmp_path):
    from dataclasses import replace

    from paper_daily.library_directory import ScopeHead
    from paper_daily.sync_journal import SyncFormatUnsupported

    cloud = Cloud()
    files = authority(cloud, tmp_path / "desktop").files
    folder, head = files.new_ids(2)
    old = DriveDirectory(files, folder, head, "personal", membership_restores=True)
    enabled = DriveDirectory(files, folder, head, "personal", positions=True)
    before = old.initialize("Library")
    bibliography = ScopeHead(1, "papers_object", "a" * 64, 80)
    positions = ScopeHead(1, "position_object", "b" * 64, 100)
    entry = ListEntry("a", "Travel", True, papers_head=bibliography, positions_head=positions)
    count = len(cloud.objects)
    with pytest.raises(ValueError, match="PDF position"):
        old.upsert(before, [entry])
    assert len(cloud.objects) == count
    enabled.upsert(before, [entry])
    with pytest.raises(SyncFormatUnsupported):
        old.read()
    enabled.upsert(enabled.read(), [ListEntry("a", "Renamed", True)])
    assert enabled.read().directory.lists == (replace(entry, name="Renamed"),)


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


def test_private_directory_attachment_roundtrip_and_retry(tmp_path, monkeypatch):
    import hashlib

    from paper_daily.drive_sync_files import MAX_INLINE
    from paper_daily.sync_blobs import BlobManifest, BlobStore

    cloud = Cloud()
    left, right = (authority(cloud, tmp_path / device).files for device in ("win", "mac"))
    folder, head = left.new_ids(2)
    directory = DriveDirectory(left, folder, head, "personal")
    from test_library_selection import database, selection
    from test_sync_graph_research import PAPER, membership, metadata, operation

    from paper_daily.drive_list_history import DriveListPapers
    from paper_daily.workspace_service import Ticket

    catalog = directory.upsert(directory.initialize("Private library"),
                               [ListEntry("a", "A", False)]).directory
    stores = [selection(database(tmp_path / label), tmp_path / (label + "-settings"),
                        library_id="personal") for label in ("desktop", "laptop")]
    paper = dict(operation("paper", PAPER, metadata()), workspace_id="personal")
    member = dict(membership("a"), workspace_id="personal")
    for store in stores:
        store.save(catalog, ["a"], expected_revision=0)
    DriveListPapers(directory, stores[0], "a").append(None, [paper, member], revision=1)
    remote = DriveDirectory(right, folder, head, "personal")

    def transfer(directory, device):
        return directory.attachment_objects(tmp_path / f"receipts-{device}", stores[device], "a",
                                            PAPER, paper["incarnation"], 1, Ticket())

    with pytest.raises(PermissionError, match="Enable PDF"):
        transfer(directory, 0)
    stores[0].set_pdf_sync("a", True, revision=1, ticket=Ticket())
    sender = transfer(directory, 0)
    with pytest.raises(PermissionError, match="Enable PDF"):
        transfer(remote, 1)
    stores[1].set_pdf_sync("a", True, revision=1, ticket=Ticket())
    receiver = transfer(remote, 1)
    pdf = tmp_path / "synthetic.pdf"
    data = b"%PDF-1.7" + bytes(MAX_INLINE) + b"%%EOF"
    pdf.write_bytes(data)
    owner = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    different = BlobManifest("0" * 64, owner.size)
    count = len(cloud.objects)
    with pytest.raises(ValueError, match="selected attachment"):
        sender.put(pdf, expected=different)
    assert len(cloud.objects) == count
    original_put = left.put_small

    def revoke_after_chunk(*args, **kwargs):
        result = original_put(*args, **kwargs)
        stores[0].set_pdf_sync("a", False, revision=1, ticket=Ticket())
        return result

    with monkeypatch.context() as interrupted:
        interrupted.setattr(left, "put_small", revoke_after_chunk)
        with pytest.raises(PermissionError, match="permission"):
            sender.put(pdf, expected=owner)
    assert len(cloud.objects) == count + 1
    stores[0].set_pdf_sync("a", True, revision=1, ticket=Ticket())
    sender = transfer(directory, 0)
    manifest = sender.put(pdf, expected=owner)
    assert len(manifest["chunks"]) == 2
    assert sender.put(pdf, expected=owner) == manifest
    assert len(cloud.objects) == count + 2
    store = BlobStore(tmp_path / "verified-originals")
    with pytest.raises(ValueError, match="selected attachment"):
        receiver.get(manifest, store, expected=different)
    assert not store.available(owner)
    restored = receiver.get(manifest, store, expected=owner)
    assert restored.read_bytes() == data
    assert receiver.put(restored, expected=owner) == manifest
    stores[1].set_pdf_sync("a", False, revision=1, ticket=Ticket())
    stores[1].set_pdf_sync("a", True, revision=1, ticket=Ticket())
    with pytest.raises(PermissionError, match="permission"):
        receiver.get(manifest, store, expected=owner)
    with pytest.raises(ValueError, match="outside"):
        remote.attachment_objects(tmp_path / "cache", stores[1], "a", PAPER, "old", 1, Ticket())
    assert len(cloud.objects) == count + 2

    from paper_daily.drive_list_originals import DriveListOriginals

    desk = DriveListOriginals(directory, tmp_path / "receipts-0", stores[0], "a", 1, Ticket())
    mac = DriveListOriginals(remote, tmp_path / "receipts-1", stores[1], "a", 1, Ticket())
    offline = BlobStore(tmp_path / "mac-reader-originals")
    assert mac.download(PAPER, paper["incarnation"], offline) is None
    publish_head = directory.upsert

    def rename_during_publish(observed, entries, **kwargs):
        remote.upsert(remote.read(), [ListEntry("a", "Changed on laptop", True)])
        return publish_head(observed, entries, **kwargs)

    with monkeypatch.context() as racing:
        racing.setattr(directory, "upsert", rename_during_publish)
        with pytest.raises(DriveChanged):
            desk.publish(PAPER, paper["incarnation"], pdf, owner)
    assert remote.read().directory.lists[0].name == "Changed on laptop"
    assert mac.download(PAPER, paper["incarnation"], offline) is None
    assert desk.publish(PAPER, paper["incarnation"], pdf, owner) == manifest
    published = len(cloud.objects)
    assert b"directory.v5" in remote.read().directory.to_bytes()
    assert owner.sha256.encode() not in remote.read().directory.to_bytes()
    assert mac.download(PAPER, paper["incarnation"], offline).read_bytes() == data
    assert mac.publish(PAPER, paper["incarnation"], restored, owner) == manifest
    with pytest.raises(ValueError, match="different original"):
        desk.publish(PAPER, paper["incarnation"], pdf, different)
    assert len(cloud.objects) == published
    remote.upsert(remote.read(), [ListEntry("a", "Renamed", True)])
    assert mac.download(PAPER, paper["incarnation"], offline).read_bytes() == data


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
    assert left.read_library(Ticket())["drive_content"] == {}
    published = left.save_library(["a", "b"], Ticket(), lambda _: None)
    assert published["drive_content"] == {"a": [], "b": []}
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


def test_selected_list_records_arrive_in_original_reader_database_and_return(tmp_path, monkeypatch):
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
    db(win_path, "UPDATE lists SET name='Renamed on desktop' WHERE id='b'")
    db(mac_path, "UPDATE lists SET note='Description from laptop' WHERE id='b'")
    sync(mac)
    sync(win)
    sync(mac)
    for path in (win_path, mac_path):
        assert db(path, "SELECT name,note FROM lists WHERE id='b'") == [
            ("Renamed on desktop", "Description from laptop")
        ]
    # Drive accepts a field merge but its reply never reaches the desktop.
    from paper_daily.drive_list_history import DriveListHistory

    append = DriveListHistory.append

    def lose_reply(history, expected, records, *, revision):
        append(history, expected, records, revision=revision)
        raise ConnectionError("lost reply")

    db(win_path, "UPDATE lists SET name='First desktop edit' WHERE id='b'")
    db(mac_path, "UPDATE lists SET note='Independent laptop edit' WHERE id='b'")
    sync(mac)
    with monkeypatch.context() as patch:
        patch.setattr(DriveListHistory, "append", lose_reply)
        with pytest.raises(ConnectionError, match="lost reply"):
            sync(win)
    # Revert the name before retry; the local description still predates the merge.
    db(win_path, "UPDATE lists SET name='Renamed on desktop' WHERE id='b'")
    sync(win)
    sync(mac)
    for path in (win_path, mac_path):
        assert db(path, "SELECT name,note FROM lists WHERE id='b'") == [
            ("Renamed on desktop", "Independent laptop edit")
        ]
    assert db(win.path, "SELECT COUNT(*) FROM list_record_sends") == [(0,)]
    # A competing edit after the lost reply must still require an explicit decision.
    db(win_path, "UPDATE lists SET note='Base accepted by Drive' WHERE id='b'")
    with monkeypatch.context() as patch:
        patch.setattr(DriveListHistory, "append", lose_reply)
        with pytest.raises(ConnectionError):
            sync(win)
    sync(mac)
    db(win_path, "UPDATE lists SET note='Local candidate' WHERE id='b'")
    db(mac_path, "UPDATE lists SET note='Remote candidate' WHERE id='b'")
    sync(mac)
    from paper_daily.drive_list_records import ListDetailsConflict

    with pytest.raises(ListDetailsConflict, match="both versions"):
        sync(win)
    assert db(win_path, "SELECT note FROM lists WHERE id='b'") == [("Local candidate",)]
    from paper_daily.drive_list_records import review_list

    def review(decision=None):
        return review_list(remote, win, "b", win.load().revision, Ticket(), decision)

    card, = review()
    assert card["fields"] == ["note"]
    assert card["local"]["note"] == "Local candidate"
    assert card["remote"]["note"] == "Remote candidate"
    db(win_path, "UPDATE lists SET name='Independent desktop rename' WHERE id='b'")
    with pytest.raises(ValueError, match="compare again"):
        review((card, "remote"))
    card, = review()
    review((card, "remote"))
    sync(mac)
    for path in (win_path, mac_path):
        assert db(path, "SELECT name,note FROM lists WHERE id='b'") == [
            ("Independent desktop rename", "Remote candidate")]
    assert review() == []
    # The other device can edit again while the comparison dialog is open.
    db(win_path, "UPDATE lists SET name='Desktop',note='Desktop description' WHERE id='b'")
    db(mac_path, "UPDATE lists SET name='Laptop',note='Laptop description' WHERE id='b'")
    sync(mac)
    stale, = review()
    assert stale["fields"] == ["name", "note"]
    db(mac_path, "UPDATE lists SET name='Revised laptop name' WHERE id='b'")
    sync(mac)
    with pytest.raises(ValueError, match="compare again"):
        review((stale, "local"))
    assert db(mac_path, "SELECT name,note FROM lists WHERE id='b'") == [
        ("Revised laptop name", "Laptop description")]
    latest, = review()
    assert latest["remote"]["name"] == "Revised laptop name"
    # Losing the response to an explicit decision must preserve the next offline edit.
    with monkeypatch.context() as patch:
        patch.setattr(DriveListHistory, "append", lose_reply)
        with pytest.raises(ConnectionError, match="lost reply"):
            review((latest, "local"))
    db(win_path, "UPDATE lists SET note='After the choice' WHERE id='b'")
    sync(win)
    sync(mac)
    for path in (win_path, mac_path):
        assert db(path, "SELECT name,note FROM lists WHERE id='b'") == [
            ("Desktop", "After the choice")]
    assert review() == []


def test_one_list_conflict_allows_other_selected_lists_to_finish(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from paper_daily import drive_list_records, drive_sync_setup
    from paper_daily.workspace_service import Ticket

    result = {"items": []}
    from test_library_selection import database

    setup = drive_sync_setup.DriveSetup(database(tmp_path / "research"))
    setup.save_library = lambda *args, **kwargs: result
    setup.read_library = lambda ticket: result
    selected = SimpleNamespace(selected={"a", "b"}, revision=2)
    setup._library_view = (None, object(), selected, object())
    monkeypatch.setattr(drive_sync_setup, "local_binding", lambda path: None)
    seen = []

    def exchange(directory, store, list_id, revision, ticket):
        seen.append(list_id)
        if list_id == "a":
            raise drive_list_records.ListReviewRequired("Conflicting list name")

    monkeypatch.setattr(drive_list_records, "exchange_list", exchange)
    apply = drive_sync_setup.DriveSetup.apply_library
    report = apply(setup, ["a", "b"], Ticket(), lambda _: None)
    assert seen == ["a", "b"]
    assert report["reviews"] == {"a": "Conflicting list name"}
    assert not report["list_conflicts"]

    def details_conflict(directory, store, list_id, revision, ticket):
        seen.append(list_id)
        if list_id == "a":
            raise drive_list_records.ListDetailsConflict("Conflicting list name")

    seen.clear()
    monkeypatch.setattr(drive_list_records, "exchange_list", details_conflict)
    report = apply(setup, ["a", "b"], Ticket(), lambda _: None)
    assert seen == ["a", "b"] and report["list_conflicts"] == ["a"]

    def account_changed(*args):
        raise PermissionError("Google account changed")

    monkeypatch.setattr(drive_list_records, "exchange_list", account_changed)
    with pytest.raises(PermissionError, match="account changed"):
        apply(setup, ["a", "b"], Ticket(), lambda _: None)

def test_paper_metadata_requires_membership_and_travels_independently(tmp_path):
    from test_library_selection import database, selection
    from test_sync_graph_research import PAPER, membership, metadata, operation

    from paper_daily.drive_list_history import DriveListHistory, DriveListPapers

    cloud = Cloud()
    one, two = [authority(cloud, tmp_path / name).files for name in ("left", "right")]
    folder, head = one.new_ids(2)
    left, right = [DriveDirectory(f, folder, head, "workspace") for f in (one, two)]
    cat = left.upsert(left.initialize("Library"), [ListEntry("a", "A", False)]).directory
    win, mac = [
        selection(database(tmp_path / name), tmp_path / (name + "-settings"),
                  library_id="workspace")
        for name in ("windows", "mac")
    ]
    for store in (win, mac):
        store.save(cat, ["a"], expected_revision=0)
    send, receive = DriveListPapers(left, win, "a"), DriveListPapers(right, mac, "a")
    paper = operation("paper", PAPER, metadata())
    member = membership("a")
    before = len(cloud.objects)
    for bad in ([paper], [paper, membership("b")],
                [dict(paper, incarnation="different"), member]):
        with pytest.raises(ValueError, match="membership|incarnation"):
            send.append(None, bad, revision=1)
    assert len(cloud.objects) == before
    accepted = send.append(None, [paper, member], revision=1)
    assert receive.changes(None, revision=1) == (accepted, [paper, member])
    details = DriveListHistory(right, mac, "a")
    assert details.changes(None, revision=1) == (None, [])
    edited = operation("list", "a", {"name": "Renamed", "note": None})
    details.append(None, [edited], revision=1)
    assert send.changes(accepted, revision=1) == (accepted, [])
    assert left.read().directory.lists[0].name == "Renamed"
    count = len(cloud.objects)
    assert send.append(None, [paper, member], revision=1) == accepted
    assert len(cloud.objects) == count
    mac.save(left.read().directory, [], expected_revision=1)
    with pytest.raises(ValueError, match="selection"):
        receive.changes(None, revision=1)


def test_note_history_uses_verified_members_and_preserves_other_streams(tmp_path):
    from test_library_selection import database, selection
    from test_sync_graph_research import OTHER_PAPER, PAPER, membership, metadata, note, operation

    from paper_daily.drive_list_history import DriveListNotes, DriveListPapers
    from paper_daily.workspace_service import Ticket

    cloud = Cloud()
    files = [authority(cloud, tmp_path / name).files for name in ("one", "two")]
    folder, head = files[0].new_ids(2)
    win, mac = [DriveDirectory(f, folder, head, "workspace") for f in files]
    catalog = win.upsert(win.initialize("Research"), [ListEntry("a", "A", False)]).directory
    stores = [
        selection(database(tmp_path / name), tmp_path / (name + "-settings"),
                  library_id="workspace")
        for name in ("desktop", "laptop")
    ]
    for store in stores:
        store.save(catalog, ["a"], expected_revision=0)
    papers = DriveListPapers(win, stores[0], "a")
    paper_head = papers.append(None, [operation("paper", PAPER, metadata()), membership("a")],
                               revision=1)
    assert b"library-directory.v3" in win.read().directory.to_bytes()
    before = len(cloud.objects)
    with pytest.raises(PermissionError, match="Enable note sync"):
        DriveListNotes(win, stores[0], "a", revision=1)
    assert len(cloud.objects) == before
    for store in stores:
        store.set_note_sync("a", True, revision=1, ticket=Ticket())
    sender, receiver = [
        DriveListNotes(d, s, "a", revision=1) for d, s in zip((win, mac), stores, strict=True)
    ]
    before = len(cloud.objects)
    for bad in (note(OTHER_PAPER), note(OTHER_PAPER, action="delete"),
                dict(note(), parents=[dict(note()["parents"][0], incarnation="unrelated")])):
        with pytest.raises(ValueError, match="outside"):
            sender.append(None, [bad], revision=1)
    assert len(cloud.objects) == before
    accepted = sender.append(None, [note()], revision=1)
    assert receiver.changes(None, revision=1) == (accepted, [note()])
    catalog = mac.read().directory
    assert b"library-directory.v4" in catalog.to_bytes()
    assert b"Observation" not in catalog.to_bytes()
    before = len(cloud.objects)
    assert sender.append(None, [note()], revision=1) == accepted
    assert len(cloud.objects) == before
    renamed = mac.upsert(mac.read(), [ListEntry("a", "New name", False)]).directory
    assert renamed.lists[0].notes_head == accepted and renamed.lists[0].papers_head == paper_head
    stores[1].set_note_sync("a", False, revision=1, ticket=Ticket())
    stores[1].set_note_sync("a", True, revision=1, ticket=Ticket())
    with pytest.raises(PermissionError, match="permission"):
        receiver.changes(accepted, revision=1)
    stores[1].save(renamed, [], expected_revision=1)
    with pytest.raises(ValueError, match="selection"):
        receiver.changes(accepted, revision=1)
    current = stores[1].save(renamed, ["a"], expected_revision=2)
    assert stores[1].note_grant("a", current.revision) is None


def test_reading_progress_is_separate_for_each_membership_and_device(tmp_path, monkeypatch):
    from test_library_selection import database, selection
    from test_sync_graph_research import PAPER, STAMP, membership, metadata, operation, parent

    from paper_daily.drive_list_history import DriveListPapers, DriveListReading
    from paper_daily.workspace_service import Ticket

    cloud = Cloud()
    devices = [authority(cloud, tmp_path / label).files for label in ("win", "mac")]
    folder, head = devices[0].new_ids(2)
    dirs = [DriveDirectory(files, folder, head, "personal") for files in devices]
    first = dirs[0].initialize("Personal library")
    catalog = dirs[0].upsert(first, [ListEntry(k, k, True) for k in ("a", "b")]).directory
    stores = [selection(database(tmp_path / label), tmp_path / (label + "-settings"),
                        library_id="personal") for label in ("desktop", "laptop")]
    for store in stores:
        store.save(catalog, ["a", "b"], expected_revision=0)
    for key in ("a", "b"):
        paper = dict(operation("paper", PAPER, metadata()), workspace_id="personal")
        member = dict(membership(key), workspace_id="personal")
        DriveListPapers(dirs[0], stores[0], key).append(None, [paper, member], revision=1)
    with pytest.raises(PermissionError):
        DriveListReading(dirs[1], stores[1], "a", revision=1)
    for store in stores:
        store.set_reading_sync("a", True, revision=1, ticket=Ticket())
    win, mac = [DriveListReading(d, s, "a", revision=1) for d, s in zip(dirs, stores, strict=True)]
    reads = []
    read_entry = DriveListPapers._read_entry
    def counted(history, head):
        reads.append(head)
        return read_entry(history, head)
    with monkeypatch.context() as watch:
        watch.setattr(DriveListPapers, "_read_entry", counted)
        mac = DriveListReading(dirs[1], stores[1], "a", revision=1)
        assert not reads
        assert len(mac.memberships) == 1
        new_id = "b9a1b8aa-d396-49ee-b4dc-58e877820049"
        added = dict(operation("paper", new_id, metadata()), workspace_id="personal")
        link = dict(membership("a", new_id), workspace_id="personal")
        snapshot = dirs[0].read().directory.lists[0].papers_head
        DriveListPapers(dirs[0], stores[0], "a").append(snapshot, [added, link], revision=1)
        mac = DriveListReading(dirs[1], stores[1], "a", revision=1)
        assert len(reads) == 2 and len(mac.memberships) == 2
        win = DriveListReading(dirs[0], stores[0], "a", revision=1)
    member = membership("a")
    progress = dict(operation(
        "reading_state", member["entity_id"],
        dict(list_id="a", paper_id=PAPER, state="read", delivered_at=None, read_at=STAMP),
        parents=[*member["parents"], parent("membership", member["entity_id"])],
    ), workspace_id="personal")
    observed = win.append(None, [progress], revision=1)
    assert mac.changes(None, revision=1) == (observed, [progress])
    from paper_daily.drive_reader_progress import _observe
    with monkeypatch.context() as watch:
        watch.setattr(DriveListReading, "_read_entry", counted)
        reads.clear()
        assert _observe(mac, 1)[1].latest[progress["entity_id"]] == progress
        assert reads == [observed]
        assert _observe(mac, 1)[1].latest[progress["entity_id"]] == progress
        assert reads == [observed]
    stores[1].set_reading_sync("b", True, revision=1, ticket=Ticket())
    other = DriveListReading(dirs[1], stores[1], "b", revision=1)
    assert other.changes(None, revision=1) == (None, [])
    with pytest.raises(ValueError, match="selected membership"):
        other.append(None, [progress], revision=1)
    stores[1].set_reading_sync("a", False, revision=1, ticket=Ticket())
    with pytest.raises(PermissionError):
        _observe(mac, 1)
    with pytest.raises(PermissionError):
        mac.changes(None, revision=1)
    assert win.changes(None, revision=1) == (observed, [progress])

def test_devices_exchange_source_bound_positions_only_with_current_grants(tmp_path):
    from test_library_selection import database, selection
    from test_sync_graph_research import PAPER, STAMP, membership, metadata, operation, parent

    from paper_daily.drive_list_history import DriveListPapers, DriveListPositions
    from paper_daily.sync_content import content_id
    from paper_daily.workspace_service import Ticket

    cloud = Cloud()
    files = [authority(cloud, tmp_path / name).files for name in ("left", "right")]
    folder, head = files[0].new_ids(2)
    dirs = [DriveDirectory(f, folder, head, "personal", positions=True) for f in files]
    first = dirs[0].initialize("Personal library")
    catalog = dirs[0].upsert(first, [ListEntry("a", "Travel", True)]).directory
    stores = [selection(database(tmp_path / name), tmp_path / (name + "-settings"),
                        library_id="personal", device_id=name) for name in ("desktop", "laptop")]
    for store in stores:
        store.save(catalog, ["a"], expected_revision=0)
    paper = dict(operation("paper", PAPER, metadata()), workspace_id="personal")
    member = dict(membership("a"), workspace_id="personal")
    DriveListPapers(dirs[0], stores[0], "a").append(None, [paper, member], revision=1)
    with pytest.raises(PermissionError):
        DriveListPositions(dirs[0], stores[0], "a", revision=1)
    for store in stores:
        store.set_position_sync("a", True, revision=1, ticket=Ticket())
    writers = [DriveListPositions(d, s, "a", revision=1) for d, s in zip(dirs, stores, strict=True)]
    scope = {"kind": "paper", "id": PAPER}
    digest = "a" * 64
    identity = content_id(scope, "reading_position", digest)
    records = []
    for device, page in zip(stores, (8, 15), strict=True):
        payload = dict(feature="reading_position", scope=scope, source_document_hash=digest,
                       key=digest, data=dict(page=page, recorded_at=STAMP, method="entered"))
        records.append(dict(operation("research_content", identity, payload,
                                      op_id=f"position-{page}", parents=[parent("paper", PAPER)]),
                            workspace_id="personal", device_id=device.context))
    with pytest.raises(ValueError, match="local position"):
        writers[0].append(None, [records[1]], revision=1)
    first = writers[0].append(None, records[:1], revision=1)
    assert writers[0].append(None, records[:1], revision=1) == first
    assert writers[1].changes(None, revision=1) == (first, records[:1])
    latest = writers[1].append(first, records[1:], revision=1)
    assert writers[0].changes(None, revision=1) == (latest, records)
    updated = dict(records[0], operation_id="position-update", base_revision=1,
                   depends_on=records[0]["operation_id"])
    payload = records[0]["payload"]
    updated["payload"] = dict(payload, data=dict(payload["data"], page=12,
                                                 recorded_at="2001-01-01T00:00:00Z"))
    from paper_daily.sync_journal import SyncHistoryUnavailable
    count = len(cloud.objects)
    with pytest.raises(SyncHistoryUnavailable):
        writers[0].append(latest, [dict(updated, depends_on="unknown")], revision=1)
    assert len(cloud.objects) == count
    tip = writers[0].append(latest, [updated], revision=1)
    assert writers[1].suggestions(revision=1) == (tip, [updated, records[1]])
    import hashlib

    from test_reading_positions import pdf_bytes

    original = pdf_bytes(3, "Portable edition")
    digest = hashlib.sha256(original).hexdigest()
    page = dict(page=3, recorded_at=STAMP, method="entered")
    publish = writers[0].publish_page
    count = len(cloud.objects)
    with pytest.raises(ValueError, match="exact hash"):
        publish(PAPER, digest, page, pdf_bytes(3, "Other PDF"), predecessor=None, revision=1)
    with pytest.raises(ValueError, match="page count"):
        publish(PAPER, digest, dict(page, page=4), original, predecessor=None, revision=1)
    assert len(cloud.objects) == count
    sent = publish(PAPER, digest, page, original, predecessor=None, revision=1)
    count = len(cloud.objects)
    assert publish(PAPER, digest, page, original, predecessor=None, revision=1) == sent
    with pytest.raises(DriveChanged):
        publish(PAPER, digest, dict(page, page=2), original, predecessor=None, revision=1)
    assert len(cloud.objects) == count
    assert sent in writers[1].suggestions(revision=1)[1]
    resume = writers[1].resume_page
    assert resume(PAPER, sent, original, revision=1) == 3
    with pytest.raises(ValueError, match="open paper"):
        resume("other-paper", sent, original, revision=1)
    with pytest.raises(ValueError, match="exact hash"):
        resume(PAPER, sent, pdf_bytes(3, "Other PDF"), revision=1)
    with pytest.raises(ValueError, match="another device"):
        writers[0].resume_page(PAPER, sent, original, revision=1)
    newer = publish(PAPER, digest, dict(page, page=2), original,
                    predecessor=sent["operation_id"], revision=1)
    with pytest.raises(DriveChanged):
        resume(PAPER, sent, original, revision=1)
    assert resume(PAPER, newer, original, revision=1) == 2
    stores[1].set_position_sync("a", False, revision=1, ticket=Ticket())
    with pytest.raises(PermissionError):
        writers[1].changes(first, revision=1)
