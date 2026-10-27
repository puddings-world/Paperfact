import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import bundle_links, research_service
from paper_daily.desktop.bundle_dialog import BundleDialog
from paper_daily.desktop.bundle_link_dialog import BundleLinkDialog
from paper_daily.desktop.main import MainWindow

workspace = _workspace


def wait(app, condition, timeout=5):
    until = time.monotonic() + timeout
    while not condition() and time.monotonic() < until:
        app.processEvents()
        time.sleep(0.005)
    assert condition()


class Pending:
    busy = False

    def start(self, prompt, done, failed, call, **kw):
        self.busy = True
        self.call, self.done, self.failed = call, done, failed

    def finish(self):
        value, reason = self.call("")
        self.busy = False
        (self.done if value else self.failed)(value or reason)


def test_link_download_empty_repeat_failure_retry_and_stale_input(workspace, monkeypatch):
    app, root = workspace
    widget = BundleLinkDialog(root)
    pending = Pending()
    widget.runner = pending
    calls = []

    def download(url, target, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise ValueError("fixture offline")
        target.write_bytes(b"fixture")
        return target

    monkeypatch.setattr(research_service, "download_bundle", download)
    widget._start()
    assert not pending.busy and not calls
    widget.url.setText("https://files.example.org/first.zip")
    for _ in range(30):
        widget._start()
    assert not widget.go.isEnabled()
    pending.finish()
    assert len(calls) == 1 and "fixture offline" in widget.status.text()
    assert widget.go.isEnabled()
    widget._start()
    # A programmatic change must not accept a result for a different URL either.
    widget.url.setText("https://files.example.org/second.zip")
    pending.finish()
    assert widget.source is None and "網址已變更" in widget.status.text()
    widget._start()
    pending.finish()
    assert widget.source == widget.target
    assert widget.result() == QDialog.DialogCode.Accepted
    widget.deleteLater()


@pytest.mark.parametrize("closing", ["cancel", "window"])
def test_closing_while_real_worker_runs_cancels_and_waits(workspace, monkeypatch, closing):
    app, root = workspace
    widget = BundleLinkDialog(root)
    started = threading.Event()
    cancelled = threading.Event()

    def download(url, target, **kw):
        started.set()
        while not kw["cancelled"]():
            if cancelled.wait(0.01):
                break
        raise bundle_links.Cancelled("已取消下載。")

    monkeypatch.setattr(research_service, "download_bundle", download)
    widget.show()
    widget.url.setText("https://files.example.org/p.zip")
    widget.go.click()
    assert started.wait(2)
    if closing == "cancel":
        widget.cancel.click()
    else:
        widget.close()
    assert widget.cancelled.is_set()
    wait(app, lambda: not widget.runner.busy and not widget.isVisible())
    assert widget.source is None and not widget.target.exists()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_share_link_action_copies_checksum_and_cancel_keeps_clipboard(workspace, monkeypatch):
    app, root = workspace
    source = root / "export.zip"
    source.write_bytes(b"exact uploaded bytes")
    widget = BundleDialog(list_id="x", list_name="Example")
    widget.result_data = {"out": str(source)}
    pending = Pending()
    widget.runner = pending
    QApplication.clipboard().setText("unchanged")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    widget._share_link()
    assert not pending.busy and QApplication.clipboard().text() == "unchanged"
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("https://files.example.org/p.zip", True)
    )
    widget._share_link()
    widget._share_link()
    assert not widget.share_button.isEnabled()
    pending.finish()
    link = QApplication.clipboard().text()
    assert link.endswith(bundle_links.file_digest(source))
    assert widget.share_button.isEnabled() and "已複製" in widget.status.text()
    widget.deleteLater()


