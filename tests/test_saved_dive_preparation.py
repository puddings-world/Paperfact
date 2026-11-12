"""Saved deep-reading preparation on the existing owned reader lane."""

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QImage, QTextDocument
from test_progressive_figures import until
from test_reader_preparation import held, settle
from test_reader_preparation import legacy as _legacy
from test_reader_preparation import reader as _reader
from test_reader_preparation import ready as _ready

from paper_daily import figures, manual_highlight_ops, store
from paper_daily import reader_saved_inputs as saved
from paper_daily.desktop import main, reading

legacy = _legacy
reader = _reader
ready = _ready


def save_dive(text="## Result\nSAVED_RESEARCH_EXPLANATION"):
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO dives(paper_id,body,spec,written_at) VALUES(?,?,?,?) "
            "ON CONFLICT(paper_id) DO UPDATE SET body=excluded.body",
            ("local-paper", text, "fixture", "2026-10-31T00:00:00+00:00"),
        )


def test_saved_dive_render_yields_and_never_typesets_on_gui(ready, monkeypatch):
    app, _window, view = ready
    save_dive()
    view.paper = SimpleNamespace(id="local-paper", abstract="", has_pdf=False)
    view.ask_box.setText("Unsent question")
    view.note_edit.setPlainText("Unsent note")
    original = reading.render
    calls = []

    def render(*args, **kwargs):
        calls.append(threading.current_thread() is threading.main_thread())
        assert not calls[-1], "Saved deep-reading typesetting blocked the GUI"
        return original(*args, **kwargs)

    monkeypatch.setattr(reading, "render", render)
    main.ReaderPage._load_dive(view)
    settle(app, lambda: not view.preparation.busy)
    assert "SAVED_RESEARCH_EXPLANATION" in view.dive_view._body
    assert calls and not any(calls)
    assert view.ask_box.text() == "Unsent question"
    assert view.note_edit.toPlainText() == "Unsent note"
    with store.connect() as conn:
        assert (
            conn.execute("SELECT body FROM dives")
            .fetchone()[0]
            .endswith("SAVED_RESEARCH_EXPLANATION")
        )


@pytest.fixture
def cached(ready, tmp_path, monkeypatch):
    app, window, view = ready
    root = tmp_path / "figures"
    folder = root / "local-paper"
    folder.mkdir(parents=True)
    monkeypatch.setattr(figures, "FIG_DIR", root)
    monkeypatch.setattr(figures, "MIN_PNG_BYTES", 0)
    save_dive()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,spec,written_at) VALUES(?,?,?,?)",
            (
                "local-paper",
                "## Method\n[[Figure 1]]\nSaved close reading.",
                "fixture",
                "2026-10-31T00:00:00+00:00",
            ),
        )
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(0x123456)
    path = folder / "figure.png"
    assert image.save(str(path))
    item = dict(
        label="Figure 1", caption="A complete cached caption", page=3, file=path.name, kind="figure"
    )
    index = folder / "index.json"
    index.write_text(json.dumps([item]), encoding="utf-8")
    view.paper = SimpleNamespace(
        id="local-paper", abstract="", has_pdf=True, pdf_path=tmp_path / "pdf/local-paper.pdf"
    )
    return SimpleNamespace(
        app=app,
        window=window,
        view=view,
        root=root,
        folder=folder,
        path=path,
        index=index,
        item=item,
    )


def open_dive(w):
    main.ReaderPage._load_dive(w.view)
    settle(w.app, lambda: not w.view.preparation.busy)


def test_cached_dive_is_readable_before_visiting_figures_and_never_grants_source_authority(cached):
    w = cached
    assert w.view.figure_pane._frame is None
    original = w.path.read_bytes()
    open_dive(w)
    page = w.view.dive_view._body
    assert "SAVED_RESEARCH_EXPLANATION" in page and "Saved close reading" in page
    assert "data:image/png;base64," in page and "A complete cached caption" in page
    assert "Unverified cached figure" in page
    assert "original-source provenance not verified" in page
    assert "(p3)" not in page and "paperfact-figure:" not in page
    assert w.view.figure_pane._frame is None and w.path.read_bytes() == original
    assert not w.view.figure_pane.busy
    # The actual plain Qt reader must display the immutable inline image, not
    # merely retain an <img> string that its resource loader cannot open.
    import re

    address = re.search(r'src="(data:image/png;base64,[^"]+)"', page).group(1)
    displayed = w.view.dive_view.view.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl(address)
    )
    assert isinstance(displayed, (QImage,)) or hasattr(displayed, "isNull")
    assert not displayed.isNull()


