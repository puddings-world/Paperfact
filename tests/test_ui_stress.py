"""Repeated user actions must preserve data and start at most one background job."""

import threading

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
from test_presentation_pane import pane as _pane
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import bundle, list_create, llm, store
from paper_daily.desktop import fonts
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.bundle_dialog import BundleDialog
from paper_daily.desktop.import_dialog import ImportListDialog
from paper_daily.desktop.main import MainWindow

workspace = _workspace
pane = _pane


def settle(runner):
    for _ in range(400):
        QTest.qWait(5)
        if not runner.busy:
            QTest.qWait(5)
            return
    pytest.fail("background operation did not finish")


def test_header_repeated_collapse_and_navigation_do_not_duplicate_global_ai(workspace):
    fonts.load()
    llm.save_settings(profile="global", backend="cli", model="test-model", isolated=True)
    widget = MainWindow()
    widget.show()
    try:
        for _ in range(40):
            widget.show_lists()
            widget.top_toggle.setChecked(False)
            assert widget.ai_summary.isHidden()
            assert widget.ai_summary.text() == ""
            assert widget.ai_picker.text().startswith("全域 AI：")
            widget.top_toggle.click()
            assert not widget.ai_summary.isHidden()
            assert widget.ai_summary.text().count("全域 AI：") == 1
            assert widget.top_toolbar.isHidden()
            widget.top_expand.click()
            widget.stack.setCurrentWidget(widget.reader_page)
            widget.reader_page.tabs.setCurrentIndex(2)
            widget._refresh_ai_summary()
            assert "全域 AI：" not in widget.ai_summary.text()
            assert "沿用全域" in widget.ai_summary.text()
            widget.show_queue()
            assert widget.ai_summary.isHidden()
    finally:
        widget.close()
        widget.deleteLater()


def test_function_ai_label_tracks_overrides_through_repeated_model_changes(workspace):
    fonts.load()
    llm.save_settings(profile="global", backend="cli", model="global-model", isolated=True)
    llm.save_settings(profile="ask", backend="codex", model="ask-model", isolated=True)
    llm.use_profile("global", desktop=True)
    llm.use_profile("ask", task="ask", desktop=True)
    widget = MainWindow()
    widget.stack.setCurrentWidget(widget.reader_page)
    widget.reader_page.tabs.setCurrentIndex(2)
    try:
        for index in range(30):
            model = f"ask-model-{index}"
            llm.save_settings(profile="ask", model=model)
            widget._refresh_ai_summary()
            assert "個別指定" in widget.ai_summary.text()
            assert model in widget.ai_summary.text()
            assert "global-model" not in widget.ai_summary.text()
            assert "global-model" in widget.ai_picker.text()
    finally:
        widget.close()
        widget.deleteLater()


def test_compact_ai_button_opens_settings_without_changing_routes(workspace, monkeypatch):
    fonts.load()
    from paper_daily.desktop import ai_picker
    from paper_daily.desktop.account_status import AccountStatus

    llm.save_settings(profile="global", backend="cli", model="fable", isolated=True)
    llm.save_settings(profile="slides", backend="codex", model="other", isolated=True)
    llm.use_profile("global", desktop=True)
    llm.use_profile("slides", task="slides", desktop=True)
    before = llm.SETTINGS_PATH.read_bytes()
    opened = []
    monkeypatch.setattr(AccountStatus, "check", lambda *args: None)

    class Picker:
        def __init__(self, parent):
            self.parent = parent

        def exec(self):
            opened.append(self.parent)

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    widget = MainWindow()
    widget.show()
    try:
        assert widget.ai_picker.menu() is None
        widget.ai_picker.click()
        assert opened == [widget]
        assert llm.SETTINGS_PATH.read_bytes() == before
        assert "Fable" in widget.ai_picker.text()
    finally:
        widget.close()
        widget.deleteLater()


