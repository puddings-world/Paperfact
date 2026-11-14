"""A reading view that typesets: a web view over rich_html's page, with a plain
QTextBrowser in its place where Qt WebEngine is not installed.

Callers build the body with `markdown()`, which renders for whichever view is in
use, so the same code feeds both. Links, including the app's own schemes (keep:,
paperfact-highlight:...), arrive on `anchorClicked` instead of navigating the page.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, Qt, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStackedLayout, QTextBrowser, QWidget

from paper_daily.desktop import md, rich_html
from paper_daily.web_assets import WEB_DIR


def prepare() -> None:
    """Call before the QApplication exists: the web engine shares OpenGL contexts
    with the widgets, which has to be asked for up front."""
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


def web_available() -> bool:
    # Tests and headless scripts can ask for the plain view: a Chromium per test is
    # slow, and what they check is the app's behavior, not the typesetting.
    return (
        os.environ.get("PAPERFACT_PLAIN_VIEWS") != "1"
        and importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None
        and (WEB_DIR / "katex" / "katex.min.js").exists()
    )


def _web_view(owner: RichView, palette: dict[str, str]):
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, is_main_frame) -> bool:
            if kind == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                owner.anchorClicked.emit(url)
                return False
            return super().acceptNavigationRequest(url, kind, is_main_frame)

    view = QWebEngineView(owner)
    view.setPage(Page(view))
    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    # Everything the page needs is on disk; nothing it shows should reach out.
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    view.page().setBackgroundColor(QColor(palette["ground"]))
    # Initialize the native WebEngine surface before showing the main window.
    # First-paper content must not recreate/move an already visible window.
    view.setHtml("")
    return view


class RichView(QWidget):
    anchorClicked = Signal(QUrl)

    def __init__(self, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_ = palette
        self.rich = web_available()
        layout = QStackedLayout(self)
        if self.rich:
            self.view = _web_view(self, palette)
        else:
            self.view = QTextBrowser(self)
            self.view.setOpenLinks(False)
            self.view.setOpenExternalLinks(False)
            self.view.anchorClicked.connect(self.anchorClicked)
            self.view.setStyleSheet(
                f"QTextBrowser{{background:{palette['ground']};border:0;padding:16px;}}"
            )
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        self._body = ""
        # What the web page was last asked to show; None until something is.
        self._shown = None
        # Which loaded document that was: a change sent to any other is refused there.
        self._page_id = 0

    def markdown(self, text: str) -> str:
        return rich_html.markdown(text) if self.rich else md.to_html(text, self.palette_)

    def setHtml(self, body: str, *, at_end: bool = False, keep_scroll: bool = False,
                current: Callable[[], bool] | None = None) -> None:
        if current is not None and not current():
            return
        self._body = body
        if not self.rich:
            bar = self.view.verticalScrollBar()
            kept = bar.value()
            self.view.setHtml(body)
            if at_end:
                bar.setValue(bar.maximum())
            elif keep_scroll:
                bar.setValue(kept)
            return
        if body == self._shown:
            # The explanation is handed over again each time an answer arrives.
            # Loading the same page again typesets every formula and diagram once
            # more and throws the reader back to the top of what they were reading.
            if at_end:
                self.view.page().runJavaScript(
                    "window.scrollTo(0, document.body.scrollHeight)")
            return
        # Only a page that was actually loaded can take a change; one still waiting
        # to hear its scroll position has nothing on screen to change.
        in_place = bool(body) and self._shown is not None and self._page_id > 0
        self._shown = body
        if in_place:
            # Loading a page again fetches and starts every script and typesets every
            # formula in it. The page already there takes the new body and redoes only
            # the blocks after the first one that differs. It answers true, or its
            # scroll position when it could not (still loading, or not block-shaped).
            self.view.page().runJavaScript(
                f"window.PAGE_ID === {self._page_id} && typeof patchMain === 'function'"
                f" ? patchMain({json.dumps(body)}, {json.dumps(at_end)},"
                f" {json.dumps(not keep_scroll)}) : window.scrollY",
                0,
                lambda done: self._patched(done, body, at_end, keep_scroll, current),
            )
            return
        if keep_scroll:
            self.view.page().runJavaScript(
                "window.scrollY", 0,
                lambda y: self._load(body, at_end, int(y or 0), current=current),
            )
        else:
            self._load(body, at_end, 0, current=current)

    def _patched(self, done, body: str, at_end: bool, keep_scroll: bool,
                 current: Callable[[], bool] | None) -> None:
        if done is True or body != self._shown:
            # Shown in place, or a later body has been asked for and answers for itself.
            return
        at = int(done or 0) if keep_scroll and not isinstance(done, bool) else 0
        self._load(body, at_end, at, current=current)

    def _load(self, body: str, at_end: bool, at: int, *,
              current: Callable[[], bool] | None = None) -> None:
        if current is not None and not current():
            # Asked for, then overtaken before the page answered: nothing was shown.
            self._shown = None
            return
        self._page_id += 1
        page = rich_html.page(body, self.palette_, at_end=at_end, at=at, ident=self._page_id)
        self.view.setHtml(page, QUrl.fromLocalFile(str(WEB_DIR) + "/"))

    def find(self, text: str) -> bool:
        """Scroll to the first heading containing `text`; whether one exists."""
        if not self.rich:
            cursor = self.view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self.view.setTextCursor(cursor)
            return self.view.find(text)
        self.view.page().runJavaScript(f"findHeading({json.dumps(text)})")
        return text in self._body

    def scroll_to_top(self) -> None:
        if self.rich:
            self.view.page().runJavaScript("window.scrollTo(0, 0)")
        else:
            self.view.verticalScrollBar().setValue(0)

    def grab_page(self):
        """What is on screen; the web view draws on its own surface, so grabbing the
        widget itself gives a blank image."""
        return (self.view.focusProxy() or self.view).grab()
