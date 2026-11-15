"""Fake-model survey jobs keep captured routes, sources and publication separate."""

import json
from contextlib import closing

import pymupdf
import pytest
from test_survey import conn as conn
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import llm, store, survey_jobs, survey_publication, survey_reader, survey_sources
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion

QUOTE = "A selected method improves measurement."


@pytest.fixture
def ready(conn, tmp_path, monkeypatch):
    root = tmp_path / "pdf"
    root.mkdir()
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), QUOTE)
        (root / "a.pdf").write_bytes(pdf.tobytes())
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.save_settings(
        profile="selected",
        backend="openai",
        model="original-model",
        api_key="synthetic-key",
        isolated=True,
    )
    llm.use_profile("selected", desktop=True)
    calls = []

    def complete(prompt, **kwargs):
        data = json.loads(prompt)
        calls.append((data, kwargs))
        captured = next(s for s in data["sources"] if s["state"] == "captured")
        return Completion(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": "Research evidence",
                            "statements": [
                                {
                                    "text": "The reported improvement needs review.",
                                    "interpretation": "reported",
                                    "passages": [
                                        {
                                            "source_id": captured["id"],
                                            "quote": QUOTE,
                                            "page": 1,
                                            "anchor": None,
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
            model="provider-returned-model",
        )

    monkeypatch.setattr(llm, "complete_result", complete)
    return store.DB_PATH, root, calls


def capture(ready, **kwargs):
    return survey_jobs.SurveyJob.capture(ready[0], "cat", legacy_root=ready[1], **kwargs)


def test_original_pages_captured_route_verified_quotes_and_retry_without_canonical_write(
    ready,
):
    job = capture(ready)
    llm.save_settings(profile="selected", model="later-model", api_key="later-key")
    with closing(generation._connect(ready[0])) as conn:
        before = list(conn.execute("SELECT * FROM list_surveys"))
    result = job.generate()
    assert job.generate() is result and len(ready[2]) == 1
    data, kwargs = ready[2][0]
    assert data["inputs"] == job.corpus.inputs
    assert QUOTE in data["original_pages"][0]["pages"][0]["text"]
    assert {s["state"] for s in data["sources"]} == {"captured", "unavailable"}
    assert kwargs["cfg"].model == "original-model" and kwargs["cfg"].api_key == "synthetic-key"
    assert kwargs["task"] == "survey"
    assert job.selection == {"backend": "openai", "account_id": None, "model": "original-model"}
    assert result.report["generation"] == dict(
        task="survey",
        backend="openai",
        requested_model="original-model",
        returned_model="provider-returned-model",
    )
    statement = result.report["sections"][0]["statements"][0]
    assert statement["passages"][0]["location"]["state"] == "located"
    assert result.report["semantic_validation"] == "not_performed"
    assert "synthetic-key" not in json.dumps(result.report)
    assert "synthetic-key" not in repr(job)
    with closing(generation._connect(ready[0])) as conn:
        assert list(conn.execute("SELECT * FROM list_surveys")) == before


def test_duplicate_activation_and_failed_provider_release_lock_for_retry(ready, monkeypatch):
    job = capture(ready)
    other = capture(ready)
    complete = llm.complete_result

    def running(*args, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            other.generate()
        return Completion(None, "fixture unavailable")

    monkeypatch.setattr(llm, "complete_result", running)
    with pytest.raises(ValueError, match="fixture unavailable"):
        job.generate()
    monkeypatch.setattr(llm, "complete_result", complete)
    assert job.generate().report["sections"] and len(ready[2]) == 1


def test_cancellation_before_ai_and_after_response_retry_reuses_checked_output(ready, monkeypatch):
    job = capture(ready)
    with pytest.raises(ValueError, match="cancelled"):
        job.generate(cancelled=lambda: True)
    assert not ready[2]
    cancelled = False
    complete = llm.complete_result

    def finish(*args, **kwargs):
        nonlocal cancelled
        result = complete(*args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(llm, "complete_result", finish)
    with pytest.raises(ValueError, match="cancelled"):
        job.generate(cancelled=lambda: cancelled)
    assert len(ready[2]) == 1
    cancelled = False
    assert job.generate().report["sections"] and len(ready[2]) == 1


def test_input_change_before_ai_refuses_and_change_during_ai_keeps_captured_proposal(
    ready,
    monkeypatch,
):
    job = capture(ready)
    with closing(generation._connect(ready[0])) as conn, conn:
        conn.execute("UPDATE lists SET name='A newer name' WHERE id='cat'")
    with pytest.raises(ValueError, match="changed before AI"):
        job.generate()
    assert not ready[2]
    current = capture(ready)
    complete = llm.complete_result

    def change(*args, **kwargs):
        result = complete(*args, **kwargs)
        with closing(generation._connect(ready[0])) as conn, conn:
            conn.execute("UPDATE lists SET name='Changed while running' WHERE id='cat'")
        return result

    monkeypatch.setattr(llm, "complete_result", change)
    proposal = current.generate()
    assert proposal.report["inputs"]["list_name"] == "A newer name"
    assert not survey_sources.current(proposal._capture)
    assert current.generate() is proposal and len(ready[2]) == 1


def test_closed_response_contract_refuses_invented_verification_and_bad_json(ready, monkeypatch):
    valid = capture(ready).generate().report
    source_id = next(s["id"] for s in valid["sources"] if s["state"] == "captured")
    malformed = [
        '{"sections":[],"sections":[]}',
        "[]",
        '{"sections":[]}',
        "not JSON",
        '{"sections":[],"verified":true}',
        " " * (survey_jobs.MAX_RESPONSE_BYTES + 1),
        json.dumps(
            {
                "sections": [
                    {
                        "heading": "Claim",
                        "statements": [
                            {
                                "text": "Invented verification",
                                "interpretation": "reported",
                                "passages": [
                                    {
                                        "source_id": source_id,
                                        "quote": QUOTE,
                                        "page": 1,
                                        "anchor": None,
                                        "location": {"state": "located"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
    ]
    for response in malformed:
        monkeypatch.setattr(llm, "complete_result", lambda *a, text=response, **k: Completion(text))
        with pytest.raises(ValueError):
            capture(ready).generate()


def test_empty_edited_and_oversized_inputs_do_not_call_ai(ready, monkeypatch):
    with closing(generation._connect(ready[0])) as conn, conn:
        conn.execute(
            "INSERT INTO list_surveys VALUES('cat','Manual research',2,'fixture',?,1)",
            (store.now(),),
        )
    with pytest.raises(ValueError, match="explicit replacement"):
        capture(ready)
    assert capture(ready, force=True)
    monkeypatch.setattr(survey_jobs, "MAX_INPUT_BYTES", 1)
    with pytest.raises(ValueError, match="input exceeds"):
        capture(ready, force=True)
    with closing(generation._connect(ready[0])) as conn, conn:
        conn.execute("DELETE FROM list_surveys")
        conn.execute("DELETE FROM list_papers")
    with pytest.raises(ValueError):
        capture(ready)
    assert not ready[2]


def test_staging_interruption_reuses_one_model_response_and_rechecks_retained_bytes(
    ready,
    monkeypatch,
):
    job = capture(ready)
    retain = survey_sources.retain_originals
    calls = []

    def interrupted(*args, **kwargs):
        receipts = retain(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            raise OSError("fixture after retained original")
        return receipts

    monkeypatch.setattr(survey_sources, "retain_originals", interrupted)
    with pytest.raises(OSError, match="fixture"):
        job.generate()
    assert job.generate().report["sections"]
    assert len(ready[2]) == 1 and calls == [1, 1]


def test_native_generated_proposal_publishes_to_saved_reader_and_newer_report_refuses(
    prepared,
    monkeypatch,
):
    client, _, _, _, root, old_proposal = prepared
    monkeypatch.setattr(llm, "SETTINGS_PATH", root / "ai.json")
    llm.save_settings(
        profile="selected",
        backend="openai",
        model="native-model",
        api_key="synthetic-key",
        isolated=True,
    )
    llm.use_profile("selected", desktop=True)
    job = survey_jobs.SurveyJob.capture(client.journal.path, "list", legacy_root=root)
    source = job.corpus.sources[0]["id"]
    response = {
        "sections": [
            {
                "heading": "Generated evidence",
                "statements": [
                    {
                        "text": "A proposed interpretation.",
                        "interpretation": "synthesis",
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
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: Completion(json.dumps(response), model="actual")
    )
    generated = job.generate()
    survey_publication.publish(survey_publication.prepare(generated))
    saved = survey_reader.read(client.journal.path, "list")
    assert saved.data["report"] == generated.report
    assert survey_reader.inspect(saved, 0, 0, 0)["located"]
    with pytest.raises(ValueError, match="changed"):
        survey_publication.prepare(old_proposal)


def test_missing_originals_remain_explicit_and_unlocated_quotes_are_not_promoted(
    ready, monkeypatch
):
    job = capture(ready, selected_ids=[])
    assert {s["state"] for s in job.corpus.sources} == {"not_selected"}
    response = {
        "sections": [
            {
                "heading": "Evidence gaps",
                "statements": [
                    {
                        "text": "No selected originals support an empirical conclusion.",
                        "interpretation": "inference",
                        "passages": [],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: Completion(json.dumps(response)))
    report = job.generate().report
    assert report["sections"][0]["statements"][0]["passages"] == []
    assert report["generation"]["returned_model"] is None

    job = capture(ready)
    source = next(s for s in job.corpus.sources if s["state"] == "captured")
    response["sections"][0]["statements"][0]["passages"] = [
        {
            "source_id": source["id"],
            "quote": "A quotation absent from the original",
            "page": 1,
            "anchor": None,
        }
    ]
    report = job.generate().report
    location = report["sections"][0]["statements"][0]["passages"][0]["location"]
    assert location["state"] != "located"
    assert report["semantic_validation"] == "not_performed"


def test_completed_retry_refuses_corrupt_retained_original_without_recalling_ai(ready):
    from paper_daily import position_source_snapshots

    job = capture(ready)
    job.generate()
    path, _version = position_source_snapshots.verify(ready[0], job._receipts[0])
    path.write_bytes(b"corrupt fixture original")
    with pytest.raises(ValueError):
        job.generate()
    assert len(ready[2]) == 1


def test_source_cli_saves_readable_report_and_retains_exact_completed_result(
    ready, monkeypatch, capsys,
):
    from types import SimpleNamespace

    from paper_daily import cli, enrollment_history, survey_reader

    monkeypatch.setattr(cli, "PDF_DIR", ready[1])
    args = SimpleNamespace(
        list_id="cat", sources=True, force=False, source_paper=None, expected_report="none"
    )
    assert cli.cmd_survey(args) == 0
    saved = survey_reader.read(ready[0], "cat").data
    assert saved["kind"] == "local" and len(ready[2]) == 1
    args.expected_report = saved["report"]["id"]
    assert cli.cmd_survey(args) == 0 and len(ready[2]) == 1
    records = generation.list_recovery_requests(ready[0])
    assert len(records) == 1
    assert json.loads(records[0]["row_json"]) == saved["report"]
    assert survey_jobs.validate_retained(records[0]) == records[0]
    originals = survey_jobs.retained_originals(records[0])
    assert enrollment_history.generation_sources(records[0]) == {originals[0]["sha256"]}
    args.sources, args.expected_report = False, None
    args.retained = records[0]["request_id"]
    capsys.readouterr()
    assert cli.cmd_survey(args) == 0
    assert json.loads(capsys.readouterr().out) == saved["report"]
    args.force = True
    assert cli.cmd_survey(args) == 2 and len(ready[2]) == 1


def test_source_action_retains_changed_goal_result_without_overwriting_research(ready, monkeypatch):
    from paper_daily import reading_goals, survey_reader

    assert reading_goals.save(reading_goals.load(ready[0], "cat"), "Original goal")
    complete = llm.complete_result

    def change(*args, **kwargs):
        response = complete(*args, **kwargs)
        reading_goals.save(reading_goals.load(ready[0], "cat"), "A newer goal")
        return response

    monkeypatch.setattr(llm, "complete_result", change)
    outcome = survey_jobs.execute(ready[0], "cat", legacy_root=ready[1], expected_report="none")
    assert outcome["state"] == "retained"
    assert survey_reader.read(ready[0], "cat").data["kind"] == "none"
    (record,) = generation.list_recovery_requests(ready[0])
    assert record["request_id"] == outcome["request_id"]
    assert json.loads(record["row_json"])["inputs"]["goal"] == "Original goal"
    assert reading_goals.text(reading_goals.load(ready[0], "cat")) == "A newer goal"
    assert len(ready[2]) == 1


def test_source_action_duplicate_and_expected_target_guards_do_not_spend_twice(ready, monkeypatch):
    complete = llm.complete_result

    def running(*args, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            survey_jobs.execute(ready[0], "cat", legacy_root=ready[1])
        return complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", running)
    with pytest.raises(ValueError, match="selected report changed"):
        survey_jobs.execute(ready[0], "cat", legacy_root=ready[1], expected_report="f" * 64)
    assert not ready[2]
    assert survey_jobs.execute(ready[0], "cat", legacy_root=ready[1])["state"] == "saved"
    assert len(ready[2]) == 1


def test_completed_cancel_retains_readable_result_and_enrollment_history(ready, monkeypatch):
    from paper_daily.workspace_enrollment import EnrollmentService

    complete = llm.complete_result
    cancelled = False

    def finished(*args, **kwargs):
        nonlocal cancelled
        result = complete(*args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(llm, "complete_result", finished)
    result = survey_jobs.execute(ready[0], "cat", legacy_root=ready[1], cancelled=lambda: cancelled)
    assert result["state"] == "retained"
    report = survey_jobs.read_retained(ready[0], "cat", result["request_id"])
    assert report["id"] == result["report_id"] and len(ready[2]) == 1
    with pytest.raises(ValueError, match="No retained"):
        survey_jobs.read_retained(ready[0], "another-list", result["request_id"])
    plan = EnrollmentService(ready[0]).plan(pdfs={"a": ready[1] / "a.pdf"})
    assert plan["supported"], plan["blockers"]
