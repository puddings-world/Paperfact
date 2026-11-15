"""Actual generated local report publication preserves versions and exact originals."""

import json
from contextlib import closing
from dataclasses import replace

import pytest
from test_survey_jobs import conn as conn
from test_survey_jobs import ready as ready

from paper_daily import llm, survey_jobs, survey_local, survey_reader
from paper_daily import research_generation as generation
from paper_daily import survey_local_generated as publication


def job(ready, **kwargs):
    return survey_jobs.SurveyJob.capture(ready[0], "cat", legacy_root=ready[1], **kwargs)


def dump(database):
    with closing(generation._connect(database)) as conn:
        return list(conn.iterdump())


def test_generated_report_saved_once_readable_and_exportable_with_exact_originals(ready):
    current = job(ready)
    proposal = current.generate()
    before = dump(ready[0])
    staged = publication.prepare(proposal)
    assert dump(ready[0]) == before
    outcome = publication.publish(staged)
    assert outcome == dict(state="generated", reports=1, report_id=proposal.report["id"])
    saved = survey_reader.read(ready[0], "cat")
    assert saved.data["report"] == proposal.report
    assert survey_reader.inspect(saved, 0, 0, 0)["located"]
    exported = survey_local.collect(ready[0], "cat")
    assert exported.captured_record["version_id"]
    assert len(exported.files) == 2
    after = dump(ready[0])
    assert publication.publish(staged)["state"] == "unchanged"
    assert dump(ready[0]) == after and len(ready[2]) == 1


def test_new_report_blocks_pending_ai_and_staged_result_without_overwrite(ready, monkeypatch):
    pending = job(ready)
    staged_job = job(ready)
    completed = staged_job.generate()
    staged = publication.prepare(completed)
    complete = llm.complete_result

    def different(*args, **kwargs):
        result = complete(*args, **kwargs)
        body = json.loads(result.text)
        body["sections"][0]["statements"][0]["text"] = "A newer research interpretation."
        return replace(result, text=json.dumps(body))

    monkeypatch.setattr(llm, "complete_result", different)
    newer = job(ready).generate()
    publication.publish(publication.prepare(newer))
    before = dump(ready[0])
    calls = len(ready[2])
    with pytest.raises(ValueError, match="changed before AI"):
        pending.generate()
    assert len(ready[2]) == calls
    with pytest.raises(ValueError, match="changed"):
        publication.publish(staged)
    assert dump(ready[0]) == before
    assert survey_reader.read(ready[0], "cat").data["report"] == newer.report


def test_explicit_replacement_keeps_history_and_proof_intent_cannot_be_changed(ready):
    first = job(ready).generate()
    old = publication.prepare(first)
    publication.publish(old)
    llm.save_settings(profile="selected", model="next-model")
    second = job(ready, force=True).generate()
    keep = publication.prepare(second)
    before = dump(ready[0])
    assert publication.publish(keep)["state"] == "preserved"
    assert dump(ready[0]) == before
    with pytest.raises(ValueError, match="proof"):
        publication.publish(replace(keep, replace=True))
    accepted = publication.prepare(second, replace=True)
    assert publication.publish(accepted)["state"] == "generated"
    assert survey_reader.read(ready[0], "cat").data["report"] == second.report
    with closing(generation._connect(ready[0])) as conn:
        rows = list(conn.execute("SELECT * FROM research_local_surveys"))
    assert len(rows) == 2 and sum(r["is_current"] for r in rows) == 1
    with pytest.raises(ValueError, match="changed"):
        publication.publish(old)
    assert survey_reader.read(ready[0], "cat").data["report"] == second.report


@pytest.mark.parametrize("mode", ["failure", "cancel"])
def test_late_failure_or_cancel_rolls_back_report_and_grants_then_retries_once(
    ready,
    monkeypatch,
    mode,
):
    staged = publication.prepare(job(ready).generate())
    before = dump(ready[0])
    real = survey_local.publish_in
    cancelled = False

    def interrupt(*args, **kwargs):
        nonlocal cancelled
        result = real(*args, **kwargs)
        if mode == "failure":
            raise OSError("fixture after local report write")
        cancelled = True
        return result

    monkeypatch.setattr(survey_local, "publish_in", interrupt)
    with pytest.raises((OSError, ValueError)):
        publication.publish(staged, cancelled=lambda: cancelled)
    assert dump(ready[0]) == before
    cancelled = False
    monkeypatch.setattr(survey_local, "publish_in", real)
    assert publication.publish(staged)["state"] == "generated"
    assert publication.publish(staged)["state"] == "unchanged"
    assert len(ready[2]) == 1


def test_corrupt_staged_original_or_cancelled_prepare_creates_no_report(ready):
    proposal = job(ready).generate()
    before = dump(ready[0])
    with pytest.raises(ValueError, match="cancelled"):
        publication.prepare(proposal, cancelled=lambda: True)
    staged = publication.prepare(proposal)
    from pathlib import Path

    Path(staged.staged._files[0][2]).write_bytes(b"corrupt fixture")
    with pytest.raises(ValueError, match="changed"):
        publication.publish(staged)
    assert dump(ready[0]) == before


def test_no_selected_originals_stays_explicit_and_exports_without_grants(ready):
    current = job(ready, selected_ids=[])
    response = {
        "sections": [
            {
                "heading": "Missing evidence",
                "statements": [
                    {
                        "text": "No selected original supports this survey.",
                        "interpretation": "inference",
                        "passages": [],
                    }
                ],
            }
        ]
    }
    from unittest.mock import patch

    from paper_daily.ai_types import Completion

    with patch.object(llm, "complete_result", return_value=Completion(json.dumps(response))):
        proposal = current.generate()
    publication.publish(publication.prepare(proposal))
    saved = survey_reader.read(ready[0], "cat")
    assert {source["state"] for source in saved.data["report"]["sources"]} == {"not_selected"}
    exported = survey_local.collect(ready[0], "cat")
    assert len(exported.files) == 1
    with closing(generation._connect(ready[0])) as conn:
        body = survey_local.validate_record(survey_local.current_in(conn, "cat"))
    assert body["bindings"] == []


def test_switching_global_workspace_does_not_retarget_pending_publication(ready, monkeypatch):
    import sqlite3

    from paper_daily import store

    staged = publication.prepare(job(ready).generate())
    other = ready[0].parent / "other-workspace.sqlite"
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE marker(value TEXT)")
        conn.execute("INSERT INTO marker VALUES('independent workspace')")
    before = other.read_bytes()
    monkeypatch.setattr(store, "DB_PATH", other)
    assert publication.publish(staged)["state"] == "generated"
    assert other.read_bytes() == before
    assert survey_reader.read(ready[0], "cat").data["report"] == staged.proposal.report
