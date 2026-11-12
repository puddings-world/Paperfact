"""Successful queried-empty work is distinct from a retryable failure."""

import json
from contextlib import closing

import pytest
from test_deep_analysis import db as db
from test_research_generation import pdf

from paper_daily import analyze, config, followups, llm, store
from paper_daily import research_compound as compound


@pytest.mark.parametrize("available", [False, True], ids=["no-original", "owned-original"])
def test_a_paper_no_source_has_does_not_hold_up_every_night_completed_empty(
    db, monkeypatch, available
):
    monkeypatch.setattr(analyze, "PDF_DIR", db)
    monkeypatch.setattr(config, "PDF_DIR", db)
    if available:
        pdf(db / "a.pdf", "A source with no queried later work yet.")
    calls = []
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])

    def forbidden(*args, **kwargs):
        calls.append(True)
        pytest.fail("Empty overview must not call a model")

    monkeypatch.setattr(llm, "complete", forbidden)
    with store.connect() as conn:
        if not available:
            store.set_kv(conn, "analyze.failed.pdf.a", "no source had the PDF")
    assert followups.fetch("a", database=store.DB_PATH) == 0
    with closing(compound.generation._connect(store.DB_PATH)) as conn:
        records = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM research_compound_requests WHERE status='accepted'"
            )
        ]
        assert len(records) == 1
        compound.validate_request_record(records[0])
        assert json.loads(records[0]["mutations_json"])["puts"] == []
    wrote, _reason = followups.overview("a", database=store.DB_PATH)
    assert not wrote and calls == []
    with store.connect() as conn:
        assert followups.overview_for(conn, "a") is None
        assert conn.execute("SELECT COUNT(*) FROM followups WHERE paper_id='a'").fetchone()[0] == 0
        assert "later" not in analyze.left(conn, "a", retry=True)
        assert "later" not in analyze.left(conn, "a")
        if not available:
            assert analyze.left(conn, "a") == []
            assert analyze.upcoming(conn, 1) == ["c"]
            assert analyze.left(conn, "a", retry=True) == ["pdf", "dive", "highlights", "cites"]


def test_cleared_json_null_is_not_a_real_later_failure(db, monkeypatch):
    monkeypatch.setattr(analyze, "PDF_DIR", db)
    monkeypatch.setattr(config, "PDF_DIR", db)
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    assert followups.fetch("a", database=store.DB_PATH) == 0
    with store.connect() as conn:
        store.set_kv(conn, "analyze.failed.later.a", None)
        assert (
            conn.execute("SELECT value FROM kv WHERE key='analyze.failed.later.a'").fetchone()[0]
            == "null"
        )
        assert followups.nothing_to_tell(conn, "a")
        assert "later" not in analyze.left(conn, "a", retry=True)
        store.set_kv(conn, "analyze.failed.later.a", "A genuine later-work failure")
        assert not followups.nothing_to_tell(conn, "a")
        assert "later" in analyze.left(conn, "a", retry=True)
        assert "later" not in analyze.left(conn, "a")
        store.set_kv(conn, "analyze.failed.later.a", None)
        assert followups.nothing_to_tell(conn, "a")


def test_worker_lookahead_does_not_starve_next_paper_behind_unverified_empty(db, monkeypatch):
    monkeypatch.setattr(analyze, "PDF_DIR", db)
    monkeypatch.setattr(config, "PDF_DIR", db)
    pdf(db / "a.pdf", "An owned original for the already queried paper.")
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    assert followups.fetch("a", database=store.DB_PATH) == 0
    with store.connect() as conn:
        for step in ("dive", "highlights", "cites"):
            store.set_kv(conn, "analyze.failed." + step + ".a", "Requires an explicit retry")
        assert followups.nothing_to_tell(conn, "a")
        assert analyze.left(conn, "a") == []
        assert analyze.upcoming(conn, 1) == ["a"]  # Metadata caller has not hashed its PDF.
    submitted = []
    monkeypatch.setattr(
        analyze, "analyse_many", lambda ids, **kw: submitted.extend(ids) or len(ids)
    )
    assert analyze.ahead(1, log=lambda _: None) == 1
    assert submitted == ["c"]
