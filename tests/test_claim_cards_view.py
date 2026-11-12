"""The 筆記 tab offers 核心論點 once there are highlights to pick from, and shows
the cards as AI 論點 with their link back to the sentence."""

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_pdf_highlights import reader as _reader  # noqa: E402
from test_reader_prepare import _settle_owned  # noqa: E402
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
            pid,
            claims.body("We introduce WetCat.", "WetCat 是第一個濕實驗室資料集", "因為…"),
            claims.KIND,
            2,
            json.dumps({"p0": 1, "o0": 3, "p1": 1, "o1": 9}),
        )
        return 1, ""

    monkeypatch.setattr(claims, "write", write)
    page._load_notes()
    assert not page.claims_btn.isHidden() and page.claims_btn.text() == "AI 整理核心論點"
    page.claims_btn.click()
    from test_reader_ai_scope import _until

    _until(app, lambda: not page._claims_work.busy)
    _settle_owned(page.preparation, app)
    app.processEvents()
    assert asked == [("a", False)]
    shown = page.note_log._body
    assert "AI 論點" in shown and "WetCat 是第一個濕實驗室資料集" in shown
    assert "jump:" in shown and "第 2 頁" in shown
    assert page.note_status.text() == "已整理 1 張核心論點卡"
    # Once cards exist, the button remakes them.
    assert page.claims_btn.text() == "AI 重新整理核心論點"


def test_claim_job_is_single_and_switching_or_closing_keeps_the_original_target(
    window, monkeypatch
):
    import threading

    from test_reader_ai_scope import _until

    win, app = window
    monkeypatch.setattr(ai_access, "_bridge", None)
    monkeypatch.setattr(claims, "highlights", lambda conn, pid: MARKS)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def write(pid, force=False):
        calls.append(pid)
        entered.set()
        assert release.wait(10)
        win.data.add_note(pid, "Claim for original A", claims.KIND)
        return 1, ""

    monkeypatch.setattr(claims, "write", write)
    win.show()
    win.open_paper("a")
    page = win.reader_page
    page._make_claims()
    assert entered.wait(5)
    try:
        page._make_claims()
        assert calls == ["a"]
        win.open_paper("b")
        _settle_owned(page.preparation, app)
        _until(app, lambda: not page.reading_positions.busy)
        assert not win.close()
    finally:
        release.set()
        _until(app, lambda: not page._claims_work.busy)
    assert [r["body"] for r in win.data.notes("a")] == ["Claim for original A"]
    assert win.data.notes("b") == []
    assert "Claim for original A" not in page.note_log._body


def test_claim_failure_leaves_notes_and_allows_explicit_retry(window, monkeypatch):
    from test_reader_ai_scope import _until

    win, app = window
    monkeypatch.setattr(ai_access, "_bridge", None)
    monkeypatch.setattr(claims, "highlights", lambda conn, pid: MARKS)
    win.open_paper("a")
    win.data.add_note("a", "My existing note")
    page = win.reader_page
    outcomes = iter([(0, "fixture unavailable"), (1, "")])
    monkeypatch.setattr(claims, "write", lambda *a, **k: next(outcomes))
    page._make_claims()
    _until(app, lambda: not page._claims_work.busy)
    assert page.claims_btn.isEnabled() and "fixture unavailable" in page.note_status.text()
    assert [r["body"] for r in win.data.notes("a")] == ["My existing note"]
    page._make_claims()
    _until(app, lambda: not page._claims_work.busy)
    assert page.note_status.text() == "已整理 1 張核心論點卡"


def test_claim_launch_failure_releases_button_and_preserves_notes(window, monkeypatch):
    win, _app = window
    monkeypatch.setattr(ai_access, "_bridge", None)
    monkeypatch.setattr(claims, "highlights", lambda conn, pid: MARKS)
    win.open_paper("a")
    win.data.add_note("a", "Existing note")
    page = win.reader_page

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture launch failure")

    monkeypatch.setattr(page._claims_work, "start", unavailable)
    page._make_claims()
    assert page._claims_for is None and page.claims_btn.isEnabled()
    assert "請重試" in page.note_status.text()
    assert [row["body"] for row in win.data.notes("a")] == ["Existing note"]
