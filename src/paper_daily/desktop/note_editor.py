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

from paper_daily.desktop import fonts, md, ui_state
from paper_daily.store import connect

MODES = ("編輯", "分割", "預覽")


class NoteEditor(QDialog):
    def __init__(self, body: str, palette: dict[str, str], hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.pal = palette
        self.setWindowTitle("編輯筆記")
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
        for i, name in enumerate(MODES):
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
            mode = ui_state.read(conn, "ui.note_editor_mode", 1)
        self.modes.button(mode).setChecked(True)
        self._set_mode(mode, remember=False)
        self._render()

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
            ui_state.save("ui.note_editor_mode", mode)
