"""Queue pins preserve paper intent independently of lists and daily queue rows."""

import copy
import sqlite3
from contextlib import closing

import pytest
from test_list_pins import pins as pins
from test_reference_edges import SOURCE, query
from test_reference_edges import pair as pair

from paper_daily.list_pins import set_pinned
from paper_daily.sync_capture import CaptureConnection, observe_target
from paper_daily.sync_content import TABLE_FEATURES, content_payload, validate_payload

STAMP = "2026-10-30T00:00:00+00:00"


def toggle(side, on=True, **kwargs):
    with closing(sqlite3.connect(side.journal.path, factory=CaptureConnection)) as conn:
        result = set_pinned(conn, "queue", "a-source", on, pinned_at=STAMP, **kwargs)
        conn.commit()
        return result


def test_orphan_queue_pin_actual_writer_two_peers_and_idempotence(pair):
    a, b, service, ta, tb = pair
    before = len(a.journal.pending())
    assert toggle(a)["changed"]
    assert not toggle(a)["changed"]
    assert len(a.journal.pending()) == before + 1
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id,pinned_at FROM pins") == [("queue", "b-source", STAMP)]
    assert query(b, "SELECT * FROM queue") == []
    assert query(b, "SELECT * FROM list_papers") == []
    assert toggle(a, False)["changed"]
    assert not toggle(a, False)["changed"]
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM pins") == []
    assert toggle(a)["changed"]
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT pinned_at FROM pins") == [(STAMP,)]