@pytest.mark.parametrize("entry", ["global", "overview", "list"])
def test_link_entry_points_share_one_import_flow(workspace, monkeypatch, entry):
    app, root = workspace
    from paper_daily.desktop import bundle_dialog, bundle_link_dialog

    window = MainWindow()
    sources = []
    seen = []

    class Download:
        def __init__(self, folder, parent):
            self.source = Path(folder) / "fixture.zip"
            self.source.write_bytes(b"fixture")
            sources.append(self.source)

        def exec(self):
            window._import_bundle_link()  # repeated activation must not open a second job
            return QDialog.DialogCode.Accepted

    class Import:
        result_data = {"list": "fixture-list"}

        def __init__(self, parent, *, source, download_missing):
            assert source.read_bytes() == b"fixture"
            assert download_missing is False

        def exec(self):
            seen.append("preview/import")

    monkeypatch.setattr(bundle_link_dialog, "BundleLinkDialog", Download)
    monkeypatch.setattr(bundle_dialog, "BundleDialog", Import)
    monkeypatch.setattr(window, "_open_list", lambda ident: seen.append(ident))
    if entry == "global":
        window.import_link_action.trigger()
    elif entry == "overview":
        window.lists_page.import_link_button.click()
    else:
        window.queue_page.import_link_button.click()
    assert seen == ["preview/import", "fixture-list"] and len(sources) == 1
    assert not sources[0].exists() and not window._link_transfer_active
    window.close()
    window.deleteLater()


def test_cancelled_link_flow_does_not_open_import_preview(workspace, monkeypatch):
    from paper_daily.desktop import bundle_dialog, bundle_link_dialog

    window = MainWindow()

    class Cancelled:
        source = None

        def __init__(self, *a):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(bundle_link_dialog, "BundleLinkDialog", Cancelled)
    monkeypatch.setattr(
        bundle_dialog, "BundleDialog", lambda *a, **k: pytest.fail("cancel imported")
    )
    window._import_bundle_link()
    assert not window._link_transfer_active and window.active_list is None
    window.close()
    window.deleteLater()


def test_share_link_failure_keeps_clipboard_and_allows_retry(workspace, monkeypatch):
    app, root = workspace
    source = root / "export.zip"
    widget = BundleDialog(list_id="x", list_name="Example")
    widget.result_data = {"out": str(source)}
    pending = Pending()
    widget.runner = pending
    QApplication.clipboard().setText("previous link")
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("https://files.example.org/p.zip", True)
    )
    widget._share_link()
    pending.finish()
    assert "無法製作" in widget.status.text() and widget.share_button.isEnabled()
    assert QApplication.clipboard().text() == "previous link"
    source.write_bytes(b"restored export")
    widget._share_link()
    pending.finish()
    assert QApplication.clipboard().text().endswith(bundle_links.file_digest(source))
    widget.deleteLater()


def test_drive_share_uploads_a_fresh_package_and_copies_its_link(workspace, monkeypatch):
    from paper_daily import drive_share, google_slides

    app, root = workspace
    monkeypatch.setattr(google_slides, "read_client", lambda: {})
    widget = BundleDialog(list_id="x", list_name="Example")
    pending = Pending()
    widget.runner = pending
    QApplication.clipboard().setText("unchanged")
    widget._drive_share()
    assert not pending.busy and "email" in widget.status.text()
    widget.emails.setText("a@x.org, typo")
    widget._drive_share()
    assert not pending.busy and "typo" in widget.status.text()

    exported = {}

    def export(list_id, out, *, notes, with_pdfs, log):
        out.write_bytes(b"package")
        exported.update(list_id=list_id, notes=notes, with_pdfs=with_pdfs)

    def publish(list_id, path, google, *, name, emails, anyone, progress, cancelled):
        assert path.read_bytes() == b"package" and google == "signed in"
        progress(7, 7)
        return {
            "link": "https://drive.google.com/file/d/F/view",
            "file_id": "F",
            "replaced": False,
            "emails": emails,
        }

    monkeypatch.setattr(research_service, "export_bundle", export)
    monkeypatch.setattr(drive_share, "session", lambda: "signed in")
    monkeypatch.setattr(drive_share, "publish", publish)
    widget.emails.setText("a@x.org")
    widget.pdfs.setChecked(True)
    widget._drive_share()
    assert pending.busy and not widget.drive_button.isEnabled()
    widget.reject()
    assert widget.cancel_upload.is_set()
    widget.cancel_upload.clear()
    pending.finish()
    app.processEvents()
    assert exported == {"list_id": "x", "notes": True, "with_pdfs": True}
    assert QApplication.clipboard().text() == "https://drive.google.com/file/d/F/view"
    assert "a@x.org" in widget.status.text() and widget.drive_button.isEnabled()
    assert widget.upload_bar.value() == 7 and not widget.drive_open.isHidden()
    widget.deleteLater()
