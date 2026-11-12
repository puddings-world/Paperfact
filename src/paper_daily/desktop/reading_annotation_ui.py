"""Actual-pane bridge to one workspace/source-bound grouped annotation workflow."""
import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path

from PySide6.QtCore import QTimer
from shiboken6 import isValid

from paper_daily import (
    annotation_reader,
    llm,
    manual_highlight_ops,
    reading_annotation_jobs,
    reading_links,
    store,
)


@contextmanager
def automatic(pane):
    """Suppress repeated passive notices only; never cache account capability."""
    previous = getattr(pane, "_annotation_automatic", False)
    pane._annotation_automatic = True
    try:
        yield
    finally:
        pane._annotation_automatic = previous


def bind(pane):
    """Capture the loaded target, never infer a later destination from global settings."""
    pane._annotation_epoch = getattr(pane, '_annotation_epoch', 0) + 1
    pane._annotation_owner = None
    parent = pane.parent()
    database = Path(store.DB_PATH).resolve()
    try:
        if parent is not None and hasattr(parent, '_highlight_owner'):
            owner = parent._highlight_owner
            if owner is None or owner.paper_id != pane.paper_id:
                return
        else:
            owner = manual_highlight_ops.capture_owner(database, pane.paper_id)
        if owner.database != database:
            return
        pane._annotation_owner = owner
    except (OSError, ValueError, sqlite3.Error):
        return


def _current(pane, owner, epoch, fingerprint):
    if (not isValid(pane) or pane.paper_id != owner.paper_id
            or pane._annotation_owner is not owner or pane._annotation_epoch != epoch
            or Path(store.DB_PATH).resolve() != owner.database):
        return False
    parent = pane.parent()
    if fingerprint is not None and parent is not None and hasattr(parent, '_pdf_fingerprint'):
        return parent._pdf_fingerprint == fingerprint
    return True


def _controls(pane, busy):
    pane._highlights_busy = busy
    pane._update_controls()
    if not busy:
        QTimer.singleShot(0, pane, pane._update_controls)
    parent = pane.parent()
    if parent is not None and hasattr(parent, 'prepare_highlights'):
        parent.prepare_highlights.setEnabled(not busy)
        stop = getattr(parent, 'stop_highlights', None)
        if stop is not None:
            stop.setVisible(busy)
            stop.setEnabled(busy and not pane._annotation_cancel.is_set())


def _model_task(database, paper_id, force):
    """Saved complete work is reusable without reading account configuration."""
    if force:
        return 'paper_highlights'
    saved = annotation_reader.saved(database, paper_id, 'highlight_analysis')
    if saved is None:
        return 'paper_highlights'
    if not saved['items']:
        return None
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.25)) as conn:
        parts = reading_links._context(paper_id, conn)
    if not parts:
        return None
    links = annotation_reader.saved(database, paper_id, 'reading_links')
    if (links is not None and links.get('key') == reading_links._key(parts, saved)
            and links.get('analysis_hash') == saved['source_hash']
            and links.get('document_hash') == saved['document_hash']):
        return None
    return 'paper_highlights'


