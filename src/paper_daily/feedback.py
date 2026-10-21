"""Opt-in, content-free product events. No network client or automatic upload."""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from uuid import UUID, uuid4

from paper_daily import ai_profiles, llm

POLICY = "product-statistics-v2"
REMIND_AFTER_DAYS = 30
SESSION = uuid4().hex
FLOW = ContextVar("paperfact_product_flow", default=None)
UI_ACTIONS = {"ai_settings", "list_overview", "bundle_import", "bundle_export"}
BACKENDS = {"cli", "codex", "gemini", "anthropic", "openai", "gateway"}
try:
    APP_VERSION = version("paperfact")
except PackageNotFoundError:
    APP_VERSION = "development"
CONSENT_TEXT = (
    "協助改善 Paperfact：了解哪些功能常用、操作在哪裡失敗，以及等待時間。\n\n"
    "分享內容只有統計：功能次數、成功／失敗、耗時與輸入長度區間、AI 服務／模型類別、"
    "流程內的功能銜接。匯出不含帳號、裝置或工作階段識別碼，也沒有逐筆時間與操作順序。\n\n"
    "不記錄輸入原文、AI 回答、論文、筆記、檔名路徑、信箱或金鑰。"
    "本機紀錄最多保留 30 天／10,000 筆，短期流程編號僅用於本機整理。\n\n"
    "分享方式：先預覽統計，再自行匯出；目前沒有自動上傳。"
    "可隨時取消參與並清除本機紀錄。已自行分享的檔案需向接收者要求刪除。"
)


def path():
    return llm.SETTINGS_PATH.parent / "product-events.sqlite3"


@contextmanager
def _connect():
    path().parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path(), timeout=2)
    db.execute("CREATE TABLE IF NOT EXISTS consent (id INTEGER PRIMARY KEY, participant TEXT, "
               "policy TEXT, accepted_at TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, day TEXT, body TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS notice (policy TEXT PRIMARY KEY, "
               "decided_at TEXT NOT NULL, dont_ask INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS app_agreements (purpose TEXT PRIMARY KEY, "
               "version TEXT NOT NULL, accepted_at TEXT NOT NULL)")
    try:
        with db:
            yield db
    finally:
        db.close()


def consent():
    if not path().exists():
        return None
    with _connect() as db:
        return _agreement(db)


def _agreement(db):
    row = db.execute(
        "SELECT participant, policy, accepted_at FROM consent WHERE id=1 AND policy=?", (POLICY,)
    ).fetchone()
    return dict(zip(("participant_id", "policy", "accepted_at"), row, strict=True)) if row else None


def should_ask(*, at=None):
    """A declined reminder is independent of consent and scoped to this policy."""
    if not path().exists():
        return True
    at = at or datetime.now(UTC)
    with _connect() as db:
        if _agreement(db):
            return False
        row = db.execute(
            "SELECT decided_at, dont_ask FROM notice WHERE policy=?", (POLICY,)
        ).fetchone()
    if row is None:
        return True
    if row[1]:
        return False
    return at >= datetime.fromisoformat(row[0]) + timedelta(days=REMIND_AFTER_DAYS)


def set_consent(enabled, *, dont_ask=True, at=None):
    """Save an explicit choice; hiding a reminder never enables collection."""
    if type(enabled) is not bool or type(dont_ask) is not bool:
        raise ValueError("Consent and reminder choices must be booleans")
    timestamp = (at or datetime.now(UTC)).isoformat()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _save_choice(db, enabled, dont_ask, timestamp)


def _save_choice(db, enabled, dont_ask, timestamp):
    if enabled:
        if not _agreement(db):
            db.execute("PRAGMA secure_delete=ON")
            db.execute("DELETE FROM events")
            db.execute("INSERT OR REPLACE INTO consent VALUES (1, ?, ?, ?)",
                       (uuid4().hex, POLICY, timestamp))
    else:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("DELETE FROM events")
        db.execute("DELETE FROM consent")
    db.execute("INSERT OR REPLACE INTO notice VALUES (?, ?, ?)",
               (POLICY, timestamp, int(dont_ask)))


