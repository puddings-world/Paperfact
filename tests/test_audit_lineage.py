"""Saved Lineage audit keeps multi-paper quotations on their actual originals."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_lifecycle import active as active
from test_research_lineage import corpus as corpus

from paper_daily import audit_inputs, config, lineage_sets, local_operations, research_audit, store
from paper_daily.document_reader import from_workspace


def capture(corpus):
    document = from_workspace(corpus[0], legacy_root=corpus[1]).resolve("focal")
    return audit_inputs.AuditCapture.capture(corpus[0], "focal", document=document)


def test_saved_lineage_audit_keeps_cross_paper_hashes_and_locates_only_loaded_original(
    active, corpus, monkeypatch
):
    owner, row = active
    before = owner.database.read_bytes()
    captured = capture(corpus)
    report = captured.run()
    body = lineage_sets.decode(row["body_json"])
    sources = {source["id"]: source["document_hash"] for source in body["report"]["sources"]}
    assert len(report["items"]) == len(body["report"]["statements"]) == 3
    for item, statement in zip(report["items"], body["report"]["statements"], strict=True):
        assert item["feature"] == "lineage" and item["text"] == statement["text"]
        assert item["document_hash"] == sources[statement["subject"]]
        assert [passage["document_hash"] for passage in item["passages"]] == [
            sources[passage["source_id"]] for passage in statement["passages"]
        ]
        for check in (check for check in report["checks"] if check["item_id"] == item["id"]):
            passage = item["passages"][check["passage"]]
            if passage["document_hash"] == report["source"]["document_hash"]:
                assert check["state"] == "located"
            else:
                assert check["state"] == "source_mismatch" and check["location"] is None
    assert report["semantics"] == "not_checked"
    assert "lineage_other_originals" in report["not_checked"]
    assert "grounded_lineage" not in report["not_checked"]
    assert captured.current() and owner.database.read_bytes() == before
    monkeypatch.setattr(store, "DB_PATH", corpus[0])
    monkeypatch.setattr(config, "PDF_DIR", corpus[1])
    public = local_operations.dispatch("analysis.audit", {"paper_id": "focal"})
    assert public["ok"] and public["result"] == report
    assert owner.database.read_bytes() == before


def test_distinct_corpora_do_not_collide_when_their_statement_ids_match(active, corpus):
    owner, row = active
    second = dict(row)
    body = lineage_sets.decode(row["body_json"])
    body["corpus_id"] = second["corpus_key"] = str(uuid4())
    second["body_json"] = json.dumps(body)
    second["source_hash"] = lineage_sets.source_hash(body)
    lineage_sets.validate_row(second)
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute(
            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
            tuple(second[key] for key in lineage_sets.COLUMNS.split()),
        )
    report = capture(corpus).run()
    assert len(report["items"]) == len({item["id"] for item in report["items"]}) == 6


def test_invalid_saved_lineage_refuses_whole_audit_without_repairing_content(active, corpus):
    owner, _row = active
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("UPDATE paper_lineage_sets SET source_hash=?", ("0" * 64,))
    before = owner.database.read_bytes()
    with pytest.raises(research_audit.AuditError, match="invalid_saved_content"):
        capture(corpus)
    assert owner.database.read_bytes() == before


def test_saved_lineage_change_invalidates_an_existing_capture(active, corpus):
    owner, _row = active
    captured = capture(corpus)
    prior = captured.run()
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("DELETE FROM paper_lineage_sets")
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        captured.run()
    assert len(prior["items"]) == 3
    assert capture(corpus).run()["items"] == []


def test_audit_without_lineage_never_creates_optional_storage(corpus):
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        store._migrate(conn)
    before = corpus[0].read_bytes()
    assert capture(corpus).run()["items"] == []
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'"
        ).fetchone()
    assert corpus[0].read_bytes() == before