def test_queue_pin_serializer_is_closed_and_does_not_replace_list_default(pair):
    a, *_ = pair
    toggle(a)
    with closing(sqlite3.connect(a.journal.path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM pins").fetchone()
        payload = content_payload(conn, "pins", row)
    assert TABLE_FEATURES["pins"] == "list_pin"
    assert payload == {
        "scope": {"kind": "paper", "id": SOURCE},
        "feature": "queue_pin",
        "key": "main",
        "data": {"pinned_at": STAMP},
        "source_document_hash": None,
    }
    for field, value in (
        ("key", SOURCE),
        ("source_document_hash", "a" * 64),
        ("scope", {"kind": "list", "id": "queue"}),
        ("data", {"pinned_at": "2026-10-30T00:00:00"}),
        ("data", {"pinned_at": STAMP, "other": 1}),
    ):
        bad = copy.deepcopy(payload)
        bad[field] = value
        with pytest.raises((ValueError, TypeError)):
            validate_payload(bad)


def test_queue_pin_stale_observation_and_transaction_rollback(pair):
    a, *_ = pair
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        expected = observe_target(conn, "paper", "a-source", "queue_pin")
    toggle(a)
    before = a.journal.pending()
    with pytest.raises(ValueError, match="changed"):
        toggle(a, False, expected=expected)
    assert a.journal.pending() == before
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        set_pinned(conn, "queue", "a-source", False)
        conn.rollback()
    assert query(a, "SELECT pinned_at FROM pins") == [(STAMP,)]
    assert a.journal.pending() == before


@pytest.mark.parametrize("mode", ["raw", "explicit"])
def test_deleted_pin_requires_explicit_intent_and_new_incarnation(pair, mode):
    from test_reference_edges import write

    from paper_daily.sync_capture import CaptureError

    a, b, service, ta, tb = pair
    toggle(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    with a.journal.transaction() as conn:
        from paper_daily.sync_content import content_id

        identity = content_id({"kind": "paper", "id": SOURCE}, "queue_pin", "main")
        before_inc = a._graph_entity(conn, "research_content", identity)["incarnation"]
    toggle(a, False)
    before = a.journal.pending()
    if mode == "raw":
        with pytest.raises((ValueError, CaptureError)):
            write(a, "INSERT INTO pins VALUES('queue','a-source',?)", (STAMP,))
        assert query(a, "SELECT * FROM pins") == [] and a.journal.pending() == before
    else:
        toggle(a)
        assert a.journal.pending()[-1]["incarnation"] != before_inc
        a.sync_once(service, ta)
        b.sync_once(service, tb)
        assert query(b, "SELECT pinned_at FROM pins") == [(STAMP,)]


def test_raw_capture_requires_observed_existing_target_and_preserves_timestamp(pair):
    from test_reference_edges import write

    from paper_daily.sync_capture import CaptureError, expecting

    a, b, service, ta, tb = pair
    write(a, "INSERT INTO pins VALUES('queue','a-source',?)", (STAMP,))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    before = a.journal.pending()
    changed = "2026-10-31T02:00:00+00:00"
    with pytest.raises((ValueError, CaptureError)):
        write(a, "UPDATE pins SET pinned_at=? WHERE scope='queue'", (changed,))
    assert a.journal.pending() == before
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        token = observe_target(conn, "paper", "a-source", "queue_pin")
        with expecting(conn, [token]):
            conn.execute("UPDATE pins SET pinned_at=? WHERE scope='queue'", (changed,))
            conn.commit()
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT pinned_at FROM pins") == [(changed,)]


def test_pin_parent_epoch_change_refuses_stale_loaded_target_and_wrong_projection(pair):
    import json
    from copy import deepcopy

    from paper_daily.sync_content import content_id, write_content

    a, b, service, ta, tb = pair
    toggle(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    with closing(sqlite3.connect(b.journal.path, factory=CaptureConnection)) as conn:
        old = observe_target(conn, "paper", "b-source", "queue_pin")
    with b.journal.transaction() as conn:
        parent = b._graph_entity(conn, "paper", SOURCE)
        parent["incarnation"] = "replacement-paper"
        conn.execute(
            "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='paper' AND entity_id=?",
            (json.dumps(parent), SOURCE),
        )
    b.receive([])
    assert query(b, "SELECT * FROM pins") == []
    before = b.journal.pending()
    with (
        closing(sqlite3.connect(b.journal.path, factory=CaptureConnection)) as conn,
        pytest.raises(ValueError, match="changed"),
    ):
        set_pinned(conn, "queue", "b-source", True, expected=old, pinned_at=STAMP)
    assert b.journal.pending() == before
    payload = {
        "scope": {"kind": "paper", "id": SOURCE},
        "feature": "queue_pin",
        "key": "main",
        "data": {"pinned_at": STAMP},
        "source_document_hash": None,
    }
    operation = a.new_graph_operation(
        "research_content", content_id(payload["scope"], "queue_pin", "main"), payload
    )
    wrong = deepcopy(operation)
    wrong["parents"][0]["incarnation"] = "foreign-paper"
    with a.journal.transaction() as conn, pytest.raises(ValueError, match="exact materialized"):
        write_content(conn, wrong)
    assert query(a, "SELECT pinned_at FROM pins") == [(STAMP,)]


@pytest.mark.parametrize(
    "case",
    __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent / "fixtures/queue-pins.json").read_text(
            encoding="utf8"
        )
    ),
    ids=lambda c: c["name"],
)
def test_queue_pin_frozen_wire_golden(case):
    if case["valid"]:
        validate_payload(case["payload"], entity_id=case["entity_id"], parents=case["parents"])
    else:
        with pytest.raises((ValueError, TypeError)):
            validate_payload(case["payload"], entity_id=case["entity_id"], parents=case["parents"])


def test_read_only_sql_snapshot_keeps_orphan_pin_without_manufacturing_membership(pair):
    from paper_daily.sync_projection import read_manifest

    a, *_ = pair
    toggle(a)
    before = a.journal.path.read_bytes()
    snapshot = read_manifest(a.journal.path, workspace_id="workspace")
    assert snapshot["lists"] == []
    paper = next(p for p in snapshot["papers"] if p["title"] == "Source")
    assert paper["queue_pin"] == {"pinned_at": STAMP}
    assert a.journal.path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("package_sha256", "not-a-hash"),
        ("source_owner", ""),
        ("receiver_owner", "x" * 4097),
        ("incoming_pinned_at", "2026-10-30T00:00:00"),
        ("receiver_pinned_at", None),
        ("extra", True),
    ],
)
def test_import_provenance_is_closed_bounded_metadata_only(field, value):
    from paper_daily.enrollment_history import wrap

    record = {
        "package_sha256": "a" * 64,
        "source_owner": "original-paper",
        "receiver_owner": "receiver-paper",
        "incoming_pinned_at": STAMP,
        "receiver_pinned_at": "2026-10-31T00:00:00+00:00",
    }
    record[field] = value
    with pytest.raises((ValueError, TypeError)):
        wrap("queue_pin_import_v1", record)


