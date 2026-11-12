"""Work started for one paper or selection lands there, never on what is open now."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_pdf_highlights import reader as _reader  # noqa: E402
from test_reader_prepare import _settle_owned  # noqa: E402
from test_reader_prepare import window as _window  # noqa: E402

from paper_daily import llm, store  # noqa: E402
from paper_daily.desktop import ai_access  # noqa: E402

raw_reader = _reader
window = _window


@pytest.fixture
def reader(raw_reader, tmp_path, monkeypatch):
    """Use a real stored paper, resolved original and completed native load."""
    from PySide6.QtCore import QTimer

    from paper_daily import config
    from paper_daily.desktop import highlight_actions
    from paper_daily.document_reader import from_workspace
    from paper_daily.fetch import _safe_name

    widget, app, path = raw_reader
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "translation-settings.json")
    monkeypatch.setattr(config, "PDF_DIR", path.parent)
    llm.save_settings(backend="openai", model="fixture-model", api_key="fixture-key")
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(
            id=widget.paper.id, title="Test paper", venue="Fixture", year=2026, source="fixture"
        )])
    original = path.parent / (_safe_name(widget.paper.id) + ".pdf")
    import pymupdf

    with pymupdf.open(path) as document:
        for page in document:
            page.insert_text((40, 140),
                             "The original experiment compares independent observations fairly.")
        document.save(original)
    resolver = from_workspace(store.DB_PATH, legacy_root=path.parent)
    document = resolver.resolve(widget.paper.id)
    assert document.available
    widget.paper.pdf_path = original
    widget.paper._document_reader = resolver
    widget.paper._document_status = document
    widget.paper._loaded_document = document
    widget._qa_view_database = store.DB_PATH.resolve()
    highlight_actions.capture(widget, widget.paper, store.DB_PATH)
    widget._active_document = document
    assert widget.pdf.load(original)
    widget._load_highlights(original, fingerprint=document.sha256)
    admitted = []
    QTimer.singleShot(0, widget, lambda: admitted.append(True))
    _until(app, lambda: admitted and widget.pdf.position_source_version() is not None
           and not widget.reading_positions.busy and not widget.preparation.busy)
    widget.presentation_pane.load(widget.paper.id, "Test paper")
    yield widget, app, original
    widget.preparation.dispose()
    _settle_owned(widget.preparation, app)


def _until(app, predicate):
    import time

    end = time.monotonic() + 10
    while not predicate() and time.monotonic() < end:
        app.processEvents()
    assert predicate(), "Native fixture operation did not deliver"


@pytest.fixture
def asking(window, monkeypatch):
    import threading

    win, app = window
    monkeypatch.setattr(ai_access, "_bridge", None)
    monkeypatch.setattr(llm, "available", lambda **kw: True)
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    llm.save_settings(backend="openai", model="fixture-model", api_key="fixture-key")
    calls, pending = [], []
    entered = threading.Event()
    runner = win.reader_page.runner
    original = runner.start

    def complete(prompt, **_kwargs):
        assert threading.current_thread() is not threading.main_thread()
        gate, output = threading.Event(), {}
        pending.append((gate, output))

        def deliver(value, failed=False):
            output.update(answer=None if failed else value, reason=value if failed else "ok")
            gate.set()
            _until(app, lambda: not runner.busy)

        calls.append((prompt, deliver, lambda reason: deliver(reason, failed=True)))
        entered.set()
        assert gate.wait(10)
        return output.get("answer"), output.get("reason", "Fixture cancelled")

    def start(*args, **kwargs):
        entered.clear()
        original(*args, **kwargs)
        assert entered.wait(5), "Real ChatJob did not reach the fixture provider"

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(runner, "start", start)
    yield win, app, calls
    for gate, output in pending:
        if not gate.is_set():
            output.update(answer=None, reason="Fixture cancelled")
            gate.set()
    _until(app, lambda: not runner.busy)


def _bodies(win, paper_id):
    return [(r["role"], r["body"]) for r in win.data.chat(paper_id)]


def _chat(win, app):
    _settle_owned(win.reader_page.preparation, app)
    return win.reader_page.chat_view._body


def _select_passage(reader, text):
    selection = reader.pdf.selection
    assert selection.focus(selection.find(0, text))
    assert selection.selected_text() == text
    reader._ask_selection(selection.selected_text())


def _prepared_annotation(widget, monkeypatch):
    """Seed genuine source-bound output through the maintained producer, not raw rows."""
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import reading_annotation_jobs
    from paper_daily.ai_types import Completion

    with monkeypatch.context() as fake:
        fake.setattr(llm, "complete_result", lambda *_, **__: Completion(
            '{"items":[{"id":0,"kind":"evidence","reason":"Fixture source evidence."}]}'
        ))
        with ThreadPoolExecutor(max_workers=1) as worker:
            result, reason = worker.submit(
                reading_annotation_jobs.prepare,
                store.DB_PATH, widget.paper.id, legacy_root=widget.paper.pdf_path.parent,
                force=True, connections=llm.capture_connections(), owner=widget._highlight_owner,
                expected_document_hash=widget._pdf_fingerprint,
            ).result(timeout=10)
    assert reason == "ok" and result is not None
    assert result["marks"]["mapped"] == 1


def _settle_annotation(widget, app):
    _until(app, lambda: not widget.presentation_pane.busy)


def _open_annotation_source(widget, app, pid, original):
    """An actual new paper/source/native epoch, even when fixture PDFs share bytes."""
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from types import SimpleNamespace

    from PySide6.QtCore import QTimer

    from paper_daily import audit_inputs
    from paper_daily.desktop import highlight_actions
    from paper_daily.document_reader import from_workspace
    from paper_daily.fetch import _safe_name

    with store.connect() as conn:
        store.upsert_papers(conn, [dict(
            id=pid, title=f"Native fixture {pid}", venue="Fixture", year=2026, source="fixture"
        )])
    path = original.parent / (_safe_name(pid) + ".pdf")
    if path != original:
        path.write_bytes(original.read_bytes())
    resolver = from_workspace(store.DB_PATH, legacy_root=path.parent)
    document = resolver.resolve(pid)
    assert document.available
    widget.paper = SimpleNamespace(
        id=pid, pdf_path=path, _document_reader=resolver, _document_status=document,
        _loaded_document=document,
    )
    widget._qa_epoch += 1
    highlight_actions.capture(widget, widget.paper, store.DB_PATH)
    widget._active_document = document
    assert widget.pdf.load(path)
    widget._load_highlights(path, fingerprint=document.sha256)
    widget.presentation_pane.load(pid, f"Native fixture {pid}")
    actual, expected = widget.presentation_pane._annotation_owner, widget._highlight_owner
    assert actual is not None
    assert (actual.database, actual.paper_id, actual._json) == (
        expected.database, expected.paper_id, expected._json
    )

    def check_owners():
        with closing(audit_inputs._connect(expected.database)) as conn:
            actual.check(conn)
            expected.check(conn)

    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(check_owners).result(timeout=10)
    admitted = []
    QTimer.singleShot(0, widget, lambda: admitted.append(True))
    _until(app, lambda: admitted and widget.pdf.position_source_version() is not None
           and not widget.reading_positions.busy and not widget.preparation.busy)


def test_an_answer_is_saved_to_the_paper_it_was_asked_about(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("What does A assume?")
    win.open_paper("b")
    calls[0][1]("Answer about A")
    assert _bodies(win, "a") == [("user", "What does A assume?"), ("assistant", "Answer about A")]
    assert _bodies(win, "b") == []
    assert "Answer about A" not in _chat(win, app)
    win.open_paper("a")
    assert "Answer about A" in _chat(win, app)


def test_a_failed_question_is_retryable_and_left_out_of_later_prompts(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Lost question")
    assert "思考中" in _chat(win, app)
    calls[0][2]("timed out after 900s")
    shown = _chat(win, app)
    assert "思考中" not in shown and "未完成，可重試" in shown
    assert "timed out" in reader.ask_status.text()
    reader._ask("Second question")
    assert "Lost question" not in calls[1][0]
    calls[1][1]("Second answer")
    # A concise answer carries the previous exchange only when asked to.
    reader.follow_btn.setChecked(True)
    reader._ask("Third question")
    assert "Second question" in calls[2][0] and "Lost question" not in calls[2][0]


def test_retrying_an_unanswered_question_replaces_it_when_sent(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Lost question")
    calls[0][2]("unavailable")
    question_id = win.data.chat("a")[0]["id"]
    reader._retry_question(question_id)
    assert reader.ask_box.text() == "Lost question" and not calls[1:]
    reader._ask_from_box(reader.ask_box.text())
    assert _bodies(win, "a") == [("user", "Lost question")]
    assert win.data.chat("a")[0]["id"] != question_id


def test_a_failure_for_a_paper_left_behind_does_not_touch_the_open_one(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Question on A")
    win.open_paper("b")
    calls[0][2]("HTTP 503: AI request rejected")
    assert "先前論文" in reader.ask_status.text()
    assert reader.ask_btn.isEnabled()
    assert "未完成" not in _chat(win, app)


def test_page_and_passage_context_do_not_follow_the_reader_to_another_paper(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask_this_page()
    _select_passage(reader, "A passage that only paper A contains")
    assert not reader.passage_chip.isHidden()
    win.open_paper("b")
    assert reader.passage_chip.isHidden()
    reader._ask_from_box("What is this?")
    prompt = calls[0][0]
    assert "PAGE TEXT FROM PAPER A" not in prompt
    assert "only paper A contains" not in prompt
    assert _bodies(win, "b") == [("user", "What is this?")]


def test_a_page_context_is_used_only_for_its_own_paper(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask_this_page()
    win.open_paper("b")
    reader._ask("Explain")
    assert "PAGE TEXT FROM PAPER A" not in calls[0][0]


def _translation_calls(widget, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import translate

    shown, started = [], []
    result, real_show = {}, widget.pdf.selection.show_result

    def show(title, text, **kwargs):
        shown.append((title, text))
        return real_show(title, text, **kwargs)

    monkeypatch.setattr(widget.pdf.selection, "show_result", show)
    monkeypatch.setattr(translate, "machine", lambda *_: (result["answer"], result["reason"]))
    monkeypatch.setattr(llm, "complete", lambda *_, **__: (result["answer"], result["reason"]))

    def start(prompt, done, failed, **kwargs):
        def deliver(value, failure=False):
            result.update(answer=None if failure else value, reason=value if failure else "ok")
            with ThreadPoolExecutor(max_workers=1) as worker:
                answer, reason = worker.submit(kwargs["call"], prompt).result(timeout=5)
            (done if answer is not None else failed)(answer if answer is not None else reason)

        started.append((deliver, lambda reason: deliver(reason, failure=True)))

    for runner in (widget.translate_runner, widget.refine_runner):
        monkeypatch.setattr(runner, "start", start)
    return shown, started


def test_a_translation_for_an_abandoned_selection_is_not_drawn(reader, monkeypatch):
    widget, app, _path = reader
    selection = widget.pdf.selection
    shown, started = _translation_calls(widget, monkeypatch)
    selection.focus(selection.find(0, "Alpha beta"))
    widget._translate_selection("Alpha beta")
    selection.focus(selection.find(1, "gamma evidence"))
    started[0][0]("舊的譯文")
    assert ("Google 翻譯", "舊的譯文") not in shown
    started[0][1]("Google down")
    assert len(started) == 1


def test_a_translation_lands_when_the_selection_is_unchanged(reader, monkeypatch):
    widget, app, _path = reader
    selection = widget.pdf.selection
    shown, started = _translation_calls(widget, monkeypatch)
    selection.focus(selection.find(0, "Alpha beta"))
    widget._translate_selection("Alpha beta")
    started[0][1]("Google down")
    started[1][0]("AI 譯文")
    assert shown[-1] == ("AI 精譯", "AI 譯文")


def test_a_refined_translation_is_dropped_after_switching_paper(reader, monkeypatch):
    from types import SimpleNamespace

    widget, app, path = reader
    selection = widget.pdf.selection
    shown, started = _translation_calls(widget, monkeypatch)
    selection.focus(selection.find(0, "Alpha beta"))
    widget._translate_with_model("Alpha beta")
    widget.paper = SimpleNamespace(id="another:paper", pdf_path=path)
    started[0][0]("AI 譯文")
    assert ("AI 精譯", "AI 譯文") not in shown


def test_prepared_highlights_are_not_analysed_again_on_open(reader, monkeypatch):
    widget, app, _path = reader
    _prepared_annotation(widget, monkeypatch)
    monkeypatch.setattr(llm, "complete_result",
                        lambda *a, **kw: pytest.fail("prepared paper re-analysed"))
    widget._prepare_reading_highlights()
    _settle_annotation(widget, app)


def test_cached_analysis_does_not_claim_the_ai_is_reading_the_paper(reader, monkeypatch):
    widget, app, _path = reader
    pane = widget.presentation_pane
    _prepared_annotation(widget, monkeypatch)
    monkeypatch.setattr(llm, "complete_result",
                        lambda *a, **kw: pytest.fail("cached paper re-analysed"))
    widget._prepare_reading_highlights()
    _settle_annotation(widget, app)
    assert "AI 正在讀取原文" not in widget.highlight_status.text()
    assert "沿用" in widget.highlight_status.text()
    pane._highlights_busy = False


def test_missing_ai_prompts_for_login_once_per_session(reader, monkeypatch):
    widget, app, path = reader
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    prompts = []
    monkeypatch.setattr(ai_access, "login", lambda *a: prompts.append(a))
    for pid in ("test:paper", "test:other", "test:third"):
        _open_annotation_source(widget, app, pid, path)
        widget._prepare_reading_highlights()
        widget._prepare_reading_highlights()
    assert len(prompts) == 1
    assert "AI 設定" in widget.highlight_status.text()
    widget.prepare_highlights.click()
    assert len(prompts) == 2
