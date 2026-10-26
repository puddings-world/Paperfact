"""Existing close-reading and survey producers adopt durable shared publication."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_generation import BODY, rows
from test_research_generation import workspace as workspace

from paper_daily import brief, closeread, llm, store, survey
from paper_daily import research_generation as generation
from paper_daily.sync_capture import StaleCaptureError


def seed_list():
    with store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('list','List','',?)", (store.now(),))
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('list','paper',0,?)",
            (store.now(),),
        )


@pytest.mark.parametrize("feature", ["close_reading", "survey"])
def test_completed_output_survives_actual_sql_failure_and_retry(workspace, monkeypatch, feature):
    path, _client, _document = workspace
    if feature == "survey":
        seed_list()
    table = "list_surveys" if feature == "survey" else "close_readings"
    calls = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (calls.append(1) or BODY, "ok"))
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            f"CREATE TRIGGER reject_generated BEFORE INSERT ON {table} BEGIN "
            "SELECT RAISE(ABORT,'simulated disk error'); END"
        )
    result = survey.write("list") if feature == "survey" else closeread.write("paper")
    assert not result[0] and "retained" in result[1]
    assert rows(path, f"SELECT * FROM {table}") == []
    records = generation.list_recovery_requests(path)
    assert len(records) == 1
    record = records[0]
    assert json.loads(record["row_json"])["body"] == BODY
    context = generation.GenerationContext(record["context_json"])
    for _ in range(2):
        outcome = generation.retry_publication(context)
        assert outcome.status == "candidate" and outcome.candidate_id == record["candidate_id"]
    assert len(calls) == 1


def test_survey_changed_stale_draft_retains_each_variant_once(workspace):
    path, _client, _document = workspace
    seed_list()
    assert survey.write("list")[0]
    with store.connect() as conn:
        expected = survey.edit_snapshot(conn, "list")
    survey.edit("list", "Newer manual survey")
    candidates = {}
    for body in (
        "First stale draft",
        "Second stale draft",
        "First stale draft",
        "Second stale draft",
    ):
        with pytest.raises(StaleCaptureError) as error:
            survey.edit("list", body, expected=expected)
        assert candidates.setdefault(body, error.value.candidate_id) == error.value.candidate_id
    assert len(set(candidates.values())) == 2
    assert rows(path, "SELECT body FROM list_surveys") == [{"body": "Newer manual survey"}]
    saved = rows(path, "SELECT row_json FROM research_generation_requests WHERE status='candidate'")
    assert sorted(json.loads(row["row_json"])["body"] for row in saved) == sorted(candidates)


@pytest.mark.parametrize("feature", ["close_reading", "survey"])
def test_account_and_model_are_frozen_before_preparing_inputs(workspace, monkeypatch, feature):
    path, _client, _document = workspace
    if feature == "survey":
        seed_list()
    monkeypatch.setattr(llm, "SETTINGS_PATH", path.with_name("fixture-models.json"))
    llm.save_settings(
        backend="codex", model="before", account_id="11111111111111111111111111111111"
    )

    def switch():
        llm.save_settings(
            backend="codex", model="after", account_id="22222222222222222222222222222222"
        )

    if feature == "close_reading":
        original = brief.pack_text

        def prepare(*args):
            result = original(*args)
            switch()
            return result

        monkeypatch.setattr(brief, "pack_text", prepare)
    else:
        original = survey.build_input_from_snapshot

        def prepare(*args):
            result = original(*args)
            switch()
            return result

        monkeypatch.setattr(survey, "build_input_from_snapshot", prepare)
    calls = []

    def complete(prompt, *, task, **kwargs):
        selected = llm.settings(task=task)
        calls.append((selected.account_id, selected.model))
        return BODY, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    result = survey.write("list") if feature == "survey" else closeread.write("paper")
    assert result[0]
    assert calls == [("11111111111111111111111111111111", "before")]
    assert (llm.settings().account_id, llm.settings().model) == (
        "22222222222222222222222222222222",
        "after",
    )


def test_close_reading_batch_uses_original_workspace_and_account(workspace, monkeypatch):
    path, _client, _document = workspace
    other = path.with_name("other.sqlite")
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    original = brief.pack_text

    def prepare(*args):
        result = original(*args)
        monkeypatch.setattr(store, "DB_PATH", other)
        return result

    monkeypatch.setattr(brief, "pack_text", prepare)
    assert closeread.write_many(["paper"], jobs=2, log=lambda *_: None) == 1
    assert rows(path, "SELECT body FROM close_readings") == [{"body": BODY}]
    assert rows(other, "SELECT * FROM close_readings") == []