def _prune(db):
    oldest = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    db.execute("DELETE FROM events WHERE day < ?", (oldest,))
    db.execute(
        "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)"
    )


def record(event, feature, *, backend=None, model=None, success=None, elapsed_ms=0, input_chars=0,
           node_id=None):
    # Never accept arbitrary text properties. Unknown task/provider/model names may
    # themselves contain private data, so reduce them to closed categories.
    if event not in {"ai.started", "ai.completed", "ui.action", "flow.started", "flow.completed"}:
        raise ValueError("Unknown event")
    if feature not in {*ai_profiles.TASKS, "default", "probe", *UI_ACTIONS}:
        feature = "other"
    if (
        type(elapsed_ms) is not int or type(input_chars) is not int
        or min(elapsed_ms, input_chars) < 0
    ):
        raise ValueError("Invalid event measurements")
    if success is not None and type(success) is not bool:
        raise ValueError("Invalid event outcome")
    if not path().exists():
        return
    family = "service_default" if not model else "other"
    for name in ("sonnet", "opus", "haiku", "fable", "gpt", "gemini"):
        if model and (model == name or model.startswith((name + "-", "claude-" + name + "-"))):
            family = name
            break
    body = {
        "schema_version": 1, "event_id": uuid4().hex, "session_id": SESSION,
        "app_version": APP_VERSION, "platform": sys.platform,
        "event": event, "feature": feature,
        "backend": backend if backend in BACKENDS else "other",
        "model_family": family, "success": success,
        "duration_seconds": min(round(elapsed_ms / 1000), 86400),
        "input_size": "empty" if not input_chars else "short" if input_chars < 1000
        else "medium" if input_chars < 10000 else "long",
    }
    node_id = UUID(node_id).hex if node_id else uuid4().hex
    context = FLOW.get()
    body.update(node_id=node_id, trace_id=context[0] if context else node_id,
                parent_node_id=context[1] if context else None)
    with _connect() as db:
        # Consent check and insertion share one write transaction, including across
        # background analysis processes and a concurrent withdrawal in the app.
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM consent WHERE id=1 AND policy=?", (POLICY,)).fetchone():
            return
        db.execute("INSERT INTO events(day,body) VALUES (?,?)",
                   (datetime.now(UTC).date().isoformat(), json.dumps(body)))
        _prune(db)


def safe_record(*args, **kwargs):
    # Product analytics must never break research work.
    with suppress(OSError, sqlite3.Error, ValueError):
        record(*args, **kwargs)


@contextmanager
def flow(feature):
    """Adapters/features may nest flows without knowing the telemetry storage."""
    import time

    node = uuid4().hex
    parent = FLOW.get()
    trace = parent[0] if parent else node
    safe_record("flow.started", feature, node_id=node)
    token = FLOW.set((trace, node))
    started = time.monotonic()
    outcome = {"node_id": node, "success": None}
    try:
        yield outcome
    except BaseException:
        outcome["success"] = False
        raise
    finally:
        FLOW.reset(token)
        safe_record("flow.completed", feature, node_id=node, success=outcome["success"],
                    elapsed_ms=int((time.monotonic() - started) * 1000))


def local_snapshot():
    """Private local ledger for aggregation; never include it in shared exports."""
    if not path().exists():
        return {"schema_version": 1, "consent": None, "events": []}
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        agreement = _agreement(db)
        if not agreement:
            return {"schema_version": 1, "consent": None, "events": []}
        _prune(db)
        events = [
            {"sequence": sequence, "day": day, **json.loads(body)}
            for sequence, day, body in db.execute("SELECT id,day,body FROM events ORDER BY id")
        ]
    return {"schema_version": 1, "consent": agreement, "events": events}


def export_payload():
    from paper_daily.feedback_report import aggregate

    return aggregate(local_snapshot()["events"], POLICY)
