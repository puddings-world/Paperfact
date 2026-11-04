"""Switching papers replaces everything the reader says about the paper; nothing
from the previous one stays on screen while the next one loads."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_window_fits import reader as reader  # noqa: E402,F401

from paper_daily import store  # noqa: E402


def test_the_previous_papers_status_lines_are_gone_after_a_switch(reader):
    window, app = reader
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="q", title="Another paper", venue="ICLR", year=2026, source="test")]
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES ('l','q',1,'now')"
        )
    window.reload()
    page = window.reader_page
    page.highlight_status.setText("原文重點：AI 12 段（綠色） · 手動 3 段（黃色）")
    page.ask_status.setText("關鍵筆記已存 — 在「筆記」分頁，標著 ★。")
    window.open_paper("q")
    for _ in range(5):
        app.processEvents()
    assert page.paper.id == "q"
    assert "AI 12 段" not in page.highlight_status.text()
    assert page.ask_status.text() == ""
