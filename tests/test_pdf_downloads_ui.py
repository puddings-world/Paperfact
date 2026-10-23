import threading
import time

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleOptionViewItem
from test_queue_keys import _paper
from test_queue_keys import page as _page
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import pdf_downloads as dl
from paper_daily import store
from paper_daily.desktop.main import MainWindow
from paper_daily.desktop.queue_view import DOWNLOAD_ROLE, ROW_HEIGHT, pdf_progress_slot

page = _page
workspace = _workspace


def settle(queue):
    end = time.monotonic() + 4
    while queue.busy and time.monotonic() < end:
        QTest.qWait(10)
    assert not queue.busy


def test_progress_updates_rows_without_resetting_selection_and_keeps_list_identity(
    workspace, page, tmp_path,
):
    view, win = page
    for paper in win.papers:
        paper._has_pdf = False
    release, entered = threading.Event(), threading.Event()
    calls = []

    def worker(pid, progress, cancel):
        calls.append(pid)
        progress("downloading", 512, 1024, "")
        entered.set()
        assert release.wait(3)
        dest = tmp_path / (pid + ".pdf")
        dest.write_bytes(b"synthetic saved bytes")
        return dest

    manager = dl.DownloadQueue(worker)
    try:
        view.enable_downloads(manager)
        assert entered.wait(2)
        for _ in range(20):
            view.enqueue_pdfs()
        view._select("p2")
        view._poll_pdfs()
        index = view.view.currentIndex()
        assert index.data(DOWNLOAD_ROLE).percent == 50
        assert "50%" in index.data(Qt.ItemDataRole.ToolTipRole)
        height = view.view.itemDelegate().sizeHint(QStyleOptionViewItem(), index).height()
        assert height == ROW_HEIGHT
        view._poll_pdfs()
        assert view._current_paper().id == "p2"
        # Reusing row zero in another list must not display p0's progress for p99.
        original = win.papers
        win.papers = [_paper(99)]
        win.papers[0]._has_pdf = False
        win.active_list = "other-list"
        view.refresh()
        view.enqueue_pdfs()
        assert view.model.index(0).data(DOWNLOAD_ROLE).phase == "queued"
        release.set()
        settle(manager)
        view._poll_pdfs()
        assert win.papers[0].has_pdf
        win.papers, win.active_list = original, "list"
        view.refresh()
        view._poll_pdfs()
        assert all(p.has_pdf for p in win.papers)
        assert len(calls) == len(set(calls)) == 6
        assert all((tmp_path / (pid + ".pdf")).exists() for pid in calls)
    finally:
        release.set()
        manager.close()
        settle(manager)


def test_auto_download_can_be_disabled_persisted_and_resumed(workspace, page):
    view, win = page
    win.papers = [_paper(0)]
    win.papers[0]._has_pdf = False
    started = threading.Event()
    calls = []

    def worker(pid, progress, cancel):
        calls.append(pid)
        started.set()
        if len(calls) == 1:
            assert cancel.wait(3)
            dl.check_cancel(cancel)
        return "saved.pdf"

    manager = dl.DownloadQueue(worker)
    try:
        with store.connect() as conn:
            store.set_kv(conn, "ui.auto_pdf", False)
        view.enable_downloads(manager)
        assert not manager.busy and not calls
        view.auto_pdf.setChecked(True)
        assert started.wait(2)
        view.auto_pdf.setChecked(False)
        settle(manager)
        view._poll_pdfs()
        assert manager.snapshot()["p0"].phase == "cancelled"
        with store.connect() as conn:
            assert store.get_kv(conn, "ui.auto_pdf") is False
        view.enqueue_pdfs()
        assert len(calls) == 1
        view.retry_pdf.click()
        settle(manager)
        view._poll_pdfs()
        assert len(calls) == 2 and win.papers[0].has_pdf
    finally:
        manager.close()
        settle(manager)


def test_pause_and_failure_keep_retry_available_and_do_not_invoke_ai(workspace, page):
    view, win = page
    win.papers = [_paper(0)]
    win.papers[0]._has_pdf = False
    calls = []

    def worker(pid, progress, cancel):
        calls.append(pid)
        raise dl.FetchError("來源暫時無法連線")

    manager = dl.DownloadQueue(worker)
    try:
        view.enable_downloads(manager)
        settle(manager)
        view._poll_pdfs()
        assert view.retry_pdf.isEnabled() and not win.papers[0].has_pdf
        assert "未完成 1" in view.pdf_status.text()
        view.enqueue_pdfs()
        assert calls == ["p0"]
        view.retry_pdf.click()
        settle(manager)
        assert calls == ["p0", "p0"]
        view.pause_pdf.click()
    finally:
        manager.close()


def test_window_close_waits_for_cancel_cleanup_without_abandoning_worker(workspace):
    window = MainWindow()
    cleaned, entered = threading.Event(), threading.Event()

    def worker(pid, progress, cancel):
        entered.set()
        assert cancel.wait(3)
        cleaned.set()
        dl.check_cancel(cancel)

    manager = dl.DownloadQueue(worker)
    window.pdf_downloads = manager
    window.queue_page.enable_downloads(manager)
    window.show()
    try:
        manager.submit(["closing-fixture"])
        assert entered.wait(2)
        window.close()
        settle(manager)
        QTest.qWait(250)
        assert cleaned.is_set() and not window.isVisible()
        assert manager.snapshot()["closing-fixture"].phase == "cancelled"
    finally:
        manager.close()
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("phase", ["queued", "resolving", "downloading", "verifying",
                                 "done", "error", "cancelled"])
def test_all_download_states_keep_original_row_height_and_terminal_states_use_tags(page, phase):
    view, win = page
    paper = win.papers[0]
    paper._has_pdf = phase == "done"
    state = dl.State(phase, 40, 100)
    view.model.downloads = {paper.id: state}
    index = view.model.index(0)
    delegate = view.view.itemDelegate()
    assert delegate.sizeHint(QStyleOptionViewItem(), index).height() == ROW_HEIGHT
    labels = [text for text, _foreground, _background in delegate._tags(paper)]
    assert ("有 PDF" if phase == "done" else "缺 PDF") in labels
    slot = pdf_progress_slot(QRect(0, 0, 900, ROW_HEIGHT), 100, 730, state)
    assert slot.isEmpty() == (phase in ("done", "error", "cancelled"))


@pytest.mark.parametrize("width", [380, 900, 1800])
def test_inline_progress_stays_short_and_inside_the_title_line(width):
    row = QRect(0, 100, width, ROW_HEIGHT)
    slot = pdf_progress_slot(row, 100, width - 165, dl.State("downloading", 50, 100))
    assert slot.width() <= 132
    assert row.contains(slot) and slot.top() == row.top() + 7
    assert slot.bottom() < row.top() + 29  # No overlap with tags or authors.
    assert slot.left() > 100 and slot.right() < width - 52  # Title and pin retain space.
