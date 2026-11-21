"""Review exact common, local and remote versions of ordinary reader notes."""

import json
import sqlite3
from contextlib import closing

from paper_daily.drive_list_history import DriveListNotes
from paper_daily.drive_reader_notes import _payload, note_chains
from paper_daily.workspace_service import _read, _tables


def _cards(history, conn, settings, chains, ticket):
    tables = _tables(conn)
    if "research_capture_binding" in tables:
        raise ValueError("The workspace is now enrolled")
    if not {"drive_library_note_ids", "drive_library_note_bases"} <= tables:
        return
    for identity, chain in chains.items():
        ticket.check()
        latest = chain[-1]
        if len(chain) < 2:
            continue
        row = conn.execute(
            "SELECT b.operation_id,n.id,n.body,n.kind,n.created_at,n.page,n.anchor,p.title,p.id "
            "FROM drive_library_note_bases b JOIN drive_library_note_ids i "
            "ON i.remote_id=b.remote_id AND i.context=b.context "
            "JOIN notes n ON n.id=i.local_id JOIN papers p ON p.id=n.paper_id "
            "JOIN list_papers m ON m.paper_id=p.id AND m.list_id=b.list_id "
            "WHERE b.context=? AND b.list_id=? AND b.remote_id=? AND i.incarnation=? "
            "AND i.paper=?",
            (history.store.context, history.list_id, identity, latest["incarnation"],
             latest["parents"][0]["id"]),
        ).fetchone()
        if row is None or row[0] == latest["operation_id"]:
            continue
        paper = latest["payload"]["paper_id"]
        mapped = settings.execute("SELECT local_id FROM published_paper_ids WHERE remote_id=?",
                                  (paper,)).fetchone()
        if not mapped or mapped[0] != row[8] or paper != latest["parents"][0]["id"]:
            raise ValueError("The note's paper binding changed")
        base = next((op for op in chain if op["operation_id"] == row[0]), None)
        if base is None:
            raise ValueError("The common note revision is unavailable")
        local = _payload(paper, row[2:7])
        if local != base["payload"] and local != latest["payload"]:
            yield dict(context=history.store.context, grant=history.grant, list_id=history.list_id,
                       identity=identity, key=row[1], title=row[7], base_id=row[0],
                       remote_id=latest["operation_id"], base=base["payload"], local=local,
                       remote=latest["payload"])


def review(directory, store, list_id, revision, ticket, decision=None):
    history = DriveListNotes(directory, store, list_id, revision=revision)
    if not history.grant.startswith("edits-v1:"):
        raise PermissionError("Enable note edits for this list first")
    _, records = history.changes(None, revision=revision)
    chains = note_chains(history, records)
    if decision is None:
        with _read(store.workspace.path) as conn, _read(store.path) as settings:
            cards = list(_cards(history, conn, settings, chains, ticket))
        history._check(revision)
        ticket.check()
        return cards

    shown, choice = decision
    if choice not in ("local", "remote"):
        raise ValueError("Select a reviewed note version")
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(revision)
        with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                     timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            identity = shown["identity"]
            selected = {identity: chains[identity]} if identity in chains else {}
            current = next(_cards(history, conn, settings, selected, ticket), None)
            if current is None or current != shown:
                raise ValueError("The note changed after review. Compare its current versions.")
            if choice == "remote":
                payload = current["remote"]
                conn.execute("UPDATE notes SET body=?,kind=?,created_at=?,page=?,anchor=? "
                             "WHERE id=?", (payload["body"], payload["kind"], payload["created_at"],
                                            payload["page"], json.dumps(payload["anchor"])
                                            if payload["anchor"] is not None else None,
                                            current["key"]))
            conn.execute("UPDATE drive_library_note_bases SET operation_id=? "
                         "WHERE context=? AND list_id=? AND remote_id=?",
                         (current["remote_id"], store.context, list_id, identity))
            store._check()
            ticket.checkpoint(conn.commit)
