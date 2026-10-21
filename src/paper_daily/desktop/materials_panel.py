"""素材 panel: the paper's exhibits, headings and quotable sentences, ready to drop
on a slide."""

from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDrag, QImage, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paper_daily import materials as material_store
from paper_daily.desktop import ai_style
from paper_daily.desktop.slide_canvas import MATERIAL_MIME
from paper_daily.fetch import _safe_name
from paper_daily.materials import Materials


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


GROUPS = (("exhibits", "圖表"), ("headings", "章節標題"), ("sentences", "關鍵句"))
KINDS = {
    "problem": "研究問題",
    "contribution": "貢獻",
    "method": "方法",
    "evidence": "實驗證據",
    "limitation": "限制",
    "definition": "定義",
}


class _Tree(QTreeWidget):
    def supportedDropActions(self):
        return Qt.DropAction.CopyAction

    def mimeTypes(self):
        return [MATERIAL_MIME]

    def mimeData(self, items):
        payload = next((i.data(0, Qt.ItemDataRole.UserRole) for i in items if i), None)
        mime = QMimeData()
        if payload:
            mime.setData(MATERIAL_MIME, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            mime.setText(payload.get("text") or payload.get("label", ""))
        return mime


class MaterialsPanel(QWidget):
    chosen = Signal(dict)
    source_requested = Signal(dict)
    analyze_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.paper_id = None
        self._preview_image = QImage()
        self._preview_error = ""
        self._detail_height = 220
        self._image_dialog = None
        self._preview_drag_start = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("素材")
        self.title.setStyleSheet("font-weight:bold")
        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch()
        self.detail_toggle = QPushButton("詳細內容")
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setChecked(True)
        header.addWidget(self.detail_toggle)
        layout.addLayout(header)
        self.analyze = QPushButton("AI 挑選原文重點")
        self.analyze.clicked.connect(self.analyze_requested.emit)
        self.analyze.setToolTip("從原文判斷研究重要性與資訊量；首次分析與重新分析會使用 AI。")
        ai_style.mark(self.analyze)
        layout.addWidget(self.analyze)
        self.analysis_status = QLabel("尚未分析；點上方按鈕讓 AI 從原文挑選。")
        self.analysis_status.setWordWrap(True)
        layout.addWidget(self.analysis_status)
        self.tree = _Tree()
        self.tree.setHeaderHidden(True)
        # One line per material, so the list scans like a menu; the full caption,
        # image, table or sentence is in the detail pane below.
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.itemClicked.connect(lambda _item, _column: self._locate_selected())
        self.tree.setDragEnabled(True)
        self.tree.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.details_split = QSplitter(Qt.Orientation.Vertical)
        self.details_split.setHandleWidth(8)
        self.tree.setMinimumSize(0, 50)
        self.details_split.addWidget(self.tree)
        self.detail = QTextBrowser()
        self.detail.setMinimumSize(0, 50)
        self.detail.setPlaceholderText("選取素材，預覽原圖、完整表格或原文重點。")
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(self._open_preview_image)
        self.detail.viewport().installEventFilter(self)
        self.tree.currentItemChanged.connect(self._selected)
        self.details_split.addWidget(self.detail)
        self.details_split.setSizes([300, 220])
        self.details_split.setStretchFactor(0, 1)
        self.details_split.setStretchFactor(1, 1)
        self.detail_toggle.toggled.connect(self._toggle_detail)
        self.details_split.splitterMoved.connect(self._sync_detail_toggle)
        layout.addWidget(self.details_split, 1)
        self.insert_button = QPushButton("加入目前投影片")
        self.insert_button.setEnabled(False)
        self.insert_button.clicked.connect(self._insert_selected)
        layout.addWidget(self.insert_button)
        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        layout.addWidget(self.feedback)
        self.hint = QLabel(
            "雙擊素材、按「加入目前投影片」，或拖到任一簡報視角。加入後會選取新物件。"
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.setMinimumWidth(170)

    def clear(self) -> None:
        self._preview_timer.stop()
        self.paper_id = None
        self._preview_image = QImage()
        self._preview_error = ""
        self.tree.clear()
        self.detail.clear()
        self.insert_button.setEnabled(False)
        self.feedback.clear()
        self.feedback.hide()
        self.analysis_status.setText("尚未分析；點上方按鈕讓 AI 從原文挑選。")
        self.analyze.setText("AI 挑選原文重點")

    def load(self, materials: Materials | None) -> None:
        self.clear()
        if materials is None:
            return
        self.paper_id = materials.paper_id
        if materials.highlights:
            coverage = materials.highlights.get("coverage", {})
            warning = " 部分頁面沒有文字，可能需要 OCR。" if coverage.get("empty_pages") else ""
            if not coverage.get("has_page_numbers", True):
                warning += " 原文文字沒有頁碼。"
            self.analysis_status.setText("AI 已分析原文；引句已核對。理由是 AI 判斷。" + warning)
            self.analyze.setText("重新分析原文重點")
        groups = {}
        for key, label in GROUPS:
            group = QTreeWidgetItem([label])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(group)
            groups[key] = group
        for item in materials.exhibits:
            caption = item.get("caption", "")
            node = self._item(
                "  ".join(
                    x
                    for x in (
                        item["label"],
                        f"p.{item['page']}" if item.get("page") else "",
                        _one_line(caption).removeprefix(item["label"]).lstrip(" .:："),
                    )
                    if x
                ),
                dict(
                    kind="exhibit",
                    **{
                        k: item.get(k)
                        for k in (
                            "id",
                            "file",
                            "label",
                            "caption",
                            "page",
                            "rows",
                            "rect",
                            "document_hash",
                        )
                    },
                ),
                caption,
            )
            groups["exhibits"].addChild(node)
            if item.get("rows"):
                rows = item["rows"]
                node.addChild(
                    self._item(
                        f"表格資料 {len(rows)}×{len(rows[0])}（可編輯）",
                        dict(
                            kind="table",
                            id=item["id"],
                            label=item["label"],
                            page=item.get("page"),
                            rect=item.get("rect"),
                            document_hash=item.get("document_hash"),
                            rows=rows,
                        ),
                        " | ".join(rows[0]),
                    )
                )
        for item in materials.headings:
            indent = "　" * max(0, item.get("level", 1) - 1)
            groups["headings"].addChild(
                self._item(
                    indent + item["text"],
                    dict(item, kind="heading"),
                    item["text"],
                )
            )
        for item in materials.sentences:
            page = f"p.{item['page']} · " if item.get("page") else ""
            groups["sentences"].addChild(
                self._item(
                    page
                    + (
                        "手動螢光筆"
                        if item.get("origin") == "manual"
                        else KINDS.get(item.get("kind"), "")
                    )
                    + " · "
                    + _one_line(item["text"]),
                    dict(
                        kind="sentence",
                        text=item["text"],
                        page=item.get("page"),
                        source=item.get("source"),
                        reason=item.get("reason", ""),
                        anchor=item.get("anchor"),
                        mark_id=item.get("mark_id"),
                        origin=item.get("origin", "ai"),
                    ),
                    "AI 選取理由：" + item.get("reason", "") + "\n\n原文：\n" + item["text"],
                )
            )
        for key, group in groups.items():
            group.setText(0, f"{group.text(0)}（{group.childCount()}）")
            group.setExpanded(key == "sentences" or (key == "exhibits" and not materials.sentences))
        for key in ("exhibits", "sentences", "headings"):
            if groups[key].childCount():
                groups[key].setExpanded(True)
                self.tree.setCurrentItem(groups[key].child(0))
                break
        self.hint.setText(
            "雙擊素材、按「加入目前投影片」，或拖到任一簡報視角。加入後會選取新物件。"
            if materials.exhibits or materials.headings or materials.sentences
            else "這篇還沒有可用素材：需要原文 PDF 與抽取的圖表，表格資料來自逐節精讀。"
        )

    def _toggle_detail(self, checked):
        sizes = self.details_split.sizes()
        if not checked and sizes[1] > 0:
            self._detail_height = sizes[1]
        self.detail.setVisible(checked)
        if checked:
            total = max(200, sum(sizes))
            height = min(self._detail_height, total - 80)
            self.details_split.setSizes([total - height, height])
            self._render_preview()

    def _sync_detail_toggle(self, *_args):
        with QSignalBlocker(self.detail_toggle):
            self.detail_toggle.setChecked(self.details_split.sizes()[1] > 0)

    def select_highlight(self, mark_id=None):
        group = self.tree.topLevelItem(2)
        if not group or not group.childCount():
            return False
        node = group.child(0)
        if mark_id is not None:
            node = next(
                (
                    group.child(i)
                    for i in range(group.childCount())
                    if group.child(i).data(0, Qt.ItemDataRole.UserRole).get("mark_id") == mark_id
                ),
                None,
            )
            if node is None:
                return False
        group.setExpanded(True)
        self.tree.setCurrentItem(node)
        self.tree.scrollToItem(node)
        self.detail_toggle.setChecked(True)
        return True

    def _locate_selected(self):
        item = self.tree.currentItem()
        payload = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if payload:
            self.source_requested.emit(payload)

    def _insert_selected(self):
        item = self.tree.currentItem()
        if item:
            self._double_clicked(item, 0)

    def show_feedback(self, text, success=False):
        self.feedback.setText(text)
        self.feedback.setStyleSheet("color:#28613b" if success else "color:#a34b00")
        self.feedback.show()

    def eventFilter(self, watched, event):
        if watched is self.detail.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                cursor = self.detail.cursorForPosition(event.position().toPoint())
                self._preview_drag_start = (
                    event.position().toPoint()
                    if event.button() == Qt.MouseButton.LeftButton
                    and cursor.charFormat().isImageFormat()
                    else None
                )
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                cursor = self.detail.cursorForPosition(event.position().toPoint())
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and cursor.charFormat().isImageFormat()
                ):
                    self._preview_drag_start = None
                    self._insert_selected()
                    return True
            elif event.type() == QEvent.Type.MouseMove and self._preview_drag_start is not None:
                distance = (event.position().toPoint() - self._preview_drag_start).manhattanLength()
                if (
                    event.buttons() & Qt.MouseButton.LeftButton
                    and distance >= QApplication.startDragDistance()
                ):
                    self._preview_drag_start = None
                    item = self.tree.currentItem()
                    if item:
                        drag = QDrag(self.detail)
                        drag.setMimeData(self.tree.mimeData([item]))
                        if not self._preview_image.isNull():
                            drag.setPixmap(
                                QPixmap.fromImage(self._preview_image).scaledToWidth(160)
                            )
                        drag.exec(Qt.DropAction.CopyAction)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._preview_drag_start = None
        if watched is self.detail.viewport() and event.type() == QEvent.Type.Resize:
            self._preview_timer.start(30)
        return super().eventFilter(watched, event)

    def _selected(self, item, _previous) -> None:
        self._preview_image = QImage()
        self._preview_error = ""
        payload = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.insert_button.setEnabled(bool(payload))
        self.feedback.hide()
        if payload and payload.get("kind") == "exhibit":
            name = payload.get("file")
            if self.paper_id and isinstance(name, str) and Path(name).name == name:
                folder = (material_store.FIG_DIR / _safe_name(self.paper_id)).resolve()
                image_path = (folder / name).resolve()
                if image_path.is_relative_to(folder):
                    self._preview_image = QImage(str(image_path))
            if self._preview_image.isNull():
                self._preview_error = "找不到可預覽的原圖；以下仍保留說明與可用表格資料。"
        self._render_preview(reset_scroll=True)

    def _render_preview(self, *, reset_scroll=False):
        item = self.tree.currentItem()
        payload = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not payload:
            self.detail.setPlainText("選取下方的圖表、章節或關鍵句，查看完整內容。" if item else "")
            return
        e = html.escape
        label = str(
            payload.get("label")
            or {"sentence": "原文重點", "heading": "章節標題"}.get(payload["kind"], "素材")
        )
        page = f" · p.{payload['page']}" if payload.get("page") else ""
        parts = [f"<b>{e(label + page)}</b>"]
        if not self._preview_image.isNull():
            width = max(80, min(self._preview_image.width(), self.detail.viewport().width() - 24))
            height = round(width * self._preview_image.height() / self._preview_image.width())
            parts.append(
                f'<p><img src="paperfact-material:preview" width="{width}" height="{height}"></p>'
                '<p><a href="paperfact:full-image">放大原圖</a></p>'
            )
        if self._preview_error:
            parts.append(f"<p>{e(self._preview_error)}</p>")
        if payload.get("caption"):
            parts.append(f"<p>{e(payload['caption'])}</p>")
        rows = payload.get("rows")
        if rows:
            parts.append("<p><b>可編輯表格資料</b>（由精讀整理，請核對原圖）</p>")
            table = []
            for i, row in enumerate(rows):
                tag = "th" if i == 0 else "td"
                table.append(
                    "<tr>" + "".join(f"<{tag}>{e(str(cell))}</{tag}>" for cell in row) + "</tr>"
                )
            parts.append(
                '<table border="1" cellspacing="0" cellpadding="5">' + "".join(table) + "</table>"
            )
        if payload["kind"] == "sentence":
            parts.append(
                "<p><b>原文</b></p><p>" + e(payload.get("text", "")).replace("\n", "<br>") + "</p>"
            )
            parts.append(
                (
                    "<p><b>手動標記</b></p><p>"
                    if payload.get("origin") == "manual"
                    else "<p><b>AI 選取理由</b></p><p>"
                )
                + e(
                    payload.get("reason")
                    or (
                        "你在原文選取的螢光句子。"
                        if payload.get("origin") == "manual"
                        else "尚無選取理由。"
                    )
                )
                + "</p>"
            )
        elif payload["kind"] == "heading":
            parts.append(f"<p>{e(payload.get('text', ''))}</p>")
        scroll = self.detail.verticalScrollBar().value()
        self.detail.setHtml("".join(parts))
        if not self._preview_image.isNull():
            self.detail.document().addResource(
                QTextDocument.ResourceType.ImageResource,
                QUrl("paperfact-material:preview"),
                self._preview_image,
            )
            self.detail.document().markContentsDirty(0, self.detail.document().characterCount())
        self.detail.verticalScrollBar().setValue(0 if reset_scroll else scroll)

    def _open_preview_image(self, url):
        if url.toString() != "paperfact:full-image" or self._preview_image.isNull():
            return
        if self._image_dialog:
            self._image_dialog.close()
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle("素材原圖 · " + self.tree.currentItem().text(0))
        layout = QVBoxLayout(dialog)
        area = QScrollArea()
        picture = QLabel()
        picture.setPixmap(QPixmap.fromImage(self._preview_image))
        area.setWidget(picture)
        layout.addWidget(area)
        dialog.resize(1000, 720)
        self._image_dialog = dialog
        dialog.finished.connect(lambda: setattr(self, "_image_dialog", None))
        dialog.show()

    def _item(self, text: str, payload: dict, tooltip: str) -> QTreeWidgetItem:
        node = QTreeWidgetItem([text])
        node.setData(0, Qt.ItemDataRole.UserRole, payload)
        node.setToolTip(0, tooltip)
        node.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        return node

    def _double_clicked(self, item, _column) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload:
            self.chosen.emit(payload)
