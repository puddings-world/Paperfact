"""A web view asked to show the page it already shows does not load it again."""

from PySide6.QtWidgets import QApplication

from paper_daily.desktop import rich_view
from paper_daily.desktop.main import palette


class Page:
    def __init__(self, loads):
        self.scripts, self.loads = [], loads

    def runJavaScript(self, script, *rest):  # noqa: N802 - Qt's name
        self.scripts.append(script)
        # The scroll position the page reports, for the keep_scroll path.
        if rest and callable(rest[-1]):
            rest[-1](120)


class WebView:
    def __init__(self):
        self.loads = []
        self._page = Page(self.loads)

    def page(self):
        return self._page

    def setHtml(self, html, _base=None):  # noqa: N802 - Qt's name
        self.loads.append(html)


def web_view(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(rich_view, "web_available", lambda: False)
    view = rich_view.RichView(palette())
    # The suite's views are plain text; this drives the typeset path against a stand-in.
    view.rich, view.view = True, WebView()
    return view


def test_the_same_body_is_typeset_once_and_a_new_one_again(monkeypatch):
    view = web_view(monkeypatch)
    view.setHtml("<p>explanation</p>")
    view.setHtml("<p>explanation</p>")
    view.setHtml("<p>explanation</p>", keep_scroll=True)
    assert len(view.view.loads) == 1 and "explanation" in view.view.loads[0]

    view.setHtml("<p>explanation, revised</p>", keep_scroll=True)
    assert len(view.view.loads) == 2 and "revised" in view.view.loads[1]
    view.setHtml("<p>explanation</p>")
    assert len(view.view.loads) == 3


def test_the_same_conversation_still_goes_to_its_end(monkeypatch):
    view = web_view(monkeypatch)
    view.setHtml("<p>answer</p>", at_end=True)
    view.view.page().scripts.clear()
    view.setHtml("<p>answer</p>", at_end=True)
    assert len(view.view.loads) == 1
    assert view.view.page().scripts == ["window.scrollTo(0, document.body.scrollHeight)"]


def test_a_page_refused_as_out_of_date_is_not_remembered_as_shown(monkeypatch):
    view = web_view(monkeypatch)
    view.setHtml("<p>other paper</p>", current=lambda: False)
    assert view.view.loads == []
    view.setHtml("<p>other paper</p>")
    assert len(view.view.loads) == 1


def test_a_load_overtaken_while_the_page_reported_its_scroll_is_not_remembered(monkeypatch):
    view = web_view(monkeypatch)
    view.setHtml("<p>first</p>")
    answers = iter([True, False])
    view.setHtml("<p>second</p>", keep_scroll=True, current=lambda: next(answers))
    assert len(view.view.loads) == 1
    view.setHtml("<p>second</p>")
    assert len(view.view.loads) == 2 and "second" in view.view.loads[1]
