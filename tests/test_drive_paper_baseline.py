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

    def login(path, label, transport=cloud):
        files = authority(transport, tmp_path / label / "authority").files
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
    # A replacement with the same owner and list IDs still needs a fresh review.
    find = win.files.workspaces
    for field in ("folder_id", "head_id"):
        def replaced(*, directories=False, field=field):
            rows = find(directories=directories)
            return [{**row, field: "different-id"} for row in rows] if directories else rows

        with monkeypatch.context() as patch:
            patch.setattr(win.files, "workspaces", replaced)
            before = dict(cloud.objects)
            with pytest.raises(ValueError, match="directory changed"):
                win.sync_saved_library(Ticket(), lambda _: None)
            with pytest.raises(ValueError, match="directory changed"):
                win.read_library(Ticket())
            assert cloud.objects == before
    assert not win.sync_saved_library(Ticket(), lambda _: None)["reviews"]
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
        first_head, = conn.execute("SELECT head FROM drive_library_bibliographies "
                                   "WHERE list_id='return'").fetchone()
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
    # The peer publishes just after Windows received its history and before it publishes.
    publish = drive_paper_baseline.publish_initial
    peer_finished = False

    def interleave(directory, store, *args, **kwargs):
        nonlocal peer_finished
        if not peer_finished and store.workspace.path == source:
            peer_finished = True
            assert mac.sync_saved_library(Ticket(), lambda _: None)["reviews"] == {}
        return publish(directory, store, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(drive_paper_baseline, "publish_initial", interleave)
        assert win.sync_saved_library(Ticket(), lambda _: None)["reviews"] == {}
    assert peer_finished
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
    # A batch that aborts on its second paper must also roll back its first removal intent.
    from paper_daily import lists

    monkeypatch.setattr(db, "DB_PATH", source)
    with closing(sqlite3.connect(source)) as conn, conn:
        anchor, = conn.execute("SELECT head FROM drive_library_bibliographies "
                               "WHERE list_id='return'").fetchone()
        conn.execute("CREATE TRIGGER reject_removal BEFORE DELETE ON list_papers "
                     "WHEN OLD.paper_id='Desktop discovery' BEGIN SELECT RAISE(ABORT,'busy'); END")
    with pytest.raises(sqlite3.IntegrityError, match="busy"):
        lists.remove_papers("return", ["paper", "Desktop discovery"])
    with closing(sqlite3.connect(source)) as conn, conn:
        assert conn.execute("SELECT 1 FROM list_papers WHERE list_id='return' AND paper_id='paper'"
                            ).fetchone()
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE "
                                "name='drive_membership_removals'").fetchone()
        conn.execute("DROP TRIGGER reject_removal")
    assert lists.remove_papers("return", ["Desktop discovery", "Desktop discovery"]) == 1
    assert not lists.remove_paper("return", "Desktop discovery")
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT list_id,local_id,observed_head FROM drive_membership_removals"
                            ).fetchall() == [("return", "Desktop discovery", anchor)]
    # A rolled-back re-add must leave the pending request intact.
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('return','Desktop discovery',1,?)", (STAMP,))
        conn.rollback()
    # A later addition advances the remote head but leaves the removed incarnation intact.
    with closing(sqlite3.connect(laptop)) as conn, conn:
        conn.execute("INSERT INTO papers(id,title,title_key,venue,year,source) "
                     "VALUES('peer-new','Peer new','peer new','Fixture',2026,'fixture')")
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('return','peer-new',3,?)", (STAMP,))
    assert not mac.sync_saved_library(Ticket(), lambda _: None)["reviews"]
    # An unrelated raw deletion does not create a second user intent.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("DELETE FROM list_papers WHERE list_id='return' AND paper_id='paper'")
    review = win.sync_saved_library(Ticket(), lambda _: None)["reviews"]["return"]
    assert "2 removed papers; 1 explicitly removed" in review
    # Fork the synthetic transport so the rest of the journey stays on the v8 client.
    import copy

    from paper_daily.drive_membership_history import DriveMembershipChanges
    from paper_daily.drive_membership_intent import MembershipRemovalReview
    from paper_daily.sync_journal import SyncFormatUnsupported

    fork = copy.deepcopy(cloud)
    streams = []
    legacy = None
    for device, label in ((win, "win"), (mac, "mac")):
        _, store, saved, original, *_ = device._library_view
        files = authority(fork, tmp_path / ("v9-" + label)).files
        args = (files, original.folder, original.head, original.library_id)
        v9 = DriveDirectory(*args, membership_changes=True)
        legacy = DriveDirectory(*args)
        streams.append(DriveMembershipChanges(v9, store, "return", revision=saved.revision))
    writer, reader = streams
    with pytest.raises(MembershipRemovalReview) as review_error:
        publish_initial(writer.directory, writer.store, "return", writer.store.load().revision,
                        Ticket(), append_new=True)
    operations = review_error.value.operations
    assert len(operations) == 1 and operations[0]["action"] == "delete"
    revision = writer.store.load().revision
    peer_revision = reader.store.load().revision
    with pytest.raises(ValueError, match="creation"):
        writer.append(None, [dict(operations[0], incarnation="wrong")], revision=revision)
    from paper_daily.drive_membership_apply import receive_membership_changes
    from paper_daily.drive_paper_receive import receive_initial

    receive_initial(reader.directory, reader.store, "return", peer_revision, Ticket())
    assert receive_membership_changes(reader, peer_revision, Ticket()) == 0
    with closing(sqlite3.connect(laptop)) as conn, conn:
        peer_id, = conn.execute("SELECT id FROM papers WHERE title='Desktop discovery'").fetchone()
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('preserve','Other',?)", (STAMP,))
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('preserve',?,0,?)", (peer_id, STAMP))
        conn.execute("UPDATE list_papers SET state='read' WHERE list_id='return' AND paper_id=?",
                     (peer_id,))
    commit = writer.append(None, operations, revision=revision)
    count = len(fork.objects)
    assert writer.append(None, operations, revision=revision) == commit
    with pytest.raises(ValueError, match="already retired"):
        writer.append(commit, operations, revision=revision)
    assert len(fork.objects) == count
    assert reader.changes(None, revision=peer_revision) == (commit, operations)
    assert reader.changes(commit, revision=peer_revision) == (commit, [])
    with pytest.raises(SyncFormatUnsupported):
        legacy.read()

    from paper_daily.drive_paper_receive import exchange_bibliography

    fresh_db = tmp_path / "fresh-research" / "papers.db"
    fresh_db.parent.mkdir()
    with closing(sqlite3.connect(fresh_db)) as conn, conn:
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('return','Return',?)", (STAMP,))
        conn.execute("CREATE TRIGGER fail_install BEFORE INSERT ON list_papers "
                     "BEGIN SELECT RAISE(ABORT,'interrupted import'); END")
    fresh = selection(fresh_db, tmp_path / "fresh-settings", device_id="fresh-device",
                      library_id=reader.store.library_id, owner_id=reader.store.owner_id)
    fresh.save(reader.directory.read().directory, ["return"], expected_revision=0)
    with pytest.raises(sqlite3.IntegrityError, match="interrupted import"):
        exchange_bibliography(reader.directory, fresh, "return", 1, Ticket())
    with closing(sqlite3.connect(fresh_db)) as conn, conn:
        assert not conn.execute("SELECT 1 FROM papers").fetchone()
        assert not conn.execute("SELECT 1 FROM sqlite_master "
                                "WHERE name='drive_library_bibliographies'").fetchone()
        conn.execute("DROP TRIGGER fail_install")
        conn.execute("CREATE TRIGGER forbid_resurrection BEFORE INSERT ON list_papers "
                     "WHEN (SELECT title FROM papers WHERE id=NEW.paper_id)='Desktop discovery' "
                     "BEGIN SELECT RAISE(ABORT,'resurrected membership'); END")
    before_fresh = dict(fork.objects)
    for _ in range(2):
        exchange_bibliography(reader.directory, fresh, "return", 1, Ticket())
        with closing(sqlite3.connect(fresh_db)) as conn:
            titles = {r[0] for r in conn.execute("SELECT title FROM papers JOIN list_papers "
                                                 "ON papers.id=list_papers.paper_id")}
            assert titles == {"Offline local title", "Laptop discovery", "Peer new"}
            assert conn.execute("SELECT applied FROM drive_membership_watches "
                                "WHERE applied IS NOT NULL").fetchall() == [
                                    (operations[0]["operation_id"],)]
    assert fork.objects == before_fresh

    # The originating device may lose the reply after Drive accepts its deletion.
    from paper_daily.drive_membership_intent import remove_selected

    origin_cloud = copy.deepcopy(fork)
    origin_dir = DriveDirectory(authority(origin_cloud, tmp_path / "v9-origin").files,
                                reader.directory.folder, reader.directory.head,
                                reader.directory.library_id, membership_changes=True)
    origin_history = DriveMembershipChanges(origin_dir, fresh, "return", revision=1)
    with closing(sqlite3.connect(fresh_db)) as conn, conn:
        local, = conn.execute("SELECT id FROM papers WHERE title='Peer new'").fetchone()
        assert remove_selected(conn, "return", [local]) == 1
    with pytest.raises(MembershipRemovalReview) as prepared:
        publish_initial(origin_dir, fresh, "return", 1, Ticket(), append_new=True)
    [own_removal] = prepared.value.operations
    origin_history.append(commit, [own_removal], revision=1)
    with closing(sqlite3.connect(fresh_db)) as conn, conn:
        saved_head, = conn.execute("SELECT observed_head FROM drive_membership_removals").fetchone()
        conn.execute("UPDATE drive_membership_removals SET observed_head=?", (b"unrelated",))
    with pytest.raises(ListReviewRequired, match="both versions retained"):
        exchange_bibliography(origin_dir, fresh, "return", 1, Ticket())
    with closing(sqlite3.connect(fresh_db)) as conn, conn:
        assert not conn.execute("SELECT applied FROM drive_membership_watches WHERE member=? "
                                "AND applied IS NOT NULL", (own_removal["entity_id"],)).fetchone()
        conn.execute("UPDATE drive_membership_removals SET observed_head=?", (saved_head,))
    accepted = dict(origin_cloud.objects)
    for _ in range(2):
        exchange_bibliography(origin_dir, fresh, "return", 1, Ticket())
        with closing(sqlite3.connect(fresh_db)) as conn:
            assert not conn.execute("SELECT 1 FROM drive_membership_removals").fetchone()
            assert not conn.execute("SELECT 1 FROM list_papers WHERE list_id='return' "
                                    "AND paper_id=?", (local,)).fetchone()
            assert conn.execute("SELECT applied FROM drive_membership_watches WHERE "
                                "member=?", (own_removal["entity_id"],)).fetchone() == (
                                    own_removal["operation_id"],)
    assert origin_cloud.objects == accepted

    # A new desktop uses the ordinary sign-in/checklist and then its saved selection.
    device_db = tmp_path / "new-desktop" / "papers.db"
    device_db.parent.mkdir()
    with closing(sqlite3.connect(device_db)) as conn:
        conn.executescript(db.SCHEMA)
    device = login(device_db, "new-desktop-settings", origin_cloud)
    assert not device.apply_library(["return"], Ticket(), lambda _: None)["reviews"]
    reopened = login(device_db, "new-desktop-settings", origin_cloud)
    assert not reopened.sync_saved_library(Ticket(), lambda _: None)["reviews"]
    with closing(sqlite3.connect(device_db)) as conn:
        assert {r[0] for r in conn.execute("SELECT title FROM papers JOIN list_papers "
                                           "ON papers.id=list_papers.paper_id")} == {
            "Offline local title", "Laptop discovery"}
    assert origin_cloud.objects == accepted

    from paper_daily.drive_sync_files import decode, encode

    unrelated_head = encode({**decode(anchor), "sha256": "0" * 64})
    for ineligible in (first_head, unrelated_head):
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("UPDATE drive_membership_removals SET observed_head=?", (ineligible,))
        result = win.sync_saved_library(Ticket(), lambda _: None)
        assert "removed papers" in result["reviews"]["return"]
        assert "explicitly removed" not in result["reviews"]["return"]
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE drive_membership_removals SET observed_head=?", (anchor,))
    assert not mac.sync_saved_library(Ticket(), lambda _: None)["reviews"]
    for path, count in ((source, 0), (laptop, 1)):
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM list_papers r JOIN list_papers original "
                "ON r.paper_id=original.paper_id WHERE r.list_id='return' "
                "AND original.list_id='list'"
            ).fetchone() == (count,)
    with closing(sqlite3.connect(source)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM drive_membership_removals").fetchone() == (1,)
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('return','Desktop discovery',1,?)", (STAMP,))
    # Re-adding with the exact same timestamp revokes the request, even if a later
    # unobserved removal reproduces the same missing set and Drive head.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("DELETE FROM list_papers WHERE list_id='return' "
                     "AND paper_id='Desktop discovery'")
    # Prior builds could not observe re-additions, so their old actions need review.
    with closing(sqlite3.connect(source)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM drive_membership_removals").fetchone() == (0,)
        conn.execute("INSERT INTO drive_membership_removals VALUES(?,?,?,?,?,?)",
                     (win._library_view[1].context, "return", "legacy-action",
                      "Desktop discovery", STAMP, anchor))
    review = win.sync_saved_library(Ticket(), lambda _: None)["reviews"]["return"]
    assert "removed papers" in review and "explicitly removed" not in review
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('return','Desktop discovery',1,?)", (STAMP,))
    # The same paper added back later must not inherit the retired membership's reading state.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('return','paper',2,'2026-12-01T14:00:00+00:00')")
    before = dict(cloud.objects)
    report = win.sync_saved_library(Ticket(), lambda _: None)
    assert "added again" in report["reviews"]["return"]
    assert cloud.objects == before
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT state,added_at FROM list_papers WHERE list_id='return' "
                            "AND paper_id='paper'").fetchone() == (
                                "pending", "2026-12-01T14:00:00+00:00")


    # Switch the laptop to the forked v9 history after the legacy-client checks.
    peer_revision = reader.store.load().revision
    with pytest.raises(ListReviewRequired, match="local reading edits"):
        receive_membership_changes(reader, peer_revision, Ticket())
    with closing(sqlite3.connect(laptop)) as conn, conn:
        assert conn.execute("SELECT state FROM list_papers WHERE list_id='return' AND paper_id=?",
                            (peer_id,)).fetchone() == ("read",)
        conn.execute("UPDATE list_papers SET state='pending' WHERE list_id='return' AND paper_id=?",
                     (peer_id,))
        conn.execute("CREATE TRIGGER fail_ack BEFORE UPDATE OF applied ON drive_membership_watches "
                     "BEGIN SELECT RAISE(ABORT,'receipt interrupted'); END")
    with pytest.raises(sqlite3.IntegrityError, match="receipt interrupted"):
        receive_membership_changes(reader, peer_revision, Ticket())
    with closing(sqlite3.connect(laptop)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM list_papers WHERE paper_id=?",
                            (peer_id,)).fetchone() == (2,)
        conn.execute("DROP TRIGGER fail_ack")
        conn.execute("INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
                     (peer_id, "Keep this note", STAMP))
    from paper_daily.desktop.main import _legacy_pdf_name

    pdf = laptop.parent / "pdf" / _legacy_pdf_name(peer_id)
    pdf.parent.mkdir(exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 synthetic original")
    assert receive_membership_changes(reader, peer_revision, Ticket()) == 1
    assert receive_membership_changes(reader, peer_revision, Ticket()) == 0
    with closing(sqlite3.connect(laptop)) as conn:
        assert conn.execute("SELECT list_id FROM list_papers WHERE paper_id=?",
                            (peer_id,)).fetchall() == [("preserve",)]
        assert conn.execute("SELECT title FROM papers WHERE id=?", (peer_id,)).fetchone() == (
            "Desktop discovery",)
        assert conn.execute("SELECT body FROM notes WHERE paper_id=?", (peer_id,)).fetchone() == (
            "Keep this note",)
    assert pdf.read_bytes() == b"%PDF-1.4 synthetic original"
    # An already-applied removal must not replay against a subsequent local re-add.
    with closing(sqlite3.connect(laptop)) as conn, conn:
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('return',?,4,?)", (peer_id, STAMP))
    assert receive_membership_changes(reader, peer_revision, Ticket()) == 0
    with closing(sqlite3.connect(laptop)) as conn:
        assert conn.execute(
            "SELECT position FROM list_papers WHERE list_id='return' AND paper_id=?",
                            (peer_id,)).fetchone() == (4,)


def test_two_windows_exchange_offline_additions_after_closing_drive_settings(
    source, tmp_path, monkeypatch
):
    import json

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
            assert view.reading_toggle.isVisible() and not view.reading_toggle.isChecked()
            with monkeypatch.context() as cancel:
                cancel.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
                view.reading_toggle.click()
                assert not view.reading_toggle.isChecked()
            view.reading_toggle.click()
            wait(app, lambda v=view: not v.busy)
            assert view.reading_toggle.isChecked()
            assert view.pdf_toggle.isVisible() and not view.pdf_toggle.isChecked()
            with monkeypatch.context() as cancel:
                cancel.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
                view.pdf_toggle.click()
                assert not view.pdf_toggle.isChecked()
            view.pdf_toggle.click()
            wait(app, lambda v=view: not v.busy)
            assert view.pdf_toggle.isChecked() and not view.notes_toggle.isChecked()
            assert view.dive_toggle.isVisible() and not view.dive_toggle.isChecked()
            with monkeypatch.context() as cancel:
                cancel.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
                view.dive_toggle.click()
                assert not view.dive_toggle.isChecked()
            view.dive_toggle.click()
            wait(app, lambda v=view: not v.busy)
            assert view.dive_toggle.isChecked()
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

        anchor = {"p0": 4, "o0": 2, "p1": 4, "o1": 11, "document_hash": "a" * 64}
        with closing(sqlite3.connect(laptop)) as conn, conn:
            conn.execute(
                "INSERT INTO notes(paper_id,body,created_at,page,anchor) "
                "SELECT paper_id,'Laptop note',?,5,? FROM list_papers "
                "WHERE list_id='list' AND position=0", (STAMP, json.dumps(anchor))
            )
        import pymupdf

        from paper_daily.desktop.main import _legacy_pdf_name

        for path, key in ((source, "paper"), (laptop, "laptop-add")):
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("INSERT INTO dives(paper_id,body,written_at,spec) VALUES(?,?,?,?)",
                             (key, "Saved explanation " + key, STAMP, "test-spec"))
            folder = path.parent / "pdf"
            folder.mkdir()
            with pymupdf.open() as document:
                document.new_page().insert_text((50, 50), key)
                document.save(folder / _legacy_pdf_name(key))
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
                for title, original in (("Research paper", "paper"), ("laptop-add", "laptop-add")):
                    (local,) = conn.execute(
                        "SELECT id FROM papers WHERE title=?", (title,)
                    ).fetchone()
                    assert conn.execute(
                        "SELECT body,written_at,spec FROM dives WHERE paper_id=?", (local,)
                    ).fetchone() == ("Saved explanation " + original, STAMP, "test-spec")
                    with pymupdf.open(path.parent / "pdf" / _legacy_pdf_name(local)) as document:
                        assert document[0].get_text().strip() == original
                received = conn.execute(
                    "SELECT anchor FROM notes WHERE body='Laptop note'"
                ).fetchone()
                assert json.loads(received[0]) == anchor
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
            devices = (windows[0][1].service, reopened.service)
            from paper_daily.drive_list_history import DriveListNotes
            from paper_daily.drive_reader_dives import DiveHistory

            def interrupt_after_publish(method):
                def lose_reply(*args, **kwargs):
                    method(*args, **kwargs)
                    raise ConnectionError("Acknowledgement lost after upload")
                return lose_reply

            original_append = DriveListNotes.append

            def edit_during_upload(history, *args, **kwargs):
                head = original_append(history, *args, **kwargs)
                with closing(sqlite3.connect(laptop)) as conn, conn:
                    conn.execute("UPDATE notes SET body='Typing again' WHERE page=5")
                return head

            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute("UPDATE notes SET body='Sent snapshot' WHERE page=5")
            with monkeypatch.context() as midflight:
                midflight.setattr(DriveListNotes, "append", edit_during_upload)
                assert not devices[1].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with closing(sqlite3.connect(laptop)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Typing again",
                )
            assert not devices[1].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with closing(sqlite3.connect(source)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Typing again",
                )
            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute("UPDATE notes SET body='Offline draft' WHERE page=5")
            with monkeypatch.context() as disconnect:
                disconnect.setattr(DriveListNotes, "append",
                                   interrupt_after_publish(original_append))
                with pytest.raises(ConnectionError, match="Acknowledgement lost"):
                    devices[1].sync_saved_library(Ticket(), lambda _: None)
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            with closing(sqlite3.connect(source)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Offline draft",
                )
            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute("UPDATE notes SET body='Typing again' WHERE page=5")
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with closing(sqlite3.connect(source)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Typing again",
                )
            for writer, path, text in ((1, laptop, "Edited on laptop"),
                                       (0, source, "Edited on desktop")):
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.execute("UPDATE notes SET body=? WHERE page=5", (text,))
                for index in (writer, 1 - writer):
                    result = devices[index].sync_saved_library(Ticket(), lambda _: None)
                    assert not result["reviews"]
                for copy in (source, laptop):
                    with closing(sqlite3.connect(copy)) as conn:
                        [(body, saved_anchor)] = conn.execute(
                            "SELECT body,anchor FROM notes WHERE page=5"
                        ).fetchall()
                        assert body == text and json.loads(saved_anchor) == anchor
            for path, edit in ((source, "Desktop revision"), (laptop, "Laptop revision")):
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.execute("UPDATE notes SET body=? WHERE page=5", (edit,))
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.execute("UPDATE notes SET body='Unrelated desktop edit' WHERE page IS NULL")
            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute(
                    "INSERT INTO notes(paper_id,body,page,created_at) "
                    "SELECT paper_id,'Unrelated laptop card',6,? FROM notes WHERE page=5", (STAMP,)
                )
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            report = devices[1].sync_saved_library(Ticket(), lambda _: None)
            assert "retain both" in report["reviews"]["list"]
            assert report["note_conflicts"] == ["list"]
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            reopened.hide()
            runner = reopened.background
            runner.timer.start(1)
            wait(app, lambda: runner.state == "working")
            wait(app, lambda: runner.worker is None)
            assert runner.state == "note_conflict" and runner.timer.isActive()
            assert runner.timer.interval() == 30000
            reopened.show()
            for path, edit in ((source, "Desktop revision"), (laptop, "Laptop revision")):
                with closing(sqlite3.connect(path)) as conn:
                    assert conn.execute(
                        "SELECT body FROM notes ORDER BY page"
                    ).fetchall() == [
                        ("Unrelated desktop edit",), (edit,), ("Unrelated laptop card",)
                    ]
            from PySide6.QtWidgets import QPlainTextEdit, QPushButton

            from paper_daily.desktop.drive_note_compare import NoteComparison

            index = next(i for i in range(reopened.directory_lists.count())
                         if reopened.directory_lists.item(i).data(Qt.ItemDataRole.UserRole)
                         == "list")
            reopened.directory_lists.setCurrentRow(index)
            assert reopened.compare_notes.isVisible()
            shown = devices[1].review_notes("list", Ticket(), lambda _: None)
            assert len(shown) == 1 and shown[0]["title"] == "Research paper"
            for label in ("稍後決定", "採用本機版本"):
                observed = []

                def inspect(dialog, observed=observed, label=label):
                    observed.extend(view.toPlainText() for view in
                                    dialog.findChildren(QPlainTextEdit))
                    next(btn for btn in dialog.findChildren(QPushButton)
                         if btn.text() == label).click()
                    return dialog.result()

                with monkeypatch.context() as interaction:
                    interaction.setattr(NoteComparison, "exec", inspect)
                    reopened.compare_notes.click()
                    wait(app, lambda seen=observed: seen and not reopened.busy)
                assert observed == ["Edited on desktop", "Laptop revision", "Desktop revision"]
            assert not devices[1].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with closing(sqlite3.connect(source)) as conn, conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Laptop revision",
                )
                conn.execute("UPDATE notes SET body='Second desktop edit' WHERE page=5")
            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute("UPDATE notes SET body='Second laptop edit' WHERE page=5")
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with pytest.raises(ValueError, match="changed after review"):
                devices[1].review_notes("list", Ticket(), lambda _: None,
                                        decision=(shown[0], "remote"))
            [fresh] = devices[1].review_notes("list", Ticket(), lambda _: None)
            assert fresh["local"]["body"] == "Second laptop edit"
            devices[1].review_notes("list", Ticket(), lambda _: None, decision=(fresh, "remote"))
            assert not devices[1].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with closing(sqlite3.connect(laptop)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Second desktop edit",
                )
            with closing(sqlite3.connect(laptop)) as conn:
                (local,) = conn.execute(
                    "SELECT id FROM papers WHERE title='Research paper'"
                ).fetchone()
            def rewrite(path, key, body):
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.execute("UPDATE dives SET body=? WHERE paper_id=?", (body, key))

            def saved(path, key):
                with closing(sqlite3.connect(path)) as conn:
                    return conn.execute(
                        "SELECT body FROM dives WHERE paper_id=?", (key,)
                    ).fetchone()

            rewrite(laptop, local, "Revised explanation")
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert saved(source, "paper") == ("Revised explanation",)
            rewrite(laptop, local, "Sent before disconnect")
            with monkeypatch.context() as disconnect:
                disconnect.setattr(DiveHistory, "publish_batch",
                                   interrupt_after_publish(DiveHistory.publish_batch))
                with pytest.raises(ConnectionError, match="Acknowledgement lost"):
                    devices[1].sync_saved_library(Ticket(), lambda _: None)
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            assert saved(source, "paper") == ("Sent before disconnect",)
            rewrite(laptop, local, "Revised explanation")
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert saved(source, "paper") == saved(laptop, local) == ("Revised explanation",)
            rewrite(laptop, local, "Last common guide before both edits")
            with monkeypatch.context() as disconnect:
                disconnect.setattr(DiveHistory, "publish_batch",
                                   interrupt_after_publish(DiveHistory.publish_batch))
                with pytest.raises(ConnectionError, match="Acknowledgement lost"):
                    devices[1].sync_saved_library(Ticket(), lambda _: None)
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            rewrite(source, "paper", "Desktop edit after lost reply")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            rewrite(laptop, local, "Revised explanation")
            assert devices[1].sync_saved_library(Ticket(), lambda _: None)["dive_conflicts"]
            [card] = devices[1].review_notes("list", Ticket(), lambda _: None, feature="dive")
            assert [card[k]["body"] for k in ("base", "local", "remote")] == [
                "Last common guide before both edits", "Revised explanation",
                "Desktop edit after lost reply",
            ]
            devices[1].review_notes("list", Ticket(), lambda _: None, feature="dive",
                                    decision=(card, "local"))
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            rewrite(source, "paper", "Windows interpretation")
            rewrite(laptop, local, "Mac interpretation")
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            report = devices[1].sync_saved_library(Ticket(), lambda _: None)
            assert "explanations differ" in report["reviews"]["list"]
            assert saved(laptop, local) == ("Mac interpretation",)
            assert saved(source, "paper") == ("Windows interpretation",)
            assert report["dive_conflicts"] == ["list"]
            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute("UPDATE notes SET body='Offline note after conflict' WHERE page=5")
            reopened.hide()
            runner.timer.start(1)
            wait(app, lambda: runner.state == "working")
            wait(app, lambda: runner.worker is None)
            assert runner.state == "dive_conflict" and runner.timer.isActive()
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            with closing(sqlite3.connect(source)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Offline note after conflict",
                )
            assert saved(laptop, local) == ("Mac interpretation",)
            assert saved(source, "paper") == ("Windows interpretation",)
            reopened.show()
            key = "list", Ticket(), lambda _: None
            [card] = devices[1].review_notes(*key, feature="dive")
            assert card["base"]["body"] == "Revised explanation"
            rewrite(laptop, local, "Newer Mac version")
            with pytest.raises(ValueError, match="changed after review"):
                devices[1].review_notes(*key, feature="dive", decision=(card, "remote"))
            for button in ("稍後決定", "採用 Drive 版本"):
                observed = []

                def compare(dialog, observed=observed, button=button):
                    observed.extend(v.toPlainText() for v in dialog.findChildren(QPlainTextEdit))
                    next(b for b in dialog.findChildren(QPushButton) if b.text() == button).click()
                    return dialog.result()

                with monkeypatch.context() as interaction:
                    interaction.setattr(NoteComparison, "exec", compare)
                    reopened.compare_dives.click()
                    wait(app, lambda seen=observed: seen and not reopened.busy)
                assert observed == ["Revised explanation", "Newer Mac version",
                                    "Windows interpretation"]
            assert saved(laptop, local) == ("Windows interpretation",)
            assert not devices[1].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            rewrite(source, "paper", "Later desktop edit")
            rewrite(laptop, local, "Later Mac edit")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            [card] = devices[1].review_notes(*key, feature="dive")
            rewrite(source, "paper", "Desktop edit during review")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            with pytest.raises(ValueError, match="changed after review"):
                devices[1].review_notes(*key, feature="dive", decision=(card, "local"))
            [fresh] = devices[1].review_notes(*key, feature="dive")
            devices[1].review_notes(*key, feature="dive", decision=(fresh, "local"))
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert saved(source, "paper") == saved(laptop, local) == ("Later Mac edit",)
            def mark(path, key, state):
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.execute("UPDATE list_papers SET state=? WHERE list_id='list' "
                                 "AND paper_id=?", (state, key))
            def state_of(path, key):
                with closing(sqlite3.connect(path)) as conn:
                    return conn.execute("SELECT state FROM list_papers WHERE list_id='list' "
                                        "AND paper_id=?", (key,)).fetchone()[0]
            mark(source, "paper", "read")
            for device in devices:
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert state_of(laptop, local) == "read"
            from paper_daily.drive_list_history import DriveListReading

            publish = DriveListReading.append
            def lose_reply(history, *args, **kwargs):
                publish(history, *args, **kwargs)
                raise ConnectionError("Lost the upload confirmation")
            mark(laptop, local, "skipped")
            with monkeypatch.context() as disconnect:
                disconnect.setattr(DriveListReading, "append", lose_reply)
                with pytest.raises(ConnectionError, match="upload confirmation"):
                    devices[1].sync_saved_library(Ticket(), lambda _: None)
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert state_of(source, "paper") == "skipped"
            mark(laptop, local, "read")
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert state_of(source, "paper") == state_of(laptop, local) == "read"
            mark(laptop, local, "delivered")
            with monkeypatch.context() as disconnect:
                disconnect.setattr(DriveListReading, "append", lose_reply)
                with pytest.raises(ConnectionError, match="upload confirmation"):
                    devices[1].sync_saved_library(Ticket(), lambda _: None)
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            mark(source, "paper", "pending")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            mark(laptop, local, "read")
            assert devices[1].sync_saved_library(Ticket(), lambda _: None)["reading_conflicts"]
            [after_retry] = devices[1].review_notes(*key, feature="reading")
            assert [after_retry[k]["state"] for k in ("base", "local", "remote")] == [
                "delivered", "read", "pending",
            ]
            devices[1].review_notes(*key, feature="reading", decision=(after_retry, "local"))
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            with closing(sqlite3.connect(laptop)) as conn:
                assert conn.execute("SELECT count(*) FROM drive_reading_sends").fetchone() == (0,)
            mark(laptop, local, "skipped")
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert state_of(source, "paper") == "skipped"
            mark(laptop, local, "deferred")
            mark(source, "paper", "pending")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            report = devices[1].sync_saved_library(Ticket(), lambda _: None)
            assert report["reading_conflicts"] == ["list"]
            assert state_of(source, "paper") == "pending" and state_of(laptop, local) == "deferred"
            assert reopened.compare_reading.isVisible()
            [stale] = devices[1].review_notes(*key, feature="reading")
            mark(laptop, local, "read")
            with pytest.raises(ValueError, match="changed after review"):
                devices[1].review_notes(*key, feature="reading", decision=(stale, "remote"))
            [stale] = devices[1].review_notes(*key, feature="reading")
            mark(source, "paper", "delivered")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            with pytest.raises(ValueError, match="changed after review"):
                devices[1].review_notes(*key, feature="reading", decision=(stale, "local"))
            for button in ("稍後決定", "採用本機版本"):
                observed = []
                def compare_progress(dialog, observed=observed, button=button):
                    observed.extend(v.toPlainText() for v in dialog.findChildren(QPlainTextEdit))
                    next(b for b in dialog.findChildren(QPushButton) if b.text() == button).click()
                    return dialog.result()
                with monkeypatch.context() as interaction:
                    interaction.setattr(NoteComparison, "exec", compare_progress)
                    reopened.compare_reading.click()
                    wait(app, lambda seen=observed: seen and not reopened.busy)
                assert observed == ["已略過", "已讀", "已推送"]
            for device in reversed(devices):
                assert not device.sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert state_of(source, "paper") == "read"
            mark(source, "paper", "deferred")
            mark(laptop, local, "pending")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            [card] = devices[1].review_notes(*key, feature="reading")
            devices[1].review_notes(*key, feature="reading", decision=(card, "remote"))
            assert state_of(laptop, local) == "deferred"
            assert not devices[1].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            # Roll back the fixture after checking an identical, same-timestamp replacement.
            backup = laptop.with_name("before-reading-replacement.db")
            with closing(sqlite3.connect(laptop)) as src, closing(sqlite3.connect(backup)) as dst:
                src.backup(dst)
            with closing(sqlite3.connect(laptop)) as conn, conn:
                old = conn.execute("SELECT * FROM list_papers WHERE list_id='list' AND paper_id=?",
                                   (local,)).fetchone()
                conn.execute("DELETE FROM list_papers WHERE list_id='list' AND paper_id=?",
                             (local,))
                conn.execute("INSERT INTO list_papers VALUES(?,?,?,?,?,?,?,?)", old)
            mark(source, "paper", "read")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            objects = dict(cloud.objects)
            report = devices[1].sync_saved_library(Ticket(), lambda _: None)
            assert "membership was removed" in report["reviews"]["list"]
            assert state_of(laptop, local) == "deferred" and cloud.objects == objects
            with pytest.raises(ListReviewRequired, match="membership was removed"):
                devices[1].review_notes(*key, feature="reading")
            with closing(sqlite3.connect(backup)) as src, closing(sqlite3.connect(laptop)) as dst:
                src.backup(dst)
            devices[1].choose_reading_sync("list", False, Ticket(), lambda _: None)
            mac_pdf = laptop.parent / "pdf" / _legacy_pdf_name(local)
            other_pdf = (laptop.parent / "pdf" / "laptop-add.pdf").read_bytes()
            mac_pdf.write_bytes(other_pdf)
            rewrite(laptop, local, "Guide edited beside a divergent PDF")
            with closing(sqlite3.connect(laptop)) as conn, conn:
                conn.execute("UPDATE notes SET body='Reading on Mac' WHERE page=5")
            report = devices[1].sync_saved_library(Ticket(), lambda _: None)
            assert "local PDF differs" in report["reviews"]["list"]
            assert report["pdf_conflicts"] == ["list"]
            assert report["pdf_review_titles"] == {"list": ["Research paper"]}
            assert not devices[0].sync_saved_library(Ticket(), lambda _: None)["reviews"]
            assert saved(source, "paper") == ("Guide edited beside a divergent PDF",)
            reopened.hide()
            runner.tick()
            wait(app, lambda: runner.worker is None)
            assert runner.state == "pdf_conflict" and runner.timer.isActive()
            with closing(sqlite3.connect(source)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE page=5").fetchone() == (
                    "Reading on Mac",
                )
            rewrite(source, "paper", "Competing desktop guide")
            rewrite(laptop, local, "Competing laptop guide")
            devices[0].sync_saved_library(Ticket(), lambda _: None)
            runner.tick()
            wait(app, lambda: runner.worker is None)
            assert runner.state == "mixed_conflict" and runner.timer.isActive()
            assert saved(laptop, local) == ("Competing laptop guide",)
            assert saved(source, "paper") == ("Competing desktop guide",)
            assert reopened.close()
            reopened = DriveSyncDialog(closed.session, owner, owner=owner)
            reopened.show()
            wait(app, lambda: reopened.directory_lists.count() > 0 and not reopened.busy)
            assert reopened.pdf_reviews.isVisible()
            assert reopened.pdf_reviews.item(0).text() == "Research paper"
            assert mac_pdf.read_bytes() == other_pdf
            with pymupdf.open(source.parent / "pdf" / "paper.pdf") as document:
                assert document[0].get_text().strip() == "paper"
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
            assert not reopened.pdf_reviews.isVisible()
            assert not setup._library_view[1].load().selected
            assert setup._library_view[1].pdf_lists() == []
            assert setup._library_view[1].dive_lists() == []
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
    from paper_daily.drive_reader_notes import exchange_reader_notes

    # Pre-edit clients stored a plain grant ID. Refreshing must retain that consent scope.
    with closing(sqlite3.connect(store.path)) as settings, settings:
        settings.execute("UPDATE note_grants SET grant_id='original-grant' WHERE list_id='list'")
    exchange_reader_notes(directory, store, "list", 1, Ticket())
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE notes SET body='Offline edit' WHERE paper_id='paper'")
    count = len(cloud.objects)
    with pytest.raises(ListReviewRequired, match="retain both"):
        publish_reader_notes(directory, store, "list", 1, Ticket())
    with pytest.raises(ListReviewRequired, match="retain both"):
        exchange_reader_notes(directory, store, "list", 1, Ticket())
    assert len(cloud.objects) == count
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT body FROM notes WHERE paper_id='paper'").fetchone() == (
            "Offline edit",
        )



