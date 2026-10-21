"""In-place slide editing with native text selection and movable objects."""

from __future__ import annotations

import json
from contextlib import suppress
from copy import deepcopy

from PySide6.QtCore import QMimeData, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from paper_daily import presentations
from paper_daily.desktop import ai_style, fonts
from paper_daily.slide_layout import (
    HEIGHT,
    WIDTH,
    elements_for,
    text_box,
    validate_elements,
    validate_rows,
)

MATERIAL_MIME = "application/x-paperfact-material"


class EditableText(QGraphicsTextItem):
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)


class CanvasObject(QGraphicsObject):
    def __init__(self, spec: dict, editor):
        super().__init__()
        self.spec = deepcopy(spec)
        self.editor = editor
        self.resizing = False
        self.text = None
        self.pixmap = QPixmap()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setPos(spec["x"], spec["y"])
        self.setAcceptHoverEvents(True)
        if spec["kind"] == "text":
            self.text = EditableText(self)
            self.text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.text.document().setDocumentMargin(0)
            self.text.setPlainText(spec["text"])
            self.style_text()
            self.text.document().contentsChanged.connect(self._text_changed)
        elif spec["kind"] == "figure":
            with suppress(ValueError, OSError):
                self.pixmap = QPixmap.fromImage(
                    QImage.fromData(presentations.figure_bytes(editor.deck, spec["figure"]))
                )
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)

    def boundingRect(self):
        return QRectF(0, 0, self.spec["w"], self.spec["h"])

    def paint(self, painter, option, widget=None):
        rect = self.boundingRect()
        if self.spec["kind"] == "table":
            self._paint_table(painter, rect)
        elif self.spec["kind"] == "figure":
            if not self.pixmap.isNull():
                target = self.pixmap.size().scaled(
                    rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio
                )
                pos = rect.center() - QPointF(target.width() / 2, target.height() / 2)
                painter.drawPixmap(
                    QRectF(pos, QSizeF(target)), self.pixmap, QRectF(self.pixmap.rect())
                )
            else:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "原圖無法讀取")
        if self.isSelected():
            painter.setPen(QPen(QColor("#3977df"), 2))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.fillRect(
                QRectF(rect.width() - 12, rect.height() - 12, 12, 12), QColor("#3977df")
            )

    def _paint_table(self, painter, rect):
        rows, header = self.spec["rows"], self.spec["header"]
        font = fonts.font()
        font.setPixelSize(round(self.spec["size"]))
        metrics = QFontMetricsF(font)

        # Columns share the width in proportion to their longest cell, so a label
        # column is not squeezed to the width of a numeric one.
        def width(text):
            return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)

        weights = [max(max(width(r[c]) for r in rows), 3) for c in range(len(rows[0]))]
        total = sum(weights)
        widths = [rect.width() * w / total for w in weights]
        row_h = rect.height() / len(rows)
        painter.fillRect(rect, QColor("white"))
        y = 0.0
        for ri, row in enumerate(rows):
            if ri == 0 and header:
                painter.fillRect(QRectF(0, y, rect.width(), row_h), QColor("#eef2f9"))
            font.setBold(ri == 0 and header)
            painter.setFont(font)
            x = 0.0
            for ci, cell in enumerate(row):
                box = QRectF(x, y, widths[ci], row_h)
                painter.setPen(QPen(QColor("#c9d2e0"), 1))
                painter.drawRect(box)
                painter.setPen(QColor("#172238"))
                painter.drawText(
                    box.adjusted(5, 0, -5, 0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    metrics.elidedText(cell, Qt.TextElideMode.ElideRight, widths[ci] - 10),
                )
                x += widths[ci]
            y += row_h

    def style_text(self):
        if self.text is None:
            return
        font = fonts.font()
        font.setPixelSize(round(self.spec["size"]))
        font.setBold(self.spec["bold"])
        self.text.setFont(font)
        self.text.setDefaultTextColor(QColor(self.spec["color"]))
        self.text.setTextWidth(self.spec["w"])
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment(
            {
                "left": Qt.AlignmentFlag.AlignLeft,
                "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight,
            }[self.spec["align"]]
        )
        self.text.document().setDefaultTextOption(option)

    def _text_changed(self):
        self.spec["text"] = self.text.toPlainText()
        self.editor.report_fit()
        self.editor.changed.emit()

    def finish_edit(self):
        if self.text:
            self.text.clearFocus()
            self.text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self.text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            cursor = self.text.textCursor()
            cursor.clearSelection()
            self.text.setTextCursor(cursor)

    def mouseDoubleClickEvent(self, event):
        if self.text:
            self.text.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.text.setFocus()
            cursor = (
                self.text.document()
                .documentLayout()
                .hitTest(event.pos(), Qt.HitTestAccuracy.FuzzyHit)
            )
            tc = self.text.textCursor()
            tc.setPosition(max(0, cursor))
            self.text.setTextCursor(tc)
            event.accept()
        elif self.spec["kind"] == "table":
            self.editor.edit_table(self)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        self.editor.finish_editing()
        self.resizing = (
            event.pos().x() > self.spec["w"] - 18 and event.pos().y() > self.spec["h"] - 18
        )
        if self.resizing:
            self.setSelected(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.resizing:
            self.prepareGeometryChange()
            self.spec["w"] = max(20, min(WIDTH - self.x(), event.pos().x()))
            self.spec["h"] = max(12, min(HEIGHT - self.y(), event.pos().y()))
            self.style_text()
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.resizing = False
        self.editor.report_fit()
        self.editor.changed.emit()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(
                max(0, min(WIDTH - self.spec["w"], value.x())),
                max(0, min(HEIGHT - self.spec["h"], value.y())),
            )
        return super().itemChange(change, value)

    def snapshot(self):
        obj = deepcopy(self.spec)
        obj.update(x=self.x(), y=self.y())
        return obj


class CanvasView(QGraphicsView):
    zoom_changed = Signal(int, bool)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.fit_mode = True
        self._fitting = False
        self._pan_start = None
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def fit_slide(self):
        if self._fitting:
            return
        self._fitting = True
        self.fit_mode = True
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fitInView(
            QRectF(-16, -16, WIDTH + 32, HEIGHT + 32), Qt.AspectRatioMode.KeepAspectRatio
        )
        self.centerOn(WIDTH / 2, HEIGHT / 2)
        self._fitting = False
        self.zoom_changed.emit(round(self.transform().m11() * 100), True)

    def set_zoom(self, percent):
        percent = max(10, min(300, percent))
        self.fit_mode = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scale(
            percent / (self.transform().m11() * 100), percent / (self.transform().m11() * 100)
        )
        self.zoom_changed.emit(round(percent), False)

    def zoom_by(self, factor):
        self.set_zoom(round(self.transform().m11() * 100 * factor))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_slide()

    def showEvent(self, event):
        super().showEvent(event)
        if self.fit_mode:
            self.fit_slide()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.zoom_by(1.15 if delta > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - round(delta.x())
            )
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        scene = self.scene()
        focus = scene.focusItem()
        if isinstance(focus, QGraphicsTextItem) and focus.textInteractionFlags():
            if event.key() == Qt.Key.Key_Escape:
                focus.parentItem().finish_edit()
                return
            super().keyPressEvent(event)
            return
        editor = self.parent()
        if event.key() == Qt.Key.Key_Escape:
            scene.clearSelection()
            scene.clearFocus()
            event.accept()
            return
        shortcuts = (
            (QKeySequence.StandardKey.Copy, editor.copy_selected),
            (QKeySequence.StandardKey.Cut, editor.cut_selected),
            (QKeySequence.StandardKey.Paste, editor.paste),
            (QKeySequence.StandardKey.SelectAll, editor.select_all),
            (QKeySequence.StandardKey.Undo, editor.undo_requested.emit),
            (QKeySequence.StandardKey.Redo, editor.redo_requested.emit),
        )
        for key, callback in shortcuts:
            if event.matches(key):
                changes = key in (QKeySequence.StandardKey.Cut, QKeySequence.StandardKey.Paste)
                if changes:
                    editor.edit_boundary.emit()
                callback()
                if changes:
                    editor.edit_boundary.emit()
                event.accept()
                return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_D:
            editor.duplicate_selected()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            editor.edit_boundary.emit()
            self.parent().remove_selected()
            editor.edit_boundary.emit()
            return
        steps = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() in steps:
            dx, dy = steps[event.key()]
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            for item in scene.selectedItems():
                item.moveBy(dx * step, dy * step)
            self.parent().changed.emit()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MATERIAL_MIME) and self.parent().deck:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MATERIAL_MIME) and self.parent().deck:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MATERIAL_MIME) or not self.parent().deck:
            super().dropEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        self.parent().material_dropped.emit(
            bytes(event.mimeData().data(MATERIAL_MIME)).decode("utf-8"), point.x(), point.y()
        )
        event.acceptProposedAction()

    def contextMenuEvent(self, event):
        focus = self.scene().focusItem()
        if isinstance(focus, QGraphicsTextItem) and focus.textInteractionFlags():
            super().contextMenuEvent(event)
            return
        item = self.itemAt(event.pos())
        while item and not isinstance(item, CanvasObject):
            item = item.parentItem()
        if item and not item.isSelected():
            self.scene().clearSelection()
            item.setSelected(True)
        editor = self.parent()
        menu = QMenu(self)
        for label, callback in (
            ("復原\t" + fonts.key(QKeySequence.StandardKey.Undo), editor.undo_requested.emit),
            ("重做\t" + fonts.key(QKeySequence.StandardKey.Redo), editor.redo_requested.emit),
            ("剪下\t" + fonts.key(QKeySequence.StandardKey.Cut), editor.cut_selected),
            ("複製\t" + fonts.key(QKeySequence.StandardKey.Copy), editor.copy_selected),
            ("貼上\t" + fonts.key(QKeySequence.StandardKey.Paste), editor.paste),
            ("複製物件\t" + fonts.key("Ctrl+D"), editor.duplicate_selected),
            ("全選\t" + fonts.key(QKeySequence.StandardKey.SelectAll), editor.select_all),
            ("刪除\t" + fonts.DELETE, editor.remove_selected),
        ):
            menu.addAction(label, callback)
        menu.exec(event.globalPos())


