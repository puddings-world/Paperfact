"""In-memory ownership for deferred work belonging to one desktop workspace."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import store


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
        return (info.st_dev, info.st_ino) if info.st_ino else None
    except OSError:
        return None


@dataclass(frozen=True)
class WindowWorkspace:
    """A missing initial database never becomes an admitted workspace later."""

    database: Path
    identity: tuple[int, int] | None
    _closed: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    @classmethod
    def capture(cls) -> WindowWorkspace:
        database = Path(store.DB_PATH).resolve()
        return cls(database, _identity(database))

    def current(self) -> bool:
        if self._closed.is_set() or self.identity is None:
            return False
        try:
            return (
                Path(store.DB_PATH).resolve() == self.database
                and _identity(self.database) == self.identity
            )
        except (OSError, TypeError, ValueError):
            return False

    def close(self, *_args) -> None:
        self._closed.set()


def current_for(window) -> bool:
    # Existing thin method fixtures have no constructor-owned context. Every real
    # MainWindow captures one before startup/deferred reads; never replace it.
    owner = getattr(window, "_workspace_owner", None)
    return owner is None or owner.current()
