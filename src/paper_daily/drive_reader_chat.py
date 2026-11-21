"""Exchange saved reader turns through the selected personal Drive bibliography."""

import hashlib
import json
import sqlite3
from contextlib import closing
from uuid import UUID, uuid5

from paper_daily import research_chat
from paper_daily.drive_chat_removal_intent import reviewed_deletions
from paper_daily.drive_list_history import DriveListChat
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_paper_baseline import published_bindings
from paper_daily.drive_sync_files import MAX_INLINE, encode
from paper_daily.native_primary_publication import _WORKSPACE_MARKERS
from paper_daily.sync_content import content_id
from paper_daily.workspace_service import _tables

BASE_TABLE = ("CREATE TABLE IF NOT EXISTS drive_chat_bases(context,list_id,message,"
              "op,PRIMARY KEY(context,list_id,message))")

FIELDS = ("role", "body", "created_at", "page", "anchor", "exchange_id", "reply_to")


def _versions(records):
    latest, versions = {}, {}
    for op in records:
        data = op["payload"]
        key = data["key"]
        previous = latest.get(key)
        if (op["structure_revision"] or op["base_revision"] !=
                (previous["base_revision"] + 1 if previous else 0)
                or op["depends_on"] != (previous["operation_id"] if previous else None)
                or op["operation_id"] in versions or previous and (
                    previous["parents"] != op["parents"]
                    or previous["incarnation"] != op["incarnation"])):
            raise ListReviewRequired("Conversation history needs reconciliation")
        latest[key] = op
        versions[op["operation_id"]] = op
    return latest, versions


def _operation(history, payload, previous):
    scope, key = payload["scope"], payload["key"]
    identity = content_id(scope, "chat", key)
    op = dict(version=2, workspace_id=history.store.library_id, device_id=history.store.context,
              entity_type="research_content", entity_id=identity, incarnation=identity,
              action="put", structure_revision=0, depends_on=previous and previous["operation_id"],
              base_revision=previous["base_revision"] + 1 if previous else 0, payload=payload,
              parents=[dict(**scope, incarnation=history.paper_parents[scope["id"]])])
    op["operation_id"] = hashlib.sha256(encode(op, MAX_INLINE)).hexdigest()
    return op


LEGACY_TABLE = ("CREATE TABLE IF NOT EXISTS drive_chat_legacy_ids("
                "paper TEXT NOT NULL, local_id INTEGER NOT NULL, message TEXT NOT NULL,"
                "PRIMARY KEY(paper,local_id), UNIQUE(paper,message))")


def _legacy_key(conn, paper, idx, data, ordinals, *, enroll):
    known = conn.execute("SELECT message FROM drive_chat_legacy_ids WHERE paper=? AND local_id=?",
                         (paper, idx)).fetchone()
    if known:
        return known[0]
    if not enroll:
        return None
    digest = hashlib.sha256(encode(data, MAX_INLINE)).hexdigest()
    occurrence = ordinals.get((paper, digest), 0)
    while True:
        key = str(uuid5(UUID(paper), f"historical-chat:{digest}:{occurrence}"))
        occurrence += 1
        if not conn.execute("SELECT 1 FROM drive_chat_legacy_ids WHERE paper=? AND message=?",
                            (paper, key)).fetchone():
            break
    ordinals[paper, digest] = occurrence
    conn.execute("INSERT INTO drive_chat_legacy_ids VALUES(?,?,?)", (paper, idx, key))
    return key


