"""The 筆記 tab offers 核心論點 once there are highlights to pick from, and shows
the cards as AI 論點 with their link back to the sentence."""

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_pdf_highlights import reader as _reader  # noqa: E402
from test_reader_prepare import _settle  # noqa: E402
from test_reader_prepare import window as _window  # noqa: E402

from paper_daily import claims  # noqa: E402
from paper_daily.desktop import ai_access  # noqa: E402

reader = _reader
window = _window
MARKS = [{"quote": f"Sentence {i}.", "reason": "r", "anchor": "{}", "kind": ""} for i in range(3)]


def test_claim_cards_are_made_from_the_notes_tab_and_link_back(window, monkeypatch):
    win, app = window
    monkeypatch.setattr(ai_access, "_bridge", None)
    page = win.reader_page
    monkeypatch.setattr(claims, "highlights", lambda conn, pid: [])
    win.open_paper("a")
    page._load_notes()
    assert page.claims_btn.isHidden()

    monkeypatch.setattr(claims, "highlights", lambda conn, pid: MARKS)
    asked = []

    def write(pid, force=False):
        asked.append((pid, force))
        win.data.add_note(
            pid, claims.body("We introduce WetCat.", "WetCat 是第一個濕實驗室資料集", "因為…"),
            claims.KIND, 2, json.dumps({"p0": 1, "o0": 3, "p1": 1, "o1": 9}),
        )
        return 1, ""

    monkeypatch.setattr(claims, "write", write)
    page._load_notes()
    assert not page.claims_btn.isHidden() and page.claims_btn.text() == "AI 整理核心論點"
    page.claims_btn.click()
    page._claims_work.wait()
    _settle(page.prepare, app)
    app.processEvents()
    assert asked == [("a", False)]
    shown = page.note_log._body
    assert "AI 論點" in shown and "WetCat 是第一個濕實驗室資料集" in shown
    assert "jump:" in shown and "第 2 頁" in shown
    assert page.note_status.text() == "已整理 1 張核心論點卡"
    # Once cards exist, the button remakes them.
    assert page.claims_btn.text() == "AI 重新整理核心論點"
