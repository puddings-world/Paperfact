"""Exchange saved deep explanations without running an agent or adopting source evidence."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace

from paper_daily.drive_content_receipts import confirmed_sends, remember_batch
from paper_daily.drive_list_history import DriveListHistory, DriveListPapers
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import MAX_INLINE, encode
from paper_daily.native_primary_publication import _WORKSPACE_MARKERS
from paper_daily.sync_content import content_id
from paper_daily.sync_journal import canonical_operation
from paper_daily.workspace_service import _read, _tables


class DiveHistory(DriveListHistory):
    format = "paperfact.list-dive-history.v1"
    head_field = "dives_head"

    def __init__(self, directory, store, list_id, revision):
        super().__init__(directory, store, list_id)
        self.check_source = None
        self.grant = store.dive_grant(list_id, revision)
        if not self.grant:
            raise PermissionError("Enable explanation sync for this list")
        _, self.members = DriveListPapers(directory, store, list_id).members(revision)

    def _check(self, revision):
        if self.check_source:
            self.check_source()
        if self.store.dive_grant(self.list_id, revision) != self.grant:
            raise PermissionError("The explanation sync permission changed")

    def _validate_scope(self, records):
        for op in records:
            payload = op["payload"]
            if (op["entity_type"] != "research_content" or op["version"] != 2
                    or op["action"] != "put" or payload.get("feature") != "dive"
                    or payload["source_document_hash"] is not None):
                raise ValueError("Expected saved explanation text")
            paper = payload["scope"]["id"]
            if paper not in self.members or op["parents"] != [
                dict(kind="paper", id=paper, incarnation=self.members[paper])
            ] or op["incarnation"] != op["entity_id"]:
                raise ValueError("Explanation belongs to another paper incarnation")

    def publish_batch(self, head, batch, revision, ticket):
        # Validate the snapshot again after releasing the receive transaction.
        path = self.store.workspace.path
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            version = conn.execute("PRAGMA data_version").fetchone()

            def current():
                ticket.check()
                if version != conn.execute("PRAGMA data_version").fetchone():
                    raise ListReviewRequired("Research changed during explanation upload; retry")

            if _tables(conn) & _WORKSPACE_MARKERS:
                raise ListReviewRequired("The workspace changed during explanation sync")
            with _read(self.store.path) as settings:
                for op in batch:
                    payload = op["payload"]
                    local = settings.execute(
                        "SELECT local_id FROM published_paper_ids WHERE remote_id=?",
                        (payload["scope"]["id"],),
                    ).fetchone()
                    data = payload["data"]
                    row = conn.execute(
                        "SELECT body,written_at,spec FROM dives JOIN list_papers USING(paper_id) "
                        "WHERE list_id=? AND paper_id=?", (self.list_id, local[0])
                    ).fetchone() if local else None
                    if row != (data["body"], data["written_at"], data["spec"]):
                        raise ListReviewRequired("The selected explanation changed; retry")
            self.check_source = current
            try:
                return self.append(head, batch, revision=revision)
            finally:
                self.check_source = None

    def _advance(self, entry, head, records):
        return replace(entry, dives_head=head)


def _operation(history, paper, data, previous):
    scope = dict(kind="paper", id=paper)
    identity = content_id(scope, "dive", "main")
    op = dict(version=2, workspace_id=history.store.library_id, device_id=history.store.context,
              entity_type="research_content", entity_id=identity, incarnation=identity,
              action="put", structure_revision=0,
              base_revision=previous["base_revision"] + 1 if previous else 0,
              depends_on=previous["operation_id"] if previous else None,
              parents=[dict(**scope, incarnation=history.members[paper])],
              payload=dict(scope=scope, feature="dive", key="main", data=data,
                           source_document_hash=None))
    op["operation_id"] = hashlib.sha256(encode(op)).hexdigest()
    canonical_operation(op)
    return op


def _versions(records):
    latest, versions = {}, {}
    for op in records:
        paper = op["payload"]["scope"]["id"]
        previous = latest.get(paper)
        if (op["base_revision"] != (previous["base_revision"] + 1 if previous else 0)
                or op["depends_on"] != (previous["operation_id"] if previous else None)
                or op["structure_revision"] != 0 or op["operation_id"] in versions):
            raise ListReviewRequired("Explanation history needs review")
        latest[paper] = op
        versions[op["operation_id"]] = op
    return latest, versions


def _reconcile(history, records, revision, ticket, sent=()):
    store, list_id = history.store, history.list_id
    latest, versions = _versions(records)
    pending, conflicts = [], 0
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(revision)
        with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                     timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if _tables(conn) & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Use enrolled workspace sync for saved explanations")
            conn.execute("CREATE TABLE IF NOT EXISTS drive_dive_bases(context TEXT,list_id TEXT,"
                         "paper TEXT,op TEXT NOT NULL,PRIMARY KEY(context,list_id,paper))")
            local_ids = dict(settings.execute("SELECT remote_id,local_id FROM published_paper_ids"))
            largest, total = conn.execute(
                "SELECT max(length(CAST(body AS BLOB))),sum(length(CAST(body AS BLOB))) "
                "FROM dives d JOIN list_papers m ON m.paper_id=d.paper_id WHERE m.list_id=?",
                (list_id,),
            ).fetchone()
            if (largest or 0) > 200 * 1024 or (total or 0) > 8 * 1024**2:
                raise ListReviewRequired("Selected explanations exceed the supported size")
            rows = {local: (dict(body=body, written_at=stamp, spec=spec) if body is not None
                            else None) for local, body, stamp, spec in conn.execute(
                "SELECT m.paper_id,d.body,d.written_at,d.spec FROM list_papers m LEFT JOIN dives d "
                "ON d.paper_id=m.paper_id WHERE m.list_id=?", (list_id,)
            )}
            bases = dict(conn.execute("SELECT paper,op FROM drive_dive_bases WHERE context=? "
                                      "AND list_id=?", (store.context, list_id)))
            confirmed = confirmed_sends(conn, history, records)
            for paper in history.members:
                ticket.check()
                local = local_ids.get(paper)
                if local not in rows:
                    raise ListReviewRequired("Refresh this list before exchanging its explanations")
                data, current = rows[local], latest.get(paper)
                base = versions.get(bases.get(paper))
                if paper in bases and (not base or base["payload"]["scope"]["id"] != paper):
                    raise ListReviewRequired("A previously accepted explanation is missing")
                acknowledged = (confirmed.get((current["entity_id"], bases.get(paper)))
                                if current else None)
                if acknowledged:
                    base = acknowledged
                    conn.execute("INSERT OR REPLACE INTO drive_dive_bases VALUES(?,?,?,?)",
                                 (store.context, list_id, paper, base["operation_id"]))
                if current:
                    remote = current["payload"]["data"]
                    same_head = base and base["operation_id"] == current["operation_id"]
                    acknowledge = current["operation_id"] in sent or data == remote
                    if not acknowledge and data is not None and same_head:
                        pending.append(_operation(history, paper, data, current))
                        continue
                    if not acknowledge:
                        incoming = (data is None and not base
                                    and current["device_id"] != store.context)
                        if not incoming and not (base and data == base["payload"]["data"]):
                            conflicts += 1
                            continue
                        conn.execute("INSERT INTO dives(paper_id,body,written_at,spec) "
                                     "VALUES(?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET "
                                     "body=excluded.body,written_at=excluded.written_at,"
                                     "spec=excluded.spec",
                                     (local, remote["body"], remote["written_at"], remote["spec"]))
                    if not same_head:
                        conn.execute("INSERT OR REPLACE INTO drive_dive_bases VALUES(?,?,?,?)",
                                     (store.context, list_id, paper, current["operation_id"]))
                elif data is not None:
                    pending.append(_operation(history, paper, data, None))
            store._check()
            ticket.checkpoint(conn.commit)
    return pending, conflicts


def review_dives(directory, store, list_id, revision, ticket, decision=None):
    history = DiveHistory(directory, store, list_id, revision)
    _, records = history.changes(None, revision=revision)
    latest, versions = _versions(records)
    if decision is not None and decision[1] not in ("local", "remote"):
        raise ValueError("Choose an observed explanation version")
    cards = []
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(revision)
        with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                     timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE" if decision else "BEGIN")
            tables = _tables(conn)
            if tables & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Workspace binding changed")
            if "drive_dive_bases" in tables:
                for paper, op in latest.items():
                    ticket.check()
                    if decision and decision[0]["identity"] != paper:
                        continue
                    mapped = settings.execute("SELECT local_id FROM published_paper_ids "
                                              "WHERE remote_id=?", (paper,)).fetchone()
                    if not mapped:
                        continue
                    row = conn.execute(
                        "SELECT p.title,d.body,d.written_at,d.spec,b.op FROM list_papers m "
                        "JOIN papers p ON p.id=m.paper_id JOIN dives d ON d.paper_id=p.id "
                        "LEFT JOIN drive_dive_bases b ON b.context=? AND b.list_id=m.list_id "
                        "AND b.paper=? WHERE m.list_id=? AND p.id=? "
                        "AND length(CAST(d.body AS BLOB))<=204800",
                        (store.context, paper, list_id, mapped[0]),
                    ).fetchone()
                    if not row or row[4] == op["operation_id"]:
                        continue
                    base = versions.get(row[4])
                    if row[4] and (not base or base["payload"]["scope"]["id"] != paper):
                        raise ListReviewRequired("Common explanation revision is unavailable")
                    local = dict(body=row[1], written_at=row[2], spec=row[3])
                    remote = op["payload"]["data"]
                    common = base["payload"]["data"] if base else None
                    if local in (remote, common):
                        continue
                    cards.append(dict(feature="dive", title=row[0], identity=paper, key=mapped[0],
                                      context=store.context, grant=history.grant, list_id=list_id,
                                      remote_id=op["operation_id"], base_id=row[4],
                                      base=common, local=local, remote=remote))
            store._check()
            ticket.check()
            if decision is None:
                return cards
            if cards != [decision[0]]:
                raise ValueError("Explanation changed after review. Compare its current versions.")
            card = cards[0]
            if decision[1] == "remote":
                data = card["remote"]
                conn.execute("UPDATE dives SET body=?,written_at=?,spec=? WHERE paper_id=?",
                             (data["body"], data["written_at"], data["spec"], card["key"]))
            conn.execute("INSERT OR REPLACE INTO drive_dive_bases(context,list_id,paper,op) "
                         "VALUES(?,?,?,?)", (store.context, list_id, card["identity"],
                                              card["remote_id"]))
            ticket.checkpoint(conn.commit)


def exchange_dives(directory, store, list_id, revision, ticket):
    history = DiveHistory(directory, store, list_id, revision)
    if not history.members:
        return 0
    head, records = history.changes(None, revision=revision)
    pending, conflicts = _reconcile(history, records, revision, ticket)
    batches, batch, size = [], [], 0
    used = sum(len(encode(op)) + 1 for op in records)
    for op in pending:
        length = len(encode(op)) + 1
        if len(batch) == 100 or size + length > MAX_INLINE - 2048:
            batches.append(batch)
            batch, size = [], 0
        batch.append(op)
        size += length
        used += length
    if batch:
        batches.append(batch)
    generations = (head.generation if head else 0) + len(batches)
    if batches and (generations > 100 or used + generations * 2048 > 8 * 1024**2):
        raise ListReviewRequired("The selected explanations exceed the readable history budget")
    for batch in batches:
        ticket.check()
        remember_batch(history, batch, revision, ticket)
        head = history.publish_batch(head, batch, revision, ticket)
        records.extend(batch)
        _reconcile(history, records, revision, ticket, {op["operation_id"] for op in batch})
    return conflicts