def _local_turns(conn, list_id, papers, *, historical, enroll=False):
    selection = (" FROM chat c JOIN list_papers m ON c.paper_id=m.paper_id "
                 "WHERE m.list_id=?")
    size, count = conn.execute("SELECT sum(length(CAST(c.body AS BLOB)) + "
                               "coalesce(length(CAST(c.anchor AS BLOB)),0)),count(*)" + selection,
                               (list_id,)).fetchone()
    if (size or 0) > 8 * 1024**2 or count > 10000:
        raise ListReviewRequired("Conversation exceeds the supported history budget")
    result = {}
    if not count:
        return result
    tables = _tables(conn)
    linked = "research_chat_links" in tables
    columns = ("l.exchange_id,l.reply_to,l.source_hash,l.message_id" if linked
               else "NULL,NULL,NULL,NULL")
    join = "LEFT JOIN research_chat_links l ON l.local_id=c.id" if linked else ""
    ordinals = {}
    for row in conn.execute(
        f"SELECT c.id,c.paper_id,c.role,c.body,c.created_at,c.page,c.anchor,{columns} "
        f"FROM chat c {join} JOIN list_papers m ON c.paper_id=m.paper_id "
        "WHERE m.list_id=? ORDER BY c.id", (list_id,)
    ):
        idx, paper, *fields, source, key = row
        if paper not in papers:
            raise ListReviewRequired("Refresh the bibliography before syncing conversations")
        data = dict(zip(FIELDS, fields, strict=True))
        data["anchor"] = json.loads(data["anchor"]) if data["anchor"] is not None else None
        if key is None:
            if not historical:
                continue
            if "drive_chat_legacy_ids" not in tables:
                if not enroll:
                    continue
                conn.execute(LEGACY_TABLE)
                tables.add("drive_chat_legacy_ids")
            del data["exchange_id"], data["reply_to"]
            key = _legacy_key(conn, papers[paper], idx, data, ordinals, enroll=enroll)
            if key is None:
                continue
        result[key] = idx, dict(scope=dict(kind="paper", id=papers[paper]), feature="chat",
                                key=key, source_document_hash=source, data=data)
    return result


def _receive(conn, paper, payload, local, *, restore=False):
    data = payload["data"]
    fields = dict(data, anchor=json.dumps(data["anchor"], ensure_ascii=False)
                  if data["anchor"] is not None else None)
    if local is None and "exchange_id" not in data:
        if payload["source_document_hash"] is not None:
            raise ListReviewRequired("Historical message has unsupported document provenance")
        conn.execute(LEGACY_TABLE)
        identity = payload["scope"]["id"], payload["key"]
        mapped = conn.execute("SELECT local_id FROM drive_chat_legacy_ids WHERE paper=? "
                              "AND message=?", identity).fetchone()
        tables = _tables(conn)
        if restore and not mapped:
            raise ListReviewRequired("Historical message position is missing; review both copies")
        if mapped:
            occupied = conn.execute("SELECT 1 FROM chat WHERE id=?", mapped).fetchone()
            linked = "research_chat_links" in tables and conn.execute(
                "SELECT 1 FROM research_chat_links WHERE local_id=?", mapped).fetchone()
            if not restore or occupied or linked:
                raise ListReviewRequired("Historical message position changed; review both copies")
        idx = conn.execute("INSERT INTO chat(id,paper_id,role,body,created_at,page,anchor) "
                           "VALUES(:id,:paper,:role,:body,:created_at,:page,:anchor)",
                           dict(fields, id=mapped[0] if mapped else None, paper=paper)).lastrowid
        if not mapped:
            conn.execute("INSERT INTO drive_chat_legacy_ids VALUES(?,?,?)",
                         (identity[0], idx, identity[1]))
        if restore and "drive_chat_delete_actions" in tables:
            conn.execute("DELETE FROM drive_chat_delete_actions WHERE paper=? AND message=?",
                         (paper, identity[1]))
    elif local is None:
        research_chat.import_shared_turn(conn, dict(fields, paper_id=paper,
                                         message_id=payload["key"],
                                         source_hash=payload["source_document_hash"]))
    else:
        prior = local[1]
        if prior != dict(payload, data=dict(data, body=prior["data"]["body"])):
            raise ListReviewRequired("Conversation identity or source changed; review both copies")
        conn.execute("UPDATE chat SET body=? WHERE id=? AND paper_id=?",
                     (data["body"], local[0], paper))


