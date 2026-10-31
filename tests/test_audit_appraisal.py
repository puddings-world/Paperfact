"""Explicit model appraisal has one call budget, exact sources and no research writer."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_research_evidence import source as source_fixture

from paper_daily import audit_appraisal as appraisal
from paper_daily import audit_inputs, llm
from paper_daily.ai_types import Completion, Settings

source = source_fixture


@pytest.fixture
def captured(source, monkeypatch):
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,quote,anchor,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                "paper",
                source.sha256,
                "Replication used a held-out cohort of 50 participants.",
                json.dumps(dict(p0=1, o0=0, p1=1, o1=8)),
                "now",
            ),
        )
    cfg = Settings(backend="openai", model="chosen-model", account_id="fixture-account")
    monkeypatch.setattr(llm, "settings", lambda **kw: cfg)
    connections = ({}, {}, database.parent)
    monkeypatch.setattr(llm, "capture_connections", lambda: connections)
    return audit_inputs.AuditCapture.capture(database, "paper", document=source), source, cfg


def response(prompt, *, status="supported", quote=None, **kw):
    items = json.loads(prompt)["assertions"]
    return Completion(
        text=json.dumps(
            {
                "items": [
                    dict(
                        id=item["id"],
                        status=status,
                        reason="A proposed interpretation requiring reader review.",
                        evidence=[
                            dict(
                                span_id=item["spans"][0]["id"],
                                quote=quote or item["spans"][0]["text"],
                            )
                        ]
                        if item["spans"]
                        else [],
                    )
                    for item in items
                ]
            }
        ),
        model="returned-model",
    )


def job(captured):
    return appraisal.AppraisalJob.prepare(captured[0], ["mark:1"])


def test_one_captured_route_result_is_not_scientific_certification_or_database_write(
    captured, monkeypatch
):
    calls = []
    capture, source, cfg = captured
    before = source._owner.db_path.read_bytes()

    def complete(prompt, **kw):
        calls.append(kw)
        assert kw["cfg"] is cfg and kw["task"] == "audit"
        return response(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", complete)
    task = job(captured)
    monkeypatch.setattr(
        llm, "settings", lambda **kw: Settings("codex", model="different-account-model")
    )
    stages = []
    report = task.run(progress=stages.append)
    assert stages == ["retrieval", "model", "verification"]
    assert task.run() == report and len(calls) == 1
    assert report["generation"] == dict(
        task="audit",
        backend="openai",
        requested_model="chosen-model",
        returned_model="returned-model",
    )
    finding = report["findings"][0]
    assert finding["proposed_status"] == "supported" and finding["state"] == "proposed"
    assert finding["evidence"][0]["state"] == "located"
    assert finding["semantic_validation"] == "model_proposal"
    assert report["retrieval"] == "bounded_lexical_not_exhaustive"
    assert report["persistence"] == "local_derived"
    assert source._owner.db_path.read_bytes() == before
    assert "fixture-account" not in json.dumps(report) and str(source.path) not in json.dumps(
        report
    )


def test_invented_quote_never_gains_usable_evidence(captured, monkeypatch):
    monkeypatch.setattr(
        llm, "complete_result", lambda prompt, **kw: response(prompt, quote="Invented source text")
    )
    report = job(captured).run()
    finding = report["findings"][0]
    assert finding["proposed_status"] == "supported"
    assert finding["state"] == "evidence_unverified"
    assert finding["evidence"][0]["state"] == "missing" and finding["evidence"][0]["anchor"] is None


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        '{"items":[]}',
        '{"items":null}',
        '{"items":[],"items":[]}',
        '{"items":[{"id":"foreign","status":"supported","reason":"fake","evidence":[]}]}',
        '{"items":[{"id":"mark:1","status":"verified","reason":"fake","evidence":[]}]}',
        '{"items":[{"id":"mark:1","status":"supported","reason":"fake","evidence":[],"score":100}]}',
    ],
)
def test_malformed_incomplete_or_fabricated_model_output_requires_explicit_new_job(
    captured, monkeypatch, text
):
    calls = []
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: calls.append(1) or Completion(text=text)
    )
    task = job(captured)
    with pytest.raises(ValueError):
        task.run()
    assert task.result is None and calls == [1]
    with pytest.raises(ValueError, match="explicit_retry_required"):
        task.run()
    assert calls == [1]


@pytest.mark.parametrize("selected", [[], ["foreign"], ["mark:1", "mark:1"], True])
def test_bad_selection_sends_no_model_request(captured, monkeypatch, selected):
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: pytest.fail("Unexpected paid call")
    )
    with pytest.raises(ValueError):
        appraisal.AppraisalJob.prepare(captured[0], selected)


def test_unversioned_legacy_output_cannot_be_retargeted_to_current_pdf(captured, monkeypatch):
    capture, source, _cfg = captured
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        conn.execute("INSERT INTO dives VALUES('paper','Unversioned legacy assertion','now',NULL)")
    fresh = audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: pytest.fail("Unexpected paid call")
    )
    with pytest.raises(ValueError, match="source_version_unbound"):
        appraisal.AppraisalJob.prepare(fresh, ["dive"])


@pytest.mark.parametrize("scope", ["source", "saved", "cancel"])
def test_changes_or_cancellation_before_call_never_spend(captured, monkeypatch, scope):
    task = job(captured)
    capture, source, _cfg = captured
    if scope == "source":
        source.path.write_bytes(b"changed")
    elif scope == "saved":
        with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
            conn.execute("INSERT INTO dives VALUES('paper','new','now',NULL)")
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: pytest.fail("Unexpected paid call")
    )
    with pytest.raises(ValueError):
        task.run(cancelled=lambda: scope == "cancel")
    assert task.result is None and task.attempted is False


@pytest.mark.parametrize("scope", ["source", "saved", "cancel"])
def test_completed_original_result_remains_a_proposal_after_change_during_call(
    captured, monkeypatch, scope
):
    task = job(captured)
    capture, source, _cfg = captured
    stopped = [False]

    def changed(prompt, **kw):
        if scope == "source":
            source.path.write_bytes(b"changed")
        elif scope == "saved":
            with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
                conn.execute("INSERT INTO dives VALUES('paper','new','now',NULL)")
        else:
            stopped[0] = True
        return response(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", changed)
    report = task.run(cancelled=lambda: stopped[0])
    assert report["source"]["document_hash"] == source.sha256
    assert report["findings"][0]["evidence"][0]["state"] == "located"
    assert report["cancelled_after_call"] is (scope == "cancel")
    assert report["inputs_current"] is (scope == "cancel")
    assert task.result == report and report["semantic_validation"] == "model_proposal"


def test_two_simultaneous_actions_make_one_provider_call(captured, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(prompt, **kw):
        calls.append(1)
        entered.set()
        release.wait(10)
        return response(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", slow)
    first, second = job(captured), job(captured)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(first.run)
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError, match="already_running"):
                second.run()
        finally:
            release.set()
        assert pending.result(timeout=10)["findings"]
    assert calls == [1]


def test_requested_model_fallback_is_never_labelled_provider_reported(captured, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(
        llm,
        "complete_result",
        lambda prompt, **kw: replace(response(prompt, **kw), model_reported=False),
    )
    report = job(captured).run()
    assert report["generation"]["requested_model"] == "chosen-model"
    assert report["generation"]["returned_model"] is None