@pytest.mark.parametrize(
    "problem", ["missing", "malformed", "bounds", "binding", "assets", "bytes"]
)
def test_invalid_cache_keeps_saved_text_and_reports_coverage(cached, problem):
    w = cached
    if problem == "missing":
        w.index.unlink()
    elif problem == "malformed":
        w.index.write_text('{"broken":', encoding="utf-8")
    elif problem == "bounds":
        w.index.write_bytes(b" " * (saved.MAX_PREVIEW_INDEX + 1))
    elif problem == "binding":
        w.item["cache_key"] = "documents/foreign/cache"
        w.index.write_text(json.dumps([w.item]), encoding="utf-8")
    elif problem == "assets":
        w.index.write_text(
            json.dumps(
                [
                    {**w.item, "file": f"image-{index}.png"}
                    for index in range(saved.MAX_PREVIEW_ASSETS + 1)
                ]
            ),
            encoding="utf-8",
        )
    else:
        with w.path.open("wb") as stream:
            stream.truncate(saved.MAX_PREVIEW_BYTES + 1)
    open_dive(w)
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body
    assert "Cached figures" in w.view.dive_view._body
    assert "data:image/png" not in w.view.dive_view._body
    assert w.view.figure_pane._frame is None


def native(w):
    from test_document_derivatives import pdf

    from paper_daily.document_reader import DocumentReader

    path = w.view.paper.pdf_path
    path.parent.mkdir()
    path.write_bytes(pdf("Actual loaded original A"))
    document = DocumentReader(store.DB_PATH, projection_root=None, legacy_root=path.parent).resolve(
        "local-paper"
    )
    w.view._active_document = document
    w.view._highlight_view = manual_highlight_ops.load(
        w.view._highlight_owner, path, document.sha256, document=document
    )
    w.view._pdf_fingerprint = document.sha256
    assert w.view.pdf.load(path)
    settle(w.app, lambda: w.view.pdf.position_source_version() is not None)
    # Complete native setup (including the queued read-only page-record capture)
    # before this fixture starts the deliberately pending saved-reading job.
    admitted = []
    QTimer.singleShot(0, w.view, lambda: admitted.append(True))
    until(
        w.app,
        lambda: admitted and not w.view.reading_positions.busy and not w.view.preparation.busy,
    )
    w.item["document_hash"] = document.sha256
    w.item["asset_sha256"] = hashlib.sha256(w.path.read_bytes()).hexdigest()
    w.index.write_text(json.dumps([w.item]), encoding="utf-8")
    return document


def test_known_cached_B_is_rejected_while_native_A_is_loaded(cached):
    w = cached
    document = native(w)
    w.item["document_hash"] = "b" * 64
    w.index.write_text(json.dumps([w.item]), encoding="utf-8")
    open_dive(w)
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body
    assert "data:image/png" not in w.view.dive_view._body
    assert "Cached figures could not be checked" in w.view.dive_view._body
    assert w.view._active_document is document
    assert w.view.pdf.position_identity()[1] == document.path


@pytest.mark.parametrize("changed", ["index", "png"])
def test_queued_cache_change_preserves_prior_accepted_content_until_explicit_retry(cached, changed):
    w = cached
    open_dive(w)
    prior = w.view.dive_view._body
    save_dive("## Result\nNEW_SAVED_EXPLANATION")
    main.ReaderPage._load_dive(w.view)
    assert w.view.preparation._thread.wait(10000)
    assert w.view.preparation.busy
    if changed == "index":
        w.item["caption"] = "New explicit caption"
        w.index.write_text(json.dumps([w.item]), encoding="utf-8")
    else:
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(0xABCDEF)
        assert image.save(str(w.path))
    settle(w.app, lambda: not w.view.preparation.busy)
    assert w.view.dive_view._body == prior
    assert "reopen" in w.view.ask_status.text()
    open_dive(w)
    assert "NEW_SAVED_EXPLANATION" in w.view.dive_view._body
    assert "data:image/png" in w.view.dive_view._body