def _restore_reviewed(conn, paper, payload):
    # Old or interrupted writers can leave the portable identity without a chat row.
    # Release only a matching orphan, in the same transaction as its new projection.
    if "research_chat_links" in _tables(conn):
        data = payload["data"]
        conn.execute(
            "DELETE FROM research_chat_links WHERE message_id=? AND exchange_id=? "
            "AND reply_to IS ? AND source_hash IS ? AND NOT EXISTS "
            "(SELECT 1 FROM chat WHERE chat.id=research_chat_links.local_id)",
            (payload["key"], data.get("exchange_id"), data.get("reply_to"),
             payload["source_document_hash"]))
    _receive(conn, paper, payload, None, restore=True)


def has_local_messages(store, list_id):
    from paper_daily.workspace_service import _read

    with _read(store.workspace.path) as conn:
        return conn.execute(
            "SELECT 1 FROM list_papers m JOIN chat c ON c.paper_id=m.paper_id "
            "WHERE m.list_id=? LIMIT 1", (list_id,)
        ).fetchone() is not None


def _kept_deletions(conn, scope):
    if "drive_chat_local_removals" not in _tables(conn):
        return {}
    return dict(conn.execute("SELECT message,op FROM drive_chat_local_removals "
                             "WHERE context=? AND list_id=?", scope))


def _previously_seen(conn, context, key):
    return conn.execute("SELECT 1 FROM drive_chat_bases WHERE context=? AND message=? LIMIT 1",
                        (context, key)).fetchone() is not None


def _concurrent_edit(value, remote, common):
    return (value is not None and remote["payload"] != value
            and (not common or value != common["payload"] and remote != common))


