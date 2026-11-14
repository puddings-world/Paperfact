"""Whole-corpus checks use each selected source's maintained ownership proof."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_audit_lineage import equal_originals as equal_originals
from test_lineage_jobs import work
from test_research_lineage import corpus as corpus

from paper_daily import audit_lineage, config, local_operations, research_audit, store


def test_corpus_checks_every_original_even_when_bytes_match(equal_originals, monkeypatch):
    owner, row, corpus = equal_originals
    monkeypatch.setattr(store, "DB_PATH", owner.database)
    monkeypatch.setattr(config, "PDF_DIR", corpus[1])
    before = owner.database.read_bytes()
    progress = []
    prepared = work(
        audit_lineage.prepare, owner, row, progress=lambda a, b: progress.append((a, b))
    )
    result = prepared.for_delivery(owner, row)
    assert result["originals_checked"] == result["originals_total"] == 3
    assert progress == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert {source["local_paper_id"] for source in result["sources"]} == {"focal", "prior", "later"}
    for source in result["sources"]:
        assert source["state"] == "available"
        assert source["report"]["semantics"] == "not_checked"
        assert all(
            check["state"] == "located"
            for check in source["report"]["checks"]
            if check["rule"] == "quote_location"
        )
        assert not any(check["rule"] == "source_owner" for check in source["report"]["checks"])
        for check in source["report"]["checks"]:
            if "passage" in check:
                assert (
                    check["original_passage"]
                    == source["passage_indices"][check["item_id"]][check["passage"]]
                )
    public = local_operations.dispatch(
        "analysis.audit", dict(paper_id="focal", corpus_key=row["corpus_key"])
    )
    assert public["ok"] and public["result"] == result
    result["originals_checked"] = 100
    assert prepared.for_delivery(owner, row)["originals_checked"] == 3
    assert prepared.current() and owner.database.read_bytes() == before


def test_corpus_delivery_refuses_stale_row_owner_and_forged_report(equal_originals):
    owner, row, _ = equal_originals
    prepared = work(audit_lineage.prepare, owner, row)
    forged = replace(prepared, _json="{}")
    assert not forged.current()
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        prepared.for_delivery(replace(owner), row)
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("DELETE FROM paper_lineage_sets")
    assert not prepared.current()
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        prepared.for_delivery(owner, row)


def test_corpus_cancellation_discards_partial_work(equal_originals):
    owner, row, _ = equal_originals
    seen = []
    before = owner.database.read_bytes()
    with pytest.raises(research_audit.AuditError, match="cancelled"):
        work(
            audit_lineage.prepare,
            owner,
            row,
            cancelled=lambda: bool(seen),
            progress=lambda a, _b: seen.append(a),
        )
    assert seen == [0] and owner.database.read_bytes() == before


def test_corpus_refuses_corrupt_owned_source_without_fallback(equal_originals):
    from paper_daily import lineage_originals

    owner, row, corpus = equal_originals
    source_id = json.loads(row["body_json"])["report"]["sources"][1]["id"]
    original = work(lineage_originals.prepare, owner, row, source_id)
    # Corrupt the actual owned snapshot, while the download and equal-byte peers
    # remain intact. None of them may substitute for the selected original.
    original._source.write_bytes(b"broken original")
    assert (corpus[1] / "prior.pdf").is_file()
    with pytest.raises((ValueError, OSError)):
        work(audit_lineage.prepare, owner, row)


def test_unavailable_source_is_explicit_and_never_borrows_equal_bytes(equal_originals, monkeypatch):
    from paper_daily import lineage_originals

    owner, row, _ = equal_originals
    read = lineage_originals.prepare
    selected = json.loads(row["body_json"])["report"]["sources"][1]["id"]
    calls = []

    def missing(owner, expected, source_id, **kwargs):
        calls.append(source_id)
        return None if source_id == selected else read(owner, expected, source_id, **kwargs)

    monkeypatch.setattr(lineage_originals, "prepare", missing)
    prepared = work(audit_lineage.prepare, owner, row)
    report = prepared.for_delivery(owner, row)
    assert len(calls) == len(set(calls)) == 3
    assert report["originals_checked"] == 2 and report["originals_total"] == 3
    absent = next(source for source in report["sources"] if source["source_id"] == selected)
    assert absent["state"] == "original_unavailable" and absent["report"] is None
    monkeypatch.setattr(audit_lineage, "MAX_PAGES", 0)
    with pytest.raises(research_audit.AuditError, match="input_limit"):
        work(audit_lineage.prepare, owner, row)
