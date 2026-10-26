"""Actual-schema rich research transfers preserve independent feature rows and IDs."""

import json
import sqlite3
from copy import deepcopy

import pytest
from test_sync_graph_research import LIST, PAPER, STAMP, metadata, operation, parent

from paper_daily.store import SCHEMA
from paper_daily.sync_content import (
    content_id,
    content_identity,
    content_payload,
    enroll_content_identities,
    snapshot_content,
)
from paper_daily.sync_journal import Journal, canonical_operation
from paper_daily.sync_research import prepare, research_writer

HASH = "a" * 64
ANCHOR = {"p0": 0, "o0": 1, "p1": 0, "o1": 4, "document_hash": HASH}


def insert(conn, table, **row):
    conn.execute(
        f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' for _ in row)})",
        tuple(row.values()),
    )


def database(root, name):
    path = root / f"{name}.db"
    local = name + "-local-paper"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        insert(
            conn,
            "papers",
            id=local,
            venue="",
            year=2026,
            title="Paper",
            title_key="paper",
            source="fixture",
        )
    prepare(path, workspace_id="workspace", device_id="device")
    journal = Journal(path, workspace_id="workspace", device_id="device")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE research_paper_identity SET sync_id=? WHERE local_id=?", (PAPER, local)
        )
    journal.apply(operation("paper", PAPER, metadata()), research_writer)
    journal.apply(operation("list", LIST, {"name": "Research", "note": ""}), research_writer)
    return path, local, journal


def seed(path, local):
    with sqlite3.connect(path) as conn:
        insert(conn, "dives", paper_id=local, body="Deep argument", written_at=STAMP, spec="d1")
        insert(
            conn,
            "close_readings",
            paper_id=local,
            body="Section explanation",
            written_at=STAMP,
            spec="c1",
        )
        insert(
            conn,
            "cites",
            paper_id=local,
            ref_key="[2]",
            title="Earlier work",
            purpose="Foundation",
            contexts_json=json.dumps(["Builds on earlier work."]),
            edited=1,
            written_at=STAMP,
        )
        insert(
            conn,
            "followups",
            paper_id=local,
            work_id="W123",
            title="Later work",
            relation="Extends method",
            fetched_at=STAMP,
            contexts_json=json.dumps(["We extend the method."]),
        )
        insert(
            conn,
            "paper_context",
            paper_id=local,
            summary="Development",
            reading_json=json.dumps(
                [{"title": "Background", "direction": "承先", "why": "Prerequisite"}]
            ),
            written_at=STAMP,
            edited=1,
        )
        insert(
            conn,
            "resources",
            paper_id=local,
            url="https://example.org/code",
            kind="code",
            own=1,
            source="pdf",
            context="Implementation",
            checked_at=STAMP,
        )
        insert(
            conn,
            "pdf_highlights",
            id=5,
            paper_id=local,
            document_hash=HASH,
            anchor=json.dumps(ANCHOR),
            quote="Core result",
            created_at=STAMP,
        )
        insert(
            conn,
            "pdf_ai_highlights",
            paper_id=local,
            document_hash=HASH,
            source_key="claim-1",
            analysis_hash="b" * 64,
            anchor=json.dumps(ANCHOR),
            quote="Method evidence",
            reason="Supports conclusion",
            hidden=1,
        )
        insert(
            conn,
            "chat",
            id=7,
            paper_id=local,
            role="user",
            body="Why does it work?",
            created_at=STAMP,
            page=1,
            anchor=json.dumps(ANCHOR),
        )
        insert(
            conn,
            "list_surveys",
            list_id=LIST,
            body="Research landscape",
            papers=1,
            spec="s1",
            written_at=STAMP,
            edited=1,
        )
        insert(
            conn,
            "notes",
            id=41,
            paper_id=local,
            body="My interpretation",
            created_at=STAMP,
            kind="ask",
            page=1,
            anchor=json.dumps(ANCHOR),
        )
        enroll_content_identities(conn)


def envelope(key, payload, **kwargs):
    scope = payload.get("scope", {"kind": "paper", "id": payload.get("paper_id")})
    return operation(
        key[0], key[1], payload, parents=[parent(scope["kind"], scope["id"])], **kwargs
    )


def snapshot(path, **kwargs):
    with sqlite3.connect(path) as conn:
        return snapshot_content(conn, **kwargs)


