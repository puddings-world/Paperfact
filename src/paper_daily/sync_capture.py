"""Opt-in capture at the existing research connection's actual commit boundary.

The binding and triggers are durable; credentials and network clients are not.
Trusted journal/projection connections deliberately register a no-echo callback.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

CORE = {"papers", "lists", "list_papers", "notes", "kv"}
RESEARCH = CORE | {
    "dives",
    "close_readings",
    "paper_context",
    "list_surveys",
    "cites",
    "followups",
    "resources",
    "refs",
    "chat",
    "pdf_highlights",
    "pdf_ai_highlights",
    "pins",
    "queue",
    "reading_log",
}
PAPER_COLUMNS = {
    "id",
    "title",
    "authors_json",
    "year",
    "venue",
    "abstract",
    "doi",
    "arxiv_id",
    "s2_id",
    "page_url",
    "pdf_url",
    "source",
}


class CaptureError(ValueError):
    """A research mutation could not be captured safely."""


class StaleCaptureError(CaptureError):
    def __init__(self, candidate_id):
        self.candidate_id = candidate_id
        super().__init__("Research changed while editing; your candidate was retained for review")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content():
    try:
        from paper_daily import sync_content
    except ImportError:
        return None
    return sync_content


def enabled(conn):
    return bool(getattr(conn, "_capture_client", None))


def trusted_connection(conn):
    """Private journal/projection seam, never a user-supplied SQL capability."""
    conn.create_function("paperfact_capture", 3, lambda *_args: 0)


def _paper_id(conn, local_id):
    row = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local_id,)
    ).fetchone()
    if row:
        return row[0]
    identity = str(uuid4())
    conn.execute("INSERT INTO research_paper_identity VALUES(?,?)", (identity, local_id))
    return identity


def _keys(conn, table, row):
    from paper_daily.sync_schema_v2 import membership_id

    if table == "papers":
        return [("paper", _paper_id(conn, row["id"]))]
    if table == "lists":
        return [("list", row["id"]), ("workspace_list_order", "workspace-lists")]
    if table == "list_papers":
        identity = membership_id(row["list_id"], _paper_id(conn, row["paper_id"]))
        return [
            ("membership", identity),
            ("reading_state", identity),
            ("list_order", row["list_id"]),
        ]
    if table == "kv":
        return [("workspace_list_order", "workspace-lists")]
    content = _content()
    if content and table in content.CONTENT_TABLES:
        return [content.content_identity(conn, table, row)]
    if table == "notes":
        mapping = conn.execute(
            "SELECT sync_id FROM research_note_identity WHERE local_id=?", (row["id"],)
        ).fetchone()
        if mapping:
            return [("note", mapping[0])]
        identity = str(uuid4())
        conn.execute(
            "INSERT INTO research_note_identity VALUES(?,?,?,?)",
            (identity, row["id"], row["paper_id"], row["created_at"]),
        )
        return [("note", identity)]
    raise CaptureError(f"Research capture is not implemented for {table}")


def observe(conn, kind, entity_id):
    """Return a load/start token, or None for ordinary unbound workspaces."""
    if not enabled(conn):
        return None
    client = conn._capture_client
    state, _touches, own = client._optimistic_graph(conn)
    key = (kind, entity_id)
    current = state.get(key)
    head = conn.execute(
        "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?", key
    ).fetchone()
    parents = []
    for parent in current["parents"] if current else []:
        value = state.get((parent["kind"], parent["id"]))
        parents.append(
            {
                "kind": parent["kind"],
                "id": parent["id"],
                "incarnation": value["incarnation"] if value else None,
                "active": bool(value and value["active"]),
            }
        )
    return {
        "workspace_id": client.journal.workspace_id,
        "kind": kind,
        "entity_id": entity_id,
        "revision": head[0] if head else 0,
        "predecessor": own[key]["operation_id"] if key in own else None,
        "incarnation": current["incarnation"] if current else None,
        "active": bool(current and current["active"]),
        "parents": parents,
    }


def observe_note(conn, local_note_id):
    if not enabled(conn):
        return None
    row = conn.execute("SELECT * FROM notes WHERE id=?", (local_note_id,)).fetchone()
    if row is None:
        raise CaptureError("Note no longer exists")
    return observe(conn, *_keys(conn, "notes", dict(row))[0])


def observe_content(conn, table, row):
    if not enabled(conn):
        return None
    kind, identity = _keys(conn, table, dict(row))[0]
    token = observe(conn, kind, identity)
    return _content_parent(conn, table, dict(row), token)


def observe_target(conn, scope_kind, owner_id, feature, key="main"):
    """Observe an absent/existing typed target without inventing an output row."""
    if not enabled(conn):
        return None
    from paper_daily.sync_content import content_id

    if scope_kind not in ("paper", "list"):
        raise CaptureError("Invalid research owner kind")
    identity = owner_id
    if scope_kind == "paper":
        row = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (owner_id,)
        ).fetchone()
        if row is None:
            raise CaptureError("Research owner is not enrolled")
        identity = row[0]
    scope = {"kind": scope_kind, "id": identity}
    token = observe(conn, "research_content", content_id(scope, feature, key))
    if not token["parents"]:
        parent = conn._capture_client._optimistic_graph(conn)[0].get((scope_kind, identity))
        token["parents"] = [
            {
                "kind": scope_kind,
                "id": identity,
                "incarnation": parent["incarnation"] if parent else None,
                "active": bool(parent and parent["active"]),
            }
        ]
    return token


def _content_parent(conn, table, row, token):
    if token["kind"] != "research_content" or token["parents"]:
        return token
    payload = _content().content_payload(conn, table, row)
    scope = payload["scope"]
    state = conn._capture_client._optimistic_graph(conn)[0].get((scope["kind"], scope["id"]))
    token["parents"] = [
        {
            "kind": scope["kind"],
            "id": scope["id"],
            "incarnation": state["incarnation"] if state else None,
            "active": bool(state and state["active"]),
        }
    ]
    return token


@contextmanager
def expecting(conn, observations, *, source_hashes=None):
    """Carry loaded bases through the write AND its explicit commit."""
    previous = getattr(conn, "_capture_expected", {})
    previous_sources = getattr(conn, "_capture_source_hashes", {})
    sources = dict(previous_sources)
    expected = dict(previous)
    for value in observations:
        if value is None:
            continue
        if not enabled(conn) or not isinstance(value, dict):
            raise CaptureError("Observation does not belong to an enrolled workspace")
        current = observe(conn, value.get("kind"), value.get("entity_id"))
        if set(value) != set(current) or value["workspace_id"] != current["workspace_id"]:
            raise CaptureError("Observation belongs to another workspace")
        expected[(value["kind"], value["entity_id"])] = json.loads(_json(value))
    for identity, digest in (source_hashes or {}).items():
        if ("research_content", identity) not in expected:
            raise CaptureError("Source provenance requires an observed research target")
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise CaptureError("Invalid research source document hash")
        sources[identity] = digest
    conn._capture_expected = expected
    conn._capture_source_hashes = sources
    try:
        yield conn
    finally:
        conn._capture_expected = previous
        conn._capture_source_hashes = previous_sources


class CaptureConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        # Authorizer decisions depend on trusted projection scope, not cached SQL.
        kwargs["cached_statements"] = 0
        super().__init__(*args, **kwargs)
        self._capture_client = None
        self._capture_graph_cache = None
        self._capture_trusted = False
        self._capture_failed = False
        self._capture_expected = {}
        self.row_factory = sqlite3.Row
        if self.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchone():
            self._activate()

    def _activate(self):
        from paper_daily.sync_client import SyncClient
        from paper_daily.sync_journal import Journal
        from paper_daily.sync_research import research_order_writer, research_writer

        row = self.execute(
            "SELECT workspace,device FROM research_capture_binding WHERE id=1"
        ).fetchone()
        if not row:
            raise CaptureError("Capture binding is incomplete")
        path = next(r[2] for r in self.execute("PRAGMA database_list") if r[1] == "main")
        journal = Journal.attach_existing(Path(path), workspace_id=row[0], device_id=row[1])
        self._capture_client = SyncClient.attach_existing(
            journal, research_writer, order_writer=research_order_writer
        )
        self.create_function("paperfact_capture", 3, self._mark)
        # SQLite REPLACE otherwise suppresses its deletion triggers.
        self.execute("PRAGMA recursive_triggers=ON")
        self.set_authorizer(self._authorize)

    def _authorize(self, action, first, second, database, trigger):
        if self._capture_trusted:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_TRANSACTION:
            if first in ("COMMIT", "END"):
                return sqlite3.SQLITE_DENY
            if first == "ROLLBACK":
                self._capture_graph_cache = None
        if action == sqlite3.SQLITE_SAVEPOINT and first == "BEGIN" and not self.in_transaction:
            # RELEASE of a top-level SAVEPOINT commits without Connection.commit().
            return sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and (
            self._capture_failed or (first or "").startswith(("paperfact_sync_", "research_"))
        ):
            return sqlite3.SQLITE_DENY
        if action in (
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_DROP_INDEX,
        ):
            return sqlite3.SQLITE_DENY
        if (
            action == sqlite3.SQLITE_PRAGMA
            and second is not None
            and first
            not in (
                "journal_mode",
                "synchronous",
                "busy_timeout",
                "table_info",
                "table_xinfo",
                "database_list",
                "index_list",
                "index_info",
                "foreign_key_list",
            )
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def _mark(self, table, before, after):
        if self._capture_trusted:
            return 0
        if not self.in_transaction:
            raise CaptureError("Autocommit research mutations bypass capture")
        old, new = json.loads(before) if before else None, json.loads(after) if after else None
        row = new or old
        if old and new and any(old[k] != new[k] for k in _primary(self, table)):
            raise CaptureError("Research identities cannot be changed by an UPDATE")
        if old and new and "paper_id" in row and old["paper_id"] != new["paper_id"]:
            raise CaptureError("Research content cannot be reparented by an UPDATE")
        if table == "kv" and row["key"] != "lists.order":
            return 0
        if table == "papers" and old and new and all(old[k] == new[k] for k in PAPER_COLUMNS):
            return 0
        self._capture_trusted = True
        try:
            keys = _keys(self, table, row)
            key = _json([row.get(k) for k in _primary(self, table)])
            prior = self.execute(
                "SELECT before_json FROM research_capture_dirty WHERE table_name=? AND row_key=?",
                (table, key),
            ).fetchone()
            if (
                new is not None
                and prior
                and prior[0]
                and _keys(self, table, json.loads(prior[0]))[0] != keys[0]
            ):
                raise CaptureError("Replacing research cannot rebind its portable identity")
            if self._capture_graph_cache is None:
                self._capture_graph_cache = self._capture_client._optimistic_graph(self)
            for kind, identity in keys:
                token = _content_parent(self, table, row, observe(self, kind, identity))
                expected = self._capture_expected.get((kind, identity))
                self.execute(
                    "INSERT OR IGNORE INTO research_capture_bases VALUES(?,?,?,?)",
                    (kind, identity, _json(token), _json(expected) if expected else None),
                )
            key = _json([row.get(k) for k in _primary(self, table)])
            self.execute(
                "INSERT INTO research_capture_dirty VALUES(?,?,?,?) ON "
                "CONFLICT(table_name,row_key) DO UPDATE SET after_json=excluded.after_json",
                (table, key, before, after),
            )
        except BaseException:
            self._capture_failed = True
            raise
        finally:
            self._capture_trusted = False
        return 0

    def commit(self):
        if not enabled(self):
            return super().commit()
        if self._capture_failed:
            raise CaptureError("Research transaction failed; open a new connection to retry")
        self._capture_trusted = True
        try:
            if self.in_transaction:
                _flush(self)
            super().commit()
        except StaleCaptureError:
            raise
        except BaseException:
            super().rollback()
            self._capture_failed = True
            raise
        finally:
            self._capture_trusted = False
            self._capture_graph_cache = None
            self.set_authorizer(self._authorize)

    def rollback(self):
        self._capture_graph_cache = None
        return super().rollback()

    def executescript(self, script):
        if enabled(self):
            raise CaptureError("Schema scripts cannot run on an enrolled mutation connection")
        return super().executescript(script)

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        return False


def _primary(conn, table):
    return [
        row[1]
        for row in sorted(conn.execute(f'PRAGMA table_info("{table}")'), key=lambda r: r[5])
        if row[5]
    ]


def install(conn, *, workspace_id, device_id):
    """Install persistent capture in an already initialized caller transaction.

    The caller must bootstrap existing research before exposing the workspace.
    This function never enrolls credentials, creates a server or invokes AI.
    """
    if not isinstance(conn, CaptureConnection) or not conn.in_transaction:
        raise CaptureError("Capture installation requires a store transaction")
    if enabled(conn):
        journal = conn._capture_client.journal
        if (journal.workspace_id, journal.device_id) != (workspace_id, device_id):
            raise CaptureError("Capture belongs to another workspace/device")
        return
    identity = conn.execute(
        "SELECT workspace,device FROM paperfact_sync_identity WHERE id=1"
    ).fetchone()
    if not identity or tuple(identity) != (workspace_id, device_id):
        raise CaptureError("Initialize the journal/client with the same binding first")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_capture_binding(id INTEGER PRIMARY KEY "
        "CHECK(id=1),workspace TEXT NOT NULL,device TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO research_capture_binding VALUES(1,?,?)", (workspace_id, device_id)
    )
    actual = conn.execute("SELECT workspace,device FROM research_capture_binding").fetchone()
    if tuple(actual) != (workspace_id, device_id):
        raise CaptureError("Capture belongs to another workspace/device")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_capture_dirty(table_name TEXT,row_key "
        "TEXT,before_json TEXT,after_json TEXT,PRIMARY KEY(table_name,row_key))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_capture_bases(kind TEXT,entity_id "
        "TEXT,observed TEXT NOT NULL,expected TEXT,PRIMARY KEY(kind,entity_id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_capture_candidates(id TEXT PRIMARY "
        "KEY,content TEXT NOT NULL)"
    )
    content = _content()
    if content:
        content.initialize_content(conn)
        content.enroll_content_identities(conn)
    for table in sorted(RESEARCH):
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        if not columns:
            continue

        def encode(prefix, columns=columns):
            return (
                "json_object(" + ",".join(f"'{name}',{prefix}.\"{name}\"" for name in columns) + ")"
            )

        for action, old, new in (
            ("INSERT", "NULL", encode("NEW")),
            ("UPDATE", encode("OLD"), encode("NEW")),
            ("DELETE", encode("OLD"), "NULL"),
        ):
            conn.execute(
                f'CREATE TRIGGER IF NOT EXISTS "capture_{table}_{action.lower()}" '
                f'AFTER {action} ON "{table}" BEGIN '
                f"SELECT paperfact_capture('{table}',{old},{new}); END"
            )
    conn._activate()


def capture_existing(conn):
    """Queue a local baseline using the same serializers as ordinary mutations."""
    if not enabled(conn) or not conn.in_transaction:
        raise CaptureError("Baseline requires an enrolled caller transaction")
    # Legacy rows may have been added between adapter initialization and this
    # explicit bootstrap. Allocate their mappings before observing child scopes.
    with suppress_capture(conn):
        for row in conn.execute("SELECT id FROM papers").fetchall():
            _paper_id(conn, row[0])
    content = _content()
    supported = CORE | (set(content.CONTENT_TABLES) if content else set())
    for table in sorted(supported):
        for row in conn.execute(f'SELECT * FROM "{table}"').fetchall():
            value = dict(row)
            token = observe_content(conn, table, value)
            with expecting(conn, [token]):
                conn._mark(table, None, _json(value))


def _payload(conn, table, row):
    if table == "papers":
        authors = json.loads(row["authors_json"])
        return {
            "title": row["title"],
            "authors": [a.get("name") if isinstance(a, dict) else a for a in authors],
            **{key: row[key] for key in PAPER_COLUMNS - {"id", "title", "authors_json"}},
        }
    if table == "lists":
        return {"name": row["name"], "note": row["note"] or ""}
    if table == "list_papers":
        return {
            "list_id": row["list_id"],
            "paper_id": _paper_id(conn, row["paper_id"]),
            "citation": row["citation"],
            "added_at": row["added_at"],
        }
    content = _content()
    if content and table in content.CONTENT_TABLES:
        payload = content.content_payload(conn, table, row)
        kind, identity = content.content_identity(conn, table, row)
        sources = getattr(conn, "_capture_source_hashes", {})
        if kind == "research_content" and identity in sources:
            payload["source_document_hash"] = sources[identity]
            content.validate_payload(payload)
        return payload
    if table == "notes":
        if row["page"] is not None or row["anchor"] is not None or row["kind"] != "note":
            raise CaptureError("Anchored notes require the rich research adapter")
        return {"paper_id": _paper_id(conn, row["paper_id"]), "body": row["body"]}
    raise CaptureError("Unsupported research payload")


def _current(conn, client, kind, identity):
    own = client._optimistic_graph(conn)[2].get((kind, identity))
    if own:
        return own
    row = conn.execute(
        "SELECT operation FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
        (kind, identity),
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


@contextmanager
def suppress_capture(conn):
    """Private typed-action/remote projection scope on a capture connection."""
    if not isinstance(conn, CaptureConnection):
        yield
        return
    previous = conn._capture_trusted
    conn._capture_trusted = True
    try:
        yield
    finally:
        conn._capture_trusted = previous
        if not previous:
            conn._capture_graph_cache = None
        if enabled(conn):
            conn.set_authorizer(conn._authorize)


def _retain_candidate(conn, rows, observations):
    identity = _json(
        {
            "workspace": conn._capture_client.journal.workspace_id,
            "expected": [
                {k: row[k] for k in ("kind", "entity_id", "expected")} for row in observations
            ],
            "mutations": [
                {k: row[k] for k in ("table_name", "row_key", "after_json")} for row in rows
            ],
        }
    )
    candidate_id = hashlib.sha256(identity.encode()).hexdigest()
    candidate = _json({"observations": observations, "mutations": [dict(row) for row in rows]})
    sqlite3.Connection.rollback(conn)
    conn.execute(
        "INSERT OR IGNORE INTO research_capture_candidates VALUES(?,?)", (candidate_id, candidate)
    )
    sqlite3.Connection.commit(conn)
    conn._capture_failed = True
    raise StaleCaptureError(candidate_id)


def _flush(conn):
    rows = conn.execute(
        "SELECT * FROM research_capture_dirty ORDER BY table_name,row_key"
    ).fetchall()
    if not rows:
        return
    bases = conn.execute("SELECT * FROM research_capture_bases").fetchall()
    stale = [
        dict(row)
        for row in bases
        if row["expected"] is not None and row["expected"] != row["observed"]
    ]
    if stale:
        _retain_candidate(conn, rows, stale)
    content = _content()
    if content:
        content.enroll_content_identities(conn)
    client = conn._capture_client
    actions, orders = {}, set()
    for entry in rows:
        table = entry["table_name"]
        old = json.loads(entry["before_json"]) if entry["before_json"] else None
        new = json.loads(entry["after_json"]) if entry["after_json"] else None
        row = new or old
        keys = _keys(conn, table, row)
        if table == "kv":
            orders.add(keys[0])
            continue
        key = keys[0]
        actions[key] = ("put", _payload(conn, table, new)) if new else ("delete", {})
        if table == "lists":
            orders.add(keys[1])
            if new is None:
                actions[("list_order", row["id"])] = ("delete", {})
        if table == "list_papers":
            actions[keys[1]] = (
                (
                    "put",
                    {
                        "list_id": row["list_id"],
                        "paper_id": _paper_id(conn, row["paper_id"]),
                        **{k: row[k] for k in ("state", "delivered_at", "read_at")},
                    },
                )
                if new
                else ("delete", {})
            )
            orders.add(keys[2])

    def priority(item):
        (kind, _identity), (action, _payload_value) = item
        rank = {
            "paper": 0,
            "list": 0,
            "membership": 1,
            "note": 1,
            "research_content": 1,
            "reading_state": 2,
            "list_order": 3,
        }.get(kind, 1)
        return (0, rank) if action == "put" else (1, -rank)

    for (kind, identity), (action, payload) in sorted(actions.items(), key=priority):
        current = _current(conn, client, kind, identity)
        if (current is None or current["action"] == "delete") and action == "delete":
            continue
        if current and current["action"] == action and current["payload"] == payload:
            continue
        base = next(
            (row for row in bases if (row["kind"], row["entity_id"]) == (kind, identity)), None
        )
        requires_base = (kind in ("note", "research_content") and current is not None) or (
            kind == "research_content"
            and payload.get("feature")
            in {
                "dive",
                "close_reading",
                "context",
                "list_survey",
                "citation",
                "followup",
                "ai_highlight",
            }
        )
        if requires_base and (base is None or base["expected"] is None):
            _retain_candidate(conn, rows, [dict(base)] if base else [])
        # A SQL INSERT cannot silently restore an old graph incarnation.
        op = client.new_graph_operation_in(conn, kind, identity, payload, action=action)
        result = client.journal.apply_in(conn, op, client.writer)
        if result["applied"] and conn._capture_graph_cache is not None:
            client._overlay_optimistic(conn._capture_graph_cache, op)
    from paper_daily.sync_schema_v2 import membership_id

    for kind, identity in sorted(orders):
        if kind == "list_order":
            if not conn.execute("SELECT 1 FROM lists WHERE id=?", (identity,)).fetchone():
                continue
            ordered = [
                membership_id(identity, _paper_id(conn, r[0]))
                for r in conn.execute(
                    "SELECT paper_id FROM list_papers WHERE list_id=? ORDER BY position,paper_id",
                    (identity,),
                )
            ]
        else:
            ordered = [r[0] for r in conn.execute("SELECT id FROM lists ORDER BY created_at,id")]
            saved = conn.execute("SELECT value FROM kv WHERE key='lists.order'").fetchone()
            if saved:
                preference = json.loads(saved[0])
                if (
                    not isinstance(preference, list)
                    or any(not isinstance(v, str) for v in preference)
                    or len(set(preference)) != len(preference)
                ):
                    raise CaptureError("Invalid saved list order")
                ordered = [v for v in preference if v in ordered] + [
                    v for v in ordered if v not in preference
                ]
        op = client.new_order_operation_in(conn, kind, identity, ordered)
        current = _current(conn, client, kind, identity)
        if not current or current["action"] != "put" or current["payload"] != op["payload"]:
            result = client.journal.apply_in(conn, op, client.writer)
            if result["applied"] and conn._capture_graph_cache is not None:
                client._overlay_optimistic(conn._capture_graph_cache, op)
    conn.execute("DELETE FROM research_capture_dirty")
    conn.execute("DELETE FROM research_capture_bases")
