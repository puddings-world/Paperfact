"Closed Inbox preservation; source receipts never become receiver write authority."

from __future__ import annotations

from uuid import UUID, uuid4, uuid5

from paper_daily import inbox_content as content

RESEARCH = {content.ITEMS, content.HISTORY, content.CANDIDATES}
DETACHED_ORIGINALS = frozenset({content.ITEMS, content.HISTORY})
PROTOCOL = {table: content.COLUMNS[table] for table in (content.OWNER, content.REQUESTS)}


class Records:
    def __init__(self):
        self.rows = {table: {} for table in content.COLUMNS}
        self.bytes = 0

    def add(self, table, row):
        content.validate_row(table, row)
        identity = row[content.COLUMNS[table].split()[0]]
        if identity in self.rows[table]:
            raise ValueError("Duplicate Inbox recovery identity")
        self.rows[table][identity] = row
        self.bytes += len(content.encode(row).encode("utf-8"))
        if self.bytes > 64 * 1024**2 or sum(map(len, self.rows.values())) > 100_000:
            raise ValueError("Inbox recovery exceeds its metadata bound")

    def finish(self):
        items, history = self.rows[content.ITEMS], self.rows[content.HISTORY]
        owners = self.rows[content.OWNER]
        for row in history.values():
            if row["item_id"] not in items:
                raise ValueError("Inbox history has no workspace-owned item")
        for row in items.values():
            old = history.get(row["version"])
            if (
                old is None
                or any(old[key] != row[key] for key in ("body_json", "incarnation", "active"))
                or old["item_id"] != row["id"]
            ):
                raise ValueError("Inbox current version has no matching retained history")
        for row in self.rows[content.REQUESTS].values():
            if len(owners) != 1 or owners[1]["token"] != row["owner_token"]:
                raise ValueError("Inbox request belongs to another workspace lifetime")
            result = content.decode(row["result_json"])
            if result["status"] == "saved":
                retained = history.get(result["version"])
                if (
                    retained is None
                    or retained["item_id"] != result["item_id"]
                    or result["candidate_id"] is not None
                ):
                    raise ValueError("Inbox request has no matching saved version")
            else:
                retained = self.rows[content.CANDIDATES].get(result["candidate_id"])
                if (
                    retained is None
                    or retained["item_id"] != result["item_id"]
                    or (
                        result["status"] == "resolved"
                        and retained["resolved_by"] != result["version"]
                    )
                ):
                    raise ValueError("Inbox conflict receipt has no retained proposal")


def fresh_receiver_in(conn, *, recovery_device=None):
    "Explicit detached restore/copy only. Retain texts; replace live version authority."
    if not conn.in_transaction:
        raise ValueError("Inbox receiver adoption needs its caller transaction")
    content.initialize(conn)
    rows = conn.execute(f"SELECT * FROM {content.ITEMS} ORDER BY id").fetchall()
    if not rows:
        return {}
    if (
        conn.execute(f"SELECT 1 FROM {content.OWNER}").fetchone()
        or conn.execute(f"SELECT 1 FROM {content.REQUESTS}").fetchone()
    ):
        raise ValueError("Source Inbox receipt authority must remain archive-only")
    namespace = UUID(content.uuid(recovery_device)) if recovery_device is not None else None
    owner = str(uuid5(namespace, "inbox-detached-owner-v1")) if namespace else str(uuid4())
    conn.execute(f"INSERT INTO {content.OWNER} VALUES(1,?)", (owner,))
    prepared = {}
    for raw in rows:
        row = dict(zip(content.COLUMNS[content.ITEMS].split(), raw, strict=True))
        content.validate_row(content.ITEMS, row)
        operation_id = (
            str(uuid5(namespace, "inbox-detached-item-v1:" + row["id"] + ":" + row["version"]))
            if namespace
            else str(uuid4())
        )
        operation = dict(
            version=2,
            operation_id=operation_id,
            workspace_id=owner,
            device_id="local-inbox-recovery",
            entity_type="inbox_item",
            entity_id=row["id"],
            action="put" if row["active"] else "delete",
            base_revision=0,
            depends_on=None,
            parents=[],
            structure_revision=0,
            incarnation=operation_id,
            payload=content.decode(row["body_json"]) if row["active"] else {},
        )
        content.write(conn, operation)
        prepared[row["id"]] = operation
    return prepared