def test_idle_pdf_poll_skips_history_and_missing_paths_but_discovers_later_pdf(
    source, tmp_path, monkeypatch,
):
    from pathlib import Path

    from test_workspace_enrollment import pdf

    from paper_daily.drive_reader_originals import exchange_originals

    with closing(sqlite3.connect(source)) as conn, conn:
        for number in range(40):
            key = f"missing-{number}"
            conn.execute("INSERT INTO papers(id,title,title_key,venue,year,source) "
                         "VALUES(?,?,?,'Fixture',2026,'fixture')", (key, key, key))
            conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                         "VALUES('list',?,?,?)", (key, number + 1, STAMP))
    cloud = Cloud()
    files = authority(cloud, tmp_path / "authority").files
    folder, head = files.new_ids(2)
    directory = DriveDirectory(files, folder, head, "library")
    catalog = directory.upsert(directory.initialize("Library"), [
        ListEntry("list", "Reading", False)
    ]).directory
    store = selection(source, tmp_path / "settings")
    store.save(catalog, ["list"], expected_revision=0)
    publish_initial(directory, store, "list", 1, Ticket())
    store.set_pdf_sync("list", True, revision=1, ticket=Ticket())
    (source.parent / "pdf").mkdir()
    memory = {}

    def poll():
        exchange_originals(directory, tmp_path / "cache", store, "list", 1, Ticket(), memory)

    history_reads, misses = [], []
    read, exists = files.read_small, Path.exists

    def observe_read(*args, **kwargs):
        raw = read(*args, **kwargs)
        if b'"format":"paperfact.list-paper-history.v1"' in raw:
            history_reads.append(len(raw))
        return raw

    def observe_path(path):
        if path.parent == source.parent / "pdf" and path.name.startswith("missing-"):
            misses.append(path.name)
        return exists(path)

    monkeypatch.setattr(files, "read_small", observe_read)
    monkeypatch.setattr(Path, "exists", observe_path)
    poll()
    assert len(history_reads) == 1
    history_reads.clear()
    count = len(cloud.objects)
    poll()
    assert not history_reads and not misses and len(cloud.objects) == count
    pdf(source)
    poll()
    assert not history_reads and not misses
    assert directory.read().directory.lists[0].originals_head is not None


