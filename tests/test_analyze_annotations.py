"""The analysis pipeline pins its source before remote phases, including cached marks."""

import json

import pymupdf
import pytest
from test_highlight_generation import capture, marks
from test_highlight_generation import ready as _ready
from test_highlight_generation import workspace as _workspace
from test_research_generation import rows

from paper_daily import (
    analyze,
    closeread,
    dive,
    llm,
    paper_highlights,
    research_question_jobs,
    resources,
    venues,
)
from paper_daily.document_reader import from_workspace

workspace = _workspace
ready = _ready
NEW_QUOTE = "The revised experiment measures accuracy under an independent evaluation budget."


def replace_pdf(path):
    path.unlink()
    with pymupdf.open() as document:
        document.new_page().insert_textbox((40, 40, 550, 200), NEW_QUOTE)
        document.save(path)


def configure(ready, monkeypatch, *, dive_ready):
    monkeypatch.setattr(analyze, "PDF_DIR", ready[2].path.parent)
    monkeypatch.setattr(paper_highlights, "PDF_DIR", ready[2].path.parent)
    original_status = analyze.status
    monkeypatch.setattr(
        analyze,
        "status",
        lambda *args, **kwargs: {
            **original_status(*args, **kwargs), "dive": dive_ready, "cites": True, "later": True
        },
    )
    monkeypatch.setattr(venues, "refresh", lambda *a, **kw: None)
    monkeypatch.setattr(resources, "needs_check", lambda *a: False)
    monkeypatch.setattr(research_question_jobs, "ensure", lambda *a, **kw: ([], "fixture"))


def test_actual_analysis_refreshes_old_cached_highlights_for_initial_verified_new_pdf(
    ready, monkeypatch
):
    assert capture(ready).run().status == "accepted"
    old_hash = ready[2].sha256
    replace_pdf(ready[2].path)
    current = from_workspace(ready[0], legacy_root=ready[2].path.parent).resolve("paper")
    assert current.sha256 != old_hash
    configure(ready, monkeypatch, dive_ready=True)
    analyze.analyse("paper", log=lambda *a: None)
    saved = rows(ready[0], "SELECT * FROM paper_highlight_analysis")[0]
    assert saved["document_hash"] == current.sha256
    assert json.loads(saved["body_json"])["items"][0]["text"] == NEW_QUOTE
    new_marks = [mark for mark in marks(ready[0]) if mark["document_hash"] == current.sha256]
    assert len(new_marks) == 1 and new_marks[0]["quote"] == NEW_QUOTE
    assert len(ready[5]) == 2


def test_actual_analysis_never_recaptures_replacement_after_remote_explanation(ready, monkeypatch):
    assert capture(ready).run().status == "accepted"
    before_analysis = rows(ready[0], "SELECT * FROM paper_highlight_analysis")
    before_marks = marks(ready[0])
    configure(ready, monkeypatch, dive_ready=False)
    monkeypatch.setattr(closeread, "get", lambda *a: {"body": "already available"})

    def remote_explanation(**kwargs):
        replace_pdf(ready[2].path)
        return 1

    monkeypatch.setattr(dive, "dive_ahead", remote_explanation)
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: pytest.fail("No AI on replacement")
    )
    analyze.analyse("paper", log=lambda *a: None)
    assert rows(ready[0], "SELECT * FROM paper_highlight_analysis") == before_analysis
    assert marks(ready[0]) == before_marks
    failure = rows(ready[0], "SELECT value FROM kv WHERE key='analyze.failed.highlights.paper'")
    assert "PDF changed" in failure[0]["value"]
    assert len(ready[5]) == 1
