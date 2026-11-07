"""Queued AI actions retain their own account/model/configuration; no providers run."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from paper_daily import llm
from paper_daily.desktop import ai_access
from paper_daily.desktop.ask import AskWorker


def selected(task="survey"):
    cfg = llm.settings(task=task)
    return cfg.profile, cfg.model, cfg.api_key, cfg.max_tokens, cfg.cli_home


@pytest.fixture
def scene(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setenv("PF_TEST_KEY", "synthetic key one")
    llm.save_settings(profile="A", backend="openai", model="model-a", isolated=True,
                      api_key_env="PF_TEST_KEY", account_id="a" * 32, max_tokens=2048)
    llm.save_settings(profile="B", backend="openai", model="model-b", isolated=True,
                      api_key="synthetic key two", account_id="b" * 32, max_tokens=4096)
    llm.use_profile("A", desktop=True)
    first, second = QWidget(), QWidget()
    bridge = ai_access.AccessBridge(first)
    pending, checked = [], []

    def check(cfg, task):
        checked.append((task, cfg.profile, cfg.model))
        return ""

    monkeypatch.setattr(bridge, "check", check)

    def start(prompt, done, failed, call):
        value, reason = call(prompt)
        pending.append(lambda: done(value) if value is not None else failed(reason))

    monkeypatch.setattr(bridge.runner, "start", start)
    monkeypatch.setattr(type(bridge.runner), "busy", property(lambda self: bool(pending)))

    def finish():
        assert pending
        pending.pop(0)()

    yield SimpleNamespace(app=app, first=first, second=second, bridge=bridge,
                          pending=pending, checked=checked, finish=finish)
    pending.clear()
    first.close()
    second.close()
    first.deleteLater()
    second.deleteLater()
    app.processEvents()


def test_gate_callback_and_nested_worker_keep_original_task_route(scene, monkeypatch):
    llm.save_routes({"survey": "B"})
    expected = selected()
    observed = []

    def launch():
        worker = AskWorker("fixture", call=lambda _: (str(selected()), "ok"))
        worker.finished.connect(observed.append)
        worker.run()

    scene.bridge.run(scene.first, ["survey"], launch)
    llm.save_settings(profile="B", model="changed-later", max_tokens=8192)
    scene.finish()
    assert observed == [str(expected)]
    assert llm.settings(task="survey").model == "changed-later"


def test_queued_requests_capture_before_wait_and_repeated_clicks_coalesce(scene):
    expected = selected()
    observed = []
    scene.bridge.run(scene.first, ["survey"], lambda: observed.append(selected()))
    scene.bridge.run(scene.second, ["survey"], lambda: observed.append(selected()))
    for _ in range(100):
        scene.bridge.run(scene.second, ["survey"], lambda: observed.append("duplicate"))
    llm.save_settings(profile="A", model="later-model")
    scene.finish()
    scene.finish()
    assert observed == [expected, expected]
    assert scene.checked == [("survey", "A", "model-a"), ("survey", "A", "model-a")]
    assert not scene.pending


def test_nested_recapture_keeps_scope_after_config_and_key_change(scene, monkeypatch):
    expected = selected()
    snapshot = llm.capture_connections()
    with llm.connection_scope(snapshot):
        llm.save_settings(profile="A", model="later-model")
        monkeypatch.setenv("PF_TEST_KEY", "synthetic replacement")
        with llm.connection_scope(llm.capture_connections()):
            assert selected() == expected
    assert selected()[1:3] == ("later-model", "synthetic replacement")


def test_scope_detaches_mutable_caller_snapshot(scene):
    expected = selected()
    snapshot = llm.capture_connections()
    with llm.connection_scope(snapshot):
        snapshot[0]["profiles"]["A"]["model"] = "mutated caller"
        snapshot[1]["PF_TEST_KEY"] = "mutated caller key"
        assert selected() == expected


def test_two_worker_scopes_do_not_borrow_each_others_latest_profile(scene):
    first = llm.capture_connections()
    expected_first = selected()
    llm.use_profile("B", desktop=True)
    second = llm.capture_connections()
    expected_second = selected()
    barrier = Barrier(2)

    def run(snapshot):
        with llm.connection_scope(snapshot):
            barrier.wait(timeout=5)
            with llm.connection_scope(llm.capture_connections()):
                return selected()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(run, first), pool.submit(run, second)
        assert a.result(timeout=8) == expected_first
        assert b.result(timeout=8) == expected_second


def test_explicit_retry_after_failed_login_uses_new_selection(scene, monkeypatch):
    observed = []
    monkeypatch.setattr(scene.bridge, "check", lambda cfg, task:
                        "login required" if cfg.profile == "A" else "")
    scene.bridge.run(scene.first, ["survey"], lambda: observed.append(selected()))
    scene.finish()
    assert observed == [] and not scene.pending
    llm.use_profile("B", desktop=True)
    expected = selected()
    scene.bridge.run(scene.first, ["survey"], lambda: observed.append(selected()))
    scene.finish()
    assert observed == [expected]


def test_closed_pending_owner_never_launches_generation(scene):
    observed = []
    scene.second.show()
    scene.bridge.run(scene.first, ["survey"], lambda: observed.append("first"))
    scene.bridge.run(scene.second, ["survey"], lambda: observed.append("closed"))
    scene.second.close()
    while scene.pending:
        scene.finish()
    assert observed == ["first"]


def test_new_reentrant_ui_request_reads_config_not_previous_request_scope(scene):
    expected_first = selected()
    observed = []

    def first():
        observed.append(selected())
        scene.bridge.run(scene.second, ["survey"], lambda: observed.append(selected()))

    scene.bridge.run(scene.first, ["survey"], first)
    llm.use_profile("B", desktop=True)
    expected_second = selected()
    scene.finish()
    scene.finish()
    assert observed == [expected_first, expected_second]


def test_queued_task_list_is_detached_from_the_callers_mutable_list(scene):
    tasks, observed = ["survey"], []
    scene.bridge.run(scene.first, ["survey"], lambda: observed.append("first"))
    scene.bridge.run(scene.second, tasks, lambda: observed.append("second"))
    tasks[0] = "slides"
    scene.finish()
    scene.finish()
    assert scene.checked == [("survey", "A", "model-a"), ("survey", "A", "model-a")]
    assert observed == ["first", "second"]


@pytest.mark.parametrize("via_child_frame", [False, True])
def test_ready_auto_route_cannot_switch_provider_before_launch(scene, monkeypatch, via_child_frame):
    """A successful login check admits one provider even if discovery later changes."""
    present = [True]
    monkeypatch.setattr(llm.ai_profiles, "_claude_on_path", lambda: present[0])
    for name in tuple(os.environ):
        if name.startswith(("PAPERFACT_", "PAPER_DAILY_", "OPENAI_", "ANTHROPIC_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic fallback key")
    llm.save_settings(profile="A", backend="auto", isolated=False, api_key_env=None,
                      account_id=None)
    checked, observed = [], []
    monkeypatch.setattr(scene.bridge, "check", lambda cfg, task: checked.append(cfg.backend) or "")

    def launch():
        if via_child_frame:
            routes = llm.freeze_connections(("survey",))
            observed.append(routes.settings("survey").backend)
        else:
            worker = AskWorker(
                "fixture", call=lambda _: (llm.settings(task="survey").backend, "ok"),
            )
            worker.finished.connect(observed.append)
            worker.run()

    scene.bridge.run(scene.first, ["survey"], launch)
    assert checked == ["cli"]
    present[0] = False
    scene.finish()
    assert observed == ["cli"]
    assert llm.settings(task="survey").backend == "anthropic"
