from PySide6.QtWidgets import QApplication
from test_maintenance import pending as _pending
from test_maintenance import prepared
from test_maintenance import workspace as _workspace

from paper_daily import updates
from paper_daily.desktop.main import MainWindow

pending = _pending
workspace = _workspace


def test_failed_installer_restores_draft_protection(workspace, pending, tmp_path, monkeypatch):
    window = MainWindow()
    window.show()
    pane = window.reader_page.presentation_pane
    recovery = tmp_path / "draft.txt"
    window.reader_page.ask_box.setText("before update")
    monkeypatch.setattr(pane, "save_changes", lambda: False)
    monkeypatch.setattr(
        pane, "save_recovery",
        lambda: recovery.write_text(window.reader_page.ask_box.text(), encoding="utf-8"),
    )
    prepared(window.update_banner, tmp_path, monkeypatch)

    def fail(_path):
        raise OSError("fixture installer failure")

    monkeypatch.setattr(updates, "launch_installer", fail)
    try:
        window.update_banner.start_install()
        pending.pop()()
        QApplication.processEvents()
        assert recovery.read_text(encoding="utf-8") == "before update"
        assert window.isVisible()
        window.reader_page.ask_box.setText("continued editing after failed update")
        assert not window.close()
        assert window._close_dialog.isVisible()
        assert window.reader_page.ask_box.text() == "continued editing after failed update"
    finally:
        monkeypatch.setattr(pane, "save_changes", lambda: True)
        dialog = getattr(window, "_close_dialog", None)
        if dialog is not None:
            dialog.reject()
        window.close()
        window.deleteLater()
