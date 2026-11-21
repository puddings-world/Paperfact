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


def arm_present_review(store, list_id, detail, ticket):
    """Invalidate a displayed decision even after an identical delete/reinsert."""
    from uuid import uuid4

    with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                 timeout=0.5)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        store._check(conn)
        if _tables(conn) & _WORKSPACE_MARKERS:
            raise ListReviewRequired("Use enrolled workspace sync for this library")
        local = detail["observation"]["local"]
        conn.execute("CREATE TABLE IF NOT EXISTS drive_member_reviews(list_id,local_id,token, "
                     "PRIMARY KEY(list_id,local_id))")
        for table, scope in (("list_papers", "list_id"), ("pins", "scope")):
            for event, refs in (("INSERT", ["NEW"]), ("DELETE", ["OLD"]),
                                ("UPDATE", ["OLD", "NEW"])):
                conditions = " OR ".join(f"(list_id={ref}.{scope} AND local_id={ref}.paper_id)"
                                         for ref in refs)
                conn.execute(f"CREATE TRIGGER IF NOT EXISTS drive_review_{table}_{event} AFTER "
                             f"{event} ON {table} BEGIN DELETE FROM drive_member_reviews WHERE "
                             f"{conditions}; END")
        token = uuid4().hex
        conn.execute("INSERT OR REPLACE INTO drive_member_reviews VALUES(?,?,?)",
                     (list_id, local, token))
        ticket.checkpoint(conn.commit)
        detail["observation"]["token"] = token


def keep_reviewed_membership(history, revision, observation, ticket):
    """Publish the reviewed local membership only while its row and binding still match."""
    from paper_daily.drive_membership_history import restoration_operation
    from paper_daily.workspace_service import _read

    store, list_id = history.store, history.list_id
    if observation.get("revision") != revision or not observation.get("token"):
        raise ListReviewRequired("Review the current local entry before keeping it")
    head, latest, retired = history.versions(revision)
    member = observation["member"]
    removal = retired.get(member)
    if not removal or removal["operation_id"] != observation["removal"]:
        raise ListReviewRequired("The remote removal changed; review again")
    creation = latest[member]
    local = observation["local"]

    def check_review():
        ticket.check()
        with _read(store.path) as settings:
            paper = creation["payload"]["paper_id"]
            published = settings.execute(
                "SELECT local_id FROM published_paper_ids WHERE remote_id=?",
                (paper,)).fetchone() if "published_paper_ids" in _tables(settings) else None
        with _read(store.workspace.path) as conn:
            store._check(conn)
            tables = _tables(conn)
            if tables & _WORKSPACE_MARKERS or "drive_member_reviews" not in tables:
                raise ListReviewRequired("The reviewed workspace changed")
            received = conn.execute(
                "SELECT local_id FROM drive_library_papers WHERE context=? AND remote_id=?",
                (store.context, paper)).fetchone() if "drive_library_papers" in tables else None
            token = conn.execute("SELECT token FROM drive_member_reviews WHERE list_id=? "
                                 "AND local_id=?", (list_id, local)).fetchone()
            row = conn.execute("SELECT position,citation,added_at,state,read_at,delivered_at "
                               "FROM list_papers WHERE list_id=? AND paper_id=?",
                               (list_id, local)).fetchone()
            pin = conn.execute("SELECT pinned_at FROM pins WHERE scope=? AND paper_id=?",
                               (list_id, local)).fetchone()
        bindings = {entry for entry in (received, published) if entry}
        if (bindings != {(local,)} or token != (observation["token"],) or not row
                or row != observation["row"] or pin != observation["pin"]):
            raise ListReviewRequired("Local entry changed; review again")

    check_review()
    row = observation["row"]
    operation = restoration_operation(creation, removal, store.context,
                                      citation=row[1], added_at=row[2])
    uri = store.workspace.path.as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        check_review()
        conn.execute("CREATE TABLE IF NOT EXISTS drive_membership_keeps("
                     "context TEXT,list_id TEXT,member TEXT,operation TEXT,token TEXT,"
                     "PRIMARY KEY(context,list_id,member))")
        conn.execute("INSERT OR REPLACE INTO drive_membership_keeps VALUES(?,?,?,?,?)",
                     (store.context, list_id, member, operation["operation_id"],
                      observation["token"]))
        ticket.checkpoint(conn.commit)
    return history.restore(head, operation, revision=revision, check_review=check_review)


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


