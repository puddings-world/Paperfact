"""Automatic dive annotations retain original workspace, account and PDF authority."""

import sqlite3
from contextlib import closing

import pytest
from test_highlight_generation import ready as _ready
from test_highlight_generation import workspace as _workspace
from test_research_generation import BODY, rows

from paper_daily import brief, dive, paper_highlights, reading_annotation_jobs, store
from paper_daily import research_generation as generation
from paper_daily.highlight_jobs import HighlightJob
from paper_daily.manual_highlight_ops import capture_owner

workspace = _workspace
ready = _ready


def configure(ready, monkeypatch):
    with closing(generation._connect(ready[0])) as conn, conn:
        store.set_kv(conn, "ui.auto_highlights", "1")
    monkeypatch.setattr(paper_highlights, "PDF_DIR", ready[2].path.parent)

    def pack(conn, row):
        return brief.PreparedPack(
            "original source",
            ready[2].path,
            snapshot=brief.input_snapshot(conn, row["id"]),
            document=ready[2],
        )

    monkeypatch.setattr(brief, "pack_text", pack)
    monkeypatch.setattr(dive, "_from_pack", lambda *a, **kw: (BODY, "ok"))


def test_actual_dive_dispatches_group_on_original_workspace_and_account_after_global_switch(
    ready, monkeypatch, tmp_path
):
    configure(ready, monkeypatch)
    other = tmp_path / "other.db"
    with sqlite3.connect(other) as conn:
        conn.executescript(store.SCHEMA)
    captured = []

    def complete(*args, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", other)
        ready[3].update(account="changed", model="changed-model")
        return BODY, "ok"

    def prepare(database, paper_id, **kwargs):
        captured.append((database, paper_id, kwargs))
        with closing(generation._connect(database)) as conn:
            kwargs["owner"].check(conn)
        return {"marks": {"mapped": 2, "total": 2}}, "ok"

    monkeypatch.setattr(dive, "_from_pack", complete)
    monkeypatch.setattr(reading_annotation_jobs, "prepare", prepare)
    assert dive.dive_ahead(paper_id="paper") == 1
    assert len(captured) == 1
    database, paper_id, args = captured[0]
    assert (database, paper_id) == (ready[0], "paper")
    assert args["expected_document_hash"] == ready[2].sha256
    assert args["connections"] == {"account": "original", "model": "original-model"}
    assert args["legacy_root"] == ready[2].path.parent
    assert rows(ready[0], "SELECT body FROM dives") == [{"body": BODY}]
    assert rows(other, "SELECT * FROM dives") == []
    assert rows(other, "SELECT * FROM kv") == []


def test_replaced_pdf_between_dive_commit_and_annotations_keeps_dive_without_second_ai(
    ready, monkeypatch
):
    configure(ready, monkeypatch)
    original = dive._prepare_highlights

    def replace_then_prepare(*args, **kwargs):
        ready[2].path.write_bytes(b"different source after explanation accepted")
        return original(*args, **kwargs)

    monkeypatch.setattr(dive, "_prepare_highlights", replace_then_prepare)
    monkeypatch.setattr(HighlightJob, "run", lambda *a: pytest.fail("No AI on replacement PDF"))
    assert dive.dive_ahead(paper_id="paper") == 1
    assert rows(ready[0], "SELECT body FROM dives") == [{"body": BODY}]
    assert rows(ready[0], "SELECT * FROM paper_highlight_analysis") == []
    assert rows(ready[0], "SELECT * FROM pdf_ai_highlights") == []
    failure = rows(ready[0], "SELECT value FROM kv WHERE key='analyze.failed.highlights.paper'")
    assert "PDF changed" in failure[0]["value"]


def test_late_group_failure_never_marks_recreated_paper(ready, monkeypatch):
    configure(ready, monkeypatch)
    owner = capture_owner(ready[0], "paper")

    def failed(database, paper_id, **kwargs):
        with closing(generation._connect(database)) as conn, conn:
            conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
            store.upsert_papers(
                conn,
                [
                    {
                        "id": paper_id,
                        "title": "Recreated",
                        "year": 2026,
                        "venue": "Fixture",
                        "source": "fixture",
                    }
                ],
            )
        return None, "old generation failed"

    monkeypatch.setattr(reading_annotation_jobs, "prepare", failed)
    messages = []
    dive._prepare_highlights(
        "paper",
        messages.append,
        database=ready[0],
        owner=owner,
        expected_document_hash=ready[2].sha256,
    )
    assert rows(ready[0], "SELECT * FROM kv WHERE key='analyze.failed.highlights.paper'") == []
    assert any("changed research owner" in message for message in messages)
