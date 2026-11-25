"""Drive setup UI uses fake services and never logs in or opens native credentials."""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from test_sync_connection_dialog import wait
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.desktop.drive_sync_dialog import DriveSyncDialog

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


class Setup:
    def __init__(self, *_args, **_kwargs):
        self.valid = True
        self.binding = SimpleNamespace(_check=lambda: None, current=lambda: self.valid)
        self.files = None
        self.calls = 0
        self.release = threading.Event()
        self.fail = False
        self.rollback = False

    def sign_in(self, ticket, progress):
        self.calls += 1
        progress({"stage": "google_login"})
        while not self.release.wait(0.01):
            ticket.check()
        ticket.check()
        if self.fail:
            raise ConnectionError("synthetic offline")
        self.files = object()
        return {"account": {"email": "researcher@example.test"}, "workspaces": [
            {"name": "My research", "workspace_id": "workspace", "folder_id": "folder"}]}

    def rollback_consent(self):
        self.rollback = True


@pytest.fixture
def dialog(service):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    setup = Setup()
    view = DriveSyncDialog(service[0], owner, language="en",
                           service_factory=lambda *a, **k: setup, owner=owner)
    view.show()
    yield app, view, setup
    setup.release.set()
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()
    owner.close()
    app.processEvents()


def test_login_is_one_visible_job_and_discovery_does_not_enable_sync(dialog):
    app, view, setup = dialog
    view.background.position_scopes["old-list"] = object()
    assert view.sign_in()
    assert not view.background.position_scopes
    assert not view.sign_in()
    wait(app, lambda: setup.calls == 1)
    assert not view.login.isEnabled()
    assert view.progress.isVisible()
    assert not view.create.isEnabled()
    setup.release.set()
    wait(app, lambda: not view.busy)
    assert view.account.text() == "researcher@example.test"
    assert view.workspaces.currentText() == "My research"
    assert view.create.isEnabled() and view.join.isEnabled()
    assert not view.auto.isChecked()
    assert not view.session.summary()["authenticated"]


def test_failure_is_retryable_and_stale_result_cannot_choose_another_workspace(dialog):
    app, view, setup = dialog
    setup.fail = True
    setup.release.set()
    view.sign_in()
    wait(app, lambda: not view.busy)
    assert "offline" in view.status.text()
    assert view.login.isEnabled() and not view.create.isEnabled()
    setup.fail = False
    setup.release.clear()
    view.sign_in()
    wait(app, lambda: setup.calls == 2)
    setup.valid = False
    setup.release.set()
    wait(app, lambda: not view.busy)
    assert view.account.text() == "Not connected to Google"
    assert view.workspaces.count() == 0
    assert setup.rollback


def test_close_cancels_worker_and_keeps_widgets_until_it_drains(dialog):
    app, view, setup = dialog
    view.sign_in()
    wait(app, lambda: setup.calls == 1)
    assert not view.close()
    wait(app, lambda: view.disposed)
    assert not view.busy
    assert not view.isVisible()
    assert setup.rollback
    assert not view.session.summary()["authenticated"]

def test_first_directory_read_offline_can_retry_without_another_login(dialog):
    app, view, setup = dialog
    setup.files = object()
    attempts = []

    def overview(ticket, progress):
        attempts.append(True)
        if len(attempts) == 1:
            raise ConnectionError("offline")
        return {"account": {"email": "researcher@example.test"}, "lists": [], "workspaces": [],
                "library": {"ordinary": True, "items": []}}

    setup.overview = overview
    assert not view.refresh_lists.isVisible()
    assert view._start("refresh", setup.overview)
    wait(app, lambda: not view.busy)
    assert view.refresh_lists.isVisible() and view.refresh_lists.isEnabled()
    view.refresh_lists.click()
    wait(app, lambda: not view.busy)
    assert view.directory_lists.isVisible() and setup.calls == 0 and len(attempts) == 2


