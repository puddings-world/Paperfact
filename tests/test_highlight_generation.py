"""Actual original-paper selection commits analysis, anchors and receipt together."""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace

import pymupdf
import pytest
from test_research_generation import pdf, rows
from test_research_generation import workspace as _workspace

from paper_daily import llm, sync_capture
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.document_reader import from_workspace
from paper_daily.highlight_jobs import HighlightJob

workspace = _workspace
QUOTES = [
    "The original experiment isolates the effect of independent observations.",
    "The controlled comparison reports improved accuracy under the same budget.",
]


@pytest.fixture
def ready(workspace, monkeypatch):
    database, client, prior = workspace
    prior.path.unlink()
    with pymupdf.open() as document:
        document.new_page().insert_textbox((40, 40, 550, 200), " ".join(QUOTES))
        document.save(prior.path)
    document = from_workspace(database, legacy_root=prior.path.parent).resolve("paper")
    selection, requests, routes = [0], [], []
    selected = {"account": "original", "model": "original-model"}
    monkeypatch.setattr(llm, "capture_connections", lambda: dict(selected))
    monkeypatch.setattr(llm, "settings", lambda **kwargs: {})

    @contextmanager
    def scope(route):
        routes.append(route)
        yield

    def complete(prompt, **kwargs):
        requests.append(prompt)
        return Completion(
            json.dumps(
                {
                    "items": [
                        {"id": index, "kind": "evidence", "reason": "This controls the comparison."}
                        for index in selection
                    ]
                }
            )
        )

    monkeypatch.setattr(llm, "connection_scope", scope)
    monkeypatch.setattr(llm, "complete_result", complete)
    return database, client, document, selected, routes, requests, selection


def capture(ready):
    return HighlightJob.capture(ready[0], "paper", legacy_root=ready[2].path.parent)


def marks(database):
    return rows(database, "SELECT * FROM pdf_ai_highlights ORDER BY source_key")


def change_mark(database, *, delete=False):
    mark = marks(database)[0]
    with closing(generation._connect(database)) as conn:
        observed = sync_capture.observe_target(
            conn,
            "paper",
            "paper",
            "ai_highlight",
            mark["document_hash"] + ":" + mark["source_key"],
        )
        with sync_capture.expecting(conn, [observed]):
            conn.execute(
                "DELETE FROM pdf_ai_highlights WHERE id=?"
                if delete
                else "UPDATE pdf_ai_highlights SET hidden=1 WHERE id=?",
                (mark["id"],),
            )
            conn.commit()


def test_actual_highlights_and_analysis_are_one_retryable_publication(ready):
    database, client, document, selected, routes, requests, _ = ready
    job = capture(ready)
    selected.update(account="new", model="new-model")
    assert job.run().status == "accepted"
    assert job.run() == job.publication and len(requests) == 1
    assert routes == [{"account": "original", "model": "original-model"}]
    assert job.placement == {"mapped": 1, "unmatched": 0, "total": 1}
    saved = rows(database, "SELECT * FROM paper_highlight_analysis")[0]
    mark = marks(database)[0]
    assert saved["document_hash"] == mark["document_hash"] == document.sha256
    assert mark["analysis_hash"] == saved["source_hash"]
    assert mark["quote"] == QUOTES[0]
    assert json.loads(mark["anchor"])["p0"] == 0
    receipt = rows(database, "SELECT * FROM research_generation_requests")[0]
    assert generation.validate_request_record(receipt) == receipt
    assert json.loads(receipt["context_json"])["highlight_plan"]["marks"][0]["quote"] == QUOTES[0]
    if client:
        pending = client.journal.pending()
        related = [
            op
            for op in pending
            if op.get("payload", {}).get("feature") in ("highlight_analysis", "ai_highlight")
        ]
        assert len(related) == 2
        assert all(op["payload"]["source_document_hash"] == document.sha256 for op in related)


