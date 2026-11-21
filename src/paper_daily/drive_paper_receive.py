"""Apply a verified first bibliography to an ordinary reader without replacing local papers."""

import json
import sqlite3
from contextlib import closing
from uuid import NAMESPACE_URL, uuid5

from paper_daily.drive_list_history import DriveListPapers
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import decode, encode
from paper_daily.library_directory import ScopeHead
from paper_daily.store import title_key
from paper_daily.workspace_service import _read


def _local_paper(conn, store, paper, published):
    identity, payload = paper["entity_id"], paper["payload"]
    known = conn.execute(
        "SELECT local_id FROM drive_library_papers WHERE context=? AND remote_id=?",
        (store.context, identity),
    ).fetchone()
    if known and published and known != published:
        raise ListReviewRequired("Incoming paper has conflicting local identity records")
    known = known or published
    if known:
        if not conn.execute("SELECT 1 FROM papers WHERE id=?", known).fetchone():
            raise ListReviewRequired("Previously received paper was removed locally")
        return known[0]
    local_id = "sync:" + identity
    key = title_key(payload["title"])
    if conn.execute(
        "SELECT 1 FROM papers WHERE id=? OR (title_key=? AND title_key!='') "
        "OR doi=? COLLATE NOCASE OR arxiv_id=? OR s2_id=? LIMIT 1",
        (
            local_id,
            key,
            payload["doi"] or None,
            payload["arxiv_id"] or None,
            payload["s2_id"] or None,
        ),
    ).fetchone():
        raise ListReviewRequired("Possible existing paper; review before joining this bibliography")
    conn.execute(
        "INSERT INTO papers(id,title,title_key,authors_json,venue,year,source,abstract,"
        "doi,arxiv_id,s2_id,page_url,pdf_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            local_id,
            payload["title"],
            key,
            json.dumps(payload["authors"], ensure_ascii=False),
            payload["venue"] or "",
            payload["year"] or 0,
            payload["source"] or "sync",
            *(payload[k] for k in ("abstract", "doi", "arxiv_id", "s2_id", "page_url", "pdf_url")),
        ),
    )
    conn.execute(
        "INSERT INTO drive_library_papers VALUES(?,?,?)", (store.context, identity, local_id)
    )
    return local_id


def receive_initial(directory, store, list_id, revision, ticket):
    history = DriveListPapers(directory, store, list_id)
    history._check(revision)
    with _read(store.workspace.path) as conn:
        prior = None
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='drive_library_bibliographies'"
        ).fetchone():
            prior = conn.execute(
                "SELECT head FROM drive_library_bibliographies WHERE context=? AND list_id=?",
                (store.context, list_id),
            ).fetchone()
    anchor = ScopeHead(**decode(prior[0])) if prior else None
    head, records = history.changes(anchor, revision=revision)
    if anchor is not None and head == anchor:
        return head
    if head is None:
        return None
    pairs = list(zip(records[::2], records[1::2], strict=True))
    if len({paper["entity_id"] for paper, _ in pairs}) != len(pairs):
        raise ListReviewRequired("Subsequent bibliography revisions need reconciliation")
    marker = encode(head.record())
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        store._check()
        selection = store._load(settings)
        if selection.revision != revision or list_id not in selection.selected:
            raise ValueError("This device changed its list selection")
        uri = store.workspace.path.as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            ticket.check()
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
            ).fetchone():
                raise ListReviewRequired("Use the existing enrolled workspace")
            if not conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
                raise ListReviewRequired("Receive the list details before its papers")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drive_library_papers(context TEXT, remote_id TEXT, "
                "local_id TEXT NOT NULL, PRIMARY KEY(context,remote_id), UNIQUE(context,local_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drive_library_bibliographies(context TEXT,list_id TEXT,"
                "head BLOB NOT NULL, PRIMARY KEY(context,list_id))"
            )
            current = conn.execute(
                "SELECT head FROM drive_library_bibliographies WHERE context=? AND list_id=?",
                (store.context, list_id),
            ).fetchone()
            if current != prior:
                raise ValueError("Bibliography changed while receiving; retry")
            if (
                not prior
                and not any(p["device_id"] == store.context for p, _ in pairs)
                and conn.execute(
                    "SELECT 1 FROM list_papers WHERE list_id=? LIMIT 1", (list_id,)
                ).fetchone()
            ):
                raise ListReviewRequired(
                    "Keep existing local bibliography; review incoming changes"
                )
            first = conn.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM list_papers WHERE list_id=?", (list_id,)
            ).fetchone()[0]
            has_published = settings.execute(
                "SELECT 1 FROM sqlite_master WHERE name='published_paper_ids'"
            ).fetchone()
            originals = None
            for paper, member in pairs:
                ticket.check()
                published = (
                    settings.execute(
                        "SELECT local_id FROM published_paper_ids WHERE remote_id=?",
                        (paper["entity_id"],),
                    ).fetchone()
                    if has_published
                    else None
                )
                if member["device_id"] == paper["device_id"] == store.context:
                    if not published:
                        # Older source builds generated the same UUID but stored no receipt.
                        if originals is None:
                            namespace = uuid5(
                                NAMESPACE_URL,
                                f"paperfact:{store.library_id}:{store.context}:papers",
                            )
                            originals = {
                                str(uuid5(namespace, key)): key
                                for (key,) in conn.execute(
                                    "SELECT paper_id FROM list_papers WHERE list_id=?", (list_id,)
                                )
                            }
                        published = (originals.get(paper["entity_id"]),)
                    if not conn.execute(
                        "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?",
                        (list_id, published[0]),
                    ).fetchone():
                        raise ListReviewRequired("Published membership was removed locally")
                    continue
                local_id = _local_paper(conn, store, paper, published)
                if conn.execute(
                    "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?", (list_id, local_id)
                ).fetchone():
                    raise ListReviewRequired("Existing membership changed; review before applying")
                conn.execute(
                    "INSERT INTO list_papers(list_id,paper_id,position,citation,added_at) "
                    "VALUES(?,?,?,?,?)",
                    (
                        list_id,
                        local_id,
                        first,
                        member["payload"]["citation"],
                        member["payload"]["added_at"],
                    ),
                )
                first += 1
            conn.execute(
                "INSERT INTO drive_library_bibliographies VALUES(?,?,?) "
                "ON CONFLICT(context,list_id) "
                "DO UPDATE SET head=excluded.head",
                (store.context, list_id, marker),
            )
            store._check()
            ticket.checkpoint(conn.commit)
    return head


def exchange_bibliography(directory, store, list_id, revision, ticket):
    from paper_daily.drive_paper_baseline import publish_initial

    head = receive_initial(directory, store, list_id, revision, ticket)
    return publish_initial(
        directory, store, list_id, revision, ticket, append_new=True, received_head=head
    )