def test_device_checkboxes_only_save_reviewed_ids_after_confirmation(dialog, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    app, view, setup = dialog
    library = {"ordinary": True, "items": [{"id": "a", "name": "Cataract", "selected": False},
                         {"id": "b", "name": "Other research", "selected": False}]}
    login = setup.sign_in

    def sign_in(ticket, progress):
        return {**login(ticket, progress), "library": library}

    saved = []

    def save(selected, ticket, progress, *, include_new_content):
        assert include_new_content
        saved.append(selected)
        return {
            "items": [{**item, "selected": item["id"] in selected} for item in library["items"]],
            "reviews": {"b": "Conflicting description"},
        }

    setup.sign_in = sign_in
    setup.apply_library = save
    setup.release.set()
    view.sign_in()
    wait(app, lambda: not view.busy)
    assert view.directory_lists.count() == 2 and view.directory_lists.isVisible()
    assert view.sync_lists.isHidden() and view.refresh_lists.isHidden()
    assert view.keep_syncing.isHidden() and view.save_selection.isHidden()
    view.details.setChecked(True)
    assert view.refresh_lists.isVisible()
    refreshes = []
    def overview(ticket, progress):
        refreshes.append(True)
        if len(refreshes) == 1:
            raise ConnectionError("synthetic network failure")
        return {"account": {"email": "researcher@example.test"}, "lists": [],
                "workspaces": [], "library": library}
    setup.overview = overview
    library["items"].append({"id": "c", "name": "New on desktop", "selected": False})
    view.refresh_lists.click()
    view.refresh_lists.click()
    wait(app, lambda: not view.busy)
    assert refreshes == [True] and view.directory_lists.count() == 2
    assert view.refresh_lists.isEnabled() and "When online" in view.status.text()
    view.refresh_lists.click()
    wait(app, lambda: not view.busy)
    assert refreshes == [True, True] and not saved
    assert view.directory_lists.item(2).text() == "New on desktop"
    assert view.directory_lists.item(2).checkState() == Qt.CheckState.Unchecked
    assert not view.create.isVisible()
    assert "Select the lists" in view.status.text()
    view._progress({"stage": "selected_lists", "completed": 1, "total": 3})
    assert "list 2 of 3" in view.status.text()
    view._progress(dict(stage="transfer", kind="pdf", direction="download", title="My paper",
                        index=2, total=3, name="Reading", coverage=(2, 5, 5), done=50, size=100))
    assert "download pdf" in view.status.text() and "My paper" in view.status.text()
    assert view.progress.value() == 50 and "Drive 5/5" in view.status.text()
    view.directory_lists.item(1).setCheckState(Qt.CheckState.Checked)
    assert view.save_selection.isVisible()
    assert not view.refresh_lists.isEnabled()
    prompts = []

    def decline(parent, title, message, *args):
        prompts.append(message)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    for zh, expected in ((False, "on both devices"), (True, "兩台裝置")):
        view.zh = zh
        view.save_selection.click()
        assert expected in prompts[-1] and "PDF" in prompts[-1]
    view.zh = False
    assert not saved
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view.save_selection.click()
    view.save_selection.click()
    wait(app, lambda: not view.busy)
    assert saved == [["b"]]
    assert view.directory_lists.item(1).checkState() == Qt.CheckState.Checked
    assert "needs review" in view.directory_lists.item(1).text()
    assert view.directory_lists.item(1).toolTip() == "Conflicting description"
    view.directory_lists.setCurrentRow(1)
    assert view.drive_content.isVisible() and "Conflicting description" in view.drive_content.text()
    view.directory_lists.setCurrentRow(0)
    assert "Conflicting description" not in view.drive_content.text()
    assert "Review" in view.status.text()
    assert view.sync_lists.isEnabled()
    view.directory_lists.item(0).setCheckState(Qt.CheckState.Checked)
    assert not view.sync_lists.isEnabled()
    view.directory_lists.item(0).setCheckState(Qt.CheckState.Unchecked)
    calls = []

    def sync_saved(ticket, progress):
        calls.append(True)
        return {"items": [{**item, "selected": item["id"] == "b"} for item in library["items"]]}

    setup.sync_saved_library = sync_saved
    view.sync_lists.click()
    view.sync_lists.click()
    wait(app, lambda: not view.busy)
    assert calls == [True] and saved == [["b"]]
    assert view.status.text() == "Saved lists synced."

def test_saved_list_background_survives_dialog_close_and_backs_off(dialog):
    app, view, setup = dialog
    setup.files = object()
    calls = []

    def exchange(ticket, progress):
        calls.append(ticket)
        if len(calls) == 1:
            raise ConnectionError("offline")
        return {"items": [{"selected": True}], "reviews": {}}

    setup.sync_saved_library = exchange
    view._show_directory({"ordinary": True, "items": [
        {"id": "a", "name": "Synthetic", "selected": True}
    ]})
    view.keep_syncing.click()
    assert view.done_button.text() in view.status.text()
    assert view.sync_lists.text() in view.status.text()
    view.keep_syncing.click()
    assert not view.keep_syncing.isChecked() and "off" in view.status.text()
    view.keep_syncing.click()
    runner = view.background
    assert runner.service is setup and runner.timer.isActive()
    runner.tick()
    assert not calls and runner.worker is None
    from PySide6.QtWidgets import QPushButton

    view.owner.sync_status_btn = QPushButton(view.owner)
    runner._display()
    assert "等待關閉同步設定" in view.owner.sync_status_btn.text()
    assert view.close()
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert runner.state == "offline" and runner.timer.interval() == 10000
    assert "10 秒" in view.owner.sync_status_btn.text()
    runner.tick()
    assert "核對 Drive 清單目錄" in view.owner.sync_status_btn.text()
    wait(app, lambda: runner.worker is None)
    assert "已核對" in view.owner.sync_status_btn.text()
    assert len(calls) == 2 and runner.state == "waiting" and runner.timer.interval() == 30000
    setup.files = object()
    runner.tick()
    assert runner.state == "changed" and not runner.timer.isActive()
    assert len(calls) == 2


def test_background_sync_recovers_when_google_token_expires_offline(dialog, monkeypatch):
    import httpx

    from paper_daily.drive_sync_files import ABOUT, DriveFiles
    from paper_daily.google_slides import GoogleSession

    app, view, setup = dialog
    refresh = iter([httpx.ConnectError("offline"), httpx.Response(503), httpx.Response(429),
                    httpx.Response(200, json={"access_token": "renewed", "expires_in": 3600})])
    calls = []

    def token_response(*args, **kwargs):
        reply = next(refresh)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def drive_reply(request):
        calls.append(request.headers["authorization"])
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx, "post", token_response)
    session = GoogleSession({}, {"refresh_token": "fixture"})
    with httpx.Client(transport=httpx.MockTransport(drive_reply)) as client:
        setup.files = DriveFiles(session, client=client)

        def exchange(ticket, progress):
            setup.files.request("GET", ABOUT)
            return {"items": [{"selected": True}], "reviews": {}}

        setup.sync_saved_library = exchange
        runner = view.background
        assert runner.enable(setup)
        view.hide()
        for delay in (10000, 20000, 40000):
            runner.tick()
            wait(app, lambda: runner.worker is None)
            assert runner.state == "offline" and runner.timer.interval() == delay
            assert not calls and runner.service is setup
        runner.tick()
        wait(app, lambda: runner.worker is None)
        assert runner.state == "waiting" and runner.timer.interval() == 30000
        assert calls == ["Bearer renewed"]
        runner.stop()