def start(pane, *, force=True):
    if not pane.paper_id or pane.busy:
        return False
    owner = getattr(pane, '_annotation_owner', None)
    if owner is None or owner.database != Path(store.DB_PATH).resolve():
        pane._highlight_status('請重新開啟原論文，確認工作區與來源後再分析重點。')
        return False
    epoch = pane._annotation_epoch
    parent = pane.parent()
    fingerprint = getattr(parent, '_pdf_fingerprint', None) if parent is not None else None
    try:
        saved = annotation_reader.saved(owner.database, owner.paper_id, 'highlight_analysis')
        if saved and saved.get('document_hash') and fingerprint:
            force = force or saved['document_hash'] != fingerprint
        task = _model_task(owner.database, owner.paper_id, force)
        connections = llm.capture_connections() if task is not None else {}
        if task is not None:
            with llm.connection_scope(connections):
                available = llm.available(task=task)
            if not available:
                from paper_daily.desktop.ai_access import login

                reason = '請先在 AI 設定登入所選帳號，再分析原文重點或連結講解。'
                pane._highlight_status(reason)
                passive = getattr(pane, "_annotation_automatic", False)
                if not passive or not getattr(pane, "_annotation_login_notified", False):
                    pane._annotation_login_notified = True
                    login(pane, task, reason)
                return False
    except (OSError, ValueError, sqlite3.Error):
        pane._highlight_status('無法讀取這份已載入研究的註記狀態；請重新開啟後重試。')
        return False
    if not _current(pane, owner, epoch, fingerprint):
        return False
    pane._annotation_cancel = threading.Event()
    stopped = pane._annotation_cancel
    _controls(pane, True)
    pane._highlight_status('正在核對原文重點；標註儲存後才會連結深度講解。')
    pane.runner.activity_label = '核對原文重點與講解'

    def work(_prompt):
        try:
            result, reason = reading_annotation_jobs.prepare(
                owner.database, owner.paper_id, legacy_root=legacy_root,
                force=force, connections=connections, owner=owner,
                expected_document_hash=fingerprint, cancelled=stopped.is_set,
            )
            return json.dumps(result, ensure_ascii=False) if result is not None else None, reason
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            return None, preparation_failure(error)

    from paper_daily.config import PDF_DIR

    legacy_root = Path(PDF_DIR).resolve()

    def done(encoded):
        if not isValid(pane):
            return
        _controls(pane, False)
        if not _current(pane, owner, epoch, fingerprint):
            return
        prepared = json.loads(encoded)
        pane._load_materials()
        pane.highlights_ready.emit(owner.paper_id)
        marks = prepared.get('marks')
        if prepared.get('cancelled'):
            text = '已保留完成的原文標註；講解連結已停止。'
        elif prepared.get('explanation_pending'):
            text = '原文標註已儲存；講解連結尚未完成，可重試，不需重做已完成的標註。'
        elif marks and marks.get('unmatched'):
            text = f"已定位 {marks['mapped']}/{marks['total']} 段；未定位內容保留供核對。"
        elif marks:
            text = f"已儲存 {marks['mapped']} 段原文標註與講解連結。"
        else:
            text = '沒有可重新套用的重點；已刪除的內容不會自動恢復。'
        if task is None and not prepared.get('cancelled'):
            text = '沿用已儲存的原文標註與講解連結。 ' + text
        pane._highlight_status(text)

    def failed(reason):
        if not isValid(pane):
            return
        _controls(pane, False)
        if _current(pane, owner, epoch, fingerprint):
            pane._highlight_status(
                '工作未完成；舊結果保留，完成但過期的結果可在保留內容中審閱。 '
                + reason
            )

    pane.runner.start('', done, failed, call=work, task='paper_highlights')
    return bool(pane.runner.busy)


# What a reader can do about the refusals that have a known cause.
KNOWN_FAILURES = {
    'The displayed PDF changed before highlight analysis':
        '畫面上的 PDF 和記錄的原文版本不一致；請重新開啟這篇論文的 PDF 後再試。',
    'The loaded annotation owner belongs to another research target':
        '這份標註屬於另一篇論文或另一個工作區；請重新開啟這篇論文後再試。',
}


def preparation_failure(error):
    """Say why preparation stopped. Only the type name used to reach the screen, which
    told the reader nothing; the code location goes to the local diagnostics log."""
    from paper_daily import diagnostics

    diagnostics.record_exception(type(error), error.__traceback__, phase='annotation')
    detail = ' '.join(str(error).split())[:200]
    known = KNOWN_FAILURES.get(detail)
    if known:
        return known
    kind = type(error).__name__
    return f'原因：{detail}（{kind}）' if detail else f'原因不明（{kind}）'


def cancel(pane):
    stopped = getattr(pane, '_annotation_cancel', None)
    if stopped is not None and pane._highlights_busy:
        stopped.set()
        _controls(pane, True)
        pane._highlight_status('已要求停止；目前呼叫完成後保留結果，不開始下一個階段。')
