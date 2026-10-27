"""Support remains reachable through the app footer."""

from test_update_notices import workspace as _workspace

workspace = _workspace

def test_support_footer_can_be_reopened_without_network(workspace, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    from paper_daily.desktop import support_dialog
    from paper_daily.desktop.main import MainWindow

    monkeypatch.setattr(support_dialog.diagnostics, "location", lambda: tmp_path)
    opened = []
    monkeypatch.setattr(support_dialog.QDesktopServices, "openUrl", opened.append)
    window = MainWindow()
    observed = []

    def inspect_and_close():
        first = window._support_dialog
        observed.append(first.preview.toPlainText())
        window._support()
        assert window._support_dialog is first
        first.accept()

    for _ in range(2):
        QTimer.singleShot(10, inspect_and_close)
        window.support_btn.click()
        assert window._support_dialog is None
    assert len(observed) == 2 and all("Paperfact" in text for text in observed)
    assert not opened
    window.close()
    window.deleteLater()