def test_saved_list_background_serializes_foreground_and_drains_on_close(dialog):
    app, view, setup = dialog
    setup.files = object()
    entered = threading.Event()
    released = threading.Event()
    seen = []

    def exchange(ticket, progress):
        seen.append(ticket)
        progress(dict(stage="transfer", kind="notes", direction="upload", title="Research paper",
                      index=1, total=2, name="Selected"))
        entered.set()
        released.wait(5)
        ticket.check()
        return {"items": [], "reviews": {}}

    setup.sync_saved_library = exchange
    runner = view.background
    assert runner.enable(setup)
    view.hide()
    runner.tick()
    wait(app, lambda: entered.is_set() and runner.detail is not None)
    assert runner.detail["direction"] == "upload" and "Research paper" in view.status.text()
    runner.tick()
    assert not view.sign_in() and setup.calls == 0
    assert not view.owner.close() and seen[0].cancelled
    released.set()
    wait(app, lambda: runner.worker is None)
    assert len(seen) == 1 and runner.service is None and not runner.timer.isActive()


def test_saved_login_menu_reconnects_without_enabling_transfer(dialog):
    app, view, setup = dialog
    library = {"ordinary": True, "items": [{"id": "a", "name": "Example", "selected": True}]}
    remembered = []
    setup.remember_library = lambda ticket: remembered.append("saved")
    setup.forget_library = lambda ticket: remembered.append("removed")

    def restore(ticket, progress):
        setup.files = object()
        return {"account": {"email": "saved@example.test"}, "library": library,
                "workspaces": [], "lists": []}

    setup.reconnect_library = restore
    assert view.restore_login.isEnabled() and not view.save_login.isEnabled()
    view.restore_login.trigger()
    wait(app, lambda: not view.busy)
    assert view.account.text() == "saved@example.test" and setup.calls == 0
    assert not view.keep_syncing.isChecked() and view._saved_ids == {"a"}
    view.save_login.trigger()
    wait(app, lambda: not view.busy)
    assert remembered == ["saved"] and "credential store" in view.status.text()
    def remember(ticket, *, startup=False):
        remembered.append("startup on" if startup else "saved")

    setup.remember_library = remember
    setup.disable_library_startup = lambda ticket: remembered.append("startup off")
    view.startup_sync.trigger()
    wait(app, lambda: not view.busy)
    assert view.startup_sync.isChecked() and view.background.service is setup
    view.startup_sync.trigger()
    wait(app, lambda: not view.busy)
    assert not view.startup_sync.isChecked() and view.background.service is None
    view.remove_login.trigger()
    wait(app, lambda: not view.busy)
    assert remembered == ["saved", "startup on", "startup off", "removed"]
    assert view._saved_ids == {"a"}


