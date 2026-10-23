"""帶出門: build the phone page from whatever is ticked on the queue screen.

Carrying the whole queue out was the first shape and the wrong one. An hour away
from the desk is two or three papers, and every paper in the page is a PDF that has
to travel; fifteen of them is 16 MB and a scroll past fourteen titles to reach the
one being read. Ticking a few and rebuilding is the shape that matches the errand.

Publishing is deliberately not here. A published artifact belongs to a Claude
session, and the one thing this app must never do is call a model or an HTTP API
behind the user's back. The dialog builds the files and hands over the sentence that
publishes them.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import pocket
from paper_daily.desktop import fonts
from paper_daily.store import connect, get_kv, set_kv


class _BuildWorker(QObject):
    finished = Signal(object, str)  # result dict or None, error message

    def __init__(self, paper_ids: list[str]) -> None:
        super().__init__()
        self._ids = paper_ids

    def run(self) -> None:
        try:
            self.finished.emit(pocket.write(self._ids), "")
        except Exception as e:  # the dialog is the only place this can be reported
            self.finished.emit(None, f"{type(e).__name__}: {e}")


class PocketDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.win = window
        self.pal = window.pal
        pal = self.pal
        self._thread: QThread | None = None
        self._worker: _BuildWorker | None = None

        self.setWindowTitle("帶出門")
        self.setMinimumWidth(560)
        self.setStyleSheet(f"background:{pal['ground']};color:{pal['ink']};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        heading = QLabel("帶出門")
        heading.setFont(fonts.font(fonts.SERIF, 15, QFont.Weight.DemiBold))
        outer.addWidget(heading)

        self.blurb = QLabel()
        self.blurb.setWordWrap(True)
        self.blurb.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        outer.addWidget(self.blurb)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget{{background:{pal['surface']};border:1px solid {pal['border']};"
            f"font-size:12px;}}"
            f"QListWidget::item{{padding:5px 8px;}}"
        )
        outer.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.drop_btn = self._button("移除選取的")
        self.drop_btn.clicked.connect(self._drop_selected)
        row.addWidget(self.drop_btn)
        self.clear_btn = self._button("全部清掉")
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        self.build_btn = self._button("重建頁面", primary=True)
        self.build_btn.clicked.connect(self._build)
        row.addWidget(self.build_btn)
        outer.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        outer.addWidget(self.status)

        # The link never changes: republishing replaces the same page, so this is the
        # one address the phone ever needs.
        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        self.url = QLineEdit()
        self.url.setPlaceholderText("還沒有發佈過。發佈之後把網址貼在這裡,之後就一直是它。")
        self.url.setStyleSheet(
            f"QLineEdit{{background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};padding:5px 8px;font-size:12px;}}"
        )
        self.url.editingFinished.connect(self._save_url)
        link_row.addWidget(self.url, 1)
        self.open_btn = self._button("開啟")
        self.open_btn.clicked.connect(self._open_url)
        link_row.addWidget(self.open_btn)
        outer.addLayout(link_row)

        self.hint = QLabel(
            "重建只寫出 <code>data/pocket/</code> 的檔案。要讓手機看到新的一份,"
            "跟 Claude 說一句「發佈口袋頁」就行,網址不會變。"
        )
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.hint.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        outer.addWidget(self.hint)

        self._load()

    def _button(self, text: str, primary: bool = False) -> QPushButton:
        pal = self.pal
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        bg = pal["accent"] if primary else pal["surface"]
        fg = "#ffffff" if primary else pal["ink"]
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid "
            f"{pal['accent'] if primary else pal['firm']};padding:5px 14px;font-size:12px;}}"
            f"QPushButton:disabled{{color:{pal['faint']};}}"
        )
        return b

    def _load(self) -> None:
        ids = self.win.marked_ids()
        self.list.clear()
        if not ids:
            self.blurb.setText(
                "還沒有勾選任何論文。回到清單畫面,點每一列左邊的方框把要帶的勾起來。"
            )
        else:
            self.blurb.setText(
                f"勾了 {len(ids)} 篇。每一篇都會帶一份壓過的 PDF 出門,"
                "所以挑你真的會在路上讀的那幾篇。"
            )
        with connect() as conn:
            rows = {
                r["id"]: r
                for r in conn.execute(
                    "SELECT id, title, venue, year FROM papers WHERE id IN "
                    f"({','.join('?' * len(ids))})",
                    ids,
                ).fetchall()
            } if ids else {}
        for pid in ids:
            row = rows.get(pid)
            title = row["title"] if row else pid
            # A venue name runs to "International Conference on Medical Image
            # Computing and Computer-Assisted Intervention", which pushes the part
            # that matters -- whether it can carry its original -- off the row.
            venue = row["venue"] if row else ""
            if len(venue) > 26:
                venue = venue[:26].rstrip() + "…"
            where = f"{venue} {row['year']}" if row else "不在資料庫裡"
            carries = "有原文" if pocket.has_pdf(pid) else "沒有原文 PDF"
            item = QListWidgetItem(f"{title[:72]}\n{carries} · {where}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.list.addItem(item)

        self.build_btn.setEnabled(bool(ids))
        self.drop_btn.setEnabled(bool(ids))
        self.clear_btn.setEnabled(bool(ids))

        with connect() as conn:
            self.url.setText(get_kv(conn, "pocket.url") or "")

    def _drop_selected(self) -> None:
        drop = {i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()}
        if not drop:
            self.status.setText("先在上面選要移除的那幾列。")
            return
        self.win.set_marked([p for p in self.win.marked_ids() if p not in drop])
        self._load()

    def _clear(self) -> None:
        self.win.set_marked([])
        self._load()

    def _save_url(self) -> None:
        with connect() as conn:
            set_kv(conn, "pocket.url", self.url.text().strip())

    def _open_url(self) -> None:
        link = self.url.text().strip()
        if link.startswith("https://"):
            QDesktopServices.openUrl(QUrl(link))
        else:
            self.status.setText("還沒有網址可以開。")

    def _build(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        ids = self.win.marked_ids()
        if not ids:
            return
        from paper_daily.desktop.activity import begin

        self._activity = begin(self, "製作攜帶閱讀頁", key="pocket-build")
        if not self._activity.accepted:
            return
        self.build_btn.setEnabled(False)
        self.status.setText("正在壓 PDF、整理引用與血緣… 第一次跑每篇要幾秒。")

        if self._thread is not None:
            self._thread.wait()
        self._thread = QThread()
        self._worker = _BuildWorker(ids)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._done)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    @Slot(object, str)
    def _done(self, built, error: str) -> None:
        self._activity.finish(built is not None)
        self.build_btn.setEnabled(True)
        if built is None:
            self.status.setText(f"建不出來:{error}")
            return
        papers = built["papers"]
        lines = [
            f"好了:{len(papers)} 篇 · 頁面 {built['page_bytes'] // 1024} KB · "
            f"附檔 {built['total_bytes'] / 1e6:.1f} MB · "
            f"逐節精讀 {sum(1 for p in papers if p['close'])} 篇 · "
            f"簡報 {sum(len(p['decks']) for p in papers)} 份 · "
            f"清單綜覽 {len(built['surveys'])} 份"
        ]
        if built["no_pdf"]:
            lines.append(
                "沒有原文 PDF(出版社沒開放),這幾篇只會有摘要和深度講解:"
                + "、".join(t[:30] for t in built["no_pdf"])
            )
        lines.append("跟 Claude 說「發佈口袋頁」就會更新到同一個網址。")
        self.status.setText("\n".join(lines))