@pytest.mark.parametrize("fails", [False, True])
def test_runner_click_flood_is_single_flight_and_recovers(workspace, fails):
    runner = AskRunner()
    calls, results, errors = [], [], []
    release = threading.Event()

    def call(prompt):
        calls.append(prompt)
        assert release.wait(3)
        if fails:
            raise OSError("fixture failure")
        return "saved result", "ok"

    try:
        for _ in range(50):
            runner.start("one action", results.append, errors.append, call=call)
        release.set()
        settle(runner)
        assert calls == ["one action"]
        assert len(errors if fails else results) == 1
        runner.start("retry", results.append, errors.append, call=lambda _: ("retry works", "ok"))
        settle(runner)
        assert results[-1] == "retry works"
    finally:
        release.set()
        if runner._thread:
            runner._thread.quit()
            runner._thread.wait(4000)
        runner.deleteLater()


@pytest.mark.parametrize("fails_once", [False, True])
def test_create_list_click_close_flood_keeps_input_and_creates_once(
    workspace, monkeypatch, fails_once
):
    original = list_create.create
    release = threading.Event()
    calls = []

    def create(*args):
        calls.append(args)
        assert release.wait(3)
        if fails_once and len(calls) == 1:
            raise OSError("fixture disk error")
        return original(*args)

    monkeypatch.setattr(list_create, "create", create)
    widget = ImportListDialog({}, workspace[1])
    widget.mode.setCurrentIndex(widget.mode.findData("empty"))
    widget.name.setText("My research")
    widget.show()
    try:
        widget.go.click()
        for _ in range(30):
            widget.go.click()
            widget.close_btn.click()
            widget.close()
        assert widget.isVisible() and not widget.go.isEnabled()
        release.set()
        settle(widget.runner)
        if fails_once:
            assert not widget.imported and widget.go.isEnabled()
            assert widget.name.text() == "My research"
            widget.go.click()
            settle(widget.runner)
        assert widget.imported
        assert len(calls) == (2 if fails_once else 1)
        with store.connect() as conn:
            assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 1
    finally:
        release.set()
        if widget.runner._thread:
            widget.runner._thread.quit()
            widget.runner._thread.wait(4000)
        widget.close()
        widget.deleteLater()


@pytest.mark.parametrize("fails_once", [False, True])
def test_export_click_close_flood_and_disk_failure_retry(workspace, monkeypatch, fails_once):
    root = workspace[1]
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    target = root / "shared.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    original, release, calls = bundle.export, threading.Event(), []

    def export(*args, **kwargs):
        calls.append(args)
        assert release.wait(3)
        if fails_once and len(calls) == 1:
            raise OSError("fixture disk error")
        return original(*args, **kwargs)

    monkeypatch.setattr(bundle, "export", export)
    widget = BundleDialog(list_id="x", list_name="Research")
    widget.show()
    try:
        widget.go.click()
        for _ in range(30):
            widget.go.click()
            widget.close_button.click()
            widget.close()
        assert widget.isVisible() and not widget.go.isEnabled()
        release.set()
        settle(widget.runner)
        if fails_once:
            assert widget.result_data is None and widget.go.isEnabled()
            widget.go.click()
            settle(widget.runner)
        assert bundle.inspect(target)["list_id"] == "x"
        assert len(calls) == (2 if fails_once else 1)
    finally:
        release.set()
        if widget.runner._thread:
            widget.runner._thread.quit()
            widget.runner._thread.wait(4000)
        widget.close()
        widget.deleteLater()


def test_slide_panel_zoom_navigation_button_flood_preserves_content(pane, monkeypatch):
    from paper_daily import materials
    from paper_daily.desktop import presentation_pane

    widget, deck, app, _root = pane
    monkeypatch.setattr(
        presentation_pane.materials, "collect", lambda pid: materials.Materials(pid)
    )
    widget.show()
    app.processEvents()
    before = widget.deck.to_dict()
    for index in range(100):
        widget.settings_button.click()
        widget.outline_button.click()
        widget.materials_button.click()
        widget.canvas.zoom_in.click()
        widget.canvas.zoom_out.click()
        widget.canvas.fit_button.click()
        widget.outline.setCurrentRow(index % len(deck.slides))
    assert widget.deck.to_dict() == before and not widget._dirty
    assert widget.canvas.view.fit_mode


