"""Per-exchange progress for the local UI. No research content is persisted."""

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

_active = ContextVar("drive_transfer_progress", default=None)


@contextmanager
def observe(callback, store):
    state = {"callback": callback, "store": store, "titles": {}, "event": {}}
    token = _active.set(state)
    try:
        yield
    finally:
        _active.reset(token)


def stage(kind, **fields):
    state = _active.get()
    if state is None:
        return
    if kind == "list":
        state["context"] = fields
    else:
        state["context"].pop("coverage", None)
    state["kind"] = kind
    report()


def report(direction="check", *, paper=None, title="", count=None):
    state = _active.get()
    if state is None:
        return
    now = monotonic()
    if (state["kind"] != "pdf" and direction != "check"
            and state.get("last") == (state["kind"], direction)
            and now - state.get("last_at", 0) < 0.15):
        return
    state["last"], state["last_at"] = (state["kind"], direction), now
    if paper and not title:
        cache = state["titles"]
        if paper not in cache:
            store = state["store"]
            try:
                from paper_daily.workspace_service import _read

                with _read(store.path) as conn:
                    row = conn.execute("SELECT local_id FROM published_paper_ids WHERE remote_id=?",
                                       (paper,)).fetchone()
                if row:
                    with _read(store.workspace.path) as conn:
                        row = conn.execute("SELECT title FROM papers WHERE id=?", row).fetchone()
                cache[paper] = str(row[0]) if row else ""
            except (sqlite3.Error, OSError):
                cache[paper] = ""
        title = cache[paper]
    event = dict(stage="transfer", **state.get("context", {}), kind=state["kind"],
                 direction=direction, title=title, count=count)
    state["event"] = event
    state["callback"](event)


def originals_count(device, drive, total):
    state = _active.get()
    if state:
        state["context"]["coverage"] = (device, drive, total)
        report()


def byte_progress(done, total):
    state = _active.get()
    if state and state["event"].get("kind") == "pdf":
        now = monotonic()
        if done == total or now - state.get("updated", 0) >= 0.25:
            state["updated"] = now
            state["callback"](dict(state["event"], done=done, size=total))


def batch_upload(batch):
    if _active.get() and batch:
        payload = batch[0]["payload"]
        paper = payload.get("paper_id") or payload.get("scope", {}).get("id")
        report("upload", paper=paper, count=len(batch))


def describe(event, zh=True):
    if not isinstance(event, dict) or event.get("stage") != "transfer":
        return ""
    kinds = {"list": "清單", "papers": "書目", "pdf": "PDF 原文", "dives": "深入分析",
             "chat": "問答", "notes": "筆記", "positions": "續讀頁碼", "reading": "閱讀狀態"}
    verbs = {"check": "核對", "upload": "上傳", "download": "下載", "index": "登錄雲端索引"}
    kind, verb = event["kind"], event["direction"]
    action = f"{verbs[verb]}{kinds[kind]}" if zh else f"{verb} {kind}"
    parts = [f"{event['index']}/{event['total']} {event['name']}", action, event.get("title")]
    if event.get("count", 0) and event["count"] > 1:
        parts.append(f"本批共 {event['count']} 筆" if zh else f"{event['count']} records in batch")
    if event.get("coverage"):
        device, drive, total = event["coverage"]
        parts.append(f"本機 {device}/{total} · Drive {drive}/{total}" if zh
                      else f"Device {device}/{total} · Drive {drive}/{total}")
    if event.get("size"):
        parts.append(f"{event['done'] / event['size']:.0%}")
    return " · ".join(str(part) for part in parts if part)
