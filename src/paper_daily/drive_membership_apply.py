"""Apply verified Drive membership retirements without deleting the shared paper."""

import sqlite3
from contextlib import closing

from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import encode
from paper_daily.native_primary_publication import _WORKSPACE_MARKERS
from paper_daily.workspace_service import _tables


class MembershipConflict(ListReviewRequired):
    def __init__(self, conn, local_id, kind, reason):
        title = conn.execute("SELECT title FROM papers WHERE id=?", (local_id,)).fetchone()
        self.detail = {"title": title[0] if title else "", "kind": kind}
        super().__init__(reason)


def _schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS drive_membership_watches("
        "context TEXT,list_id TEXT,member TEXT,creation TEXT NOT NULL,local_id TEXT NOT NULL,"
        "position INTEGER NOT NULL,live INTEGER NOT NULL DEFAULT 1,applied TEXT,"
        "PRIMARY KEY(context,list_id,member))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS drive_member_watch_local "
                 "ON drive_membership_watches(list_id,local_id)")
    # REPLACE may skip DELETE triggers on connections using SQLite defaults.
    conn.execute("CREATE TRIGGER IF NOT EXISTS drive_member_watch_insert AFTER INSERT "
                 "ON list_papers BEGIN UPDATE drive_membership_watches SET live=0 "
                 "WHERE list_id=NEW.list_id AND local_id=NEW.paper_id AND live=1; END")
    for event, suffix, condition in (
        ("DELETE", "delete", ""),
        ("UPDATE OF list_id,paper_id", "move",
         " WHEN NEW.list_id IS NOT OLD.list_id OR NEW.paper_id IS NOT OLD.paper_id"),
    ):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS drive_member_watch_{suffix} AFTER {event} "
                     f"ON list_papers{condition} BEGIN UPDATE drive_membership_watches SET live=0 "
                     "WHERE list_id=OLD.list_id AND local_id=OLD.paper_id AND live=1; END")


