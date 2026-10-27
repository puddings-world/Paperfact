"""Device-local parent epochs for offline drafts, never portable sync incarnations.

Install before observing work. Existing legacy work cannot acquire retrospective
identity: applying it to a selected target requires explicit user reattachment.
"""

from paper_daily.sync_capture import suppress_capture

TABLE = "research_parent_lifecycle"
ROOTS = {"paper": "papers", "list": "lists"}
TRIGGERS = frozenset(
    f"paperfact_parent_{table}_{action}"
    for table in ROOTS.values()
    for action in ("insert", "delete", "identity")
)


def ensure_lifecycle(conn):
    """Initialize within the caller's transaction; never commit or enable sync."""
    if not conn.in_transaction:
        raise ValueError("Parent lifecycle installation requires a write transaction")
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (TABLE,)
    ).fetchone():
        triggers = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")]
        if not triggers >= TRIGGERS or columns != ["kind", "entity_id", "token", "active"]:
            raise ValueError("Parent lifecycle schema is incomplete; repair before editing")
        return
    with suppress_capture(conn):
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE}("
            "kind TEXT NOT NULL,entity_id TEXT NOT NULL,token TEXT NOT NULL,"
            "active INTEGER NOT NULL CHECK(active IN (0,1)),PRIMARY KEY(kind,entity_id))"
        )
        for kind, table in ROOTS.items():
            conn.execute(
                f"INSERT OR IGNORE INTO {TABLE} SELECT ?,id,lower(hex(randomblob(16))),1 "
                f"FROM {table}",
                (kind,),
            )
            insert = (
                f"INSERT INTO {TABLE}(kind,entity_id,token,active) "
                f"VALUES('{kind}',NEW.id,lower(hex(randomblob(16))),1) "
                "ON CONFLICT(kind,entity_id) DO UPDATE SET token=excluded.token,active=1;"
            )
            retire = f"UPDATE {TABLE} SET active=0 WHERE kind='{kind}' AND entity_id=OLD.id;"
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS paperfact_parent_{table}_insert "
                f"AFTER INSERT ON {table} BEGIN {insert} END"
            )
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS paperfact_parent_{table}_delete "
                f"AFTER DELETE ON {table} BEGIN {retire} END"
            )
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS paperfact_parent_{table}_identity "
                f"AFTER UPDATE OF id ON {table} WHEN OLD.id IS NOT NEW.id "
                f"BEGIN {retire} {insert} END"
            )


def parent_lifecycle(conn, kind, entity_id):
    if kind not in ROOTS or not isinstance(entity_id, str):
        raise ValueError("Invalid research parent identity")
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (TABLE,)
    ).fetchone()
    if not exists:
        return None
    row = conn.execute(
        f"SELECT token,active FROM {TABLE} WHERE kind=? AND entity_id=?", (kind, entity_id)
    ).fetchone()
    if row is None or not row[1]:
        return None
    token = row[0]
    if (
        not isinstance(token, str)
        or len(token) != 32
        or any(c not in "0123456789abcdef" for c in token)
    ):
        raise ValueError("Invalid research parent lifecycle token")
    return token


def validate_record(row):
    if not isinstance(row, dict) or set(row) != {"kind", "entity_id", "token", "active"}:
        raise ValueError("Invalid research parent lifecycle record")
    if row["kind"] not in ROOTS or not isinstance(row["entity_id"], str) or not row["entity_id"]:
        raise ValueError("Invalid research parent identity")
    if type(row["active"]) is not int or row["active"] not in (0, 1):
        raise ValueError("Invalid research parent activity")
    token = row["token"]
    if (
        not isinstance(token, str)
        or len(token) != 32
        or any(c not in "0123456789abcdef" for c in token)
    ):
        raise ValueError("Invalid research parent lifecycle token")
    return row
