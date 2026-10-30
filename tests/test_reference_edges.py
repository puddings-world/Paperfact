"""Portable reference pairs share capture, graph lifetimes and verified recovery."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from paper_daily import store, sync_recovery
from paper_daily.sync_capture import (
    CaptureConnection,
    StaleCaptureError,
    capture_existing,
    expecting,
    install,
    observe_target,
)
from paper_daily.sync_client import SyncClient
from paper_daily.sync_content import content_id
from paper_daily.sync_graph import check_preconditions
from paper_daily.sync_journal import Journal, canonical_operation
from paper_daily.sync_research import prepare, research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService

SOURCE = str(uuid5(NAMESPACE_URL, "reference-source"))
TARGET = str(uuid5(NAMESPACE_URL, "reference-target"))
OTHER = str(uuid5(NAMESPACE_URL, "unrelated-paper"))


def metadata(title):
    return {
        "title": title,
        "authors": [],
        "year": 2026,
        "venue": "Fixture",
        "source": "fixture",
        **dict.fromkeys(("abstract", "doi", "arxiv_id", "s2_id", "page_url", "pdf_url")),
    }


def client(path, device):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        for _identity, label in ((SOURCE, "source"), (TARGET, "target"), (OTHER, "other")):
            local = device + "-" + label
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) VALUES(?,?,?,?,?,?)",
                (local, label, label, "Fixture", 2026, "fixture"),
            )
    prepare(path, workspace_id="workspace", device_id=device)
    with closing(sqlite3.connect(path)) as conn, conn:
        for identity, label in ((SOURCE, "source"), (TARGET, "target"), (OTHER, "other")):
            conn.execute(
                "UPDATE research_paper_identity SET sync_id=? WHERE local_id=?",
                (identity, device + "-" + label),
            )
    return SyncClient(
        Journal(path, workspace_id="workspace", device_id=device),
        research_writer,
        order_writer=research_order_writer,
    )


def query(side, sql, args=()):
    with closing(sqlite3.connect(side.journal.path)) as conn:
        return conn.execute(sql, args).fetchall()


def enable(side):
    with closing(sqlite3.connect(side.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id=side.journal.device_id)
        conn.commit()


def write(side, sql, args=()):
    with closing(sqlite3.connect(side.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(sql, args)
        conn.commit()


def payload(source=SOURCE, target=TARGET, value=1):
    return {
        "scope": {"kind": "paper", "id": source},
        "feature": "reference_edge",
        "key": target,
        "data": {"influential": value},
        "source_document_hash": None,
    }


def edge(side, *, source=SOURCE, target=TARGET, value=1, **kwargs):
    data = payload(source, target, value)
    operation = side.new_graph_operation(
        "research_content", content_id(data["scope"], "reference_edge", target), data, **kwargs
    )
    side.save(operation)
    return operation


@pytest.fixture
def pair(tmp_path):
    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    service = ReferenceService(tmp_path / "authority.db")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    for identity, name in ((SOURCE, "Source"), (TARGET, "Target"), (OTHER, "Other")):
        a.save(a.new_graph_operation("paper", identity, metadata(name)))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    enable(a)
    enable(b)
    return a, b, service, ta, tb


def test_existing_sql_writer_maps_both_endpoints_and_repeats_do_not_duplicate(pair):
    a, b, service, ta, tb = pair
    write(a, "INSERT INTO refs VALUES('a-source','a-target',1)")
    pending = a.journal.pending()
    assert len(pending) == 1
    op = pending[0]
    assert op["payload"] == payload()
    assert [(p["kind"], p["id"]) for p in op["parents"]] == [("paper", SOURCE), ("paper", TARGET)]
    write(a, "INSERT OR REPLACE INTO refs VALUES('a-source','a-target',1)")
    assert a.journal.pending() == pending
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM refs") == [("b-source", "b-target", 1)]
    assert not b.journal.pending()
    b.receive(service.pull(tb, after=b.status()["cursor"]))
    assert query(b, "SELECT * FROM refs") == [("b-source", "b-target", 1)]


def test_sql_update_and_delete_are_captured_without_an_editor_token(pair):
    a, b, service, ta, tb = pair
    write(a, "INSERT INTO refs VALUES('a-source','a-target',1)")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    write(a, "UPDATE refs SET influential=0")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT influential FROM refs") == [(0,)]
    write(a, "DELETE FROM refs")
    deletion = a.journal.pending()[0]
    assert len(deletion["parents"]) == 2 and deletion["action"] == "delete"
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(a, "SELECT * FROM refs") == query(b, "SELECT * FROM refs") == []
    assert len(a.history()) >= 6


def test_self_edge_preserves_existing_row_and_has_one_dependency(pair):
    a, b, service, ta, tb = pair
    write(a, "INSERT INTO refs VALUES('a-source','a-source',0)")
    operation = a.journal.pending()[0]
    assert len(operation["parents"]) == 1 and operation["payload"]["key"] == SOURCE
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM refs") == [("b-source", "b-source", 0)]
    write(a, "DELETE FROM refs")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM refs") == []


def test_conflicting_edge_edits_retain_both_versions(pair):
    a, b, service, ta, tb = pair
    edge(a, value=0)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    edge(a, value=1)
    removed = b.new_graph_operation(
        "research_content",
        content_id(payload()["scope"], "reference_edge", TARGET),
        {},
        action="delete",
    )
    b.save(removed)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert b.status()["conflicts"] == 1
    assert query(b, "SELECT influential FROM refs") == [(1,)]
    assert any(
        event["operation"]["operation_id"] == removed["operation_id"]
        for event in b.history(conflicts_only=True)
    )


def test_deleted_edge_requires_explicit_restore_and_new_incarnation(pair):
    a, b, service, ta, tb = pair
    first = edge(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    deleted = a.new_graph_operation("research_content", first["entity_id"], {}, action="delete")
    a.save(deleted)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    with pytest.raises(ValueError, match="restore=True"):
        edge(a)
    restored = edge(a, restore=True)
    assert restored["incarnation"] != first["incarnation"]
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM refs") == [("b-source", "b-target", 1)]
    # A stale delete cannot remove this restored edge.
    with a.journal.transaction() as conn:
        research_writer(conn, deleted)
    assert query(a, "SELECT * FROM refs") == [("a-source", "a-target", 1)]


def test_failed_transaction_rolls_back_research_and_outbox(pair):
    a, *_ = pair
    before = a.journal.pending()
    with pytest.raises(sqlite3.Error):
        write(a, "INSERT INTO refs VALUES('a-source','not-enrolled',1)")
    assert query(a, "SELECT * FROM refs") == []
    assert a.journal.pending() == before
    with pytest.raises(sqlite3.Error):
        write(a, "INSERT INTO refs VALUES('a-source','a-target',2)")
    assert query(a, "SELECT * FROM refs") == []
    assert a.journal.pending() == before


def test_explicit_stale_editor_observation_preserves_candidate(pair):
    a, *_ = pair
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        token = observe_target(conn, "paper", "a-source", "reference_edge", TARGET)
    edge(a, value=0)
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with expecting(conn, [token]):
            conn.execute("UPDATE refs SET influential=1")
            with pytest.raises(StaleCaptureError):
                conn.commit()
    assert query(a, "SELECT influential FROM refs") == [(0,)]
    assert len(query(a, "SELECT * FROM research_capture_candidates")) == 1


@pytest.mark.parametrize("endpoint", [SOURCE, TARGET])
def test_absent_edge_observations_cover_both_endpoint_incarnations(pair, endpoint):
    a, *_ = pair
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        token = observe_target(conn, "paper", "a-source", "reference_edge", TARGET)
    assert [p["id"] for p in token["parents"]] == [SOURCE, TARGET]
    with a.journal.transaction() as conn:
        state = a._graph_entity(conn, "paper", endpoint)
        state["incarnation"] = "replacement-endpoint"
        conn.execute(
            "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='paper' AND entity_id=?",
            (json.dumps(state), endpoint),
        )
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with expecting(conn, [token]):
            conn.execute("INSERT INTO refs VALUES('a-source','a-target',1)")
            with pytest.raises(StaleCaptureError):
                conn.commit()
    assert query(a, "SELECT * FROM refs") == []


@pytest.mark.parametrize("endpoint", [SOURCE, TARGET])
def test_replaced_or_inactive_paper_hides_edge_without_erasing_history(pair, endpoint):
    a, b, service, ta, tb = pair
    edge(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    before = b.history()
    with b.journal.transaction() as conn:
        state = b._graph_entity(conn, "paper", endpoint)
        state["incarnation"] = "replacement-endpoint"
        conn.execute(
            "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='paper' AND entity_id=?",
            (json.dumps(state), endpoint),
        )
    b.receive([])
    assert query(b, "SELECT * FROM refs") == []
    assert b.history() == before
    assert "parent_incarnation" in {row["reason"] for row in b.deferred_reasons()}
    with pytest.raises(ValueError, match="restore=True"):
        edge(b)


def test_builder_rejects_missing_target_and_projection_checks_exact_target(pair):
    a, *_ = pair
    absent = str(uuid4())
    with pytest.raises(ValueError, match="Parent is missing"):
        edge(a, target=absent)
    operation = a.new_graph_operation(
        "research_content", content_id(payload()["scope"], "reference_edge", TARGET), payload()
    )
    wrong = deepcopy(operation)
    wrong["parents"][1]["incarnation"] = "replaced"
    with a.journal.transaction() as conn, pytest.raises(ValueError, match="exact materialized"):
        research_writer(conn, wrong)
    assert query(a, "SELECT * FROM refs") == []


@pytest.mark.parametrize(
    "mutation", ["reversed", "duplicate", "one-parent", "nonedge-two", "wrong-id"]
)
def test_closed_schema_rejects_ambiguous_parent_roles(pair, mutation):
    a, *_ = pair
    operation = a.new_graph_operation(
        "research_content", content_id(payload()["scope"], "reference_edge", TARGET), payload()
    )
    if mutation == "reversed":
        operation["parents"].reverse()
    elif mutation == "duplicate":
        operation["parents"][1] = deepcopy(operation["parents"][0])
    elif mutation == "one-parent":
        operation["parents"].pop()
    elif mutation == "nonedge-two":
        operation["payload"] = {
            "scope": payload()["scope"],
            "feature": "dive",
            "key": "main",
            "data": {"body": "x", "written_at": "2026-01-01T00:00:00+00:00", "spec": None},
            "source_document_hash": None,
        }
    else:
        operation["entity_id"] = str(uuid4())
    with pytest.raises(ValueError):
        canonical_operation(operation)


def test_reversed_delete_is_rejected_before_authority_or_projection(pair):
    a, *_ = pair
    first = edge(a)
    deleted = a.new_graph_operation("research_content", first["entity_id"], {}, action="delete")
    deleted["parents"].reverse()
    with pytest.raises(ValueError, match="reversed"):
        canonical_operation(deleted)


def test_baseline_captures_existing_refs_with_root_order_and_recovery(tmp_path):
    path = tmp_path / "source.db"
    side = client(path, "a")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO refs VALUES('a-source','a-target',1)")
        conn.execute("INSERT INTO refs VALUES('a-target','a-source',0)")
        conn.execute("INSERT INTO refs VALUES('a-other','a-other',0)")
    enable(side)
    with closing(sqlite3.connect(path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        capture_existing(conn)
        conn.commit()
    pending = side.journal.pending()
    first_edge = next(
        index for index, op in enumerate(pending) if op["entity_type"] == "research_content"
    )
    assert all(op["entity_type"] == "paper" for op in pending[:first_edge])
    assert query(side, "SELECT * FROM refs ORDER BY paper_id,ref_paper_id") == [
        ("a-other", "a-other", 0),
        ("a-source", "a-target", 1),
        ("a-target", "a-source", 0),
    ]
    server = ReferenceService(tmp_path / "authority.db")
    token = server.enroll("workspace", "a")
    side.sync_once(server, token)
    other = client(tmp_path / "remote.db", "b")
    other.receive(server.pull(server.enroll("workspace", "b")))
    assert query(other, "SELECT * FROM refs ORDER BY paper_id,ref_paper_id") == [
        ("b-other", "b-other", 0),
        ("b-source", "b-target", 1),
        ("b-target", "b-source", 0),
    ]
    archive = tmp_path / "backup.zip"
    sync_recovery.create(path, archive)
    restored = tmp_path / "restored"
    sync_recovery.restore_detached(archive, restored)
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM refs").fetchone() == (3,)
    assert len(side.history()) == len(pending)


def test_target_pending_projection_defers_edge_then_materializes(pair):
    a, b, service, ta, tb = pair
    b.save(b.new_graph_operation("paper", TARGET, metadata("Local target metadata")))
    edge(a)
    a.sync_once(service, ta)
    b.receive(service.pull(tb, after=b.status()["cursor"]))
    assert query(b, "SELECT * FROM refs") == []
    assert "parent_pending" in {row["reason"] for row in b.deferred_reasons()}
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert query(b, "SELECT * FROM refs") == [("b-source", "b-target", 1)]


def test_reference_preconditions_need_both_lifecycles(pair):
    a, *_ = pair
    operation = a.new_graph_operation(
        "research_content", content_id(payload()["scope"], "reference_edge", TARGET), payload()
    )
    with a.journal.transaction() as conn:
        states = {
            ("paper", identity): a._graph_entity(conn, "paper", identity)
            for identity in (SOURCE, TARGET)
        }
    assert check_preconditions(
        lambda kind, identity: states.get((kind, identity)), lambda _id: None, operation
    )
    states[("paper", TARGET)]["active"] = False
    assert not check_preconditions(
        lambda kind, identity: states.get((kind, identity)), lambda _id: None, operation
    )
    states.pop(("paper", TARGET))
    with pytest.raises(ValueError, match="Missing graph parent"):
        check_preconditions(
            lambda kind, identity: states.get((kind, identity)), lambda _id: None, operation
        )


def test_reference_retry_and_invalid_batched_receive_are_atomic(pair, tmp_path):
    a, _b, service, ta, tb = pair
    operation = edge(a)
    accepted = service.push(ta, operation)
    assert service.push(ta, operation) == accepted
    changed = deepcopy(operation)
    changed["payload"]["data"]["influential"] = 0
    with pytest.raises(ValueError):
        service.push(ta, changed)
    fresh = client(tmp_path / "fresh.db", "fresh")
    events = service.pull(tb)
    invalid = deepcopy(events)
    invalid[-1]["operation"]["parents"][1]["incarnation"] = "unavailable-target"
    invalid[-1]["head"]["operation"] = deepcopy(invalid[-1]["operation"])
    with pytest.raises(ValueError):
        fresh.receive(invalid)
    assert fresh.status()["cursor"] == 0
    assert not query(fresh, "SELECT * FROM refs")
    fresh.receive(events)
    assert query(fresh, "SELECT * FROM refs") == [("fresh-source", "fresh-target", 1)]


def test_latest_root_revision_materializes_before_earlier_edge(pair, tmp_path):
    a, _b, service, ta, tb = pair
    edge(a)
    a.save(a.new_graph_operation("paper", TARGET, metadata("Renamed target after edge")))
    a.sync_once(service, ta)
    fresh = client(tmp_path / "fresh.db", "fresh")
    fresh.receive(service.pull(tb))
    assert query(fresh, "SELECT title FROM papers WHERE id='fresh-target'") == [
        ("Renamed target after edge",)
    ]
    assert query(fresh, "SELECT * FROM refs") == [("fresh-source", "fresh-target", 1)]


@pytest.mark.parametrize("endpoint", ["a-source", "a-target"])
def test_existing_unsupported_paper_deletion_rolls_back_edge_and_paper(pair, endpoint):
    a, *_ = pair
    edge(a)
    pending = a.journal.pending()
    with pytest.raises(ValueError, match="Paper deletion"):
        write(a, "DELETE FROM papers WHERE id=?", (endpoint,))
    assert query(a, "SELECT * FROM refs") == [("a-source", "a-target", 1)]
    assert query(a, "SELECT id FROM papers WHERE id=?", (endpoint,)) == [(endpoint,)]
    assert a.journal.pending() == pending


def test_bundle_preserves_local_reference_pair_without_reusing_device_identity(
    pair, tmp_path, monkeypatch
):
    from paper_daily import bundle

    a, *_ = pair
    edge(a)
    write(
        a,
        "INSERT INTO lists(id,name,note,created_at) VALUES('route','Research','',?)",
        ("2026-10-30T00:00:00+00:00",),
    )
    write(
        a,
        "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
        "VALUES('route','a-source',0,?)",
        ("2026-10-30T00:00:00+00:00",),
    )
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(bundle, "DATA_DIR", a.journal.path.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", a.journal.path.parent / "pdf")
    made = bundle.export("route", tmp_path / "research.zip", with_pdfs=False)
    destination = tmp_path / "shared"
    destination.mkdir()
    monkeypatch.setattr(store, "DB_PATH", destination / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", destination)
    monkeypatch.setattr(bundle, "PDF_DIR", destination / "pdf")
    store.init_db()
    report = bundle.import_(made["out"])
    assert report["refs"] == 1 and report["cited_papers"] == 1
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert conn.execute("SELECT * FROM refs").fetchall() == [("a-source", "a-target", 1)]
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchall()


def test_collection_replace_preserves_unrelated_pairs_and_unchanged_intents(pair):
    a, b, service, ta, tb = pair
    edge(a, target=TARGET)
    edge(a, target=OTHER, value=0)
    edge(a, source=TARGET, target=SOURCE)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM refs WHERE paper_id='a-source'")
        conn.execute("INSERT INTO refs VALUES('a-source','a-target',1)")
        conn.execute("INSERT INTO refs VALUES('a-source','a-source',0)")
        conn.commit()
    assert len(a.journal.pending()) == 2
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT * FROM refs ORDER BY paper_id,ref_paper_id") == [
        ("b-source", "b-source", 0),
        ("b-source", "b-target", 1),
        ("b-target", "b-source", 1),
    ]


def test_sql_primary_key_reparent_is_rolled_back(pair):
    a, *_ = pair
    edge(a)
    pending = a.journal.pending()
    with pytest.raises(sqlite3.Error):
        write(a, "UPDATE refs SET ref_paper_id='a-other'")
    assert query(a, "SELECT * FROM refs") == [("a-source", "a-target", 1)]
    assert a.journal.pending() == pending


def test_actual_python_authority_events_validate_and_project_in_mobile(pair):
    import subprocess
    from pathlib import Path

    a, _b, service, ta, tb = pair
    edge(a)
    a.sync_once(service, ta)
    javascript = """
import {readFileSync} from 'node:fs';
import {receive,projection} from './mobile/domain.mjs';
import {emptyState} from './mobile/store.mjs';
const state=emptyState('workspace','phone');
receive(state,JSON.parse(readFileSync(0,'utf8')));
console.log(JSON.stringify(projection(state).papers.flatMap(p=>(p.references??[]).map(r=>[p.id,r.paper_id,r.influential]))));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", javascript],
        cwd=Path(__file__).parents[1],
        input=json.dumps(service.pull(tb)),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=True,
    )
    assert json.loads(result.stdout) == [[SOURCE, TARGET, 1]]
