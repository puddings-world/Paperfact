from PySide6.QtCore import QTimer
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily.desktop import support_dialog

reader = reader_fixture
legacy = legacy_fixture


def test_footer_opens_single_support_dialog_and_can_reopen(reader, tmp_path, monkeypatch):
    _, window, _ = reader
    monkeypatch.setattr(support_dialog.diagnostics, 'location', lambda: tmp_path)
    opened = []
    monkeypatch.setattr(support_dialog.QDesktopServices, 'openUrl', lambda url: opened.append(url))
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
    assert len(observed) == 2 and all('Paperfact' in text for text in observed)
    assert not opened
    assert window.feedback_btn.isEnabled()
