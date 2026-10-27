"""Non-blocking release notices with a quiet, pauseable rotating summary."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton

from paper_daily import __version__, runtime, updates
from paper_daily.store import connect


class _Relay(QObject):
    found = Signal(object)
    check_failed = Signal()
    progress = Signal(int, int)
    downloaded = Signal(object)
    verified = Signal()
    failed = Signal(str)


def _emit(signal, *args):
    # Closing a window while a bounded background request finishes is normal.
    with suppress(RuntimeError):  # Qt receiver was deleted.
        signal.emit(*args)


class UpdateBanner(QFrame):
    """One notice per release; never change the reader's selection or focus."""

    quit_for_update = Signal()
    check_status = Signal(bool, str)

    def __init__(self, palette: dict[str, str], *, prepare_install=None, cancel_install=None):
        super().__init__()
        self.release: updates.Release | None = None
        self._checking = self._downloading = self._closed = False
        self._dismissed = None
        self._prepare_install = prepare_install
        self._cancel_install = cancel_install
        self._ready = None
        self._installing = False
        self._verifying = False
        self._manual_check = False
        self._messages = []
        self._message_index = 0
        self._relay = _Relay(self)
        self._relay.found.connect(self._found)
        self._relay.check_failed.connect(self._check_failed)
        self._relay.progress.connect(self._progress)
        self._relay.downloaded.connect(self._downloaded)
        self._relay.verified.connect(self._verified)
        self._relay.failed.connect(self._failed)
        self._poll = QTimer(self)
        self._poll.setInterval(15 * 60 * 1000)
        self._poll.timeout.connect(self.check_in_background)
        self._rotate = QTimer(self)
        self._rotate.setInterval(6000)
        self._rotate.timeout.connect(self._cycle)
        self.setObjectName("updateBanner")
        self.setStyleSheet(
            f"#updateBanner{{background:{palette['accentSoft']};"
            f"border-bottom:1px solid {palette['accent']};}}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 6, 12, 6)
        row.setSpacing(10)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setStyleSheet(f"color:{palette['ink']};font-size:12px;")
        row.addWidget(self.label, 1)
        self.install = QPushButton("更新並重啟")
        self.install.setStyleSheet(
            f"QPushButton{{background:{palette['accent']};color:white;"
            f"border:1px solid {palette['accent']};border-radius:4px;padding:4px 12px;"
            f"font-weight:600;}}"
        )
        self.install.clicked.connect(self.start_install)
        row.addWidget(self.install)
        self.notes = QPushButton("看更新內容")
        self.notes.clicked.connect(self._open_page)
        row.addWidget(self.notes)
        self.later = QPushButton("稍後")
        self.later.clicked.connect(self._snooze)
        row.addWidget(self.later)
        self.hide()

    def check_in_background(self, *, force=False):
        if self._closed or self._checking:
            return
        if self._downloading or self._ready is not None or self._installing:
            if force:
                self.show()
                self.check_status.emit(False, "已有更新下載中或等待安裝，請查看上方公告。")
            return
        self._poll.start()
        self._checking = True
        self._manual_check = force
        self.check_status.emit(True, "正在檢查更新…")
        relay = self._relay
        channel = updates.default_channel()

        def work():
            try:
                with connect() as conn:
                    options = {"channel": channel, **({"force": True} if force else {})}
                    release = updates.check(conn, **options)
                    if not force and release is not None and updates.snoozed(conn, release):
                        release = None
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
                _emit(relay.check_failed)
                return
            _emit(relay.found, release)

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _check_failed(self):
        self._checking = False
        if not self._closed:
            self.check_status.emit(False, "暫時無法檢查更新，請確認網路後重試。")

    def _found(self, release):
        self._checking = False
        if self._closed:
            return
        if self._downloading or self._ready is not None or self._installing:
            self.check_status.emit(False, "已有更新下載中或等待安裝，請查看上方公告。")
            return
        self.check_status.emit(
            False,
            f"找到 Paperfact {release.version}，請查看上方公告。"
            if release
            else "目前沒有符合更新頻道的新版本。",
        )
        if release is None:
            self._rotate.stop()
            self.hide()
            return
        if not self._manual_check and self._dismissed == (release.version, updates.date.today()):
            return
        self.offer(release)

    def offer(self, release):
        if self._closed or self._downloading or self._ready is not None or self._installing:
            return
        if self.release == release and not self.isHidden():
            return
        self.release = release
        news = updates.headline(release.notes)
        kind = "安裝版" if runtime.FROZEN else "原始碼版"
        channel = "公開 beta" if release.prerelease else "正式發布"
        text = f"Paperfact {release.version} 可以更新了 · {channel}（目前 {kind} {__version__}）"
        summary = f"{text}：{news}" if news else text
        if updates.can_install():
            self.install.setText("更新並重啟")
            instruction = "按「更新並重啟」下載新版；你的研究資料會保留。"
            self.install.setToolTip("下載新版，關閉 Paperfact 後安裝，再重新開啟。")
        elif not runtime.FROZEN:
            self.install.setText("怎麼更新")
            instruction = "原始碼版：先保存修改，再 git pull --ff-only、執行 setup 腳本並重開。"
            self.install.setToolTip(instruction)
        else:
            self.install.setText("下載新版")
            instruction = "請從發布頁下載適合這台電腦的安裝檔。"
            self.install.setToolTip(instruction)
        self._messages = [summary, f"Paperfact {release.version} · {instruction}"]
        self._message_index = 0
        self.label.setText(summary)
        self.label.setToolTip(
            "\n".join(self._messages) + "\n滑鼠移到公告或鍵盤焦點在按鈕時暫停輪播。"
        )
        self.install.setEnabled(True)
        self.later.setEnabled(True)
        self.show()
        self._rotate.start()

    def _cycle(self):
        focused = QApplication.focusWidget()
        if (
            self._closed
            or self._downloading
            or self._ready is not None
            or self._installing
            or not self.isVisible()
            or self.underMouse()
            or (focused is not None and (focused is self or self.isAncestorOf(focused)))
            or not self._messages
        ):
            return
        self._message_index = (self._message_index + 1) % len(self._messages)
        self.label.setText(self._messages[self._message_index])

    def start_install(self):
        release = self.release
        if release is None or self._closed or self._downloading or self._installing:
            return
        if self._ready is not None:
            self._apply_ready()
            return
        asset = updates.asset_for(release)
        if not updates.can_install() or asset is None:
            self._open_page()
            return
        name, url = asset
        self._downloading = True
        self._rotate.stop()
        self.install.setEnabled(False)
        self.later.setEnabled(False)
        self.label.setText(f"正在下載 Paperfact {release.version}…")
        relay = self._relay

        def work():
            if self._closed:
                return
            try:
                digest = release.digests.get(name, "")
                if not digest:
                    raise ValueError("此版本缺少驗證資訊，請從發布頁下載。")
                dest = updates.download_dir() / name
                path = updates.download(
                    url, dest, lambda done, total: _emit(relay.progress, done, total)
                )
                updates.verify_download(path, digest)
            except (OSError, ValueError, updates.httpx.HTTPError) as exc:
                from paper_daily import diagnostics

                diagnostics.record_exception(type(exc), exc.__traceback__, phase="background")
                _emit(
                    relay.failed,
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "下載或驗證失敗，請檢查網路及可用空間後重試。",
                )
                return
            _emit(relay.downloaded, path)

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _progress(self, done, total):
        if self.release is None or self._closed:
            return
        size = f"{done / 1e6:.0f} / {total / 1e6:.0f} MB" if total else f"{done / 1e6:.0f} MB"
        self.label.setText(f"正在下載 Paperfact {self.release.version}… {size}")

    def _downloaded(self, path: Path):
        if self._closed:
            return
        self._downloading = False
        self._ready = path
        self._verified()

    def _apply_ready(self):
        if self._closed or self._installing or self._verifying or self._ready is None:
            return
        self._verifying = True
        self.install.setEnabled(False)
        self.later.setEnabled(False)
        self.label.setText("正在重新驗證下載檔案…")
        path, digest = self._ready, self.release.digests.get(self._ready.name, "")
        relay = self._relay

        def work():
            try:
                updates.verify_download(path, digest)
            except (OSError, ValueError):
                _emit(relay.failed, "下載檔案驗證失敗，請重新下載。")
                return
            _emit(relay.verified)

        threading.Thread(target=work, name="update-verify", daemon=True).start()

    def _verified(self):
        self._verifying = False
        if self._closed or self._installing or self._ready is None:
            return
        if self._prepare_install is not None and not self._prepare_install():
            self.label.setText("新版已下載並驗證；請先完成背景工作、儲存並關閉對話視窗，再按更新。")
            self.install.setText("完成後更新並重啟")
            self.install.setEnabled(True)
            self.later.setEnabled(True)
            return
        self._installing = True
        try:
            updates.launch_installer(self._ready)
        except (OSError, ValueError) as exc:
            if self._cancel_install is not None:
                self._cancel_install()
            self._installing = False
            self._ready = None
            self._failed(str(exc) if isinstance(exc, ValueError) else "無法啟動安裝程式，請重試。")
            return
        self.label.setText("下載完成，Paperfact 會關閉、安裝新版，然後自己重新開啟。")
        self.quit_for_update.emit()

    def _failed(self, reason):
        self._downloading = False
        self._verifying = False
        self._ready = None
        if self._closed:
            return
        self._rotate.stop()
        self.label.setText(f"更新沒有完成：{reason}。可以按「看更新內容」到發布頁手動下載。")
        self.install.setText("再試一次")
        self.install.setEnabled(True)
        self.later.setEnabled(True)

    def _open_page(self):
        page = self.release.page if self.release else updates.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(page))

    def _snooze(self):
        if self._downloading or self._verifying or self._installing:
            return
        if self.release is not None:
            with connect() as conn:
                updates.snooze(conn, self.release)
            self._dismissed = (self.release.version, updates.date.today())
        self._rotate.stop()
        self.hide()

    def shutdown(self):
        self._closed = True
        self._poll.stop()
        self._rotate.stop()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