def _reset_reading_receipts(conn, store, list_id, member, local):
    tables = _tables(conn)
    for table in ("drive_reading_bases", "drive_reading_sends"):
        if table in tables:
            conn.execute(f"DELETE FROM {table} WHERE context=? AND list_id=? AND member=?",
                         (store.context, list_id, member))
    if "drive_reading_members" in tables:
        conn.execute("DELETE FROM drive_reading_members WHERE context=? AND list_id=? "
                     "AND paper_id=?",
                     (store.context, list_id, local))


def _adopt_kept(conn, store, list_id, creation, local):
    key = (store.context, list_id, creation["entity_id"])
    approved = conn.execute(
        "SELECT 1 FROM drive_membership_keeps k JOIN drive_member_reviews r "
        "ON r.list_id=k.list_id AND r.token=k.token WHERE k.context=? AND k.list_id=? "
        "AND k.member=? AND k.operation=? AND r.local_id=?", (*key, creation["operation_id"], local)
    ).fetchone()
    if not approved:
        return False
    row = conn.execute("SELECT position,citation,added_at FROM list_papers "
                       "WHERE list_id=? AND paper_id=?", (list_id, local)).fetchone()
    payload = creation["payload"]
    if not row or row[1:] != (payload["citation"], payload["added_at"]):
        raise ListReviewRequired("Local entry changed after keeping it; review again")
    conn.execute("INSERT OR REPLACE INTO drive_membership_watches "
                 "(context,list_id,member,creation,local_id,position) VALUES(?,?,?,?,?,?)",
                 (*key, creation["operation_id"], local, row[0]))
    conn.execute("DELETE FROM drive_membership_keeps WHERE context=? AND list_id=? AND member=?",
                 key)
    return True


def _restore_removed(conn, store, list_id, member, creation, local):
    payload = creation["payload"]
    existing = conn.execute("SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?",
                            (list_id, local)).fetchone()
    if existing:
        raise ListReviewRequired("Local entry was added again; review before restoring")
    position, = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM list_papers "
                             "WHERE list_id=?", (list_id,)).fetchone()
    conn.execute("INSERT INTO list_papers(list_id,paper_id,position,citation,added_at) "
                 "VALUES(?,?,?,?,?)",
                 (list_id, local, position, payload["citation"], payload["added_at"]))
    conn.execute("UPDATE drive_membership_watches SET creation=?,position=?,live=1,"
                 "applied=NULL WHERE context=? AND list_id=? AND member=?",
                 (creation["operation_id"], position, store.context, list_id, member))