def test_simultaneous_repeated_queue_toggle_has_one_current_pin(pair):
    from concurrent.futures import ThreadPoolExecutor

    a, *_ = pair
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: toggle(a), range(4)))
    assert sum(result["changed"] for result in results) == 1
    assert query(a, "SELECT * FROM pins") == [("queue", "a-source", STAMP)]
    assert len(a.journal.pending()) == 1


def test_list_and_queue_pins_have_independent_saved_lifetimes(pins):
    from test_list_pins import LIST

    a, b, service, ta, tb = pins
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        set_pinned(conn, LIST, "a-source", True, pinned_at=STAMP)
        set_pinned(conn, "queue", "a-source", True, pinned_at=STAMP)
        conn.commit()
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id FROM pins ORDER BY scope") == [
        (LIST, "b-source"),
        ("queue", "b-source"),
    ]
    toggle(a, False)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id FROM pins") == [(LIST, "b-source")]


def test_actual_batch_writer_deduplicates_and_missing_second_owner_rolls_back(pair, monkeypatch):
    from paper_daily import store
    from paper_daily.desktop.main import Data

    a, *_ = pair
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    data = Data()
    before = a.journal.pending()
    with pytest.raises(ValueError):
        data.set_pins("queue", ["a-source", "missing-owner"], True)
    assert data.pins("queue") == set() and a.journal.pending() == before
    data.set_pins("queue", [], True)
    assert a.journal.pending() == before
    data.set_pins("queue", ["a-source", "a-source"], True)
    assert data.pins("queue") == {"a-source"} and len(a.journal.pending()) == len(before) + 1
    data.set_pins("queue", ["a-source"], True)
    assert len(a.journal.pending()) == len(before) + 1


def test_closing_uncommitted_pin_clear_restores_saved_pin_and_outbox(pair):
    a, *_ = pair
    toggle(a)
    before = a.journal.pending()
    conn = sqlite3.connect(a.journal.path, factory=CaptureConnection)
    set_pinned(conn, "queue", "a-source", False)
    conn.close()
    assert query(a, "SELECT pinned_at FROM pins") == [(STAMP,)] and a.journal.pending() == before


def test_peer_pin_conflict_retains_both_versions_until_explicit_restore(pair):
    a, b, service, ta, tb = pair
    toggle(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    toggle(a, False)
    payload = {
        "scope": {"kind": "paper", "id": SOURCE},
        "feature": "queue_pin",
        "key": "main",
        "data": {"pinned_at": "2026-11-01T00:00:00+00:00"},
        "source_document_hash": None,
    }
    from paper_daily.sync_content import content_id

    b.save(
        b.new_graph_operation(
            "research_content", content_id(payload["scope"], "queue_pin", "main"), payload
        )
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert b.status()["conflicts"] == 1 and query(b, "SELECT * FROM pins") == []
    conflict = b.history(conflicts_only=True)[-1]
    b.resolve_conflict(conflict["sequence"], restore=True)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert b.status()["conflicts"] == 0
    assert query(a, "SELECT pinned_at FROM pins") == [("2026-11-01T00:00:00+00:00",)]