def test_startup_sync_retries_offline_and_honors_withdrawal(dialog):
    from paper_daily.desktop.saved_list_sync import resume_on_open

    app, view, setup = dialog
    runner = view.background
    owner = runner.parent()
    stamp = [None]
    attempts = []
    exchanges = []
    setup.library_startup_record = lambda: stamp[0]

    def reconnect(ticket, progress, *, startup_record):
        attempts.append(startup_record)
        progress({"stage": "local_page_scopes", "stamp": startup_record,
                  "scopes": {"test-list": ("device", "folder", "head", "test-list", 1)}})
        if len(attempts) == 1:
            raise ConnectionError("offline")
        setup.files = object()
        return {"library": {"items": [{"selected": True}]}}

    def exchange(ticket, progress):
        exchanges.append(1)
        return {"items": [{"selected": True}], "reviews": {}}

    setup.reconnect_library = reconnect
    setup.sync_saved_library = exchange

    def open_again():
        return resume_on_open(owner, "unused", current_path=lambda: "unused",
                              factory=lambda *a, **kw: setup)

    assert not open_again() and not runner.timer.isActive()
    stamp[0] = "saved"
    assert open_again() and not open_again()
    view.hide()
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert runner.state == "offline" and not exchanges
    assert "test-list" in runner.position_scopes
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert attempts == ["saved", "saved"] and runner.state == "waiting" and not exchanges
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert exchanges == [1]
    stamp[0] = None
    runner.tick()
    assert not runner.timer.isActive() and runner.service is None and exchanges == [1]


def test_list_comparison_displays_versions_and_requires_a_choice(dialog):
    from PySide6.QtWidgets import QPlainTextEdit, QPushButton

    from paper_daily.desktop.drive_note_compare import NoteComparison

    _, parent, _ = dialog
    card = dict(feature="list", fields=["note"], base={"note": "original"},
                local={"note": "desktop"}, remote={"note": "laptop"})
    for label, expected in (("Decide later", None), ("Use Drive version", (card, "remote")),
                            ("Keep this device's version", (card, "local"))):
        view = NoteComparison([card], parent)
        assert [box.toPlainText().splitlines() for box in view.findChildren(QPlainTextEdit)] == [
            ["Description", value] for value in ("original", "desktop", "laptop")]
        next(button for button in view.findChildren(QPushButton) if button.text() == label).click()
        assert view.decision == expected
        view.deleteLater()


def test_chat_comparison_shows_question_and_returns_only_the_chosen_version(dialog):
    from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QPushButton

    from paper_daily.desktop.drive_note_compare import NoteComparison

    _, parent, _ = dialog
    card = dict(feature="chat", title="Study", question="Why adjust for age?",
                base={"body": "Initial"}, local={"body": "Windows"}, remote={"body": "Mac"})
    for label, choice in (("Decide later", None), ("Use Drive version", (card, "remote"))):
        view = NoteComparison([card], parent)
        assert view.windowTitle() == "Compare Q&A versions"
        assert view.findChild(QComboBox).currentText() == "Study · Why adjust for age?"
        assert [box.toPlainText() for box in view.findChildren(QPlainTextEdit)] == [
            "Initial", "Windows", "Mac"]
        next(button for button in view.findChildren(QPushButton) if button.text() == label).click()
        assert view.decision == choice
        view.deleteLater()


