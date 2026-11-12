"""Manual first enrollment through real Qt: source stays, fresh copy is editable."""

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from test_manual_deck_enrollment import archived_and_active, baseline
from test_manual_deck_enrollment import no_external as no_external
from test_manual_deck_enrollment import scientific as scientific
from test_manual_deck_enrollment import source as source
from test_retained_original_ui import settle

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import presentations, retained_originals, store
from paper_daily.desktop.enrollment_dialog import EnrollmentDialog
from paper_daily.document_reader import from_workspace
from paper_daily.research_review import ResearchReview
from paper_daily.sync_deck_publication import publication_scope


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def views(app, source):
    created = []

    def make(*, language="zh-TW", current_path=None):
        opened = []
        view = EnrollmentDialog(
            source["database"], language=language, current_path=current_path,
            open_workspace=opened.append,
        )
        view.opened = opened
        created.append(view)
        view.show()
        return view

    yield make
    for view in created:
        if view.busy:
            view.cancel()
            settle(app, lambda view=view: not view.busy, timeout=30)
        if not view.disposed:
            view.close()
        settle(app, lambda view=view: view.disposed)
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def check(app, view, source):
    view.output_path.setText(str(source["output"]))
    view.backup_path.setText(str(source["backup"]))
    assert view.check_content()
    settle(app, lambda: not view.busy, timeout=30)
    assert view.preview is not None and view.preview["supported"], view.coverage.toPlainText()
    assert view.prepare_button.isEnabled()
    return view.preview


def _verify_copy(source, result):
    client, original, operation = archived_and_active(result)
    assert original["raw"] == source["saved_json"]
    assert len(original["raw"]["figures"]) == 3 and len(original["images"]) == 2
    assert operation["payload"]["source_document_hash"] is None
    with publication_scope(client):
        loaded = presentations.load_deck("local-paper", "guide")
        assert loaded.title == "Prior manual current"
        for identity, data in original["images"].items():
            assert presentations.figure_bytes(loaded, identity) == data
    reader = from_workspace(Path(result["database"]))
    try:
        assert reader.resolve("local-paper").path.read_bytes() == source["primary_bytes"]
    finally:
        reader.close()
    review = ResearchReview(Path(result["database"]))
    try:
        items = [row for row in review.page(limit=100)["items"] if row["origin"] == "enrolled_deck"]
        assert len(items) == 1
        with closing(review._connect()) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            assert catalog.TABLE not in tables
        view = review.prepare_file(review.preview("enrolled_deck", items[0]["id"]))
        assert view.data["current"]["title"] == "Prior manual current"
        assert view.data["retained"] == source["expected"]["deck"]
        assert len(view.data["image_manifest"]) == 4
        sha = source["expected"]["source_document_hash"]
        proof = retained_originals.prepare(review, view, sha)
        assert proof.data == source["expected"]["original_bytes"][sha]
    finally:
        review.close()
    return client