def test_all_sql_rich_features_roundtrip_with_portable_scopes_and_colliding_integer_ids(tmp_path):
    source, local, _ = database(tmp_path, "source")
    destination, remote_local, receiver = database(tmp_path, "receiver")
    seed(source, local)
    with sqlite3.connect(destination) as conn:
        insert(
            conn,
            "notes",
            id=41,
            paper_id=remote_local,
            body="Unrelated local note",
            kind="note",
            created_at="2025-01-01T00:00:00+00:00",
        )
        insert(
            conn,
            "chat",
            id=7,
            paper_id=remote_local,
            role="user",
            body="Unrelated question",
            created_at="2025-01-01T00:00:00+00:00",
        )
        enroll_content_identities(conn)
    before = snapshot(source)
    assert len(before) == 11
    assert all(local not in json.dumps(p) for p in before.values())
    for key, payload in before.items():
        value = envelope(key, payload)
        assert receiver.apply(value, research_writer)["applied"]
        assert not receiver.apply(value, research_writer)["applied"]
    after = snapshot(destination)
    assert {key: after[key] for key in before} == before
    with sqlite3.connect(destination) as conn:
        assert (
            conn.execute("SELECT body FROM notes WHERE id=41").fetchone()[0]
            == "Unrelated local note"
        )
        assert (
            conn.execute("SELECT body FROM chat WHERE id=7").fetchone()[0] == "Unrelated question"
        )
        assert conn.execute("SELECT body,kind,page FROM notes WHERE id!=41").fetchone() == (
            "My interpretation",
            "ask",
            1,
        )
        assert conn.execute("SELECT hidden,reason FROM pdf_ai_highlights").fetchone() == (
            1,
            "Supports conclusion",
        )
    prepare(destination, workspace_id="workspace", device_id="device")
    assert snapshot(destination) == after


def test_natural_row_edits_and_deletes_do_not_replace_other_features(tmp_path):
    path, local, journal = database(tmp_path, "fixture")
    seed(path, local)
    values = snapshot(path)
    key = next(key for key, payload in values.items() if payload.get("feature") == "citation")
    original = envelope(key, values[key], op_id="citation-create")
    journal.apply(original, research_writer)
    revised = deepcopy(values[key])
    revised["data"]["why"] = "Corrected by reader"
    journal.apply(
        envelope(key, revised, op_id="citation-edit", predecessor="citation-create"),
        research_writer,
    )
    changed = snapshot(path)
    assert changed[key]["data"]["why"] == "Corrected by reader"
    assert {k: v for k, v in changed.items() if k != key} == {
        k: v for k, v in values.items() if k != key
    }
    deletion = envelope(
        key, revised, op_id="citation-delete", predecessor="citation-edit", action="delete"
    )
    deletion["payload"] = {}
    journal.apply(deletion, research_writer)
    assert key not in snapshot(path)
    assert len(snapshot(path)) == 10


def test_rich_note_marker_allows_anchored_edit_but_plain_legacy_form_still_cannot_replace_it(
    tmp_path,
):
    path, local, journal = database(tmp_path, "fixture")
    seed(path, local)
    values = snapshot(path, tables={"notes"})
    key, payload = next(iter(values.items()))
    original = envelope(key, payload, op_id="rich-create")
    journal.apply(original, research_writer)
    plain = envelope(
        key,
        {"paper_id": PAPER, "body": "Wrong plain overwrite"},
        op_id="plain",
        predecessor="rich-create",
    )
    with pytest.raises(ValueError, match="Anchored"):
        journal.apply(plain, research_writer)
    assert snapshot(path, tables={"notes"}) == values
    revised = dict(payload, body="Revised interpretation")
    journal.apply(
        envelope(key, revised, op_id="rich-edit", predecessor="rich-create"), research_writer
    )
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id,body,page FROM notes").fetchone() == (
            41,
            "Revised interpretation",
            1,
        )
    deletion = envelope(key, revised, op_id="rich-delete", predecessor="rich-edit", action="delete")
    deletion["payload"] = {}
    journal.apply(deletion, research_writer)
    assert snapshot(path, tables={"notes"}) == {}


def test_capture_after_local_deletion_can_retire_content_and_rich_note_markers(tmp_path):
    path, local, journal = database(tmp_path, "fixture")
    seed(path, local)
    values = snapshot(path, tables={"notes", "chat"})
    for index, (key, payload) in enumerate(values.items()):
        journal.apply(envelope(key, payload, op_id=f"create-{index}"), research_writer)
        with sqlite3.connect(path) as conn:
            conn.execute("DELETE FROM notes" if key[0] == "note" else "DELETE FROM chat")
        deletion = envelope(
            key, payload, action="delete", op_id=f"delete-{index}", predecessor=f"create-{index}"
        )
        deletion["payload"] = {}
        journal.apply(deletion, research_writer)
    assert snapshot(path, tables={"notes", "chat"}) == {}