def receive_membership_changes(history, revision, ticket, *, accept_absent=None):
    """Watch current memberships before retirement; commit each batch with its receipts."""
    store, list_id = history.store, history.list_id
    retiring = history.retirements(revision)
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(revision)
        bindings = dict(settings.execute("SELECT remote_id,local_id FROM published_paper_ids")
                        ) if "published_paper_ids" in _tables(settings) else {}
        uri = store.workspace.path.as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            store._check(conn)
            tables = _tables(conn)
            if tables & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Use enrolled workspace sync for this library")
            head = history.paper_head
            prior = conn.execute(
                "SELECT head FROM drive_library_bibliographies WHERE context=? AND list_id=?",
                (store.context, list_id),
            ).fetchone() if "drive_library_bibliographies" in tables else None
            if head is None or prior != (encode(head.record()),):
                raise ListReviewRequired("Receive the bibliography before membership changes")
            if "drive_library_papers" in tables:
                for remote, local in conn.execute(
                    "SELECT remote_id,local_id FROM drive_library_papers WHERE context=?",
                    (store.context,),
                ):
                    if bindings.setdefault(remote, local) != local:
                        raise ListReviewRequired("Conflicting local paper bindings")
            _schema(conn)
            watches = {row[0]: row[1:] for row in conn.execute(
                "SELECT member,creation,local_id,position,live,applied "
                "FROM drive_membership_watches "
                "WHERE context=? AND list_id=?", (store.context, list_id))}
            applied = 0
            for index, (member, creation) in enumerate(history.creations.items()):
                ticket.check()
                payload = creation["payload"]
                local = bindings.get(payload["paper_id"])
                watch = watches.get(member)
                removal = retiring.get(member)
                if accept_absent and member != accept_absent["member"]:
                    continue
                if not local or (watch and watch[:2] != (creation["operation_id"], local)):
                    raise ListReviewRequired("Membership identity changed; review before applying")
                if watch and watch[4] is not None:
                    if not removal or watch[4] != removal["operation_id"]:
                        raise ListReviewRequired("Membership receipt differs from Drive")
                    continue
                if watch and not removal:
                    continue
                row = conn.execute(
                    "SELECT position,citation,added_at,state,read_at,delivered_at FROM list_papers "
                    "WHERE list_id=? AND paper_id=?", (list_id, local)).fetchone()
                intents = []
                if not row and removal and "drive_membership_removals" in tables:
                    intents = conn.execute(
                        "SELECT action_id,observed_head FROM drive_membership_removals "
                        "WHERE context=? AND list_id=? AND local_id=? AND added_at=? "
                        "AND action_id GLOB 'v2-*'",
                        (store.context, list_id, local, payload["added_at"]),
                    ).fetchall()
                observed = {"member": member, "removal": removal["operation_id"],
                            "local": local, "intents": sorted(i[0] for i in intents),
                            "revision": revision} if removal and not row else None
                if accept_absent and accept_absent != observed:
                    raise ListReviewRequired("List entry changed; review again")
                if observed:
                    end = history.boundaries.get(intents[0][1], 0) if len(intents) == 1 else 0
                    if accept_absent or end > 2 * index + 1 and (
                        removal["device_id"] == store.context
                        or intents[0][0].endswith("-" + creation["operation_id"])
                    ):
                        conn.execute(
                            "INSERT INTO drive_membership_watches "
                            "(context,list_id,member,creation,local_id,position,live,applied) "
                            "VALUES(?,?,?,?,?,-1,0,?) ON CONFLICT(context,list_id,member) "
                            "DO UPDATE SET live=0,applied=excluded.applied",
                            (store.context, list_id, member, creation["operation_id"], local,
                             removal["operation_id"]),
                        )
                        if intents:
                            conn.executemany("DELETE FROM drive_membership_removals "
                                             "WHERE context=? AND list_id=? AND action_id=?",
                                             ((store.context, list_id, i[0]) for i in intents))
                        applied += 1
                        continue
                if not row and not removal:
                    # Publication checks the local intent against the observed bibliography.
                    continue
                if not row or row[1:3] != (payload["citation"], payload["added_at"]):
                    if removal:
                        conflict = MembershipConflict(
                            conn, local, "changed" if row else "absent",
                            "Local membership differs; both versions retained")
                        if observed:
                            conflict.detail["observation"] = observed
                        raise conflict
                    raise ListReviewRequired("Local membership differs; both versions retained")
                if not removal:
                    conn.execute("INSERT INTO drive_membership_watches"
                                 "(context,list_id,member,creation,local_id,position) "
                                 "VALUES(?,?,?,?,?,?)", (store.context, list_id, member,
                                                        creation["operation_id"], local, row[0]))
                    continue
                pinned = conn.execute("SELECT 1 FROM pins WHERE scope=? AND paper_id=?",
                                      (list_id, local)).fetchone()
                # A pending local state can itself be an offline edit of an accepted read.
                # Keep the membership until those reading receipts are reconciled.
                reading_history = any(
                    table in tables and conn.execute(
                        f"SELECT 1 FROM {table} WHERE context=? AND list_id=? AND member=? LIMIT 1",
                        (store.context, list_id, member)).fetchone()
                    for table in ("drive_reading_bases", "drive_reading_sends")
                )
                if (not watch or not watch[3] or row[0] != watch[2] or pinned or reading_history
                        or row[3:] != ("pending", None, None)):
                    kind = "unverified" if not watch else "replaced" if not watch[3] else "edited"
                    raise MembershipConflict(conn, local, kind,
                                             "Review local reading edits or replacement membership")
                deleted = conn.execute("DELETE FROM list_papers WHERE list_id=? AND paper_id=?",
                                       (list_id, local))
                if deleted.rowcount != 1:
                    raise ListReviewRequired("Membership removal was not applied")
                conn.execute("UPDATE drive_membership_watches SET applied=? "
                             "WHERE context=? AND list_id=? AND member=?",
                             (removal["operation_id"], store.context, list_id, member))
                applied += 1
            if accept_absent and not applied:
                raise ListReviewRequired("List entry changed; review again")
            store._check(conn)
            ticket.checkpoint(conn.commit)
    return applied


def applied_retirements(directory, store, list_id, revision, head):
    """Exclude only matching Drive retirements already committed on this device."""
    from paper_daily.drive_membership_history import DriveMembershipChanges
    from paper_daily.drive_paper_baseline import BibliographyAdvanced
    from paper_daily.workspace_service import _read

    history = DriveMembershipChanges(directory, store, list_id, revision=revision)
    if history.paper_head != head:
        raise BibliographyAdvanced("Bibliography advanced while checking removals")
    retired = history.retirements(revision)
    if not retired:
        return set()
    with _read(store.workspace.path) as conn:
        if "drive_membership_watches" not in _tables(conn):
            return set()
        receipts = dict(conn.execute("SELECT member,applied FROM drive_membership_watches "
                                     "WHERE context=? AND list_id=? AND applied IS NOT NULL",
                                     (store.context, list_id)))
    return {history.creations[member]["payload"]["paper_id"] for member, op in retired.items()
            if receipts.get(member) == op["operation_id"]}