def review_chat(directory, store, list_id, revision, ticket, decision=None):
    """Re-read both versions and the exact device grant before applying a choice."""
    if decision is not None and decision[1] not in {"local", "remote"}:
        raise ValueError("Choose a displayed conversation version")
    history = DriveListChat(directory, store, list_id, revision=revision)
    _, records = history.changes(None, revision=revision)
    latest, versions = _versions(records)
    cards = []
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE" if decision else "BEGIN")
        history._check(revision)
        with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                     timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE" if decision else "BEGIN")
            if _tables(conn) & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Workspace changed before conversation review")
            mapping = published_bindings(settings, history.active_papers)
            historical = history.grant.startswith("chat-v2:")
            local = _local_turns(conn, list_id, {v: k for k, v in mapping.items()},
                                 historical=historical)
            bases = (dict(conn.execute("SELECT message,op FROM drive_chat_bases WHERE "
                                       "context=? AND list_id=?", (store.context, list_id)))
                     if "drive_chat_bases" in _tables(conn) else {})
            kept = _kept_deletions(conn, (store.context, list_id))
            actions = reviewed_deletions(conn, store.context, list_id)
            for key, remote in latest.items():
                ticket.check()
                if decision and key != decision[0]["identity"]:
                    continue
                other = remote["payload"]
                if not historical and "exchange_id" not in other["data"]:
                    continue
                paper = mapping.get(other["scope"]["id"])
                if not paper or not conn.execute(
                    "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?", (list_id, paper)
                ).fetchone():
                    continue
                idx, value = local.get(key, (None, None))
                common = versions.get(bases.get(key))
                if bases.get(key) and (not common or common["payload"]["key"] != key):
                    raise ListReviewRequired("Accepted conversation version is missing")
                if value is None:
                    if ("drive_chat_bases" not in _tables(conn)
                            or not _previously_seen(conn, store.context, key)
                            or kept.get(key) == remote["operation_id"]):
                        continue
                elif not _concurrent_edit(value, remote, common):
                    continue
                elif value != dict(other, data=dict(other["data"], body=value["data"]["body"])):
                    raise ListReviewRequired("Conversation identity or source changed")
                title, = conn.execute("SELECT title FROM papers WHERE id=?", (paper,)).fetchone()
                prompt = conn.execute(
                    "SELECT substr(c.body,1,100) FROM research_chat_links l JOIN chat c "
                    "ON c.id=l.local_id WHERE l.message_id=? AND c.paper_id=? AND c.role='user'",
                    (other["data"].get("reply_to") or key, paper)
                ).fetchone() if other["data"].get("exchange_id") and value is not None else None
                excerpt = " ".join((prompt[0] if prompt else other["data"]["body"][:100]).split())
                action = actions.get(key) if value is None else None
                cards.append(dict(removal_action=action if action and action[0] == paper else None,
                                  feature="chat", title=title, question=excerpt,
                                  identity=key, key=idx,
                                  context=store.context, grant=history.grant, list_id=list_id,
                                  revision=revision, base_id=bases.get(key),
                                  remote_id=remote["operation_id"], paper=paper,
                                  base=common["payload"]["data"] if common else None,
                                  local=value["data"] if value else None, remote=other["data"]))
            store._check()
            ticket.check()
            if decision is None:
                return cards
            if cards != [decision[0]]:
                raise ValueError("Conversation changed after review; compare both versions again")
            card = cards[0]
            conn.execute(BASE_TABLE)
            if card["local"] is None:
                if decision[1] == "remote":
                    _restore_reviewed(conn, card["paper"], latest[card["identity"]]["payload"])
                    if card["identity"] in kept:
                        conn.execute("DELETE FROM drive_chat_local_removals WHERE context=? "
                                     "AND list_id=? AND message=?",
                                     (store.context, list_id, card["identity"]))
                else:
                    conn.execute("CREATE TABLE IF NOT EXISTS drive_chat_local_removals("
                                 "context,list_id,message,op,PRIMARY KEY(context,list_id,message))")
                    conn.execute("INSERT OR REPLACE INTO drive_chat_local_removals VALUES(?,?,?,?)",
                                 (store.context, list_id, card["identity"], card["remote_id"]))
            elif decision[1] == "remote":
                conn.execute("UPDATE chat SET body=? WHERE id=? AND paper_id=?",
                             (card["remote"]["body"], card["key"], card["paper"]))
            conn.execute("INSERT OR REPLACE INTO drive_chat_bases VALUES(?,?,?,?)",
                         (store.context, list_id, card["identity"], card["remote_id"]))
            ticket.checkpoint(conn.commit)


def _check_initial_order(local, latest, bases):
    """An unversioned copy can only be extended when its existing prefix agrees."""
    def sequences(payloads):
        by_paper = {}
        for value in payloads:
            paper = value["scope"]["id"]
            by_paper.setdefault(paper, []).append(value["key"])
        return by_paper

    historical = {v["scope"]["id"] for _, v in local.values() if "exchange_id" not in v["data"]}
    historical.update(op["payload"]["scope"]["id"] for op in latest.values()
                      if "exchange_id" not in op["payload"]["data"])
    if not historical:
        return
    device = sequences(v for _, v in local.values())
    cloud = sequences(op["payload"] for op in latest.values())
    for paper in historical & device.keys() & cloud.keys():
        left, right = device[paper], cloud[paper]
        if any(key in bases for key in (*left, *right)
               if key in local and "exchange_id" not in local[key][1]["data"]):
            continue
        shared = min(len(left), len(right))
        if left[:shared] != right[:shared]:
            raise ListReviewRequired("Historical conversation copies differ before first sync")


