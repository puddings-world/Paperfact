"""Per-list pins follow a membership incarnation, never offline-retention settings."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_reference_edges import SOURCE, TARGET, query, write
from test_reference_edges import pair as pair

from paper_daily import store
from paper_daily.list_pins import set_pinned
from paper_daily.sync_capture import CaptureConnection, StaleCaptureError, expecting, observe_target
from paper_daily.sync_content import content_id
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_schema_v2 import membership_id

LIST = "pin-list"
OTHER_LIST = "other-pin-list"
STAMP = "2026-10-30T00:00:00+00:00"


@pytest.fixture
def pins(pair):
    a, b, service, ta, tb = pair
    for list_id in (LIST, OTHER_LIST):
        a.save(a.new_graph_operation("list", list_id, {"name": list_id, "note": ""}))
        for paper_id in (SOURCE, TARGET):
            a.save(
                a.new_graph_operation(
                    "membership",
                    membership_id(list_id, paper_id),
                    {"list_id": list_id, "paper_id": paper_id, "citation": None, "added_at": STAMP},
                )
            )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    return pair


def toggle(side, on=True, scope=LIST, paper="a-source", **kwargs):
    with closing(sqlite3.connect(side.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = set_pinned(conn, scope, paper, on, **kwargs)
        conn.commit()
        return result


def test_actual_desktop_toggle_updates_visible_flag_and_is_idempotent(pins, monkeypatch):
    from paper_daily.desktop.main import Data

    a, b, service, ta, tb = pins
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    data = Data()
    before = query(a, "SELECT list_id,paper_id,position FROM list_papers ORDER BY list_id,paper_id")
    data.set_pin(LIST, "a-source", True)
    first = a.journal.pending()
    assert data.pins(LIST) == {"a-source"}
    assert len(first) == 1 and first[0]["payload"]["feature"] == "list_pin"
    assert [p["kind"] for p in first[0]["parents"]] == ["list", "paper", "membership"]
    data.set_pin(LIST, "a-source", True)
    assert a.journal.pending() == first
    assert (
        query(a, "SELECT list_id,paper_id,position FROM list_papers ORDER BY list_id,paper_id")
        == before
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id FROM pins") == [(LIST, "b-source")]
    data.set_pin(LIST, "a-source", False)
    second = a.journal.pending()
    assert second[0]["action"] == "delete" and data.pins(LIST) == set()
    data.set_pin(LIST, "a-source", False)
    assert a.journal.pending() == second
    data.set_pin(LIST, "a-source", True)
    assert a.journal.pending()[-1]["incarnation"] != first[0]["incarnation"]


def test_same_paper_can_be_pinned_independently_in_two_lists(pins):
    a, b, service, ta, tb = pins
    toggle(a, scope=LIST, pinned_at=STAMP)
    toggle(a, scope=OTHER_LIST, pinned_at=STAMP)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id,pinned_at FROM pins ORDER BY scope") == [
        (OTHER_LIST, "b-source", STAMP),
        (LIST, "b-source", STAMP),
    ]
    toggle(a, False, scope=LIST)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope FROM pins") == [(OTHER_LIST,)]


def test_sql_cascade_records_pin_delete_before_membership_and_does_not_resurrect(pins):
    a, b, service, ta, tb = pins
    toggle(a, pinned_at=STAMP)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    write(a, "DELETE FROM list_papers WHERE list_id=? AND paper_id=?", (LIST, "a-source"))
    pending = a.journal.pending()
    pin = next(op for op in pending if op["entity_type"] == "research_content")
    member = next(op for op in pending if op["entity_type"] == "membership")
    assert pin["action"] == "delete" and member["action"] == "delete"
    assert pending.index(pin) < pending.index(member)
    assert query(a, "SELECT * FROM pins") == []
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM pins") == []
    restored = a.new_graph_operation(
        "membership",
        membership_id(LIST, SOURCE),
        {"list_id": LIST, "paper_id": SOURCE, "citation": None, "added_at": STAMP},
        restore=True,
    )
    a.save(restored)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM pins") == []
    assert toggle(a, pinned_at=STAMP)["changed"]
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id FROM pins") == [(LIST, "b-source")]


def test_typed_membership_delete_also_hides_prior_pin_and_preserves_history(pins):
    a, b, service, ta, tb = pins
    toggle(a, pinned_at=STAMP)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    old = a.history()
    a.save(a.new_graph_operation("membership", membership_id(LIST, SOURCE), {}, action="delete"))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(a, "SELECT * FROM pins") == query(b, "SELECT * FROM pins") == []
    assert all(event in a.history() for event in old)
    a.save(
        a.new_graph_operation(
            "membership",
            membership_id(LIST, SOURCE),
            {"list_id": LIST, "paper_id": SOURCE, "citation": None, "added_at": STAMP},
            restore=True,
        )
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(a, "SELECT * FROM pins") == query(b, "SELECT * FROM pins") == []


def test_raw_sql_cannot_restore_a_tombstone_but_explicit_current_toggle_can(pins):
    a, *_ = pins
    toggle(a, pinned_at=STAMP)
    toggle(a, False)
    before = a.journal.pending()
    with pytest.raises(StaleCaptureError):
        write(a, "INSERT INTO pins VALUES(?,?,?)", (LIST, "a-source", STAMP))
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        token = observe_target(conn, "list", LIST, "list_pin", SOURCE)
        conn.execute("BEGIN IMMEDIATE")
        with expecting(conn, [token]):
            conn.execute("INSERT INTO pins VALUES(?,?,?)", (LIST, "a-source", STAMP))
            with pytest.raises(ValueError, match="restore=True"):
                conn.commit()
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
    assert toggle(a, pinned_at=STAMP)["changed"]


def test_stale_toggle_observation_cannot_pin_recreated_membership(pins):
    a, *_ = pins
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        expected = observe_target(conn, "list", LIST, "list_pin", SOURCE)
    a.save(a.new_graph_operation("membership", membership_id(LIST, SOURCE), {}, action="delete"))
    a.save(
        a.new_graph_operation(
            "membership",
            membership_id(LIST, SOURCE),
            {"list_id": LIST, "paper_id": SOURCE, "citation": None, "added_at": STAMP},
            restore=True,
        )
    )
    before = a.journal.pending()
    with pytest.raises(ValueError, match="membership changed"):
        toggle(a, expected=expected, pinned_at=STAMP)
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before


@pytest.mark.parametrize("kind", ["missing", "missing-queue-paper", "not-member"])
def test_invalid_pin_target_has_no_saved_data_or_operation(pins, kind):
    a, *_ = pins
    before = a.journal.pending()
    with pytest.raises(ValueError):
        toggle(
            a,
            scope="queue"
            if kind == "missing-queue-paper"
            else "missing"
            if kind == "missing"
            else LIST,
            paper="absent-paper"
            if kind == "missing-queue-paper"
            else "a-other"
            if kind == "not-member"
            else "a-source",
            pinned_at=STAMP,
        )
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before


def test_transaction_failure_and_close_roll_back_pin_and_outbox(pins):
    a, *_ = pins
    before = a.journal.pending()
    conn = sqlite3.connect(a.journal.path, factory=CaptureConnection)
    conn.execute("BEGIN IMMEDIATE")
    set_pinned(conn, LIST, "a-source", True, pinned_at=STAMP)
    conn.close()
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        set_pinned(conn, LIST, "a-source", True, pinned_at=STAMP)
        conn.rollback()
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before


def test_pin_conflict_keeps_versions_and_explicit_restore_resolves(pins):
    a, b, service, ta, tb = pins
    toggle(a, pinned_at=STAMP)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    toggle(a, False)
    # Update a saved pin's timestamp using an explicitly observed content edit.
    identity = content_id({"kind": "list", "id": LIST}, "list_pin", SOURCE)
    payload = {
        "scope": {"kind": "list", "id": LIST},
        "feature": "list_pin",
        "key": SOURCE,
        "data": {"pinned_at": "2026-10-30T01:00:00+00:00"},
        "source_document_hash": None,
    }
    b.save(b.new_graph_operation("research_content", identity, payload))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert b.status()["conflicts"] == 1 and query(b, "SELECT * FROM pins") == []
    conflict = b.history(conflicts_only=True)[-1]
    b.resolve_conflict(conflict["sequence"], restore=True)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert b.status()["conflicts"] == 0
    assert query(a, "SELECT pinned_at FROM pins") == [("2026-10-30T01:00:00+00:00",)]


@pytest.mark.parametrize("change", ["wrong-member", "wrong-root", "reordered", "missing-root"])
def test_wire_pin_requires_exact_ordered_membership_pair(pins, change):
    a, *_ = pins
    toggle(a, pinned_at=STAMP)
    operation = a.journal.pending()[0]
    if change == "wrong-member":
        operation["parents"][2]["id"] = membership_id(OTHER_LIST, SOURCE)
    elif change == "wrong-root":
        operation["parents"][1]["id"] = TARGET
    elif change == "reordered":
        operation["parents"].reverse()
    else:
        operation["parents"].pop(0)
    with pytest.raises(ValueError):
        canonical_operation(operation)


def test_atomic_desktop_batch_rolls_back_missing_second_selection(pins, monkeypatch):
    from paper_daily.desktop.main import Data

    a, *_ = pins
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    data = Data()
    before = a.journal.pending()
    with pytest.raises(ValueError):
        data.set_pins(LIST, ["a-source", "a-other"], True)
    assert data.pins(LIST) == set() and a.journal.pending() == before
    data.set_pins(LIST, [], True)
    assert a.journal.pending() == before
    data.set_pins(LIST, ["a-source", "a-target", "a-source"], True)
    first = a.journal.pending()
    assert len(first) == 2 and data.pins(LIST) == {"a-source", "a-target"}
    data.set_pins(LIST, ["a-source", "a-target"], True)
    assert a.journal.pending() == first


def test_concurrent_repeated_toggle_creates_one_current_pin(pins):
    from concurrent.futures import ThreadPoolExecutor

    a, *_ = pins
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _index: toggle(a, pinned_at=STAMP), range(12)))
    assert sum(result["changed"] for result in results) == 1
    assert len(a.journal.pending()) == 1
    assert query(a, "SELECT scope,paper_id,pinned_at FROM pins") == [(LIST, "a-source", STAMP)]


def test_membership_cascade_is_transactional_and_preserves_other_list_pin(pins):
    a, *_ = pins
    toggle(a, pinned_at=STAMP)
    toggle(a, scope=OTHER_LIST, pinned_at=STAMP)
    before = a.journal.pending()
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM list_papers WHERE list_id=? AND paper_id=?", (LIST, "a-source"))
        conn.rollback()
    assert query(a, "SELECT scope FROM pins ORDER BY scope") == [(OTHER_LIST,), (LIST,)]
    assert a.journal.pending() == before
    write(a, "DELETE FROM list_papers WHERE list_id=? AND paper_id=?", (LIST, "a-source"))
    assert query(a, "SELECT scope FROM pins") == [(OTHER_LIST,)]


def legacy(root, *, scope=LIST, member=True):
    root.mkdir()
    database = root / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Paper','paper','Fixture',2026,'fixture')"
        )
        conn.execute("INSERT INTO lists VALUES(?,?,?,?)", (LIST, "Reading", "", STAMP))
        if member:
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,'paper',0,?)",
                (LIST, STAMP),
            )
        conn.execute("INSERT INTO pins VALUES(?,'paper',?)", (scope, STAMP))
    return database


def test_lossless_enrollment_and_recovery_keep_current_membership_pin(tmp_path):
    from paper_daily import sync_recovery
    from paper_daily.workspace_enrollment import EnrollmentService

    database = legacy(tmp_path / "legacy")
    service = EnrollmentService(database)
    assert service.plan()["supported"]
    result = service.prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id="11111111-1111-4111-8111-111111111111",
    )
    with closing(sqlite3.connect(result["database"])) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == [(LIST, "paper", STAMP)]
        operation = json.loads(
            conn.execute(
                "SELECT envelope FROM paperfact_sync_operations "
                "WHERE entity_type='research_content'"
            ).fetchone()[0]
        )
        assert operation["payload"]["feature"] == "list_pin"
        assert [parent["kind"] for parent in operation["parents"]] == [
            "list",
            "paper",
            "membership",
        ]
    sync_recovery.restore_detached(result["backup"], tmp_path / "restored")
    with closing(sqlite3.connect(tmp_path / "restored/papers.db")) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == [(LIST, "paper", STAMP)]


@pytest.mark.parametrize("kind", ["unknown-scope", "orphan"])
def test_unknown_scope_or_orphan_list_pin_is_an_explicit_preflight_blocker(tmp_path, kind):
    from paper_daily.workspace_enrollment import EnrollmentBlocked, EnrollmentService

    database = legacy(
        tmp_path / "legacy",
        scope="unknown-list" if kind == "unknown-scope" else LIST,
        member=kind != "orphan",
    )
    service = EnrollmentService(database)
    plan = service.plan()
    assert not plan["supported"]
    assert any(
        "pins require migration" in message or "existing list membership" in message
        for message in plan["blockers"]
    )
    with pytest.raises(EnrollmentBlocked):
        service.prepare(
            tmp_path / "candidate",
            backup_output=tmp_path / "backup.zip",
            request_id="11111111-1111-4111-8111-111111111111",
        )
    assert not (tmp_path / "candidate").exists()
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pins").fetchone() == (1,)


def test_unbound_queue_behavior_and_membership_cleanup_remain_local(tmp_path):
    database = legacy(tmp_path / "legacy")
    with closing(sqlite3.connect(database)) as conn:
        set_pinned(conn, "queue", "paper", True, pinned_at=STAMP)
        conn.commit()
        conn.execute("DELETE FROM list_papers")
        conn.commit()
        assert conn.execute("SELECT scope FROM pins").fetchall() == [("queue",)]
        set_pinned(conn, "queue", "paper", False)
        conn.commit()
        assert conn.execute("SELECT * FROM pins").fetchall() == []


def test_pin_list_package_roundtrip_preserves_flags_without_sync_identity(tmp_path, monkeypatch):
    from paper_daily import bundle

    database = legacy(tmp_path / "legacy")
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", database.parent / "pdf")
    made = bundle.export(LIST, tmp_path / "shared.zip", with_pdfs=False)
    destination = tmp_path / "receiver"
    destination.mkdir()
    monkeypatch.setattr(store, "DB_PATH", destination / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", destination)
    monkeypatch.setattr(bundle, "PDF_DIR", destination / "pdf")
    store.init_db()
    report = bundle.import_(made["out"])
    assert report["pins"] == 1
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == [(LIST, "paper", STAMP)]
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchall()


def test_read_only_sql_snapshot_contains_only_actual_list_membership_pins(tmp_path):
    from paper_daily.sync_projection import read_manifest

    database = legacy(tmp_path / "legacy")
    from paper_daily.sync_research import prepare

    prepare(database, workspace_id="snapshot", device_id="reader")
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("INSERT INTO pins VALUES('queue','paper',?)", (STAMP,))
        conn.execute("INSERT INTO pins VALUES('orphan','paper',?)", (STAMP,))
    result = read_manifest(database, workspace_id="snapshot")
    assert result["lists"][0]["members"][0]["pinned"] is True
    assert result["lists"][0]["members"][0]["pinned_at"] == STAMP
    assert result["lists"][0]["members"][0]["position"] == 0
    assert len(result["lists"]) == 1


def test_explicit_toggle_migrates_cleanup_schema_in_caller_transaction(pins):
    a, *_ = pins
    with a.journal.transaction() as conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
    before = a.journal.pending()
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        set_pinned(conn, LIST, "a-source", True, pinned_at=STAMP)
        assert conn.in_transaction
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_pin_membership_delete'"
        ).fetchone()
        conn.rollback()
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
    assert not query(a, "SELECT 1 FROM sqlite_master WHERE name='paperfact_pin_membership_delete'")
    toggle(a, pinned_at=STAMP)
    assert query(a, "SELECT 1 FROM sqlite_master WHERE name='paperfact_pin_membership_delete'")


def test_remote_pin_requires_explicit_schema_install_and_retries_cleanly(pins):
    from paper_daily.sync_capture import install

    a, b, service, ta, tb = pins
    with b.journal.transaction() as conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
    toggle(a, pinned_at=STAMP)
    a.sync_once(service, ta)
    events = service.pull(tb, after=b.status()["cursor"])
    cursor = b.status()["cursor"]
    with pytest.raises(ValueError, match="schema migration"):
        b.receive(events)
    assert b.status()["cursor"] == cursor and query(b, "SELECT * FROM pins") == []
    with closing(sqlite3.connect(b.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="b")
        conn.commit()
    b.receive(events)
    assert query(b, "SELECT scope,paper_id FROM pins") == [(LIST, "b-source")]


def test_pin_membership_closure_cannot_mix_new_roots_with_old_membership(pins):
    from copy import deepcopy

    from paper_daily.sync_graph import check_preconditions

    a, *_ = pins
    toggle(a, pinned_at=STAMP)
    operation = a.journal.pending()[0]
    with a.journal.transaction() as conn:
        graph = deepcopy(a._optimistic_graph(conn)[0])
    assert check_preconditions(
        lambda kind, identity: graph.get((kind, identity)), lambda _id: None, operation
    )
    graph[("list", LIST)]["incarnation"] = "new-list-root"
    operation["parents"][0]["incarnation"] = "new-list-root"
    # Every supplied parent matches its current graph record, but the member's
    # retained list root is still old. A kind/id-only closure check would miss it.
    assert not check_preconditions(
        lambda kind, identity: graph.get((kind, identity)), lambda _id: None, operation
    )


def test_atomic_desktop_batch_rolls_back_unprojected_second_membership(pins, monkeypatch):
    from paper_daily.desktop.main import Data

    a, *_ = pins
    with a.journal.transaction() as conn:
        identity = membership_id(LIST, TARGET)
        metadata = a._graph_entity(conn, "membership", identity)
        metadata["incarnation"] = "unprojected-member"
        conn.execute(
            "UPDATE paperfact_sync_graph SET metadata=? "
            "WHERE entity_type='membership' AND entity_id=?",
            (json.dumps(metadata), identity),
        )
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    before = a.journal.pending()
    with pytest.raises(ValueError, match="exact projected membership"):
        Data().set_pins(LIST, ["a-source", "a-target"], True)
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before


def test_same_named_wrong_cleanup_trigger_cannot_claim_pin_safety(pins):
    a, *_ = pins
    with a.journal.transaction() as conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
        conn.execute(
            "CREATE TRIGGER paperfact_pin_membership_delete "
            "AFTER DELETE ON list_papers BEGIN SELECT 1; END"
        )
    before = a.journal.pending()
    with pytest.raises(ValueError, match="explicit repair"):
        toggle(a, pinned_at=STAMP)
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before


def test_enrollment_preflight_preserves_unexpected_same_named_pin_writer(tmp_path):
    from paper_daily.workspace_enrollment import EnrollmentBlocked, EnrollmentService

    database = legacy(tmp_path / "legacy")
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
        conn.execute(
            "CREATE TRIGGER paperfact_pin_membership_delete "
            "AFTER DELETE ON list_papers BEGIN SELECT 1; END"
        )
    before = database.read_bytes()
    service = EnrollmentService(database)
    assert "pin cleanup trigger requires review" in service.plan()["blockers"]
    with pytest.raises(EnrollmentBlocked):
        service.prepare(
            tmp_path / "candidate",
            backup_output=tmp_path / "backup.zip",
            request_id="11111111-1111-4111-8111-111111111111",
        )
    assert database.read_bytes() == before
    assert not (tmp_path / "candidate").exists()


def test_actual_window_failure_reports_safe_status_without_changing_visible_selection(
    pins, tmp_path, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from paper_daily import llm
    from paper_daily.desktop.account_status import AccountStatus
    from paper_daily.desktop.main import MainWindow
    from paper_daily.desktop.queue_view import PAPER_ROLE, QueuePage

    a, *_ = pins
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "fixture-llm.json")
    monkeypatch.setattr(llm, "complete", lambda *_args, **_kwargs: pytest.fail("pin called AI"))
    monkeypatch.setattr(AccountStatus, "check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(MainWindow, "top_up_dives", lambda *_args: None)
    monkeypatch.setattr(QueuePage, "enqueue_pdfs", lambda *_args: None)
    app = QApplication.instance() or QApplication([])
    widget = MainWindow()
    widget.active_list = LIST
    widget.reload()
    widget.stack.setCurrentWidget(widget.queue_page)
    widget.show()
    widget.queue_page.view.setCurrentIndex(widget.queue_page.model.index(0, 0))
    app.processEvents()
    selected = widget.queue_page.view.currentIndex().data(PAPER_ROLE).id
    order = [paper.id for _index, paper in widget.queue_page.model._rows]
    flags = [(paper.id, paper.pinned) for paper in widget.papers]
    before = a.journal.pending()
    try:
        with a.journal.transaction() as conn:
            identity = membership_id(LIST, TARGET)
            metadata = a._graph_entity(conn, "membership", identity)
            metadata["incarnation"] = "unprojected-current-member"
            conn.execute(
                "UPDATE paperfact_sync_graph SET metadata=? "
                "WHERE entity_type='membership' AND entity_id=?",
                (json.dumps(metadata), identity),
            )
        assert widget.set_pinned(["a-source", "a-target"], True) is False
        assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
        assert [(paper.id, paper.pinned) for paper in widget.papers] == flags
        assert [paper.id for _index, paper in widget.queue_page.model._rows] == order
        assert widget.queue_page.view.currentIndex().data(PAPER_ROLE).id == selected
        assert widget.progress.text()
        assert any(job.state == "error" for job in widget.activity_hub.jobs.values())

        real_set_pins = widget.data.set_pins

        def fail(*_args):
            raise sqlite3.OperationalError("private/path secret-token")

        monkeypatch.setattr(widget.data, "set_pins", fail)
        assert widget.set_pinned(["a-source"], True) is False
        visible = widget.progress.text() + " ".join(
            job.stage for job in widget.activity_hub.jobs.values()
        )
        assert "private/path" not in visible and "secret-token" not in visible
        assert widget.queue_page.view.currentIndex().data(PAPER_ROLE).id == selected
        assert widget.progress.isVisible()
        monkeypatch.setattr(widget.data, "set_pins", real_set_pins)
        monkeypatch.setattr(
            widget,
            "reload",
            lambda: (_ for _ in ()).throw(sqlite3.OperationalError("private/refresh secret-token")),
        )
        assert widget.set_pinned(["a-source"], True) is True
        assert query(a, "SELECT scope,paper_id FROM pins") == [(LIST, "a-source")]
        assert [(paper.id, paper.pinned) for paper in widget.papers] == flags
        assert "private/refresh" not in widget.progress.text()
        assert "secret-token" not in widget.progress.text()
        assert widget.queue_page.view.currentIndex().data(PAPER_ROLE).id == selected
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("kind", ["trusted-journal", "ordinary-sqlite"])
def test_enrolled_pin_api_rejects_non_capture_connections_without_outbox_bypass(pins, kind):
    a, *_ = pins
    before = a.journal.pending()
    if kind == "trusted-journal":
        with a.journal.transaction() as conn:
            conn.execute("INSERT INTO kv VALUES('ui.fixture','caller-owned')")
            with pytest.raises(ValueError, match="CaptureConnection"):
                set_pinned(conn, LIST, "a-source", True, pinned_at=STAMP)
            assert conn.in_transaction
    else:
        with (
            closing(sqlite3.connect(a.journal.path)) as conn,
            pytest.raises(ValueError, match="CaptureConnection"),
        ):
            set_pinned(conn, LIST, "a-source", True, pinned_at=STAMP)
    assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
