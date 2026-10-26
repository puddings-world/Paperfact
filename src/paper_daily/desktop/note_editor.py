"""Edit a note as Markdown, with the rendered note beside it.

Half the notes are answers kept from 問 Claude: tables, step-by-step formulas,
lists. Editing them as a plain text box meant tidying a table blind, so the editor
shows the source and the rendered note side by side (分割), or either one alone,
the way a Markdown editor does. The preview is the same renderer the cards use, so
what you see is what the card will show.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from paper_daily.desktop import fonts, md
from paper_daily.store import connect, get_kv, set_kv

MODES = ("編輯", "分割", "預覽")
SAVE_TEXT = {
    "zh-TW": {
        "save": "儲存",
        "cancel": "取消",
        "status": "儲存狀態",
        "missing": "這則筆記已不存在，請重新整理。",
        "changed": "筆記已在別處變更。請重新整理並確認新版內容後再刪除。",
        "delete_failed": "尚未刪除。請確認筆記是否已變更，再重試。",
        "deleted": "已刪除筆記。",
        "empty": "請保留筆記內容；若要刪除整則筆記，請回到筆記清單。",
        "failed": "尚未儲存，內容仍保留在這裡。請確認筆記是否已在其他視窗變更，再重試或複製草稿。",
        "stale": "筆記已在別處更新。這份修改已保留為待核對版本，草稿仍在這裡。",
    },
    "en": {
        "save": "Save",
        "cancel": "Cancel",
        "status": "Save status",
        "missing": "This note no longer exists. Refresh the note list.",
        "changed": "This note changed elsewhere. Refresh and review it before deleting.",
        "delete_failed": "Not deleted. Check for changes, then retry.",
        "deleted": "Note deleted.",
        "empty": "Keep some note text. To delete the note, return to the note list.",
        "failed": (
            "Not saved. Your draft is still here. Check for changes elsewhere, "
            "then retry or copy it."
        ),
        "stale": (
            "This note changed elsewhere. Your revision was retained for review; "
            "the draft is still here."
        ),
    },
}


def note_message(code, language="zh-TW"):
    return SAVE_TEXT.get(language, SAVE_TEXT["en"])[code]


class NoteEditor(QDialog):
    def __init__(
        self, body: str, palette: dict[str, str], hint: str = "", parent=None,
        *, save=None, language="zh-TW", save_messages=None,
    ) -> None:
        super().__init__(parent)
        self.pal = palette
        self._save_callback = save
        self._saving = self._saved = False
        self._save_text = {**SAVE_TEXT.get(language, SAVE_TEXT["en"]), **(save_messages or {})}
        self.setWindowTitle("編輯筆記" if language == "zh-TW" else "Edit note")
        self.resize(1100, 700)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        if hint:
            note = QLabel(hint)
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{palette['muted']};font-size:11px;")
            top.addWidget(note, 1)
        else:
            top.addStretch(1)
        self.modes = QButtonGroup(self)
        modes = MODES if language == "zh-TW" else ("Edit", "Split", "Preview")
        for i, name in enumerate(modes):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton{{background:{palette['surface']};color:{palette['muted']};"
                f"border:1px solid {palette['firm']};padding:3px 12px;font-size:12px;}}"
                f"QPushButton:checked{{background:{palette['accent']};color:#ffffff;"
                f"border-color:{palette['accent']};}}"
            )
            self.modes.addButton(button, i)
            top.addWidget(button)
        layout.addLayout(top)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.editor = QPlainTextEdit(body)
        self.editor.setFont(fonts.font(fonts.MONO, 11))
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setStyleSheet(
            f"QTextBrowser{{background:{palette['surface']};color:{palette['ink']};"
            f"border:1px solid {palette['border']};padding:10px;}}"
        )
        self.split.addWidget(self.editor)
        self.split.addWidget(self.preview)
        layout.addWidget(self.split, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_status = QLabel()
        self.save_status.setWordWrap(True)
        self.save_status.setAccessibleName(self._save_text["status"])
        layout.addWidget(self.save_status)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText(self._save_text["save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self._save_text["cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Re-rendering a long answer on every keystroke stutters; a pause is enough.
        self._render_soon = QTimer(self)
        self._render_soon.setSingleShot(True)
        self._render_soon.setInterval(200)
        self._render_soon.timeout.connect(self._render)
        self.editor.textChanged.connect(self._render_soon.start)
        self.editor.verticalScrollBar().valueChanged.connect(self._follow)
        self.modes.idClicked.connect(self._set_mode)

        with connect() as conn:
            mode = get_kv(conn, "ui.note_editor_mode", 1)
        self.modes.button(mode).setChecked(True)
        self._set_mode(mode, remember=False)
        self._render()

    def accept(self) -> None:
        if self._saving or self._saved:
            return
        if self._save_callback is None:
            super().accept()
            return
        body = self.text().strip()
        if not body:
            self.save_status.setText(self._save_text["empty"])
            return
        self._saving = True
        self.save_button.setEnabled(False)
        try:
            self._save_callback(body)
        except Exception as exc:
            key = "stale" if getattr(exc, "candidate_id", None) else "failed"
            self.save_status.setText(self._save_text[key])
        else:
            self._saved = True
            super().accept()
        finally:
            self._saving = False
            self.save_button.setEnabled(not self._saved)

    def text(self) -> str:
        return self.editor.toPlainText()

    def _render(self) -> None:
        bar = self.preview.verticalScrollBar()
        keep = bar.value()
        self.preview.setHtml(md.to_html(self.editor.toPlainText(), self.pal))
        bar.setValue(keep)

    def _follow(self, _value: int) -> None:
        """Keep the preview at the same place in the note as the source."""
        source = self.editor.verticalScrollBar()
        target = self.preview.verticalScrollBar()
        if source.maximum():
            target.setValue(round(target.maximum() * source.value() / source.maximum()))

    def _set_mode(self, mode: int, remember: bool = True) -> None:
        self.editor.setVisible(mode in (0, 1))
        self.preview.setVisible(mode in (1, 2))
        if mode == 1:
            self.split.setSizes([1, 1])
        if remember:
            with connect() as conn:
                set_kv(conn, "ui.note_editor_mode", mode)
