"""One staged source can join a caller-owned compound import transaction safely."""

from uuid import uuid4

import pytest
from test_sync_files import PAPER, paper_payload
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture
from test_sync_source_files import source as source_fixture

from paper_daily.sync_source_files import PreparedSource, prepare_source, publish_source_in

codec = codec_fixture
pair = pair_fixture
source = source_fixture


def prepared(pair, source, *, paper_id=PAPER, parent=None, request="compound-source"):
    _server, a, _b, fa, _fb, _ta, _tb = pair
    if parent is None:
        with a.journal.transaction() as conn:
            parent = a._optimistic_graph(conn)[0][("paper", PAPER)]["incarnation"]
    return prepare_source(
        a,
        paper_id,
        source[0],
        document_hash=source[2],
        parent_incarnation=parent,
        store=fa.store,
        version_root=fa.root,
        request_id=request,
    )


def test_caller_rollback_has_no_partial_source_then_identical_retry_is_one_operation(pair, source):
    value = prepared(pair, source)
    a = pair[1]
    before = a.journal.pending()
    with pytest.raises(RuntimeError, match="later write"), a.journal.transaction() as conn:
        publish_source_in(conn, a, value)
        raise RuntimeError("later write failed")
    assert a.journal.pending() == before
    with a.journal.transaction() as conn:
        first = publish_source_in(conn, a, value)
    with a.journal.transaction() as conn:
        assert publish_source_in(conn, a, value) == first
    assert len(a.journal.pending()) == len(before) + 1


def test_planned_new_paper_must_exist_in_same_transaction_before_source_publication(pair, source):
    a = pair[1]
    identity = str(uuid4())
    value = prepared(pair, source, paper_id=identity, parent="new-paper-operation")
    with pytest.raises(ValueError, match="active paper"), a.journal.transaction() as conn:
        publish_source_in(conn, a, value)
    with a.journal.transaction() as conn:
        paper = a.new_graph_operation_in(
            conn, "paper", identity, paper_payload(), operation_id="new-paper-operation"
        )
        a.journal.apply_in(conn, paper, a.writer)
        operation = publish_source_in(conn, a, value)
        assert operation["parents"] == [
            {"kind": "paper", "id": identity, "incarnation": "new-paper-operation"}
        ]


def test_switched_database_and_missing_staging_cannot_grant_file_ownership(pair, source):
    value = prepared(pair, source)
    a, b = pair[1:3]
    before = a.journal.pending()
    with b.journal.transaction() as conn, pytest.raises(ValueError, match="binding"):
        publish_source_in(conn, b, value)
    for invalid in ({"payload": value.payload}, object.__new__(PreparedSource)):
        with a.journal.transaction() as conn, pytest.raises(ValueError):
            publish_source_in(conn, a, invalid)
    assert a.journal.pending() == before


def test_bytes_changed_after_prepare_are_rejected_without_partial_operation(pair, source):
    value = prepared(pair, source)
    a = pair[1]
    asset = value.proof.files[source[2]][0]
    asset.write_bytes(b"x" * asset.stat().st_size)
    before = a.journal.pending()
    with a.journal.transaction() as conn, pytest.raises(ValueError, match="bytes changed"):
        publish_source_in(conn, a, value)
    assert a.journal.pending() == before
