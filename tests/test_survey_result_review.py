"""Reviewed retained reports preserve goals, versions, originals and retry safety."""

import json
from contextlib import closing
from pathlib import Path

import pytest
from test_survey import conn as conn
from test_survey_jobs import ready as ready
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import llm, reading_goals, survey_jobs, survey_reader
from paper_daily import research_generation as generation
from paper_daily import survey_result_review as review
from paper_daily.ai_types import Completion


@pytest.fixture(params=["local", "native"])
def retained(request, monkeypatch, tmp_path):
    if request.param == "local":
        database, root, _calls = request.getfixturevalue("ready")
        list_id = "cat"
    else:
        client, _server, _token, _files, root, _old = request.getfixturevalue("prepared")
        database, list_id = client.journal.path, "list"
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "review-llm.json")
    llm.save_settings(
        profile="review",
        backend="openai",
        model="synthetic-review",
        api_key="synthetic-key",
        isolated=True,
    )
    llm.use_profile("review", desktop=True)
    calls, statement = [], ["A retained interpretation."]

    def complete(prompt, **_options):
        data = json.loads(prompt)
        calls.append(1)
        source = next(s for s in data["sources"] if s["state"] == "captured")
        return Completion(
            json.dumps(
                dict(
                    sections=[
                        dict(
                            heading="Historical report",
                            statements=[
                                dict(
                                    text=statement[0],
                                    interpretation="synthesis",
                                    passages=[
                                        dict(
                                            source_id=source["id"],
                                            quote="A selected method",
                                            page=1,
                                            anchor=None,
                                        )
                                    ],
                                )
                            ],
                        )
                    ]
                )
            ),
            model="synthetic-returned",
        )

    monkeypatch.setattr(llm, "complete_result", complete)

    def make(text):
        statement[0] = text
        job = survey_jobs.SurveyJob.capture(database, list_id, legacy_root=root, force=True)
        receipt = survey_jobs.retain(job, job.generate())
        return survey_reader.read_retained(database, list_id, receipt.request_id)

    reading_goals.save(reading_goals.load(database, list_id), "Historical goal")
    make("A retained interpretation.")
    reading_goals.save(reading_goals.load(database, list_id), "Current goal")
    record = survey_jobs.list_retained(database, list_id)[0]
    original = survey_reader.read_retained(database, list_id, record["request_id"])
    return database, list_id, original, calls, make


def snapshot(database):
    with closing(generation._connect(database)) as connection:
        return list(connection.iterdump())


def test_review_prepares_without_writes_then_applies_exact_report_and_retries(retained):
    database, list_id, original, calls, _make = retained
    before = snapshot(database)
    value = review.prepare(original)
    try:
        assert snapshot(database) == before and len(calls) == 1
        assert value.summary()["goal"] == "Historical goal"
        assert value.summary()["current_report_id"] is None
        assert review.apply(value)["state"] == "imported"
        saved = survey_reader.read(database, list_id)
        assert saved.data["report"] == original.data["report"]
        assert survey_reader.inspect(saved, 0, 0, 0)["located"]
        assert reading_goals.text(reading_goals.load(database, list_id)) == "Current goal"
        written = snapshot(database)
        assert review.apply(value)["state"] == "unchanged"
        assert snapshot(database) == written and len(calls) == 1
    finally:
        value.close()
    assert survey_reader.inspect(survey_reader.read(database, list_id), 0, 0, 0)["located"]


@pytest.mark.parametrize("change", ["target", "receipt", "cancel", "closed"])
def test_review_refuses_changed_or_cancelled_intent_without_research_writes(retained, change):
    database, list_id, original, calls, _make = retained
    value = review.prepare(original)
    try:
        if change == "target":
            with closing(generation._connect(database)) as connection, connection:
                connection.execute("UPDATE lists SET note='A later edit' WHERE id=?", (list_id,))
        elif change == "receipt":
            path = Path(value.files[1][0])
            path.write_bytes(path.read_bytes() + b" ")
        elif change == "closed":
            value.close()
        before = snapshot(database)
        with pytest.raises((ValueError, OSError)):
            review.apply(value, cancelled=lambda: change == "cancel")
        assert snapshot(database) == before and len(calls) == 1
        assert survey_reader.read(database, list_id).data["kind"] == "none"
    finally:
        value.close()


def test_old_review_retry_never_reactivates_a_report_after_a_newer_review(retained):
    database, list_id, original, calls, make = retained
    old = review.prepare(original)
    new = None
    try:
        review.apply(old)
        later = make("A newer reviewed interpretation.")
        new = review.prepare(later)
        review.apply(new)
        before = snapshot(database)
        with pytest.raises(ValueError):
            review.apply(old)
        assert snapshot(database) == before
        assert survey_reader.read(database, list_id).data["report"] == later.data["report"]
        assert len(calls) == 2
    finally:
        old.close()
        if new is not None:
            new.close()


def test_review_uses_logical_targets_and_preserves_unrelated_settings_changes(retained):
    database, list_id, original, calls, _make = retained
    with closing(generation._connect(database)) as connection, connection:
        connection.execute("INSERT INTO kv(key,value) VALUES('ui:review-fixture','before')")
    assert not original.current()
    value = review.prepare(original)
    try:
        with closing(generation._connect(database)) as connection, connection:
            connection.execute("UPDATE kv SET value='after' WHERE key='ui:review-fixture'")
        review.apply(value)
        assert survey_reader.read(database, list_id).data["report"] == original.data["report"]
        with closing(generation._connect(database)) as connection:
            row = connection.execute(
                "SELECT value FROM kv WHERE key='ui:review-fixture'"
            ).fetchone()
            assert row[0] == "after"
        assert len(calls) == 1
    finally:
        value.close()


def test_changed_archive_read_cannot_reuse_the_prepared_review_seal(retained):
    from dataclasses import replace

    database, _list_id, original, calls, _make = retained
    value = review.prepare(original)
    try:
        before = snapshot(database)
        changed = replace(value, original=replace(original, _json="{}"))
        with pytest.raises(ValueError, match="explicit prepared review"):
            review.apply(changed)
        assert snapshot(database) == before and len(calls) == 1
    finally:
        value.close()
