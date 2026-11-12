"""Shared, explicit graph research actions for future UI/CLI/MCP adapters.

These actions receive already-resolved research. They never call an AI provider,
download a PDF, change the active workspace, or enable sync on app startup.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from paper_daily.sync_journal import MAX_BYTES, _identifier, canonical_operation
from paper_daily.sync_schema_v2 import membership_id

MAX_ACTION_BYTES = 8 * 1024 * 1024
MAX_PAPERS = 200


class ResearchOperations:
    """One retry identity and one transaction for a compound research action."""

    def __init__(self, client, *, expected=None):
        # Explicit local preparation may initialize the ledger only in its
        # originally observed database. Existing callers keep their contract.
        def current(conn=None):
            if expected is None:
                return
            from pathlib import Path

            if (
                not isinstance(expected, tuple)
                or len(expected) != 2
                or not isinstance(expected[1], tuple)
                or len(expected[1]) != 2
                or any(type(value) is not int for value in expected[1])
                or not expected[1][1]
            ):
                raise ValueError("Expected a known original database identity")
            path = Path(expected[0]).resolve()
            info = path.stat()
            if (
                Path(client.journal.path).resolve() != path
                or (info.st_dev, info.st_ino) != expected[1]
            ):
                raise ValueError("Original action database was replaced")
            if conn is not None:
                actual = next(
                    (row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"),
                    None,
                )
                if not actual or Path(actual).resolve() != path:
                    raise ValueError("Action connection belongs to another database")

        def ledger(conn):
            if expected is None:
                return
            row = conn.execute(
                "SELECT type,sql FROM sqlite_master WHERE name='research_action_receipts'"
            ).fetchone()
            if row is not None and row[0] == "table":
                columns = [tuple(value) for value in conn.execute(
                    "PRAGMA table_info(research_action_receipts)"
                )]
                if columns != [
                    (0, "request_id", "TEXT", 0, None, 1),
                    (1, "fingerprint", "TEXT", 1, None, 0),
                    (2, "result", "TEXT", 1, None, 0),
                ]:
                    raise ValueError("Existing action ledger columns are unsupported")
            wanted = (
                "CREATE TABLE research_action_receipts "
                "(request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL)"
            )
            def normalize(value):
                return "".join(value.upper().split()).replace("IFNOTEXISTS", "")
            if row is not None and (
                row[0] != "table" or not row[1] or normalize(row[1]) != normalize(wanted)
            ):
                raise ValueError("Existing action ledger schema is unsupported")

        current()
        self.client = client
        with client.journal.transaction() as conn:
            current(conn)
            ledger(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_action_receipts "
                "(request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL)"
            )
            current(conn)

    def create_list(self, name, papers, *, request_id, note=""):
        return self._intake("create", None, name, note, papers, request_id)

    def add_papers(self, list_id, papers, *, request_id):
        _identifier(list_id)
        return self._intake("add", list_id, None, None, papers, request_id)

    def attach_document(self, paper_id, manifest, *, store, request_id):
        """Attach staged, verified PDF bytes through the common research action API."""
        from paper_daily.sync_document_actions import attach_document

        return attach_document(self, paper_id, manifest, store=store, request_id=request_id)

    def set_reading_state(self, list_id, paper_ids, state, *, request_id):
        """Record one explicit, retry-safe reading action for selected memberships.

        Each list has its own state for a shared paper. An explicit mark on a
        restored membership creates fresh state in its current incarnation; old
        offline state is never silently reattached to it.
        """
        _identifier(list_id)
        _identifier(request_id)
        if not isinstance(state, str) or state not in {
            "pending",
            "delivered",
            "read",
            "skipped",
            "deferred",
        }:
            raise ValueError("Unsupported reading state")
        if not isinstance(paper_ids, list):
            raise ValueError("Select between 1 and 200 papers")
        paper_ids = paper_ids.copy()
        if not 1 <= len(paper_ids) <= MAX_PAPERS:
            raise ValueError("Select between 1 and 200 papers")
        for paper_id in paper_ids:
            if not isinstance(paper_id, str) or str(UUID(paper_id)) != paper_id:
                raise ValueError("Reading state requires portable paper UUIDs")
        if len(set(paper_ids)) != len(paper_ids):
            raise ValueError("Reading selection contains duplicate papers")
        request = json.dumps(
            {"mode": "reading_state", "list_id": list_id, "paper_ids": paper_ids, "state": state},
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(request.encode("utf-8")).hexdigest()
        journal = self.client.journal
        with journal.transaction() as conn:
            receipt = conn.execute(
                "SELECT fingerprint,result FROM research_action_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if receipt:
                if receipt[0] != fingerprint:
                    raise ValueError("Research action retry changed its content")
                return json.loads(receipt[1])
            result = {"list_id": list_id, "papers": [], "operation_ids": []}
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            graph = self.client._optimistic_graph(conn)[0]
            for index, paper_id in enumerate(paper_ids):
                member_id = membership_id(list_id, paper_id)
                member = graph.get(("membership", member_id))
                if member is None or not member["active"]:
                    raise ValueError("Reading state requires an active graph membership")
                row = conn.execute(
                    "SELECT lp.delivered_at,lp.read_at FROM list_papers lp "
                    "JOIN research_paper_identity p ON p.local_id=lp.paper_id "
                    "WHERE lp.list_id=? AND p.sync_id=?",
                    (list_id, paper_id),
                ).fetchone()
                if row is None:
                    raise ValueError("Reading membership is unavailable in this workspace")
                payload = {
                    "list_id": list_id,
                    "paper_id": paper_id,
                    "state": state,
                    "delivered_at": stamp if state == "delivered" else row[0],
                    "read_at": stamp if state == "read" else row[1],
                }
                parents = [
                    {"kind": "membership", "id": member_id, "incarnation": member["incarnation"]},
                    *member["parents"],
                ]
                old = graph.get(("reading_state", member_id))
                restore = old is not None and (
                    not old["active"]
                    or self.client._parent_keys(old["parents"]) != self.client._parent_keys(parents)
                )
                operation = self.client.new_graph_operation_in(
                    conn,
                    "reading_state",
                    member_id,
                    payload,
                    operation_id=self._id(request_id, f"reading-state-op:{index}"),
                    restore=restore,
                )
                journal.apply_in(conn, operation, self.client.writer)
                result["operation_ids"].append(operation["operation_id"])
                result["papers"].append(
                    {key: payload[key] for key in ("paper_id", "state", "delivered_at", "read_at")}
                )
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Research action receipt exceeds its bounded size")
            conn.execute(
                "INSERT INTO research_action_receipts VALUES(?,?,?)",
                (request_id, fingerprint, encoded),
            )
            return json.loads(encoded)

    def reorder_papers(self, list_id, paper_ids, *, request_id):
        """Save the complete paper permutation for one list without changing content."""
        _identifier(list_id)
        if not isinstance(paper_ids, list):
            raise ValueError("Paper order must be a list of portable UUIDs")
        identities = paper_ids.copy()
        if len(identities) > 2000:
            raise ValueError("Order accepts at most 2000 entries")
        members = [membership_id(list_id, identity) for identity in identities]
        return self._reorder("list_order", list_id, members, request_id)

    def reorder_lists(self, list_ids, *, request_id):
        """Save the complete workspace list permutation with an independent revision."""
        return self._reorder("workspace_list_order", "workspace-lists", list_ids, request_id)

    def _reorder(self, kind, identity, ordered_ids, request_id):
        _identifier(request_id)
        if not isinstance(ordered_ids, list):
            raise ValueError("Order must be a list of research identities")
        ordered_ids = ordered_ids.copy()
        if len(ordered_ids) > 2000:
            raise ValueError("Order accepts at most 2000 entries")
        for item in ordered_ids:
            _identifier(item)
        if len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError("Order cannot contain duplicate identities")
        request = json.dumps(
            {"mode": kind, "entity_id": identity, "ordered_ids": ordered_ids},
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(request.encode("utf-8")).hexdigest()
        journal = self.client.journal
        with journal.transaction() as conn:
            receipt = conn.execute(
                "SELECT fingerprint,result FROM research_action_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if receipt:
                if receipt[0] != fingerprint:
                    raise ValueError("Research action retry changed its content")
                return json.loads(receipt[1])
            graph = self.client._optimistic_graph(conn)[0]
            old = graph.get((kind, identity))
            expected = []
            if kind == "list_order":
                scope = graph.get(("list", identity))
                if scope is None or not scope["active"]:
                    raise ValueError("Ordering requires an active graph list")
                expected = [{"kind": "list", "id": identity, "incarnation": scope["incarnation"]}]
            restore = old is not None and (
                not old["active"]
                or self.client._parent_keys(old["parents"]) != self.client._parent_keys(expected)
            )
            operation = self.client.new_order_operation_in(
                conn,
                kind,
                identity,
                ordered_ids,
                operation_id=self._id(request_id, "order-op"),
                restore=restore,
            )
            journal.apply_in(conn, operation, self.client.writer)
            result = {
                "kind": kind,
                "entity_id": identity,
                "ordered_ids": ordered_ids,
                "operation_id": operation["operation_id"],
            }
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Research action receipt exceeds its bounded size")
            conn.execute(
                "INSERT INTO research_action_receipts VALUES(?,?,?)",
                (request_id, fingerprint, encoded),
            )
            return json.loads(encoded)

    def _id(self, request_id, label):
        namespace = json.dumps(
            [self.client.journal.workspace_id, self.client.journal.device_id, request_id, label],
            separators=(",", ":"),
        )
        return str(uuid5(NAMESPACE_URL, "paperfact:research-action:" + namespace))

    def _request(self, mode, list_id, name, note, papers, request_id):
        _identifier(request_id)
        if mode == "create" and (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 200
            or not isinstance(note, str)
            or len(note) > 128 * 1024
        ):
            raise ValueError("Invalid list name or note")
        if not isinstance(papers, list) or len(papers) > MAX_PAPERS:
            raise ValueError("An intake action accepts at most 200 paper entries")
        byte_count, normalized, reused = 0, [], set()
        operations = 1 if mode == "create" else 0
        for index, item in enumerate(papers):
            if not isinstance(item, dict) or not set(item) <= {
                "paper",
                "paper_id",
                "notes",
                "citation",
            }:
                raise ValueError("Invalid paper entry fields")
            if ("paper" in item) == ("paper_id" in item):
                raise ValueError("Choose new paper metadata or an existing portable paper ID")
            notes, citation = item.get("notes", []), item.get("citation")
            if not isinstance(notes, list) or len(notes) > 100:
                raise ValueError("Invalid note collection")
            operations += len(notes) + (2 if "paper" in item else 1)
            if operations > 1000:
                raise ValueError(
                    "Research intake requires bounded batches of at most 1000 operations"
                )
            for body in notes:
                if not isinstance(body, str) or len(body.encode("utf-8")) > 200 * 1024:
                    raise ValueError("Invalid bounded note body")
                byte_count += len(body.encode("utf-8"))
            if citation is not None and (not isinstance(citation, str) or len(citation) > 4000):
                raise ValueError("Invalid membership citation")
            if "paper_id" in item:
                identity = item["paper_id"]
                if not isinstance(identity, str) or str(UUID(identity)) != identity:
                    raise ValueError("Existing paper requires a portable UUID")
                if identity in reused:
                    raise ValueError("An intake action cannot repeat an existing paper")
                reused.add(identity)
            else:
                identity = self._id(request_id, f"paper:{index}")
                op_id = self._id(request_id, f"paper-op:{index}")
                encoded = canonical_operation(
                    {
                        "version": 2,
                        "operation_id": op_id,
                        "workspace_id": self.client.journal.workspace_id,
                        "device_id": self.client.journal.device_id,
                        "entity_type": "paper",
                        "entity_id": identity,
                        "action": "put",
                        "base_revision": 0,
                        "depends_on": None,
                        "payload": item["paper"],
                        "incarnation": op_id,
                        "parents": [],
                        "structure_revision": 0,
                    }
                )
                byte_count += len(encoded.encode("utf-8"))
            if byte_count > MAX_ACTION_BYTES:
                raise ValueError("Research intake exceeds 8 MiB")
            normalized.append({**item, "notes": notes, "citation": citation})
        encoded = json.dumps(
            {"mode": mode, "list_id": list_id, "name": name, "note": note, "papers": normalized},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > MAX_ACTION_BYTES:
            raise ValueError("Research intake exceeds 8 MiB")
        return json.loads(encoded), hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _intake(self, mode, list_id, name, note, papers, request_id):
        value, fingerprint = self._request(mode, list_id, name, note, papers, request_id)
        journal = self.client.journal
        with journal.transaction() as conn:
            receipt = conn.execute(
                "SELECT fingerprint,result FROM research_action_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if receipt:
                if receipt[0] != fingerprint:
                    raise ValueError("Research action retry changed its content")
                return json.loads(receipt[1])
            list_id = list_id or self._id(request_id, "list")
            operation_ids = []

            def save(kind, identity, payload, label):
                operation = self.client.new_graph_operation_in(
                    conn, kind, identity, payload, operation_id=self._id(request_id, label)
                )
                # The journal and every typed projection write share this one transaction.
                journal.apply_in(conn, operation, self.client.writer)
                operation_ids.append(operation["operation_id"])

            if mode == "create":
                save("list", list_id, {"name": value["name"], "note": value["note"]}, "list-op")
            else:
                graph = self.client._optimistic_graph(conn)[0].get(("list", list_id))
                if graph is None or not graph["active"]:
                    raise ValueError("List must be active in the graph before adding papers")
            result = {"list_id": list_id, "papers": [], "operation_ids": operation_ids}
            added_at = datetime.now(UTC).isoformat(timespec="seconds")
            for index, item in enumerate(value["papers"]):
                if "paper" in item:
                    paper_id = self._id(request_id, f"paper:{index}")
                    save("paper", paper_id, item["paper"], f"paper-op:{index}")
                else:
                    paper_id = item["paper_id"]
                member = membership_id(list_id, paper_id)
                existing = conn.execute(
                    "SELECT lp.added_at FROM list_papers lp "
                    "JOIN research_paper_identity p ON p.local_id=lp.paper_id "
                    "WHERE lp.list_id=? AND p.sync_id=?",
                    (list_id, paper_id),
                ).fetchone()
                membership_time = existing[0] if existing is not None else added_at
                save(
                    "membership",
                    member,
                    {
                        "list_id": list_id,
                        "paper_id": paper_id,
                        "citation": item["citation"],
                        "added_at": membership_time,
                    },
                    f"member-op:{index}",
                )
                entry = {"paper_id": paper_id, "membership_id": member, "note_ids": []}
                for offset, body in enumerate(item["notes"]):
                    identity = self._id(request_id, f"note:{index}:{offset}")
                    save(
                        "note",
                        identity,
                        {"paper_id": paper_id, "body": body},
                        f"note-op:{index}:{offset}",
                    )
                    entry["note_ids"].append(identity)
                result["papers"].append(entry)
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Research action receipt exceeds its bounded size")
            conn.execute(
                "INSERT INTO research_action_receipts VALUES(?,?,?)",
                (request_id, fingerprint, encoded),
            )
            return json.loads(encoded)
