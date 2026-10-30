"""A small task picker; opening, previewing and canceling never call AI."""
from pathlib import Path

from PySide6.QtWidgets import QDialog, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QPushButton

from paper_daily import research_tasks, store


def identity(reader):
    paper = reader.paper
    return (Path(store.DB_PATH).resolve(), paper.id if paper else None,
            getattr(reader, '_qa_epoch', None))


def preview(reader, title, text):
    dialog = QInputDialog(reader)
    dialog.setWindowTitle(title)
    dialog.setLabelText('可編輯任務，也可補上你的研究目的。確認後只帶入草稿，送出才會詢問 AI。')
    dialog.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
    dialog.setTextValue(text)
    dialog.setOkButtonText('帶入草稿')
    dialog.setCancelButtonText('取消')
    editor = dialog.findChild(QPlainTextEdit)
    if editor is not None:
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    dialog.resize(680, 420)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    result = dialog.textValue()
    dialog.deleteLater()
    return result, accepted


def draft(reader, task_id):
    before = identity(reader)
    if before[1] is None:
        return
    was_visible = reader.window().isVisible()
    original = reader.ask_box.text()
    task = next(item for item in research_tasks.TASKS if item.id == task_id)
    text, accepted = preview(reader, task.label, research_tasks.question(task_id))
    if not accepted or not text.strip() or (was_visible and not reader.window().isVisible()):
        return
    if identity(reader) != before or reader.ask_box.text() != original:
        reader.ask_status.setText('論文或草稿已變更，保留目前輸入；請重新選擇研究任務。')
        return
    if original.strip():
        choice = QMessageBox.question(
            reader, '取代提問草稿？', '目前有尚未送出的提問。要用這個研究任務取代嗎？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
    if (identity(reader) == before and reader.ask_box.text() == original
            and (not was_visible or reader.window().isVisible())):
        reader._draft_question(text.strip())


def button(reader):
    widget = QPushButton('研究任務…')
    widget.setObjectName('researchTasks')
    widget.setToolTip('核對證據、評估方法、解讀圖表、規劃重現；先編輯草稿，再自行送出。')
    menu = QMenu(widget)
    for task in research_tasks.TASKS:
        action = menu.addAction(task.label)
        action.setData(task.id)
        action.triggered.connect(lambda _checked=False, key=task.id: draft(reader, key))
    widget.setMenu(menu)
    return widget
