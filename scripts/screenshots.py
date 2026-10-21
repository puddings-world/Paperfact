"""Screenshots of the real app on a list, plus a report of the fonts and shortcut
labels the platform resolved. The release workflow takes them on Windows, macOS and
Linux so a layout can be compared across the three; no model calls or downloads are
started.

    python scripts/screenshots.py OUT_DIR --demo          # a generated workspace
    python scripts/screenshots.py OUT_DIR [--list ID] [--paper ID]   # your own data
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtGui import QFontInfo, QKeySequence
from PySide6.QtWidgets import QApplication

parser = argparse.ArgumentParser()
parser.add_argument("out")
parser.add_argument("--list", default="cataract")
parser.add_argument("--paper", default="ref:cataract1kdatasetfordeep")
parser.add_argument("--demo", action="store_true", help="photograph a generated workspace")
args = parser.parse_args()
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

w.open_paper(args.paper)
pump(30)
r = w.reader_page
r.tabs.setCurrentWidget(r.dive_view)
pump(10)
w.grab().save(str(out / "reader.png"))
# The web view draws on its own surface, which a window grab leaves blank.
r.dive_view.grab_page().save(str(out / "dive.png"))
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
