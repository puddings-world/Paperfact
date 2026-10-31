"""Read-only source inventory for exact applied positions received from a peer."""

from paper_daily import file_change, local_source_owners, reading_positions, sync_content
from paper_daily.enrollment_history import _value
from paper_daily.sync_artifacts import desired_file, paper_current
from paper_daily.sync_files import canonical_json, file_id
from paper_daily.sync_journal import MAX_BYTES, canonical_operation
from paper_daily.sync_source_files import inspectable


def current_source(conn, row, *, ticket):
    """Verify existing graph/file authority; create no receipt, binding or file."""
    required = {
        "paperfact_sync_graph_projection",
        "research_file_desired",
        "research_paper_identity",
    }
    tables = {raw[0] for raw in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= tables:
        raise ValueError("Reading position requires its exact source ownership receipt")
    expected = sync_content.content_payload(conn, reading_positions.TABLE, row)
    identity = sync_content.content_id(expected["scope"], "reading_position", row["document_hash"])
    projected = conn.execute(
        "SELECT operation,active FROM paperfact_sync_graph_projection "
        "WHERE entity_type='research_content' AND entity_id=?",
        (identity,),
    ).fetchone()
    if (
        not projected
        or projected[1] != 1
        or not isinstance(projected[0], str)
        or len(projected[0].encode()) > MAX_BYTES
    ):
        raise ValueError("Reading position has no exact active applied owner")
    operation = _value(projected[0])
    canonical_operation(operation)
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if (
        operation["entity_type"] != "research_content"
        or operation["entity_id"] != identity
        or operation["action"] != "put"
        or not binding
        or operation["workspace_id"] != binding[0]
        or canonical_json(operation["payload"]) != canonical_json(expected)
    ):
        raise ValueError("Reading position differs from its active applied owner")
    paper = expected["scope"]["id"]
    source = desired_file(conn, file_id(paper, "original_source", row["document_hash"]))
    if (
        source is None
        or not paper_current(conn, source)
        or canonical_json(source["parents"]) != canonical_json(operation["parents"])
    ):
        raise ValueError("Reading position original belongs to a different paper lifetime")
    path = inspectable(conn, paper, row["document_hash"])
    if path is None:
        raise ValueError("Reading position original is unavailable")
    size = source["payload"]["assets"][0]["size"]
    verified = local_source_owners._read_pdf(
        path, row["document_hash"], size, lambda: ticket.cancelled
    )
    ticket.check()
    if verified is None:
        raise ValueError("Reading position source verification was cancelled")
    data, version = verified
    reading_positions.verify_page(row, data)
    ticket.check()
    if file_change.version(path) != version:
        raise ValueError("Reading position original changed during verification")
    return dict(path=str(path), sha256=row["document_hash"], size=size)
