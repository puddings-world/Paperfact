import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from test_research_chat import legacy as legacy_fixture
from test_research_chat import messages

from paper_daily import llm, store
from paper_daily.desktop import ai_access, main

legacy = legacy_fixture


class Deferred:
    busy = False

    def start(self, prompt, done, failed, call=None, **kwargs):
        if self.busy:
            return
        self.busy = True
        self.job, self.done, self.failed = call, done, failed

    def run(self):
        try:
            answer, reason = self.job("")
        except Exception:
            answer, reason = None, "Fixture failure"
        self.busy = False
        (self.done if answer is not None else self.failed)(answer if answer is not None else reason)


@pytest.fixture
def reader(legacy, tmp_path, monkeypatch):
    from paper_daily import research_questions
    from paper_daily.desktop.account_status import AccountStatus
    from paper_daily.desktop.update_banner import UpdateBanner

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(AccountStatus, "check", lambda *_: None)
    monkeypatch.setattr(UpdateBanner, "check_in_background", lambda *_: None)
    monkeypatch.setattr(main.MainWindow, "_refresh_ai_summary", lambda *a, **k: None)
    monkeypatch.setattr(main.MainWindow, "announce_ready", lambda *_: None)
    monkeypatch.setattr(research_questions, "cached", lambda *_: {"items": []})
    window = main.MainWindow()
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(ai_access, "_bridge", None)
    view = window.reader_page
    view.paper = SimpleNamespace(id="local-paper")
    view.ask_box.setText("Question")
    view._qa_view_database = legacy
    monkeypatch.setattr(view, "_load_chat", lambda: None)
    yield app, window, view
    if getattr(view.runner, "_thread", None):
        view.runner._thread.quit()
        view.runner._thread.wait(3000)
    window._ready_poll.stop()
    window.workspace_changes.timer.stop()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_reentrant_submit_then_navigation_never_writes_other_paper(reader, monkeypatch):
    app, window, view = reader
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    original = window.data.begin_chat
    attempts = []

    def begin(*args, **kwargs):
        attempts.append(1)
        view._ask("Duplicate")
        app.processEvents()
        return original(*args, **kwargs)

    monkeypatch.setattr(window.data, "begin_chat", begin)
    calls = []
    monkeypatch.setattr(
        llm, "complete", lambda prompt, **kw: (calls.append(prompt) or "Answer", "ok")
    )
    view._ask("Question")
    view.paper = SimpleNamespace(id="another-paper")
    view._qa_epoch += 1
    view.ask_box.setText("Different paper draft")
    deferred.run()
    assert attempts == [1] and len(calls) == 1
    assert messages()[-1]["body"] == "Answer"
    assert view.ask_box.text() == "Different paper draft"
    assert window.data.chat("another-paper") == []


def test_failure_retry_keeps_question_and_uses_original_account(reader, monkeypatch):
    _, _, view = reader
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    llm.save_settings(profile="a", backend="openai", model="first", isolated=True)
    llm.save_settings(profile="b", backend="openai", model="second", isolated=True)
    llm.use_profile("a", desktop=True)
    calls = []

    def complete(prompt, cfg, **kwargs):
        calls.append(cfg.model)
        return (None, "Try again") if len(calls) == 1 else ("Answer", "ok")

    monkeypatch.setattr(llm, "complete", complete)
    view._ask("Question")
    llm.use_profile("b", desktop=True)
    deferred.run()
    assert view.ask_box.text() == "Question"
    assert len(messages()) == 1
    view._ask("Question")
    deferred.run()
    assert calls == ["first", "first"] and len(messages()) == 2
    assert view.ask_box.text() == ""


def test_aba_return_keeps_new_draft_and_repeated_delivery_does_not_duplicate(reader, monkeypatch):
    _, _, view = reader
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("Answer", "ok"))
    view._ask("Question")
    view._qa_epoch += 2
    view.ask_box.setText("New A draft")
    deferred.run()
    view._ask_done("duplicate callback")
    assert len(messages()) == 2 and view.ask_box.text() == "New A draft"


