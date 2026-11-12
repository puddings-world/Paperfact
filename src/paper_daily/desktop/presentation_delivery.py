"""Ephemeral full-deck result delivery; never serialized publication authority.

The producer owns save/retention. Keep its actual Deck metadata in memory instead
of reconstructing a writable managed result from a public JSON representation.
"""

from __future__ import annotations

import json
import weakref
from pathlib import Path

from shiboken6 import isValid

from paper_daily import presentations, store
from paper_daily.desktop.window_workspace import _identity

COPY = {
    "en": {
        "not_started": "Workspace changed; presentation generation did not start.",
        "failed": "Presentation job failed: {kind}",
        "saved_elsewhere": "Saved in the original workspace; the current view is unchanged.",
        "missing_result": "The presentation result is not ready; the current content is unchanged.",
        "failed_elsewhere": (
            "Generation in the original workspace failed; "
            "current content is unchanged."
        ),
    },
    "zh-TW": {
        "not_started": "工作區已切換；簡報工作未開始。",
        "failed": "簡報工作失敗：{kind}",
        "saved_elsewhere": "簡報已保存至原工作區；目前畫面未變動。",
        "missing_result": "簡報回傳內容尚未準備好；目前內容未變動。",
        "failed_elsewhere": "原工作區的簡報未生成；目前內容未變動。",
    },
}


class GenerationDelivery:
    def __init__(self, view, paper_id, options):
        self._view = weakref.ref(view)
        self.copy = COPY.get(getattr(view.window(), "language", "zh-TW"), COPY["en"])
        self._outer = getattr(view.window(), "_workspace_owner", None)
        self.database = Path(store.DB_PATH).resolve()
        self.identity = _identity(self.database)
        self.directory = Path(presentations.DECK_DIR).resolve()
        self.paper_id = paper_id
        self.options = options
        self.result = None
        self.retention = None
        self._pending_hub = view.pending_panel.hub

    def current(self):
        """Cheap native/path checks only; the backend owns source and save checks."""
        try:
            return (
                Path(store.DB_PATH).resolve() == self.database
                and _identity(self.database) == self.identity
                and Path(presentations.DECK_DIR).resolve() == self.directory
                and (
                    self._outer is None
                    or (
                        self._outer.database == self.database
                        and self._outer.identity == self.identity
                        and self._outer.current()
                    )
                )
            )
        except (OSError, TypeError, ValueError):
            return False

    def _owner(self):
        view = self._view()
        if (
            view is None
            or not isValid(view)
            or getattr(view, "_generation_delivery", None) is not self
            or getattr(view.window(), "_workspace_owner", None) is not self._outer
        ):
            return None
        return view

    def run(self, _prompt):
        # Do not touch widgets on the worker, even to ask whether they are alive.
        if not self.current():
            return None, self.copy["not_started"]
        try:
            deck, reason = presentations.generate(self.paper_id, **self.options)
            if deck is None:
                return None, reason
            if not isinstance(deck, presentations.Deck):
                raise ValueError("Invalid generated deck")
            self.result = deck
            return json.dumps(deck.to_dict(), ensure_ascii=False), reason
        except Exception as exc:  # noqa: BLE001 - retain the worker failure lifecycle
            from paper_daily.sync_deck_publication import (
                IncompleteDraftRetention,
                StaleDeckError,
            )

            if (
                isinstance(exc, (IncompleteDraftRetention, StaleDeckError))
                and getattr(exc, "retention", None) is not None
            ):
                self.retention = exc.retention
                if not self.retention.durable:
                    self._pending_hub.hold(self.retention)
                return None, "Completed presentation requires disposition"
            return None, self.copy["failed"].format(kind=type(exc).__name__)

    def _retained(self):
        if self.retention is None:
            return False
        view = self._owner()
        if view is not None:
            view._generation_delivery = None
            view._generating = False
            view._update_controls()
            key = "retained" if self.retention.durable else "notice"
            view.status.setText(view.pending_panel.copy[key])
            view.pending_panel.refresh()
        self.result = None
        return True

    def done(self, text):
        if self._retained():
            return
        view = self._owner()
        if view is None:
            self.result = None
            return
        view._generation_delivery = None
        if not self.current():
            view._generating = False
            view._update_controls()
            view.status.setText(self.copy["saved_elsewhere"])
            self.result = None
            return
        if self.result is None:
            view._failed(self.copy["missing_result"])
            return
        try:
            view._generated(text, _published=self.result)
        finally:
            self.result = None

    def failed(self, reason):
        if self._retained():
            return
        view = self._owner()
        if view is None:
            self.result = None
            return
        view._generation_delivery = None
        self.result = None
        if self.current():
            view._failed(reason)
        else:
            view._generating = False
            view._update_controls()
            view.status.setText(self.copy["failed_elsewhere"])