class SlideCanvas(QWidget):
    changed = Signal()
    edit_boundary = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    material_dropped = Signal(str, float, float)
    revise_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.deck = None
        self.can_add_sources = lambda sources: True
        self.objects = []
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("本頁物件"))
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 96)
        self.font_size.setValue(27)
        self.font_size.setSuffix(" px")
        self.font_size.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.font_size.setKeyboardTracking(False)
        self.font_size.setToolTip("選取文字框的字級")
        self.font_size.valueChanged.connect(lambda v: self.format_selected(size=v))
        bar.addWidget(self.font_size)
        self.bold = QPushButton("B")
        self.bold.setMaximumWidth(32)
        self.bold.setProperty("compact", True)
        self.bold.setCheckable(True)
        self.bold.setEnabled(False)
        self.bold.setToolTip("選取文字框以設定粗體；底色表示已啟用。")
        self.bold.clicked.connect(self.toggle_bold)
        bar.addWidget(self.bold)
        color = QPushButton("字色")
        color.clicked.connect(self.choose_color)
        bar.addWidget(color)
        text = QPushButton("＋文字")
        text.clicked.connect(self.add_text)
        bar.addWidget(text)
        bar.addStretch()
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.revise_instruction = QPlainTextEdit()
        self.revise_instruction.setPlaceholderText(
            "這一頁要怎麼改？例如：改給臨床醫師聽、換成 Table 2 的數字"
        )
        self.revise_instruction.setFixedHeight(68)
        self.revise_instruction.setMinimumWidth(80)
        self.revise_button = QPushButton("AI 改寫這頁")
        self.revise_button.clicked.connect(self.revise_requested.emit)
        ai_style.mark(self.revise_button)
        bar.addWidget(self.revise_instruction, 1)
        bar.addWidget(self.revise_button)
        layout.addLayout(bar)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(-16, -16, WIDTH + 32, HEIGHT + 32)
        self.view = CanvasView(self.scene, self)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.setAcceptDrops(True)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.view.setBackgroundBrush(QColor("#e8edf5"))
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setMinimumSize(100, 100)
        layout.addWidget(self.view, 1)
        zoom_bar = QHBoxLayout()
        zoom_bar.addWidget(QLabel("畫布縮放"))
        self.zoom_out = QPushButton("-")
        self.zoom_out.setFixedWidth(28)
        self.zoom_out.setProperty("compact", True)
        self.zoom_out.clicked.connect(lambda: self.view.zoom_by(1 / 1.2))
        zoom_bar.addWidget(self.zoom_out)
        self.zoom = QSpinBox()
        self.zoom.setRange(10, 300)
        self.zoom.setSuffix(" %")
        self.zoom.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.zoom.setKeyboardTracking(False)
        self.zoom.setToolTip(f"只改變觀看大小，不改變字級與匯出尺寸。{fonts.ZOOM_WHEEL}縮放；中鍵拖曳平移。")
        self.zoom.valueChanged.connect(self.view.set_zoom)
        zoom_bar.addWidget(self.zoom)
        self.zoom_in = QPushButton("+")
        self.zoom_in.setFixedWidth(28)
        self.zoom_in.setProperty("compact", True)
        self.zoom_in.clicked.connect(lambda: self.view.zoom_by(1.2))
        zoom_bar.addWidget(self.zoom_in)
        self.fit_button = QPushButton("適合視窗")
        self.fit_button.setCheckable(True)
        self.fit_button.setChecked(True)
        self.fit_button.clicked.connect(self.view.fit_slide)
        zoom_bar.addWidget(self.fit_button)
        zoom_bar.addStretch()
        self.view.zoom_changed.connect(self._zoom_changed)
        layout.addLayout(zoom_bar)
        self.hint = QLabel(f"空白畫布 ↑↓ 換頁 · Esc 取消選取 · {fonts.ALT}左右切換視角")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.scene.selectionChanged.connect(self._selection)

    def _zoom_changed(self, percent, fitting):
        self.zoom.blockSignals(True)
        self.zoom.setValue(percent)
        self.zoom.blockSignals(False)
        self.fit_button.setChecked(fitting)

    def load(self, deck, index):
        self._loading = True
        self.deck = deck
        self.objects = []
        self.scene.clear()
        paper = self.scene.addRect(0, 0, WIDTH, HEIGHT, QPen(Qt.PenStyle.NoPen), QColor("white"))
        paper.setZValue(-10)
        self.scene.addRect(0, 0, 10, HEIGHT, QPen(Qt.PenStyle.NoPen), QColor("#2356bd"))
        if deck:
            for spec in elements_for(deck.slides[index]):
                self._insert(spec)
            footer = self.scene.addText(
                f"Paperfact     {index + 1:02d} / {len(deck.slides):02d}     "
                + f"引用 {len(deck.slides[index].sources)} 項："
                + " · ".join(
                    next((str(s.get("label", sid)) for s in deck.sources if s["id"] == sid), sid)
                    for sid in deck.slides[index].sources
                )[:70]
            )
            footer.setDefaultTextColor(QColor("#68788f"))
            font = fonts.font()
            font.setPixelSize(14)
            footer.setFont(font)
            footer.setPos(56, 628)
        else:
            message = self.scene.addText(
                "將這篇論文變成可編輯的導讀\n\n按「生成投影片」，整理背景、原圖與講稿。"
            )
            font = fonts.font()
            font.setPixelSize(30)
            message.setFont(font)
            message.setPos(64, 210)
        self.setEnabled(bool(deck))
        self._loading = False
        self._selection()
        self.report_fit()

    def report_fit(self):
        if self._loading:
            return
        overflow = any(
            o.text and o.text.document().size().height() > o.spec["h"] + 2 for o in self.objects
        )
        self.hint.setText(
            "文字超出文字框，匯出會裁切。請拉大文字框或調整字級。"
            if overflow
            else f"空白畫布 ↑↓ 換頁 · Esc 取消選取 · {fonts.ALT}左右切換視角"
        )
        self.hint.setStyleSheet("color:#a34b00" if overflow else "")

    def _insert(self, spec):
        item = CanvasObject(spec, self)
        item.setZValue(len(self.objects) + 1)
        self.objects.append(item)
        self.scene.addItem(item)
        return item

    def _selection(self):
        if self._loading:
            return
        items = [i for i in self.scene.selectedItems() if isinstance(i, CanvasObject)]
        text_items = [i for i in items if i.text]
        self.bold.setEnabled(bool(text_items))
        self.bold.setChecked(bool(text_items) and all(i.spec.get("bold") for i in text_items))
        mixed = bool(text_items) and len({bool(i.spec.get("bold")) for i in text_items}) > 1
        self.bold.setToolTip(
            "選取文字的粗體狀態混合；按下可全部設為粗體。"
            if mixed
            else "粗體已啟用；按下取消。"
            if self.bold.isChecked()
            else "選取文字框以設定粗體；底色表示已啟用。"
        )
        if items and "size" in items[0].spec:
            self.font_size.blockSignals(True)
            self.font_size.setValue(round(items[0].spec["size"]))
            self.font_size.blockSignals(False)

    def finish_editing(self):
        for obj in self.objects:
            obj.finish_edit()

    def snapshot(self):
        return [obj.snapshot() for obj in self.objects]

    def add_text(self):
        if not self.deck or len(self.objects) >= 60:
            return
        self.finish_editing()
        self.scene.clearSelection()
        item = self._insert(text_box("輸入文字", 100, 320, 500, 100))
        item.setSelected(True)
        self.changed.emit()

    def add_object(self, spec: dict) -> bool:
        if spec.get("kind") == "figure" and not self.can_add_sources([spec["figure"]]):
            return False
        if not self.deck or len(self.objects) >= 60:
            self.hint.setText("每頁最多 60 個物件，請先刪除部分物件。")
            return False
        self.finish_editing()
        self.scene.clearSelection()
        spec = deepcopy(spec)
        spec["x"] = max(0, min(WIDTH - spec["w"], spec["x"]))
        spec["y"] = max(0, min(HEIGHT - spec["h"], spec["y"]))
        self._insert(spec).setSelected(True)
        self.report_fit()
        self.changed.emit()
        return True

    def edit_table(self, item):
        text = "\n".join("\t".join(row) for row in item.spec["rows"])
        edited, ok = QInputDialog.getMultiLineText(
            self, "編輯表格", "每行一列，欄位以 Tab 分隔；第一列是表頭。", text
        )
        if not ok:
            return
        rows = [line.split("\t") for line in edited.splitlines() if line.strip()]
        width = max((len(r) for r in rows), default=0)
        try:
            rows = validate_rows([(r + [""] * width)[:width] for r in rows])
        except ValueError as exc:
            self.hint.setText(f"表格未更新：{exc}")
            return
        item.spec["rows"] = rows
        item.update()
        self.changed.emit()

    def remove_selected(self):
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CanvasObject)]
        for item in selected:
            self.objects.remove(item)
            self.scene.removeItem(item)
        if selected:
            self.report_fit()
            self.changed.emit()

    def format_selected(self, **changes):
        if self._loading:
            return
        selected = [
            i
            for i in self.scene.selectedItems()
            if isinstance(i, CanvasObject) and "size" in i.spec
        ]
        for item in selected:
            # A table has a size but no colour or weight of its own.
            item.spec.update(
                changes if item.text else {k: v for k, v in changes.items() if k == "size"}
            )
            item.style_text()
            item.update()
        if selected:
            self._selection()
            self.changed.emit()

    def toggle_bold(self):
        selected = [i for i in self.scene.selectedItems() if isinstance(i, CanvasObject) and i.text]
        if selected:
            value = not all(i.spec.get("bold") for i in selected)
            self.format_selected(bold=value)

    def choose_color(self):
        color = QColorDialog.getColor(QColor("#172238"), self, "文字顏色")
        if color.isValid():
            self.format_selected(color=color.name())

    def select_all(self):
        self.finish_editing()
        for obj in self.objects:
            obj.setSelected(True)

    def _selection_data(self):
        return [obj.snapshot() for obj in self.objects if obj.isSelected()]

    def copy_selected(self):
        objects = self._selection_data()
        if not objects or not self.deck:
            return False
        mime = QMimeData()
        mime.setData(
            "application/x-paperfact-slide-objects",
            json.dumps(
                {"paper_id": self.deck.paper_id, "objects": objects}, ensure_ascii=False
            ).encode(),
        )
        mime.setText("\n".join(o["text"] for o in objects if o["kind"] == "text"))
        QApplication.clipboard().setMimeData(mime)
        return True

    def cut_selected(self):
        if self.copy_selected():
            self.remove_selected()

    def duplicate_selected(self):
        self._paste_objects(self._selection_data())

    def paste(self):
        if not self.deck:
            return
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        if mime.hasFormat("application/x-paperfact-slide-objects"):
            try:
                raw = bytes(mime.data("application/x-paperfact-slide-objects"))
                if len(raw) > 2_000_000:
                    raise ValueError("Clipboard objects are too large")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("Invalid clipboard data")
                objects = (
                    validate_elements(payload.get("objects"), {f["id"] for f in self.deck.figures})
                    or []
                )
                if payload.get("paper_id") != self.deck.paper_id and any(
                    o["kind"] == "figure" for o in objects
                ):
                    raise ValueError("請在同一篇論文中貼上原圖，避免引用到另一篇的圖片。")
            except (ValueError, TypeError, UnicodeError) as exc:
                self.hint.setText(f"無法貼上：{exc}")
                return
        elif mime.hasText():
            if len(mime.text()) > 12000:
                self.hint.setText("文字框最多 12000 字，請分段貼上。")
                return
            objects = [text_box(mime.text(), 80, 290, 700, 180)]
        else:
            return
        self._paste_objects(objects)

    def _paste_objects(self, objects):
        if not objects or not self.deck:
            return
        if len(self.objects) + len(objects) > 60:
            self.hint.setText("每頁最多 60 個物件，請先刪除部分物件。")
            return
        if not self.can_add_sources([o["figure"] for o in objects if o["kind"] == "figure"]):
            return
        self.finish_editing()
        self.scene.clearSelection()
        for spec in deepcopy(objects):
            spec["x"] = min(WIDTH - spec["w"], spec["x"] + 20)
            spec["y"] = min(HEIGHT - spec["h"], spec["y"] + 20)
            spec.pop("role", None)
            self._insert(spec).setSelected(True)
        self.report_fit()
        self.changed.emit()
