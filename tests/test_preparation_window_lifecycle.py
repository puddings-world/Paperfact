"""Actual preparation lifetime gates parent launch/close, including reentrant saves."""

import os
import sqlite3
from contextlib import closing
from threading import Event

import pytest
from test_reader_preparation import activate, pending_turn, settle
from test_reader_preparation import legacy as legacy_fixture
from test_reader_preparation import reader as reader_fixture
from test_reader_preparation import ready as ready_fixture
from test_research_chat import messages

from paper_daily import store, updates
from paper_daily.desktop import reader_preparation as preparation
from paper_daily.desktop import ui_state

legacy = legacy_fixture
reader = reader_fixture
ready = ready_fixture


@pytest.fixture
def joint(ready):
    app, window, view = ready
    window.show()
    app.processEvents()
    view.ask_box.setText("Keep exact unsent question")
    view.note_edit.setPlainText("Keep exact unsent note")
    pending_turn()
    return app, window, view


def hold(monkeypatch):
    entered, release = Event(), Event()
    actual = preparation._prepare
    calls = []

    def controlled(request, cancelled):
        calls.append(request.token)
        entered.set()
        assert release.wait(20)
        return actual(request, cancelled)

    monkeypatch.setattr(preparation, "_prepare", controlled)
    return entered, release, calls


def observe(window, monkeypatch):
    saves, remembered, launched = [], [], []
    actual_save, actual_remember = (
        window.reader_page.presentation_pane.save_changes,
        window.remember,
    )

    def save():
        saves.append(True)
        return actual_save()

    def remember(key, value):
        remembered.append((key, value))
        return actual_remember(key, value)

    monkeypatch.setattr(window.reader_page.presentation_pane, "save_changes", save)
    monkeypatch.setattr(window, "remember", remember)
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    return saves, remembered, launched


def invoke(window, action, tmp_path):
    if action == "restart":
        return window._prepare_restart()
    if action == "update":
        return window._prepare_update()
    if action == "close":
        return window.close()
    banner = window.update_banner
    banner.release = updates.Release("9.9.9", "Fixture", "", "https://fixture/release", {})
    banner._ready = tmp_path / "verified-fixture.exe"
    banner._verified()
    return banner._installing


@pytest.mark.parametrize("action", ["restart", "update", "verified"])
def test_actual_held_preparation_blocks_parent_launch_without_saving_or_losing_drafts(
    joint, monkeypatch, tmp_path, action
):
    app, window, view = joint
    before = messages()
    before_html = view.chat_view._body
    entered, release, calls = hold(monkeypatch)
    saves, remembered, launched = observe(window, monkeypatch)
    try:
        activate(view)
        assert entered.wait(5)
        for _ in range(3):
            assert not invoke(window, action, tmp_path)
        assert view.preparation.busy and not view.preparation._disposed
        assert not saves and not remembered and not launched
        assert view.ask_box.text() == "Keep exact unsent question"
        assert view.note_edit.toPlainText() == "Keep exact unsent note"
        assert messages() == before
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)
    assert view.chat_view._body == before_html
    assert len(calls) == 1


def transition_state(database):
    with store.connect(path=database) as conn:
        return {
            key: ui_state.read(conn, "ui." + key) for key in ("restart", "presentation", "geometry")
        }


def test_native_finished_but_queued_delivery_is_still_a_parent_admission_barrier(
    joint, monkeypatch, tmp_path
):
    app, window, view = joint
    before_html = view.chat_view._body
    entered, release, _calls = hold(monkeypatch)
    saves, remembered, launched = observe(window, monkeypatch)
    try:
        activate(view)
        assert entered.wait(5)
        worker = view.preparation._thread
        release.set()
        assert worker.wait(5000)  # Native completion, with GUI delivery deliberately queued.
        assert view.preparation.busy
        assert not invoke(window, "update", tmp_path)
        assert not saves and not remembered and not launched
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)
    assert view.chat_view._body == before_html
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert "Question" in view.chat_view._body
    assert invoke(window, "restart", tmp_path)
    assert saves and remembered


@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("queued", [False, True])
def test_normal_and_stale_close_wait_for_preparation_then_dispose_without_late_render(
    joint, monkeypatch, tmp_path, foreign, queued
):
    app, window, view = joint
    database = store.DB_PATH
    before_messages = messages(database)
    before_html = view.chat_view._body
    view.note_edit.clear()
    view.ask_box.clear()
    view._qa_drafts = {}
    target = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(target)) as conn:
        conn.execute("CREATE TABLE marker(value)")
        conn.execute("INSERT INTO marker VALUES('untouched')")
    data = target.read_bytes()
    entered, release, _ = hold(monkeypatch)
    try:
        activate(view)
        assert entered.wait(5)
        if queued:
            worker = view.preparation._thread
            release.set()
            assert worker.wait(5000)
        if foreign:
            monkeypatch.setattr(store, "DB_PATH", target)
        assert not window.close()
        assert window.isVisible()
        assert not view.preparation._disposed
        assert not view.reading_positions._disposed
        assert not window.workspace_changes.disposed
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)
    assert view.chat_view._body == before_html and messages(database) == before_messages
    assert window.close()
    assert view.preparation._disposed and view.reading_positions._disposed
    assert window.workspace_changes.disposed and not window.isVisible()
    view.preparation.source_changed()
    assert not view.preparation.request()
    app.processEvents()
    assert view.chat_view._body == before_html
    assert target.read_bytes() == data
    replacement = target.with_suffix(".replacement")
    replacement.write_bytes(data)
    os.replace(replacement, target)
    assert target.read_bytes() == data


