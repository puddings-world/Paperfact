"""Retire pinned reviews without permission to refresh a foreign workspace."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import MethodType, SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
from test_research_review import candidate
from test_research_review import workspace as workspace_fixture
from test_review_dialog import app as app_fixture
from test_review_dialog import opened

from paper_daily import store
from paper_daily.desktop.main import MainWindow
from paper_daily.desktop.window_workspace import WindowWorkspace

workspace, app = workspace_fixture, app_fixture
CONNECT = sqlite3.connect


def rows(path, sql):
    with closing(CONNECT(path)) as conn:
        return conn.execute(sql).fetchall()


def drafts(path):
    with closing(CONNECT(path)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_drafts'"
        ).fetchone():
            return []
        return conn.execute("SELECT body FROM research_review_drafts ORDER BY rowid").fetchall()


def database_path(value):
    text = os.fspath(value)
    if text.startswith("file:"):
        text = unquote(urlsplit(text).path)
        if text.startswith("/") and len(text) > 2 and text[2] == ":":
            text = text[1:]
    return Path(text).resolve()


@pytest.mark.parametrize("background", [False, True], ids=["explicit-poll", "timer-poll"])
@pytest.mark.parametrize("failure", [False, True], ids=["save-ok", "save-fails-retry"])
@pytest.mark.parametrize("closed", [False, True], ids=["live-owner", "accepted-closed-owner"])
def test_foreign_workspace_cleanup_saves_only_original_draft_and_never_refreshes_target(
    app, workspace, monkeypatch, background, failure, closed
):
    path, client = workspace
    candidate(path)
    owner = WindowWorkspace.capture()
    dialog = opened(app, path)
    dialog.draft.setPlainText("Keep this original-workspace draft")
    assert dialog.dirty
    pending = client.journal.pending()
    before_drafts = drafts(path)
    target = path.parent / "other.sqlite"
    with closing(CONNECT(target)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) "
            "VALUES('other','Other','other',2026,'Fixture','fixture')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('other','Target stays intact','now')"
        )
    target_bytes = target.read_bytes()
    target_rows = rows(target, "SELECT paper_id,body FROM notes")
    attempts = []
    save = dialog.service.save_draft

    def unavailable(*args, **kwargs):
        attempts.append(True)
        raise OSError("Fixture original-workspace disk failure")

    if failure:
        monkeypatch.setattr(dialog.service, "save_draft", unavailable)

    def forbidden(*args, **kwargs):
        pytest.fail("A stale window must not poll or refresh the foreign workspace")

    host = SimpleNamespace(
        _workspace_owner=owner,
        _review_dialog=dialog,
        workspace_changes=SimpleNamespace(poll=forbidden, poll_in_background=forbidden),
        _external_refresh_pending=True,
        _external_lists_changed=forbidden,
    )
    host._close_stale_review = MethodType(MainWindow._close_stale_review, host)
    monkeypatch.setattr(store, "DB_PATH", target)
    if closed:
        owner.close()
    foreign_connections = []

    def scoped_connect(database, *args, **kwargs):
        if database_path(database) == target.resolve():
            foreign_connections.append(True)
            pytest.fail("Review retirement must not open the foreign database")
        return CONNECT(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", scoped_connect)
    try:
        MainWindow._poll_external_lists(host, background=background)
        if closed:
            assert not dialog.disposed and not dialog.service.closed
            assert not attempts and drafts(path) == before_drafts
            assert dialog.draft.toPlainText() == "Keep this original-workspace draft"
        else:
            if failure:
                assert attempts == [True]
                assert not dialog.disposed and not dialog.service.closed
                assert dialog.isVisible()
                assert dialog.draft.toPlainText() == "Keep this original-workspace draft"
                assert drafts(path) == before_drafts and "not saved" in dialog.status.text()
                monkeypatch.setattr(dialog.service, "save_draft", save)
                MainWindow._poll_external_lists(host, background=background)
            assert dialog.disposed and dialog.service.closed
            assert drafts(path) == [("Keep this original-workspace draft",)]
            MainWindow._poll_external_lists(host, background=background)
            assert drafts(path) == [("Keep this original-workspace draft",)]
        assert not foreign_connections
        assert target.read_bytes() == target_bytes
        assert rows(target, "SELECT paper_id,body FROM notes") == target_rows
        assert rows(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]
        assert client.journal.pending() == pending
    finally:
        monkeypatch.setattr(dialog.service, "save_draft", save)
        if not dialog.disposed:
            dialog.reject()
        dialog.deleteLater()
        app.processEvents()
