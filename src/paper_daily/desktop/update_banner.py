"""The banner that says a new version is out, and installs it on request.

Checking and downloading run on worker threads: GitHub can take seconds to answer,
or not answer at all, and the window must not wait for it at launch.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from paper_daily import __version__, updates
from paper_daily.store import connect


class _Relay(QObject):
    """Carries results from worker threads back to the GUI thread."""

    found = Signal(object)
    progress = Signal(int, int)
    downloaded = Signal(object)
    failed = Signal(str)


class UpdateBanner(QFrame):
    """「Paperfact 0.2.0 可以更新了：…」 with 更新並重啟 / 看更新內容 / 稍後."""

    # Asks the window to close so the installer can replace the app.
    quit_for_update = Signal()

    def __init__(self, palette: dict[str, str]):
        super().__init__()
        self.release: updates.Release | None = None
        self._relay = _Relay()
        self._relay.found.connect(self._found)
        self._relay.progress.connect(self._progress)
        self._relay.downloaded.connect(self._downloaded)
        self._relay.failed.connect(self._failed)
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

    # ---- checking ----------------------------------------------------------
    def check_in_background(self) -> None:
        def work() -> None:
            with connect() as conn:
                release = updates.check(conn)
                if release is not None and updates.snoozed(conn, release):
                    release = None
            self._relay.found.emit(release)

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _found(self, release: updates.Release | None) -> None:
        if release is not None:
            self.offer(release)

    def offer(self, release: updates.Release) -> None:
        self.release = release
        news = updates.headline(release.notes)
        text = f"Paperfact {release.version} 可以更新了（目前 {__version__}）"
        self.label.setText(f"{text}：{news}" if news else text)
        if updates.can_install():
            self.install.setText("更新並重啟")
            self.install.setToolTip("下載新版，關閉 Paperfact 後安裝，再重新開啟。")
        else:
            # A source checkout: its owner updates it with git.
            self.install.setText("怎麼更新")
            self.install.setToolTip("原始碼版：在專案資料夾執行 git pull，再執行 setup 腳本。")
        self.install.setEnabled(True)
        self.later.setEnabled(True)
        self.show()

    # ---- installing ----------------------------------------------------------
    def start_install(self) -> None:
        release = self.release
        if release is None:
            return
        asset = updates.asset_for(release)
        if not updates.can_install() or asset is None:
            self._open_page()
            return
        name, url = asset
        dest = updates.download_dir() / name
        self.install.setEnabled(False)
        self.later.setEnabled(False)
        self.label.setText(f"正在下載 Paperfact {release.version}…")

        def work() -> None:
            try:
                path = updates.download(url, dest, self._relay.progress.emit)
            except (OSError, updates.httpx.HTTPError) as exc:
                self._relay.failed.emit(str(exc) or type(exc).__name__)
                return
            self._relay.downloaded.emit(path)

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        if self.release is None:
            return
        size = f"{done / 1e6:.0f} / {total / 1e6:.0f} MB" if total else f"{done / 1e6:.0f} MB"
        self.label.setText(f"正在下載 Paperfact {self.release.version}… {size}")

    def _downloaded(self, path: Path) -> None:
        try:
            updates.launch_installer(path)
        except OSError as exc:
            self._failed(str(exc))
            return
        self.label.setText("下載完成，Paperfact 會關閉、安裝新版，然後自己重新開啟。")
        self.quit_for_update.emit()

    def _failed(self, reason: str) -> None:
        self.label.setText(f"更新沒有完成：{reason}。可以按「看更新內容」到發布頁手動下載。")
        self.install.setText("再試一次")
        self.install.setEnabled(True)
        self.later.setEnabled(True)

    # ---- the other two buttons -------------------------------------------------
    def _open_page(self) -> None:
        page = self.release.page if self.release else updates.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(page))

    def _snooze(self) -> None:
        if self.release is not None:
            with connect() as conn:
                updates.snooze(conn, self.release)
        self.hide()