def test_close_while_real_worker_active_preserves_question_and_waits(reader, monkeypatch):
    app, window, view = reader
    entered, release = threading.Event(), threading.Event()

    def complete(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return "Answer", "ok"

    monkeypatch.setattr(llm, "complete", complete)
    window.show()
    view._ask("Question")
    try:
        for _ in range(200):
            app.processEvents()
            time.sleep(0.01)
            if entered.is_set():
                break
        assert entered.is_set() and len(messages()) == 1, (
            view.ask_status.text(),
            view._qa_job,
            view.runner.busy,
        )
        assert not window.close()
        assert window.isVisible()
    finally:
        release.set()
        for _ in range(200):
            app.processEvents()
            time.sleep(0.01)
            if not view.runner.busy:
                break
    assert not view.runner.busy and messages()[-1]["body"] == "Answer"


def test_delete_uses_loaded_bases_and_keeps_changed_messages(reader):
    _, window, _ = reader
    window.data.add_chat("local-paper", "user", "Question")
    row = window.data.chat("local-paper")[0]
    expected = window.data.chat_snapshot("local-paper", [row["id"]])
    with store.connect() as conn:
        conn.execute("UPDATE chat SET body='Changed' WHERE id=?", (row["id"],))
    with pytest.raises(ValueError):
        window.data.delete_chat([row["id"]], expected=expected)
    assert messages()[0]["body"] == "Changed"
    fresh = window.data.chat_snapshot("local-paper", [row["id"]])
    window.data.delete_chat([row["id"]], expected=fresh)
    assert messages() == []


def test_login_required_retry_captures_new_account_without_duplicate_question(reader, monkeypatch):
    _, _, view = reader
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(
        llm, "ACCESS_CHECK", lambda cfg, task: "Sign in" if cfg.backend == "none" else ""
    )
    llm.save_settings(backend="none")
    calls = []
    monkeypatch.setattr(
        llm, "complete", lambda prompt, cfg, **kw: (calls.append(cfg.model) or "Answer", "ok")
    )
    view._ask("Question")
    deferred.run()
    assert view.ask_box.text() == "Question" and messages() == []
    llm.save_settings(backend="openai", model="new-login")
    view._ask("Question")
    deferred.run()
    assert calls == ["new-login"] and len(messages()) == 2


def test_empty_selection_and_invalid_anchor_do_not_start_ai(reader, monkeypatch):
    _, window, view = reader
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    view._ask(" ")
    view._ask_selection("")
    assert not deferred.busy and messages() == []
    view._ask("Question", anchor='{"unexpected":true}')
    assert not deferred.busy and view.ask_box.text() == "Question"


def test_subprocess_captures_original_workspace_before_launch_argument_evaluation(
    reader, monkeypatch, tmp_path
):
    from paper_daily.desktop import activity

    _, window, _ = reader
    original = store.DB_PATH
    seen = []
    handle = SimpleNamespace(accepted=True, finish=lambda *a: None)
    monkeypatch.setattr(activity, "begin", lambda *a, **k: handle)

    def command(*args):
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "other" / "papers.db")
        return ["fixture-cli", *args]

    monkeypatch.setattr(main.runtime, "cli_command", command)
    monkeypatch.setattr(
        main.subprocess, "Popen", lambda args, **kw: seen.append(kw) or SimpleNamespace()
    )
    monkeypatch.setattr(window.activity_hub, "watch_popen", lambda *a: None)
    window._spawn_job(["analyse", "paper"], "local-paper")
    window._dive_job = None
    assert seen[0]["env"]["PAPERFACT_DATA"] == str(original.parent.resolve())
    monkeypatch.setattr(store, "DB_PATH", original)


def test_delete_click_uses_rendered_turn_not_a_fresh_replacement(reader):
    _, window, view = reader
    window.data.add_chat("local-paper", "user", "Rendered question")
    view._chat_snapshot = window.data.chat_snapshot("local-paper")
    row = view._chat_snapshot["rows"][0]["row"]
    with store.connect() as conn:
        conn.execute("UPDATE chat SET body='Remote replacement' WHERE id=?", (row["id"],))
    view._forget_exchange(row["id"])
    assert messages()[0]["body"] == "Remote replacement"
    assert view.ask_status.text()


def test_concise_is_on_by_default_and_a_follow_up_applies_to_one_question(reader, monkeypatch):
    _, _, view = reader
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    llm.save_settings(profile="a", backend="openai", model="m", isolated=True)
    prompts = []
    monkeypatch.setattr(llm, "complete",
                        lambda prompt, cfg, **k: (prompts.append(prompt) or "Answer", "ok"))
    assert view.concise_btn.isChecked() and not view.follow_btn.isHidden()

    view._ask("First question")
    deferred.run()
    assert "回答格式(精要)" in prompts[-1]

    view.follow_btn.setChecked(True)
    view._ask("Follow up")
    assert not view.follow_btn.isChecked()  # One follow-up, then back to one at a time.
    deferred.run()
    assert "First question" in prompts[-1]

    view._ask("Unrelated")
    deferred.run()
    assert "First question" not in prompts[-1] and "Follow up" not in prompts[-1]

    view.concise_btn.setChecked(False)
    view._ask("In full")
    deferred.run()
    assert "回答格式(精要)" not in prompts[-1] and "Unrelated" in prompts[-1]
