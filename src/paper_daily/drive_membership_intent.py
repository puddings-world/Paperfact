"""Device-local evidence of an explicit removal from an observed Drive bibliography."""

from uuid import uuid4

from paper_daily.drive_list_records import ListReviewRequired
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS drive_removal_local "
                "ON drive_membership_removals(list_id,local_id)"
            )
            # Restoring a row by UI, import or another writer withdraws any still-local
            # removal for that pair. SQLite rolls this back if the re-addition fails.
            for event, suffix, condition in (
                ("INSERT", "insert", ""),
                ("UPDATE OF list_id,paper_id", "move",
                 " WHEN NEW.list_id IS NOT OLD.list_id OR NEW.paper_id IS NOT OLD.paper_id"),
            ):
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS drive_withdraw_removal_{suffix} AFTER {event} "
                    f"ON list_papers{condition} BEGIN DELETE FROM drive_membership_removals "
                    "WHERE list_id=NEW.list_id AND local_id=NEW.paper_id; END"
                )
        # Legacy UUID-only actions have no continuous evidence of non-restoration.
        action_id = f"v2-{uuid4()}"
        conn.executemany(
            "INSERT INTO drive_membership_removals VALUES(?,?,?,?,?,?)",
            ((context, list_id, action_id, key, row[0], head) for context, head in scopes),
        )
        removed += 1
    return removed


class MembershipRemovalReview(ListReviewRequired):
    def __init__(self, missing, operations):
        self.missing = missing
        self.operations = operations
        super().__init__(
            f"List has {missing} removed papers; {len(operations)} explicitly removed "
            "on this device. Drive retains its copy pending review"
        )


def observed_removals(store, list_id, boundaries, candidates):
    """Prepare removals only when the recorded prefix contains the original member."""
    from paper_daily.drive_membership_history import removal_operation
    from paper_daily.workspace_service import _read

    with _read(store.workspace.path) as conn:
        if "drive_membership_removals" not in _tables(conn):
            return []
        requested = {tuple(row) for row in conn.execute(
            "SELECT local_id,added_at,observed_head FROM drive_membership_removals "
            "WHERE context=? AND list_id=? AND action_id GLOB 'v2-*'",
            (store.context, list_id),
        )}
    if not requested:
        return []
    with _read(store.path) as settings:
        if "published_paper_ids" not in _tables(settings):
            return []
        matched = {}
        for local_id, added_at, observed_head in requested:
            end = boundaries.get(observed_head)
            if end is None:
                continue
            binding = settings.execute(
                "SELECT remote_id FROM published_paper_ids WHERE local_id=?", (local_id,)
            ).fetchone()
            member = candidates.get(binding[0]) if binding else None
            if member and member[0] < end and member[1]["payload"]["added_at"] == added_at:
                matched[binding[0]] = removal_operation(member[1], store.context)
        return [matched[key] for key in sorted(matched)]