def receive_membership_changes(history, revision, ticket, *, accept_removal=None):
    """Watch current memberships before retirement; commit each batch with its receipts."""
    store, list_id = history.store, history.list_id
    _, creations, retiring = history.versions(revision)
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
            already_confirmed = False
            for index, (member, creation) in enumerate(creations.items()):
                ticket.check()
                payload = creation["payload"]
                local = bindings.get(payload["paper_id"])
                watch = watches.get(member)
                removal = retiring.get(member)
                if accept_removal and member != accept_removal["member"]:
                    continue
                if (local and not removal and not accept_removal
                        and "drive_membership_keeps" in tables
                        and creation["device_id"] == store.context
                        and _adopt_kept(conn, store, list_id, creation, local)):
                    _reset_reading_receipts(conn, store, list_id, member, local)
                    applied += 1
                    continue
                if (local and watch and watch[1] == local and watch[4]
                        and watch[4] == creation["depends_on"] and not removal
                        and not accept_removal):
                    _restore_removed(conn, store, list_id, member, creation, local)
                    _reset_reading_receipts(conn, store, list_id, member, local)
                    applied += 1
                    continue
                if not local or (watch and watch[:2] != (creation["operation_id"], local)):
                    raise ListReviewRequired("Membership identity changed; review before applying")
                if watch and watch[4] is not None:
                    if not removal or watch[4] != removal["operation_id"]:
                        raise ListReviewRequired("Membership receipt differs from Drive")
                    if accept_removal:
                        # A previous confirmation can commit before the follow-up sync fails.
                        restored = conn.execute("SELECT 1 FROM list_papers WHERE list_id=? "
                                                "AND paper_id=?", (list_id, local)).fetchone()
                        already_confirmed = (
                            not restored and accept_removal["revision"] == revision
                            and accept_removal["removal"] == watch[4]
                            and accept_removal["local"] == local
                        )
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
                present = None
                if row and removal:
                    present = {"member": member, "removal": removal["operation_id"],
                               "local": local, "revision": revision, "row": row,
                               "pin": conn.execute("SELECT pinned_at FROM pins WHERE scope=? "
                                                   "AND paper_id=?", (list_id, local)).fetchone()}
                if accept_removal and present and "token" in accept_removal:
                    token = conn.execute("SELECT token FROM drive_member_reviews WHERE list_id=? "
                                         "AND local_id=?", (list_id, local)).fetchone()
                    if token and accept_removal == dict(present, token=token[0]):
                        conn.execute("DELETE FROM list_papers WHERE list_id=? AND paper_id=?",
                                     (list_id, local))
                        observed = accept_removal
                if accept_removal and accept_removal != observed:
                    raise ListReviewRequired("List entry changed; review again")
                if observed:
                    end = history.boundaries.get(intents[0][1], 0) if len(intents) == 1 else 0
                    if accept_removal or end > 2 * index + 1 and (
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
                        conflict.detail["observation"] = observed or present
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
                    conflict = MembershipConflict(
                        conn, local, kind, "Review local reading edits or replacement membership")
                    conflict.detail["observation"] = present
                    raise conflict
                deleted = conn.execute("DELETE FROM list_papers WHERE list_id=? AND paper_id=?",
                                       (list_id, local))
                if deleted.rowcount != 1:
                    raise ListReviewRequired("Membership removal was not applied")
                conn.execute("UPDATE drive_membership_watches SET applied=? "
                             "WHERE context=? AND list_id=? AND member=?",
                             (removal["operation_id"], store.context, list_id, member))
                applied += 1
            if accept_removal and not (applied or already_confirmed):
                raise ListReviewRequired("List entry changed; review again")
            store._check(conn)
            ticket.checkpoint(conn.commit)
    return applied


def received_membership_versions(directory, store, list_id, revision, head):
    """Exclude only matching Drive retirements already committed on this device."""
    from paper_daily.drive_membership_history import membership_history
    from paper_daily.drive_paper_baseline import BibliographyAdvanced
    from paper_daily.workspace_service import _read

    history = membership_history(directory, store, list_id, revision=revision)
    if history.paper_head != head:
        raise BibliographyAdvanced("Bibliography advanced while checking removals")
    _, versions, retired = history.versions(revision)
    if not retired:
        return versions, set()
    with _read(store.workspace.path) as conn:
        if "drive_membership_watches" not in _tables(conn):
            return versions, set()
        receipts = dict(conn.execute("SELECT member,applied FROM drive_membership_watches "
                                     "WHERE context=? AND list_id=? AND applied IS NOT NULL",
                                     (store.context, list_id)))
    applied = {versions[member]["payload"]["paper_id"] for member, op in retired.items()
               if receipts.get(member) == op["operation_id"]}
    return versions, applied