def test_deleted_answer_comparison_labels_only_the_selected_card(dialog):
    from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QPushButton

    from paper_daily.desktop.drive_note_compare import NoteComparison

    _, parent, _ = dialog
    edited = dict(feature="chat", title="Study", question="Which sample?",
                  base={"body": "Initial"}, local={"body": "Local"}, remote={"body": "Updated"})
    missing = dict(edited, local=None, removal_action=("paper", "revision", "action"))
    view = NoteComparison([edited, missing], parent)
    picker = view.findChild(QComboBox)
    picker.setCurrentIndex(1)
    assert [box.toPlainText() for box in view.findChildren(QPlainTextEdit)] == [
        "Initial", "Deleted in the reader on this device", "Updated"]
    button = next(b for b in view.findChildren(QPushButton)
                  if b.text() == "Keep deleted on this device")
    picker.setCurrentIndex(0)
    assert button.text() == "Keep this device's version"
    picker.setCurrentIndex(1)
    button.click()
    assert view.decision == (missing, "local")
    view.deleteLater()


def test_background_keeps_polling_after_list_details_conflict(dialog):
    app, view, setup = dialog
    setup.files = object()
    reports = iter([
        {"reviews": {"a": "Compare list details"}, "list_conflicts": ["a"]},
        {"reviews": {"a": "Compare saved answers"}, "chat_conflicts": ["a"]},
        {"reviews": {}},
        {"reviews": {"a": "Compare list details", "b": "Unknown history"}, "list_conflicts": ["a"]},
    ])
    setup.sync_saved_library = lambda ticket, progress: {
        "items": [{"selected": True}, {"selected": True}], **next(reports)}
    runner = view.background
    assert runner.enable(setup)
    view.hide()
    for expected in ("list_conflict", "chat_conflict", "waiting", "list_review"):
        runner.tick()
        wait(app, lambda: runner.worker is None)
        assert runner.state == expected
        # A list that needs a decision no longer ends background sync for the rest.
        assert runner.timer.isActive()
    assert "Unknown history" in runner.problem and "需要核對" in runner.problem


def test_background_retries_after_an_unexpected_failure(dialog):
    import sqlite3

    app, view, setup = dialog
    setup.files = object()
    outcomes = iter([sqlite3.OperationalError("database is locked"), {"reviews": {}}])

    def exchange(ticket, progress):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return {"items": [{"selected": True}], **outcome}

    setup.sync_saved_library = exchange
    runner = view.background
    assert runner.enable(setup)
    view.hide()
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert runner.state == "error" and runner.timer.isActive()
    assert "database is locked" in runner.problem and "自動重試" in runner.problem
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert runner.state == "waiting" and runner.timer.isActive() and not runner.problem


def test_newer_library_prompts_upgrade_and_stops_background_retry(dialog):
    from paper_daily.drive_sync_files import encode
    from paper_daily.library_directory import Directory

    app, view, setup = dialog
    raw = encode(dict(format="paperfact.library-directory.v9", generation=1,
                      library_id="library", lists=[]))

    def read_newer(*args):
        return Directory.from_bytes(raw, library_id="library")

    setup.sign_in = read_newer
    assert view.sign_in()
    wait(app, lambda: not view.busy)
    assert "Update Paperfact" in view.status.text()
    setup.files = object()
    setup.sync_saved_library = read_newer
    runner = view.background
    assert runner.enable(setup)
    view.hide()
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert runner.state == "format" and not runner.timer.isActive()