def verify_detached_projection(conn, original, recovery_device):
    """Compare only the exact helper-derived receiver view of hash-verified originals.

    The caller must verify each original table against its declared backup hash.
    This reader grants no write authority and never accepts additional local work.
    """
    import sqlite3
    from contextlib import closing

    if set(original) != DETACHED_ORIGINALS:
        raise ValueError("Detached Inbox originals require a fresh restore from backup")
    content.uuid(recovery_device)
    required = {content.ITEMS, content.HISTORY, content.OWNER, content.REQUESTS}
    if not required <= {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}:
        raise ValueError("Detached Inbox receiver tables are incomplete")
    original_records = Records()
    for table in (content.ITEMS, content.HISTORY):
        for row in original[table]:
            original_records.add(table, row)
    original_records.finish()
    with closing(sqlite3.connect(":memory:")) as expected:
        expected.execute("BEGIN")
        content.initialize(expected)
        for table in (content.ITEMS, content.HISTORY):
            for row in original[table]:
                content.validate_row(table, row)
                columns = content.COLUMNS[table].split()
                expected.execute(
                    'INSERT INTO "' + table + '" VALUES(' + ",".join("?" for _ in columns) + ")",
                    [row[column] for column in columns],
                )
        fresh_receiver_in(expected, recovery_device=recovery_device)
        for table in (content.ITEMS, content.HISTORY, content.OWNER):
            columns = content.COLUMNS[table].split()
            count = expected.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
            if conn.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] != count:
                raise ValueError("Detached Inbox projection row count changed")
            # An exact match cannot contain a field larger than its expected
            # counterpart's maximum. Reject oversized tampering before fetching.
            for column in columns:
                largest = expected.execute(
                    'SELECT COALESCE(max(length(CAST("'
                    + column
                    + '" AS BLOB))),0) FROM "'
                    + table
                    + '"'
                ).fetchone()[0]
                if conn.execute(
                    'SELECT 1 FROM "'
                    + table
                    + '" WHERE length(CAST("'
                    + column
                    + '" AS BLOB))>? LIMIT 1',
                    (largest,),
                ).fetchone():
                    raise ValueError("Detached Inbox projection field size changed")

            def records(database, columns=columns, table=table):
                result = []
                for raw in database.execute('SELECT * FROM "' + table + '"'):
                    row = dict(zip(columns, raw, strict=True))
                    content.validate_row(table, row)
                    result.append(content.encode(row))
                return sorted(result)

            if records(conn) != records(expected):
                raise ValueError(
                    "Detached Inbox differs from its exact original/receiver projection"
                )
        if conn.execute('SELECT 1 FROM "' + content.REQUESTS + '" LIMIT 1').fetchone():
            raise ValueError(
                "Detached Inbox has new local requests; original authority is archive-only"
            )


def enroll_in(conn, client, request_id):
    "Publish only the explicitly copied current roots; old receipts stay archived."
    if not conn.in_transaction:
        raise ValueError("Inbox enrollment needs its caller transaction")
    request = UUID(request_id)
    prepared = {}
    for row in conn.execute(
        f"SELECT id,body_json,active FROM {content.ITEMS} ORDER BY id"
    ).fetchall():
        identity, body, active = row
        operation = client.new_graph_operation_in(
            conn,
            "inbox_item",
            identity,
            content.decode(body) if active else {},
            action="put" if active else "delete",
            operation_id=str(uuid5(request, "inbox-enrollment:" + identity)),
        )
        client.journal.apply_in(conn, operation, client.writer)
        prepared[identity] = operation
    return prepared


def compare_baseline(table, expected, current, original_items, seeds, enrolled):
    "Only exact helper-proven new headers/versions may differ in a reviewed copy."
    if table not in RESEARCH:
        raise ValueError("Unsupported Inbox baseline table")
    originals = {row["id"]: row for row in original_items}
    if set(seeds) != set(originals) or set(enrolled) != set(originals):
        raise ValueError("Inbox copy has an incomplete receiver-root proof")
    for identity, original in originals.items():
        for operation in (seeds[identity], enrolled[identity]):
            if (
                operation["version"] != 2
                or operation["entity_type"] != "inbox_item"
                or operation["entity_id"] != identity
                or operation["parents"]
                or operation["incarnation"] != operation["operation_id"]
                or operation["action"] != ("put" if original["active"] else "delete")
                or (
                    original["active"]
                    and operation["payload"] != content.decode(original["body_json"])
                )
            ):
                raise ValueError("Inbox receiver root differs from captured research")
    wanted = [dict(row) for row in expected]
    if table == content.ITEMS:
        for row in wanted:
            operation = enrolled[row["id"]]
            row.update(incarnation=operation["incarnation"], version=operation["operation_id"])
    elif table == content.HISTORY:
        for identity, original in originals.items():
            for operation in (seeds[identity], enrolled[identity]):
                wanted.append(
                    dict(
                        version=operation["operation_id"],
                        item_id=identity,
                        body_json=original["body_json"],
                        incarnation=operation["incarnation"],
                        active=original["active"],
                    )
                )

    def canonical(rows):
        return sorted(content.encode(row) for row in rows)

    if canonical(wanted) != canonical(current):
        raise ValueError("Inbox copy lost or changed captured research/history")
