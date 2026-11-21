"""Display saved analysis independently of the rich reader and its render worker."""

import sqlite3

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

from paper_daily import analyze
from paper_daily.workspace_service import _read


def result_text(database, paper_id, job):
    stages = "\n".join(job.history) or job.stage
    with _read(database) as conn:
        paper = conn.execute("SELECT title FROM papers WHERE id=?", (paper_id,)).fetchone()
        if paper is None:
            return f"這篇論文已不在此工作區。\n\n{stages}"
        dive = conn.execute("SELECT body,written_at FROM dives WHERE paper_id=?",
                            (paper_id,)).fetchone()
        reasons = [f"{label}：{reason}" for key, label in analyze.STEPS.items()
                   if (reason := analyze.failed(conn, paper_id, key))]
    parts = [paper[0], job.stage, "本次工作紀錄\n" + stages]
    if reasons:
        parts.append("已記錄的步驟原因\n" + "\n".join(reasons))
    parts.append(f"已儲存講解 · {dive[1]}\n\n{dive[0]}" if dive and dive[0]
                 else "目前尚無已儲存的深度講解。")
    return "\n\n".join(parts)


def show_analysis_result(parent, database, paper_id, job):
    dialog = QDialog(parent)
    dialog.setWindowTitle("深入分析結果")
    dialog.resize(780, 560)
    layout = QVBoxLayout(dialog)
    view = QPlainTextEdit(dialog)
    view.setReadOnly(True)
    try:
        view.setPlainText(result_text(database, paper_id, job))
    except sqlite3.Error as exc:
        view.setPlainText(f"無法讀取已儲存的結果：{exc}\n\n" + "\n".join(job.history))
    layout.addWidget(view)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
