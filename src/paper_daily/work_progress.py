"""Local, content-free progress events shared by threads and desktop CLI jobs."""

import json
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar

PREFIX = "@paperfact-progress "
_sink = ContextVar("paperfact_progress", default=None)
_output_lock = threading.Lock()


@contextmanager
def observe(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


def report(stage, completed=None, total=None, *, paper_id=None, outcome=None):
    event = {"stage": str(stage)[:240]}
    if type(completed) is int and type(total) is int and 0 <= completed <= total and total > 0:
        event.update(completed=completed, total=total)
    if paper_id:
        event["paper_id"] = paper_id
    if outcome in ("partial", "error"):
        event["outcome"] = outcome
    callback = _sink.get()
    if callback is not None:
        callback(event)
    elif os.environ.get("PAPERFACT_PROGRESS") == "1":
        with _output_lock:
            print(PREFIX + json.dumps(event, ensure_ascii=False), flush=True)


def parse(line):
    if not line.startswith(PREFIX):
        return None
    try:
        data = json.loads(line[len(PREFIX):])
        return data if isinstance(data, dict) and isinstance(data.get("stage"), str) else None
    except ValueError:
        return None
