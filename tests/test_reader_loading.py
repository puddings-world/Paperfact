import pymupdf

from paper_daily import figures, paper_highlights


def test_original_text_cache_is_invalidated_when_pdf_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_highlights, "PDF_DIR", tmp_path)
    path = tmp_path / "paper.pdf"

    def write(text):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((40, 60), text)
            doc.save(path)

    write("First original evidence.")
    original_open = pymupdf.open
    reads = []

    def tracked(*args, **kwargs):
        if args:
            reads.append(args[0])
        return original_open(*args, **kwargs)

    monkeypatch.setattr(pymupdf, "open", tracked)
    first = paper_highlights.read_original("paper")
    first[0]["text"] = "caller edit"
    assert "First original" in paper_highlights.read_original("paper")[0]["text"]
    assert len(reads) == 1
    write("Second original evidence with changed length.")
    assert "Second original" in paper_highlights.read_original("paper")[0]["text"]
    assert len(reads) == 2


def test_reader_cached_figures_do_not_extract_pdf_on_ui_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(figures, "FIG_DIR", tmp_path)
    monkeypatch.setattr(figures, "ensure_dirs", lambda: None)

    def fail(*args, **kwargs):
        raise AssertionError("must not open PDF for a cached-only lookup")

    monkeypatch.setattr(pymupdf, "open", fail)
    assert figures.extract("paper", tmp_path / "paper.pdf", cached_only=True) == []


def test_switching_papers_during_extraction_finishes_the_latest_paper(tmp_path, monkeypatch):
    import os
    import threading

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop import figure_pane
    from paper_daily.desktop.main import LIGHT

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"fixture")
    started, release = threading.Event(), threading.Event()
    calls = []

    def extract(pid, pdf):
        calls.append(pid)
        if pid == "first":
            started.set()
            release.wait(2)
        return [figures.Figure(pid, "Figure 1", "Caption", 1, tmp_path / "absent.png")]

    monkeypatch.setattr(figure_pane, "extract", extract)
    widget = figure_pane.FigurePane(LIGHT)
    ready = []
    widget.ready.connect(ready.append)
    try:
        widget.load("first", path, True)
        assert started.wait(1)
        widget.load("second", path, True)
        release.set()
        for _ in range(200):
            QTest.qWait(10)
            if ready == ["second"]:
                break
        assert ready == ["second"] and calls == ["first", "second"]
    finally:
        release.set()
        widget._requested = None
        widget._thread.quit()
        widget._thread.wait(3000)
        widget.deleteLater()
        app.processEvents()


def test_the_figures_tab_lists_every_figure_and_jumps_to_the_one_picked(tmp_path):
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop import figure_pane
    from paper_daily.desktop.main import LIGHT

    app = QApplication.instance() or QApplication([])
    found = [
        figures.Figure("p", label, "A caption long enough to take a line. " * 3, 1,
                       tmp_path / "absent.png", kind)
        for label, kind in [("Figure 1", "figure"), ("Figure 2", "figure"),
                            ("Table 1", "table"), ("Figure 3", "figure"),
                            ("Figure 4", "figure"), ("Figure 5", "figure")]
    ]
    widget = figure_pane.FigurePane(LIGHT)
    widget.resize(420, 260)
    widget.show()
    widget._paper_id = "p"
    widget._show("p", found)
    app.processEvents()
    toc = widget._toc
    assert not toc.isHidden()
    for i, fig in enumerate(found):
        assert f"href='{i}'" in toc.text() and fig.label in toc.text()
    # It stays put above the list rather than scrolling away with it.
    assert widget.viewportMargins().top() == toc.height() > 0
    toc.linkActivated.emit("3")
    bar = widget.verticalScrollBar()
    assert bar.value() == min(widget._entries[3].y(), bar.maximum()) > 0
    widget._clear()
    assert toc.isHidden() and widget.viewportMargins().top() == 0
    widget.deleteLater()
    app.processEvents()


def test_many_figures_are_added_a_few_per_turn_and_all_arrive(tmp_path, monkeypatch):
    # Thirty figures made at once held the window still for over half a second
    # after the 圖表 tab was opened.
    import time

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop import figure_pane
    from paper_daily.desktop.main import LIGHT

    app = QApplication.instance() or QApplication([])
    made = figure_pane.FigurePane._entry

    def slow(self, fig, image=None):
        time.sleep(0.005)
        return made(self, fig, image)

    monkeypatch.setattr(figure_pane.FigurePane, "_entry", slow)
    found = [
        figures.Figure("p", f"Figure {i}", "Caption.", 1, tmp_path / "absent.png")
        for i in range(30)
    ]
    widget = figure_pane.FigurePane(LIGHT)
    ready = []
    widget.ready.connect(ready.append)
    widget._paper_id = "p"
    started = time.perf_counter()
    widget._show("p", found)
    assert time.perf_counter() - started < 0.1
    assert 0 < len(widget._entries) < len(found) and ready == []
    # The contents line names every figure from the start, and a jump to one not
    # yet made makes the rest first.
    assert "Figure 29" in widget._toc.text()
    widget.scroll_to(29)
    assert len(widget._entries) == len(found)
    for _ in range(100):
        if ready:
            break
        QTest.qWait(10)
    assert ready == ["p"]
    widget.deleteLater()
    app.processEvents()


def test_figures_ask_for_the_dive_again_only_when_extracted_just_now(tmp_path, monkeypatch):
    # The close reading places figures, so a dive rendered before they existed is
    # rendered again; one rendered from the cache already had them, and redoing it
    # froze the 圖表 tab.
    from paper_daily.desktop import figure_pane

    monkeypatch.setattr(figures, "FIG_DIR", tmp_path)
    found = [figures.Figure("p", "Figure 1", "Caption.", 1, tmp_path / "absent.png")]
    monkeypatch.setattr(figure_pane, "extract", lambda pid, pdf: found)
    results = []
    worker = figure_pane._ExtractWorker("p", tmp_path / "paper.pdf")
    worker.finished.connect(lambda *args: results.append(args[3]))
    worker.run()
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "index.json").write_text("[]")
    worker.run()
    assert results == [True, False]
