"""Explicit, backed-up recovery when settings cannot be opened."""

from uuid import uuid4

from PySide6.QtWidgets import QMessageBox

from paper_daily import ai_profiles, llm


def backup_and_reset():
    source = llm.SETTINGS_PATH
    content = source.read_bytes()
    backup = source.with_name(f"llm-recovery-{uuid4().hex[:12]}.json")
    with backup.open("xb") as stream:
        stream.write(content)
    # Atomic replacement leaves the original settings intact if writing fails.
    ai_profiles.write(source, {"backend": "none", "isolated": True})
    return backup


def offer(parent):
    choice = QMessageBox.question(
        parent, "AI 設定無法讀取",
        "可以先備份現有 AI 設定，再重設為未啟用 AI。\n"
        "論文、筆記與官方登入檔案會保留；重設後需要重新選擇 AI。\n"
        "要備份並重設嗎？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if choice != QMessageBox.StandardButton.Yes:
        return False
    try:
        backup = backup_and_reset()
    except OSError:
        QMessageBox.warning(parent, "重設未完成", "無法備份或寫入設定，原設定仍保留。")
        return False
    QMessageBox.information(
        parent, "已備份並重設", f"原設定保存在：{backup.name}\n備份可能包含金鑰，請勿分享。"
    )
    return True
