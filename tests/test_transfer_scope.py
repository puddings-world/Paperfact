"""Research packages stay global; the slide action exports just the open deck."""

import pytest
from PySide6.QtWidgets import QFileDialog
from test_presentation_pane import pane as _pane
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import bundle, store
from paper_daily.desktop import bundle_dialog
from paper_daily.desktop.main import MainWindow

workspace = _workspace
pane = _pane


@pytest.mark.parametrize("view", ["overview", "list", "slides"])
def test_global_data_menu_exports_current_list_from_each_view(workspace, monkeypatch, view):
    app, root = workspace
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    with store.connect() as conn:
        conn.executemany("INSERT INTO lists(id,name,created_at) VALUES (?,?, 'now')",
                         [("mine", "My Research"), ("other", "Other Research")])
        conn.commit()
    window = MainWindow()
    target = root / "research.zip"
    exported = []

    class ExportDialog:
        def __init__(self, parent, *, list_id, list_name):
            self.list_id = list_id

        def exec(self):
            exported.append(self.list_id)
            bundle.export(self.list_id, target)

    monkeypatch.setattr(bundle_dialog, "BundleDialog", ExportDialog)
    try:
        window._open_list("mine")
        if view == "overview":
            window.show_lists()
        elif view == "slides":
            window.stack.setCurrentWidget(window.reader_page)
            window.reader_page.tabs.setCurrentWidget(window.reader_page.presentation_pane)
        window.show()
        app.processEvents()
        before = window.stack.currentWidget()
        assert window.research_data_button.isVisible()
        assert not window.reader_page.presentation_pane.isAncestorOf(window.research_data_button)
        assert window.export_bundle_action in window.research_data_button.menu().actions()
        assert window.import_bundle_action in window.research_data_button.menu().actions()
        window.export_bundle_action.trigger()
        assert exported == ["mine"]
        assert bundle.inspect(target)["list_id"] == "mine"
        assert window.stack.currentWidget() is before and window.active_list == "mine"
    finally:
        window.close()
        window.deleteLater()


def test_global_import_cancellation_and_empty_export_leave_workspace_untouched(
    workspace, monkeypatch
):
    window = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))
    monkeypatch.setattr(bundle_dialog, "BundleDialog",
                        lambda *a, **k: pytest.fail("cancelled import opened a transfer job"))
    try:
        assert not window.export_bundle_action.isEnabled()
        assert window.import_bundle_action.isEnabled()
        window.import_bundle_action.trigger()
        window._export_bundle()
        with store.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
        assert window.active_list is None and not window.activity_hub.busy
    finally:
        window.close()
        window.deleteLater()


def test_slide_export_label_and_dialog_are_scoped_to_the_deck(pane, monkeypatch):
    widget, deck, _app, _root = pane
    shown = []
    before = deck.to_dict()

    def cancelled(parent, title, filename, formats):
        shown.append((title, filename, formats))
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", cancelled)
    assert widget.export_button.text() == "匯出簡報…"
    assert "PDF" in widget.export_button.toolTip()
    widget.export_button.click()
    assert len(shown) == 1 and shown[0][0] == "匯出論文簡報"
    assert shown[0][1].endswith(".pdf") and shown[0][2].startswith("PDF")
    assert widget.deck.to_dict() == before and not widget.busy
