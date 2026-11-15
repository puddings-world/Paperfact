"""Surveys preserve captured research purpose without rewriting old goal provenance."""

import json
from contextlib import closing
from copy import deepcopy

import pytest
from test_survey import source_aware_survey as source_aware_survey
from test_survey_jobs import conn as conn
from test_survey_jobs import ready as ready
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import (
    llm,
    reading_goals,
    store,
    survey,
    survey_content,
    survey_jobs,
    survey_local,
    survey_local_generated,
    survey_publication,
    survey_reader,
)
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion, Settings
from paper_daily.desktop.survey_evidence import TEXT, render


def set_goal(database, list_id, text):
    outcome = reading_goals.save(reading_goals.load(database, list_id), text)
    assert outcome is None or outcome.status == "accepted"


def capture(ready):
    return survey_jobs.SurveyJob.capture(ready[0], "cat", legacy_root=ready[1])


def test_goal_reaches_both_survey_flows_and_saved_report_keeps_its_original_purpose(
    ready,
    monkeypatch,
):
    goal = "Compare measurement assumptions. <script>literal goal</script>"
    set_goal(ready[0], "cat", goal)
    job = capture(ready)
    proposal = job.generate()
    data = ready[2][0][0]
    assert data["inputs"]["goal"] == goal and goal in data["analysis_context"]
    assert proposal.report["recipe"] == survey_content.GOAL_RECIPE
    assert proposal.report["inputs"]["goal"] == goal
    survey_local_generated.publish(survey_local_generated.prepare(proposal))
    saved = survey_reader.read(ready[0], "cat")
    exported = survey_local.collect(ready[0], "cat")
    raw = next(data for path, data in exported.files if path.as_posix() == exported.record["path"])
    assert json.loads(raw)["report"]["inputs"]["goal"] == goal
    assert json.loads(raw)["report"] == proposal.report
    for language in ("en", "zh-TW"):
        html = render(saved.data, TEXT[language])
        assert "&lt;script&gt;literal goal&lt;/script&gt;" in html
        assert "<script>literal goal</script>" not in html

    calls = []

    def legacy(prompt, **kwargs):
        calls.append(prompt)
        return "## Research\n" + "A supported interpretation. " * 120, "ok"

    monkeypatch.setattr(llm, "complete", legacy)
    assert survey.write("cat")[0]
    assert len(calls) == 1 and goal in calls[0]
    set_goal(ready[0], "cat", "A different later goal")
    assert survey_reader.read(ready[0], "cat").data["report"]["inputs"]["goal"] == goal


def test_goal_absence_clear_and_metadata_changes_refuse_pending_inference(ready):
    job = capture(ready)
    assert job.corpus.inputs["goal"] is None
    set_goal(ready[0], "cat", "An intermediate question")
    set_goal(ready[0], "cat", "")
    with pytest.raises(ValueError, match="changed before AI"):
        job.generate()
    assert not ready[2]
    cleared = capture(ready)
    assert cleared.corpus.inputs["goal"] == ""
    with closing(generation._connect(ready[0])) as conn, conn:
        conn.execute(
            "UPDATE list_reading_goals SET written_at=? WHERE list_id='cat'", ("new-version",)
        )
    with pytest.raises(ValueError, match="changed before AI"):
        cleared.generate()
    assert not ready[2]


def test_goal_change_during_completion_preserves_proposal_and_refuses_local_publication(
    ready,
    monkeypatch,
):
    set_goal(ready[0], "cat", "Original question")
    job = capture(ready)
    complete = llm.complete_result

    def change(*args, **kwargs):
        response = complete(*args, **kwargs)
        set_goal(ready[0], "cat", "New question while working")
        return response

    monkeypatch.setattr(llm, "complete_result", change)
    proposal = job.generate()
    assert proposal.report["inputs"]["goal"] == "Original question"
    with pytest.raises(ValueError, match="changed"):
        survey_local_generated.prepare(proposal)
    assert reading_goals.text(reading_goals.load(ready[0], "cat")) == "New question while working"
    assert survey_reader.read(ready[0], "cat").data["kind"] == "none"
    assert len(ready[2]) == 1


def test_native_goal_change_refuses_completed_report_without_reverting_goal(prepared, monkeypatch):
    client, _, _, _, root, original = prepared
    database = client.journal.path
    set_goal(database, "list", "Original native question")
    monkeypatch.setattr(llm, "settings", lambda **kwargs: Settings("codex", model="fixture"))
    source = original._capture.sources[0]["id"]
    response = {
        "sections": [
            {
                "heading": "Goal-aware",
                "statements": [
                    {
                        "text": "An interpretation for this question.",
                        "interpretation": "inference",
                        "passages": [
                            {
                                "source_id": source,
                                "quote": "A selected method",
                                "page": 1,
                                "anchor": None,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    def complete(*args, **kwargs):
        set_goal(database, "list", "A later native question")
        return Completion(json.dumps(response))

    monkeypatch.setattr(llm, "complete_result", complete)
    proposal = survey_jobs.SurveyJob.capture(database, "list", legacy_root=root).generate()
    assert proposal.report["inputs"]["goal"] == "Original native question"
    with pytest.raises(ValueError, match="changed"):
        survey_publication.prepare(proposal)
    assert reading_goals.text(reading_goals.load(database, "list")) == "A later native question"


def test_goal_budgets_reject_bad_rows_before_ai_but_allow_unicode_limit(ready):
    with closing(generation._connect(ready[0])) as conn, conn:
        conn.execute("INSERT INTO list_reading_goals VALUES('cat',?,?)", ("x" * 2001, store.now()))
    with pytest.raises(ValueError, match="bounds"):
        capture(ready)
    assert not ready[2]
    set_goal(ready[0], "cat", "\U0001f9ea" * 2000)
    assert len(capture(ready).corpus.inputs["goal"]) == 2000


def test_legacy_unknown_goal_and_new_recipe_closed_fields_remain_distinct(source_aware_survey):
    report = source_aware_survey
    assert report["recipe"] == survey_content.RECIPE
    assert "goal" not in survey_content.decode(survey_content.encode(report))["inputs"]
    html = render(dict(report=report, sources=[]), TEXT["en"])
    assert TEXT["en"]["goal_unknown"] in html
    for goal in (None, "", "Compare methods", "\U0001f9ea" * 2000):
        body = deepcopy(report)
        body["recipe"] = survey_content.GOAL_RECIPE
        body["inputs"]["goal"] = goal
        body["id"] = survey_content.content.hashed({k: v for k, v in body.items() if k != "id"})
        assert survey_content.decode(survey_content.encode(body))["inputs"]["goal"] == goal
    for invalid in (42, [], {}, "x" * 2001):
        body = deepcopy(report)
        body["recipe"] = survey_content.GOAL_RECIPE
        body["inputs"]["goal"] = invalid
        body["id"] = survey_content.content.hashed({k: v for k, v in body.items() if k != "id"})
        with pytest.raises(ValueError):
            survey_content.validate(body)
    extra = deepcopy(report)
    extra["inputs"]["goal"] = "Cannot silently extend v1"
    extra["id"] = survey_content.content.hashed({k: v for k, v in extra.items() if k != "id"})
    with pytest.raises(ValueError):
        survey_content.validate(extra)
