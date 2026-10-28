"""Presentation tab: existing research to editable notes or a teaching deck."""

from __future__ import annotations

import hashlib
import html
import json
import time
from collections import OrderedDict
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSignalBlocker, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsTextItem,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paper_daily import (
    google_slides,
    llm,
    materials,
    paper_highlights,
    presentation_export,
    presentation_odp,
    presentations,
    slide_revise,
)
from paper_daily.desktop import ai_style, fonts, script_editor, window_events
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.focus_scope import scopes
from paper_daily.desktop.key_hints import KeyHints, keycap
from paper_daily.desktop.materials_panel import MaterialsPanel
from paper_daily.desktop.script_editor import ScriptPage
from paper_daily.desktop.slide_canvas import MATERIAL_MIME, SlideCanvas
from paper_daily.slide_layout import elements_for, table_box, text_box, validate_elements

# A thumbnail takes 20-30 ms to draw, so a deck drawn in one go held the window for
# half a second on every switch to the tab. They are drawn a few per event-loop
# turn, and remembered by what they show, so a deck seen before costs nothing.
THUMBNAIL_BUDGET = 0.012
THUMBNAIL_CACHE_SIZE = 240
_thumbnails: OrderedDict[str, QPixmap] = OrderedDict()


def _thumbnail_key(deck: presentations.Deck, index: int) -> str:
    slide = deck.slides[index]
    # The footer shows the page number, the page count and the sources' labels.
    shown = {
        "paper": deck.paper_id,
        "slide": asdict(slide),
        "page": index,
        "pages": len(deck.slides),
        "sources": [s for s in deck.sources if s["id"] in slide.sources],
        "figures": deck.figures,
    }
    return hashlib.sha1(
        json.dumps(shown, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


class _StatusLabel(QLabel):
    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


class PresentationPane(QWidget):
    source_requested = Signal(dict)
    highlights_ready = Signal(str)
    highlights_status = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.paper_id: str | None = None
        self.deck: presentations.Deck | None = None
        self._mode = "guide"
        self._index = -1
        self._loading = False
        self._dirty = False
        self._canvas_dirty = False
        self._layout_reset = False
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(1000)
        self._autosave.timeout.connect(self._save_canvas)
        self._generating = False
        self._revising = False
        self._pdf_job = None
        self._highlights_busy = False
        self._cloud_busy = False
        self._google_session = None
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self.runner = AskRunner(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.paper_label = QLabel("選擇論文後，可將閱讀成果整理成簡報。")
        self.paper_label.setWordWrap(True)
        layout.addWidget(self.paper_label)
        self._last_settings_height = 150
        self._last_outline_width = 190
        self._last_materials_width = 280
        self._first_paper = True
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self.mode = QComboBox()
        for key, label in presentations.MODES.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(self.mode.findData(self._mode))
        self.mode.setToolTip("研究筆記：自己複習；論文導讀：向別人講解。兩種簡報分開保存。")
        self.toolbar.addWidget(self.mode)
        self.settings_button = QPushButton("製作設定")
        self.settings_button.setToolTip(
            "設定 AI 下一次產生簡報的頁數、時間、對象與素材；不會立即改動現有投影片。"
        )
        self.settings_button.setCheckable(True)
        self.settings_button.toggled.connect(self._toggle_settings)
        self.toolbar.addWidget(self.settings_button)
        self.generate_button = QPushButton("產生此版本")
        self.generate_button.setToolTip(
            "依製作設定呼叫 AI 產生整份簡報；成功後舊稿保留在歷史版本，會使用 AI 額度。"
        )
        self.generate_button.clicked.connect(self._generate)
        ai_style.mark(self.generate_button)
        self.toolbar.addWidget(self.generate_button)
        self.toolbar.addSeparator()
        self.save_button = QPushButton("儲存修改")
        self.save_button.setToolTip(
            "保存目前手動編輯，不呼叫 AI。畫布與文字欄位會同步、自動儲存，"
            f"也可按 {fonts.key(QKeySequence.StandardKey.Save)}。"
        )
        self.save_button.clicked.connect(self.save_changes)
        self.toolbar.addWidget(self.save_button)
        self.history_button = QPushButton("歷史版本")
        self.history_button.setToolTip("還原重新產生前的整份簡報；逐次手動修改請用「復原」。")
        self.history_button.clicked.connect(self._restore_history)
        self.toolbar.addWidget(self.history_button)
        self.export_button = QPushButton("匯出簡報…")
        self.export_button.setToolTip(
            "匯出目前這份簡報，預設為 PDF；可選 HTML、講稿或可編輯格式。"
            "分享整份研究清單請用上方「研究資料」。")
        self.export_button.clicked.connect(self._export)
        self.toolbar.addWidget(self.export_button)
        self.google_button = QToolButton()
        self.google_button.setText("建立 Google Slides")
        self.google_button.setToolTip(
            "在瀏覽器登入 Google，建立可編輯副本並開啟；每頁講稿與引用會一併帶入。"
        )
        self.google_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.google_button.clicked.connect(self._google_export)
        google_menu = QMenu(self.google_button)
        google_menu.addAction("開啟上次建立的簡報", self._google_open)
        google_menu.addAction("切換 Google 帳號並建立", self._google_switch_account)
        advanced = google_menu.addMenu("開發者設定")
        advanced.addAction("設定應用程式 OAuth…", self._google_configure)
        advanced.addAction("清除本次登入", self._google_disconnect)
        self.google_button.setMenu(google_menu)
        self.toolbar.addWidget(self.google_button)
        self.include_notes = QCheckBox("其他格式含講者備註", self)
        self.include_notes.setChecked(True)
        self.include_notes.hide()
        export_options = self.toolbar.addAction("簡報匯出選項")
        export_menu = QMenu(self)
        notes_action = export_menu.addAction("HTML／ODP 含講者備註")
        notes_action.setCheckable(True)
        notes_action.setChecked(True)
        notes_action.toggled.connect(self.include_notes.setChecked)
        self.include_notes.toggled.connect(notes_action.setChecked)
        export_options.setMenu(export_menu)
        layout.addWidget(self.toolbar)

        settings_content = QWidget()
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(8, 6, 8, 6)
        settings_layout.addWidget(QLabel("整份簡報的生成設定 · 修改後按「重新產生」套用"))
        row = QHBoxLayout()
        row.addWidget(QLabel("目標頁數"))
        self.count = QSpinBox()
        self.count.setRange(4, presentations.MAX_SLIDES)
        self.count.setValue(12)
        row.addWidget(self.count)
        row.addWidget(QLabel("講解分鐘"))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 120)
        self.minutes.setValue(15)
        row.addWidget(self.minutes)
        row.addStretch()
        settings_layout.addLayout(row)
        self.audience = QLineEdit()
        self.audience.setMaxLength(500)
        self.audience.setPlaceholderText("聽眾與需求，例如：有研究基礎，但沒讀過這篇論文")
        settings_layout.addWidget(self.audience)
        inputs_row = QHBoxLayout()
        inputs_row.addWidget(QLabel("參考資料"))
        self.inputs: dict[str, QCheckBox] = {}
        for key, label in presentations.INPUTS.items():
            box = QCheckBox(label)
            box.setChecked(True)
            inputs_row.addWidget(box)
            self.inputs[key] = box
        inputs_row.addStretch()
        settings_layout.addLayout(inputs_row)
        self.settings_panel = QScrollArea()
        self.settings_panel.setWidgetResizable(True)
        self.settings_panel.setWidget(settings_content)
        self.settings_panel.hide()

        workspace_bar = QHBoxLayout()
        self.outline_button = QPushButton("頁面目錄：開")
        self.outline_button.setToolTip(
            "左側：目前簡報的投影片縮圖，用來切頁與調整順序。藍底／開表示顯示。"
        )
        self.outline_button.setCheckable(True)
        self.outline_button.setChecked(True)
        self.outline_button.toggled.connect(self._toggle_outline)
        workspace_bar.addWidget(self.outline_button)
        self.materials_button = QPushButton("論文素材：關")
        self.materials_button.setCheckable(True)
        self.materials_button.setToolTip(
            "右側：論文原圖、表格與重點，可預覽後加入投影片。藍底／開表示顯示。"
        )
        self.materials_button.toggled.connect(self._toggle_materials)
        workspace_bar.addWidget(self.materials_button)
        reset = QPushButton("還原面板配置")
        reset.setToolTip("恢復面板大小、開關與適合視窗縮放；不改動投影片內容、物件位置或歷史版本。")
        reset.clicked.connect(self._reset_workspace)
        workspace_bar.addWidget(reset)
        # Single keys, as these are pressed often and in a row; a text field takes
        # its letters first, so typing an A never closes a panel.
        for letter, button in (
            ("A", self.outline_button),
            ("D", self.materials_button),
            ("R", reset),
        ):
            button.setIcon(keycap(letter))
            button.setToolTip(f"{button.toolTip()}（快捷鍵 {letter}）")
            shortcut = QShortcut(QKeySequence(letter), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda button=button: self._press_panel_key(button))
        self.status = _StatusLabel("")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setMinimumWidth(0)
        workspace_bar.addWidget(self.status, 1)
        layout.addLayout(workspace_bar)
        split = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.outline = QListWidget()
        self.outline.setViewMode(QListView.ViewMode.IconMode)
        self.outline.setFlow(QListView.Flow.TopToBottom)
        self.outline.setWrapping(False)
        self.outline.setMovement(QListView.Movement.Static)
        self.outline.setIconSize(QSize(144, 81))
        self.outline.setGridSize(QSize(166, 120))
        self.outline.setWordWrap(True)
        self._thumbnail_canvas = SlideCanvas(self)
        self._thumbnail_canvas.hide()
        blank = QPixmap(288, 162)
        blank.fill(Qt.GlobalColor.white)
        self._blank_thumbnail = QIcon(blank)
        self._thumbnail_queue: list[int] = []
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.setInterval(0)
        self._thumbnail_timer.timeout.connect(self._draw_queued_thumbnails)
        left_layout.addWidget(self.outline)
        order = QToolBar()
        order.setMovable(False)
        self.up = order.addAction("前移")
        self.down = order.addAction("後移")
        self.remove = QPushButton("刪除")
        self.add = QPushButton("＋ 新增")
        self.undo_button = order.addAction("復原")
        self.add.clicked.connect(self._add)
        self.undo_button.triggered.connect(self._undo_edit)
        self.up.setToolTip("投影片往前移")
        self.down.setToolTip("投影片往後移")
        self.up.triggered.connect(lambda: self._move(-1))
        self.down.triggered.connect(lambda: self._move(1))
        self.remove.clicked.connect(self._remove)
        left_layout.addWidget(order)
        editing = QHBoxLayout()
        editing.addWidget(self.add)
        editing.addWidget(self.remove)
        left_layout.addLayout(editing)
        left.setMinimumWidth(110)
        self._outline_panel = left
        self.outline.viewport().installEventFilter(self)
        split.addWidget(left)
        self.views = QTabWidget()
        self.views.setObjectName("views")
        self.canvas = SlideCanvas(self)
        self.canvas.revise_requested.connect(self._revise_current_slide)
        self.canvas.can_add_sources = self._can_add_sources
        self.canvas.changed.connect(self._canvas_changed)
        self.canvas.edit_boundary.connect(self.save_changes)
        self.canvas.undo_requested.connect(self._undo_edit)
        self.canvas.redo_requested.connect(self._redo_edit)
        self.views.addTab(self.canvas, "投影片畫布")
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self._open_source)
        self.views.addTab(self.preview, "核對來源")
        editor = QWidget()
        form = QFormLayout(editor)
        self.slide_title = QLineEdit()
        self.slide_title.setMaxLength(70)
        self.section = QLineEdit()
        self.section.setMaxLength(100)
        self.takeaway = QLineEdit()
        self.takeaway.setMaxLength(160)
        self.bullets = QPlainTextEdit()
        self.bullets.setPlaceholderText("每行一個重點；細節放入講稿")
        self.bullets.setMinimumHeight(80)
        self.figure = QComboBox()
        self.source_picker = QTreeWidget()
        self.source_picker.setHeaderHidden(True)
        self.source_picker.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._source_items = []
        self._source_groups = {}
        self.source_search = QLineEdit()
        self.source_search.setPlaceholderText("搜尋全部來源（含尚未引用）…")
        self.source_selected_only = QCheckBox("只看本頁已引用")
        self.source_selected_only.setChecked(True)
        self.source_selected_only.setToolTip("取消篩選可加入其他來源；不會更動引用勾選。")
        self.source_search.textChanged.connect(self._filter_sources)
        self.source_selected_only.toggled.connect(self._filter_sources)
        self.source_picker.setToolTip(
            "勾選方框才會變更本頁引用；點選文字只選取這一列。每頁保留 1–8 個來源。"
        )
        self.source_picker.setMinimumHeight(150)
        form.addRow("標題", self.slide_title)
        form.addRow("對應段落", self.section)
        form.addRow("核心理解", self.takeaway)
        form.addRow("投影片重點", self.bullets)
        form.addRow("論文原圖", self.figure)
        self.sources_label = QLabel("本頁引用 · 勾選 1–8 個來源")
        source_panel = QWidget()
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        explanation = QLabel("引用標記會同步到頁尾、核對來源與匯出講稿，不會增刪或改寫投影片文字。")
        explanation.setWordWrap(True)
        source_layout.addWidget(explanation)
        search_bar = QHBoxLayout()
        search_bar.addWidget(self.source_search, 1)
        search_bar.addWidget(self.source_selected_only)
        source_layout.addLayout(search_bar)
        source_layout.addWidget(self.source_picker)
        self.source_detail = QPlainTextEdit()
        self.source_detail.setReadOnly(True)
        self.source_detail.setPlaceholderText("點選來源可預覽內容；勾選方框才會更動引用。")
        self.source_detail.setMaximumHeight(85)
        source_layout.addWidget(self.source_detail)
        self.source_locate = QPushButton("定位左側原文")
        self.source_locate.setEnabled(False)
        self.source_locate.clicked.connect(self._locate_selected_source)
        source_layout.addWidget(self.source_locate)
        self.source_picker.currentItemChanged.connect(self._preview_source)
        form.addRow(self.sources_label, source_panel)
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setWidget(editor)
        self.views.addTab(editor_scroll, "內容與引用")
        self.script_page = ScriptPage()
        self.speaker_notes = self.script_page.editor
        self.speaker_notes.setPlaceholderText("講解脈絡、逐步推導、轉場與需核對的地方")
        self.speaker_notes.textChanged.connect(self._script_length)
        self.views.addTab(self.script_page, "講稿")
        self.views.setAcceptDrops(True)
        self.views.tabBar().setToolTip(f"左右鍵切換視角；編輯文字或物件時用 {fonts.ALT}左右鍵。")
        self._view_hints = KeyHints(
            self.views.tabBar(),
            Qt.KeyboardModifier.AltModifier,
            self._view_hint_labels,
            lambda: scopes().within(self.views),
        )
        for target in (
            self.views.tabBar(),
            self.preview,
            self.canvas.view,
            editor,
            editor_scroll.viewport(),
        ):
            target.installEventFilter(self)
        self._view_navigation_targets = (
            self.views.tabBar(),
            self.views,
            self.preview,
            self.canvas.view,
            editor,
            editor_scroll.viewport(),
        )
        # Reserve Alt+arrows before the window's history shortcuts see them: the
        # shortcut check goes to the focused widget, which window_events covers.
        window_events.watch(self)
        # Material drops land on whichever surface of the views is under the pointer.
        for surface in self.views.findChildren(QWidget):
            surface.installEventFilter(self)
        split.addWidget(self.views)
        self.materials_panel = MaterialsPanel()
        self.materials_panel.hide()
        self.materials_panel.chosen.connect(self._insert_material)
        self.materials_panel.analyze_requested.connect(self._analyze_highlights)
        self._materials_for: str | None = None
        split.addWidget(self.materials_panel)
        scopes().add(
            self, "簡報", "A 目錄 · D 素材 · R 還原面板", lambda: self._views_focus_target()
        )
        scopes().add(self._outline_panel, "頁面目錄", "↑↓ 換頁", lambda: self.outline)
        scopes().add(
            self.views,
            "投影片視角",
            f"←/→ 換視角，打字時 {fonts.ALT}←/→",
            lambda: self._views_focus_target(),
        )
        scopes().add(
            self.materials_panel,
            "素材",
            "雙擊加入投影片",
            lambda: self.materials_panel.tree,
        )
        split.setHandleWidth(8)
        split.setCollapsible(1, False)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([190, 640, 280])
        self._split = split
        self._workspace_split = QSplitter(Qt.Orientation.Vertical)
        self._workspace_split.setHandleWidth(8)
        self._workspace_split.addWidget(self.settings_panel)
        self._workspace_split.addWidget(split)
        self._workspace_split.setCollapsible(1, False)
        self._workspace_split.setStretchFactor(0, 0)
        self._workspace_split.setStretchFactor(1, 1)
        self._workspace_split.setSizes([150, 600])
        layout.addWidget(self._workspace_split, 1)
        self.setStyleSheet(
            "QSplitter::handle { background: #dce3ed; } "
            "QSplitter::handle:hover { background: #8ca9d1; }"
            "QPushButton[compact=true] { padding: 2px 4px; }"
            "QPushButton:pressed { background: #e4ebff; border-color: #3158d7; }"
            "QPushButton:checked { background: #3158d7; color: white; border: 1px solid #3158d7; }"
            "QPushButton:checked:hover { background: #2447b8; color: white; }"
            "QPushButton:checked:disabled { background: #dce3ed; color: #52657d; "
            "border-color: #a7b4c8; }"
        )
        self._split.splitterMoved.connect(self._sync_panels)
        self._workspace_split.splitterMoved.connect(self._sync_panels)
        self.canvas.material_dropped.connect(self._material_dropped)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.outline.currentRowChanged.connect(self._selected)
        for field in (
            self.slide_title,
            self.section,
            self.takeaway,
            self.bullets,
            self.speaker_notes,
        ):
            field.textChanged.connect(self._changed)
        self.figure.currentIndexChanged.connect(self._figure_changed)
        self.source_picker.itemChanged.connect(lambda item, _column: self._sources_changed(item))
        for field in (self.count, self.minutes):
            field.valueChanged.connect(self._options_changed)
        self.minutes.valueChanged.connect(self._script_length)
        self.audience.textEdited.connect(self._options_changed)
        for box in self.inputs.values():
            box.toggled.connect(self._options_changed)
        self._save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.save_changes)
        self._show_deck(None)

    def _views_focus_target(self):
        return self.canvas.view if self.views.currentIndex() == 0 else self.views.currentWidget()

    def _press_panel_key(self, button):
        if not button.isEnabled():
            return
        if button.isCheckable():
            button.toggle()
        else:
            button.click()
        # Closing the panel that held the keys would send focus out of the pane,
        # and the next A or D would then do nothing.
        focus = QApplication.focusWidget()
        if focus is None or not focus.isVisible() or not self.isAncestorOf(focus):
            self._views_focus_target().setFocus()

    def _script_length(self):
        budget = None
        if self.deck and self.deck.slides:
            budget = round(self.minutes.value() * 60 / len(self.deck.slides))
        self.script_page.meta.setText(
            script_editor.length_label(self.speaker_notes.toPlainText(), budget)
        )

    def _switch_view(self, step):
        self.views.setCurrentIndex((self.views.currentIndex() + step) % self.views.count())
        (self.canvas.view if self.views.currentIndex() == 0 else self.views.tabBar()).setFocus()

    def _switch_slide(self, step):
        if not self.deck or self._index < 0 or self.busy:
            return
        index = max(0, min(len(self.deck.slides) - 1, self._index + step))
        if index != self._index:
            self.outline.setCurrentRow(index)
        self.canvas.view.setFocus()

    def eventFilter(self, watched, event):
        if (
            event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
            and isinstance(watched, QWidget)
            and (watched is self.views or self.views.isAncestorOf(watched))
            and watched not in (self.canvas.view, self.canvas.view.viewport())
            and event.mimeData().hasFormat(MATERIAL_MIME)
        ):
            if event.type() == QEvent.Type.Drop:
                try:
                    payload = json.loads(bytes(event.mimeData().data(MATERIAL_MIME)))
                except (ValueError, UnicodeError):
                    self._material_feedback("素材格式無法讀取，請從論文素材面板重新拖入。")
                else:
                    if isinstance(payload, dict):
                        self._insert_material(payload)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return True
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            focus = QApplication.focusWidget()
            if (
                self.isVisible()
                and focus is not None
                and scopes().within(self.views)
                and event.modifiers() == Qt.KeyboardModifier.AltModifier
                and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            ):
                if event.type() == QEvent.Type.ShortcutOverride:
                    event.accept()
                else:
                    self._switch_view(-1 if event.key() == Qt.Key.Key_Left else 1)
                return True
        if (
            event.type() == QEvent.Type.KeyPress
            and watched is self.canvas.view
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and event.key()
            in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
        ):
            focus = self.canvas.scene.focusItem()
            editing_text = isinstance(focus, QGraphicsTextItem) and bool(
                focus.textInteractionFlags()
            )
            page_key = event.key() in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
            if not editing_text and (page_key or not self.canvas.scene.selectedItems()):
                self._switch_slide(-1 if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else 1)
                return True
        if (
            event.type() == QEvent.Type.KeyPress
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            and watched in getattr(self, "_view_navigation_targets", ())
        ):
            editing = False
            if watched is self.canvas.view:
                focus = self.canvas.scene.focusItem()
                editing = bool(self.canvas.scene.selectedItems()) or (
                    isinstance(focus, QGraphicsTextItem) and bool(focus.textInteractionFlags())
                )
            if not editing:
                self._switch_view(-1 if event.key() == Qt.Key.Key_Left else 1)
                return True
        if watched is self.outline.viewport() and event.type() == QEvent.Type.Resize:
            width = max(80, min(240, self.outline.viewport().width() - 20))
            height = round(width * 9 / 16)
            self.outline.setIconSize(QSize(width, height))
            self.outline.setGridSize(QSize(width + 12, height + 42))
        return super().eventFilter(watched, event)

    def _toggle_settings(self, checked):
        if not checked and self._workspace_split.sizes()[0] > 0:
            self._last_settings_height = self._workspace_split.sizes()[0]
        self.settings_panel.setVisible(checked)
        if checked and self._workspace_split.sizes()[0] < 60:
            self._workspace_split.setSizes(
                [self._last_settings_height, max(180, self.height() - 240)]
            )

    def _toggle_outline(self, checked):
        self.outline_button.setText("頁面目錄：開" if checked else "頁面目錄：關")
        sizes = self._split.sizes()
        if not checked and sizes[0] > 0:
            self._last_outline_width = sizes[0]
        self._outline_panel.setVisible(checked)
        if checked:
            self._split.setSizes(
                [
                    self._last_outline_width,
                    max(250, sum(sizes) - self._last_outline_width - sizes[2]),
                    sizes[2],
                ]
            )

    def _reset_workspace(self):
        self._last_outline_width, self._last_materials_width = 190, 280
        self.settings_button.setChecked(not bool(self.deck))
        self.outline_button.setChecked(True)
        self.materials_button.setChecked(False)
        self.materials_panel.detail_toggle.setChecked(True)
        self.materials_panel.details_split.setSizes([300, 220])
        self._split.setSizes([190, max(300, self.width() - 220), 280])
        self._workspace_split.setSizes([150, max(180, self.height() - 240)])
        self.canvas.view.fit_slide()

    def _sync_panels(self, *_args):
        for index, button in ((0, self.outline_button), (2, self.materials_button)):
            button.blockSignals(True)
            button.setChecked(self._split.sizes()[index] > 0)
            button.blockSignals(False)
        self.outline_button.setText(
            "頁面目錄：開" if self.outline_button.isChecked() else "頁面目錄：關"
        )
        self.materials_button.setText(
            "論文素材：開" if self.materials_button.isChecked() else "論文素材：關"
        )
        self.settings_button.blockSignals(True)
        self.settings_button.setChecked(self._workspace_split.sizes()[0] > 0)
        self.settings_button.blockSignals(False)

    def workspace_state(self):
        panels = dict(
            settings=self.settings_button.isChecked(),
            outline=self.outline_button.isChecked(),
            materials=self.materials_button.isChecked(),
        )
        return dict(
            panels=panels,
            sizes=self._split.sizes(),
            heights=self._workspace_split.sizes(),
            details=self.materials_panel.details_split.sizes(),
            detail_visible=self.materials_panel.detail_toggle.isChecked(),
            outline_width=self._last_outline_width,
            materials_width=self._last_materials_width,
            zoom="fit" if self.canvas.view.fit_mode else self.canvas.zoom.value(),
        )

    def restore_workspace(self, state):
        if not isinstance(state, dict):
            return
        self._first_paper = False
        panels = state.get("panels", {})
        if isinstance(panels, dict):
            for key, button in (
                ("settings", self.settings_button),
                ("outline", self.outline_button),
                ("materials", self.materials_button),
            ):
                if type(panels.get(key)) is bool:
                    button.setChecked(panels[key])
        for key, split, count in (
            ("sizes", self._split, 3),
            ("heights", self._workspace_split, 2),
            ("details", self.materials_panel.details_split, 2),
        ):
            sizes = state.get(key)
            if (
                isinstance(sizes, list)
                and len(sizes) == count
                and any(sizes)
                and all(type(v) is int and 0 <= v <= 20000 for v in sizes)
            ):
                split.setSizes(sizes)
        if type(state.get("detail_visible")) is bool:
            self.materials_panel.detail_toggle.setChecked(state["detail_visible"])
        for key in ("outline_width", "materials_width"):
            value = state.get(key)
            if type(value) is int and 100 <= value <= 2000:
                setattr(self, "_last_" + key, value)
        zoom = state.get("zoom")
        if type(zoom) is int:
            self.canvas.view.set_zoom(zoom)
        else:
            self.canvas.view.fit_slide()

    def _options_changed(self, *_args) -> None:
        if not self._loading and self.deck and not self.busy:
            self.status.setText("製作選項已修改。按「重新產生」套用；目前草稿會保留在歷史版本。")

    @property
    def busy(self) -> bool:
        return (
            self._generating
            or self._revising
            or self.runner.busy
            or self._pdf_job is not None
            or self._cloud_busy
            or self._highlights_busy
        )

    def load(self, paper_id: str, title: str, *, defer=False) -> None:
        self._pending_load = None
        self.paper_id = paper_id
        self._undo.clear()
        self._redo.clear()
        self.paper_label.setText(title)
        if defer:
            self._show_deck(None)
            self._materials_for = None
            self.materials_panel.clear()
            self._pending_load = (paper_id, title)
            return
        if self.materials_button.isChecked():
            self._load_materials()
        else:
            self._materials_for = None
            self.materials_panel.clear()
        try:
            deck = presentations.load_deck(paper_id, self._mode)
        except (ValueError, OSError) as exc:
            self._show_deck(None)
            self.status.setText(f"簡報讀取失敗，已保存的檔案未變動：{exc}")
            return
        self._show_deck(deck)
        self._restore_recovery()
        if self._first_paper:
            self.settings_button.setChecked(deck is None)
            self._first_paper = False

    def showEvent(self, event):
        super().showEvent(event)
        pending = getattr(self, "_pending_load", None)
        if pending:
            self.load(*pending)

    def _recovery_path(self):
        return presentations._folder(self.paper_id) / f"{self._mode}-recovery.json"

    def save_recovery(self):
        if self.deck and self._dirty:
            presentations._atomic_json(
                self._recovery_path(),
                {
                    "deck_id": self.deck.deck_id,
                    "deck": self.deck.to_dict(),
                    "index": self._index,
                    "slide": self._raw_slide(),
                    "canvas_dirty": self._canvas_dirty,
                    "layout_reset": self._layout_reset,
                },
            )

    def _restore_recovery(self):
        if not self.deck or not self._recovery_path().exists():
            return
        try:
            pending = json.loads(self._recovery_path().read_text(encoding="utf-8"))
            if pending["deck_id"] != self.deck.deck_id:
                self.status.setText("有另一版本的未完成草稿保存在本機，未套用到目前簡報。")
                return
            index, raw = pending["index"], pending["slide"]
            if type(index) is not int or not 0 <= index < len(self.deck.slides):
                raise ValueError("草稿頁碼無效")
            base = presentations.deck_from_dict(pending.get("deck", self.deck.to_dict()))
            temp = presentations.deck_from_dict(base.to_dict())
            restored = presentations.Slide(**raw)
            restored.elements = validate_elements(
                raw.get("elements"), {f["id"] for f in temp.figures}
            )
            temp.slides[index] = restored
            self._show_deck(base, reset_options=False)
            self.outline.setCurrentRow(index)
            self._loading = True
            self.slide_title.setText(restored.title)
            self.section.setText(restored.section)
            self.takeaway.setText(restored.takeaway)
            self.bullets.setPlainText("\n".join(restored.bullets))
            self.speaker_notes.setPlainText(restored.speaker_notes)
            self.figure.setCurrentIndex(max(0, self.figure.findData(restored.figure)))
            self._last_figure = self.figure.currentIndex()
            for item in self._source_items:
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if item.data(0, Qt.ItemDataRole.UserRole) in restored.sources
                    else Qt.CheckState.Unchecked,
                )
            self.canvas.load(temp, index)
            self.canvas.deck = self.deck
            self._dirty = True
            self._canvas_dirty = bool(pending.get("canvas_dirty"))
            self._layout_reset = bool(pending.get("layout_reset"))
            self._source_count()
            self.views.setCurrentIndex(2)
            self.status.setText("已恢復上次未完成的修改；請修正內容後儲存。正式簡報仍保留原稿。")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.status.setText(f"未完成草稿仍保留在本機，無法自動恢復：{exc}")
        finally:
            self._loading = False

    def _show_deck(self, deck: presentations.Deck | None, *, reset_options: bool = True) -> None:
        self._loading = True
        self._autosave.stop()
        self._canvas_dirty = self._layout_reset = False
        self.canvas.load(None, 0)
        self.deck, self._index, self._dirty = deck, -1, False
        self._thumbnail_queue = []
        self._thumbnail_timer.stop()
        self.outline.clear()
        for field in (
            self.slide_title,
            self.section,
            self.takeaway,
            self.bullets,
            self.speaker_notes,
        ):
            field.clear()
        self._source_items.clear()
        self._source_groups.clear()
        self.source_picker.clear()
        self.source_detail.clear()
        self.source_locate.setEnabled(False)
        self.figure.clear()
        self.figure.addItem("不使用圖表", None)
        if deck:
            for item in deck.figures:
                self.figure.addItem(item.get("label", item["id"]), item["id"])
            # One repaint for the whole tree rather than one per source (often 100+).
            self.source_picker.setUpdatesEnabled(False)
            for source in deck.sources:
                self._add_source_item(source["id"], source.get("label", source["id"]), source)
            self.source_picker.setUpdatesEnabled(True)
            for i, slide in enumerate(deck.slides):
                self.outline.addItem(f"{i + 1}. {slide.title}")
                cached = _thumbnails.get(_thumbnail_key(deck, i))
                # A white page of the same size until it is drawn: the list keeps
                # its layout and nothing moves when the picture arrives.
                self.outline.item(i).setIcon(
                    QIcon(cached) if cached is not None else self._blank_thumbnail
                )
                if cached is None:
                    self._thumbnail_queue.append(i)
            if self._thumbnail_queue:
                self._thumbnail_timer.start()
            if reset_options:
                self.count.setValue(len(deck.slides))
                self.minutes.setValue(deck.minutes)
                self.audience.setText(deck.audience)
                selected_inputs = deck.generation.get("inputs")
                if isinstance(selected_inputs, list):
                    for key, box in self.inputs.items():
                        box.setChecked(key in selected_inputs)
            self.status.setText(
                f"{len(deck.slides)} 頁 · 草稿已保存，分享前請核對原文與引用。"
                + (" 來源有截取或缺漏，匯出時會保留覆蓋說明。" if deck.coverage else "")
            )
        else:
            self.preview.setHtml(
                "<h2>將理解整理成可講解的投影片</h2>"
                "<p>研究筆記依論文章節整理重點與疑問。論文導讀補齊背景，"
                "沿研究問題、方法與實驗證據帶別人進入狀況。</p>"
                "<p>勾選要納入的資料，設定聽眾、頁數和時間，再按「產生此版本」。"
                "只有按下產生才會使用 AI。</p>"
            )
            self.status.setText(
                "尚未生成投影片。按「生成投影片」開始分析，完成後可直接雙擊畫布改字。"
            )
        self._loading = False
        self._update_controls()
        if deck:
            self.outline.setCurrentRow(0)

    def _update_controls(self) -> None:
        blocked = (
            self._generating
            or self._revising
            or self._pdf_job is not None
            or self._cloud_busy
            or self._highlights_busy
        )
        self.canvas.revise_button.setEnabled(bool(self.deck) and not blocked)
        self.canvas.revise_button.setText("改寫中…" if self._revising else "AI 改寫這頁")
        self.generate_button.setEnabled(bool(self.paper_id) and not blocked)
        self.generate_button.setText("重新產生（保留舊稿）" if self.deck else "生成投影片")
        for widget in (self.save_button, self.up, self.down, self.remove, self.add, self.views):
            widget.setEnabled(bool(self.deck) and not blocked)
        self.export_button.setEnabled(bool(self.deck) and not blocked)
        self.google_button.setEnabled(bool(self.deck) and not blocked)
        self.outline.setEnabled(not blocked)
        self.undo_button.setEnabled(bool(self._undo or self._dirty) and not blocked)
        self.history_button.setEnabled(bool(self.paper_id) and not blocked)
        self.materials_button.setEnabled(bool(self.paper_id))
        self.materials_panel.analyze.setEnabled(bool(self.paper_id) and not blocked)

    def _view_hint_labels(self) -> list[str | None]:
        count, current = self.views.count(), self.views.currentIndex()
        labels: list[str | None] = [None] * count
        labels[(current - 1) % count] = fonts.ALT + "←"
        labels[(current + 1) % count] = fonts.ALT + "→"
        return labels

    def _toggle_materials(self, checked: bool) -> None:
        self.materials_button.setText("論文素材：開" if checked else "論文素材：關")
        sizes = self._split.sizes()
        if not checked and sizes[2] > 0:
            self._last_materials_width = sizes[2]
        self.materials_panel.setVisible(checked)
        if checked:
            self._split.setSizes(
                [
                    sizes[0],
                    max(250, sum(sizes) - sizes[0] - self._last_materials_width),
                    self._last_materials_width,
                ]
            )
        if checked and self.paper_id and self._materials_for != self.paper_id:
            self._load_materials()

    def _browse_figures(self):
        self.materials_button.setChecked(True)
        self.materials_panel.detail_toggle.setChecked(True)
        group = self.materials_panel.tree.topLevelItem(0)
        if group and group.childCount():
            group.setExpanded(True)
            current = self.materials_panel.tree.currentItem()
            if current is None or current.parent() is not group:
                current = group.child(0)
            self.materials_panel.tree.setCurrentItem(current)
            self.materials_panel.tree.scrollToItem(current)
            self.materials_panel.tree.setFocus()
            self.status.setText("先預覽右側圖表，再雙擊或拖到畫布加入；這裡不會立即插入。")
        else:
            self.status.setText("這篇尚無可用原圖，請先加入原文 PDF 並抽取圖表。")

    def _load_materials(self) -> None:
        if not self.paper_id:
            return
        try:
            found = materials.collect(self.paper_id)
        except (ValueError, OSError) as exc:
            self.materials_panel.load(None)
            self.status.setText(f"素材讀取失敗：{exc}")
            return
        self._materials_for = self.paper_id
        self.materials_panel.load(found)

    def _highlight_status(self, text):
        self.materials_panel.analysis_status.setText(text)
        self.highlights_status.emit(self.paper_id, text)

    def _analyze_highlights(self, *, force=True) -> None:
        if not self.paper_id or self.busy:
            return
        cached = paper_highlights.cached(self.paper_id) if not force else None
        try:
            cfg = llm.settings(task="paper_highlights") if cached is None else None
        except (ValueError, OSError) as exc:
            self._highlight_status(str(exc))
            return
        if cached is None and not llm.available(task="paper_highlights"):
            from paper_daily.desktop.ai_access import login

            reason = "請先在 AI 設定登入帳號，再按分析／補上標註。"
            self._highlight_status(reason)
            login(self, "paper_highlights", reason)
            return
        paper_id = self.paper_id
        self._highlights_busy = True
        self._update_controls()
        self._highlight_status("AI 正在讀取原文、比較研究重要性並核對引句；舊結果暫時保留。")

        def analyze(_prompt):
            try:
                result, reason = paper_highlights.prepare_reading(paper_id, force=force, cfg=cfg)
                return (
                    json.dumps(result, ensure_ascii=False) if result is not None else None
                ), reason
            except Exception as exc:  # noqa: BLE001 - always finish the worker lifecycle
                return None, f"研究重點分析失敗：{type(exc).__name__}"

        def done(_result):
            self._highlights_busy = False
            self._update_controls()
            if self.paper_id == paper_id:
                self._load_materials()
                self.highlights_ready.emit(paper_id)
                prepared = json.loads(_result)
                marks = prepared.get("marks")
                if marks and marks.get("unmatched"):
                    self._highlight_status(
                        f"已定位 {marks['mapped']}/{marks['total']} 段；"
                        "其餘無法精確定位，仍保留在素材中供核對。"
                    )
                elif prepared.get("explanation_reason") and not prepared.get("explanation"):
                    self._highlight_status(
                        "原文標註與素材已同步；" + prepared["explanation_reason"]
                    )

        def failed(reason):
            self._highlights_busy = False
            self._update_controls()
            if self.paper_id == paper_id:
                self._highlight_status(f"分析未完成，舊結果保留：{reason}")

        self.runner.start("", done, failed, call=analyze, task="paper_highlights")

    def _material_dropped(self, text: str, x: float, y: float) -> None:
        try:
            payload = json.loads(text)
        except ValueError:
            return
        if isinstance(payload, dict):
            self._insert_material(payload, x, y)

    def _ensure_evidence(self, payload: dict) -> None:
        """A figure or table from the paper is evidence the slide must be able to cite,
        even when the deck was generated without the original."""
        sid, label = payload["id"], payload.get("label") or payload["id"]
        page = payload.get("page") if type(payload.get("page")) is int else None
        if payload.get("file") and not any(f["id"] == sid for f in self.deck.figures):
            self.deck.figures.append(
                {
                    "id": sid,
                    "file": payload["file"],
                    "label": label,
                    "caption": payload.get("caption") or "",
                    "page": page,
                }
            )
            self.figure.addItem(label, sid)
        if not any(s["id"] == sid for s in self.deck.sources):
            self.deck.sources.append(
                {"id": sid, "label": label, "kind": "figure", "page": page, "url": None}
            )
            self._add_source_item(sid, label)

    def _add_source_item(self, sid, label, source=None):
        if source is None:
            source = next((s for s in self.deck.sources if s["id"] == sid), {}) if self.deck else {}
        group = {
            "abstract": "原文與摘要",
            "original": "原文與摘要",
            "figure": "論文圖表",
            "dive": "AI 講解",
            "close_reading": "AI 講解",
            "citations": "研究脈絡與文獻",
            "notes": "我的筆記",
            "chat": "問答紀錄",
        }.get(source.get("kind"), "其他來源")
        with QSignalBlocker(self.source_picker):
            parent = self._source_groups.get(group)
            if parent is None:
                parent = QTreeWidgetItem([group])
                self.source_picker.addTopLevelItem(parent)
                self._source_groups[group] = parent
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, sid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setToolTip(0, "勾選只會加入引用標記，不會自動改寫投影片。")
            parent.addChild(item)
            self._source_items.append(item)

    def _filter_sources(self, *_args):
        query = self.source_search.text().strip().casefold()
        by_id = {s["id"]: s for s in self.deck.sources} if self.deck else {}
        with QSignalBlocker(self.source_picker):
            for item in self._source_items:
                source = by_id.get(item.data(0, Qt.ItemDataRole.UserRole), {})
                match = query in (item.text(0) + " " + str(source.get("text") or "")).casefold()
                selected = item.checkState(0) == Qt.CheckState.Checked
                item.setHidden(
                    not match
                    or (self.source_selected_only.isChecked() and not query and not selected)
                )
            for label, parent in self._source_groups.items():
                children = [parent.child(i) for i in range(parent.childCount())]
                selected = sum(item.checkState(0) == Qt.CheckState.Checked for item in children)
                parent.setText(0, f"{label} · 已引用 {selected}/{len(children)}")
                parent.setHidden(all(item.isHidden() for item in children))
                if query or self.source_selected_only.isChecked():
                    parent.setExpanded(True)
                elif self.sender() is self.source_selected_only:
                    parent.setExpanded(False)

    def _preview_source(self, item, _previous=None):
        sid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        source = next((s for s in self.deck.sources if s["id"] == sid), None) if self.deck else None
        self.source_locate.setEnabled(bool(source))
        self.source_detail.setPlainText(
            str(source.get("text") or "這個來源只保存了標籤與位置，可定位原文核對。")
            if source
            else ""
        )

    def _locate_selected_source(self):
        item = self.source_picker.currentItem()
        if item:
            sid = item.data(0, Qt.ItemDataRole.UserRole)
            if sid:
                self._open_source(QUrl("paperfact-source:" + sid))

    def _checked_sources(self):
        return [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self._source_items
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def _can_add_sources(self, sources):
        if not self.deck or self._index < 0:
            return False
        refs = set(self._raw_slide()["sources"]) | set(sources)
        if len(refs) > 8:
            self.status.setText(
                "本頁已有 8 個引用來源。請在「內容與引用」取消一個不需要的來源，再加入素材。"
            )
            return False
        return True

    def _sources_changed(self, item):
        if (
            self._loading
            or not self.deck
            or self._index < 0
            or item.data(0, Qt.ItemDataRole.UserRole) is None
        ):
            return
        refs = self._raw_slide()["sources"]
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        checked = item.checkState(0) == Qt.CheckState.Checked
        reason = ""
        if not checked and sid in refs:
            reason = "這個來源對應本頁使用中的圖表，請先移除圖表再取消引用。"
        elif not refs:
            reason = "每頁至少保留 1 個來源；請先勾選替代來源，再取消這個引用。"
        elif checked and len(refs) > 8:
            reason = "每頁最多 8 個來源；請先取消一個不需要的引用。"
        if reason:
            with QSignalBlocker(self.source_picker):
                item.setCheckState(0, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked)
            self.status.setText(reason)
        else:
            self._changed()
        self._source_count()

    def _source_count(self):
        self.sources_label.setText(f"本頁引用 · 已勾選 {len(self._checked_sources())}/8")
        self._filter_sources()

    def _figure_changed(self):
        if self._loading:
            return
        if not self._can_add_sources(
            [self.figure.currentData()] if self.figure.currentData() else []
        ):
            with QSignalBlocker(self.figure):
                self.figure.setCurrentIndex(getattr(self, "_last_figure", 0))
            return
        self._last_figure = self.figure.currentIndex()
        self._changed()

    def _cite(self, sid: str | None) -> None:
        for item in self._source_items:
            if item.data(0, Qt.ItemDataRole.UserRole) == sid:
                item.setCheckState(0, Qt.CheckState.Checked)

    def _material_feedback(self, text, success=False):
        self.status.setText(text)
        self.materials_panel.show_feedback(text, success)

    def _insert_material(
        self, payload: dict, x: float | None = None, y: float | None = None
    ) -> None:
        if not self.deck or self._index < 0:
            self._material_feedback("請先生成或新增投影片，再加入素材。")
            return
        if self.busy:
            self._material_feedback("目前正在生成或匯出，完成後即可加入素材。")
            return
        if not self.save_changes():
            self._material_feedback(self.status.text())
            return
        if len(self.canvas.objects) >= 60:
            self._material_feedback("每頁最多 60 個物件，請先刪除部分物件或換一頁。")
            return
        kind = payload.get("kind")
        source = payload.get("id") if kind in ("exhibit", "table") else payload.get("source")
        if kind == "sentence":
            page = payload.get("page")
            source = f"page:{page}" if type(page) is int and page > 0 else "original"
        if source and not self._can_add_sources([source]):
            self._material_feedback(self.status.text())
            return
        try:
            if kind == "exhibit":
                self._ensure_evidence(payload)
                spec = dict(kind="figure", figure=payload["id"], x=600, y=300, w=480, h=290)
            elif kind == "table":
                rows = payload["rows"]
                cols = len(rows[0])
                self._ensure_evidence(payload)
                spec = table_box(
                    rows,
                    56,
                    300,
                    min(1088, 120 + 150 * cols),
                    min(360, 30 * len(rows)),
                    18 if cols <= 6 else 14,
                )
            elif kind == "heading":
                spec = text_box(str(payload["text"]), 56, 82, 900, 60, 30, bold=True)
            elif kind == "sentence":
                page = payload.get("page")
                sid = f"page:{page}" if type(page) is int and page > 0 else "original"
                payload = dict(payload, source=sid)
                if not any(s["id"] == sid for s in self.deck.sources):
                    label = f"原文第 {page} 頁" if sid != "original" else "原文（無頁碼）"
                    self.deck.sources.append(dict(id=sid, kind="original", label=label, page=page))
                    self._add_source_item(sid, label)
                quote = f"「{payload['text']}」" + (f"（p.{page}）" if page else "")
                spec = text_box(quote, 56, 313, 820, 140, 22)
            else:
                return
        except (KeyError, TypeError, ValueError) as exc:
            self._material_feedback(f"素材無法加入：{exc}")
            return
        if x is not None and y is not None:
            spec["x"], spec["y"] = x, y
        self.views.setCurrentIndex(0)
        if not self.canvas.add_object(spec):
            self._material_feedback(self.canvas.hint.text())
            return
        source = payload.get("id") if kind in ("exhibit", "table") else payload.get("source")
        self._cite(source)
        self.canvas.scene.clearSelection()
        inserted = self.canvas.objects[-1]
        inserted.setSelected(True)
        self.canvas.view.ensureVisible(inserted)
        self.canvas.view.setFocus()
        self._material_feedback("已加入並選取新物件；可拖曳調整位置，稍後自動儲存。", True)

    def _draw_queued_thumbnails(self) -> None:
        """Draw waiting thumbnails until the turn's budget is spent, the one on
        screen first and then down the list as it is read."""
        if not self.deck:
            self._thumbnail_queue = []
            return
        start = time.perf_counter()
        while self._thumbnail_queue:
            if self._index in self._thumbnail_queue:
                self._thumbnail_queue.remove(self._index)
                index = self._index
            else:
                index = self._thumbnail_queue.pop(0)
            if index < min(len(self.deck.slides), self.outline.count()):
                self._thumbnail(index)
            if time.perf_counter() - start >= THUMBNAIL_BUDGET:
                break
        if self._thumbnail_queue:
            self._thumbnail_timer.start()

    def _thumbnail(self, index: int) -> None:
        if not self.deck:
            return
        key = _thumbnail_key(self.deck, index)
        image = _thumbnails.get(key)
        if image is None:
            self._thumbnail_canvas.load(self.deck, index)
            image = QPixmap(288, 162)
            image.fill(Qt.GlobalColor.white)
            painter = QPainter(image)
            self._thumbnail_canvas.scene.render(
                painter, QRectF(0, 0, 288, 162), QRectF(0, 0, 1200, 675)
            )
            painter.end()
            _thumbnails[key] = image
            if len(_thumbnails) > THUMBNAIL_CACHE_SIZE:
                _thumbnails.popitem(last=False)
        else:
            _thumbnails.move_to_end(key)
        if index in self._thumbnail_queue:
            self._thumbnail_queue.remove(index)
        self.outline.item(index).setIcon(QIcon(image))

    def _canvas_changed(self) -> None:
        if not self._loading and self.deck and self._index >= 0:
            if not self._dirty and self.canvas.snapshot() == elements_for(
                self.deck.slides[self._index]
            ):
                return
            self._dirty = self._canvas_dirty = True
            # Keep the structured editor in sync without emitting textChanged.
            fields = {
                "title": self.slide_title,
                "section": self.section,
                "takeaway": self.takeaway,
                "bullets": self.bullets,
            }
            for obj in self.canvas.snapshot():
                field = fields.get(obj.get("role"))
                if obj["kind"] != "text" or field is None:
                    continue
                value = obj["text"]
                with QSignalBlocker(field):
                    if field is self.bullets:
                        field.setPlainText(
                            "\n".join(line.lstrip("• ") for line in value.splitlines())
                        )
                    else:
                        field.setText(value)
            self._update_controls()
            self.status.setText("正在編輯，稍後自動儲存…")
            self._autosave.start()

    def _save_canvas(self) -> None:
        if self._dirty:
            self.save_changes()

    def _changed(self, *_args) -> None:
        if not self._loading and self.deck and self._index >= 0:
            self._dirty = True
            elements = self.canvas.snapshot()
            fields = {
                self.slide_title: "title",
                self.section: "section",
                self.takeaway: "takeaway",
                self.bullets: "bullets",
            }
            role = fields.get(self.sender())
            draft = deepcopy(self.deck)
            slide = draft.slides[self._index]
            slide.title = self.slide_title.text()
            slide.section = self.section.text()
            slide.takeaway = self.takeaway.text()
            slide.bullets = [
                line.strip().lstrip("•").strip()
                for line in self.bullets.toPlainText().splitlines()
                if line.strip()
            ]
            slide.speaker_notes = self.speaker_notes.toPlainText()
            slide.sources = self._checked_sources()
            if role:
                value = (
                    "\n".join("• " + b for b in slide.bullets)
                    if role == "bullets"
                    else getattr(slide, role)
                )
                matches = [obj for obj in elements if obj.get("role") == role]
                if not matches and value:
                    template = deepcopy(slide)
                    template.elements = None
                    obj = next(obj for obj in elements_for(template) if obj.get("role") == role)
                    elements.append(obj)
                    matches = [obj]
                for obj in matches:
                    obj["text"] = value
            figure = self.figure.currentData()
            previous_figure = self.canvas.deck.slides[self._index].figure
            if self.sender() is self.figure and figure != previous_figure:
                previous = next(
                    (
                        obj
                        for obj in elements
                        if obj["kind"] == "figure" and obj["figure"] == previous_figure
                    ),
                    None,
                )
                if previous and figure:
                    previous["figure"] = figure
                elif previous:
                    elements.remove(previous)
                elif figure:
                    elements.append(dict(kind="figure", figure=figure, x=564, y=310, w=580, h=285))
            slide.figure = figure
            for obj in elements:
                if obj["kind"] == "figure" and obj["figure"] not in slide.sources:
                    slide.sources.append(obj["figure"])
            slide.elements = elements
            self._canvas_dirty = True
            self._layout_reset = False
            # Render the draft even while a partially typed field is invalid.
            # The saved deck is only replaced after validation succeeds.
            self.canvas.load(draft, self._index)
            self._render_preview(slide)
            self.status.setText("已同步至畫布，稍後自動儲存…")
            self._autosave.start()

    def _raw_slide(self) -> dict:
        figure = self.figure.currentData()
        refs = self._checked_sources()
        if figure and figure not in refs:
            refs.append(figure)
        elements = (
            None
            if self._layout_reset
            else (
                self.canvas.snapshot()
                if self._canvas_dirty
                else self.deck.slides[self._index].elements
            )
        )
        for obj in elements or []:
            if obj["kind"] == "figure" and obj["figure"] not in refs:
                refs.append(obj["figure"])
        title = self.slide_title.text()
        return {
            "elements": elements,
            "title": title,
            "section": self.section.text(),
            "takeaway": self.takeaway.text(),
            "bullets": [
                x.strip().lstrip("•").strip()
                for x in self.bullets.toPlainText().splitlines()
                if x.strip()
            ],
            "speaker_notes": self.speaker_notes.toPlainText(),
            "sources": refs,
            "figure": figure,
        }

    def save_changes(self) -> bool:
        if not self.deck or not self._dirty or self._index < 0:
            return True
        try:
            raw = self._raw_slide()
            if not 1 <= len(raw["sources"]) <= 8:
                raise ValueError("請到「內容與引用」勾選 1–8 個來源（包含本頁圖表）。")
            slide = presentations.validate_slide(
                raw,
                {s["id"] for s in self.deck.sources},
                {f["id"] for f in self.deck.figures},
            )
            # Validate and persist a copy before replacing the visible draft.
            updated = presentations.deck_from_dict(self.deck.to_dict())
            updated.slides[self._index] = slide
            updated.edited = True
            presentations.save_deck(updated)
            with suppress(OSError):
                self._recovery_path().unlink(missing_ok=True)
        except (ValueError, OSError) as exc:
            self.status.setText(f"修改尚未儲存：{exc}")
            return False
        self._autosave.stop()
        canvas_only = self._canvas_dirty and not self._layout_reset
        self._canvas_dirty = self._layout_reset = False
        self._redo.clear()
        self._undo.append(self.deck.to_dict())
        self._undo = self._undo[-20:]
        self.deck = updated
        self.canvas.deck = updated
        self._dirty = False
        self._loading = True
        for item in self._source_items:
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if item.data(0, Qt.ItemDataRole.UserRole) in slide.sources
                else Qt.CheckState.Unchecked,
            )
        self._loading = False
        self._source_count()
        self._thumbnail(self._index)
        self._update_controls()
        self.outline.item(self._index).setText(f"{self._index + 1}. {slide.title}")
        self.status.setText("修改已儲存。")
        self._render_preview()
        if not canvas_only:
            self.canvas.load(self.deck, self._index)
        return True

    def _selected(self, index: int) -> None:
        if self._loading or not self.deck or index < 0:
            return
        if not self.save_changes():
            self._loading = True
            self.outline.setCurrentRow(self._index)
            self._loading = False
            return
        self._loading = True
        self._index = index
        slide = self.deck.slides[index]
        self.slide_title.setText(slide.title)
        self.section.setText(slide.section)
        self.takeaway.setText(slide.takeaway)
        self.bullets.setPlainText("\n".join(slide.bullets))
        self.speaker_notes.setPlainText(slide.speaker_notes)
        self.figure.setCurrentIndex(max(0, self.figure.findData(slide.figure)))
        self._last_figure = self.figure.currentIndex()
        for item in self._source_items:
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if item.data(0, Qt.ItemDataRole.UserRole) in slide.sources
                else Qt.CheckState.Unchecked,
            )
        self._dirty = False
        self._loading = False
        self._source_count()
        self.canvas.load(self.deck, self._index)
        self._canvas_dirty = self._layout_reset = False
        self._render_preview()

    def _open_source(self, url: QUrl) -> None:
        if not self.deck or url.scheme() != "paperfact-source":
            return
        sid = url.path()
        source = next((s for s in self.deck.sources if s["id"] == sid), None)
        if source:
            self.source_requested.emit(dict(source))

    def _render_preview(self, slide=None) -> None:
        if not self.deck or self._index < 0:
            return
        slide = slide if slide is not None else self.deck.slides[self._index]
        e = html.escape
        body = (
            '<div style="color:#2356bd">'
            + e(slide.section)
            + "</div>"
            + "<h2>"
            + e(slide.title)
            + "</h2><p><b>"
            + e(slide.takeaway)
            + "</b></p><ul>"
            + "".join("<li>" + e(b) + "</li>" for b in slide.bullets)
            + "</ul>"
        )
        if slide.elements is not None:
            body = "".join(
                "<p>" + e(obj["text"]).replace("\n", "<br>") + "</p>"
                for obj in slide.elements
                if obj["kind"] == "text"
            )
        for obj in slide.elements or []:
            if obj["kind"] == "table":
                body += (
                    '<table border="1" cellspacing="0" cellpadding="4">'
                    + "".join(
                        "<tr>" + "".join("<td>" + e(cell) + "</td>" for cell in row) + "</tr>"
                        for row in obj["rows"]
                    )
                    + "</table>"
                )
        figures = (
            [slide.figure]
            if slide.figure and slide.elements is None
            else [obj["figure"] for obj in slide.elements or [] if obj["kind"] == "figure"]
        )
        for figure in figures:
            try:
                image = QImage.fromData(presentations.figure_bytes(self.deck, figure))
                if image.isNull():
                    raise ValueError("圖片無法解碼")
                url = QUrl("paperfact-figure:" + figure)
                self.preview.document().addResource(
                    QTextDocument.ResourceType.ImageResource, url, image
                )
                width = min(420, max(100, self.preview.viewport().width() - 40))
                height = int(width * image.height() / max(image.width(), 1))
                body += f'<p><img src="{url.toString()}" width="{width}" height="{height}"></p>'
            except (ValueError, OSError) as exc:
                body += "<p>原圖讀取失敗：" + e(str(exc)) + "</p>"
        body += (
            '<hr><p style="font-size:11px">來源：'
            + " · ".join(
                '<a href="'
                + e(QUrl("paperfact-source:" + sid).toString(), quote=True)
                + '">'
                + e(str(next(s for s in self.deck.sources if s["id"] == sid).get("label", sid)))
                + "</a>"
                for sid in slide.sources
            )
            + f"</p><p>{self._index + 1} / {len(self.deck.slides)}</p>"
        )
        self.preview.setHtml(body)

    def _mode_changed(self, _index: int) -> None:
        mode = self.mode.currentData()
        if mode == self._mode:
            return
        if not self.save_changes():
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData(self._mode))
            self.mode.blockSignals(False)
            return
        self._mode = mode
        if self.paper_id:
            self.load(self.paper_id, self.paper_label.text())

    def _generate(self) -> None:
        if not self.paper_id or self.busy:
            return
        if self.deck:
            if getattr(self, "_generate_dialog", None):
                self._generate_dialog.raise_()
                return
            box = QMessageBox(self)
            self._generate_dialog = box
            box.setWindowTitle("重新產生整份簡報？")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("AI 將重新製作整份簡報，取代目前顯示的投影片與排版。")
            box.setInformativeText(
                "目前修改會先儲存；成功後舊稿可從「歷史版本」還原。這會使用 AI 額度。要繼續嗎？"
            )
            proceed = box.addButton("儲存並重新產生", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("取消，繼續編輯", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(cancel)
            box.setEscapeButton(cancel)
            paper_id, mode, deck_id = self.paper_id, self._mode, self.deck.deck_id

            def finished(_result):
                accepted = box.clickedButton() is proceed
                self._generate_dialog = None
                box.deleteLater()
                if (
                    accepted
                    and self.paper_id == paper_id
                    and self._mode == mode
                    and self.deck
                    and self.deck.deck_id == deck_id
                ):
                    self._start_generation()

            box.finished.connect(finished)
            box.open()
            return
        self._start_generation()

    def _start_generation(self) -> None:
        from paper_daily.desktop.ai_access import requires_ai

        requires_ai("slides")(type(self)._start_generation_ready)(self)

    def _start_generation_ready(self) -> None:
        if not self.paper_id or self.busy or not self.save_changes():
            return
        try:
            cfg = llm.settings(task="slides")
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        if not llm.available(task="slides"):
            self.status.setText("請從上方「AI 設定」設定論文簡報使用的連線。")
            return
        paper_id, mode = self.paper_id, self._mode
        options = dict(
            mode=mode,
            audience=self.audience.text().strip() or "有研究基礎但未讀過這篇的研究者",
            minutes=self.minutes.value(),
            slide_count=self.count.value(),
            inputs={k for k, box in self.inputs.items() if box.isChecked()},
            cfg=cfg,
        )
        self._generating = True
        self._update_controls()
        self.status.setText("正在讀取來源並生成投影片與講稿，通常需要數分鐘…可繼續閱讀。")

        def make(_prompt):
            try:
                deck, reason = presentations.generate(paper_id, **options)
                return (json.dumps(deck.to_dict(), ensure_ascii=False) if deck else None), reason
            except Exception as exc:  # noqa: BLE001 - keep the worker lifecycle intact
                return None, f"簡報工作失敗：{type(exc).__name__}"

        self.runner.start("", self._generated, self._failed, call=make, task="slides")

    def _generated(self, text: str) -> None:
        self._generating = False
        try:
            deck = presentations.deck_from_dict(json.loads(text))
        except (ValueError, TypeError) as exc:
            self._failed(str(exc))
            return
        if deck.paper_id == self.paper_id and deck.mode == self._mode:
            self._undo.clear()
            self._redo.clear()
            self._show_deck(deck)
        else:
            self._update_controls()
            self.status.setText("簡報已保存至原論文，切回該論文與版本即可查看。")

    def _failed(self, reason: str) -> None:
        self.runner.activity.finish(False)
        self._generating = False
        self._update_controls()
        self.status.setText(f"簡報未生成，已保存的版本未變動：{reason}")

    def _move(self, direction: int) -> None:
        if not self.deck or not self.save_changes():
            return
        target = self._index + direction
        if not 0 <= target < len(self.deck.slides):
            return
        updated = presentations.deck_from_dict(self.deck.to_dict())
        updated.slides[self._index], updated.slides[target] = (
            updated.slides[target],
            updated.slides[self._index],
        )
        updated.edited = True
        try:
            presentations.save_deck(updated)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self._redo.clear()
        self._undo.append(self.deck.to_dict())
        self._show_deck(updated, reset_options=False)
        self.outline.setCurrentRow(target)

    def _remove(self) -> None:
        if not self.deck or len(self.deck.slides) <= 1 or not self.save_changes():
            return
        updated = presentations.deck_from_dict(self.deck.to_dict())
        updated.slides.pop(self._index)
        updated.edited = True
        try:
            presentations.save_deck(updated)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self._redo.clear()
        self._undo.append(self.deck.to_dict())
        self._show_deck(updated, reset_options=False)

    def _add(self) -> None:
        if not self.deck or not self.save_changes():
            return
        if len(self.deck.slides) >= presentations.MAX_SLIDES:
            self.status.setText("最多 24 頁，請先刪除或合併投影片。")
            return
        updated = presentations.deck_from_dict(self.deck.to_dict())
        source = next((s for s in updated.sources if s["kind"] == "original"), updated.sources[0])
        updated.slides.insert(
            self._index + 1,
            presentations.Slide("新投影片", "", "", ["請填寫本頁重點"], "", [source["id"]]),
        )
        updated.edited = True
        try:
            presentations.save_deck(updated)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        target = self._index + 1
        self._redo.clear()
        self._undo.append(self.deck.to_dict())
        self._show_deck(updated, reset_options=False)
        self.outline.setCurrentRow(target)
        self.views.setCurrentIndex(0)

    def _revise_current_slide(self):
        if not self.deck or self._index < 0 or self.busy or not self.save_changes():
            return
        instruction = self.canvas.revise_instruction.toPlainText().strip()
        if not instruction or len(instruction) > 2000:
            self.status.setText("請寫下這一頁要怎麼改（2000 字以內）。")
            return
        snapshot = self.deck.to_dict()
        paper_id, index = self.paper_id, self._index
        self._revising = True
        self._update_controls()
        self.status.setText(f"正在改寫第 {index + 1} 頁；其餘頁面保留。")

        def run(_prompt):
            try:
                candidate = presentations.deck_from_dict(snapshot)
                slide, reason = slide_revise.revise(candidate, index, instruction)
                if slide is None:
                    return None, reason
                slide.elements = None
                candidate.slides[index] = slide
                return json.dumps(
                    dict(deck=candidate.to_dict(), summary=reason), ensure_ascii=False
                ), "ok"
            except Exception as exc:  # Worker errors must leave the original draft usable.
                return None, f"單頁改寫失敗：{type(exc).__name__}: {exc}"

        def done(answer):
            self._revising = False
            self._update_controls()
            if (
                self.paper_id != paper_id
                or self._index != index
                or not self.deck
                or self.deck.to_dict() != snapshot
                or self._dirty
            ):
                if self.paper_id == paper_id:
                    self.status.setText("頁面或內容已變更，這次 AI 結果未套用；原頁保留。")
                return
            try:
                result = json.loads(answer)
                updated = presentations.deck_from_dict(result["deck"])
                updated.edited = True
                presentations.save_deck(updated)
            except (ValueError, OSError) as exc:
                self.status.setText(f"改寫未儲存，原頁保留：{exc}")
                return
            self._undo.append(snapshot)
            self._undo = self._undo[-20:]
            self._redo.clear()
            self._show_deck(updated, reset_options=False)
            self.outline.setCurrentRow(index)
            self.canvas.view.setFocus()
            undo = fonts.key(QKeySequence.StandardKey.Undo)
            self.status.setText(result["summary"] + f"（已儲存；{undo} 可復原）")

        def failed(reason):
            self._revising = False
            self._update_controls()
            if self.paper_id == paper_id:
                self.status.setText(f"原頁未變動：{reason}")

        self.runner.start("", done, failed, call=run, task="slides")

    def _undo_edit(self) -> None:
        if self.busy or not self.save_changes() or not self._undo:
            return
        self._restore_edit(self._undo, self._redo, "已復原上一個簡報修改。")

    def _redo_edit(self) -> None:
        if self.busy or not self.save_changes() or not self._redo:
            return
        self._restore_edit(self._redo, self._undo, "已重做簡報修改。")

    def _restore_edit(self, source: list, target: list, message: str) -> None:
        previous = presentations.deck_from_dict(source[-1])
        try:
            presentations.save_deck(previous)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        index = self._index
        target.append(self.deck.to_dict())
        source.pop()
        self._show_deck(previous, reset_options=False)
        self.outline.setCurrentRow(min(index, len(previous.slides) - 1))
        self.canvas.view.setFocus()
        self.status.setText(message)

    def _restore_history(self) -> None:
        if not self.paper_id or self.busy or not self.save_changes():
            return
        try:
            versions = presentations.list_versions(self.paper_id, self._mode)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        if not versions:
            self.status.setText("尚無歷史版本。重新產生成功後，前一份草稿會自動保留在這裡。")
            return
        labels = [
            f"{i + 1}. {v['created_at']} · {v['slides']} 頁 · {v['title']}"
            for i, v in enumerate(versions)
        ]
        label, ok = QInputDialog.getItem(
            self, "還原歷史版本", "目前草稿也會先保留。選擇要還原的版本：", labels, 0, False
        )
        if not ok:
            return
        try:
            deck = presentations.restore_version(
                self.paper_id, self._mode, versions[labels.index(label)]["file"]
            )
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self._undo.clear()
        self._redo.clear()
        self._show_deck(deck)
        self.status.setText("已還原歷史版本；還原前的草稿也已保留。")

    def _export(self) -> None:
        if not self.deck or self.busy or not self.save_changes():
            return
        filename, selected = QFileDialog.getSaveFileName(
            self,
            "匯出論文簡報",
            presentation_export.suggested_filename(self.deck.paper_title),
            "PDF 投影片 (*.pdf);;HTML 投影片 (*.html);;Markdown 講稿 (*.md);;"
            "JSON 簡報資料 (*.json);;OpenDocument 可編輯簡報 (*.odp)",
        )
        if not filename:
            return
        suffix = (
            ".md"
            if selected.startswith("Markdown")
            else (".json" if selected.startswith("JSON") else ".pdf")
        )
        if selected.startswith("HTML"):
            suffix = ".html"
        if selected.startswith("OpenDocument"):
            suffix = ".odp"
        if selected.startswith("PDF"):
            suffix = ".pdf"
        dest = Path(filename)
        if dest.suffix.lower() != suffix:
            dest = dest.with_suffix(suffix)
            if (
                dest.exists()
                and QMessageBox.question(
                    self,
                    "覆寫匯出檔案",
                    f"{dest.name} 已存在，要覆寫嗎？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        if suffix == ".pdf":
            self._export_pdf(dest)
            return
        exporter = {
            ".html": presentation_export.export_html,
            ".md": presentation_export.export_markdown,
            ".json": presentation_export.export_json,
            ".odp": presentation_odp.export_odp,
        }[suffix]
        try:
            exporter(self.deck, dest, include_notes=self.include_notes.isChecked())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "簡報匯出失敗", str(exc))
            return
        self.status.setText(f"已匯出：{dest.name}。HTML 可離線播放，或列印成 PDF。")
        if suffix == ".html":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest.resolve())))

    def _export_pdf(self, dest: Path) -> None:
        if self.busy or self.deck is None:
            return
        try:
            from paper_daily.desktop.presentation_pdf import PdfExport
        except ImportError:
            self.status.setText("PDF 匯出需要 Qt GUI；可先匯出 HTML 再從瀏覽器列印 PDF。")
            return
        from paper_daily.desktop.activity import begin

        self._pdf_activity = begin(self, "匯出 PDF 投影片", key=f"slides-pdf:{self.paper_id}")
        if not self._pdf_activity.accepted:
            return
        job = PdfExport(self)
        job.progress.connect(self._pdf_progress)
        self._pdf_job = job
        job.finished.connect(self._pdf_finished)
        job.failed.connect(self._pdf_failed)
        self._update_controls()
        self.status.setText("正在匯出 PDF 投影片；講者備註請另外匯出 HTML 或 Markdown。")
        job.start(self.deck, dest)

    def _pdf_progress(self, done, total):
        self._pdf_activity.update(dict(stage=f"已繪製 {done}/{total} 頁",
                                       completed=done, total=total))

    def _pdf_finished(self, filename: str) -> None:
        self._pdf_activity.finish(message="PDF 已匯出")
        job, self._pdf_job = self._pdf_job, None
        self._update_controls()
        self.status.setText(f"PDF 已匯出：{Path(filename).name}")
        if job:
            job.deleteLater()

    def _pdf_failed(self, reason: str) -> None:
        self._pdf_activity.finish(False, "PDF 未匯出，請查看簡報區的原因")
        job, self._pdf_job = self._pdf_job, None
        self._update_controls()
        self.status.setText(f"PDF 未匯出：{reason}")
        if job:
            job.deleteLater()

    def _google_configure(self) -> bool:
        if self.busy:
            return False
        QMessageBox.information(
            self,
            "連接 Google Slides",
            "此設定供 Paperfact 開發者或自架管理者使用。"
            "先在 Google Cloud 啟用 Drive 與 Slides API，建立 Desktop app OAuth client，"
            "並下載 JSON 設定檔。接著選取此檔，匯出時會在系統瀏覽器登入。\n\n"
            "Paperfact 只要求存取自己建立的檔案。登入憑證僅保留在本次 app 工作階段。\n"
            "設定步驟：https://developers.google.com/workspace/drive/api/quickstart/python",
        )
        filename, _ = QFileDialog.getOpenFileName(
            self, "選取 Google Desktop OAuth client", "", "JSON (*.json)"
        )
        if not filename:
            return False
        try:
            google_slides.configure(Path(filename))
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return False
        self._google_session = None
        self.status.setText("Google 連線設定已保存。選擇匯出副本後，會開啟瀏覽器登入。")
        return True

    def _google_disconnect(self) -> None:
        self._google_session = None
        self.status.setText("已清除本次工作階段的 Google 登入。雲端簡報仍保留在你的 Drive。")

    def _google_switch_account(self) -> None:
        if not self.busy:
            self._google_session = None
            self._google_export()

    def _google_open(self) -> None:
        if not self.paper_id:
            return
        url = google_slides.last_link(self.paper_id, self._mode)
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            self.status.setText("此版本尚未匯出 Google Slides，請先建立可編輯副本。")

    def _google_export(self) -> None:
        if not self.deck or self.busy or not self.save_changes():
            return
        try:
            google_slides.read_client()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        deck = presentations.deck_from_dict(self.deck.to_dict())
        self._cloud_busy = True
        self._update_controls()
        self.status.setText("正在連接 Google，請在系統瀏覽器完成登入。接著會建立新的簡報副本。")

        def upload(_prompt):
            try:
                if self._google_session is None:
                    self._google_session = google_slides.authorize()
                url = google_slides.export_copy(deck, self._google_session, include_notes=True)
                return json.dumps({"url": url}), "ok"
            except google_slides.GoogleNotesError as exc:
                return json.dumps({"url": exc.url, "warning": str(exc)}), "ok"
            except Exception as exc:  # noqa: BLE001 - finish the worker on connection errors
                if isinstance(exc, ValueError):
                    return None, str(exc)
                return None, f"Google 連線失敗：{type(exc).__name__}"

        previous_label = getattr(self.runner, "activity_label", None)
        self.runner.activity_label = "建立 Google Slides"
        try:
            self.runner.start("", self._google_done, self._google_failed, call=upload)
        finally:
            self.runner.activity_label = previous_label

    def _google_done(self, result: str) -> None:
        data = json.loads(result)
        url = data["url"]
        self._cloud_busy = False
        self._update_controls()
        message = data.get("warning") or "已建立 Google Slides，講稿與引用已一併整理。"
        self.status.setText(f"{message} {url}")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        QDesktopServices.openUrl(QUrl(url))

    def _google_failed(self, reason: str) -> None:
        self._cloud_busy = False
        self._update_controls()
        self.status.setText(reason)
