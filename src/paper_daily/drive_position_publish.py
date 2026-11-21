"""Publish current, locally recorded reader positions through an enrolled list."""

import hashlib
import json
import sqlite3
from contextlib import closing

from paper_daily import (
    local_source_owners,
    reading_positions,
    research_generation,
    source_snapshots,
)
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_paper_baseline import published_bindings
from paper_daily.reading_position_ops import validate_receipt
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_files import canonical_json
from paper_daily.workspace_service import _read, _tables


def publish_recorded(history, tips, revision, ticket):
    store = history.store
    database = store.workspace.path
    own = {(op["payload"]["scope"]["id"], op["payload"]["key"]): op
           for op in tips if op["device_id"] == store.context}
    active = {record[0] for member, record in history.memberships.items()
              if member not in history.retired and member not in history.restored}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if not {reading_positions.RECEIPTS, reading_positions.TABLE} <= _tables(conn):
            return False
        generation = conn.execute("PRAGMA data_version").fetchone()

        def check():
            ticket.check()
            if conn.execute("PRAGMA data_version").fetchone() != generation:
                raise ListReviewRequired("Research changed during PDF page sync; sync again")

        with _read(store.path) as settings:
            bindings = {local: remote for remote, local in
                        published_bindings(settings, active).items()}
        rows = conn.execute(
            "SELECT p.paper_id,p.document_hash,p.page,p.recorded_at,p.method "
            "FROM list_papers m JOIN reading_positions p ON m.paper_id=p.paper_id "
            "WHERE m.list_id=?", (history.list_id,)
        ).fetchall()
        pending = {}
        for local, digest, page, stamp, method in rows:
            paper = bindings.get(local)
            data = dict(page=page, recorded_at=stamp, method=method)
            previous = own.get((paper, digest))
            if paper and (not previous or previous["payload"]["data"] != data):
                pending[local, digest] = paper, data, previous
        if not pending:
            return False
        history.check_source = check
        wrote = False
        try:
            # Imported rows have no matching save from this database and paper lifetime.
            for record in _receipts(database):
                check()
                result = json.loads(record[2])
                row = result["position"]
                key = row["paper_id"], row["document_hash"]
                if key not in pending or result["status"] != "saved":
                    continue
                paper, data, previous = pending[key]
                if any(row[name] != value for name, value in data.items()):
                    continue
                fields = reading_positions.RECEIPT_FIELDS.split()
                validate_receipt(dict(zip(fields, record, strict=True)))
                owner = json.loads(record[1])["owner"]
                local, digest = key
                if (owner["database_identity"] != research_generation._identity(database)
                        or owner["binding"] is not None or owner["parent_lifecycle"] !=
                        parent_lifecycle(conn, "paper", local)):
                    continue
                metadata = dict(owner, format="paperfact.position-source-owner.v2",
                                position_key=digest)
                source_id = "position:" + hashlib.sha256(canonical_json(metadata)).hexdigest()
                source = conn.execute("SELECT * FROM research_local_source_owners "
                                      "WHERE request_id=?", (source_id,)).fetchone()
                if source is None:
                    continue
                receipt = dict(zip(local_source_owners.COLUMNS.split(), source, strict=True))
                if receipt["sha256"] != digest or json.loads(receipt["owner_json"]) != metadata:
                    raise ListReviewRequired("Review the saved PDF page's original")
                path = source_snapshots.source_path(database, receipt)
                verified = local_source_owners._read_pdf(path, digest, receipt["size"],
                                                         lambda: ticket.cancelled)
                check()
                history.publish_page(paper, digest, data, verified[0], revision=revision,
                                     predecessor=previous["operation_id"] if previous else None)
                wrote = True
                del pending[key]
                if not pending:
                    break
        finally:
            history.check_source = ticket.check
        return wrote


def _receipts(database):
    # Keep the history cursor off the connection monitoring concurrent reader edits.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        yield from conn.execute("SELECT request_id,request_json,result_json "
                                "FROM research_reading_position_receipts ORDER BY rowid DESC")
