"""Bounded watcher ownership/lifetime against actual isolated SQLite databases."""

import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

from paper_daily import store
from paper_daily.desktop import workspace_changes
from paper_daily.desktop.workspace_changes import WorkspaceChanges


def database(path, revision=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            "CREATE TABLE workspace_revision(id INTEGER PRIMARY KEY,revision INTEGER);"
            f"INSERT INTO workspace_revision VALUES(1,{revision});"
            "CREATE TABLE integration_changes(id INTEGER PRIMARY KEY);"
        )
    return path


def selected_path(value):
    value = os.fspath(value)
    if value.startswith("file:"):
        value = unquote(urlsplit(value).path)
        if value.startswith("/") and len(value) > 2 and value[2] == ":":
            value = value[1:]
    return Path(value).resolve()


def settle(app, condition, timeout=5):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert condition(), "Own watcher did not drain"


@pytest.fixture
def pair(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    a = database(tmp_path / "a" / "research.sqlite")
    b = database(tmp_path / "b" / "research.sqlite", revision=9)
    monkeypatch.setattr(store, "DB_PATH", a)
    watchers = []

    def observer(parent=None):
        watcher = WorkspaceChanges(parent)
        watcher.timer.stop()
        watchers.append(watcher)
        return watcher

    yield SimpleNamespace(app=app, a=a, b=b, observer=observer)
    for watcher in watchers:
        try:
            close = getattr(watcher, "close", None)
            if close is not None:
                close()
            else:
                watcher.timer.stop()
                watcher._reader.shutdown(wait=False, cancel_futures=True)
            settle(app, lambda watcher=watcher: not watcher._reading)
            watcher.deleteLater()
        except RuntimeError:  # A test explicitly destroyed this QObject.
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def change(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE workspace_revision SET revision=revision+1 WHERE id=1")


def test_existing_watcher_never_opens_next_global_workspace_and_B_can_be_replaced(
    pair, monkeypatch
):
    watcher = pair.observer()
    before = watcher.revision
    notifications, opened = [], []
    watcher.changed.connect(lambda: notifications.append(True))
    original = sqlite3.connect

    def connect(path, *args, **kwargs):
        opened.append(selected_path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(workspace_changes.sqlite3, "connect", connect)
    monkeypatch.setattr(store, "DB_PATH", pair.b)
    watcher.poll()
    for _ in range(20):
        watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert pair.b not in opened
    assert not notifications and watcher.revision == before
    replacement = pair.b.with_suffix(".replacement")
    data = pair.b.read_bytes()
    replacement.write_bytes(data)
    os.replace(replacement, pair.b)  # Actual native one-shot replacement; no mock/retry.
    assert pair.b.read_bytes() == data


def test_revision_label_cannot_mix_global_B_with_bytes_read_from_A(pair, monkeypatch):
    watcher = pair.observer()
    original = sqlite3.connect

    def connect(path, *args, **kwargs):
        conn = original(path, *args, **kwargs)
        assert selected_path(path) == pair.a
        monkeypatch.setattr(store, "DB_PATH", pair.b)
        return conn

    monkeypatch.setattr(workspace_changes.sqlite3, "connect", connect)
    result = watcher._revision()  # Preserve the no-argument seam.
    assert result is None or result[0] == str(pair.a)


def test_queued_old_delivery_is_rejected_after_global_switch(pair, monkeypatch):
    watcher = pair.observer()
    before = watcher.revision
    notifications = []
    queued = threading.Event()
    watcher.changed.connect(lambda: notifications.append(True))
    watcher._read.connect(lambda _: queued.set(), Qt.ConnectionType.DirectConnection)
    change(pair.a)
    watcher.poll_in_background()
    assert queued.wait(5)  # The GUI has not processed its queued delivery.
    monkeypatch.setattr(store, "DB_PATH", pair.b)
    settle(pair.app, lambda: not watcher._reading)
    assert not notifications and watcher.revision == before


def test_missing_initial_file_never_creates_or_attaches_to_a_later_database(pair, monkeypatch):
    missing = pair.a.with_name("missing.sqlite")
    monkeypatch.setattr(store, "DB_PATH", missing)
    watcher = pair.observer()
    watcher.poll()
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert not missing.exists()
    database(missing, revision=50)
    notifications, opened = [], []
    watcher.changed.connect(lambda: notifications.append(True))
    original = sqlite3.connect

    def connect(path, *args, **kwargs):
        opened.append(selected_path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(workspace_changes.sqlite3, "connect", connect)
    watcher.poll()
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert not opened and not notifications and watcher.revision is None


def test_deleted_file_is_not_recreated_and_same_path_replacement_is_not_followed(pair, monkeypatch):
    watcher = pair.observer()
    before = watcher.revision
    notifications, opened = [], []
    watcher.changed.connect(lambda: notifications.append(True))
    replacement = database(pair.a.with_suffix(".replacement"), revision=77)
    pair.a.unlink()
    watcher.poll()
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert not pair.a.exists()
    os.replace(replacement, pair.a)
    original = sqlite3.connect

    def connect(path, *args, **kwargs):
        opened.append(selected_path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(workspace_changes.sqlite3, "connect", connect)
    watcher.poll()
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert not opened and not notifications and watcher.revision == before


def test_queued_old_delivery_is_rejected_after_same_path_replacement(pair):
    watcher = pair.observer()
    before = watcher.revision
    notifications, queued = [], threading.Event()
    watcher.changed.connect(lambda: notifications.append(True))
    watcher._read.connect(lambda _: queued.set(), Qt.ConnectionType.DirectConnection)
    change(pair.a)
    watcher.poll_in_background()
    assert queued.wait(5)
    replacement = database(pair.a.with_suffix(".replacement"), revision=90)
    os.replace(replacement, pair.a)
    settle(pair.app, lambda: not watcher._reading)
    assert not notifications and watcher.revision == before


def test_close_during_actual_A_read_drains_without_B_open_notification_or_new_jobs(
    pair, monkeypatch
):
    watcher = pair.observer()
    entered, release = threading.Event(), threading.Event()
    original = sqlite3.connect
    opened, notifications = [], []

    def connect(path, *args, **kwargs):
        conn = original(path, *args, **kwargs)
        opened.append(selected_path(path))
        entered.set()
        assert release.wait(5)
        return conn

    watcher.changed.connect(lambda: notifications.append(True))
    monkeypatch.setattr(workspace_changes.sqlite3, "connect", connect)
    watcher.poll_in_background()
    try:
        assert entered.wait(5)
        assert not watcher.close()
        assert not watcher.timer.isActive()
        monkeypatch.setattr(store, "DB_PATH", pair.b)
        for _ in range(20):
            watcher.poll()
            watcher.poll_in_background()
        replacement = pair.b.with_suffix(".replacement")
        content = pair.b.read_bytes()
        replacement.write_bytes(content)
        os.replace(replacement, pair.b)
        assert pair.b.read_bytes() == content
    finally:
        release.set()
    settle(pair.app, lambda: not watcher._reading)
    assert watcher.close() and opened == [pair.a] and not notifications
    watcher.timer.timeout.emit()
    assert opened == [pair.a]


def test_close_before_queued_delivery_discards_notification(pair):
    watcher = pair.observer()
    before = watcher.revision
    queued, notifications = threading.Event(), []
    watcher._read.connect(lambda _: queued.set(), Qt.ConnectionType.DirectConnection)
    watcher.changed.connect(lambda: notifications.append(True))
    change(pair.a)
    watcher.poll_in_background()
    assert queued.wait(5)
    assert watcher.close()
    settle(pair.app, lambda: not watcher._reading)
    assert not notifications and watcher.revision == before


def test_persistent_reader_remains_single_flight_and_reuses_worker_after_commit(pair, monkeypatch):
    watcher = pair.observer()
    entered, release = threading.Event(), threading.Event()
    original = watcher._revision
    reads, notifications = [], []

    def revision():
        reads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return original()

    monkeypatch.setattr(watcher, "_revision", revision)
    watcher.changed.connect(lambda: notifications.append(threading.get_ident()))
    change(pair.a)
    watcher.poll_in_background()
    try:
        assert entered.wait(5)
        for _ in range(20):
            watcher.poll_in_background()
        assert len(reads) == 1
    finally:
        release.set()
    settle(pair.app, lambda: not watcher._reading)
    change(pair.a)
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert len(reads) == 2 and reads[0] == reads[1] != threading.get_ident()
    assert notifications == [threading.get_ident()] * 2


def test_reader_submit_failure_allows_explicit_retry_without_duplicate_result(pair, monkeypatch):
    watcher = pair.observer()
    original = watcher._reader.submit
    notifications = []
    watcher.changed.connect(lambda: notifications.append(True))
    monkeypatch.setattr(watcher._reader, "submit", lambda *_: (_ for _ in ()).throw(RuntimeError()))
    watcher.poll_in_background()
    assert not watcher._reading and not notifications
    monkeypatch.setattr(watcher._reader, "submit", original)
    change(pair.a)
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert notifications == [True]


def test_destroyed_QObject_with_active_read_cannot_emit_or_schedule_more_work(pair, monkeypatch):
    parent = QWidget()
    watcher = pair.observer(parent)
    entered, release = threading.Event(), threading.Event()
    original = watcher._revision
    calls, notifications = [], []

    def revision():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return original()

    monkeypatch.setattr(watcher, "_revision", revision)
    watcher.changed.connect(lambda: notifications.append(True))
    watcher.poll_in_background()
    try:
        assert entered.wait(5)
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pair.app.processEvents()
    finally:
        release.set()
    settle(pair.app, lambda: not watcher._reading)
    assert calls == [True] and not notifications


def test_read_failure_does_not_leave_observer_busy_or_block_later_commit(pair, monkeypatch):
    watcher = pair.observer()
    original = watcher._revision
    notifications = []
    watcher.changed.connect(lambda: notifications.append(True))

    def failed():
        raise RuntimeError("Synthetic metadata reader failure")

    monkeypatch.setattr(watcher, "_revision", failed)
    watcher.poll()
    assert not watcher._reading
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    monkeypatch.setattr(watcher, "_revision", original)
    change(pair.a)
    watcher.poll_in_background()
    settle(pair.app, lambda: not watcher._reading)
    assert notifications == [True]


def test_close_cancels_admitted_read_queued_behind_busy_persistent_worker(pair, monkeypatch):
    watcher = pair.observer()
    occupied, release = threading.Event(), threading.Event()
    calls, notifications = [], []

    def hold_worker():
        occupied.set()
        assert release.wait(5)

    busy = watcher._reader.submit(hold_worker)
    try:
        assert occupied.wait(5)
        monkeypatch.setattr(watcher, "_revision", lambda: calls.append(True))
        watcher.changed.connect(lambda: notifications.append(True))
        watcher.poll_in_background()
        assert watcher.close()  # Its own queued read was cancelled without waiting.
    finally:
        release.set()
        busy.result(timeout=5)
    settle(pair.app, lambda: not watcher._reading)
    assert not calls and not notifications