@pytest.mark.parametrize("feature", ["add", "survey", "queue"])
def test_failed_process_start_releases_controls_and_can_retry(workspace, monkeypatch, feature):
    from paper_daily.desktop import add_dialog, survey_dialog

    owner = MainWindow()
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    from paper_daily import runtime

    missing = str(workspace[1] / "missing-python.exe")
    monkeypatch.setattr(runtime, "cli_command", lambda *args: [missing, *args])
    if feature == "add":
        widget = add_dialog.AddToListDialog(owner.pal, "x", "Research", workspace[1], owner)
        widget.body.setPlainText("A real reference title for a test")
        start = widget._start_ready

        def pending():
            return widget.process

        status = widget.status
    elif feature == "survey":
        widget = survey_dialog.SurveyDialog("x", "Research", owner.pal, owner)
        start = widget._run_ready

        def pending():
            return widget.job

        status = widget.status
    else:
        widget = owner.queue_page

        def start():
            return widget._start_ready(["repdf", "missing"])

        def pending():
            return widget._job

        status = widget.analysis
    try:
        for _ in range(3):
            start()
            first = pending()
            for _ in range(20):
                start()
                assert pending() is first
            for _ in range(100):
                QTest.qWait(5)
                if pending() is None:
                    break
            assert pending() is None and "無法啟動" in status.text()
            if feature == "add":
                assert widget.go.isEnabled() and widget._temp is None
                assert widget.body.toPlainText() == "A real reference title for a test"
            elif feature == "survey":
                assert widget.run_btn.isEnabled()
    finally:
        widget.close()
        owner.close()
        owner.deleteLater()


@pytest.mark.parametrize("feature", ["login", "usage", "inline_usage"])
def test_account_actions_deduplicate_and_metadata_dialogs_can_close(
    workspace, monkeypatch, feature
):
    from paper_daily import ai_accounts, ai_usage
    from paper_daily.ai_types import Settings
    from paper_daily.desktop.ai_picker import AIPickerDialog
    from paper_daily.desktop.ai_usage import AIUsageDialog

    release, calls = threading.Event(), []
    monkeypatch.setattr(ai_accounts, "command", lambda backend: [backend])
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: [])
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: dict(windows=[], message="fixture"))
    monkeypatch.setattr(ai_usage, "local_summary", lambda cfg: None)
    llm.save_settings(profile="base", backend="cli", isolated=True)

    def auth(cfg, action):
        if feature in {"usage", "inline_usage"} or action == "login":
            calls.append(action)
            assert release.wait(3)
            return None, "fixture login cancelled"
        return "fixture@example.org", "ok"

    monkeypatch.setattr(ai_accounts, "auth", auth)
    widget = AIUsageDialog(Settings("cli")) if feature == "usage" else AIPickerDialog()
    widget.show()
    try:
        QTest.qWait(20)
        if feature == "login":
            settle(widget.runner)
            button = widget.login_button
            button.click()
        elif feature == "usage":
            button = widget.refresh_button
        else:
            button = widget.usage.refresh_button
        for _ in range(50):
            button.click()
            widget.reject()
        # Requested UX: metadata reads may detach; an actual login still waits safely.
        assert widget.isVisible() is (feature != "inline_usage")
        assert not button.isEnabled()
        release.set()
        settle(widget.auth_runner if feature == "login" else widget.runner)
        assert len(calls) == 1
        if feature != "inline_usage":
            assert button.isEnabled()
        widget.reject()
        assert not widget.isVisible()
    finally:
        release.set()
        if widget.runner._thread:
            widget.runner._thread.quit()
            widget.runner._thread.wait(4000)
        if feature == "login" and widget.auth_runner._thread:
            widget.auth_runner._thread.quit()
            widget.auth_runner._thread.wait(4000)
        widget.deleteLater()