def verify_copy(source, result):
    captured = dict(
        source, saved_json=json.loads(source["saved"].read_bytes()),
        primary_bytes=source["primary"].read_bytes(),
    )
    original_open = Path.open
    source_root = source["root"].resolve()

    def independent(path, *args, **kwargs):
        if path.resolve().is_relative_to(source_root):
            pytest.fail("Prepared copy tried to open a file in its source workspace")
        return original_open(path, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", independent)
        return _verify_copy(captured, result)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_actual_manual_preview_prepare_keeps_complete_copy_and_opens_only_explicitly(
    source, app, views, monkeypatch, language
):
    view = views(language=language)
    before = baseline(source)
    planned, prepared = view.service.plan, view.service.prepare
    calls = []

    def plan(*args, **kwargs):
        calls.append("plan")
        return planned(*args, **kwargs)

    def prepare(*args, **kwargs):
        calls.append("prepare")
        return prepared(*args, **kwargs)

    monkeypatch.setattr(view.service, "plan", plan)
    monkeypatch.setattr(view.service, "prepare", prepare)
    view.output_path.setText(str(source["output"]))
    view.backup_path.setText(str(source["backup"]))
    for _ in range(25):
        view.check_button.click()
    settle(app, lambda: not view.busy, timeout=30)
    assert view.preview["supported"] and calls == ["plan"]
    assert view.t["manual_decks"] + ": 1" in view.coverage.toPlainText()
    assert view.t["retained_decks"] + ": 1" in view.coverage.toPlainText()
    assert baseline(source) == before and not view.opened
    for _ in range(25):
        view.prepare_button.click()
    settle(app, lambda: not view.busy, timeout=45)
    assert calls == ["plan", "prepare"] and view.result is not None, view.status.text()
    assert not view.result["uploaded"] and not view.result["adopted"]
    assert source["output"].is_dir() and source["backup"].is_file()
    assert view.status.text() == view.t["prepared"] and baseline(source) == before
    assert view.open_button.isEnabled() and not view.opened
    verify_copy(source, view.result)
    for _ in range(25):
        view.open_button.click()
    assert len(view.opened) == 1 and not view.open_button.isEnabled()
    assert view.opened[0].database_path == Path(view.result["database"])
    assert view.guard.path == source["database"] and baseline(source) == before


def test_manual_prepare_failure_preserves_destinations_and_request_then_explicit_retry(
    source, app, views, monkeypatch
):
    view = views()
    check(app, view, source)
    before, prepare, requests = baseline(source), view.service.prepare, []

    def failed(*args, **kwargs):
        requests.append(kwargs["request_id"])
        raise sqlite3.OperationalError("PRIVATE RAW RESEARCH PATH")

    monkeypatch.setattr(view.service, "prepare", failed)
    for _ in range(25):
        view.prepare_button.click()
    settle(app, lambda: not view.busy)
    assert view.status.text() == view.t["failure"]
    assert "PRIVATE" not in view.status.text() and len(requests) == 1
    assert view.result is None and view.prepare_button.isEnabled()
    assert not source["output"].exists() and not source["backup"].exists()
    assert baseline(source) == before

    def retried(*args, **kwargs):
        requests.append(kwargs["request_id"])
        return prepare(*args, **kwargs)

    monkeypatch.setattr(view.service, "prepare", retried)
    view.prepare_button.click()
    settle(app, lambda: not view.busy, timeout=45)
    assert requests == [requests[0], requests[0]] and view.result is not None
    verify_copy(source, view.result)
    assert baseline(source) == before and not view.opened


@pytest.mark.parametrize("changed", ["cancel", "close", "workspace"])
def test_held_manual_prepare_does_not_publish_after_cancel_close_or_workspace_change(
    source, app, views, monkeypatch, tmp_path, changed
):
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
        conn.commit()
    other_before = other.read_bytes()
    selected = [source["database"]]
    view = views(current_path=lambda: selected[0])
    check(app, view, source)
    before = baseline(source)
    entered, release = threading.Event(), threading.Event()
    prepare, requests = view.service.prepare, []

    def held(*args, **kwargs):
        requests.append(kwargs["request_id"])
        entered.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(view.service, "prepare", held)
    view.prepare_button.click()
    try:
        settle(app, entered.is_set)
        for _ in range(25):
            view.prepare_button.click()
        assert len(requests) == 1
        if changed == "cancel":
            view.cancel()
        elif changed == "close":
            assert not view.close() and not view.disposed
        else:
            selected[0] = other
            assert not view._check_source()
    finally:
        release.set()
    settle(app, lambda: not view.busy, timeout=30)
    if changed == "close":
        settle(app, lambda: view.disposed)
    assert view.result is None and not view.opened
    assert not source["output"].exists() and not source["backup"].exists()
    assert baseline(source) == before and other.read_bytes() == other_before
    if changed == "cancel":
        assert view.status.text() == view.t["cancelled"]
        monkeypatch.setattr(view.service, "prepare", prepare)
        view.prepare_button.click()
        settle(app, lambda: not view.busy, timeout=45)
        assert view.result is not None and view._request == requests[0]
        verify_copy(source, view.result)
        assert baseline(source) == before
