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

    def markdown(self, text: str) -> str:
        return rich_html.markdown(text) if self.rich else md.to_html(text, self.palette_)

    def setHtml(self, body: str, *, at_end: bool = False, keep_scroll: bool = False) -> None:
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
        if keep_scroll:
            self.view.page().runJavaScript(
                "window.scrollY", 0, lambda y: self._load(body, at_end, int(y or 0))
            )
        else:
            self._load(body, at_end, 0)

    def _load(self, body: str, at_end: bool, at: int) -> None:
        page = rich_html.page(body, self.palette_, at_end=at_end, at=at)
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