@pytest.mark.parametrize(
    "damage", ["unknown", "scope", "id", "hash", "anchor", "nested", "oversize", "secret_url"]
)
def test_closed_schema_rejects_untrusted_or_ambiguous_content(tmp_path, damage):
    path, local, _ = database(tmp_path, "fixture")
    seed(path, local)
    values = snapshot(path)
    feature = "resource" if damage == "secret_url" else "manual_highlight"
    key, payload = next((k, deepcopy(p)) for k, p in values.items() if p.get("feature") == feature)
    value = envelope(key, payload)
    if damage == "unknown":
        payload["data"]["api_key"] = "forbidden"
    elif damage == "scope":
        payload["scope"]["kind"] = "list"
    elif damage == "id":
        value["entity_id"] = PAPER
    elif damage == "hash":
        payload["source_document_hash"] = "not-a-hash"
    elif damage == "anchor":
        payload["data"]["anchor"]["document_hash"] = "f" * 64
    elif damage == "nested":
        payload["data"]["anchor"]["credentials"] = {"token": "no"}
    elif damage == "oversize":
        payload["data"]["quote"] = "x" * (300 * 1024)
    else:
        payload["key"] = "https://user:secret@example.org/data"
    with pytest.raises(ValueError):
        canonical_operation(value)


def test_row_capture_api_is_readonly_and_matches_filtered_snapshot(tmp_path):
    path, local, _ = database(tmp_path, "fixture")
    seed(path, local)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        before = conn.total_changes
        row = dict(conn.execute("SELECT * FROM chat").fetchone())
        key = content_identity(conn, "chat", row)
        payload = content_payload(conn, "chat", row)
        assert snapshot_content(conn, tables={"chat"}) == {key: payload}
        assert conn.total_changes == before
        assert key[1] == content_id(payload["scope"], payload["feature"], payload["key"])


def test_real_graph_client_roundtrip_keeps_feature_conflicts_independent(tmp_path):
    from test_sync_operations import client, paper

    from paper_daily.sync_operations import ResearchOperations
    from paper_daily.sync_service import ReferenceService

    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    roots = ResearchOperations(a).create_list("Route", [{"paper": paper()}], request_id="route")
    portable = roots["papers"][0]["paper_id"]
    scope = {"kind": "paper", "id": portable}
    dive = dict(
        scope=scope,
        feature="dive",
        key="main",
        source_document_hash=HASH,
        data={"body": "Initial dive", "written_at": STAMP, "spec": "d1"},
    )
    close = dict(
        scope=scope,
        feature="close_reading",
        key="main",
        source_document_hash=HASH,
        data={"body": "Initial close read", "written_at": STAMP, "spec": "c1"},
    )
    dive_id, close_id = (
        content_id(scope, "dive", "main"),
        content_id(scope, "close_reading", "main"),
    )
    for identity, payload in ((dive_id, dive), (close_id, close)):
        a.save(a.new_graph_operation("research_content", identity, payload))
    service = ReferenceService(tmp_path / "service.db")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert snapshot(a.journal.path) == snapshot(b.journal.path)
    a.save(
        a.new_graph_operation(
            "research_content", dive_id, dict(dive, data=dict(dive["data"], body="Device A dive"))
        )
    )
    b.save(
        b.new_graph_operation(
            "research_content",
            close_id,
            dict(close, data=dict(close["data"], body="Device B close read")),
        )
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    shared = snapshot(a.journal.path)
    assert shared == snapshot(b.journal.path)
    assert shared[("research_content", dive_id)]["data"]["body"] == "Device A dive"
    assert shared[("research_content", close_id)]["data"]["body"] == "Device B close read"
    assert shared[("research_content", dive_id)]["source_document_hash"] == HASH


@pytest.mark.parametrize("table", ["notes", "chat", "list_surveys"])
def test_stale_retirement_does_not_erase_restored_content(tmp_path, table):
    path, local, journal = database(tmp_path, "fixture")
    seed(path, local)
    key, payload = next(iter(snapshot(path, tables={table}).items()))
    journal.apply(envelope(key, payload, op_id="first"), research_writer)
    restored = envelope(key, payload, op_id="restored", predecessor="first")
    restored["incarnation"] = "restored"
    journal.apply(restored, research_writer)
    deletion = envelope(
        key, payload, op_id="old-retirement", predecessor="restored", action="delete"
    )
    deletion["payload"] = {}
    journal.apply(deletion, research_writer)
    assert snapshot(path, tables={table}) == {key: payload}


def test_missing_parent_rolls_back_and_list_removal_can_retire_only_its_survey(tmp_path):
    path, local, journal = database(tmp_path, "fixture")
    seed(path, local)
    key, payload = next(iter(snapshot(path, tables={"list_surveys"}).items()))
    broken = deepcopy(payload)
    broken["scope"]["id"] = "unknown-list"
    identity = content_id(broken["scope"], broken["feature"], broken["key"])
    before = snapshot(path)
    with pytest.raises(ValueError, match="parent"):
        journal.apply(envelope(("research_content", identity), broken), research_writer)
    assert snapshot(path) == before
    journal.apply(envelope(key, payload, op_id="survey-create"), research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM lists WHERE id=?", (LIST,))
    deletion = envelope(
        key, payload, op_id="survey-retire", predecessor="survey-create", action="delete"
    )
    deletion["payload"] = {}
    journal.apply(deletion, research_writer)
    assert snapshot(path, tables={"list_surveys"}) == {}
    assert len(snapshot(path)) == len(before) - 1