def exchange_chat(directory, store, list_id, revision, ticket):
    history = DriveListChat(directory, store, list_id, revision=revision)
    head, records = history.changes(None, revision=revision)
    latest, versions = _versions(records)
    pending, conflicts = [], 0
    with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                 timeout=0.5)) as conn, conn:
        with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
            settings.execute("BEGIN IMMEDIATE")
            conn.execute("BEGIN IMMEDIATE")
            history._check(revision)
            if _tables(conn) & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Use the enrolled workspace for these conversations")
            mapping = published_bindings(settings, history.active_papers)
            historical = history.grant.startswith("chat-v2:")
            local = _local_turns(conn, list_id, {v: k for k, v in mapping.items()},
                                 historical=historical, enroll=historical)
            if not local and not latest:
                return 0
            conn.execute(BASE_TABLE)
            scope = (store.context, list_id)
            bases = dict(conn.execute("SELECT message,op FROM drive_chat_bases WHERE context=? "
                                      "AND list_id=?", scope))
            if historical:
                _check_initial_order(local, latest, bases)
            kept = _kept_deletions(conn, scope)
            for key in dict.fromkeys([*latest, *local, *bases]):
                ticket.check()
                turn, remote = local.get(key), latest.get(key)
                if remote and not historical and "exchange_id" not in remote["payload"]["data"]:
                    continue
                common = versions.get(bases.get(key))
                if bases.get(key) and (not common or common["payload"]["key"] != key):
                    raise ListReviewRequired("Accepted conversation version is missing")
                value = turn[1] if turn else None
                if remote and remote["payload"]["scope"]["id"] not in history.active_papers:
                    continue
                if remote and remote["payload"] != value:
                    if not turn and _previously_seen(conn, store.context, key):
                        if kept.get(key) != remote["operation_id"]:
                            conflicts += 1
                        continue
                    if _concurrent_edit(value, remote, common):
                        conflicts += 1
                        continue
                    if not turn or value == common["payload"]:
                        paper = mapping.get(remote["payload"]["scope"]["id"])
                        if not paper or not conn.execute(
                            "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?",
                            (list_id, paper)
                        ).fetchone():
                            raise ListReviewRequired("Conversation paper is missing")
                        _receive(conn, paper, remote["payload"], turn)
                        value = remote["payload"]
                if value is not None and (not remote or remote["payload"] != value):
                    pending.append(_operation(history, value, remote))
                if turn and key in kept:
                    conn.execute("DELETE FROM drive_chat_local_removals WHERE context=? "
                                 "AND list_id=? AND message=?", (*scope, key))
                if remote or turn:
                    anchor = remote["operation_id"] if remote else None
                    if key not in bases or bases[key] != anchor:
                        conn.execute("INSERT OR REPLACE INTO drive_chat_bases VALUES(?,?,?,?)",
                                     (*scope, key, anchor))
            version = conn.execute("PRAGMA data_version").fetchone()
            ticket.checkpoint(conn.commit)

        def check_source():
            ticket.check()
            if conn.execute("PRAGMA data_version").fetchone() != version:
                raise ListReviewRequired("Conversation changed during upload; retry")

        history.check_source = check_source
        batches, batch, size = [], [], 0
        for op in pending:
            length = len(encode(op, MAX_INLINE)) + 1
            if batch and (size + length > MAX_INLINE - 2048
                          or len(batch) >= history.max_operations):
                batches.append(batch)
                batch, size = [], 0
            batch.append(op)
            size += length
        if batch:
            batches.append(batch)
        pages = (head.generation if head else 0) + len(batches)
        if batches and (pages > history.max_pages or
                        sum(len(encode(op, MAX_INLINE)) + 1 for op in records + pending)
                        + pages * 2048 > history.max_bytes):
            raise ListReviewRequired("Conversation exceeds the readable Drive history budget")
        for batch in batches:
            head = history.append(head, batch, revision=revision)
            conn.execute("BEGIN IMMEDIATE")
            history._check(revision)
            conn.executemany("UPDATE drive_chat_bases SET op=? WHERE context=? AND list_id=? "
                             "AND message=?", [(op["operation_id"], *scope, op["payload"]["key"])
                                               for op in batch])
            ticket.checkpoint(conn.commit)
    return conflicts