def test_first_enrollment_remembers_only_confirmed_lists(dialog, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    app, view, setup = dialog
    setup.files = object()
    rows = [{"id": name, "name": name, "selected": False} for name in ("one", "two")]
    setup.overview = lambda ticket, progress: {
        "account": {"email": "test@example.test"}, "workspaces": [], "lists": rows,
        "library": {"ordinary": True, "first_selection": True, "items": rows},
    }
    assert view._start("refresh", setup.overview)
    wait(app, lambda: not view.busy)
    first, second = (view.directory_lists.item(i) for i in range(2))
    assert first.checkState() == second.checkState() == Qt.CheckState.Checked
    second.setCheckState(Qt.CheckState.Unchecked)
    events = []

    def apply(selected, ticket, progress, *, include_new_content):
        assert include_new_content
        events.append(selected)
        return {"ordinary": True, "items": [dict(row, selected=row["id"] in selected)
                                             for row in rows]}

    setup.apply_library = apply
    def remember(ticket, *, startup):
        events.append(startup)
        if events.count(True) == 1:
            raise ConnectionError("offline")

    setup.remember_library = remember
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    view.save_selection.click()
    assert not events and view.background.service is None
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    view.save_selection.click()
    wait(app, lambda: "Retry automatic sync" in view.status.text() and not view.busy)
    assert "List selection saved" in view.status.text() and not view.startup_sync.isChecked()
    assert view.save_selection.text() == "Retry automatic sync" and view.background.service is None
    view.save_selection.click()
    view.save_selection.click()
    wait(app, lambda: view.startup_sync.isChecked() and not view.busy)
    assert events == [["one"], True, True] and view.background.service is setup
    assert view.directory_lists.item(1).checkState() == Qt.CheckState.Unchecked
    view.pilot.setChecked(True)
    assert view.create.isVisible() and not view.directory_lists.isVisible()
    view.pilot.setChecked(False)
    assert view.directory_lists.isVisible() and not view.create.isVisible()


def test_linked_workspace_opens_original_library_without_exchanging_research(
    dialog, tmp_path, monkeypatch
):
    import sqlite3

    from PySide6.QtWidgets import QFileDialog

    from paper_daily.drive_sync_setup import DriveSetup

    app, view, _ = dialog
    linked = view.session.workspace.path
    setup = DriveSetup(linked)
    from paper_daily.workspace_service import Ticket

    with pytest.raises(PermissionError, match="original local library"):
        setup.reconnect_library(Ticket(), lambda _: None)
    setup.account = {"email": "fixture@example.test"}
    setup.files = SimpleNamespace(workspaces=lambda: [])
    view.service = setup
    assert view._start("refresh", setup.overview)
    wait(app, lambda: not view.busy)
    assert view.open_library.isVisible() and not view.directory_lists.isVisible()
    assert not view.sync_lists.isVisible() and "linked workspace" in view.status.text()
    opened = []
    view.open_workspace = opened.append
    original = tmp_path / "original"
    original.mkdir()
    with sqlite3.connect(original / "papers.db") as conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
    paths = iter(["", str(tmp_path / "missing"), str(linked.parent), str(original)])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: next(paths))
    view.open_library.click()
    assert not opened and not view.disposed
    view.open_library.click()
    assert not opened and "Check the folder" in view.status.text()
    view.open_library.click()
    assert not opened and "also a linked workspace" in view.status.text()
    view.open_library.click()
    assert [target.database_path for target in opened] == [original / "papers.db"]
    assert view.disposed and view.session.workspace.path == linked


def test_minimized_sync_keeps_polling_and_restore_brings_next_exchange_forward(dialog):
    app, view, setup = dialog
    owner = view.owner
    runner = view.background
    setup.files = object()
    calls = []

    def exchange(ticket, progress):
        calls.append(ticket)
        return {"items": [{"id": "a", "selected": True}]}

    setup.sync_saved_library = exchange
    view.hide()
    owner.showMinimized()
    app.processEvents()
    assert runner.enable(setup)
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert len(calls) == 1 and runner.timer.isActive() and runner.timer.interval() == 120000
    owner.showNormal()
    app.processEvents()
    assert 0 <= runner.timer.remainingTime() <= 1100
    runner.tick()
    wait(app, lambda: runner.worker is None)
    assert len(calls) == 2 and runner.timer.interval() == 30000
    runner.stop()


@pytest.mark.parametrize("first,expected", [(True, ["one", "two"]), (False, [])])
def test_startup_login_enrolls_only_a_new_selection(dialog, first, expected):
    app, view, setup = dialog
    rows = [{"id": n, "name": n, "selected": False} for n in ("one", "two")]
    result = {"account": {"email": "test@example.test"}, "workspaces": [], "lists": rows,
              "library": {"ordinary": True, "first_selection": first, "items": rows}}
    events = []

    def login(ticket, progress):
        setup.files = object()
        return result

    def apply(selected, ticket, progress, *, include_new_content):
        assert include_new_content
        events.extend(selected)
        return {"ordinary": True, "items": [dict(row, selected=True) for row in rows]}

    setup.sign_in = login
    setup.apply_library = apply
    setup.remember_library = lambda ticket, *, startup: None
    view.sign_in_for_sync()
    wait(app, lambda: not view.busy)
    assert events == expected
    assert view.startup_sync.isChecked() == first
