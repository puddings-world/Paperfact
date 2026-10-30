"""Actual link production retains exact highlights, explanation inputs and PDF identity."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_question_generation import ready as _ready
from test_research_generation import pdf, rows
from test_research_generation import workspace as _workspace

from paper_daily import llm, store, sync_capture
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.document_reader import from_workspace
from paper_daily.reading_link_jobs import ReadingLinksJob

workspace = _workspace
ready = _ready
QUOTE = "Original experiment supports the reported controlled comparison."


def save(database, table, feature, value):
    with closing(generation._connect(database)) as conn:
        observed = sync_capture.observe_target(conn, "paper", "paper", feature, "main")
        with sync_capture.expecting(conn, [observed]):
            columns = list(value)
            updates = ",".join(f'"{key}"=excluded."{key}"' for key in columns if key != "paper_id")
            names = ",".join(f'"{key}"' for key in columns)
            conn.execute(
                f'INSERT INTO "{table}"({names}) VALUES('
                + ",".join("?" for _ in columns)
                + f") ON CONFLICT(paper_id) DO UPDATE SET {updates}",
                tuple(value.values()),
            )
            conn.commit()


@pytest.fixture
def links_ready(ready, monkeypatch):
    database, client, prior, selected, routes, _ = ready
    prior.path.unlink()
    pdf(prior.path, QUOTE)
    document = from_workspace(database, legacy_root=prior.path.parent).resolve("paper")
    assert document.available and document.sha256 != prior.sha256
    highlight = {
        "paper_id": "paper",
        "source_hash": "a" * 64,
        "document_hash": document.sha256,
        "written_at": store.now(),
        "body_json": json.dumps(
            {
                "items": [
                    {
                        "text": QUOTE,
                        "page": 1,
                        "kind": "evidence",
                        "reason": "Controlled evidence",
                        "source": "page:1",
                    }
                ],
                "coverage": {"pages": 1, "empty_pages": [], "chunks": 1, "has_page_numbers": True},
            }
        ),
    }
    save(database, "paper_highlight_analysis", "highlight_analysis", highlight)
    requests = []

    def complete(prompt, **kwargs):
        requests.append(json.loads(prompt))
        return Completion(
            json.dumps(
                {
                    "links": [
                        {
                            "quote": 0,
                            "section": "dive:0",
                            "explanation": "The quotation supports this comparison.",
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(llm, "complete_result", complete)
    return database, client, document, selected, routes, requests, highlight


def capture(value):
    return ReadingLinksJob.capture(value[0], "paper", legacy_root=value[2].path.parent)


def test_links_publish_exact_source_and_retry_without_another_model(links_ready):
    database, client, document, selected, routes, requests, _ = links_ready
    job = capture(links_ready)
    selected.update(account="another", model="another")
    result = job.run()
    assert result.status == "accepted" and job.run() == result
    assert len(requests) == 1 and requests[0]["quotes"][0]["text"] == QUOTE
    assert routes == [{"account": "original-account", "model": "original-model"}]
    row = rows(database, "SELECT * FROM paper_reading_links")[0]
    assert row["document_hash"] == document.sha256
    assert json.loads(row["body_json"])["analysis_hash"] == "a" * 64
    if client:
        operations = [
            op
            for op in client.journal.pending()
            if op.get("payload", {}).get("feature") == "reading_links"
        ]
        assert len(operations) == 1
        assert operations[0]["payload"]["source_document_hash"] == document.sha256


@pytest.mark.parametrize("change", ["analysis", "explanation", "pdf", "target"])
def test_changed_inputs_retain_completed_links_without_overwriting(
    links_ready, monkeypatch, change
):
    database, _, document, _, _, requests, highlight = links_ready
    job = capture(links_ready)
    original = llm.complete_result

    def changed(prompt, **kwargs):
        result = original(prompt, **kwargs)
        if change == "pdf":
            document.path.unlink()
            pdf(document.path, "A replacement source")
        elif change == "analysis":
            save(
                database,
                "paper_highlight_analysis",
                "highlight_analysis",
                {**highlight, "source_hash": "b" * 64},
            )
        elif change == "explanation":
            save(
                database,
                "dives",
                "dive",
                {
                    "paper_id": "paper",
                    "body": "Edited explanation",
                    "spec": None,
                    "written_at": store.now(),
                },
            )
        else:
            save(
                database,
                "paper_reading_links",
                "reading_links",
                {
                    "paper_id": "paper",
                    "body_json": json.dumps({"links": [], "analysis_hash": "b" * 64}),
                    "document_hash": document.sha256,
                    "source_hash": "b" * 64,
                    "written_at": store.now(),
                },
            )
        return result

    monkeypatch.setattr(llm, "complete_result", changed)
    outcome = job.run()
    assert outcome.status == "candidate" and job.run() == outcome
    assert len(requests) == 1
    current = rows(database, "SELECT * FROM paper_reading_links")
    assert len(current) == (1 if change == "target" else 0)
    if current:
        assert current[0]["source_hash"] == "b" * 64


@pytest.mark.parametrize("digest", [None, "b" * 64])
def test_unknown_or_wrong_source_does_not_call_model(links_ready, digest):
    database, _, _, _, _, requests, highlight = links_ready
    save(
        database,
        "paper_highlight_analysis",
        "highlight_analysis",
        {**highlight, "document_hash": digest},
    )
    with pytest.raises(ValueError, match="PDF"):
        capture(links_ready).run()
    assert not requests
    assert rows(database, "SELECT * FROM paper_reading_links") == []


def test_storage_failure_keeps_completed_links_without_regeneration(links_ready):
    database, _, _, _, _, requests, _ = links_ready
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER fail_links BEFORE INSERT ON paper_reading_links "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    job = capture(links_ready)
    outcome = job.run()
    assert outcome.status == "candidate" and job.run() == outcome
    assert len(requests) == 1
    records = generation.list_recovery_requests(database)
    assert len(records) == 1
    assert json.loads(records[0]["row_json"]) == job.result
    assert rows(database, "SELECT * FROM paper_reading_links") == []


def test_duplicate_link_job_does_not_call_model_twice(links_ready, monkeypatch):
    first, second = capture(links_ready), capture(links_ready)
    original = llm.complete_result

    def overlap(prompt, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            second.run()
        return original(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", overlap)
    assert first.run().status == "accepted"
    assert len(links_ready[5]) == 1


def test_successful_relink_replaces_existing_links_without_marker_collision(links_ready):
    assert capture(links_ready).run().status == "accepted"
    assert capture(links_ready).run().status == "accepted"
    assert len(links_ready[5]) == 2
    assert len(rows(links_ready[0], "SELECT * FROM paper_reading_links")) == 1
    assert (
        len(
            rows(
                links_ready[0],
                "SELECT * FROM paper_annotation_known "
                "WHERE feature='reading_links' AND paper_id='paper'",
            )
        )
        == 1
    )
