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


@pytest.fixture
def equal_originals(corpus, monkeypatch):
    """Real distinct paper owners with exactly equal, fully readable source bytes."""
    from test_lineage_recovery import published
    from test_research_evidence import pdf
    from test_research_lineage import CHANGE, CITING, LATER, OWN_LATER, PRIOR

    from paper_daily import research_generation as generation
    from paper_daily import research_lineage
    from paper_daily.manual_highlight_ops import observe_owner

    database, root, _old = corpus
    pdf(root / "focal.pdf", [[PRIOR, CHANGE, CITING, LATER, OWN_LATER]])
    for name in ("prior", "later"):
        (root / (name + ".pdf")).write_bytes((root / "focal.pdf").read_bytes())
    selected = research_lineage.capture(database, "focal", ["prior", "later"], legacy_root=root)
    same = database, root, selected
    published(same, monkeypatch)
    owner = observe_owner(database, "focal", expected_native=generation._identity(database))
    return owner, lineage_sets.saved(database, "focal")[0], same


def test_equal_pdf_bytes_never_verify_another_paper_owners_lineage(equal_originals):
    owner, row, corpus = equal_originals
    before = owner.database.read_bytes()
    captured = capture(corpus)
    report = captured.run()
    body = lineage_sets.decode(row["body_json"])
    assert len({source["document_hash"] for source in body["report"]["sources"]}) == 1
    bindings = {binding["source_id"]: binding["paper_id"] for binding in body["bindings"]}
    statements = {statement["id"]: statement for statement in body["report"]["statements"]}
    foreign, local = [], []
    for check in report["checks"]:
        if check["rule"] != "quote_location":
            continue
        statement = statements[check["item_id"].rsplit(":", 1)[1]]
        passage = statement["passages"][check["passage"]]
        (local if bindings[passage["source_id"]] == "focal" else foreign).append(check)
    assert foreign and local
    assert all(check["state"] != "located" for check in foreign), foreign
    assert all(
        check["state"] == "source_owner_mismatch" and check["location"] is None for check in foreign
    )
    assert all(check["state"] == "located" for check in local)
    assert captured.current() and owner.database.read_bytes() == before


def test_equal_byte_foreign_owner_never_borrows_spans_model_route_or_exact_fact_binding(
    equal_originals, monkeypatch
):
    from paper_daily import audit_appraisal, audit_facts, audit_retrieval, llm

    owner, _row, corpus = equal_originals
    captured = capture(corpus)
    items = json.loads(captured._items_json)
    foreign = next(item for item in items if item["source_paper_id"] == "prior")
    focal = next(item for item in items if item["source_paper_id"] == "focal")
    monkeypatch.setattr(
        llm, "capture_connections", lambda: pytest.fail("No foreign-source AI route")
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No AI call"))
    with pytest.raises(research_audit.AuditError, match="source_owner_mismatch"):
        audit_appraisal.AppraisalJob.prepare(captured, [foreign["id"]])
    spans, _pages = audit_retrieval.retrieve(captured.snapshot, [foreign, focal])
    assert spans[foreign["id"]] == [] and spans[focal["id"]]
    fact = dict(
        id="foreign-output",
        category="method",
        statement=foreign["text"],
        origin="author_stated",
        scope=dict(
            construct="method",
            outcome="comparison",
            comparator="none",
            population="study",
            time="unspecified",
            unit="text",
            statistic="none",
            conditions="specified",
        ),
        value=dict(kind="text", text=foreign["text"]),
        location=dict(kind="output", item_id=foreign["id"], start=0, end=len(foreign["text"])),
        passages=[],
    )
    proposed = dict(
        format=audit_facts.FORMAT,
        source=captured.snapshot.source,
        study_type="empirical",
        facts=[fact],
    )
    sheet = audit_facts.prepare(captured, proposed)
    assert sheet.report["facts"][0]["source_binding"] == "different_original"
    assert sheet.current() and captured.current()


def test_lineage_audit_maps_local_owners_to_the_readers_native_paper_ids(equal_originals):
    from paper_daily import lineage_sets

    owner, row, corpus = equal_originals
    native = {key: str(uuid4()) for key in ("focal", "prior", "later")}
    # An actual alias registry, not a source/byte grant or a claim of full enrollment.
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute(
            "CREATE TABLE research_paper_identity(sync_id TEXT PRIMARY KEY,local_id TEXT UNIQUE)"
        )
        conn.executemany(
            "INSERT INTO research_paper_identity VALUES(?,?)",
            [(value, key) for key, value in native.items()],
        )
    captured = capture(corpus)
    assert captured.snapshot.source["paper_id"] == native["focal"]
    report = captured.run()
    assert {item["source_paper_id"] for item in report["items"]} == set(native.values())
    body = lineage_sets.decode(row["body_json"])
    local = next(
        statement
        for statement in body["report"]["statements"]
        if statement["subject"] == body["report"]["focal"]
    )
    checks = [check for check in report["checks"] if check["item_id"].endswith(":" + local["id"])]
    assert checks and all(check["state"] == "located" for check in checks)