def test_held_preview_keeps_gui_heartbeat_and_all_bytes_sql_and_markdown_off_gui(
    cached, monkeypatch
):
    w = cached
    entered, release = threading.Event(), threading.Event()
    original = saved.read_preview
    calls, beats = [], []
    connect = saved._connect
    digest = hashlib.file_digest

    def sql(*args):
        assert threading.current_thread() is not threading.main_thread(), "GUI SQL"
        return connect(*args)

    def hashed(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread(), "GUI hash"
        return digest(*args, **kwargs)

    def preview(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(saved, "_connect", sql)
    monkeypatch.setattr(hashlib, "file_digest", hashed)
    monkeypatch.setattr(saved, "read_preview", preview)
    w.view.ask_box.setText("Keep unsent question")
    w.view.note_edit.setPlainText("Keep unsent note")
    main.ReaderPage._load_dive(w.view)
    assert entered.wait(2)
    try:
        QTimer.singleShot(0, lambda: beats.append(w.view.preparation.busy))
        w.app.processEvents()
        assert beats == [True]
        for _ in range(30):
            main.ReaderPage._load_dive(w.view)
        assert calls == [1]
    finally:
        release.set()
    settle(w.app, lambda: not w.view.preparation.busy)
    assert "data:image/png" in w.view.dive_view._body and calls == [1]
    assert w.view.ask_box.text() == "Keep unsent question"
    assert w.view.note_edit.toPlainText() == "Keep unsent note"


@pytest.mark.parametrize("changed", ["paper", "workspace", "native", "database"])
def test_pending_dive_never_crosses_original_view_workspace_or_native_identity(
    cached, monkeypatch, changed
):
    w = cached
    document = native(w)
    entered, release, calls = held(monkeypatch)
    w.view.ask_box.setText("Keep current draft")
    main.ReaderPage._load_dive(w.view)
    assert entered.wait(2)
    try:
        if changed == "paper":
            w.view.paper = SimpleNamespace(id="another-paper", abstract="", has_pdf=False)
            w.view._qa_epoch += 1
        elif changed == "workspace":
            monkeypatch.setattr(store, "DB_PATH", w.folder / "other.db")
        elif changed == "native":
            document.path.write_bytes(document.path.read_bytes())
        else:
            replacement = Path(store.DB_PATH).with_name("replacement.db")
            with (
                closing(sqlite3.connect(store.DB_PATH)) as source,
                closing(sqlite3.connect(replacement)) as target,
            ):
                source.backup(target)
            replacement.replace(store.DB_PATH)
    finally:
        release.set()
    settle(w.app, lambda: not w.view.preparation.busy)
    assert w.view.dive_view._body == ""
    assert w.view.ask_box.text() == "Keep current draft" and calls == [0]
    assert w.view._dive_highlights is None


def test_owned_figures_ready_upgrades_preview_without_extra_extraction_from_dive(
    cached, monkeypatch
):
    w = cached
    document = native(w)
    open_dive(w)
    assert "Unverified cached figure" in w.view.dive_view._body
    from paper_daily.desktop import figure_pane

    original = figure_pane.extract
    calls = []

    def extract(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(figure_pane, "extract", extract)
    main.ReaderPage._load_figures(w.view)
    until(w.app, lambda: not w.view.figure_pane.busy and not w.view.preparation.busy)
    assert calls == [1]
    assert w.view.figure_pane._frame is not None
    assert w.view.figure_pane._frame.ready_emitted
    assert "data:image/png" in w.view.dive_view._body
    assert "Unverified cached figure" not in w.view.dive_view._body
    assert "(p1)" in w.view.dive_view._body
    open_dive(w)
    assert calls == [1] and w.view._active_document is document


def test_close_cancels_saved_dive_and_waits_through_queued_gui_delivery(cached, monkeypatch):
    w = cached
    entered, release, _calls = held(monkeypatch)
    w.view.ask_box.setText("Keep unsent question")
    main.ReaderPage._load_dive(w.view)
    assert entered.wait(2)
    try:
        assert not w.window._prepare_restart()
        assert w.view.preparation.busy
    finally:
        release.set()
    assert w.view.preparation._thread.wait(10000)
    assert w.view.preparation.busy
    settle(w.app, lambda: not w.view.preparation.busy)
    assert w.view.dive_view._body == ""
    assert w.view.ask_box.text() == "Keep unsent question"
    open_dive(w)
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body


@pytest.mark.parametrize("running", [False, True])
def test_empty_dive_preserves_abstract_and_analysis_state_on_worker(ready, monkeypatch, running):
    app, window, view = ready
    view.paper = SimpleNamespace(id="local-paper", abstract="SYNTHETIC_ABSTRACT", has_pdf=False)
    monkeypatch.setattr(window, "analysis_running", lambda *_: running)
    main.ReaderPage._load_dive(view)
    settle(app, lambda: not view.preparation.busy)
    assert "SYNTHETIC_ABSTRACT" in view.dive_view._body
    assert ("paperfact-analyze:now" in view.dive_view._body) is (not running)
    assert "SAVED_RESEARCH_EXPLANATION" not in view.dive_view._body


def test_actual_close_veto_drains_dive_without_discarding_drafts(cached, monkeypatch):
    w = cached
    entered, release, _calls = held(monkeypatch)
    w.window.show()
    w.view.ask_box.setText("Keep visible draft")
    main.ReaderPage._load_dive(w.view)
    assert entered.wait(2)
    try:
        assert not w.window.close()
        assert w.window.isVisible() and w.view.preparation.busy
    finally:
        release.set()
    settle(w.app, lambda: not w.view.preparation.busy)
    assert w.view.dive_view._body == ""
    assert w.window.isVisible() and w.view.ask_box.text() == "Keep visible draft"
    open_dive(w)
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body


def test_saved_dive_does_not_acquire_AI_route_after_account_switch(cached, monkeypatch):
    from paper_daily import llm

    w = cached
    entered, release, _calls = held(monkeypatch)
    main.ReaderPage._load_dive(w.view)
    assert entered.wait(2)
    try:
        llm.save_settings(profile="fixture-changed", backend="none", isolated=True)
        llm.use_profile("fixture-changed", desktop=True)

        def forbidden(*args, **kwargs):
            pytest.fail("Saved reading acquired an AI route")

        monkeypatch.setattr(llm, "capture_connections", forbidden)
        monkeypatch.setattr(llm, "settings", forbidden)
        monkeypatch.setattr(llm, "complete", forbidden)
    finally:
        release.set()
    settle(w.app, lambda: not w.view.preparation.busy)
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body
    assert w.view.ask_box.text() == "Question"


@pytest.mark.parametrize("cache_source", ["original_A", "desired_B"])
def test_actual_worker_preserves_loaded_A_while_desired_B_changes(tmp_path, cache_source):
    from concurrent.futures import ThreadPoolExecutor

    from test_document_reader import LOCAL, prepared
    from test_sync_document_research import document as operation
    from test_sync_document_research import pdf_bytes
    from test_sync_reading_state_research import save

    from paper_daily import file_change, sync_capture
    from paper_daily import research_generation as generation
    from paper_daily.desktop import reader_preparation as prep
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_writer

    database, journal, _blobs, resolver, _alias, _data = prepared(tmp_path)
    SyncClient(journal, research_writer)
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO dives VALUES(?,?,?,?)",
                (LOCAL, "## Result\nEXACT_A_EXPLANATION", "2026-10-31T00:00:00+00:00", "fixture"),
            )
            conn.execute(
                "INSERT INTO close_readings VALUES(?,?,?,?)",
                (LOCAL, "## Evidence\n[[Figure 1]]", "fixture", "2026-10-31T00:00:00+00:00"),
            )
        conn.commit()
    loaded_a = resolver.resolve(LOCAL)
    owner = manual_highlight_ops.capture_owner(database, LOCAL)
    scope = saved.capture(
        owner, document=loaded_a, native_source_version=file_change.version(loaded_a.path)
    )
    newer_b = pdf_bytes("Desired original B")
    save(journal, operation(newer_b, op_id="new-desired-b"))
    assert resolver.intact(loaded_a) and not resolver.current(loaded_a)
    options = dict(
        min_height=figures.MIN_HEIGHT,
        max_height=figures.MAX_HEIGHT,
        render_scale=figures.RENDER_SCALE,
        min_png_bytes=figures.MIN_PNG_BYTES,
    )
    encoded = json.dumps(options, sort_keys=True, separators=(",", ":"))
    relative = (
        Path("documents")
        / loaded_a.sha256
        / ("figures-v1-" + hashlib.sha256(encoded.encode()).hexdigest()[:24])
    )
    root = tmp_path / "figures"
    folder = root / relative
    folder.mkdir(parents=True)
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(0x123456)
    path = folder / "figure.png"
    assert image.save(str(path))
    tag = loaded_a.sha256 if cache_source == "original_A" else hashlib.sha256(newer_b).hexdigest()
    (folder / "index.json").write_text(
        json.dumps(
            [
                dict(
                    label="Figure 1",
                    caption="Captured original preview",
                    page=1,
                    file=path.name,
                    kind="figure",
                    document_hash=tag,
                    cache_key=relative.as_posix(),
                    asset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            ]
        ),
        encoding="utf-8",
    )
    request = prep.Request(
        1,
        (),
        scope,
        loaded_a,
        tuple(sorted(main.LIGHT.items())),
        False,
        targets=("dive",),
        preview=saved.capture_preview(root, options),
    )
    before_jobs = journal.pending()
    with ThreadPoolExecutor(max_workers=1) as pool:
        publication = pool.submit(prep._prepare, request, threading.Event()).result(timeout=20)
    assert "EXACT_A_EXPLANATION" in publication.dive_html
    assert ("data:image/png" in publication.dive_html) is (cache_source == "original_A")
    assert publication.snapshot.data["source"]["document_hash"] == loaded_a.sha256
    assert resolver.intact(loaded_a) and not resolver.current(loaded_a)
    assert publication.snapshot.request == scope
    assert journal.pending() == before_jobs


class ReadProbe:
    """Observe actual byte reads while retaining real stream/native file handles."""

    def __init__(self, stream, reads):
        self.stream, self.reads = stream, reads

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, *args):
        data = self.stream.read(*args)
        self.reads.append(len(data))
        return data


def test_resolved_index_escape_is_rejected_before_cache_bytes_are_read(cached, monkeypatch):
    import os

    w = cached
    outside = w.root.parent / "outside-index.json"
    outside.write_bytes(w.index.read_bytes())
    w.index.unlink()
    try:
        os.symlink(outside, w.index)
    except OSError as error:
        # This Windows token lacks SeCreateSymbolicLinkPrivilege. Exercise only
        # the path-resolution boundary through its I/O seam; all actual stream
        # reads/native versions still use the real disposable files.
        assert getattr(error, "winerror", None) == 1314
        w.index.write_bytes(outside.read_bytes())
        resolve = Path.resolve

        def resolved(path, *args, **kwargs):
            return outside if path == w.index else resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolved)
    opened, reads = Path.open, []

    def observed(path, *args, **kwargs):
        stream = opened(path, *args, **kwargs)
        return ReadProbe(stream, reads) if path == w.index else stream

    monkeypatch.setattr(Path, "open", observed)
    open_dive(w)
    assert reads == [], "An escaped index was read before root admission"
    assert "data:image/png" not in w.view.dive_view._body
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body
    assert "Cached figures could not be checked" in w.view.dive_view._body


def test_replaced_opened_index_is_rejected_before_first_byte_read(cached, monkeypatch):
    w = cached
    replacement = w.folder / "replacement.json"
    replacement.write_text(
        json.dumps([{**w.item, "caption": "Foreign replacement bytes"}]), encoding="utf-8"
    )
    observed_version = saved._preview_version
    opened, reads, state = Path.open, [], {"armed": False, "swapped": False}

    def version(path):
        result = observed_version(path)  # Real native version; never forge it.
        if path == w.index and not state["swapped"]:
            state["armed"] = True
        return result

    def swapped(path, *args, **kwargs):
        if path == w.index and state["armed"] and not state["swapped"]:
            replacement.replace(w.index)
            state["swapped"] = True
        stream = opened(path, *args, **kwargs)
        return ReadProbe(stream, reads) if path == w.index else stream

    monkeypatch.setattr(saved, "_preview_version", version)
    monkeypatch.setattr(Path, "open", swapped)
    open_dive(w)
    assert state["swapped"]
    assert reads == [], "A replaced opened stream was read before native identity admission"
    assert "data:image/png" not in w.view.dive_view._body
    assert "SAVED_RESEARCH_EXPLANATION" in w.view.dive_view._body
    assert "Cached figures could not be checked" in w.view.dive_view._body
