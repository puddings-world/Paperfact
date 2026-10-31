"""Existing companion writer gets an explicit fresh context; raw SQL cannot."""

import copy

import pytest
from test_sync_capture import bound as bound_fixture
from test_sync_capture import make, seed

from paper_daily import queue, store
from paper_daily.legacy_briefs import record_pack
from paper_daily.sync_service import ReferenceService

bound = bound_fixture
STAMP = "2026-10-30T12:34:56+08:00"


def setup():
    seed()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="child",
                    title="Child",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                    score=10,
                )
            ],
        )
        conn.execute("INSERT INTO refs VALUES('local-paper','child',1)")
        conn.execute(
            "INSERT INTO queue(paper_id,rank,role,queued_at) VALUES('local-paper',1,'manual',?)",
            (STAMP,),
        )
        conn.execute(
            "INSERT INTO queue(paper_id,rank,role,queued_at) VALUES('child',9,'main',?)", (STAMP,)
        )
        record_pack(
            conn, "local-paper", STAMP, "manual", b"# Existing brief", legacy_day="2026-10-30"
        )


def queue_ops(client):
    return [
        op
        for op in client.journal.pending()
        if op.get("payload", {}).get("feature") == "queue_entry"
    ]


def test_actual_add_companions_changes_context_with_fresh_incarnation_and_repeat_is_noop(
    bound, tmp_path
):
    setup()
    old = next(op for op in queue_ops(bound) if op["payload"]["data"]["rank"] == 9)
    with store.connect() as conn:
        assert queue.add_companions(conn, "local-paper") == ["child"]
    latest = queue_ops(bound)[-1]
    assert latest["entity_id"] == old["entity_id"]
    assert latest["incarnation"] == latest["operation_id"] != old["incarnation"]
    assert latest["parents"][0] == old["parents"][0] and len(latest["parents"]) == 2
    count = len(bound.journal.pending())
    with store.connect() as conn:
        assert queue.add_companions(conn, "local-paper") == ["child"]
    assert len(bound.journal.pending()) == count
    authority = ReferenceService(tmp_path / "service.db")
    ta, tb = authority.enroll("workspace", "a"), authority.enroll("workspace", "b")
    peer = make(tmp_path / "peer.db", "b")
    # This fixture's pre-existing brief is not sent; metadata/queue graph only.
    for op in bound.journal.pending():
        if op["entity_type"] == "research_file":
            continue
        event = authority.push(ta, op)
        assert event["outcome"] == "accepted"
        bound.journal.acknowledge(op["operation_id"], event["sequence"])
    peer.sync_once(authority, tb)
    with peer.journal.transaction() as conn:
        actual = conn.execute(
            "SELECT rank,role,parent_id,queued_at FROM queue WHERE role='companion'"
        ).fetchone()
        assert actual[0:2] == (1.1, "companion") and actual[3] == STAMP
        assert actual[2] is not None
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 1
    with store.connect() as conn:
        assert conn.execute("SELECT brief_path FROM reading_log").fetchone()[0] is not None


def test_raw_sql_cannot_grant_context_replacement(bound):
    setup()
    count = len(bound.journal.pending())
    with pytest.raises(ValueError, match="restore"), store.connect() as conn:
        conn.execute("UPDATE queue SET parent_id='local-paper' WHERE paper_id='child'")
    assert len(bound.journal.pending()) == count
    with store.connect() as conn:
        assert tuple(
            conn.execute("SELECT rank,role,parent_id FROM queue WHERE paper_id='child'").fetchone()
        ) == (9, "main", None)


def prepared_transition(bound, tmp_path):
    setup()
    authority = ReferenceService(tmp_path / "service.db")
    token = authority.enroll("workspace", "a")
    for operation in bound.journal.pending():
        if operation["entity_type"] != "research_file":
            event = authority.push(token, operation)
            assert event["outcome"] == "accepted"
            bound.journal.acknowledge(operation["operation_id"], event["sequence"])
    with store.connect() as conn:
        queue.add_companions(conn, "local-paper")
    candidate = queue_ops(bound)[-1]
    return authority, token, candidate


@pytest.mark.parametrize(
    "change", ["same-incarnation", "wrong-identity", "reversed-closure", "wrong-owner"]
)
def test_context_shape_never_grants_unrelated_authority(bound, tmp_path, change):
    from uuid import uuid4

    authority, token, value = prepared_transition(bound, tmp_path)
    value = copy.deepcopy(value)
    if change == "same-incarnation":
        value["incarnation"] = value["depends_on"]
    elif change == "wrong-identity":
        value["entity_id"] = str(uuid4())
    elif change == "reversed-closure":
        value["parents"].reverse()
    else:
        value["payload"]["scope"]["id"] = value["parents"][1]["id"]
    with pytest.raises(ValueError):
        authority.push(token, value)


@pytest.mark.parametrize(
    "change", ["head", "structure", "unrelated-structure", "deleted-new-parent"]
)
def test_context_stale_preconditions_are_not_accepted_and_brief_is_unchanged(
    bound, tmp_path, change
):
    authority, token, value = prepared_transition(bound, tmp_path)
    value = copy.deepcopy(value)
    with store.connect() as conn:
        path = conn.execute("SELECT brief_path FROM reading_log").fetchone()[0]
    from pathlib import Path

    data = Path(path).read_bytes()
    if change == "head":
        value["depends_on"] = None
        value["base_revision"] = 0
    elif change == "structure":
        value.pop("structure_depends_on", None)
        value["structure_revision"] = 0
    elif change == "unrelated-structure":
        value["structure_depends_on"] = value["parents"][1]["incarnation"]
        with pytest.raises(ValueError, match="Unrelated"):
            authority.push(token, value)
        assert Path(path).read_bytes() == data
        return
    else:
        # Paper delete remains unsupported on the public wire. Test the pure
        # archived/retired parent guard without widening that contract.
        import json
        import sqlite3
        from contextlib import closing

        from paper_daily.sync_graph import check_preconditions

        with closing(sqlite3.connect(authority.path)) as conn:
            state = {
                (kind, identity): json.loads(metadata)
                for kind, identity, metadata in conn.execute(
                    "SELECT entity_type,entity_id,metadata FROM sync_graph"
                )
            }
        state[("paper", value["parents"][1]["id"])]["active"] = False
        receipts = {item["operation"]["operation_id"]: item for item in authority.pull(token)}
        assert (
            check_preconditions(
                lambda kind, identity: state.get((kind, identity)), receipts.get, value
            )
            is False
        )
        assert Path(path).read_bytes() == data
        return
    event = authority.push(token, value)
    assert event["outcome"] == "conflict"
    assert authority.push(token, value) == event
    assert Path(path).read_bytes() == data


def test_concurrent_peer_scalar_edit_wins_and_context_candidate_is_retained(bound, tmp_path):
    authority, token, candidate = prepared_transition(bound, tmp_path)
    tb = authority.enroll("workspace", "b")
    peer = make(tmp_path / "b.db", "b")
    peer.sync_once(authority, tb)
    payload = copy.deepcopy(candidate["payload"])
    payload["data"].update(rank=123.5, role="manual", parent_id=None)
    operation = peer.new_graph_operation("research_content", candidate["entity_id"], payload)
    event = authority.push(tb, operation)
    assert event["outcome"] == "accepted"
    conflict = authority.push(token, candidate)
    assert conflict["outcome"] == "conflict"
    assert conflict["head"]["operation"]["payload"]["data"]["rank"] == 123.5
    assert authority.push(token, candidate) == conflict
    assert conflict["operation"]["payload"]["data"]["parent_id"] is not None
