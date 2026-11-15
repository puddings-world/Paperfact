"""Screenshots of the real app on a list, plus a report of the fonts and shortcut
labels the platform resolved. The release workflow takes them on Windows, macOS and
Linux so a layout can be compared across the three; no model calls or downloads are
started.

    python scripts/screenshots.py OUT_DIR --demo          # a generated workspace
    python scripts/screenshots.py OUT_DIR [--list ID] [--paper ID]   # your own data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtGui import QFontInfo, QImage, QKeySequence
from PySide6.QtWidgets import QApplication


def wait_until(app, ready, *, label, seconds=10):
    """Pump real queued work until observed completion, with a finite deadline."""
    deadline = time.monotonic() + seconds
    while True:
        app.processEvents()
        if ready():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError('Screenshot not ready: ' + label)
        time.sleep(0.02)


def observe_rendering(view):
    """Retain a small state-only trace; do not record supplied research HTML."""
    events = view._screenshot_render_trace = []
    for method in ('setHtml', '_load', '_patched'):
        original = getattr(view, method)

        def observed(*args, _method=method, _original=original, **kwargs):
            before = view._page_id
            result = _original(*args, **kwargs)
            events.append(dict(
                method=_method, page_advanced=view._page_id != before,
                body_present=bool(view._body.strip()), shown_missing=view._shown is None,
                shown_matches=view._shown == view._body,
                patch_accepted=_method == '_patched' and args[0] is True,
            ))
            del events[:-24]
            return result

        setattr(view, method, observed)


def save_reading_view(app, reader, target, *, seconds=10):
    """Wait for saved text and its exact rendered page; never publish a blank PNG."""
    view = reader.dive_view
    wait_until(app, lambda: not reader.preparation.busy and bool(view._body.strip()),
               label='saved reading content', seconds=seconds)
    if view.rich:
        state = dict(pending=False, ready=None, observed={"callback": "missing"})

        def rendered():
            if state['ready'] == view._page_id:
                return True
            if not state['pending']:
                page_id = view._page_id
                state['pending'] = True

                def observed(value):
                    state['pending'] = False
                    try:
                        value = json.loads(value) if isinstance(value, str) else None
                    except (ValueError, TypeError):
                        value = None
                    if not isinstance(value, dict):
                        state['observed'] = {"callback": "invalid"}
                        return
                    state['observed'] = {
                        "page_matches": value.get("page_matches") is True,
                        "document_complete": value.get("document_complete") is True,
                        "has_main": value.get("has_main") is True,
                        "has_text": value.get("has_text") is True,
                        "fonts_loaded": value.get("fonts_loaded") is True,
                    }
                    if all(state['observed'].values()) and page_id == view._page_id:
                        state['ready'] = page_id

                view.view.page().runJavaScript(
                    "JSON.stringify({"
                    f"page_matches: window.PAGE_ID === {page_id},"
                    "document_complete: document.readyState === 'complete',"
                    "has_main: !!document.querySelector('main'),"
                    "has_text: !!document.querySelector('main') && "
                    "document.querySelector('main').textContent.trim().length > 0,"
                    "fonts_loaded: document.fonts.status === 'loaded'})", 0, observed)
            return state['ready'] == view._page_id

        try:
            wait_until(app, rendered, label='rendered reading page', seconds=seconds)
        except TimeoutError as error:
            state['observed'].update(
                requested_body_present=bool(view._body.strip()),
                shown_matches=getattr(view, '_shown', None) == view._body,
                shown_missing=getattr(view, '_shown', None) is None,
                render_trace=getattr(view, '_screenshot_render_trace', []),
            )
            raise TimeoutError(f"{error}; render state: {json.dumps(state['observed'])}") from error
        from PySide6.QtTest import QTest

        QTest.qWait(80)
    pixmap = view.grab_page()
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull() or len(set(bytes(image.constBits())[::4])) < 2:
        raise RuntimeError('Screenshot reading surface is blank')
    if not pixmap.save(str(target)):
        raise OSError('Could not save the reading screenshot')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--list", default="cataract")
    parser.add_argument("--paper", default="ref:cataract1kdatasetfordeep")
    parser.add_argument("--demo", action="store_true", help="photograph a generated workspace")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.demo:
        # Before paper_daily is imported: config reads the data directory once.
        os.environ["PAPERFACT_DATA"] = str((out / "workspace").resolve())
        sys.path.insert(0, str(Path(__file__).parent))
        import demo_workspace

        demo_workspace.seed()
        args.list, args.paper = demo_workspace.LIST_ID, demo_workspace.PAPER_ID

    from paper_daily.desktop import rich_view  # noqa: E402

    rich_view.prepare()
    app = QApplication(sys.argv)

    from paper_daily.desktop import fonts  # noqa: E402
    from paper_daily.desktop import main as m  # noqa: E402
    from paper_daily.desktop.fetcher import FetchRunner  # noqa: E402

    m.style(app)
    fonts.load()
    m.ReaderPage._check_resources = lambda self: None
    m.ReaderPage._prepare_reading_highlights = lambda self: None
    m.MainWindow.top_up_dives = lambda self, prefer=None: None
    FetchRunner.start = lambda self, *a, **k: False


    def pump(n=8):
        for _ in range(n):
            app.processEvents()


    report = [f"platform: {sys.platform} / Qt platform: {app.platformName()}"]
    for name, families in (("sans", fonts.SANS), ("mono", fonts.MONO), ("serif", fonts.SERIF)):
        report.append(f"{name}: {QFontInfo(fonts.font(families)).family()}")
    for label, key in (
        ("copy", QKeySequence.StandardKey.Copy),
        ("redo", QKeySequence.StandardKey.Redo),
        ("find", QKeySequence.StandardKey.Find),
        ("find next", QKeySequence.StandardKey.FindNext),
        ("back", QKeySequence.StandardKey.Back),
        ("forward", QKeySequence.StandardKey.Forward),
    ):
        report.append(f"{label}: {fonts.key(key)}")
    report.append(f"zoom: {fonts.ZOOM_WHEEL} / delete: {fonts.DELETE} / views: {fonts.ALT}")

    w = m.MainWindow()
    w.resize(1680, 1000)
    w.show()
    pump()
    w._switching = True
    w.list_picker.setCurrentIndex(w.list_picker.findData(args.list))
    w._switching = False
    w.active_list = args.list
    w.reload()
    w.show_queue()
    pump(20)
    w.grab().save(str(out / "list.png"))

    observe_rendering(w.reader_page.dive_view)
    w.open_paper(args.paper)
    pump(30)
    r = w.reader_page
    r.tabs.setCurrentWidget(r.dive_view)
    pump(10)
    # Background preparation and WebEngine rendering complete asynchronously.
    save_reading_view(app, r, out / "dive.png")
    report.append("saved reading content and rendered surface: verified")
    w.grab().save(str(out / "reader.png"))
    # A laptop-sized window, where toolbars run out of room first.
    w.resize(1180, 760)
    pump(10)
    w.grab().save(str(out / "reader-laptop.png"))
    w.resize(1680, 1000)
    pump(5)
    report.append(f"typeset views: {r.dive_view.rich}")
    report.append(f"find box: {r.find_box.placeholderText()}")

    r.tabs.setCurrentWidget(r.cites_pane)
    pump(5)
    r.cites_pane._view = "graph"
    r.cites_pane.load(args.paper)
    pump(20)
    w.grab().save(str(out / "citemap.png"))

    r.tabs.setCurrentWidget(r.presentation_pane)
    pump(30)
    r.presentation_pane.canvas.view.fit_slide()
    pump(10)
    w.grab().save(str(out / "slides.png"))
    report.append(f"canvas hint: {r.presentation_pane.canvas.hint.text()}")

    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
