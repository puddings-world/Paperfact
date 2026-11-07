"""Resolved job routes survive child bootstrap and nested pool workers."""
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from types import SimpleNamespace

import pytest

from paper_daily import integration_entry, llm, runtime
from paper_daily.ai_job_intent import FrozenRoutes, JobIntentError
from paper_daily.ai_types import Settings
from paper_daily.cli_job_protocol import encode_frame, hello_line, ready_line

REQUEST = "1" * 32
COMMAND = ("survey", "fixture-list", "--force")


def routes():
    return FrozenRoutes(
        Settings("none", model=None),
        {"survey": Settings("openai", model="fixture-model", api_key="synthetic-private-key",
                             isolated=True, max_tokens=4096, account_id="a" * 32,
                             cli_home="private-account-home")},
        account_directory="private-accounts",
    )


def test_resolved_factory_pins_only_declared_tasks_and_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.save_settings(profile="selected", backend="openai", model="before", isolated=True,
                      api_key="synthetic-one")
    llm.use_profile("selected", desktop=True)
    llm.save_settings(profile="unused", backend="openai", model="unused", isolated=True)
    data = llm._stored()
    data["routes"] = {"ask": "missing-profile"}
    llm.ai_profiles.write(llm.SETTINGS_PATH, data)
    frozen = llm.freeze_connections(("survey",))
    llm.save_settings(profile="selected", model="after", api_key="synthetic-two")
    assert frozen.settings("survey").model == "before"
    assert frozen.settings("survey").api_key == "synthetic-one"
    assert frozen.settings("survey").cli_home is None
    assert frozen.task_names == ("survey",) and frozen.profile_names == ()
    with pytest.raises(JobIntentError, match="undeclared_task"):
        frozen.settings("ask")
    with pytest.raises(JobIntentError, match="undeclared_profile"):
        frozen.settings("survey", profile="unused")


def test_job_default_reaches_fresh_pool_threads_and_nested_capture(monkeypatch):
    frozen = routes()
    monkeypatch.setattr(llm, "_stored", lambda: pytest.fail("child reread settings"))
    def nested():
        with llm.connection_scope(llm.capture_connections()):
            cfg = llm.settings("survey")
            return cfg.model, cfg.api_key, cfg.max_tokens, cfg.cli_home
    with llm.private_job_scope(frozen):
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(lambda _: nested(), range(2))) == [
                ("fixture-model", "synthetic-private-key", 4096, "private-account-home")
            ] * 2
        with pytest.raises(JobIntentError, match="undeclared_task"):
            llm.settings("ask")
    assert llm._PROCESS_CONNECTIONS is None


def test_bootstrap_validates_frame_before_cli_and_preserves_trailing_stdin(monkeypatch):
    intent = routes().bind(REQUEST, COMMAND)
    source = BytesIO(encode_frame(intent) + b"ordinary trailing input")
    output = StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=source))
    monkeypatch.setattr(sys, "stdout", output)
    observed = []
    def run(args):
        assert tuple(args) == COMMAND
        runtime.load_env_file(path=None)
        cfg = llm.settings("survey")
        observed.append((cfg.model, cfg.api_key, source.read()))
        return 7
    monkeypatch.setitem(sys.modules, "paper_daily.cli", SimpleNamespace(main=run))
    monkeypatch.setattr(runtime, "read_env_file", lambda *_: pytest.fail("private job loaded .env"))
    result = integration_entry.main(["_desktop-job-v1", REQUEST, *COMMAND])
    assert result == 7
    assert observed == [("fixture-model", "synthetic-private-key", b"ordinary trailing input")]
    assert output.getvalue().encode() == hello_line(REQUEST) + ready_line(REQUEST)
    assert "synthetic-private-key" not in output.getvalue()
    assert llm._PROCESS_CONNECTIONS is None and runtime._PRIVATE_JOB_ENV is False


@pytest.mark.parametrize("change", ["truncated", "wrong-request", "wrong-command", "oversized"])
def test_invalid_bootstrap_never_invokes_cli_or_changes_route(monkeypatch, change):
    frame = encode_frame(routes().bind(REQUEST, COMMAND))
    if change == "truncated":
        frame = frame[:-3]
    elif change == "wrong-request":
        frame = encode_frame(routes().bind("2" * 32, COMMAND))
    elif change == "wrong-command":
        frame = encode_frame(routes().bind(REQUEST, ("survey", "other")))
    else:
        frame = frame[:7] + (2 ** 21).to_bytes(4, "big")
    output, errors = StringIO(), StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=BytesIO(frame)))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    monkeypatch.setitem(sys.modules, "paper_daily.cli", SimpleNamespace(
        main=lambda *_: pytest.fail("invalid job executed CLI")))
    assert integration_entry.main(["_desktop-job-v1", REQUEST, *COMMAND]) == 2
    assert output.getvalue().encode() == hello_line(REQUEST)
    assert errors.getvalue() == "AI job startup failed; please retry.\n"
    assert "synthetic" not in output.getvalue() + errors.getvalue()
    assert llm._PROCESS_CONNECTIONS is None and runtime._PRIVATE_JOB_ENV is False


def test_ordinary_cli_does_not_touch_stdin_or_private_scope(monkeypatch):
    called = []
    monkeypatch.setattr(sys, "stdin", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "paper_daily.cli", SimpleNamespace(
        main=lambda args: called.append(args) or 0))
    assert integration_entry.main(["lists"]) == 0
    assert called == [["lists"]]
    assert llm._PROCESS_CONNECTIONS is None and runtime._PRIVATE_JOB_ENV is False
