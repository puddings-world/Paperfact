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


def _same_work(conn, local_id, payload):
    """A shared title is not enough when the identifiers or the years disagree."""
    year, doi, arxiv = conn.execute(
        "SELECT year,doi,arxiv_id FROM papers WHERE id=?", (local_id,)
    ).fetchone()
    if doi and payload["doi"] and doi.casefold() != payload["doi"].casefold():
        return False
    if arxiv and payload["arxiv_id"] and arxiv != payload["arxiv_id"]:
        return False
    return not (year and payload["year"] and abs(year - payload["year"]) > 1)


def _local_paper(conn, store, paper, published, received, *, taken=None, merged=None):
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
    matches = conn.execute(
        "SELECT id FROM papers WHERE id=? OR (title_key=? AND title_key!='') "
        "OR doi=? COLLATE NOCASE OR arxiv_id=? OR s2_id=?",
        (
            local_id,
            key,
            payload["doi"] or None,
            payload["arxiv_id"] or None,
            payload["s2_id"] or None,
        ),
    )
    matches = [found for (found,) in matches]
    if local_id in matches:
        raise ListReviewRequired("Possible existing paper; review before joining this bibliography")
    from paper_daily.drive_transfer_progress import report

    report("download", title=payload["title"])
    # Distinct identities published together by one source can share bibliographic
    # metadata, so those stay apart. A paper this device already had is the same
    # work: join it, keeping the local copy and everything written on it. Refusing
    # here stopped a whole list on any device that already held one of its papers.
    own = [
        found for found in matches
        if received.get(found) != paper["device_id"]
        and not conn.execute(
            "SELECT 1 FROM drive_library_papers WHERE context=? AND local_id=?",
            (store.context, found),
        ).fetchone()
        and not (taken and taken(found))
        and _same_work(conn, found, payload)
    ]
    if len(own) == 1:
        conn.execute(
            "INSERT INTO drive_library_papers VALUES(?,?,?)", (store.context, identity, own[0])
        )
        if merged is not None:
            merged.add(own[0])
        return own[0]
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
    received[local_id] = paper["device_id"]
    return local_id


def _exact_existing_members(conn, store, list_id, pairs, ticket):
    from paper_daily.sync_capture import PAPER_COLUMNS, _payload

    columns = ",".join("p." + key for key in sorted(PAPER_COLUMNS))
    cursor = conn.execute(
        f"SELECT {columns},m.citation,m.added_at,m.position FROM list_papers m "
        "JOIN papers p ON p.id=m.paper_id WHERE m.list_id=? ORDER BY m.position,m.paper_id",
        (list_id,))
    cursor.row_factory = sqlite3.Row
    result = {}
    for row, (paper, member) in zip(cursor, pairs, strict=False):
        ticket.check()
        source = paper["device_id"]
        namespace = uuid5(NAMESPACE_URL, f"paperfact:{store.library_id}:{source}:papers")
        identity = paper["entity_id"]
        if (str(uuid5(namespace, row["id"])) != identity
                or _payload(conn, "papers", row) != paper["payload"]
                or member["payload"]["citation"] != row["citation"]
                or member["payload"]["added_at"] != row["added_at"]):
            break
        result[identity] = row["id"], row["position"]
    count, = conn.execute("SELECT count(*) FROM list_papers WHERE list_id=?", (list_id,)).fetchone()
    if len(result) != count or len(result) != len(pairs):
        raise ListReviewRequired("Keep existing local bibliography; review incoming changes")
    return result


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
        populated = conn.execute(
            "SELECT 1 FROM list_papers WHERE list_id=? LIMIT 1", (list_id,)
        ).fetchone()
    anchor = ScopeHead(**decode(prior[0])) if prior else None
    head = history._current_head()
    pages = list(history._pages_since(head, anchor, revision))
    if anchor is not None and head == anchor:
        return head
    if head is None:
        return None
    records = [op for _, operations in pages for op in operations]
    pairs = list(zip(records[::2], records[1::2], strict=True))
    if len({paper["entity_id"] for paper, _ in pairs}) != len(pairs):
        raise ListReviewRequired("Subsequent bibliography revisions need reconciliation")
    retired = {}
    versions = {}
    if directory.membership_changes:
        from paper_daily.drive_membership_history import membership_history

        changes = membership_history(directory, store, list_id, revision=revision)
        if changes.paper_head != head:
            from paper_daily.drive_paper_baseline import BibliographyAdvanced

            raise BibliographyAdvanced("Bibliography changed before receiving memberships")
        _, versions, retired = changes.versions(revision)
    # Compare a pre-existing bibliography against the entire first snapshot.
    # Fresh readers and previously enrolled readers can advance one immutable page at a time.
    batches = [(head, records)] if populated and not prior else pages
    for page, operations in batches:
        batch = list(zip(operations[::2], operations[1::2], strict=True))
        marker = encode(page.record())
        visible = _apply_page(store, list_id, revision, ticket, prior, marker, batch,
                              versions, retired)
        prior = (marker,)
        from paper_daily.drive_transfer_progress import bibliography_saved

        bibliography_saved(visible)
    return head


