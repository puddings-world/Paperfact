import json
import zipfile

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from paper_daily import diagnostics
from paper_daily.desktop import support_dialog as ui


@pytest.fixture
def view(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    opened = []
    monkeypatch.setattr(
        ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True
    )
    dialog = ui.SupportDialog(directory=tmp_path)
    dialog.show()
    app.processEvents()
    yield dialog, opened
    dialog.close()


def test_preview_export_exact_match_and_duplicate_click(view, tmp_path, monkeypatch):
    dialog, opened = view
    assert not opened and not list(tmp_path.iterdir())
    target = tmp_path / "report.zip"
    chosen = []

    def choose(*a):
        chosen.append(1)
        dialog.export_report()  # File chooser's nested event loop / repeated action.
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    dialog.export_button.click()
    dialog.export_button.click()
    assert chosen == [1]
    assert not dialog.export_button.isEnabled()
    with zipfile.ZipFile(target) as archive:
        assert json.loads(archive.read("diagnostics.json")) == json.loads(
            dialog.preview.toPlainText()
        )
    assert "沒有上傳" in dialog.status.text()
    dialog.refresh_button.click()
    assert dialog.export_button.isEnabled()


def test_cancel_and_close_during_chooser_write_nothing(view, tmp_path, monkeypatch):
    dialog, _ = view
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    dialog.export_button.click()
    assert not list(tmp_path.iterdir())
    assert dialog.export_button.isEnabled()

    def close(*a):
        dialog.close()
        return str(tmp_path / "ignored.zip"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", close)
    dialog.export_report()
    assert not list(tmp_path.iterdir())


def test_export_failure_preserves_preview_and_retries(view, tmp_path, monkeypatch):
    dialog, _ = view
    preview = dialog.preview.toPlainText()
    target = tmp_path / "report.zip"
    target.write_bytes(b"keep")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    dialog.export_button.click()
    assert target.read_bytes() == b"keep"
    assert "失敗" in dialog.status.text()
    assert dialog.export_button.isEnabled()
    assert dialog.preview.toPlainText() == preview
    target = tmp_path / "retry.zip"
    dialog.export_button.click()
    assert target.is_file()


def test_refresh_failure_disables_stale_export_then_recovers(view, monkeypatch):
    dialog, _ = view
    collect = diagnostics.collect
    monkeypatch.setattr(diagnostics, "collect", lambda *a: (_ for _ in ()).throw(OSError()))
    dialog.refresh_button.click()
    assert not dialog.export_button.isEnabled()
    assert not dialog.preview.toPlainText()
    monkeypatch.setattr(diagnostics, "collect", collect)
    dialog.refresh_button.click()
    assert dialog.export_button.isEnabled()


def test_links_only_open_on_explicit_click_and_never_send_report(view):
    dialog, opened = view
    for button in (dialog.issue_button, dialog.repo_button, dialog.org_button):
        button.click()
        button.click()
    assert opened == [ui.ISSUE_URL, ui.REPO_URL, ui.ORG_URL]
    assert "自行決定" in dialog.status.text()


def test_browser_failure_can_retry(view, monkeypatch):
    dialog, opened = view
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda *a: False)
    dialog.issue_button.click()
    assert "無法開啟" in dialog.status.text()
    monkeypatch.setattr(
        ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True
    )
    dialog.issue_button.click()
    assert opened == [ui.ISSUE_URL]


def test_export_keeps_reviewed_workspace_snapshot(view, tmp_path, monkeypatch):
    dialog, _ = view
    preview = dialog.preview.toPlainText()
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    (elsewhere / "app.log").write_text("ValueError: private-other-account\n")
    monkeypatch.setattr(diagnostics, "location", lambda: elsewhere)
    target = tmp_path / "original.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    dialog.export_button.click()
    with zipfile.ZipFile(target) as archive:
        assert archive.read("diagnostics.json").decode() == preview
    assert "private-other" not in preview
