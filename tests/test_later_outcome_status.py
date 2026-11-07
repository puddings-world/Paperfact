"""Actual native bar shows source-current empty work as absence, not success."""

from types import SimpleNamespace

import pytest
from test_analysis_status import app as app
from test_analysis_status import settle
from test_deep_analysis import db as db
from test_research_generation import pdf

from paper_daily import analyze, config, followups, llm, store
from paper_daily.desktop import analysis_bar
from paper_daily.desktop.main import palette


def prepared(db, monkeypatch, available):
    monkeypatch.setattr(analyze, "PDF_DIR", db)
    monkeypatch.setattr(config, "PDF_DIR", db)
    if available:
        pdf(db / "a.pdf", "The original for a recorded successful empty lookup.")
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    monkeypatch.setattr(
        llm, "complete", lambda *a, **kw: pytest.fail("Status may not call a model")
    )
    assert followups.fetch("a", database=store.DB_PATH) == 0
    bar = analysis_bar.AnalysisBar(SimpleNamespace(analysis_running=lambda *args: False), palette())
    bar.show()
    return bar


@pytest.mark.parametrize("available", [False, True])
def test_actual_bar_explains_queried_empty_without_completion_checkmark(
    app, db, monkeypatch, available
):
    bar = prepared(db, monkeypatch, available)
    try:
        app.processEvents()
        bar.show_paper("a")
        settle(app, bar._status_worker)
        assert "\u5df2\u67e5\u8a62" in bar.label.text() and "\u5c1a\u7121" in bar.label.text()
        assert "\u555f\u5f8c \u2713" not in bar.label.text()
        assert bar._state["later"] is False
        with store.connect() as conn:
            assert followups.overview_for(conn, "a") is None
            import json

            body = json.loads(
                conn.execute(
                    "SELECT body_json FROM paper_later_outcomes WHERE paper_id='a'"
                ).fetchone()[0]
            )
            assert body["query"]["queried_at"] in bar.label.toolTip()
            assert "Recorded query at" in bar.label.toolTip()
            assert "queried, no results" in bar.label.toolTip()
            assert "queried_empty" not in bar.label.toolTip()
    finally:
        bar._status_worker.close()
        bar.close()


def test_late_empty_status_is_not_drawn_after_research_input_changes(app, db, monkeypatch):
    bar = prepared(db, monkeypatch, True)
    try:
        app.processEvents()
        bar.show_paper("a")
        assert bar._status_worker.wait(5)
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO followups(paper_id,work_id,title,fetched_at) "
                "VALUES('a','late','New unjudged work','2026-11-01T00:00:00+00:00')"
            )
        for _ in range(5):
            app.processEvents()
        assert "\u5c1a\u7121" not in bar.label.text()
    finally:
        bar._status_worker.close()
        bar.close()
