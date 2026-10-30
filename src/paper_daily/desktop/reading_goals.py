"""Edit a list purpose independently of generated summaries and paper content."""
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from paper_daily import reading_goals


class ReadingGoalDialog(QDialog):
    def __init__(self, database, list_id, parent=None, *, current_path=None):
        super().__init__(parent)
        self.path = Path(database).resolve()
        self.list_id = list_id
        self.current_path = current_path or (lambda: self.path)
        self.context = reading_goals.load(self.path, list_id)
        self._saving = False
        self.disposed = False
        self.publication = None
        self.setWindowTitle('清單研究目的')
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        label = QLabel('這份清單要幫你回答什麼問題？也可以寫下背景、閱讀深度或比較標準。'
                       '研究目的會隨清單分享及同步；儲存不會呼叫 AI 或重做既有分析。')
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText('例如：比較不同方法的假設與證據，找出可用於下一個實驗的設計。')
        self.editor.setPlainText(reading_goals.text(self.context))
        layout.addWidget(self.editor, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText('儲存研究目的')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.editor.textChanged.connect(self.validate)
        self.validate()

    def validate(self):
        count = len(self.editor.toPlainText())
        self.status.setText(f'{count} / {reading_goals.MAX_GOAL} 字；留空可清除研究目的。')
        self.save_button.setEnabled(not self._saving and count <= reading_goals.MAX_GOAL)

    def save(self):
        if self.disposed or self._saving or not self.save_button.isEnabled():
            return
        if Path(self.current_path()).resolve() != self.path:
            self.status.setText('工作區已變更；請保留文字，關閉後在原清單重新開啟。')
            self.save_button.setEnabled(False)
            return
        self._saving = True
        self.save_button.setEnabled(False)
        try:
            publication = reading_goals.save(self.context, self.editor.toPlainText())
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            self.status.setText(f'尚未儲存，可重試：{type(error).__name__}')
        else:
            self.publication = publication
            if publication is None or publication.status == 'accepted':
                self.accept()
            else:
                self.status.setText('清單或研究目的已變更。你的文字已保留供審閱，未覆蓋較新的內容。')
                self.editor.setReadOnly(True)
                self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('返回清單')
        finally:
            self._saving = False
            if not self.disposed and not self.editor.isReadOnly():
                self.save_button.setEnabled(
                    len(self.editor.toPlainText()) <= reading_goals.MAX_GOAL)

    def done(self, result):
        if self._saving:
            # A successful synchronous commit is already complete before accept().
            self._saving = False
        self.disposed = True
        super().done(result)
