"""A typeset page that gains or changes a block keeps the blocks before it as they are.

The page side runs in a child process: the web engine needs a QApplication made with
shared OpenGL contexts and a real window system, and the suite's own views are plain.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QApplication

from paper_daily.desktop import rich_view
from paper_daily.desktop.main import palette
from paper_daily.web_assets import WEB_DIR


class Page:
    def __init__(self, answers):
        self.scripts, self.answers = [], answers

    def runJavaScript(self, script, *rest):  # noqa: N802 - Qt's name
        self.scripts.append(script)
        if rest and callable(rest[-1]):
            rest[-1](self.answers.pop(0) if self.answers else None)


class WebView:
    def __init__(self, answers):
        self.loads, self._page = [], Page(answers)

    def page(self):
        return self._page

    def setHtml(self, html, _base=None):  # noqa: N802 - Qt's name
        self.loads.append(html)


def web_view(monkeypatch, answers):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(rich_view, "web_available", lambda: False)
    view = rich_view.RichView(palette())
    view.rich, view.view = True, WebView(answers)
    return view


def test_a_changed_body_goes_to_the_page_already_loaded(monkeypatch):
    view = web_view(monkeypatch, [True, True])
    view.setHtml("<h3>log</h3><p>one</p>", at_end=True)
    assert len(view.view.loads) == 1 and "window.PAGE_ID = 1;" in view.view.loads[0]

    view.setHtml("<h3>log</h3><p>one</p><p>two</p>", at_end=True)
    assert len(view.view.loads) == 1
    sent = view.view.page().scripts[-1]
    assert sent.startswith("window.PAGE_ID === 1 && ")
    assert json.dumps("<h3>log</h3><p>one</p><p>two</p>") + ", true, true)" in sent

    # Neither the end nor the old place asked for: the page starts at its top, as a
    # freshly loaded one would.
    view.setHtml("<p>another paper</p>")
    assert len(view.view.loads) == 1
    assert view.view.page().scripts[-1].split(" : ")[0].endswith(", false, true)")


def test_a_page_that_cannot_take_the_change_is_loaded_anew_where_it_was(monkeypatch):
    view = web_view(monkeypatch, [340.0, None, False])
    view.setHtml("<p>one</p>")
    view.setHtml("<p>two</p>", keep_scroll=True)
    assert len(view.view.loads) == 2
    assert "window.START_AT = 340;" in view.view.loads[1]
    assert "window.PAGE_ID = 2;" in view.view.loads[1]
    # A page with no answer at all (it was still loading) is loaded from its top.
    view.setHtml("<p>three</p>", keep_scroll=True)
    assert len(view.view.loads) == 3 and "window.START_AT = 0;" in view.view.loads[2]
    assert view.view.page().scripts[-1].startswith("window.PAGE_ID === 2 && ")
    view.setHtml("<p>four</p>", keep_scroll=True)
    assert len(view.view.loads) == 4 and "window.START_AT = 0;" in view.view.loads[3]


def test_an_answer_for_a_body_since_replaced_loads_nothing(monkeypatch):
    view = web_view(monkeypatch, [])
    view.setHtml("<p>one</p>")
    held = []
    view.view.page().runJavaScript = lambda _script, *rest: held.append(rest[-1])
    view.setHtml("<p>two</p>")
    view.setHtml("<p>three</p>")
    held[0](0.0)
    assert len(view.view.loads) == 1, "the refusal was for a body no longer wanted"
    held[1](0.0)
    assert len(view.view.loads) == 2 and "three" in view.view.loads[1]


def test_an_empty_body_always_loads_a_clean_page(monkeypatch):
    view = web_view(monkeypatch, [])
    view.setHtml("<p>one</p>")
    view.setHtml("")
    assert len(view.view.loads) == 2 and view.view.page().scripts == []


SCRIPT = r"""
import json, sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
from paper_daily.desktop import rich_view
from paper_daily.desktop.main import palette

sys.excepthook = lambda *exc: (sys.__excepthook__(*exc), sys.exit(1))

rich_view.prepare()
app = QApplication(sys.argv)
win = QMainWindow()
view = rich_view.RichView(palette())
assert view.rich
win.setCentralWidget(view)
win.resize(700, 500)
win.show()
card = '<table class="note-card"><tr><td>{}</td></tr></table>'
first = "<h3>log</h3>" + card.format('first <span class="math">a^2</span>')
second = first + card.format('second <span class="math">b^2</span>')
revised = first + card.format('second, revised')
other = '<div class="math block">c^2</div><p>another paper</p>'
LOOK = '''(function () {
  var main = document.querySelector('main'), kids = main.children;
  return JSON.stringify({
    page: window.PAGE_ID, loads: window.LOADS || 0, count: kids.length,
    kept: kids.length > 1 && kids[1].__mark === 'same element',
    typeset: main.querySelectorAll('.katex').length,
    raw: main.querySelectorAll('.math:not(:has(.katex))').length,
    text: main.textContent.indexOf('revised') >= 0,
    top: window.scrollY });
})()'''
seen = []

def run(script, then):
    view.view.page().runJavaScript(script, 0, then)

def look(then):
    run(LOOK, lambda found: (seen.append(json.loads(found)), then()))

def step1():
    run("document.querySelector('main').children[1].__mark = 'same element'; 1",
        lambda _r: look(step2))

def step2():
    view.setHtml(second, at_end=True)
    QTimer.singleShot(400, lambda: look(step3))

def step3():
    view.setHtml(revised, at_end=True)
    QTimer.singleShot(400, lambda: look(step4))

def step4():
    view.setHtml(other)
    QTimer.singleShot(400, lambda: look(finish))

def finish():
    print("RESULT " + json.dumps(seen))
    app.quit()

view.setHtml(first, at_end=True)
QTimer.singleShot(2500, step1)
QTimer.singleShot(20000, lambda: (print("RESULT timeout " + json.dumps(seen)), app.quit()))
app.exec()
"""


@pytest.mark.skipif(sys.platform != "win32", reason="checked against the Windows window system")
@pytest.mark.skipif(
    importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None
    or not (WEB_DIR / "katex" / "katex.min.js").exists(),
    reason="needs Qt WebEngine and the vendored web assets",
)
def test_the_real_page_typesets_only_what_changed():
    env = {
        k: v for k, v in os.environ.items() if k not in ("PAPERFACT_PLAIN_VIEWS", "QT_QPA_PLATFORM")
    }
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, timeout=120, env=env
    )
    line = next((x for x in done.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line and "timeout" not in line, done.stdout[-2000:] + done.stderr[-2000:]
    loaded, appended, revised, other = json.loads(line[len("RESULT "):])
    assert loaded == {**loaded, "page": 1, "count": 2, "typeset": 1, "raw": 0}
    # One more exchange: the same document, the same first card, one more formula.
    assert appended == {**appended, "page": 1, "count": 3, "kept": True, "typeset": 2, "raw": 0}
    # The last card replaced: the first is still that element, the old second is gone.
    assert revised == {**revised, "page": 1, "count": 3, "kept": True, "typeset": 1,
                       "text": True}
    # Nothing shared: every block is new and typeset, in the page already loaded.
    assert other == {**other, "page": 1, "count": 2, "kept": False, "typeset": 1, "raw": 0,
                     "top": 0}