def test_mark_write_failure_rolls_back_analysis_and_keeps_complete_result(ready):
    database = ready[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER broken_marks BEFORE INSERT ON pdf_ai_highlights "
            "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    job = capture(ready)
    assert job.run().status == "candidate"
    assert rows(database, "SELECT * FROM paper_highlight_analysis") == []
    assert marks(database) == []
    assert rows(database, "SELECT * FROM paper_annotation_known") == []
    retained = generation.list_recovery_requests(database)
    assert len(retained) == 1
    assert json.loads(retained[0]["row_json"]) == job.result
    assert len(json.loads(retained[0]["context_json"])["highlight_plan"]["marks"]) == 1
    assert (
        generation.retry_publication(generation.GenerationContext(retained[0]["context_json"]))
        == job.publication
    )
    assert len(ready[5]) == 1
    if ready[1]:
        assert not [
            op
            for op in ready[1].journal.pending()
            if op.get("payload", {}).get("feature") in ("highlight_analysis", "ai_highlight")
        ]


def test_user_hidden_choice_survives_omission_and_return_with_same_source_digest(ready):
    database = ready[0]
    assert capture(ready).run().status == "accepted"
    digest = rows(database, "SELECT source_hash FROM paper_highlight_analysis")[0]["source_hash"]
    change_mark(database)
    ready[6][:] = [1]
    assert capture(ready).run().status == "accepted"
    assert len(marks(database)) == 2
    assert next(mark for mark in marks(database) if mark["quote"] == QUOTES[0])["hidden"] == 1
    ready[6][:] = [0]
    assert capture(ready).run().status == "accepted"
    assert rows(database, "SELECT source_hash FROM paper_highlight_analysis") == [
        {"source_hash": digest}
    ]
    assert next(mark for mark in marks(database) if mark["quote"] == QUOTES[0])["hidden"] == 1
    assert len(ready[5]) == 3


def test_changed_user_hidden_choice_during_generation_retains_entire_new_layer(ready, monkeypatch):
    database = ready[0]
    assert capture(ready).run().status == "accepted"
    before = rows(database, "SELECT * FROM paper_highlight_analysis")
    job = capture(ready)
    complete = llm.complete_result

    def delayed(*args, **kwargs):
        answer = complete(*args, **kwargs)
        change_mark(database)
        return answer

    monkeypatch.setattr(llm, "complete_result", delayed)
    assert job.run().status == "candidate"
    assert rows(database, "SELECT * FROM paper_highlight_analysis") == before
    assert marks(database)[0]["hidden"] == 1
    assert len(ready[5]) == 2


def test_changed_pdf_retains_selected_text_without_placing_on_replacement(ready, monkeypatch):
    database, _, document, *_ = ready
    complete = llm.complete_result

    def replace_source(*args, **kwargs):
        answer = complete(*args, **kwargs)
        document.path.unlink()
        pdf(document.path, "Unrelated replacement experiment")
        return answer

    monkeypatch.setattr(llm, "complete_result", replace_source)
    job = capture(ready)
    assert job.run().status == "candidate"
    assert marks(database) == []
    assert rows(database, "SELECT * FROM paper_highlight_analysis") == []
    assert json.loads(job.result["body_json"])["items"][0]["text"] == QUOTES[0]
    assert job.placement == {"mapped": 0, "unmatched": 1, "total": 1}


def test_duplicate_activation_does_not_run_a_second_model(ready, monkeypatch):
    first, second = capture(ready), capture(ready)
    complete = llm.complete_result

    def nested(*args, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            second.run()
        return complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", nested)
    assert first.run().status == "accepted" and len(ready[5]) == 1


def test_model_failure_preserves_existing_analysis_and_marks(ready, monkeypatch):
    assert capture(ready).run().status == "accepted"
    before = (rows(ready[0], "SELECT * FROM paper_highlight_analysis"), marks(ready[0]))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: Completion(None, "Unavailable"))
    with pytest.raises(ValueError, match="Unavailable"):
        capture(ready).run()
    assert (rows(ready[0], "SELECT * FROM paper_highlight_analysis"), marks(ready[0])) == before


def test_deleted_synchronized_mark_is_not_implicitly_restored(ready):
    if ready[1] is None:
        # Unbound deletion has no synchronization tombstone; current missing state
        # can be regenerated by a fresh explicitly requested job.
        assert capture(ready).run().status == "accepted"
        change_mark(ready[0], delete=True)
        assert capture(ready).run().status == "accepted"
        return
    assert capture(ready).run().status == "accepted"
    before = rows(ready[0], "SELECT * FROM paper_highlight_analysis")
    change_mark(ready[0], delete=True)
    assert capture(ready).run().status == "candidate"
    assert marks(ready[0]) == []
    assert rows(ready[0], "SELECT * FROM paper_highlight_analysis") == before


@pytest.mark.parametrize("field", ["quote", "document_hash", "hidden"])
def test_retained_plan_cannot_change_source_or_user_choice(ready, field):
    job = capture(ready)
    assert job.run().status == "accepted"
    data = job.context.data
    data["highlight_plan"]["marks"][0][field] = {
        "quote": "Invented quotation",
        "document_hash": "f" * 64,
        "hidden": 1,
    }[field]
    tampered = replace(job.context, _json=generation._context_json(data))
    with pytest.raises(ValueError):
        generation.publish_generated(tampered, row=job.result)
    assert marks(ready[0])[0]["quote"] == QUOTES[0]
    assert not generation.list_recovery_requests(ready[0])
