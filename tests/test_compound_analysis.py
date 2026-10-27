"""The actual pipeline commits venue preparation before its observed resource phase."""

import sqlite3
from contextlib import closing

import pytest
from test_research_compound import driver as driver
from test_research_generation import rows
from test_research_generation import workspace as workspace

from paper_daily import analyze, cites, closeread, dive, followups, store, venues


def test_actual_pipeline_separates_pending_venue_and_resource_transactions(driver, monkeypatch):
    path, _client, document, _calls, install, _invoke = driver
    install("resources")
    monkeypatch.setattr(analyze, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(analyze, "status", lambda *_: {key: True for key in analyze.STEPS})
    monkeypatch.setattr(
        venues,
        "refresh",
        lambda conn, *_a, **_k: conn.execute(
            "UPDATE papers SET venue='Published venue' WHERE id='paper'"
        ),
    )
    from paper_daily import research_questions

    monkeypatch.setattr(research_questions, "ensure", lambda *_: ([], "ready"))
    result = analyze.analyse("paper", log=lambda _: None)
    assert all(result.values())
    assert rows(path, "SELECT venue FROM papers") == [{"venue": "Published venue"}]
    assert len(rows(path, "SELECT * FROM resources")) == 2
    with store.connect() as conn:
        assert store.get_kv(conn, "resources:paper") == "text"


def test_pipeline_stops_unconverted_stages_after_workspace_switch(driver, monkeypatch):
    path, _client, document, _calls, install, _invoke = driver
    other = path.with_name("new-selection.sqlite")
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    install("resources", lambda: monkeypatch.setattr(store, "DB_PATH", other))
    monkeypatch.setattr(analyze, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(analyze, "status", lambda *_: {key: key == "pdf" for key in analyze.STEPS})
    monkeypatch.setattr(venues, "refresh", lambda *_a, **_k: None)
    for module, name in (
        (dive, "dive_ahead"),
        (closeread, "write"),
        (cites, "analyse"),
        (followups, "analyse"),
    ):
        monkeypatch.setattr(
            module, name, lambda *_a, **_k: pytest.fail("No stage may follow new workspace")
        )
    messages = []
    result = analyze.analyse("paper", log=messages.append)
    assert result["pdf"] and not result["dive"]
    assert any("remaining analysis stages" in message for message in messages)
    assert len(rows(path, "SELECT * FROM resources")) == 2
    assert rows(other, "SELECT * FROM resources") == []
    assert rows(other, "SELECT * FROM kv") == []


def test_resource_failure_is_not_reported_as_complete_analysis(driver, monkeypatch):
    path, _client, _document, _calls, install, _invoke = driver
    install("resources")
    monkeypatch.setattr(analyze, "status", lambda *_: {key: True for key in analyze.STEPS})
    monkeypatch.setattr(venues, "refresh", lambda *_a, **_k: None)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER reject_resources BEFORE INSERT ON resources "
            "BEGIN SELECT RAISE(ABORT,'fixture disk'); END"
        )
    from paper_daily.sync_capture import StaleCaptureError

    with pytest.raises(StaleCaptureError):
        analyze.analyse("paper", log=lambda _: None)
    assert rows(path, "SELECT * FROM resources") == []
    assert rows(path, "SELECT * FROM kv WHERE key='resources:paper'") == []
