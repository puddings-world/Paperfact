"""Deferred callbacks belong to the actual MainWindow's original workspace."""

import json
import os
import sqlite3
import threading
import traceback
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, Qt
from PySide6.QtWidgets import QApplication

from paper_daily import analysis_schedule, llm, store, updates
from paper_daily.desktop import main, ui_state
from paper_daily.desktop.account_status import AccountStatus
from paper_daily.desktop.ai_dialog import AIStatusButton

CONNECT = sqlite3.connect


def path_of(value):
    text = os.fspath(value)
    if text.startswith("file:"):
        text = unquote(urlsplit(text).path)
        if text.startswith("/") and len(text) > 2 and text[2] == ":":
            text = text[1:]
    return Path(text).resolve()


def saved(path):
    with closing(CONNECT(path)) as conn:
        return {
            "papers": list(conn.execute("SELECT id,title FROM papers ORDER BY id")),
            "notes": list(conn.execute("SELECT paper_id,body,kind FROM notes ORDER BY id")),
            "lists": list(conn.execute("SELECT id,name FROM lists ORDER BY id")),
            "members": list(
                conn.execute(
                    "SELECT list_id,paper_id,position FROM list_papers ORDER BY list_id,position"
                )
            ),
        }


def list_ids(window):
    return [window.list_picker.itemData(i) for i in range(window.list_picker.count())]


@pytest.fixture
def owner(tmp_path, monkeypatch, request):
    app = QApplication.instance() or QApplication([])
    paths = {}
    for name in ("alpha", "beta"):
        path = tmp_path / name / "papers.db"
        path.parent.mkdir()
        monkeypatch.setattr(store, "DB_PATH", path)
        store.init_db()
        with store.connect() as conn:
            store.upsert_papers(
                conn,
                [
                    {
                        "id": name,
                        "title": name + " source",
                        "venue": "Fixture",
                        "year": 2026,
                        "source": "test",
                    }
                ],
            )
            conn.execute(
                "INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
                (name, name + " saved note", "2026-10-31T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO lists(id,name,created_at) VALUES(?,?,?)",
                (name + "-list", name + " list", "2026-10-31T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,0,?)",
                (name + "-list", name, "2026-10-31T00:00:00+00:00"),
            )
            store.set_kv(
                conn, analysis_schedule.BATCH, {"at": "2026-10-31T00:00:00+00:00", "ids": [name]}
            )
        paths[name] = path
    monkeypatch.setattr(store, "DB_PATH", paths["alpha"])
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "model.json")
    monkeypatch.setattr(llm, "settings", lambda *a, **k: llm.Settings("none"))
    monkeypatch.setattr(llm, "task_routes", lambda: {})
    monkeypatch.setattr(AccountStatus, "check", lambda *a, **k: None)
    monkeypatch.setattr(AIStatusButton, "refresh", lambda button: button.setText("AI fixture"))
    monkeypatch.setattr(main.ReaderPage, "_check_resources", lambda *_: None)
    monkeypatch.setattr(main.ReaderPage, "_prepare_reading_highlights", lambda *_: None)
    monkeypatch.setattr(updates, "check", lambda *a, **k: None)
    window = main.MainWindow()
    window.show()
    app.processEvents()
    assert window.ready_banner.ids == ["alpha"]
    window.reader_page.note_edit.setPlainText("Unsent Alpha note")
    window.reader_page.ask_box.setText("Unsent Alpha question")
    observation = {"test": request.node.name, "a": str(paths["alpha"]), "b": str(paths["beta"])}
    yield SimpleNamespace(
        app=app, window=window, a=paths["alpha"], b=paths["beta"], observation=observation
    )
    output = os.environ.get("WINDOW_SCOPE_OBSERVATIONS")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(observation, ensure_ascii=False) + "\n")
    monkeypatch.setattr(store, "DB_PATH", paths["alpha"])
    window.reader_page.presentation_pane._generating = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    ui_state.flush()


