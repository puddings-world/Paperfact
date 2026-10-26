"""Actual dive/context producers and manual entrypoints publish against loaded inputs."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
from types import SimpleNamespace

import pytest
from test_research_generation import BODY, pdf, rows
from test_research_generation import workspace as workspace

from paper_daily import cli, dive, followups, llm, store
from paper_daily import research_generation as generation
from paper_daily.sync_capture import StaleCaptureError, suppress_capture


def seed_context(path):
    with closing(generation._connect(path)) as conn, conn, suppress_capture(conn):
        conn.execute(
            "INSERT INTO cites(paper_id,ref_key,title,verdict,purpose,written_at) "
            "VALUES('paper','1','Prior experiment',?,'Baseline',?)",
            (followups.VERDICTS[0], store.now()),
        )


def receipt(path, table):
    records = rows(path, "SELECT * FROM research_generation_requests")
    return [r for r in records if json.loads(r["context_json"])["table"] == table]


def test_dive_actual_generation_publishes_before_count_and_retries_without_ai(
    workspace, monkeypatch
):
    path, client, document = workspace
    monkeypatch.setattr(dive, "_prepare_highlights", lambda *_: None)
    calls = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (calls.append(k) or BODY, "ok"))
    assert dive.dive_ahead(paper_id="paper") == 1
    assert rows(path, "SELECT body FROM dives")[0]["body"] == BODY
    saved = receipt(path, "dives")[0]
    context = json.loads(saved["context_json"])
    assert context["document"]["sha256"] == document.sha256
    assert context["target"] is None
    assert generation.retry_publication(path, saved["request_id"]).status == "accepted"
    assert len(calls) == 1
    if client:
        with client.journal.transaction() as conn:
            operations = [
                json.loads(r[0])
                for r in conn.execute("SELECT envelope FROM paperfact_sync_operations")
            ]
        assert any(op["payload"].get("feature") == "dive" for op in operations)


@pytest.mark.parametrize("change", ["manual", "metadata", "pdf", "owner"])
def test_dive_stale_output_is_retained_not_counted(workspace, monkeypatch, change):
    path, _client, document = workspace
    monkeypatch.setattr(
        dive, "_prepare_highlights", lambda *_: pytest.fail("candidate is not success")
    )

    def complete(*args, **kwargs):
        if change == "manual":
            dive.save("paper", "User explanation")
        elif change == "pdf":
            document.path.unlink()
            pdf(document.path, "Different input")
        else:
            with closing(generation._connect(path)) as conn, conn, suppress_capture(conn):
                conn.execute(
                    "UPDATE papers SET title='Changed' WHERE id='paper'"
                    if change == "metadata"
                    else "DELETE FROM papers WHERE id='paper'"
                )
        return BODY, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert dive.dive_ahead(paper_id="paper") == 0
    saved = rows(path, "SELECT body FROM dives")
    assert saved == ([{"body": "User explanation"}] if change == "manual" else [])
    retained = [r for r in receipt(path, "dives") if r["status"] == "candidate"]
    assert len(retained) == 1 and json.loads(retained[0]["row_json"])["body"] == BODY


def test_dive_workspace_switch_keeps_original_destination(workspace, monkeypatch, tmp_path):
    path, _client, _document = workspace
    replacement = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(replacement)) as conn:
        conn.executescript(store.SCHEMA)

    def complete(*args, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", replacement)
        return BODY, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(dive, "_prepare_highlights", lambda *_: pytest.fail("wrong workspace"))
    assert dive.dive_ahead(paper_id="paper") == 1
    assert rows(path, "SELECT body FROM dives") == [{"body": BODY}]
    assert rows(replacement, "SELECT * FROM dives") == []


def test_duplicate_dive_jobs_make_one_call_and_failed_job_can_retry(workspace, monkeypatch):
    path, _client, _document = workspace
    started, release = Event(), Event()
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        started.set()
        assert release.wait(10)
        return BODY, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(dive._generate_for, "paper")
        assert started.wait(10)
        try:
            body, reason = dive._generate_for("paper")
            assert body is None and "progress" in reason
        finally:
            release.set()
        assert running.result()[0] == BODY
    assert len(calls) == 1 and len(receipt(path, "dives")) == 1
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (None, "unavailable"))
    assert dive._generate_for("paper") == (None, "unavailable")
    assert len(receipt(path, "dives")) == 1


def test_direct_generate_and_manual_data_save_share_observation_boundary(workspace, monkeypatch):
    from paper_daily.desktop.main import Data

    path, _client, _document = workspace
    with closing(generation._connect(path)) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone()
        assert dive.generate(conn, row)[0] == BODY
    data = Data()
    expected = data.dive_for_edit("paper")
    data.save_dive("paper", "Another edit")
    with pytest.raises(StaleCaptureError):
        data.save_dive("paper", "Original editor draft", expected=expected)
    assert rows(path, "SELECT body FROM dives") == [{"body": "Another edit"}]
    stale = [r for r in receipt(path, "dives") if r["status"] == "candidate"]
    assert json.loads(stale[0]["row_json"])["body"] == "Original editor draft"


def test_cli_captures_target_before_blocking_input(workspace, monkeypatch, capsys):
    path, _client, _document = workspace

    class Input:
        def read(self):
            dive.save("paper", "Concurrent manual edit")
            return "External draft"

    monkeypatch.setattr(cli.sys, "stdin", Input())
    assert cli.cmd_set_dive(SimpleNamespace(paper_id="paper", file=None)) == 1
    assert "not replaced" in capsys.readouterr().out
    assert rows(path, "SELECT body FROM dives") == [{"body": "Concurrent manual edit"}]
    assert any(r["status"] == "candidate" for r in receipt(path, "dives"))


def test_overview_actual_first_generation_and_manual_edit(workspace, monkeypatch):
    path, _client, _document = workspace
    seed_context(path)
    answer = {
        "summary": "Field context",
        "reading": [{"title": "Prior experiment", "direction": "before", "why": "Baseline"}],
    }
    prompts = []
    monkeypatch.setattr(
        llm, "complete", lambda p, **k: (prompts.append(p) or json.dumps(answer), "ok")
    )
    assert followups.overview("paper")[0]
    saved = rows(path, "SELECT * FROM paper_context")[0]
    assert saved["summary"] == answer["summary"]
    assert json.loads(saved["reading_json"]) == answer["reading"]
    assert "Prior experiment" in prompts[0]
    assert receipt(path, "paper_context")[0]["status"] == "accepted"
    with closing(generation._connect(path)) as conn:
        expected = followups.overview_edit_snapshot(conn, "paper")
    followups.edit_overview("paper", "Hand edited", [], expected=expected)
    assert rows(path, "SELECT summary,edited FROM paper_context") == [
        {"summary": "Hand edited", "edited": 1}
    ]
    assert followups.overview("paper") == (False, "edited by hand")
    assert len(prompts) == 1


@pytest.mark.parametrize("change", ["edit", "input", "switch"])
def test_overview_stale_or_switched_completion_preserves_data(workspace, monkeypatch, change):
    path, _client, _document = workspace
    seed_context(path)
    other = path.with_name("other.db")
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)

    def complete(*args, **kwargs):
        if change == "edit":
            followups.edit_overview("paper", "Manual context", [])
        elif change == "switch":
            monkeypatch.setattr(store, "DB_PATH", other)
        else:
            with closing(generation._connect(path)) as conn, conn, suppress_capture(conn):
                conn.execute("UPDATE cites SET purpose='Changed baseline'")
        return json.dumps({"summary": "Generated context", "reading": []}), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    accepted, _reason = followups.overview("paper")
    assert accepted == (change == "switch")
    assert rows(other, "SELECT * FROM paper_context") == []
    expected = {
        "edit": [{"summary": "Manual context"}],
        "input": [],
        "switch": [{"summary": "Generated context"}],
    }[change]
    assert rows(path, "SELECT summary FROM paper_context") == expected
    if change != "switch":
        assert any(r["status"] == "candidate" for r in receipt(path, "paper_context"))


def test_overview_empty_missing_failure_and_invalid_result_do_not_publish(workspace, monkeypatch):
    path, _client, _document = workspace
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no input"))
    assert not followups.overview("missing")[0]
    assert not followups.overview("paper")[0]
    seed_context(path)
    for reply in (None, "invalid", '{"summary": {}, "reading": "invalid"}'):
        monkeypatch.setattr(llm, "complete", lambda *a, reply=reply, **k: (reply, "failure"))
        assert not followups.overview("paper")[0]
    assert rows(path, "SELECT * FROM paper_context") == []


def test_wrong_owner_context_and_transaction_failure_do_not_overwrite(workspace, monkeypatch):
    path, _client, _document = workspace
    with closing(generation._connect(path)) as conn:
        expected = followups.overview_edit_snapshot(conn, "paper")
    with pytest.raises(ValueError, match="another paper"):
        followups.edit_overview("other", "Bad target", [], expected=expected)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER reject_context BEFORE INSERT ON paper_context BEGIN "
            "SELECT RAISE(ABORT,'fixture storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        followups.edit_overview("paper", "Recoverable draft", [], expected=expected)
    assert rows(path, "SELECT * FROM paper_context") == []
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TRIGGER reject_context")
    followups.edit_overview("paper", "Recoverable draft", [], expected=expected)
    followups.edit_overview("paper", "Recoverable draft", [], expected=expected)
    assert len(receipt(path, "paper_context")) == 1


@pytest.mark.parametrize("feature", ["dive", "overview"])
def test_completed_model_output_survives_storage_failure(workspace, monkeypatch, feature):
    path, _client, _document = workspace
    table = "dives" if feature == "dive" else "paper_context"
    if feature == "overview":
        seed_context(path)
        monkeypatch.setattr(
            llm,
            "complete",
            lambda *a, **k: (
                json.dumps({"summary": "Generated retained context", "reading": []}),
                "ok",
            ),
        )
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            f"CREATE TRIGGER reject_output BEFORE INSERT ON {table} BEGIN "
            "SELECT RAISE(ABORT,'fixture storage failure'); END"
        )
    result = dive._generate_for("paper") if feature == "dive" else followups.overview("paper")
    assert not result[0] and "retained" in result[1]
    assert rows(path, f"SELECT * FROM {table}") == []
    candidates = generation.list_recovery_requests(path)
    assert len(candidates) == 1 and candidates[0]["status"] == "candidate"
    data = json.loads(candidates[0]["row_json"])
    assert (
        data["body"] == BODY
        if feature == "dive"
        else data["summary"] == "Generated retained context"
    )
    captured = generation.GenerationContext(candidates[0]["context_json"])
    assert generation.retry_publication(captured).candidate_id == candidates[0]["candidate_id"]


def test_overview_duplicate_job_rejected_before_another_model_call(workspace, monkeypatch):
    path, _client, _document = workspace
    seed_context(path)
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        assert followups.overview("paper") == (False, "overview is already in progress")
        return json.dumps({"summary": "Field context", "reading": []}), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert followups.overview("paper")[0]
    assert len(calls) == 1 and len(receipt(path, "paper_context")) == 1


def test_overview_bounds_are_checked_before_model_call(workspace, monkeypatch):
    path, _client, _document = workspace
    seed_context(path)
    with (
        closing(generation._connect(path)) as conn,
        pytest.raises(ValueError, match="record limit"),
    ):
        followups.overview_inputs(conn, "paper", limit=0)


@pytest.mark.parametrize("workspace", [True], indirect=True)
def test_enrolled_outputs_roundtrip_to_empty_peer(workspace, monkeypatch, tmp_path):
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import prepare, research_writer
    from paper_daily.sync_service import ReferenceService

    path, client, _document = workspace
    assert client is not None
    assert dive._generate_for("paper")[0] == BODY
    seed_context(path)
    monkeypatch.setattr(
        llm,
        "complete",
        lambda *a, **k: (json.dumps({"summary": "Portable overview", "reading": []}), "ok"),
    )
    assert followups.overview("paper")[0]
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "device")
    for operation in client.journal.pending():
        service.push(token, operation)
    peer_path = tmp_path / "peer.sqlite"
    with closing(sqlite3.connect(peer_path)) as conn:
        conn.executescript(store.SCHEMA)
    prepare(peer_path, workspace_id="workspace", device_id="peer")
    peer = SyncClient(
        Journal(peer_path, workspace_id="workspace", device_id="peer"), research_writer
    )
    peer.receive(service.pull(service.enroll("workspace", "peer")))
    assert rows(peer_path, "SELECT body FROM dives") == [{"body": BODY}]
    assert rows(peer_path, "SELECT summary FROM paper_context") == [
        {"summary": "Portable overview"}
    ]


@pytest.mark.parametrize("feature", ["dive", "overview"])
def test_producer_keeps_account_model_selected_before_input_loading(
    workspace, monkeypatch, feature
):
    path, _client, _document = workspace
    if feature == "overview":
        seed_context(path)
    selection = [SimpleNamespace(account_id="original", model="first")]
    monkeypatch.setattr(llm, "settings", lambda **kwargs: selection[0])
    original_begin = generation.begin_generation

    def begin(*args, **kwargs):
        context = original_begin(*args, **kwargs)
        selection[0] = SimpleNamespace(account_id="other", model="second")
        return context

    monkeypatch.setattr(generation, "begin_generation", begin)

    def complete(*args, cfg, **kwargs):
        assert (cfg.account_id, cfg.model) == ("original", "first")
        return (
            BODY
            if feature == "dive"
            else json.dumps({"summary": "Captured connection", "reading": []})
        ), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert dive._generate_for("paper")[0] if feature == "dive" else followups.overview("paper")[0]


@pytest.mark.parametrize("reply", [None, "too short"])
def test_unsuccessful_dive_does_not_make_a_receipt(workspace, monkeypatch, reply):
    path, _client, _document = workspace
    monkeypatch.setattr(llm, "complete", lambda *args, **kwargs: (reply, "unavailable"))
    assert dive._generate_for("paper")[0] is None
    assert rows(path, "SELECT * FROM dives") == []
    assert (
        rows(path, "SELECT name FROM sqlite_master WHERE name='research_generation_requests'") == []
    )


def test_dive_selection_to_worker_handoff_keeps_original_workspace(workspace, monkeypatch):
    path, _client, _document = workspace
    other = path.with_name("selection-other.sqlite")
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    original_select = dive._select

    def select(*args, **kwargs):
        selected = original_select(*args, **kwargs)
        monkeypatch.setattr(store, "DB_PATH", other)
        return selected

    monkeypatch.setattr(dive, "_select", select)
    assert dive.dive_ahead(paper_id="paper", jobs=2) == 1
    assert rows(path, "SELECT body FROM dives") == [{"body": BODY}]
    assert rows(other, "SELECT * FROM dives") == []
