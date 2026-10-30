"""Maintenance behavior uses fixture accounts and isolated SQLite only."""

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_research_generation import workspace as workspace

from paper_daily import ai_providers, analysis_schedule, cites, cli, dive, llm, store
from paper_daily.ai_types import Settings
from paper_daily.desktop import ui_state


@pytest.mark.parametrize(
    ("stdout", "kind"),
    [
        ("API Error: 400 request violates usage policy private-paper", "policy"),
        ("Error: rate limit reached private-token", "limit"),
        ("Execution error: authentication failed private-email@example.test", "auth"),
        ("API Error: private diagnostic and sk-private-key", "error"),
    ],
)
def test_zero_exit_cli_failure_is_not_an_answer_or_success_receipt(
    tmp_path, monkeypatch, stdout, kind
):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(ai_providers.shutil, "which", lambda _: "fixture-claude")
    monkeypatch.setattr(
        ai_providers.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr="private stderr and token",
        ),
    )
    result = llm.complete_result("private-question", cfg=Settings("cli"), task="ask")
    assert result.text is None and llm.failure_kind(result.reason) == kind
    assert "private" not in result.reason
    raw = (tmp_path / "ai-usage.jsonl").read_text(encoding="utf-8")
    row = json.loads(raw)
    assert row["success"] is False and row["failure"] == kind
    assert "private" not in raw and "sk-" not in raw


@pytest.mark.parametrize(
    "answer", ["An API Error may occur in this method.", "Policy and quota are research topics."]
)
def test_regular_answer_is_not_rejected_for_mentioning_error_words(tmp_path, monkeypatch, answer):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(ai_providers.shutil, "which", lambda _: "fixture-claude")
    monkeypatch.setattr(
        ai_providers.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=answer,
            stderr="",
        ),
    )
    result = llm.complete_result("question", cfg=Settings("cli"), task="ask")
    assert result.text == answer
    row = json.loads((tmp_path / "ai-usage.jsonl").read_text(encoding="utf-8"))
    assert row["success"] is True and row["failure"] is None


@pytest.mark.parametrize("command", ["dive-ahead", "cites-ahead"])
@pytest.mark.parametrize(
    ("every", "queue", "lists", "expected"),
    [
        (0, 4, 3, False),
        (1, 0, 0, False),
        (1, 2, 0, True),
        (7, 0, 2, True),
    ],
)
def test_nightly_rewrites_obey_manual_only_while_manual_calls_remain_available(
    tmp_path,
    monkeypatch,
    command,
    every,
    queue,
    lists,
    expected,
):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        analysis_schedule.save(conn, dict(every=every, queue=queue, lists=lists, notify=False))
    calls = []
    monkeypatch.setattr(dive, "dive_ahead", lambda **kw: calls.append(kw) or 1)
    monkeypatch.setattr(cites, "analyse_ahead", lambda **kw: calls.append(kw) or 1)
    assert cli.main([command, "2", "--rewrite", "--scheduled"]) == 0
    assert len(calls) == int(expected)
    assert cli.main([command, "2", "--rewrite"]) == 0
    assert len(calls) == int(expected) + 1
    assert all(call["rewrite"] for call in calls)


def test_registered_nightly_rewrite_commands_use_scheduled_gates():
    text = (Path(__file__).parents[1] / "scripts/nightly.ps1").read_text(encoding="utf-8")
    commands = [line for line in text.splitlines() if line.startswith("& $py")]
    rewrites = [line for line in commands if "cites-ahead" in line or "dive-ahead" in line]
    assert len(rewrites) == 2 and all("--scheduled" in line for line in rewrites)


def test_close_flush_cannot_be_overwritten_by_an_older_worker_snapshot(tmp_path, monkeypatch):
    ui_state.flush()
    database = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    store.init_db()
    original = store.connect
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    errors = []

    @contextmanager
    def paused(**kwargs):
        if (
            kwargs.get("path") == database
            and threading.current_thread().name == "ui-state"
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(5)
        with original(**kwargs) as conn:
            yield conn

    monkeypatch.setattr(store, "connect", paused)
    ui_state.save("ui.regression", "old")
    assert entered.wait(5)
    ui_state.save("ui.regression", "latest")

    def flush():
        try:
            assert ui_state.flush()
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=flush)
    worker.start()
    try:
        assert not finished.wait(0.05)
    finally:
        release.set()
        worker.join(5)
    assert finished.is_set() and not errors
    assert ui_state.flush()
    with original() as conn:
        assert store.get_kv(conn, "ui.regression") == "latest"


@pytest.mark.parametrize("backend", ["codex", "gemini"])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_other_cli_errors_never_become_answers(tmp_path, monkeypatch, backend, exit_code):
    from paper_daily import ai_accounts, gemini_cli

    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(ai_accounts, "command", lambda name: ["fixture-" + name])
    monkeypatch.setattr(gemini_cli, "status", lambda cfg: ("fixture", "ok"))

    def run(argv, **kwargs):
        error = "API Error: rate limit reached private-account"
        if backend == "codex" and not exit_code:
            Path(argv[argv.index("--output-last-message") + 1]).write_text(error, encoding="utf-8")
        return SimpleNamespace(
            returncode=exit_code,
            stdout=json.dumps({"response": error}) if backend == "gemini" else error,
            stderr="usage limit private-token",
        )

    monkeypatch.setattr(ai_providers.subprocess, "run", run)
    result = llm.complete_result("private question", cfg=Settings(backend), task="ask")
    assert result.text is None and llm.failure_kind(result.reason) == "limit"
    assert "private" not in result.reason


def test_ui_state_flush_never_creates_shared_research_operations(workspace):
    path, client, _doc = workspace
    before = client.journal.pending() if client else None
    ui_state.save("ui.maintenance", "saved")
    assert ui_state.flush()
    with store.connect(path=path) as conn:
        assert store.get_kv(conn, "ui.maintenance") == "saved"
    if client:
        assert client.journal.pending() == before


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("違反使用政策", "policy"),
        ("用量已達上限", "limit"),
        ("登入失效", "auth"),
        ("請求逾時", "timeout"),
    ],
)
def test_chinese_failure_reasons_have_the_same_content_free_categories(reason, expected):
    assert llm.failure_kind(reason) == expected