def capture_connections(monkeypatch):
    opened = []

    def connect(path, *args, **kwargs):
        opened.append(
            {
                "path": str(path_of(path)),
                "stack": [
                    Path(frame.filename).name + ":" + frame.name
                    for frame in traceback.extract_stack(limit=12)[:-1]
                ],
            }
        )
        return CONNECT(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    return opened


@pytest.mark.parametrize("lifetime", ["active", "closed", "close-veto"])
@pytest.mark.parametrize("callback", ["ready", "external-pending"])
def test_queued_old_window_never_opens_B_and_B_can_be_replaced(
    owner, monkeypatch, lifetime, callback
):
    window = owner.window
    original_a, original_b = saved(owner.a), saved(owner.b)
    original_lists = list_ids(window)
    timer = window._ready_poll if callback == "ready" else window.workspace_changes.timer
    if callback == "external-pending":
        window._external_refresh_pending = True
    assert QMetaObject.invokeMethod(timer, "timeout", Qt.ConnectionType.QueuedConnection)
    if lifetime == "close-veto":
        window.reader_page.presentation_pane._generating = True
        assert not window.close()
        assert window.isVisible()
    elif lifetime == "closed":
        assert window.close()
        assert not window.isVisible()
    opened = capture_connections(monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", owner.b)
    owner.app.processEvents()
    # Do the actual native replacement even when a later ownership assertion fails.
    content = owner.b.read_bytes()
    replacement = owner.b.with_suffix(".replacement")
    replacement.write_bytes(content)
    os.replace(replacement, owner.b)
    assert owner.b.read_bytes() == content
    owner.observation.update(
        opened=opened,
        ready=window.ready_banner.ids,
        list_ids=list_ids(window),
        B_replaced=True,
        A_saved_unchanged=saved(owner.a) == original_a,
        B_saved_unchanged=saved(owner.b) == original_b,
    )
    assert saved(owner.a) == original_a
    assert saved(owner.b) == original_b
    assert window.reader_page.note_edit.toPlainText() == "Unsent Alpha note"
    assert window.reader_page.ask_box.text() == "Unsent Alpha question"
    assert str(owner.b) not in [entry["path"] for entry in opened]
    assert window.ready_banner.ids == ["alpha"]
    assert list_ids(window) == original_lists


def test_current_A_notification_timer_still_reports_its_actual_saved_batch(owner, monkeypatch):
    opened = capture_connections(monkeypatch)
    assert QMetaObject.invokeMethod(
        owner.window._ready_poll, "timeout", Qt.ConnectionType.QueuedConnection
    )
    owner.app.processEvents()
    assert owner.window.ready_banner.ids == ["alpha"]
    assert str(owner.a) in [entry["path"] for entry in opened]
    assert str(owner.b) not in [entry["path"] for entry in opened]


@pytest.mark.parametrize("switch", [False, True])
def test_owned_update_timer_does_not_open_another_workspaces_database(owner, monkeypatch, switch):
    banner = owner.window.update_banner
    finished = threading.Event()
    banner._relay.found.connect(lambda _: finished.set(), Qt.ConnectionType.DirectConnection)
    before = saved(owner.b)
    opened = capture_connections(monkeypatch)
    assert QMetaObject.invokeMethod(banner._poll, "timeout", Qt.ConnectionType.QueuedConnection)
    if switch:
        monkeypatch.setattr(store, "DB_PATH", owner.b)
    owner.app.processEvents()
    if banner._checking:
        assert finished.wait(5)
    owner.app.processEvents()
    replacement = owner.b.with_suffix(".update-replacement")
    content = owner.b.read_bytes()
    replacement.write_bytes(content)
    os.replace(replacement, owner.b)
    assert owner.b.read_bytes() == content
    owner.observation.update(
        opened=opened, B_replaced=True, B_saved_unchanged=saved(owner.b) == before
    )
    assert saved(owner.b) == before
    assert str(owner.b) not in [entry["path"] for entry in opened]
    if not switch:
        assert str(owner.a) in [entry["path"] for entry in opened]


@pytest.mark.parametrize("button", ["dismiss", "read"])
def test_stale_ready_banner_never_marks_new_workspace_seen_or_navigates(owner, monkeypatch, button):
    navigated = []
    owner.window.ready_banner.open_paper.connect(navigated.append)
    with closing(CONNECT(owner.b)) as conn:
        before = conn.execute(
            "SELECT value FROM kv WHERE key=?", (analysis_schedule.SEEN,)
        ).fetchone()
    assert before is None
    opened = capture_connections(monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", owner.b)
    getattr(owner.window.ready_banner, button).click()
    with closing(CONNECT(owner.b)) as conn:
        after = conn.execute(
            "SELECT value FROM kv WHERE key=?", (analysis_schedule.SEEN,)
        ).fetchone()
    owner.observation.update(
        opened=opened, B_seen_before=before, B_seen_after=after, navigated=navigated
    )
    assert after == before
    assert not navigated


@pytest.mark.parametrize("callback", ["ready", "external-pending", "update"])
def test_same_path_replacement_is_not_adopted_by_the_existing_window(owner, monkeypatch, callback):
    window = owner.window
    # Close only the old owned observer through its actual drain barrier, so the
    # fixture can replace its owned A once. No GC or replacement retries.
    watcher = window.workspace_changes
    watcher.close()
    assert watcher._lifetime.drained.wait(5)
    if callback == "ready":
        timer = window._ready_poll
    elif callback == "external-pending":
        window._external_refresh_pending = True
        timer = watcher.timer
    else:
        timer = window.update_banner._poll
    assert QMetaObject.invokeMethod(timer, "timeout", Qt.ConnectionType.QueuedConnection)
    replacement = owner.a.with_suffix(".replacement")
    replacement.write_bytes(owner.b.read_bytes())
    os.replace(replacement, owner.a)
    before = saved(owner.a)
    opened = capture_connections(monkeypatch)
    owner.app.processEvents()
    assert not opened
    assert saved(owner.a) == before
    assert window.ready_banner.ids == ["alpha"]
    assert list_ids(window) == ["alpha-list"]
    assert window.reader_page.note_edit.toPlainText() == "Unsent Alpha note"


def test_workspace_owner_checks_only_metadata_and_never_grants_missing_later(tmp_path, monkeypatch):
    from paper_daily.desktop.window_workspace import WindowWorkspace

    missing = tmp_path / "not-created.db"
    monkeypatch.setattr(store, "DB_PATH", missing)
    absent = WindowWorkspace.capture()
    assert not missing.exists() and not absent.current()
    with closing(CONNECT(missing)) as conn:
        conn.execute("CREATE TABLE fixture(value)")
    assert not absent.current()
    current = WindowWorkspace.capture()

    def forbidden(*args, **kwargs):
        raise AssertionError("metadata check attempted database or byte I/O")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(Path, "open", forbidden)
        assert current.current()
        current.close()
        assert not current.current()
        assert not absent.current()


def _clear_drafts(window):
    reader = window.reader_page
    reader.note_edit.clear()
    reader.ask_box.clear()
    reader.presentation_pane.canvas.revise_instruction.clear()
    reader._qa_drafts = {}


def _kv(path):
    with closing(CONNECT(path)) as conn:
        return list(conn.execute("SELECT key,value FROM kv ORDER BY key"))


@pytest.mark.parametrize("draft", ["note", "question", "slide", "revision", "queued-question"])
def test_stale_close_veto_preserves_drafts_and_current_A_can_resume(owner, monkeypatch, draft):
    window, reader = owner.window, owner.window.reader_page
    _clear_drafts(window)
    if draft == "note":
        reader.note_edit.setPlainText("Keep note exact")
    elif draft == "question":
        reader.ask_box.setText("Keep question exact")
    elif draft == "slide":
        reader.presentation_pane._dirty = True
    elif draft == "revision":
        reader.presentation_pane.canvas.revise_instruction.setPlainText("Keep page rewrite request")
    else:
        reader._qa_drafts = {"other-paper": "Keep queued question exact"}
    before = _kv(owner.b)
    opened = capture_connections(monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", owner.b)
    for _ in range(3):
        assert not window.close()
    assert window.isVisible()
    assert "original workspace" in window.ready_banner.label.text()
    assert window._workspace_drafts()
    assert not owner.window._workspace_owner._closed.is_set()
    assert _kv(owner.b) == before
    assert str(owner.b) not in [entry["path"] for entry in opened]
    if draft == "note":
        assert reader.note_edit.toPlainText() == "Keep note exact"
    elif draft == "question":
        assert reader.ask_box.text() == "Keep question exact"
    elif draft == "slide":
        assert reader.presentation_pane._dirty
    elif draft == "revision":
        assert (
            reader.presentation_pane.canvas.revise_instruction.toPlainText()
            == "Keep page rewrite request"
        )
    else:
        assert reader._qa_drafts == {"other-paper": "Keep queued question exact"}
    monkeypatch.setattr(store, "DB_PATH", owner.a)
    assert QMetaObject.invokeMethod(
        window._ready_poll, "timeout", Qt.ConnectionType.QueuedConnection
    )
    owner.app.processEvents()
    assert window.ready_banner.ids == ["alpha"] and window.ready_banner.read.isEnabled()
    assert window._workspace_owner.current()


def test_stale_no_draft_close_skips_all_global_persistence_after_busy_barrier(owner, monkeypatch):
    window, reader = owner.window, owner.window.reader_page
    _clear_drafts(window)
    before = _kv(owner.b)
    calls = []
    actual_save, actual_remember, actual_flush = (
        reader.presentation_pane.save_changes,
        window.remember,
        ui_state.flush,
    )

    def save():
        calls.append("save")
        return actual_save()

    def remember(*args):
        calls.append("remember")
        return actual_remember(*args)

    def flush():
        calls.append("flush")
        return actual_flush()

    with monkeypatch.context() as patch:
        patch.setattr(reader.presentation_pane, "save_changes", save)
        patch.setattr(window, "remember", remember)
        patch.setattr(ui_state, "flush", flush)
        patch.setattr(store, "DB_PATH", owner.b)
        reader.presentation_pane._generating = True
        assert not window.close()
        assert not window._workspace_owner._closed.is_set()
        reader.presentation_pane._generating = False
        assert window.close()
        assert not window.isVisible()
        assert not calls
        assert not window._ready_poll.isActive() and not window.workspace_changes.timer.isActive()
        assert _kv(owner.b) == before


@pytest.mark.parametrize("operation", ["close", "restart", "update"])
def test_context_changed_inside_save_cannot_persist_new_workspace_state(
    owner, monkeypatch, operation
):
    window, reader = owner.window, owner.window.reader_page
    before = _kv(owner.b)

    def save_then_context_changes():
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        return True

    monkeypatch.setattr(reader.presentation_pane, "save_changes", save_then_context_changes)
    if operation == "close":
        assert not window.close()
    elif operation == "restart":
        assert not window._prepare_restart()
    else:
        assert not window._prepare_update()
    assert _kv(owner.b) == before
    assert reader.note_edit.toPlainText() == "Unsent Alpha note"
    assert reader.ask_box.text() == "Unsent Alpha question"
    assert window.isVisible()


def test_context_change_during_state_collection_cannot_queue_layout_to_B(owner, monkeypatch):
    window, pane = owner.window, owner.window.reader_page.presentation_pane
    before = _kv(owner.b)
    actual = pane.workspace_state

    def changed_state():
        value = actual()
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        return value

    monkeypatch.setattr(pane, "workspace_state", changed_state)
    assert not window.close()
    assert _kv(owner.b) == before
    with ui_state._lock:
        assert not any(path.resolve() == owner.b.resolve() for path, _key in ui_state._pending)


def test_notification_scope_is_rechecked_after_its_bound_read(owner, monkeypatch):
    window = owner.window
    window.ready_banner.ids = []
    actual = analysis_schedule.unseen

    def switch_after_read(conn):
        ids = actual(conn)
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        return ids

    opened = capture_connections(monkeypatch)
    monkeypatch.setattr(analysis_schedule, "unseen", switch_after_read)
    assert QMetaObject.invokeMethod(
        window._ready_poll, "timeout", Qt.ConnectionType.QueuedConnection
    )
    owner.app.processEvents()
    assert window.ready_banner.ids == []
    assert str(owner.b) not in [entry["path"] for entry in opened]


def test_deferred_update_admission_deduplicates_drains_stale_and_retries_A(owner, monkeypatch):
    from paper_daily.desktop import update_banner

    jobs = []

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            jobs.append(self.target)

    monkeypatch.setattr(update_banner, "threading", SimpleNamespace(Thread=Thread))
    banner = owner.window.update_banner
    opened = capture_connections(monkeypatch)
    banner.check_in_background()
    banner.check_in_background()
    assert len(jobs) == 1 and banner._checking
    monkeypatch.setattr(store, "DB_PATH", owner.b)
    jobs[0]()
    owner.app.processEvents()
    assert not banner._checking and not opened
    monkeypatch.setattr(store, "DB_PATH", owner.a)
    banner.check_in_background()
    assert len(jobs) == 2
    jobs[1]()
    owner.app.processEvents()
    assert not banner._checking
    assert str(owner.a) in [entry["path"] for entry in opened]
    assert str(owner.b) not in [entry["path"] for entry in opened]


def test_original_update_read_can_drain_A_without_stale_UI_or_any_B_read(owner, monkeypatch):
    banner = owner.window.update_banner
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    synthetic = updates.Release("9.9.9", "Fixture", "", "https://fixture/release", {})

    def check(conn, **kwargs):
        started.set()
        assert release.wait(5)
        store.set_kv(conn, "updates.synthetic", "finished in original A")
        return synthetic

    monkeypatch.setattr(updates, "check", check)
    banner._relay.found.connect(lambda *_: finished.set(), Qt.ConnectionType.DirectConnection)
    opened = capture_connections(monkeypatch)
    try:
        banner.check_in_background()
        assert started.wait(5)
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        release.set()
        assert finished.wait(5)
        owner.app.processEvents()
        assert not banner._checking
        assert banner.release is None and banner.isHidden()
        assert str(owner.b) not in [entry["path"] for entry in opened]
        with closing(CONNECT(owner.a)) as conn:
            assert conn.execute(
                "SELECT value FROM kv WHERE key='updates.synthetic'"
            ).fetchone() == ('"finished in original A"',)
        with closing(CONNECT(owner.b)) as conn:
            assert (
                conn.execute("SELECT value FROM kv WHERE key='updates.synthetic'").fetchone()
                is None
            )
    finally:
        release.set()
        assert finished.wait(5)
        owner.app.processEvents()


@pytest.mark.parametrize("switch", ["before", "inside-prepare"])
def test_verified_update_never_launches_installer_after_window_scope_changes(
    owner, monkeypatch, tmp_path, switch
):
    banner = owner.window.update_banner
    started = []
    banner.release = updates.Release("9.9.9", "Fixture", "", "https://fixture/release", {})
    banner._ready = tmp_path / "already-verified-fixture.exe"
    monkeypatch.setattr(updates, "launch_installer", started.append)
    if switch == "before":
        monkeypatch.setattr(store, "DB_PATH", owner.b)
    else:

        def prepare():
            owner.window._closing_with_recovery = True
            monkeypatch.setattr(store, "DB_PATH", owner.b)
            return True

        banner._prepare_install = prepare
    banner._verified()
    assert not started and not banner._installing
    assert not getattr(owner.window, "_closing_with_recovery", False)


def test_manual_update_dialog_does_not_remain_disabled_after_a_stale_check(owner, monkeypatch):
    from paper_daily import build_identity
    from paper_daily.desktop import update_banner
    from paper_daily.desktop.version_dialog import VersionDialog

    jobs = []

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            jobs.append(self.target)

    monkeypatch.setattr(update_banner, "threading", SimpleNamespace(Thread=Thread))
    monkeypatch.setattr(build_identity, "describe", lambda info: "Fixture build")
    dialog = VersionDialog(owner.window, owner.window.update_banner, None, lambda: None)
    try:
        dialog.check_button.click()
        assert not dialog.check_button.isEnabled() and len(jobs) == 1
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        jobs[0]()
        owner.app.processEvents()
        assert dialog.check_button.isEnabled()
        assert "original workspace" in dialog.status.text()
        assert owner.window.update_banner.release is None
    finally:
        dialog.close()
        dialog.deleteLater()
        owner.app.processEvents()


def test_actual_old_main_and_bound_watcher_do_not_open_the_minimal_foreign_fixture(
    owner, monkeypatch, tmp_path
):
    from paper_daily.desktop.workspace_changes import WorkspaceChanges

    foreign = tmp_path / "minimal-B.sqlite"
    with closing(CONNECT(foreign)) as conn:
        conn.executescript(
            "CREATE TABLE workspace_revision(id INTEGER PRIMARY KEY, revision INTEGER);"
            "INSERT INTO workspace_revision VALUES(1,9);"
            "CREATE TABLE integration_changes(id INTEGER PRIMARY KEY);"
        )
    watcher = WorkspaceChanges()
    try:
        assert QMetaObject.invokeMethod(
            owner.window._ready_poll, "timeout", Qt.ConnectionType.QueuedConnection
        )
        opened = capture_connections(monkeypatch)
        monkeypatch.setattr(store, "DB_PATH", foreign)
        watcher.poll()
        for _ in range(20):
            watcher.poll_in_background()
        owner.app.processEvents()
        content = foreign.read_bytes()
        replacement = foreign.with_suffix(".replacement")
        replacement.write_bytes(content)
        os.replace(replacement, foreign)
        assert foreign.read_bytes() == content
        assert str(foreign) not in [entry["path"] for entry in opened]
        assert owner.window.ready_banner.ids == ["alpha"]
        assert not watcher._reading
    finally:
        watcher.close()
        assert watcher._lifetime.drained.wait(5)
        watcher.deleteLater()
        owner.app.processEvents()
