"""Actual held-query/source and publication-gap refusal; no live providers."""

import json
import os
import shutil
from contextlib import closing

import pytest
from test_deep_analysis import db as db
from test_research_generation import pdf

from paper_daily import config, followups, later_outcome_sources, later_outcomes, llm, store
from paper_daily import research_generation as generation


def install(db, monkeypatch, available):
    monkeypatch.setattr(config, "PDF_DIR", db)
    if available:
        pdf(db / "a.pdf", "Original A remains the exact query source.")
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: pytest.fail("No overview model call"))


def assert_no_accepted_outcome(path):
    with closing(generation._connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchone():
            assert not conn.execute(
                "SELECT 1 FROM research_generation_requests WHERE status='accepted'"
            ).fetchall()


@pytest.mark.parametrize("available", [False, True], ids=["missing-original", "available-original"])
@pytest.mark.parametrize(
    "change", ["source", "lookup", "inventory", "target", "parent", "database", "policy"]
)
def test_actual_query_changes_never_accept_stale_empty_completion(
    db, monkeypatch, available, change
):
    install(db, monkeypatch, available)
    path = store.DB_PATH

    def query(_):
        if change == "source":
            pdf(db / "a.pdf", "A replacement original B appeared during lookup.")
        elif change == "database":
            replacement = db / "replacement.sqlite"
            shutil.copyfile(path, replacement)
            os.replace(replacement, path)
        elif change == "policy":
            monkeypatch.setattr(followups, "MOST_CITED", followups.MOST_CITED + 1)
        else:
            with store.connect() as conn:
                if change == "lookup":
                    conn.execute("UPDATE papers SET doi='10.0000/replaced' WHERE id='a'")
                elif change == "inventory":
                    conn.execute(
                        "INSERT INTO followups(paper_id,work_id,title,fetched_at) "
                        "VALUES('a','new','Unjudged work','2026-11-01T00:00:00+00:00')"
                    )
                elif change == "target":
                    conn.execute(
                        "INSERT INTO paper_context VALUES('a','My manual overview','[]',"
                        "'2026-11-01T00:00:00+00:00',1)"
                    )
                else:
                    row = conn.execute("SELECT * FROM papers WHERE id='a'").fetchone()
                    conn.execute("DELETE FROM papers WHERE id='a'")
                    conn.execute(
                        "INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row
                    )
        return []

    monkeypatch.setattr(followups, "_citing_openalex", query)
    assert followups.fetch("a", database=path) == 0
    assert_no_accepted_outcome(path)
    with store.connect() as conn:
        assert not followups.nothing_to_tell(conn, "a")
        if change == "target":
            assert followups.overview_for(conn, "a")["summary"] == "My manual overview"
        if change == "inventory":
            assert followups.for_paper(conn, "a")[0]["title"] == "Unjudged work"


@pytest.mark.parametrize("available", [False, True])
def test_source_change_after_staging_is_rejected_under_publication_lock(db, monkeypatch, available):
    install(db, monkeypatch, available)
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    stage = later_outcome_sources.stage

    def changing(context, row):
        result = stage(context, row)
        pdf(db / "a.pdf", "Source changed after byte verification and staging.")
        return result

    monkeypatch.setattr(later_outcome_sources, "stage", changing)
    assert followups.fetch("a", database=store.DB_PATH) == 0
    assert_no_accepted_outcome(store.DB_PATH)
    with closing(generation._connect(store.DB_PATH)) as conn:
        record = conn.execute(
            "SELECT context_json,status FROM research_generation_requests"
        ).fetchone()
        assert record[1] == "candidate"
        assert json.loads(record[0])["table"] == later_outcomes.TABLE
