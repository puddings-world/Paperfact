"""Handle application-only file-open events without a global QObject filter.

A global Python filter wraps every WebEngine internal receiver, including native
objects whose lifetimes PySide cannot safely expose. QApplication.event sees
only events addressed to the application itself, including macOS FileOpen.
"""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class DesktopApplication(QApplication):
    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            handler = getattr(self, "file_opens", None)
            if handler is not None and isValid(handler) and handler.eventFilter(None, event):
                return True
        return super().event(event)
