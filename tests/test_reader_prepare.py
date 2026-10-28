"""Opening a paper switches the page at once and fills in its typeset parts when
they are ready. They were typeset on the window's thread, which froze it for a
third of a second to a second and a half per paper."""

import os
import sys
import threading
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import llm, store  # noqa: E402
from paper_daily.desktop import fonts  # noqa: E402
from paper_daily.desktop import main as m  # noqa: E402
from paper_daily.desktop.off_thread import OffThread  # noqa: E402


def _settle(prepare, app):
    assert prepare.wait()
    for _ in range(5):
        app.processEvents()


def test_only_the_newest_request_of_a_kind_is_applied():
    app = QApplication.instance() or QApplication([])
    prepare = OffThread()
    applied, gate = [], threading.Event()

    def slow():
        gate.wait(5)
        return "first"

    prepare.run("dive", slow, applied.append)
    prepare.run("dive", lambda: "second", applied.append)
    prepare.run("chat", lambda: "chat", applied.append)
    gate.set()
    _settle(prepare, app)
    assert applied == ["second", "chat"]
    prepare.run("dive", lambda: "third", applied.append)
    prepare.cancel("dive")
    _settle(prepare, app)
    assert applied == ["second", "chat"]


def test_a_failure_on_the_worker_is_raised_on_the_windows_thread(monkeypatch):
    app = QApplication.instance() or QApplication([])
    prepare = OffThread()
    seen, applied = [], []
    monkeypatch.setattr(sys, "excepthook", lambda kind, error, tb: seen.append(
        (error, threading.current_thread() is threading.main_thread())
    ))

    def broken():
        raise ValueError("no such page")

    prepare.run("dive", broken, applied.append)
    _settle(prepare, app)
    assert applied == []
    assert [(str(error), on_main) for error, on_main in seen] == [("no such page", True)]


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    m.style(app)
    fonts.load()
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(conn, [
            dict(id=pid, title=f"Paper {pid}", venue="ICLR", year=2026, source="test")
            for pid in ("a", "b")
        ])
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('l','A list','now')")
        for position, pid in enumerate(("a", "b")):
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES (?,?,?,'now')",
                ("l", pid, position),
            )
    monkeypatch.setattr(m.ReaderPage, "_check_resources", lambda self: None)
    monkeypatch.setattr(m.ReaderPage, "_prepare_reading_highlights", lambda self: None)
    win = m.MainWindow()
    monkeypatch.setattr(win, "top_up_dives", lambda *a, **k: None)
    win.show()
    win.data.save_dive("a", "## Method A\n\nDive of the first paper.")
    win.data.save_dive("b", "## Method B\n\nDive of the second paper.")
    yield win, app
    win.reader_page.prepare.wait()
    win.close()
    win.deleteLater()
    app.processEvents()


def _dive(win):
    return win.reader_page.dive_view._body


def test_a_paper_opens_before_its_dive_is_typeset_and_never_shows_the_last_one(
    window, monkeypatch
):
    win, app = window
    reader = win.reader_page
    win.open_paper("a")
    _settle(reader.prepare, app)
    assert "Dive of the first paper." in _dive(win)

    from paper_daily.desktop import reading

    typeset, gate = reading.render, threading.Event()

    def slow_render(*args, **kwargs):
        gate.wait(5)
        return typeset(*args, **kwargs)

    monkeypatch.setattr(reading, "render", slow_render)
    started = time.perf_counter()
    win.open_paper("b")
    assert time.perf_counter() - started < 2
    assert win.stack.currentWidget() is reader and reader.paper.id == "b"
    assert "Dive of the first paper." not in _dive(win)
    gate.set()
    _settle(reader.prepare, app)
    assert "Dive of the second paper." in _dive(win)


def test_a_paper_left_before_its_dive_was_ready_does_not_overwrite_the_next(
    window, monkeypatch
):
    win, app = window
    reader = win.reader_page
    from paper_daily.desktop import reading

    typeset, gate = reading.render, threading.Event()

    def held_for_a(body, *args, **kwargs):
        if "Method A" in body:
            gate.wait(5)
        return typeset(body, *args, **kwargs)

    monkeypatch.setattr(reading, "render", held_for_a)
    win.open_paper("a")
    win.open_paper("b")
    gate.set()
    _settle(reader.prepare, app)
    assert "Dive of the second paper." in _dive(win)
    assert "Dive of the first paper." not in _dive(win)


def test_the_analysis_bar_reads_its_status_off_the_windows_thread(window, monkeypatch):
    # Whether the highlights are current is checked against the PDF's whole text.
    win, app = window
    from paper_daily import analyze

    status, gate, threads = analyze.status, threading.Event(), []

    def slow_status(conn, paper_id):
        threads.append(threading.current_thread() is threading.main_thread())
        gate.wait(5)
        return status(conn, paper_id)

    monkeypatch.setattr(analyze, "status", slow_status)
    started = time.perf_counter()
    win.open_paper("a")
    assert time.perf_counter() - started < 2
    gate.set()
    bar = win.reader_page.analysis_bar
    _settle(bar._status, app)
    assert threads and not any(threads)
    assert "講解" in bar.label.text()
