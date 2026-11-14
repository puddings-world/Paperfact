"""A small task picker; opening, previewing and canceling never call AI."""
import sqlite3
from contextlib import closing
from pathlib import Path

from PySide6.QtWidgets import QDialog, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QPushButton

from paper_daily import reading_goals, research_tasks, store


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


def purpose(reader):
    host = getattr(reader, 'win', reader.window())
    list_id = getattr(host, 'active_list', None)
    if not list_id:
        return None
    database = Path(store.DB_PATH).resolve()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        member = conn.execute('SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?',
                              (list_id, reader.paper.id)).fetchone()
    if member is None:
        return None
    context = reading_goals.load(database, list_id)
    return (list_id, reading_goals.text(context), context.data['parent_lifecycle'],
            context.data['database_identity'])


def draft(reader, task_id):
    before = identity(reader)
    if before[1] is None:
        return
    try:
        intent = purpose(reader)
    except (OSError, ValueError, sqlite3.Error):
        reader.ask_status.setText('無法讀取清單研究目的，請重新選擇清單後重試。')
        return
    was_visible = reader.window().isVisible()
    original = reader.ask_box.text()
    task = next(item for item in research_tasks.TASKS if item.id == task_id)
    question = research_tasks.question(task_id, goal=intent[1] if intent else '')
    text, accepted = preview(reader, task.label, question)
    if not accepted or not text.strip() or (was_visible and not reader.window().isVisible()):
        return
    try:
        unchanged_purpose = purpose(reader) == intent
    except (OSError, ValueError, sqlite3.Error):
        unchanged_purpose = False
    if not unchanged_purpose or identity(reader) != before or reader.ask_box.text() != original:
        reader.ask_status.setText('論文或草稿已變更，保留目前輸入；請重新選擇研究任務。')
        return
    if original.strip():
        choice = QMessageBox.question(
            reader, '取代提問草稿？', '目前有尚未送出的提問。要用這個研究任務取代嗎？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
    try:
        unchanged_purpose = purpose(reader) == intent
    except (OSError, ValueError, sqlite3.Error):
        unchanged_purpose = False
    if (unchanged_purpose and identity(reader) == before and reader.ask_box.text() == original
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
    menu.addSeparator()
    claims = menu.addAction("\u6838\u5c0d\u8ad6\u8b49\u8207\u539f\u6587\u2026")
    claims.setData('claim_evidence')
    from paper_daily.desktop.claim_evidence import open_report

    claims.triggered.connect(lambda: open_report(reader))
    audit = menu.addAction("\u6aa2\u67e5\u5df2\u5b58\u8b49\u64da\u2026")
    audit.setData("analysis_audit")
    from paper_daily.desktop.research_audit import open_report as open_audit

    audit.triggered.connect(lambda: open_audit(reader))
    lineage = menu.addAction("\u7814\u7a76\u8108\u7d61\u5206\u6790\u2026")
    lineage.setData("grounded_lineage")
    from paper_daily.desktop.lineage_dialog import open_report as open_lineage

    lineage.triggered.connect(lambda: open_lineage(reader))
    widget.setMenu(menu)
    return widget
