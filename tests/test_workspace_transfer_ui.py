import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from paper_daily import llm, store
from paper_daily.desktop.bundle_dialog import BundleDialog
from paper_daily.desktop.import_dialog import ImportListDialog
from paper_daily.desktop.main import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    yield app, tmp_path
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _sync_runner(widget, monkeypatch):
    def start(prompt, done, failed, call=None, **kwargs):
        result, reason = call(prompt)
        (done if result else failed)(result or reason)

    monkeypatch.setattr(widget.runner, "start", start)


def test_fresh_clone_opens_empty_overview_without_ai_or_sample_lists(workspace, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("startup invoked AI"))
    widget = MainWindow()
    assert widget.list_picker.count() == 0
    assert widget.stack.currentWidget() is widget.lists_page
    assert "空的" in widget.lists_page.empty.text()
    assert not widget.export_bundle_action.isEnabled()
    assert not widget.add_paper_action.isEnabled()
    assert not widget.reader_page.auto_highlights.isChecked()
    widget.close()
    widget.deleteLater()


def test_switching_lists_does_not_start_background_ai(workspace, monkeypatch):
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('mine','Research','now')")
        conn.commit()
    widget = MainWindow()
    monkeypatch.setattr(widget, "_spawn_job", lambda *a: pytest.fail("silent AI analysis"))
    widget._open_list("mine")
    widget.top_up_dives()
    assert widget.active_list == "mine" and widget.export_bundle_action.isEnabled()
    assert widget.add_paper_action.isEnabled()
    widget.close()
    widget.deleteLater()


def test_empty_list_dialog_creates_a_list_without_an_ai_account(workspace, monkeypatch):
    widget = ImportListDialog({}, workspace[1])
    _sync_runner(widget, monkeypatch)
    monkeypatch.setattr(widget, "_create_ai", lambda: pytest.fail("empty list requested login"))
    widget.name.setText("My own field")
    widget.mode.setCurrentIndex(widget.mode.findData("empty"))
    widget._start()
    assert widget.imported and widget.list_id
    assert widget.go.text() == "開啟清單"
    widget.deleteLater()


def test_bundle_preview_export_and_import_run_without_ai(workspace, monkeypatch):
    from paper_daily import bundle

    _app, root = workspace
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    target = root / "shared.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("bundle used AI"))
    exporter = BundleDialog(list_id="x", list_name="Research")
    _sync_runner(exporter, monkeypatch)
    exporter._start()
    assert target.exists() and exporter.go.text() == "完成"
    importer = BundleDialog(source=target)
    _sync_runner(importer, monkeypatch)
    importer._preview()
    assert importer.preview_ready and "Research" in importer.summary.text()
    assert not importer.replace.isChecked()
    importer._start()
    assert importer.result_data["list"] == "x"
    assert "已匯入" in importer.status.text()
    exporter.deleteLater()
    importer.deleteLater()


def test_source_code_zip_cannot_be_imported_as_research_data(workspace, monkeypatch):
    import zipfile

    path = workspace[1] / "software.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Paperfact/README.md", "software")
    widget = BundleDialog(source=path)
    _sync_runner(widget, monkeypatch)
    widget._preview()
    assert not widget.go.isEnabled()
    assert "非軟體原始碼" in widget.status.text()
    widget.deleteLater()


def test_bundle_import_failure_keeps_preview_and_allows_retry(workspace, monkeypatch):
    from paper_daily import bundle

    widget = BundleDialog(source=workspace[1] / "shared.zip")
    _sync_runner(widget, monkeypatch)
    widget.preview_ready = True
    widget.go.setEnabled(True)
    monkeypatch.setattr(bundle, "import_", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    widget._start()
    assert widget.go.isEnabled() and "disk" in widget.status.text()
    assert widget.result_data is None
    widget.deleteLater()


def test_close_and_restart_wait_for_login_preflight(workspace):
    from types import SimpleNamespace

    from PySide6.QtGui import QCloseEvent

    widget = MainWindow()
    widget.ai_access = SimpleNamespace(runner=SimpleNamespace(busy=True))
    event = QCloseEvent()
    widget.closeEvent(event)
    assert not event.isAccepted()
    assert not widget._prepare_restart()
    widget.ai_access.runner.busy = False
    widget.close()
    widget.deleteLater()


def test_overview_exports_selected_list_without_switching_active_list(workspace, monkeypatch):
    from paper_daily import bundle
    from paper_daily.desktop import bundle_dialog

    _app, root = workspace
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    with store.connect() as conn:
        conn.executemany(
            "INSERT INTO lists(id,name,created_at) VALUES (?,?,?)",
            [("first", "First", "now"), ("second", "Second", "now")],
        )
        conn.commit()
    widget = MainWindow()
    widget._open_list("first")
    widget.show_lists()
    page = widget.lists_page
    page.view.setCurrentRow(widget.list_picker.findData("second"))
    target = root / "selected.zip"
    seen = []

    class ExportDialog:
        def __init__(self, parent, *, list_id, list_name):
            self.list_id = list_id
            seen.append((list_id, list_name))

        def exec(self):
            bundle.export(self.list_id, target)

    monkeypatch.setattr(bundle_dialog, "BundleDialog", ExportDialog)
    assert page.export_button.isEnabled() and "Second" in page.export_button.toolTip()
    page.export_button.click()
    assert seen == [("second", "Second")]
    assert bundle.inspect(target)["list_id"] == "second"
    assert widget.active_list == "first" and widget.stack.currentWidget() is page
    widget.close()
    widget.deleteLater()


def test_overview_export_is_disabled_without_a_research_list(workspace, monkeypatch):
    widget = MainWindow()
    page = widget.lists_page
    monkeypatch.setattr(widget, "_export_list_bundle", lambda *a: pytest.fail("invalid export"))
    assert not page.export_button.isEnabled()
    page.export_selected()
    widget.list_picker.blockSignals(True)
    widget.list_picker.addItem("ML queue", None)
    widget.list_picker.blockSignals(False)
    page.refresh()
    assert not page.export_button.isEnabled()
    page.export_selected()
    widget.close()
    widget.deleteLater()
