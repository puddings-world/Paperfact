"""Lineage uses the same explicit, account-isolated task routing as other jobs."""

import json

import pytest
from test_ai_profiles import clean as clean
from test_ai_tasks import choose
from test_ai_tasks import setup as setup
from test_lineage_jobs import work
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import ai_profiles, llm
from paper_daily.ai_types import Completion
from paper_daily.desktop.ai_tasks import AITasksDialog
from paper_daily.lineage_jobs import LineageJob


def test_lineage_public_task_choice_preserves_global_and_other_task_choices(clean):
    llm.save_settings(profile="default", backend="openai", model="global", max_tokens=6000)
    llm.save_settings(profile="other", backend="openai", model="account-model", max_tokens=6000)
    llm.save_task_choices({"lineage": (llm.settings(profile="other"), "exact-lineage-model")})
    assert llm.settings("lineage").model == "exact-lineage-model"
    assert llm.settings("ask").model == llm.settings().model == "global"
    assert llm.settings(profile="other").model == "account-model"
    llm.clear_route("lineage")
    assert llm.settings("lineage").model == "global"


def test_lineage_task_row_saves_reopens_and_cancels_without_generation(setup, monkeypatch):
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No generation"))
    before = ai_profiles.load(llm.SETTINGS_PATH)["profiles"]
    widget = AITasksDialog()
    assert "lineage" in widget.rows
    choose(widget, "lineage", "codex", "large")
    widget._save()
    assert llm.settings("lineage").model == "large"
    assert llm.settings("lineage").account_id == "b" * 32
    assert llm.settings().model == "usual"
    assert ai_profiles.load(llm.SETTINGS_PATH)["profiles"] == before
    reopened = AITasksDialog()
    assert reopened.rows["lineage"][1].currentText() == "large"
    saved = llm.SETTINGS_PATH.read_bytes()
    choose(reopened, "lineage", "cli", "small")
    reopened.reject()
    assert llm.SETTINGS_PATH.read_bytes() == saved


def test_actual_lineage_job_keeps_admitted_model_after_route_changes(clean, corpus, monkeypatch):
    llm.save_settings(profile="default", backend="openai", model="global", max_tokens=6000)
    llm.save_settings(profile="other", backend="openai", model="account-model", max_tokens=6000)
    llm.save_task_choices({"lineage": (llm.settings(profile="other"), "admitted-model")})
    captured = llm.freeze_connections(("lineage",))
    job = work(LineageJob.prepare, corpus[2], connections=captured)
    llm.save_task_choices({"lineage": (llm.settings(profile="default"), "next-model")})
    calls = []

    def complete(_prompt, **options):
        calls.append(options["cfg"])
        assert llm.settings("lineage").model == "admitted-model"
        return Completion(json.dumps(proposals(corpus[2])), model="returned-model")

    monkeypatch.setattr(llm, "complete_result", complete)
    result = work(job.run)
    assert len(calls) == 1 and calls[0].profile == "other"
    assert result.execution["requested_model"] == "admitted-model"
    assert result.execution["returned_model"] == "returned-model"
    assert llm.settings("lineage").model == "next-model"