@pytest.mark.parametrize("action", ["restart", "update", "verified", "close"])
def test_preparation_admitted_during_save_blocks_final_launch_and_persistence(
    joint, monkeypatch, tmp_path, action
):
    app, window, view = joint
    database = store.DB_PATH
    state = transition_state(database)
    original = view.presentation_pane.save_changes
    entered, release, _ = hold(monkeypatch)
    _, remembered, launched = observe(window, monkeypatch)

    def reentrant_save():
        result = original()
        activate(view)
        assert entered.wait(5)
        return result

    monkeypatch.setattr(view.presentation_pane, "save_changes", reentrant_save)
    try:
        assert not invoke(window, action, tmp_path)
        assert view.preparation.busy and not view.preparation._disposed
        assert not remembered and not launched
        assert transition_state(database) == state
        assert view.ask_box.text() == "Keep exact unsent question"
        assert view.note_edit.toPlainText() == "Keep exact unsent note"
        assert window.isVisible()
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)


@pytest.mark.parametrize("action", ["restart", "close"])
def test_reentrant_real_remember_hook_cannot_queue_transition_state_while_preparation_runs(
    joint, monkeypatch, tmp_path, action
):
    app, window, view = joint
    database = store.DB_PATH
    state = transition_state(database)
    original = window.remember
    entered, release, _ = hold(monkeypatch)
    admitted = []

    def remember(key, value):
        if not admitted:
            admitted.append(key)
            activate(view)
            assert entered.wait(5)
        return original(key, value)

    monkeypatch.setattr(window, "remember", remember)
    try:
        assert not invoke(window, action, tmp_path)
        assert admitted and view.preparation.busy
        assert transition_state(database) == state
        assert window.isVisible()
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)


def test_reentrant_state_collection_is_rechecked_before_geometry_persistence(
    joint, monkeypatch, tmp_path
):
    app, window, view = joint
    database = store.DB_PATH
    state = transition_state(database)
    original = view.presentation_pane.workspace_state
    entered, release, _ = hold(monkeypatch)
    _, remembered, _launched = observe(window, monkeypatch)

    def collect():
        result = original()
        activate(view)
        assert entered.wait(5)
        return result

    monkeypatch.setattr(view.presentation_pane, "workspace_state", collect)
    try:
        assert not window.close()
        assert view.preparation.busy and not remembered
        assert transition_state(database) == state
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)


@pytest.mark.parametrize("action", ["restart", "close"])
def test_modal_child_reentrancy_admits_read_only_preparation_but_blocks_parent_save(
    joint, monkeypatch, tmp_path, action
):
    from types import SimpleNamespace

    app, window, view = joint
    database = store.DB_PATH
    state = transition_state(database)
    entered, release, _ = hold(monkeypatch)
    saves, remembered, launched = observe(window, monkeypatch)

    def child_close():
        activate(view)
        assert entered.wait(5)
        return True

    window._research_inbox_dialog = SimpleNamespace(disposed=False, close=child_close)
    try:
        assert not invoke(window, action, tmp_path)
        assert not saves and not remembered and not launched
        assert transition_state(database) == state
        assert view.ask_box.text() == "Keep exact unsent question"
    finally:
        window._research_inbox_dialog = None
        release.set()
        settle(app, lambda: not view.preparation.busy)


def test_update_rechecks_after_delegated_restart_returns(joint, monkeypatch, tmp_path):
    app, window, view = joint
    actual = window._prepare_restart
    entered, release, _ = hold(monkeypatch)
    launched = []
    monkeypatch.setattr(updates, "launch_installer", launched.append)

    def restart():
        result = actual()
        assert result
        activate(view)
        assert entered.wait(5)
        return result

    monkeypatch.setattr(window, "_prepare_restart", restart)
    try:
        assert not invoke(window, "verified", tmp_path)
        assert not launched and view.preparation.busy
        assert window.isVisible()
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)


def test_gui_install_phase_itself_remains_busy_until_the_frame_is_installed_or_discarded(
    joint, monkeypatch, tmp_path
):
    app, window, view = joint
    original = view.chat_view.setHtml
    before_html = view.chat_view._body
    saves, remembered, launched = observe(window, monkeypatch)
    deliveries = []

    def install(body, **kwargs):
        deliveries.append(view.preparation.busy)
        assert not window._prepare_update()
        return original(body, **kwargs)

    monkeypatch.setattr(view.chat_view, "setHtml", install)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert deliveries == [True]
    assert not saves and not remembered and not launched
    assert view.chat_view._body == before_html
    assert view.ask_box.text() == "Keep exact unsent question"


def test_verified_banner_retry_after_drain_launches_once_with_exact_drafts_saved(
    joint, monkeypatch, tmp_path
):
    import json

    app, window, view = joint
    database = store.DB_PATH
    entered, release, _ = hold(monkeypatch)
    _, _, launched = observe(window, monkeypatch)
    try:
        activate(view)
        assert entered.wait(5)
        assert not invoke(window, "verified", tmp_path)
        assert not launched
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)
    assert invoke(window, "verified", tmp_path)
    window.update_banner._verified()
    assert launched == [tmp_path / "verified-fixture.exe"]
    state = json.loads(transition_state(database)["restart"])
    assert state["note"] == "Keep exact unsent note"
    assert state["question"] == "Keep exact unsent question"
    assert view.preparation._disposed and not window.isVisible()
