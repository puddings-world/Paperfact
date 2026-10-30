"""Small actual-reader bridge; standalone pdf_highlights compatibility stays separate."""

import sqlite3
from pathlib import Path

from shiboken6 import isValid

from paper_daily import manual_highlight_ops as operations


def capture(reader, paper, fallback_database):
    """Mark this as an actual loaded reader even when owner capture fails."""
    reader._highlight_owner = None
    reader._highlight_view = None
    resolver = getattr(paper, "_document_reader", None)
    database = resolver.db_path if resolver is not None else fallback_database
    try:
        reader._highlight_owner = operations.capture_owner(database, paper.id)
    except (OSError, ValueError, sqlite3.Error) as exc:
        reader.pdf_note.setText(f"螢光標記尚不可編輯：{exc}")


def load(reader, path, fingerprint):
    reader._highlight_view = None
    view = operations.load(
        reader._highlight_owner, path, fingerprint,
        document=getattr(reader, "_active_document", None),
    )
    reader._highlight_view = view
    return view.marks


def apply(reader, *, erase=False):
    """Run an immediate explicit edit; completion never repaints a replacement view."""
    from paper_daily import store
    from paper_daily.desktop.document_flow import loaded_document_valid

    paper = reader.paper
    view = getattr(reader, "_highlight_view", None)
    selection = getattr(reader.pdf, "selection", None)
    if not paper or not selection:
        return
    try:
        if (view is None or view.owner is not reader._highlight_owner
                or Path(store.DB_PATH).resolve() != view.owner.database
                or view.owner.paper_id != paper.id
                or view.path != Path(paper.pdf_path).resolve()
                or view.fingerprint != reader._pdf_fingerprint
                or not loaded_document_valid(reader)):
            raise ValueError("請重新開啟這篇論文，確認原文版本後再標註。")
        if erase:
            ids = selection.selected_highlights()
            if not ids:
                return
            operations.remove(view, ids)
        else:
            anchor = selection.anchor()
            if not anchor:
                return
            operations.add(view, anchor, selection.selected_text())
    except (OSError, ValueError, sqlite3.Error) as exc:
        if isValid(reader) and reader.paper is paper and reader._highlight_view is view:
            reader.pdf_note.setText(f"螢光標記未保存，原選取保留：{exc}")
        return
    if (not isValid(reader) or reader.paper is not paper or reader._highlight_view is not view
            or Path(store.DB_PATH).resolve() != view.owner.database):
        return
    selection.clear()
    reader._load_highlights(view.path, fingerprint=view.fingerprint)
    reader._refresh_highlight_materials()
    reader.pdf_note.setText("已移除選取範圍的螢光標記。" if erase
                           else "螢光標記已保存並同步素材。")
