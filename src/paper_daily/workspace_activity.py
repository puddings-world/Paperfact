"""Read existing activity in one bounded read-only snapshot; never initialize sync."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from paper_daily import file_change
from paper_daily.activity_projection import WINDOW, _same, graph_active, project_activity
from paper_daily.sync_client import validate_event
from paper_daily.sync_journal import _identifier, canonical_operation
from paper_daily.workspace_service import (
    Ticket,
    WorkspaceChanged,
    _binding,
    _read,
    _safe_path,
    _tables,
)

MAX_BYTES = 8 * 1024**2


_SEAL = object()


def _versions(path):
    values = []
    for index, item in enumerate((path, Path(str(path) + "-wal"))):
        observed = file_change.version(item) if item.exists() else None
        # A read-only SQLite open may create/close a zero-byte WAL. It contains
        # no header or frames; DB changes and every nonempty WAL remain guarded.
        if index == 1 and observed is not None and observed[2] == 0:
            observed = None
        values.append((str(item), observed))
    return tuple(values)


@dataclass(frozen=True, eq=False)
class PreparedActivity(Mapping):
    """Immutable worker result; native witnesses invalidate every semantic proof."""

    _json: str
    _versions: tuple
    _reader: object
    _seal: object

    def __getitem__(self, key):
        return json.loads(self._json)[key]

    def __iter__(self):
        return iter(json.loads(self._json))

    def __len__(self):
        return len(json.loads(self._json))


class ActivityReader:
    def __init__(self, database, *, current_path=None):
        # Capture before scheduling; no SQL or source hashing on construction.
        self.path = _safe_path(database)
        info = self.path.stat()
        self.identity = info.st_dev, info.st_ino
        self.current_path = current_path or (lambda: self.path)
        self._path_check()
        self._initial = self._observed = _versions(self.path)
        self.binding = None
        self.needs_reopen = False
        self.workspace_id = self.device_id = None
        self._token = object()

    def _path_check(self):
        if Path(self.current_path()).resolve() != self.path:
            raise WorkspaceChanged("The selected workspace changed")
        info = _safe_path(self.path).stat()
        if not info.st_ino or (info.st_dev, info.st_ino) != self.identity:
            raise WorkspaceChanged("The selected database was replaced")

    def current(self, prepared=None):
        try:
            self.check(prepared)
            return True
        except (OSError, ValueError, WorkspaceChanged):
            return False

    def check(self, prepared=None):
        """Native metadata only. A stale proof needs an explicit worker refresh."""
        self._path_check()
        expected = self._observed
        if prepared is not None:
            if (
                not isinstance(prepared, PreparedActivity)
                or prepared._seal is not _SEAL
                or prepared._reader is not self._token
            ):
                raise WorkspaceChanged("Unrecognized activity proof")
            expected = prepared._versions
        if _versions(self.path) != expected:
            raise WorkspaceChanged("The selected records changed")

    def _begin(self, conn, versions):
        binding = _binding(conn, _tables(conn))
        if self.binding is None:
            if versions != self._initial:
                self.needs_reopen = True
                raise WorkspaceChanged("The workspace changed before the first read")
            self.binding = binding
            identity = next(
                (value for name, value in binding if name == "paperfact_sync_identity"), None
            )
            self.workspace_id, self.device_id = identity or (None, None)
        elif binding != self.binding:
            self.needs_reopen = True
            raise WorkspaceChanged("The selected binding changed")

    def _prepare(self, value, versions, ticket):
        ticket.check()
        self._path_check()
        if _versions(self.path) != versions:
            raise WorkspaceChanged("The records changed during the read")
        prepared = PreparedActivity(
            json.dumps(value, ensure_ascii=False), versions, self._token, _SEAL
        )
        self._observed = versions
        return prepared

    @staticmethod
    def _decode(value, budget):
        if not isinstance(value, str):
            raise ValueError("Stored activity exceeds its bounded row size")
        budget[0] += len(value.encode("utf-8"))
        if budget[0] > MAX_BYTES:
            raise ValueError("Activity window exceeds its bounded size")
        return json.loads(value)

    def _event(self, encoded, budget, sequence, outcome):
        event = self._decode(encoded, budget)
        if (
            validate_event(event, self.workspace_id) != encoded
            or event["sequence"] != sequence
            or event["outcome"] != outcome
        ):
            raise ValueError("Stored activity differs from its canonical receipt")
        return event

    def _facts(self, conn, tables, events, cursor, ticket, budget):
        heads, graph, pending, notes, papers = {}, {}, set(), {}, {}
        keys = {(e["operation"]["entity_type"], e["operation"]["entity_id"]) for e in events}
        queue = list(keys)
        for event in events:
            queue.extend((p["kind"], p["id"]) for p in event["operation"].get("parents", []))
        while queue:
            ticket.check()
            key = queue.pop()
            if key in graph:
                continue
            if len(graph) >= 2000:
                raise ValueError("Activity parent closure exceeds its bound")
            row = conn.execute(
                "SELECT CASE WHEN length(CAST(metadata AS BLOB))<=16384 THEN metadata END "
                "FROM paperfact_sync_graph WHERE entity_type=? AND entity_id=?",
                key,
            ).fetchone()
            if row is None:
                continue
            metadata = self._decode(row[0], budget)
            if (
                not isinstance(metadata, dict)
                or set(metadata) != {"incarnation", "structure_revision", "active", "parents"}
                or type(metadata["active"]) is not bool
                or not isinstance(metadata["parents"], list)
                or len(metadata["parents"]) > 3
            ):
                raise ValueError("Invalid stored activity parent")
            _identifier(metadata["incarnation"])
            for parent in metadata["parents"]:
                if not isinstance(parent, dict) or set(parent) != {"kind", "id", "incarnation"}:
                    raise ValueError("Invalid stored activity parent reference")
                for value in parent.values():
                    _identifier(value)
                queue.append((parent["kind"], parent["id"]))
            graph[key] = metadata
        for key in keys:
            ticket.check()
            row = conn.execute(
                "SELECT h.revision,h.applied_revision,p.reason FROM paperfact_sync_heads h "
                "LEFT JOIN paperfact_sync_graph_projection p USING(entity_type,entity_id) "
                "WHERE h.entity_type=? AND h.entity_id=?",
                key,
            ).fetchone()
            if row:
                heads[key] = {"revision": row[0], "applied_revision": -1 if row[2] else row[1]}
            if conn.execute(
                "SELECT 1 FROM paperfact_sync_operations WHERE entity_type=? AND entity_id=? "
                "AND (server_revision IS NULL OR server_revision>?) LIMIT 1",
                (*key, cursor),
            ).fetchone():
                pending.add(key)
        for kind, identity in graph:
            if kind != "paper" or "research_paper_identity" not in tables:
                continue
            row = conn.execute(
                "SELECT p.id,substr(p.title,1,160) FROM research_paper_identity i "
                "JOIN papers p ON p.id=i.local_id WHERE i.sync_id=?",
                (identity,),
            ).fetchone()
            if row:
                papers[identity] = {"local_id": row[0], "title": row[1]}
        if "research_note_identity" in tables:
            for kind, identity in keys:
                if kind != "note":
                    continue
                row = conn.execute(
                    "SELECT n.id,p.sync_id,CASE WHEN length(CAST(n.anchor AS BLOB))<=4096 "
                    "THEN n.anchor END,n.anchor IS NOT NULL FROM research_note_identity i "
                    "JOIN notes n ON n.id=i.local_id AND n.paper_id=i.paper_id "
                    "AND n.created_at=i.created_at JOIN research_paper_identity p "
                    "ON p.local_id=n.paper_id WHERE i.sync_id=?",
                    (identity,),
                ).fetchone()
                if row:
                    anchor = self._decode(row[2], budget) if row[3] else None
                    notes[identity] = {"local_id": row[0], "paper_id": row[1], "anchor": anchor}
        bound, resolved, current_hashes = set(), set(), {}
        for event in events:
            op = event["operation"]
            if "paperfact_sync_conflicts" in tables:
                row = conn.execute(
                    "SELECT resolved_by FROM paperfact_sync_conflicts WHERE operation_id=?",
                    (op["operation_id"],),
                ).fetchone()
                if row and row[0] is not None:
                    resolved.add(op["operation_id"])
            if op["entity_type"] == "research_file" and "research_file_applied" in tables:
                row = conn.execute(
                    "SELECT CASE WHEN length(CAST(operation AS BLOB))<=262144 THEN operation END "
                    "FROM research_file_applied WHERE entity_id=?",
                    (op["entity_id"],),
                ).fetchone()
                if row:
                    applied = self._decode(row[0], budget)
                    if canonical_operation(applied) == canonical_operation(op):
                        bound.add(op["operation_id"])
        if "research_document_desired" in tables:
            from paper_daily.sync_documents import applied_document, desired_document

            for identity in papers:
                desired = desired_document(conn, identity)
                if desired:
                    current_hashes[identity] = desired["sha256"]
                    applied = (
                        applied_document(conn, identity)
                        if "research_document_applied" in tables
                        else None
                    )
                    if desired == applied:
                        bound.add(desired["operation_id"])
        return dict(
            heads=heads,
            graph=graph,
            papers=papers,
            notes=notes,
            pending=pending,
            file_bindings=bound,
            resolved=resolved,
        ), current_hashes

    def _snapshot(self, conn, ticket):
        tables = _tables(conn)
        if _binding(conn, tables) != self.binding:
            raise WorkspaceChanged("The selected binding changed")
        if (
            self.workspace_id is None
            or "paperfact_sync_inbox" not in tables
            or "paperfact_sync_cursor" not in tables
        ):
            return {"available": False, "recent": [], "continue": [], "window": 0}, {}, {}
        cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()[0]
        rows = conn.execute(
            "SELECT sequence,outcome,CASE WHEN length(CAST(event AS BLOB))<=540672 THEN event END "
            "FROM paperfact_sync_inbox WHERE sequence<=? ORDER BY sequence DESC LIMIT ?",
            (cursor, WINDOW + 1),
        )
        budget, events, has_more = [0], [], False
        for index, row in enumerate(rows):
            ticket.check()
            if index == WINDOW:
                has_more = True
                break
            events.append(self._event(row[2], budget, row[0], row[1]))
        facts, hashes = self._facts(conn, tables, events, cursor, ticket, budget)
        result = project_activity(
            workspace_id=self.workspace_id,
            device_id=self.device_id,
            cursor=cursor,
            events=events,
            has_more=has_more,
            **facts,
        )
        result["available"] = True
        return result, facts, hashes

    def snapshot(self, ticket=None):
        ticket = ticket or Ticket()
        self._path_check()
        versions = _versions(self.path)
        if self.binding is None and versions != self._initial:
            self.needs_reopen = True
            raise WorkspaceChanged("The workspace changed before the first read")
        initializing = self.binding is None
        try:
            with _read(self.path) as conn:
                self._begin(conn, versions)
                result, _, _ = self._snapshot(conn, ticket)
            return self._prepare(result, versions, ticket)
        except BaseException:
            if initializing:
                # A failed first read must never establish a new binding for retry.
                self.binding = None
                self.workspace_id = self.device_id = None
                try:
                    self.needs_reopen = _versions(self.path) != self._initial
                except OSError:
                    self.needs_reopen = True
            raise

    def resolve(self, observed, *, locate=False, ticket=None):
        """Worker-only ownership and exact note proof, sealed to a native DB witness."""
        ticket = ticket or Ticket()
        self.check()
        versions = _versions(self.path)
        with _read(self.path, budget=0.5) as conn:
            tables = _tables(conn)
            if (
                _binding(conn, tables) != self.binding
                or self.workspace_id is None
                or type(observed.get("sequence")) is not int
            ):
                raise WorkspaceChanged("The activity selection is unavailable")
            stored = conn.execute(
                "SELECT outcome,CASE WHEN length(CAST(event AS BLOB))<=540672 THEN event END "
                "FROM paperfact_sync_inbox WHERE sequence=?",
                (observed["sequence"],),
            ).fetchone()
            if stored is None:
                raise WorkspaceChanged("The activity selection is unavailable")
            budget = [0]
            event = self._event(stored[1], budget, observed["sequence"], stored[0])
            cursor = conn.execute(
                "SELECT sequence FROM paperfact_sync_cursor WHERE id=1"
            ).fetchone()[0]
            facts, hashes = self._facts(conn, tables, [event], cursor, ticket, budget)
            result = project_activity(
                workspace_id=self.workspace_id,
                device_id=self.device_id,
                cursor=cursor,
                events=[event],
                **facts,
            )
            current = next(
                (
                    row
                    for row in [*result["continue"], *result["recent"]]
                    if row["sequence"] == observed.get("sequence")
                    and row["operation_id"] == observed.get("operation_id")
                ),
                None,
            )
            if (
                current is None
                or not current["paper_id"]
                or current["paper_id"] != observed.get("paper_id")
                or current["paper_incarnation"] != observed.get("paper_incarnation")
            ):
                raise WorkspaceChanged("This activity item is no longer current")
            if not graph_active(facts["graph"], ("paper", current["paper_id"])):
                raise WorkspaceChanged("The activity owner is unavailable")
            if locate and (
                current["resume"] is None or not _same(current["resume"], observed.get("resume"))
            ):
                raise WorkspaceChanged("This source-pinned note changed")
            paper = facts["papers"][current["paper_id"]]
            note = facts["notes"].get(current["entity_id"]) if locate else None
            value = {
                "row": current,
                "local_paper_id": paper["local_id"],
                "local_note_id": note["local_id"] if note else None,
                "current_hash": hashes.get(current["paper_id"]),
                "note_anchor": note["anchor"] if note else None,
            }
        return self._prepare(value, versions, ticket)
