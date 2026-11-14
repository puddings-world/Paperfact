"""Explicit-path sync client experiment; no automatic app or network integration."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import uuid4

from paper_daily.sync_journal import ID, Journal, canonical_operation


def validate_event(event, workspace_id):
    if not isinstance(event, dict) or set(event) != {"sequence", "outcome", "operation", "head"}:
        raise ValueError("Invalid sync event")
    sequence = event["sequence"]
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Invalid event sequence")
    if event["outcome"] not in ("accepted", "conflict"):
        raise ValueError("Invalid event outcome")
    operation = json.loads(canonical_operation(event["operation"]))
    if operation["workspace_id"] != workspace_id:
        raise ValueError("Event belongs to another workspace")
    head = event["head"]
    if not isinstance(head, dict) or set(head) != {"revision", "operation"}:
        raise ValueError("Invalid entity head")
    revision = head["revision"]
    if type(revision) is not int or not 0 <= revision <= sequence:
        raise ValueError("Invalid entity revision")
    if revision == 0:
        if head["operation"] is not None:
            raise ValueError("An absent head cannot contain an operation")
    else:
        canonical_operation(head["operation"])
        for key in ("workspace_id", "entity_type", "entity_id"):
            if head["operation"][key] != operation[key]:
                raise ValueError("Head belongs to another research entity")
    if event["outcome"] == "accepted":
        if revision != sequence or head["operation"] != operation:
            raise ValueError("Accepted event must identify its new head")
    elif revision >= sequence:
        raise ValueError("A conflict cannot replace its canonical head")
    return json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SyncClient:
    """Transactional receive/cursor and retryable push through a supplied transport.

    The transport owns authentication. Research writers are trusted local callbacks.
    Neither credentials nor model calls are stored or executed by this client.
    """

    def __init__(self, journal: Journal, writer, *, order_writer=None, projection_writer=None):
        if projection_writer is not None and not callable(projection_writer):
            raise ValueError("Projection writer must be callable or None")
        self.projection_writer = projection_writer
        self.journal = journal
        self.writer = writer
        self.order_writer = order_writer
        self._running = threading.Lock()
        conn = journal._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            journal._binding(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_cursor "
                "(id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL)"
            )
            conn.execute("INSERT OR IGNORE INTO paperfact_sync_cursor VALUES(1,0)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_inbox "
                "(sequence INTEGER PRIMARY KEY, event TEXT NOT NULL, outcome TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_heads "
                "(entity_type TEXT,entity_id TEXT,revision INTEGER NOT NULL,operation TEXT,"
                "applied_revision INTEGER NOT NULL DEFAULT -1,"
                "PRIMARY KEY(entity_type,entity_id))"
            )
            has_conflict_index = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='paperfact_sync_conflicts'"
                ).fetchone()
                is not None
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_conflicts "
                "(operation_id TEXT PRIMARY KEY,sequence INTEGER NOT NULL UNIQUE,resolved_by TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_resolution_intents "
                "(operation_id TEXT PRIMARY KEY,conflict_sequence INTEGER NOT NULL,"
                "request TEXT NOT NULL,operation TEXT NOT NULL)"
            )
            if not has_conflict_index:
                # Upgrade the private prototype once; receive maintains this index in
                # its cursor transaction. Ordinary restart must not scan full history.
                for row in conn.execute("SELECT event FROM paperfact_sync_inbox ORDER BY sequence"):
                    self._record_conflict_state(conn, json.loads(row[0]))
            has_graph = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paperfact_sync_graph'"
                ).fetchone()
                is not None
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_graph "
                "(entity_type TEXT,entity_id TEXT,metadata TEXT NOT NULL,"
                "PRIMARY KEY(entity_type,entity_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_graph_projection "
                "(entity_type TEXT,entity_id TEXT,source TEXT NOT NULL,operation TEXT,"
                "active INTEGER NOT NULL,reason TEXT,PRIMARY KEY(entity_type,entity_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_graph_receipts "
                "(operation_id TEXT PRIMARY KEY,event TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_order_projection "
                "(scope TEXT PRIMARY KEY,revision INTEGER NOT NULL,digest TEXT NOT NULL)"
            )
            if not has_graph:
                for row in conn.execute("SELECT event FROM paperfact_sync_inbox ORDER BY sequence"):
                    self._record_graph_state(conn, json.loads(row[0]))
                conn.execute(
                    "UPDATE paperfact_sync_heads SET applied_revision=-1 WHERE EXISTS "
                    "(SELECT 1 FROM paperfact_sync_graph_projection p WHERE "
                    "p.entity_type=paperfact_sync_heads.entity_type "
                    "AND p.entity_id=paperfact_sync_heads.entity_id)"
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def attach_existing(cls, journal, writer, *, order_writer=None, projection_writer=None):
        """Use initialized sync tables on the caller's current transaction; no DDL."""
        if projection_writer is not None and not callable(projection_writer):
            raise ValueError("Projection writer must be callable or None")
        value = cls.__new__(cls)
        value.projection_writer = projection_writer
        value.journal, value.writer, value.order_writer = journal, writer, order_writer
        value._running = threading.Lock()
        return value

    @staticmethod
    def _graph_entity(conn, kind, identity):
        row = conn.execute(
            "SELECT metadata FROM paperfact_sync_graph WHERE entity_type=? AND entity_id=?",
            (kind, identity),
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _parent_keys(parents):
        return {(parent["kind"], parent["id"], parent["incarnation"]) for parent in parents}

    def _record_graph_state(self, conn, event):
        operation = event["operation"]
        if operation["version"] == 2:
            from paper_daily.sync_graph import apply_accepted, check_preconditions

            def get_entity(kind, identity):
                return self._graph_entity(conn, kind, identity)

            def get_receipt(identity):
                row = conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                    (identity,),
                ).fetchone()
                return json.loads(row[0]) if row else None

            def set_entity(kind, identity, metadata):
                conn.execute(
                    "INSERT INTO paperfact_sync_graph VALUES(?,?,?) "
                    "ON CONFLICT(entity_type,entity_id) DO UPDATE SET metadata=excluded.metadata",
                    (kind, identity, json.dumps(metadata, sort_keys=True)),
                )

            if event["outcome"] == "accepted":
                from paper_daily.sync_ordering import ORDER_KINDS, validate_order

                if operation["entity_type"] in ORDER_KINDS:
                    state = {
                        (row[0], row[1]): json.loads(row[2])
                        for row in conn.execute("SELECT * FROM paperfact_sync_graph")
                    }
                    if not validate_order(operation, state):
                        raise ValueError("Accepted order violates its observed set")
                if not check_preconditions(get_entity, get_receipt, operation):
                    raise ValueError("Accepted event violates graph preconditions")
                apply_accepted(get_entity, set_entity, operation, event["sequence"])
            conn.execute(
                "INSERT INTO paperfact_sync_graph_projection "
                "(entity_type,entity_id,source,operation,active,reason) VALUES(?,?,?,NULL,0,NULL) "
                "ON CONFLICT(entity_type,entity_id) DO UPDATE SET source=excluded.source",
                (operation["entity_type"], operation["entity_id"], canonical_operation(operation)),
            )
        conn.execute(
            "INSERT INTO paperfact_sync_graph_receipts VALUES(?,?)",
            (operation["operation_id"], json.dumps(event, sort_keys=True)),
        )

    def _pending_graph(self, conn, cursor=None):
        if cursor is None:
            cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0]
        return [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT envelope FROM paperfact_sync_operations WHERE server_revision IS NULL "
                "OR server_revision>? ORDER BY sequence",
                (cursor,),
            )
        ]

    @staticmethod
    def _overlay_optimistic(graph, operation):
        """Overlay one local intent without inventing an accepted server sequence."""
        state, touches, own = graph
        key = (operation["entity_type"], operation["entity_id"])
        old = state.get(key)
        if operation["version"] == 2:
            from paper_daily.sync_graph import _check_address

            _check_address(operation, old)
        own[key] = operation
        if operation["version"] != 2:
            return
        lifecycle = (
            old is None
            or not old["active"]
            or operation["action"] == "delete"
            or old["incarnation"] != operation["incarnation"]
        )
        state[key] = {
            "incarnation": operation["incarnation"],
            "structure_revision": old["structure_revision"] if old else 0,
            "active": operation["action"] == "put",
            "parents": operation["parents"],
        }
        if "content_address" in operation:
            state[key]["content_address"] = dict(operation["content_address"])
        if lifecycle:
            touches[key] = operation["operation_id"]
        for parent in operation["parents"]:
            touches[(parent["kind"], parent["id"])] = operation["operation_id"]

    def _optimistic_graph(self, conn):
        cached = getattr(conn, "_capture_graph_cache", None)
        if cached is not None:
            return cached
        state = {
            (row[0], row[1]): json.loads(row[2])
            for row in conn.execute("SELECT * FROM paperfact_sync_graph")
        }
        graph = (state, {}, {})
        for operation in self._pending_graph(conn):
            self._overlay_optimistic(graph, operation)
        return graph

    def new_graph_operation(
        self, kind, entity_id, payload, *, action="put", operation_id=None, restore=False
    ):
        """Build an explicit v2 operation; restoring an entity requires restore=True."""
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            self.journal._binding(conn)
            return self.new_graph_operation_in(
                conn,
                kind,
                entity_id,
                payload,
                action=action,
                operation_id=operation_id,
                restore=restore,
            )
        finally:
            conn.close()

    def new_graph_operation_in(
        self, conn, kind, entity_id, payload, *, action="put", operation_id=None, restore=False
    ):
        """Build against the caller's transaction, including its uncommitted outbox."""
        if not conn.in_transaction:
            raise ValueError("A caller-owned transaction is required")
        databases = conn.execute("PRAGMA database_list").fetchall()
        main = next((row[2] for row in databases if row[1] == "main"), None)
        if not main or Path(main).resolve() != self.journal.path.resolve():
            raise ValueError("Connection belongs to another research database")
        self.journal._binding(conn)
        return self._new_graph_operation(
            conn,
            kind,
            entity_id,
            payload,
            action=action,
            operation_id=operation_id,
            restore=restore,
        )

    def new_lineage_operation_in(self, conn, prepared_sources, source_operations, payload):
        """Build from the original sealed corpus and same-transaction source publication.

        Data construction only; this does not enable the common Lineage registry
        or publish a scientific row/outbox. The caller owns its transaction.
        """
        from paper_daily.lineage_operations import build_in

        return build_in(conn, self, prepared_sources, source_operations, payload)

    def _new_graph_operation(
        self,
        conn,
        kind,
        entity_id,
        payload,
        *,
        action="put",
        operation_id=None,
        restore=False,
        retirement=False,
        lineage_template=None,
    ):
        if type(restore) is not bool:
            raise ValueError("Restore must be an explicit boolean choice")
        if kind not in (
            "list",
            "paper",
            "membership",
            "note",
            "reading_state",
            "paper_document",
            "research_content",
            "research_file",
            "list_order",
            "workspace_list_order",
            "inbox_item",
        ):
            raise ValueError("Unsupported graph entity")
        if not isinstance(payload, dict):
            raise ValueError("Graph payload must be an object")
        identity = operation_id if operation_id is not None else str(uuid4())
        for value in (entity_id, identity):
            if not isinstance(value, str) or not ID.fullmatch(value):
                raise ValueError("Invalid graph identifier")
        state, touches, own = self._optimistic_graph(conn)
        key = (kind, entity_id)
        current = state.get(key)
        if kind in ("paper", "list", "reading_state", "workspace_list_order", "inbox_item"):
            if kind == "reading_state" and action == "delete" and current is None:
                raise ValueError("A child deletion needs its known parent identities")
            requested = []
        elif kind == "research_content" and action == "put":
            from paper_daily.sync_content import parent_identities, validate_payload

            if payload.get("feature") == "lineage":
                from paper_daily import lineage_dependencies, lineage_wire

                if lineage_template is None:
                    raise ValueError("Lineage puts require the observed native builder")
                lineage_dependencies.canonical_operation(lineage_template)
                requested = lineage_wire.parent_identities(payload)
            else:
                validate_payload(payload, entity_id=entity_id)
                requested = parent_identities(payload)
        elif kind == "list_order" and action == "put":
            requested = [("list", entity_id)]
        elif action == "delete":
            if current is None:
                raise ValueError("A child deletion needs its known parent identities")
            requested = [(p["kind"], p["id"]) for p in current["parents"]]
        else:
            requested = [("paper", payload.get("paper_id"))]
            if kind == "membership":
                requested.insert(0, ("list", payload.get("list_id")))
        parents = []
        for parent_key in requested:
            if not isinstance(parent_key[1], str) or not ID.fullmatch(parent_key[1]):
                raise ValueError("Invalid graph parent identifier")
            parent = state.get(parent_key)
            if parent is None or not parent["active"]:
                if retirement and current:
                    parents = current["parents"]
                    break
                raise ValueError("Parent is missing or deleted; restore it explicitly first")
            parents.append(
                {"kind": parent_key[0], "id": parent_key[1], "incarnation": parent["incarnation"]}
            )
        if lineage_template is not None and action == "put":
            if parents != lineage_template["parents"]:
                raise ValueError("Lineage parents changed; explicitly observe a new analysis")
            parents = lineage_template["parents"]
        if kind == "reading_state":
            parents = self._reading_parents(state, entity_id)
        changed_parent = current and self._parent_keys(current["parents"]) != self._parent_keys(
            parents
        )
        if retirement and current:
            parents = current["parents"]
            incarnation = current["incarnation"]
        elif current and (not current["active"] or changed_parent):
            if action == "put":
                if not restore:
                    raise ValueError("Restoring deleted research requires restore=True")
                incarnation = identity
            elif changed_parent:
                raise ValueError("Parent incarnation changed; review the child conflict")
            else:
                incarnation = current["incarnation"]
        elif current:
            if restore:
                raise ValueError("An active entity cannot be restored")
            incarnation = current["incarnation"]
        else:
            incarnation = identity
        head = conn.execute(
            "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?", key
        ).fetchone()
        accepted = self._graph_entity(conn, *key)
        operation = {
            "version": 2,
            "operation_id": identity,
            "workspace_id": self.journal.workspace_id,
            "device_id": self.journal.device_id,
            "entity_type": kind,
            "entity_id": entity_id,
            "action": action,
            "base_revision": head[0] if head else 0,
            "depends_on": own[key]["operation_id"] if key in own else None,
            "payload": payload,
            "incarnation": incarnation,
            "parents": parents,
            "structure_revision": accepted["structure_revision"] if accepted else 0,
        }
        if key in touches:
            operation["structure_depends_on"] = touches[key]
        address = (lineage_template or current or {}).get("content_address")
        if address is not None:
            operation["content_address"] = dict(address)
            operation["source_dependencies"] = (
                lineage_template["source_dependencies"] if action == "put" else []
            )
        operation = json.loads(canonical_operation(operation))
        self._guard_membership_creation(conn, operation)
        self._guard_reading_parents(conn, operation)
        self._guard_order(conn, operation)
        self._guard_document_parent(conn, operation)
        from paper_daily import lineage_dependencies

        if lineage_dependencies.requires_readiness(operation):
            self._guard_content_parent(conn, operation)
        return operation

    def new_order_operation(
        self, kind, entity_id, ordered_ids, *, operation_id=None, restore=False
    ):
        """Build a full permutation against the current optimistic member set."""
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            return self.new_order_operation_in(
                conn, kind, entity_id, ordered_ids, operation_id=operation_id, restore=restore
            )
        finally:
            conn.close()

    def new_order_operation_in(
        self, conn, kind, entity_id, ordered_ids, *, operation_id=None, restore=False
    ):
        from paper_daily.sync_ordering import ORDER_KINDS, active_items, observed_set

        if not conn.in_transaction:
            raise ValueError("A caller-owned transaction is required")
        databases = conn.execute("PRAGMA database_list").fetchall()
        main = next((row[2] for row in databases if row[1] == "main"), None)
        if not main or Path(main).resolve() != self.journal.path.resolve():
            raise ValueError("Connection belongs to another research database")
        self.journal._binding(conn)
        if kind not in ORDER_KINDS:
            raise ValueError("Unsupported ordering kind")
        state, _, _ = self._optimistic_graph(conn)
        parents = []
        if kind == "list_order":
            parent = state.get(("list", entity_id))
            if not parent or not parent["active"]:
                raise ValueError("Ordering requires an active list")
            parents = [{"kind": "list", "id": entity_id, "incarnation": parent["incarnation"]}]
        stub = {
            "workspace_id": self.journal.workspace_id,
            "entity_type": kind,
            "entity_id": entity_id,
            "parents": parents,
        }
        items = active_items(stub, state)
        if (
            not isinstance(ordered_ids, list)
            or any(not isinstance(value, str) for value in ordered_ids)
            or sorted(ordered_ids) != sorted(item["id"] for item in items)
        ):
            raise ValueError("Order must be a complete permutation of the active set")
        lookup = {item["id"]: item for item in items}
        payload = {
            "items": [lookup[identity] for identity in ordered_ids],
            "observed_set": observed_set(stub, items),
        }
        if kind == "list_order":
            payload["list_id"] = entity_id
        return self.new_graph_operation_in(
            conn, kind, entity_id, payload, operation_id=operation_id, restore=restore
        )

    def _guard_content_parent(self, conn, operation):
        if operation["version"] != 2 or operation["entity_type"] != "research_content":
            return
        if operation["action"] == "delete" and operation.get("resolution_of"):
            from paper_daily.sync_graph import check_preconditions

            def receipt(identity):
                row = conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                    (identity,),
                ).fetchone()
                return json.loads(row[0]) if row else None

            if not check_preconditions(
                lambda kind, identity: self._graph_entity(conn, kind, identity), receipt, operation
            ):
                raise ValueError("Content retirement no longer matches its conflict")
            return
        graph, _, _ = self._optimistic_graph(conn)
        from paper_daily import lineage_dependencies

        if lineage_dependencies.requires_readiness(operation):
            lineage_dependencies.canonical_operation(operation)
            if not lineage_dependencies.active(
                lambda kind, identity: graph.get((kind, identity)), operation
            ):
                raise ValueError("Lineage requires every exact active original dependency")
        for parent in operation["parents"]:
            current = graph.get((parent["kind"], parent["id"]))
            if (
                current is None
                or not current["active"]
                or current["incarnation"] != parent["incarnation"]
            ):
                raise ValueError("Research content requires every exact active parent")

    def _guard_document_parent(self, conn, operation):
        if operation["version"] != 2 or operation["entity_type"] not in (
            "paper_document", "research_file"
        ):
            return
        if operation["action"] == "delete" and operation.get("resolution_of"):
            from paper_daily.sync_graph import check_preconditions

            def receipt(identity):
                row = conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                    (identity,),
                ).fetchone()
                return json.loads(row[0]) if row else None

            if not check_preconditions(
                lambda kind, identity: self._graph_entity(conn, kind, identity), receipt, operation
            ):
                raise ValueError("Document retirement no longer matches its conflict")
            return
        state, _, _ = self._optimistic_graph(conn)
        paper_id = (operation["entity_id"] if operation["entity_type"] == "paper_document"
                    else operation["parents"][0]["id"])
        parent = state.get(("paper", paper_id))
        expected = (
            [{"kind": "paper", "id": paper_id, "incarnation": parent["incarnation"]}]
            if parent
            else []
        )
        if not parent or not parent["active"] or operation["parents"] != expected:
            raise ValueError("Document requires its exact active paper incarnation")

    def _guard_order(self, conn, operation):
        from paper_daily.sync_ordering import ORDER_KINDS, validate_order

        if operation["version"] != 2 or operation["entity_type"] not in ORDER_KINDS:
            return
        state, _, _ = self._optimistic_graph(conn)
        if not (operation["action"] == "delete" and operation.get("resolution_of")):
            for ref in operation["parents"]:
                parent = state.get((ref["kind"], ref["id"]))
                if (
                    parent is None
                    or not parent["active"]
                    or parent["incarnation"] != ref["incarnation"]
                ):
                    raise ValueError("Ordering parent is missing, deleted or replaced")
        if not validate_order(operation, state):
            raise ValueError("Ordering set changed; build a new complete reorder")

    def deferred_reasons(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid deferred reason limit")
        conn = self.journal._connect()
        try:
            self.journal._binding(conn)
            return [
                {"entity_type": row[0], "entity_id": row[1], "reason": row[2]}
                for row in conn.execute(
                    "SELECT entity_type,entity_id,reason FROM paperfact_sync_graph_projection "
                    "WHERE reason IS NOT NULL ORDER BY entity_type,entity_id LIMIT ?",
                    (limit,),
                )
            ]
        finally:
            conn.close()

    def new_operation(self, kind, entity_id, payload, *, action="put", operation_id=None):
        """Build once and retain the returned envelope when retrying a local action."""
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            self.journal._binding(conn)
            head = conn.execute(
                "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
                (kind, entity_id),
            ).fetchone()
            previous = conn.execute(
                "SELECT operation_id FROM paperfact_sync_operations "
                "WHERE entity_type=? AND entity_id=? AND (server_revision IS NULL "
                "OR server_revision>(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)) "
                "ORDER BY sequence DESC LIMIT 1",
                (kind, entity_id),
            ).fetchone()
            value = {
                "version": 1,
                "operation_id": operation_id or str(uuid4()),
                "workspace_id": self.journal.workspace_id,
                "device_id": self.journal.device_id,
                "entity_type": kind,
                "entity_id": entity_id,
                "action": action,
                "base_revision": head[0] if head else 0,
                "depends_on": previous[0] if previous else None,
                "payload": payload,
            }
            value = json.loads(canonical_operation(value))
            self._guard_legacy(conn, value)
            return value
        finally:
            conn.close()

    @staticmethod
    def _reading_parents(state, identity):
        membership = state.get(("membership", identity))
        if membership is None or not membership["active"]:
            raise ValueError("Reading state requires an active membership")
        parents = [
            {"kind": "membership", "id": identity, "incarnation": membership["incarnation"]},
            *[dict(parent) for parent in membership["parents"]],
        ]
        for ref in parents:
            parent = state.get((ref["kind"], ref["id"]))
            if (
                parent is None
                or not parent["active"]
                or parent["incarnation"] != ref["incarnation"]
            ):
                raise ValueError("Reading state membership parent closure is not active")
        return parents

    def _guard_reading_parents(self, conn, operation):
        pin = operation["entity_type"] == "research_content" and any(
            p["kind"] == "membership" for p in operation.get("parents", [])
        )
        if operation["version"] != 2 or (operation["entity_type"] != "reading_state" and not pin):
            return
        if operation["action"] == "delete" and operation.get("resolution_of"):
            from paper_daily.sync_graph import check_preconditions

            def receipt(identity):
                row = conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                    (identity,),
                ).fetchone()
                return json.loads(row[0]) if row else None

            if not check_preconditions(
                lambda kind, identity: self._graph_entity(conn, kind, identity), receipt, operation
            ):
                raise ValueError("Reading state retirement no longer matches its conflict")
            return
        state, _, _ = self._optimistic_graph(conn)
        member_id = (
            next(p["id"] for p in operation["parents"] if p["kind"] == "membership")
            if pin
            else operation["entity_id"]
        )
        parents = self._reading_parents(state, member_id)
        if self._parent_keys(parents) != self._parent_keys(operation["parents"]):
            raise ValueError("Reading state parent closure differs from its membership")

    @staticmethod
    def _guard_membership_creation(conn, operation):
        if (
            operation["version"] != 2
            or operation["entity_type"] != "membership"
            or operation["action"] != "put"
        ):
            return
        origin = conn.execute(
            "SELECT envelope FROM paperfact_sync_operations WHERE operation_id=?",
            (operation["incarnation"],),
        ).fetchone()
        if origin:
            creation = json.loads(origin[0])
        else:
            receipt = conn.execute(
                "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                (operation["incarnation"],),
            ).fetchone()
            creation = json.loads(receipt[0])["operation"] if receipt else None
        if creation is not None and (
            creation["version"] == 2
            and creation["entity_type"] == "membership"
            and creation["entity_id"] == operation["entity_id"]
            and creation["action"] == "put"
            and creation["incarnation"] == operation["incarnation"]
            and creation["payload"]["added_at"] != operation["payload"]["added_at"]
        ):
            raise ValueError("Membership added_at is immutable within its incarnation")

    def _guard_legacy(self, conn, operation):
        if operation["version"] != 1:
            return
        graph, _, _ = self._optimistic_graph(conn)
        key = (operation["entity_type"], operation["entity_id"])
        if key in graph:
            raise ValueError("Use the version-2 builder for enrolled graph research")
        if key[0] != "note":
            return
        papers = set()
        if operation["action"] == "put":
            papers.add(operation["payload"]["paper_id"])
        else:
            head = conn.execute(
                "SELECT operation FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
                key,
            ).fetchone()
            if head and head[0]:
                papers.add(json.loads(head[0])["payload"].get("paper_id"))
            for row in conn.execute(
                "SELECT envelope FROM paperfact_sync_operations "
                "WHERE entity_type=? AND entity_id=? "
                "ORDER BY sequence DESC",
                key,
            ):
                previous = json.loads(row[0])
                if previous["action"] == "put":
                    papers.add(previous["payload"].get("paper_id"))
                    break
        if any(("paper", paper) in graph for paper in papers):
            raise ValueError("Use the version-2 builder for notes under enrolled graph papers")

    def save(self, operation):
        def write(conn, value):
            self._guard_legacy(conn, value)
            self._guard_membership_creation(conn, value)
            self._guard_reading_parents(conn, value)
            self._guard_order(conn, value)
            self._guard_document_parent(conn, value)
            self._guard_content_parent(conn, value)
            self.writer(conn, value)

        return self.journal.apply(operation, write)

    def conflict_observation_in(self, conn, sequence):
        """Capture the exact canonical/parent/pending state displayed by a review."""
        self.journal._binding(conn)
        target = conn.execute(
            "SELECT i.event,c.resolved_by FROM paperfact_sync_inbox i "
            "JOIN paperfact_sync_conflicts c ON c.sequence=i.sequence WHERE i.sequence=?",
            (sequence,),
        ).fetchone()
        if target is None:
            raise ValueError("Unknown conflict sequence")
        event = json.loads(validate_event(json.loads(target["event"]), self.journal.workspace_id))
        operation = event["operation"]
        key = (operation["entity_type"], operation["entity_id"])
        head = conn.execute(
            "SELECT revision,operation FROM paperfact_sync_heads "
            "WHERE entity_type=? AND entity_id=?",
            key,
        ).fetchone()
        graph = self._optimistic_graph(conn)[0]
        state = graph.get(key)
        parents = [
            {"ref": ref, "current": graph.get((ref["kind"], ref["id"]))}
            for ref in (state or operation).get("parents", [])
        ]
        result = {
            "event": event, "resolved_by": target["resolved_by"],
            "head": dict(head) if head else None, "state": state, "parents": parents,
            "outstanding": self._outstanding(conn, key),
        }
        from paper_daily import lineage_dependencies

        if lineage_dependencies.requires_readiness(operation):
            canonical = json.loads(head["operation"]) if head and head["operation"] else None
            references = list(operation["source_dependencies"])
            if canonical is not None:
                references.extend(canonical.get("source_dependencies", []))
            result["originals"] = [
                {"ref": ref, "current": graph.get(("research_file", ref["file_id"]))}
                for ref in references
            ]
        return result

    def resolve_conflict(
        self, sequence, *, choice="incoming", payload=None, operation_id=None, restore=False
    ):
        return self._resolve_conflict(
            sequence, choice=choice, payload=payload, operation_id=operation_id, restore=restore
        )

    def resolve_conflict_in(self, conn, sequence, *, expected, **options):
        """Resolve against a displayed observation inside the caller's transaction.

        No commit occurs here. The caller can atomically record its review decision.
        expected is obtained from conflict_observation_in, never recaptured on Save.
        """
        databases = conn.execute("PRAGMA database_list").fetchall()
        main = next((row[2] for row in databases if row[1] == "main"), None)
        if (not conn.in_transaction or not main
                or Path(main).resolve() != self.journal.path.resolve()):
            raise ValueError("A transaction in the original workspace is required")
        if not isinstance(expected, dict):
            raise ValueError("A displayed conflict observation is required")
        return self._resolve_conflict(sequence, connection=conn, expected=expected, **options)

    def _resolve_conflict(
        self, sequence, *, choice="incoming", payload=None, operation_id=None, restore=False,
        connection=None, expected=None
    ):
        """Save an explicit resolution; acceptance in the event stream closes the conflict.

        Retain operation_id for caller retries. Repeated pending requests without an ID
        reuse their existing intent. Outstanding edits must sync before resolution.
        """
        if type(sequence) is not int or sequence < 1:
            raise ValueError("Invalid conflict sequence")
        if type(restore) is not bool:
            raise ValueError("Restore must be an explicit boolean choice")
        if choice not in ("incoming", "canonical"):
            raise ValueError("Invalid resolution choice")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Resolution payload must be an object")
        if operation_id is not None and (
            not isinstance(operation_id, str) or not ID.fullmatch(operation_id)
        ):
            raise ValueError("Invalid resolution operation ID")
        try:
            request = json.dumps(
                {
                    "sequence": sequence,
                    "choice": choice,
                    "payload": payload,
                    **({"restore": True} if restore else {}),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid resolution payload") from exc
        conn = connection if connection is not None else self.journal._connect()
        try:
            if connection is None:
                conn.execute("BEGIN")
            self.journal._binding(conn)
            previous = None
            if operation_id is not None:
                previous = conn.execute(
                    "SELECT request,operation FROM research_resolution_intents "
                    "WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
            if previous is None:
                previous = conn.execute(
                    "SELECT i.request,i.operation FROM research_resolution_intents i "
                    "JOIN paperfact_sync_operations o ON o.operation_id=i.operation_id "
                    "WHERE i.conflict_sequence=? AND (o.server_revision IS NULL OR "
                    "o.server_revision>(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)) "
                    "ORDER BY o.sequence DESC LIMIT 1",
                    (sequence,),
                ).fetchone()
                if previous and operation_id is not None:
                    raise ValueError("A resolution is already pending for this conflict")
            if previous:
                if previous["request"] != request:
                    raise ValueError("Resolution retry changed its choice or payload")
                operation = json.loads(previous["operation"])
            else:
                if (expected is not None
                        and self.conflict_observation_in(conn, sequence) != expected):
                    raise ValueError("Displayed conflict changed; your draft is retained")
                target = conn.execute(
                    "SELECT i.event,c.resolved_by FROM paperfact_sync_inbox i "
                    "JOIN paperfact_sync_conflicts c ON c.sequence=i.sequence WHERE i.sequence=?",
                    (sequence,),
                ).fetchone()
                if target is None:
                    raise ValueError("Unknown conflict sequence")
                if target["resolved_by"] is not None:
                    raise ValueError("Conflict is already resolved")
                conflict = json.loads(target["event"])["operation"]
                key = (conflict["entity_type"], conflict["entity_id"])
                head = conn.execute(
                    "SELECT revision,operation FROM paperfact_sync_heads "
                    "WHERE entity_type=? AND entity_id=?",
                    key,
                ).fetchone()
                if self._outstanding(conn, key):
                    raise ValueError("Synchronize outstanding edits before resolving this conflict")
                source = (
                    conflict
                    if choice == "incoming"
                    else (json.loads(head["operation"]) if head["operation"] else None)
                )
                operation = {
                    "version": 1,
                    "operation_id": operation_id if operation_id is not None else str(uuid4()),
                    "workspace_id": self.journal.workspace_id,
                    "device_id": self.journal.device_id,
                    "entity_type": key[0],
                    "entity_id": key[1],
                    "action": source["action"] if source else "delete",
                    "base_revision": head["revision"],
                    "depends_on": None,
                    "payload": payload
                    if payload is not None
                    else (source["payload"] if source else {}),
                    "resolution_of": conflict["operation_id"],
                }
                if conflict["version"] == 2:
                    state = self._graph_entity(conn, *key)
                    references = state["parents"] if state else conflict["parents"]
                    obsolete = any(
                        (parent := self._graph_entity(conn, ref["kind"], ref["id"])) is None
                        or not parent["active"]
                        or parent["incarnation"] != ref["incarnation"]
                        for ref in references
                    )
                    from paper_daily import lineage_dependencies

                    if source is not None and lineage_dependencies.requires_readiness(source):
                        obsolete = obsolete or not lineage_dependencies.active(
                            lambda kind, identity: self._graph_entity(conn, kind, identity), source
                        )
                    retirement = choice == "canonical" and (obsolete or source is None)
                    if retirement:
                        operation.update(
                            version=2,
                            action="delete",
                            payload={},
                            parents=references,
                            incarnation=state["incarnation"] if state else conflict["incarnation"],
                            structure_revision=state["structure_revision"] if state else 0,
                        )
                        address = (state or conflict).get("content_address")
                        if address is not None:
                            operation["content_address"] = dict(address)
                            operation["source_dependencies"] = []
                        if payload not in (None, {}):
                            raise ValueError("Canonical retirement requires an empty payload")
                    else:
                        operation = self._new_graph_operation(
                            conn,
                            *key,
                            operation["payload"],
                            action=operation["action"],
                            operation_id=operation["operation_id"],
                            restore=restore,
                            lineage_template=source
                            if (source is not None
                                and lineage_dependencies.requires_readiness(source))
                            else None,
                        )
                        operation["resolution_of"] = conflict["operation_id"]
                elif restore:
                    raise ValueError("Explicit incarnation restore requires version 2")
                operation = json.loads(canonical_operation(operation))
        finally:
            if connection is None:
                conn.close()

        def write_resolution(conn, value):
            if expected is not None and self.conflict_observation_in(conn, sequence) != expected:
                raise ValueError("Displayed conflict changed; your draft is retained")
            row = conn.execute(
                "SELECT resolved_by FROM paperfact_sync_conflicts WHERE operation_id=?",
                (value["resolution_of"],),
            ).fetchone()
            if row is None or row["resolved_by"] is not None:
                raise ValueError("Conflict changed before resolution was saved")
            key = (value["entity_type"], value["entity_id"])
            current = conn.execute(
                "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
                key,
            ).fetchone()
            if current is None or current[0] != value["base_revision"]:
                raise ValueError("Canonical content changed; review the conflict again")
            if self._outstanding(conn, key):
                raise ValueError("Synchronize outstanding edits before resolving this conflict")
            if value["version"] == 2:
                from paper_daily.sync_graph import check_preconditions

                def get_receipt(identity):
                    record = conn.execute(
                        "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                        (identity,),
                    ).fetchone()
                    return json.loads(record[0]) if record else None

                if not check_preconditions(
                    lambda kind, identity: self._graph_entity(conn, kind, identity),
                    get_receipt,
                    value,
                ):
                    raise ValueError("Graph changed; review the conflict again")
            self._guard_legacy(conn, value)
            self._guard_membership_creation(conn, value)
            self._guard_reading_parents(conn, value)
            self._guard_order(conn, value)
            self._guard_document_parent(conn, value)
            self._guard_content_parent(conn, value)
            self.writer(conn, value)
            conn.execute(
                "INSERT INTO research_resolution_intents VALUES(?,?,?,?)",
                (value["operation_id"], sequence, request, canonical_operation(value)),
            )

        result = (
            self.journal.apply(operation, write_resolution) if connection is None
            else self.journal.apply_in(connection, operation, write_resolution)
        )
        return {"operation_id": operation["operation_id"], **result}

    @staticmethod
    def _outstanding(conn, key):
        return (
            conn.execute(
                "SELECT 1 FROM paperfact_sync_operations WHERE entity_type=? AND entity_id=? "
                "AND (server_revision IS NULL OR server_revision>"
                "(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)) LIMIT 1",
                key,
            ).fetchone()
            is not None
        )

    @staticmethod
    def _record_conflict_state(conn, event):
        operation = event["operation"]
        target_id = operation.get("resolution_of")
        if target_id is not None:
            target = conn.execute(
                "SELECT i.event FROM paperfact_sync_conflicts c "
                "JOIN paperfact_sync_inbox i ON i.sequence=c.sequence WHERE c.operation_id=?",
                (target_id,),
            ).fetchone()
            if target is None:
                raise ValueError("Resolution refers to an unknown conflict")
            original = json.loads(target["event"])["operation"]
            if (original["entity_type"], original["entity_id"]) != (
                operation["entity_type"],
                operation["entity_id"],
            ):
                raise ValueError("Resolution refers to another research entity")
            if event["outcome"] == "accepted":
                conn.execute(
                    "UPDATE paperfact_sync_conflicts SET resolved_by=? "
                    "WHERE operation_id=? AND resolved_by IS NULL",
                    (operation["operation_id"], target_id),
                )
        if event["outcome"] == "conflict":
            conn.execute(
                "INSERT OR IGNORE INTO paperfact_sync_conflicts VALUES(?,?,NULL)",
                (operation["operation_id"], event["sequence"]),
            )

    def status(self):
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            self.journal._binding(conn)
            return {
                "cursor": conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0],
                "pending": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision IS NULL"
                ).fetchone()[0],
                "awaiting_receipts": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision>"
                    "(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)"
                ).fetchone()[0],
                "conflicts": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_conflicts WHERE resolved_by IS NULL"
                ).fetchone()[0],
                "deferred": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_heads h LEFT JOIN "
                    "paperfact_sync_graph_projection p USING(entity_type,entity_id) "
                    "WHERE h.applied_revision<h.revision OR p.reason IS NOT NULL"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def history(self, *, conflicts_only=False, after=0, limit=100):
        if type(after) is not int or after < 0:
            raise ValueError("Invalid history cursor")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid history limit")
        conn = self.journal._connect()
        try:
            self.journal._binding(conn)
            rows = conn.execute(
                "SELECT event FROM paperfact_sync_inbox WHERE sequence>? "
                "AND (?=0 OR outcome='conflict') ORDER BY sequence LIMIT ?",
                (after, int(conflicts_only), limit),
            )
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def receive(self, events):
        """Persist a bounded contiguous batch and resulting research in one transaction.

        Local edits defer materialization until their acknowledgment is received in the
        contiguous inbox, including when upload succeeded but pull failed. All versions
        remain in history. UI draft/selection handling belongs to the desktop adapter.
        """
        if not isinstance(events, list) or len(events) > 1000:
            raise ValueError("Invalid event batch")
        encoded = [validate_event(event, self.journal.workspace_id) for event in events]
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.journal._binding(conn)
            cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0]
            received = 0
            for data in encoded:
                event = json.loads(data)
                sequence = event["sequence"]
                if sequence <= cursor:
                    receipt = conn.execute(
                        "SELECT event FROM paperfact_sync_inbox WHERE sequence=?", (sequence,)
                    ).fetchone()
                    if receipt is None or receipt[0] != data:
                        raise ValueError("Event replay changed content")
                    continue
                if sequence != cursor + 1:
                    raise ValueError("Event stream has a gap")
                op, head = event["operation"], event["head"]
                key = (op["entity_type"], op["entity_id"])
                existing = conn.execute(
                    "SELECT revision,operation FROM paperfact_sync_heads "
                    "WHERE entity_type=? AND entity_id=?",
                    key,
                ).fetchone()
                head_data = canonical_operation(head["operation"]) if head["operation"] else None
                if event["outcome"] == "conflict":
                    expected = tuple(existing) if existing else (0, None)
                    if (head["revision"], head_data) != expected:
                        raise ValueError("Conflict head differs from the accepted event stream")
                if existing and (
                    head["revision"] < existing[0]
                    or (head["revision"] == existing[0] and head_data != existing[1])
                ):
                    raise ValueError("Entity head moved backwards or changed content")
                conn.execute(
                    "INSERT INTO paperfact_sync_heads "
                    "(entity_type,entity_id,revision,operation,applied_revision) "
                    "VALUES(?,?,?,?,-1) "
                    "ON CONFLICT(entity_type,entity_id) DO UPDATE SET "
                    "revision=excluded.revision,operation=excluded.operation,"
                    "applied_revision=-1",
                    (*key, head["revision"], head_data),
                )
                conn.execute(
                    "INSERT INTO paperfact_sync_inbox VALUES(?,?,?)",
                    (sequence, data, event["outcome"]),
                )
                self._record_conflict_state(conn, event)
                self._record_graph_state(conn, event)
                from paper_daily import lineage_dependencies

                if event["outcome"] == "accepted" and lineage_dependencies.requires_readiness(op):
                    from paper_daily.lineage_projection import _retain_received_in

                    _retain_received_in(conn, self, event)
                self._invalidate_order_cache(conn, op)
                cursor = sequence
                received += 1
            applied = self._materialize(conn, cursor)
            conn.execute("UPDATE paperfact_sync_cursor SET sequence=? WHERE id=1", (cursor,))
            conn.commit()
            return {"received": received, "applied": applied, "cursor": cursor}
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _materialize_legacy(self, conn, cursor):
        heads = conn.execute(
            "SELECT * FROM paperfact_sync_heads h WHERE applied_revision<revision "
            "AND NOT EXISTS (SELECT 1 FROM paperfact_sync_graph_projection p "
            "WHERE p.entity_type=h.entity_type AND p.entity_id=h.entity_id) ORDER BY revision"
        ).fetchall()
        applied = 0
        for head in heads:
            key = (head["entity_type"], head["entity_id"])
            pending = conn.execute(
                "SELECT 1 FROM paperfact_sync_operations "
                "WHERE entity_type=? AND entity_id=? "
                "AND (server_revision IS NULL OR server_revision>?) LIMIT 1",
                (*key, cursor),
            ).fetchone()
            if pending:
                continue
            if head["operation"] is None:
                # Canonical absence still needs materialization when a local stale-base
                # create was rejected. Keep that content in conflict history, and invoke
                # only the research writer; this synthetic delete is never queued/pushed.
                operation = {
                    "version": 1,
                    "operation_id": str(uuid4()),
                    "workspace_id": self.journal.workspace_id,
                    "device_id": self.journal.device_id,
                    "entity_type": head["entity_type"],
                    "entity_id": head["entity_id"],
                    "action": "delete",
                    "base_revision": 0,
                    "depends_on": None,
                    "payload": {},
                }
            else:
                operation = json.loads(head["operation"])
            conn.set_authorizer(self.journal._authorize_writer)
            try:
                self.writer(conn, operation)
            finally:
                conn.set_authorizer(None)
            conn.execute(
                "UPDATE paperfact_sync_heads SET applied_revision=revision "
                "WHERE entity_type=? AND entity_id=?",
                key,
            )
            applied += 1
        return applied

    @staticmethod
    def _projection_encoded(operation):
        from paper_daily import lineage_dependencies

        if lineage_dependencies.requires_readiness(operation):
            return lineage_dependencies.canonical_operation(operation)
        return canonical_operation(operation)

    def _write_projection_in(self, conn, source, *, visible):
        """Preserve an immutable source for explicitly registered graph projectors.

        The receive owner validates events and owns transaction/cursor rollback.
        This dispatch creates no event, outbox or schema. A typed source without
        an explicit projector cannot fall back to a synthetic generic deletion.
        """
        from paper_daily import lineage_dependencies

        if not conn.in_transaction or type(visible) is not bool:
            raise ValueError("Projection requires a transaction and boolean visibility")
        encoded = self._projection_encoded(source)
        operation = json.loads(encoded)
        if self.projection_writer is None and lineage_dependencies.requires_readiness(operation):
            raise ValueError("Typed Lineage receive requires an explicit projection writer")
        conn.set_authorizer(self.journal._authorize_writer)
        try:
            if self.projection_writer is not None:
                self.projection_writer(conn, operation, visible=visible)
            else:
                if not visible:
                    operation.update(action="delete", payload={})
                self.writer(conn, operation)
        finally:
            conn.set_authorizer(None)
        if self.projection_writer is not None and self._projection_encoded(operation) != encoded:
            raise ValueError("Projection writer cannot change its original operation")

    def _materialize_graph(self, conn, cursor):
        heads = conn.execute(
            "SELECT h.*,p.source,p.operation AS projected_operation,p.active,p.reason "
            "FROM paperfact_sync_heads h JOIN paperfact_sync_graph_projection p "
            "USING(entity_type,entity_id) "
            "WHERE h.entity_type NOT IN ('list_order','workspace_list_order') "
            "ORDER BY CASE WHEN h.entity_type IN ('list','paper') THEN 0 "
            "WHEN h.entity_type='research_file' THEN 1 "
            "WHEN h.entity_type='reading_state' THEN 3 ELSE 2 END,h.revision"
        ).fetchall()
        pending = self._pending_graph(conn, cursor)
        outstanding = {(op["entity_type"], op["entity_id"]) for op in pending}
        applied = 0
        lineage_initialized = False

        def blocked(key, reason):
            conn.execute(
                "UPDATE paperfact_sync_graph_projection SET reason=? "
                "WHERE entity_type=? AND entity_id=?",
                (reason, *key),
            )

        def project(head, source, *, visible, reason=None):
            key = (head["entity_type"], head["entity_id"])
            changed = (
                head["applied_revision"] != head["revision"] or bool(head["active"]) != visible
            )
            if changed:
                self._write_projection_in(conn, source, visible=visible)
            conn.execute(
                "UPDATE paperfact_sync_heads SET applied_revision=revision "
                "WHERE entity_type=? AND entity_id=?",
                key,
            )
            conn.execute(
                "UPDATE paperfact_sync_graph_projection SET operation=?,active=?,reason=? "
                "WHERE entity_type=? AND entity_id=?",
                (self._projection_encoded(source), int(visible), reason, *key),
            )
            return int(changed)

        for head in heads:
            key = (head["entity_type"], head["entity_id"])
            source = json.loads(head["operation"] or head["source"])
            if key in outstanding:
                blocked(key, "pending_local")
                continue
            if source["entity_type"] in ("list", "paper", "membership"):
                old = (
                    json.loads(head["projected_operation"]) if head["projected_operation"] else None
                )
                lifecycle = (
                    source["action"] == "delete"
                    or (old is not None and old["incarnation"] != source["incarnation"])
                    or any(
                        (parent["kind"], parent["id"]) == key
                        and parent["incarnation"] != source["incarnation"]
                        for operation in pending
                        if operation["version"] == 2
                        for parent in operation["parents"]
                    )
                )
                if lifecycle and any(
                    (parent["kind"], parent["id"]) == key
                    for operation in pending
                    if operation["version"] == 2
                    for parent in operation["parents"]
                ):
                    blocked(key, "pending_descendant")
                    continue
            reason = None
            for parent in source["parents"]:
                parent_key = (parent["kind"], parent["id"])
                if parent_key in outstanding:
                    reason = "parent_pending"
                    break
                state = self._graph_entity(conn, *parent_key)
                if state is None:
                    reason = "parent_missing"
                    break
                if not state["active"]:
                    reason = "parent_deleted"
                    break
                if state["incarnation"] != parent["incarnation"]:
                    reason = "parent_incarnation"
                    break
                projected = conn.execute(
                    "SELECT h.revision,h.applied_revision,p.active,p.operation,p.reason "
                    "FROM paperfact_sync_heads h JOIN paperfact_sync_graph_projection p "
                    "USING(entity_type,entity_id) WHERE h.entity_type=? AND h.entity_id=?",
                    parent_key,
                ).fetchone()
                if (
                    projected is None
                    or projected["revision"] != projected["applied_revision"]
                    or not projected["active"]
                    or projected["reason"] is not None
                ):
                    reason = "parent_deferred"
                    break
            if (
                source["entity_type"] == "membership"
                and reason in ("parent_missing", "parent_deleted", "parent_incarnation")
                and any(
                    (parent["kind"], parent["id"]) == key
                    for operation in pending
                    if operation["version"] == 2
                    for parent in operation["parents"]
                )
            ):
                # Hiding an obsolete membership can cascade into its local state row,
                # even though its own head did not change. Preserve that unsent child.
                blocked(key, "pending_descendant")
                continue
            if (
                head["operation"] is not None
                and source["action"] == "delete"
                and reason in ("parent_missing", "parent_deleted", "parent_incarnation")
            ):
                # An accepted retirement is already canonical absence, not a child
                # waiting forever for an obsolete parent's incarnation to return.
                reason = None
            from paper_daily import lineage_dependencies

            if lineage_dependencies.requires_readiness(source):
                if not lineage_initialized:
                    from paper_daily.lineage_projection import initialize_receive_in

                    initialize_receive_in(conn, self, source)
                    lineage_initialized = True
                # This checks every dependency's outstanding edits first, before
                # any earlier missing/retired parent or source can hide science.
                reason = lineage_dependencies.projection_reason_in(conn, self, source)
            if reason in (
                "parent_pending",
                "parent_deferred",
                "source_pending",
                "source_deferred",
                "projection_capacity",
            ):
                blocked(key, reason)
                continue
            if head["operation"] is None and source["entity_type"] == "paper":
                # Paper deletion is outside the v2 retention contract. Keep a rejected
                # local paper for explicit reconciliation instead of inventing deletion.
                blocked(key, "canonical_absence")
                continue
            visible = head["operation"] is not None and source["action"] == "put" and reason is None
            applied += project(head, source, visible=visible, reason=reason)
        return applied

    @staticmethod
    def _invalidate_order_cache(conn, operation):
        if operation["version"] != 2 or operation["entity_type"] not in ("list", "membership"):
            return
        if (
            operation["action"] != "delete"
            and operation["incarnation"] != operation["operation_id"]
        ):
            return
        # A rejected optimistic removal may have physically recreated a row at the
        # end even when canonical membership and the accepted order are unchanged.
        for row in conn.execute("SELECT scope FROM paperfact_sync_order_projection").fetchall():
            scope = json.loads(row[0])
            affected = (
                operation["entity_type"] == "list"
                and (
                    scope["kind"] == "workspace_list_order" or scope["id"] == operation["entity_id"]
                )
            ) or (
                operation["entity_type"] == "membership"
                and scope["kind"] == "list_order"
                and any(
                    ref["kind"] == "list" and ref["id"] == scope["id"]
                    for ref in operation["parents"]
                )
            )
            if affected:
                conn.execute("DELETE FROM paperfact_sync_order_projection WHERE scope=?", (row[0],))

    def _materialize_orders(self, conn, cursor):
        from paper_daily.sync_ordering import active_items, observed_set, scope

        canonical = {
            (row[0], row[1]): json.loads(row[2])
            for row in conn.execute("SELECT * FROM paperfact_sync_graph")
        }
        pending = self._pending_graph(conn, cursor)
        optimistic = dict(canonical)
        for op in pending:
            if op["version"] == 2:
                optimistic[(op["entity_type"], op["entity_id"])] = {
                    "active": op["action"] == "put",
                    "incarnation": op["incarnation"],
                    "parents": op["parents"],
                }
        projected = {}
        for row in conn.execute(
            "SELECT entity_type,entity_id,operation,active FROM paperfact_sync_graph_projection "
            "WHERE operation IS NOT NULL"
        ):
            op = json.loads(row[2])
            projected[(row[0], row[1])] = {
                "active": bool(row[3]),
                "incarnation": op["incarnation"],
                "parents": op["parents"],
            }
        heads = {
            (row["entity_type"], row["entity_id"]): row
            for row in conn.execute(
                "SELECT h.*,p.source FROM paperfact_sync_heads h "
                "JOIN paperfact_sync_graph_projection p USING(entity_type,entity_id) "
                "WHERE h.entity_type IN ('list_order','workspace_list_order')"
            )
        }
        stubs = {
            ("workspace_list_order", "workspace-lists"): {
                "workspace_id": self.journal.workspace_id,
                "entity_type": "workspace_list_order",
                "entity_id": "workspace-lists",
                "parents": [],
            }
        }
        for (kind, identity), value in canonical.items():
            if kind == "list" and value["active"]:
                stubs[("list_order", identity)] = {
                    "workspace_id": self.journal.workspace_id,
                    "entity_type": "list_order",
                    "entity_id": identity,
                    "parents": [
                        {"kind": "list", "id": identity, "incarnation": value["incarnation"]}
                    ],
                }
        for key, head in heads.items():
            stubs.setdefault(key, json.loads(head["operation"] or head["source"]))

        def mark(key, reason, *, applied=False, operation=None, visible=False):
            if key not in heads:
                return
            conn.execute(
                "UPDATE paperfact_sync_graph_projection SET reason=? "
                "WHERE entity_type=? AND entity_id=?",
                (reason, *key),
            )
            if applied:
                conn.execute(
                    "UPDATE paperfact_sync_heads SET applied_revision=revision "
                    "WHERE entity_type=? AND entity_id=?",
                    key,
                )
                conn.execute(
                    "UPDATE paperfact_sync_graph_projection SET operation=?,active=? "
                    "WHERE entity_type=? AND entity_id=?",
                    (canonical_operation(operation), int(visible), *key),
                )

        applied = 0
        for key, stub in stubs.items():
            head = heads.get(key)
            source = json.loads(head["operation"] or head["source"]) if head else None
            callback_scope = {**scope(stub), "workspace_id": self.journal.workspace_id}
            if any((op["entity_type"], op["entity_id"]) == key for op in pending):
                mark(key, "pending_local")
                continue
            if self.order_writer is None:
                mark(key, "order_writer_unavailable")
                continue
            parent = stub["parents"][0] if stub["parents"] else None
            if parent:
                root_key = ("list", parent["id"])
                root = canonical.get(root_key)
                if root is None or not root["active"]:
                    mark(key, None, applied=True, operation=source)
                    continue
                local_root = projected.get(root_key)
                if (
                    local_root is None
                    or not local_root["active"]
                    or local_root["incarnation"] != root["incarnation"]
                    or any((op["entity_type"], op["entity_id"]) == root_key for op in pending)
                ):
                    mark(key, "parent_pending")
                    continue
            actual = active_items(stub, canonical)
            # Neither a local lifecycle change nor a deferred graph parent may be
            # overwritten by a positional callback with a smaller/different set.
            if active_items(stub, optimistic) != actual or active_items(stub, projected) != actual:
                mark(key, "pending_descendant")
                continue
            revision = head["revision"] if head else 0
            digest = observed_set(stub, actual)
            encoded_scope = json.dumps(callback_scope, sort_keys=True)
            cached = conn.execute(
                "SELECT revision,digest FROM paperfact_sync_order_projection WHERE scope=?",
                (encoded_scope,),
            ).fetchone()
            explicit = (
                source is not None
                and head["operation"] is not None
                and source["action"] == "put"
                and scope(source) == scope(stub)
            )
            if (
                cached is not None
                and tuple(cached) == (revision, digest)
                and (head is None or head["applied_revision"] == revision)
            ):
                mark(key, None)
                continue
            remaining = {(item["id"], item["incarnation"]): item for item in actual}
            ordered = []
            for item in source["payload"]["items"] if explicit else []:
                found = remaining.pop((item["id"], item["incarnation"]), None)
                if found:
                    ordered.append(found)

            def created(item, order_kind=key[0]):
                row = conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                    (item["incarnation"],),
                ).fetchone()
                event = json.loads(row[0]) if row else None
                expected_kind = "list" if order_kind == "workspace_list_order" else "membership"
                if (
                    event is None
                    or event["outcome"] != "accepted"
                    or event["operation"]["entity_type"] != expected_kind
                    or event["operation"]["entity_id"] != item["id"]
                    or event["operation"]["incarnation"] != item["incarnation"]
                    or event["operation"]["action"] != "put"
                ):
                    raise ValueError("Ordering requires the accepted creation receipt")
                return event["sequence"], item["id"]

            ordered.extend(sorted(remaining.values(), key=created))
            conn.set_authorizer(self.journal._authorize_writer)
            try:
                self.order_writer(conn, callback_scope, ordered)
            finally:
                conn.set_authorizer(None)
            conn.execute(
                "INSERT INTO paperfact_sync_order_projection VALUES(?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET revision=excluded.revision,"
                "digest=excluded.digest",
                (encoded_scope, revision, digest),
            )
            if head:
                mark(key, None, applied=True, operation=source, visible=explicit)
            applied += 1
        return applied

    def _materialize(self, conn, cursor):
        applied = self._materialize_legacy(conn, cursor) + self._materialize_graph(conn, cursor)
        return applied + self._materialize_orders(conn, cursor)

    def sync_once(self, transport, token, *, limit=100, prepare_push=None):
        """One bounded pass, with no timer, hidden retries, login or network policy."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid sync batch limit")
        if prepare_push is not None and not callable(prepare_push):
            raise ValueError("Push preparation must be callable")
        if not self._running.acquire(blocking=False):
            return {"busy": True}
        try:
            pushed, deferred_push = 0, 0
            skipped = set()
            for operation in self.journal.pending(limit):
                dependencies = {operation.get("depends_on"), operation.get("structure_depends_on")}
                dependencies.update(ref["incarnation"] for ref in operation.get("parents", []))
                dependencies.update(
                    ref["incarnation"] for ref in operation.get("source_dependencies", [])
                )
                if operation["entity_type"] in ("list_order", "workspace_list_order"):
                    dependencies.update(
                        item["incarnation"] for item in operation["payload"].get("items", [])
                    )
                ready = not bool(dependencies & skipped)
                if ready and prepare_push is not None:
                    # Preparation can inspect an immutable intent but cannot modify
                    # the envelope subsequently acknowledged by this client.
                    prepared = json.loads(canonical_operation(operation))
                    ready = prepare_push(prepared)
                    if canonical_operation(prepared) != canonical_operation(operation):
                        raise ValueError("Push preparation cannot change a saved operation")
                    if type(ready) is not bool:
                        raise ValueError("Push preparation must return a boolean")
                if not ready:
                    skipped.add(operation["operation_id"])
                    deferred_push += 1
                    continue
                event = transport.push(token, operation)
                validate_event(event, self.journal.workspace_id)
                if event["operation"] != operation:
                    raise ValueError("Acknowledgment belongs to another operation")
                self.journal.acknowledge(operation["operation_id"], event["sequence"])
                pushed += 1
            events = transport.pull(token, after=self.status()["cursor"], limit=limit)
            received = self.receive(events)
            return {
                "busy": False,
                "pushed": pushed,
                "deferred_push": deferred_push,
                **received,
                **self.status(),
            }
        finally:
            self._running.release()
