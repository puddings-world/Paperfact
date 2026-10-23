"""Page-level controls share the offline bundle dialog and export whole lists."""

import json
import zipfile

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QFileDialog
from test_workspace_transfer_ui import _sync_runner
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import bundle, store
from paper_daily.desktop.bundle_dialog import BundleDialog
from paper_daily.desktop.main import MainWindow

workspace = _workspace


@pytest.fixture
def listing(workspace, monkeypatch):
    app, root = workspace
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    monkeypatch.setattr(bundle, "fetch", lambda *a, **k: pytest.fail("transfer used network"))
    with store.connect() as conn:
        store.upsert_papers(conn, [
            {"id": pid, "title": title, "venue": "MICCAI", "year": 2025, "source": "test"}
            for pid, title in [("ref:a", "Alpha"), ("ref:b", "Beta"), ("ref:c", "Gamma")]
        ])
        conn.executescript("""
            INSERT INTO lists(id,name,created_at) VALUES
                ('mine','My research','now'), ('other','Shared research','now');
            INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES
                ('mine','ref:a',0,'now'), ('mine','ref:b',1,'now'),
                ('other','ref:c',0,'now');
            INSERT INTO notes(paper_id,body,created_at) VALUES ('ref:b','Saved note','now');
        """)
    bundle.PDF_DIR.mkdir()
    (bundle.PDF_DIR / "ref_b.pdf").write_bytes(b"%PDF fixture original")
    window = MainWindow()
    yield window, app, root
    window.close()
    window.deleteLater()


def _page(window, view):
    window._open_list("mine")
    if view == "overview":
        window.show_lists()
        return window.lists_page, window.lists_page.import_button, window.lists_page.export_button
    page = window.queue_page
    return page, page.import_bundle_button, page.export_bundle_button


@pytest.mark.parametrize("view", ["overview", "list"])
@pytest.mark.parametrize("filtered", [False, True])
def test_page_export_is_visible_and_contains_whole_list(listing, monkeypatch, view, filtered):
    window, app, root = listing
    page, importer, exporter = _page(window, view)
    if filtered:
        window.queue_page.search.setText("Alpha")
        window.toggle_marked("ref:a")
        window.queue_page.refresh()
        assert window.queue_page.model.rowCount() == 1
    target = root / "export.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    dialogs = []

    def run(dialog):
        dialogs.append(dialog)
        _sync_runner(dialog, monkeypatch)
        dialog._start()
        assert dialog.result_data and "已匯出" in dialog.status.text()
        dialog.deleteLater()

    monkeypatch.setattr(BundleDialog, "exec", run)
    window.resize(1180, 680)
    window.show()
    app.processEvents()
    for button in (importer, exporter):
        assert button.isVisible() and button.isEnabled()
        corner = button.mapTo(page, QPoint(0, 0))
        assert page.rect().contains(corner)
        assert page.rect().contains(corner + button.rect().bottomRight())
    boundary = page.body if view == "overview" else page.search
    button_bottom = exporter.mapTo(page, QPoint(0, exporter.height())).y()
    assert button_bottom <= boundary.mapTo(page, QPoint()).y()
    assert "My research" in exporter.toolTip()
    assert "整份清單" in exporter.toolTip()
    exporter.click()
    assert len(dialogs) == 1
    info = bundle.inspect(target)
    assert info["list_id"] == "mine" and info["papers"] == 2 and info["pdfs"] == 1
    with zipfile.ZipFile(target) as archive:
        tables = json.loads(archive.read("tables.json"))
        manifest = json.loads(archive.read("manifest.json"))
        assert {row["paper_id"] for row in manifest["members"]} == {"ref:a", "ref:b"}
        assert tables["notes"][0]["body"] == "Saved note"
        assert archive.read("files/pdf/ref_b.pdf") == b"%PDF fixture original"
    assert window.active_list == "mine" and window.stack.currentWidget() is page


@pytest.mark.parametrize("view", ["overview", "list"])
def test_page_import_cancel_and_success_use_bundle_identity(listing, monkeypatch, view):
    window, _app, root = listing
    source = root / "shared.zip"
    bundle.export("other", source)
    with store.connect() as conn:
        conn.execute("DELETE FROM list_papers WHERE list_id='other'")
        conn.execute("DELETE FROM lists WHERE id='other'")
        conn.commit()
    window.refresh_lists()
    page, importer, _exporter = _page(window, view)
    opened = []

    def run(dialog):
        opened.append(dialog)
        _sync_runner(dialog, monkeypatch)
        dialog._preview()
        assert dialog.preview_ready and "Shared research" in dialog.summary.text()
        dialog._start()
        assert dialog.result_data["list"] == "other"
        dialog.deleteLater()

    monkeypatch.setattr(BundleDialog, "exec", run)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))
    for _ in range(3):
        importer.click()
    assert not opened and window.active_list == "mine"
    assert window.stack.currentWidget() is page
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(source), ""))
    importer.click()
    assert len(opened) == 1 and window.active_list == "other"
    assert window.stack.currentWidget() is window.queue_page
    # Re-import through either entry point merges without duplicating the list or its papers.
    importer.click()
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 2
        for list_id, count in (("mine", 2), ("other", 1)):
            assert conn.execute(
                "SELECT COUNT(*) FROM list_papers WHERE list_id=?", (list_id,)
            ).fetchone()[0] == count


def test_expanded_export_tracks_list_switch_and_cancellation(listing, monkeypatch):
    window, _app, _root = listing
    page, _importer, exporter = _page(window, "list")
    window._open_list("other")
    assert "Shared research" in exporter.toolTip()
    seen = []

    def run(dialog):
        seen.append(dialog.list_id)
        _sync_runner(dialog, monkeypatch)
        dialog._start()
        assert dialog.result_data is None and dialog.go.isEnabled()
        dialog.deleteLater()

    monkeypatch.setattr(BundleDialog, "exec", run)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    exporter.click()
    assert seen == ["other"] and window.active_list == "other"
    assert not window.activity_hub.busy
    window.active_list = None
    page.refresh()
    assert not exporter.isEnabled() and page.import_bundle_button.isEnabled()
    exporter.click()
    assert seen == ["other"]
