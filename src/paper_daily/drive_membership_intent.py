"""Device-local evidence of an explicit removal from an observed Drive bibliography."""

from uuid import uuid4

from paper_daily.workspace_service import _tables


def remove_selected(conn, list_id, paper_ids):
    """Use the caller's transaction for both the membership edit and its local evidence."""
    conn.execute("BEGIN IMMEDIATE")
    tables = _tables(conn)
    scopes = []
    if "drive_library_bibliographies" in tables and "research_capture_binding" not in tables:
        scopes = conn.execute(
            "SELECT context,head FROM drive_library_bibliographies WHERE list_id=?", (list_id,)
        ).fetchall()
    delete = "DELETE FROM list_papers WHERE list_id=? AND paper_id=?"
    keys = dict.fromkeys(paper_ids)
    if not scopes:
        return conn.executemany(delete, ((list_id, key) for key in keys)).rowcount

    removed = 0
    for key in keys:
        row = conn.execute(delete + " RETURNING added_at", (list_id, key)).fetchone()
        if row is None:
            continue
        if not removed:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drive_membership_removals("
                "context TEXT NOT NULL,list_id TEXT NOT NULL,action_id TEXT NOT NULL,"
                "local_id TEXT NOT NULL,added_at TEXT NOT NULL,observed_head BLOB NOT NULL,"
                "PRIMARY KEY(context,list_id,action_id))"
            )
        action_id = str(uuid4())
        conn.executemany(
            "INSERT INTO drive_membership_removals VALUES(?,?,?,?,?,?)",
            ((context, list_id, action_id, key, row[0], head) for context, head in scopes),
        )
        removed += 1
    return removed


def observed_removals(store, list_id, head, missing_dates):
    """Match local requests to missing members of this exact verified Drive revision."""
    from paper_daily.drive_sync_files import encode
    from paper_daily.workspace_service import _read

    with _read(store.workspace.path) as conn:
        if "drive_membership_removals" not in _tables(conn):
            return 0
        requested = {tuple(row) for row in conn.execute(
            "SELECT local_id,added_at FROM drive_membership_removals "
            "WHERE context=? AND list_id=? AND observed_head=?",
            (store.context, list_id, encode(head.record())),
        )}
    if not requested:
        return 0
    with _read(store.path) as settings:
        if "published_paper_ids" not in _tables(settings):
            return 0
        matched = set()
        for local_id, added_at in requested:
            binding = settings.execute(
                "SELECT remote_id FROM published_paper_ids WHERE local_id=?", (local_id,)
            ).fetchone()
            if binding and missing_dates.get(binding[0]) == added_at:
                matched.add(binding[0])
        return len(matched)