def test_restore_ordinary_library_grant_without_browser_or_research_transfer(
    source, tmp_path, monkeypatch
):
    from test_drive_sync_files import GrantStore

    from paper_daily import drive_sync_setup
    from paper_daily.drive_sync_credentials import DriveGrant
    from paper_daily.workspace_service import Cancelled

    cloud, native = Cloud(), GrantStore()
    files = authority(cloud, tmp_path / "device").files
    files.session.client = {"client_id": "fixture.apps.googleusercontent.com"}
    files.session.token = {"refresh_token": "fixture-refresh"}
    monkeypatch.setattr(drive_sync_setup, "DriveFiles", lambda *args, **kwargs: files)
    monkeypatch.setattr(DriveGrant, "session", lambda self: files.session)
    options = dict(backend=lambda: native, profiles=tmp_path / "profiles",
                   cache=tmp_path / "cache")

    def progress(_):
        pass

    first = drive_sync_setup.DriveSetup(source, **options, authorize=lambda **kw: files.session)
    first.sign_in(Ticket(), progress)
    with pytest.raises(ValueError, match="selection"):
        first.remember_library(Ticket())
    first.apply_library(["list"], Ticket(), progress)
    cancelled = Ticket()
    cancelled.cancel()
    with pytest.raises(Cancelled):
        first.remember_library(cancelled)
    assert not native.rows
    first.remember_library(Ticket())
    assert first.library_startup_record() is None
    first.remember_library(Ticket(), startup=True)
    stamp = first.library_startup_record()
    assert stamp and len(native.rows) == 1
    before, objects = source.read_bytes(), dict(cloud.objects)

    def unexpected(**kwargs):
        pytest.fail("Restoring a saved grant opened a browser")

    second = drive_sync_setup.DriveSetup(source, **options, authorize=unexpected)
    assert second.files is None
    overview = second.reconnect_library(Ticket(), progress, startup_record=stamp)
    assert [row["id"] for row in overview["library"]["items"] if row["selected"]] == ["list"]
    assert before == source.read_bytes() and objects == cloud.objects

    third = drive_sync_setup.DriveSetup(source, **options, authorize=unexpected)
    with monkeypatch.context() as patch:
        patch.setattr(files, "account", lambda: {"id": "another-owner"})
        with pytest.raises(PermissionError, match="account changed"):
            third.reconnect_library(Ticket(), progress)
    assert third.files is None and third.account is None
    third.disable_library_startup(Ticket())
    assert third.library_startup_record() is None and native.rows
    with pytest.raises(PermissionError, match="disabled"):
        third.reconnect_library(Ticket(), progress, startup_record=stamp)
    first.remember_library(Ticket(), startup=True)
    first.sign_in(Ticket(), progress)
    assert first.library_startup_record() is None
    third.forget_library(Ticket())
    with pytest.raises(PermissionError, match="Sign in"):
        third.reconnect_library(Ticket(), progress)
    assert not native.rows and before == source.read_bytes() and objects == cloud.objects
