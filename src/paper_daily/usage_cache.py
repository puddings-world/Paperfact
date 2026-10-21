"""Account-scoped quota snapshots and cross-process AI-completion invalidation."""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from uuid import uuid4

from paper_daily import ai_choices, ai_usage, llm


def key(cfg):
    return str(llm.SETTINGS_PATH.resolve()), *ai_choices.account_key(cfg)


def marker(cfg):
    identity = repr(ai_choices.account_key(cfg)).encode()
    return llm.SETTINGS_PATH.parent / "usage-changes" / hashlib.sha256(identity).hexdigest()


def invalidate(cfg):
    """Also notifies a desktop running separately from the analysis subprocess."""
    path = marker(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def revision(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


class UsageCache:
    def __init__(self, ttl=300):
        self.ttl = ttl
        self.entries = {}
        self.pending = set()
        self.condition = threading.Condition()

    def peek(self, cfg):
        with self.condition:
            value = self.entries.get(key(cfg))
            return copy.deepcopy(value["snapshot"]) if value else None

    def _fresh(self, identity, changed):
        value = self.entries.get(identity)
        return value and value["revision"] == changed and time.monotonic() - value["at"] < self.ttl

    def read(self, cfg, *, force=False):
        identity, path = key(cfg), marker(cfg)
        with self.condition:
            if identity in self.pending:
                self.condition.wait_for(lambda: identity not in self.pending, timeout=100)
                # Share an in-flight request even for repeated manual refreshes.
                if identity in self.pending:
                    raise TimeoutError("Usage query still running")
                force = False
            changed = revision(path)
            if not force and self._fresh(identity, changed):
                return copy.deepcopy(self.entries[identity]["snapshot"])
            self.pending.add(identity)
        try:
            try:
                quota = ai_usage.subscription(cfg)
            except Exception:
                quota = {"windows": [], "message": "方案用量暫時無法取得，剩餘量未知。"}
            try:
                local = ai_usage.local_summary(cfg)
            except (OSError, ValueError):
                local = None
            snapshot = {"quota": quota, "local": local, "version": uuid4().hex}
            with self.condition:
                self.entries[identity] = {"snapshot": snapshot, "at": time.monotonic(),
                                          "revision": changed}
            return copy.deepcopy(snapshot)
        finally:
            with self.condition:
                self.pending.discard(identity)
                self.condition.notify_all()

    def refresh_background(self, cfg):
        with self.condition:
            identity = key(cfg)
            if identity in self.pending or self._fresh(identity, revision(marker(cfg))):
                return
            previous = self.entries.get(identity)
            if previous and time.monotonic() - previous["at"] < 5:
                return
        # read() deduplicates concurrent callers, including open account dialogs.
        threading.Thread(target=self.read, args=(cfg,), daemon=True).start()


cache = UsageCache()