def _apply_page(store, list_id, revision, ticket, prior, marker, pairs, versions, retired):
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
            exact = {}
            if (
                not prior
                and not any(p["device_id"] == store.context for p, _ in pairs)
                and conn.execute(
                    "SELECT 1 FROM list_papers WHERE list_id=? LIMIT 1", (list_id,)
                ).fetchone()
            ):
                if retired or versions:
                    raise ListReviewRequired("Review existing bibliography membership changes")
                try:
                    exact = _exact_existing_members(conn, store, list_id, pairs, ticket)
                except ListReviewRequired:
                    # Not the same list paper for paper: join what matches below and
                    # leave the rest of the local list to be published as additions.
                    exact = {}
            first = conn.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM list_papers WHERE list_id=?", (list_id,)
            ).fetchone()[0]
            has_published = settings.execute(
                "SELECT 1 FROM sqlite_master WHERE name='published_paper_ids'"
            ).fetchone()
            from paper_daily.drive_membership_apply import _schema

            _schema(conn)
            originals = None
            received = {}
            merged = set()

            def taken(local):
                return has_published and settings.execute(
                    "SELECT 1 FROM published_paper_ids WHERE local_id=?", (local,)
                ).fetchone()

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
                if paper["entity_id"] in exact:
                    local, position = exact[paper["entity_id"]]
                    if published and published != (local,):
                        raise ListReviewRequired("Existing bibliography identity changed")
                    conn.execute("INSERT OR IGNORE INTO drive_library_papers VALUES(?,?,?)",
                                 (store.context, paper["entity_id"], local))
                    if _local_paper(conn, store, paper, published, received) != local:
                        raise ListReviewRequired("Existing bibliography identity changed")
                    conn.execute("INSERT INTO drive_membership_watches "
                                 "(context,list_id,member,creation,local_id,position) "
                                 "VALUES(?,?,?,?,?,?)",
                                 (store.context, list_id, member["entity_id"],
                                  member["operation_id"], local, position))
                    continue
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
                if versions:
                    member = versions[member["entity_id"]]
                local_id = _local_paper(conn, store, paper, published, received,
                                        taken=taken, merged=merged)
                held = conn.execute(
                    "SELECT position FROM list_papers WHERE list_id=? AND paper_id=?",
                    (list_id, local_id),
                ).fetchone()
                removal = retired.get(member["entity_id"])
                if held and local_id in merged and not removal:
                    # Already in this list on this device: one entry, dated as shared.
                    conn.execute(
                        "UPDATE list_papers SET added_at=? WHERE list_id=? AND paper_id=?",
                        (member["payload"]["added_at"], list_id, local_id),
                    )
                    conn.execute("INSERT INTO drive_membership_watches "
                                 "(context,list_id,member,creation,local_id,position) "
                                 "VALUES(?,?,?,?,?,?)",
                                 (store.context, list_id, member["entity_id"],
                                  member["operation_id"], local_id, held[0]))
                    continue
                if held:
                    raise ListReviewRequired("Existing membership changed; review before applying")
                if removal:
                    # This incoming membership never existed on this device. Preserve the
                    # paper binding and install the retirement with the bibliography receipt.
                    conn.execute("INSERT INTO drive_membership_watches VALUES(?,?,?,?,?,?,0,?)",
                                 (store.context, list_id, member["entity_id"],
                                  member["operation_id"], local_id, first, removal["operation_id"]))
                    continue
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
                # Observe the received lifetime even before the directory adopts removals.
                conn.execute("INSERT INTO drive_membership_watches "
                             "(context,list_id,member,creation,local_id,position) "
                             "VALUES(?,?,?,?,?,?)",
                             (store.context, list_id, member["entity_id"],
                              member["operation_id"], local_id, first))
                first += 1
            conn.execute(
                "INSERT INTO drive_library_bibliographies VALUES(?,?,?) "
                "ON CONFLICT(context,list_id) "
                "DO UPDATE SET head=excluded.head",
                (store.context, list_id, marker),
            )
            store._check(conn)
            visible, = conn.execute(
                "SELECT count(*) FROM list_papers WHERE list_id=?", (list_id,)
            ).fetchone()
            ticket.checkpoint(conn.commit)
    return visible


def exchange_bibliography(directory, store, list_id, revision, ticket):
    from paper_daily.drive_membership_intent import MembershipRemovalReview
    from paper_daily.drive_paper_baseline import BibliographyAdvanced, publish_initial

    def exchange():
        head = receive_initial(directory, store, list_id, revision, ticket)
        if head and directory.membership_changes:
            from paper_daily.drive_membership_apply import receive_membership_changes
            from paper_daily.drive_membership_history import membership_history

            history = membership_history(directory, store, list_id, revision=revision)
            receive_membership_changes(history, revision, ticket)
        def publish():
            return publish_initial(directory, store, list_id, revision, ticket,
                                   append_new=True, received_head=head)

        try:
            return publish()
        except MembershipRemovalReview as review:
            if not (head and directory.membership_changes
                    and review.missing == len(review.operations)):
                raise
            operations = review.operations
        current, _ = history.changes(None, revision=revision)
        for start in range(0, len(operations), history.max_operations):
            ticket.check()
            batch = operations[start:start + history.max_operations]
            current = history.append(current, batch, revision=revision)
        receive_membership_changes(history, revision, ticket)
        return publish()

    try:
        return exchange()
    except BibliographyAdvanced:
        # Retry once. Continued contention is handled by the background scheduler.
        ticket.check()
        return exchange()
