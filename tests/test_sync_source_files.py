"""Original A transfers independently of current B without changing reader binding."""

import copy
import hashlib

import pymupdf
import pytest
from test_sync_files import PAPER, drain
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily.sync_files import (
    canonical_json,
    descriptor,
    validate_closure,
    validate_payload,
)
from paper_daily.sync_source_files import FEATURE, encode, publish, resolved

codec = codec_fixture
pair = pair_fixture


def pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), text)
        return doc.tobytes()


@pytest.fixture
def source(tmp_path):
    data = pdf("Original source A: a bounded research comparison")
    target = tmp_path / "original.pdf"
    target.write_bytes(data)
    return target, data, hashlib.sha256(data).hexdigest()


def save(pair, source, request="source-a"):
    _server, a, _b, fa, _fb, _ta, _tb = pair
    with a.journal.transaction() as conn:
        parent = a._optimistic_graph(conn)[0][("paper", PAPER)]["incarnation"]
    return publish(
        a,
        PAPER,
        source[0],
        document_hash=source[2],
        parent_incarnation=parent,
        store=fa.store,
        version_root=fa.root,
        request_id=request,
    )


def test_two_devices_transfer_original_without_current_document_rebinding(pair, source):
    server, a, b, fa, fb, ta, tb = pair
    operation = save(pair, source)
    assert operation["payload"]["feature"] == FEATURE
    before = len(a.journal.pending())
    assert save(pair, source, "second-click") == operation
    assert len(a.journal.pending()) == before
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    b.sync_once(server, tb)
    with b.journal.transaction() as conn:
        assert resolved(conn, PAPER, source[2]) is None
    drain(lambda: fb.download(operation["entity_id"]), "bound")
    with b.journal.transaction() as conn:
        located = resolved(conn, PAPER, source[2])
        assert located.read_bytes() == source[1]
        assert not conn.execute("SELECT 1 FROM research_document_desired").fetchall()
        assert resolved(conn, PAPER, "0" * 64) is None
    forbidden = ("owner_json", "database_identity", "db_path", "device", "token", "credentials")
    wire = canonical_json(operation["payload"]).decode()
    assert not any(key in wire for key in forbidden)


@pytest.mark.parametrize(
    "change",
    ["version", "feature", "hash", "owner", "asset", "role", "extra", "bool_size", "large"],
)
def test_closed_source_format_rejects_unknown_or_inconsistent_values(source, change):
    payload, blobs = encode(PAPER, source[1])
    bad = copy.deepcopy(payload)
    if change == "version":
        bad["format_version"] = 2
    elif change == "feature":
        bad["feature"] = "source_v2"
    elif change == "hash":
        bad["source_document_hash"] = "a" * 64
    elif change == "owner":
        body = canonical_json(
            {
                "version": 1,
                "paper_id": "22222222-2222-4222-8222-222222222222",
                "document_hash": source[2],
            }
        )
        bad["body"] = descriptor(body, "application/json")
        blobs[bad["body"]["sha256"]] = body
    elif change == "asset":
        bad["assets"].append(copy.deepcopy(bad["assets"][0]))
    elif change == "role":
        bad["assets"][0]["role"] = "figure"
    elif change == "extra":
        bad["path"] = "C:/private/original.pdf"
    elif change == "bool_size":
        bad["assets"][0]["size"] = True
    else:
        bad["assets"][0]["size"] = 150 * 1024**2 + 1
    with pytest.raises(ValueError):
        validate_payload(bad)
        validate_closure(bad, lambda row: blobs[row["sha256"]])


def test_source_budget_is_distinct_from_deck_asset_budget(source):
    payload, _ = encode(PAPER, source[1])
    payload["assets"][0]["size"] = 100 * 1024**2
    validate_payload(payload)
    from paper_daily.sync_files import MAX_ASSETS

    assert MAX_ASSETS == 64 * 1024**2


def test_wrong_selected_bytes_and_parent_fail_before_metadata_publication(pair, source):
    _server, a, _b, fa, _fb, _ta, _tb = pair
    baseline = a.journal.pending()
    with pytest.raises(ValueError, match="incarnation"):
        publish(
            a,
            PAPER,
            source[0],
            document_hash=source[2],
            parent_incarnation="wrong",
            store=fa.store,
            version_root=fa.root,
            request_id="wrong-parent",
        )
    source[0].write_bytes(pdf("Replacement B"))
    with a.journal.transaction() as conn:
        parent = a._optimistic_graph(conn)[0][("paper", PAPER)]["incarnation"]
    with pytest.raises(ValueError, match="digest"):
        publish(
            a,
            PAPER,
            source[0],
            document_hash=source[2],
            parent_incarnation=parent,
            store=fa.store,
            version_root=fa.root,
            request_id="wrong-source",
        )
    assert a.journal.pending() == baseline
