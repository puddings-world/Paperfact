"""Exact-content adoption from an independently verified original-complete package.

This is not generic overwrite, native marker repair, or restoration authority.
PackageImporter owns the sealed decision and the transaction containing sources,
this observed-row transition, typed publication and the retry receipt.
"""

from paper_daily import lineage_package_native, lineage_projection, lineage_wire, sync_capture


def parents_in(conn, client, payload):
    graph = client._optimistic_graph(conn)[0]
    parents = []
    for kind, identity in lineage_wire.parent_identities(payload):
        parent = graph.get((kind, identity))
        projected = conn.execute(
            "SELECT incarnation FROM research_paper_projection WHERE sync_id=?", (identity,)
        ).fetchone()
        if (
            parent is None
            or not parent["active"]
            or projected is None
            or projected[0] != parent["incarnation"]
        ):
            return None
        parents.append(dict(kind=kind, id=identity, incarnation=parent["incarnation"]))
    return parents


def eligible_in(conn, client, identity, payload, current):
    if current is None:
        return False
    if sync_capture._current(conn, client, "research_content", identity) is not None:
        return False
    if ("research_content", identity) in client._optimistic_graph(conn)[0]:
        return False
    if conn.execute(
        "SELECT 1 FROM paperfact_sync_operations "
        "WHERE entity_type='research_content' AND entity_id=? LIMIT 1",
        (identity,),
    ).fetchone():
        return False
    for table, column in (
        (lineage_projection.TABLE, "entity_id"),
        (lineage_projection.HISTORY, "entity_id"),
    ):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() and (
            conn.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (identity,)).fetchone()
        ):
            return False
    if parents_in(conn, client, payload) is None:
        return False
    try:
        return current == lineage_wire.decode_row(conn, payload)
    except ValueError:
        # New/differently mapped source owners cannot adopt this private report.
        # The surrounding comparison may still offer Keep current.
        return False


def consume_in(conn, client, operation, expected):
    """Remove only the unchanged matching private row before typed publication.

    This helper owns no commit/savepoint and grants no publication by itself.
    Trusted package/direct-selection actions call it; a later exception
    must roll back the entire compound action, including this temporary removal.
    """
    if not conn.in_transaction:
        raise ValueError("Matching adoption requires its caller transaction")
    payload = operation["payload"]
    current = lineage_package_native.saved_in(conn, expected["paper_id"], expected["corpus_key"])
    if current != expected or not eligible_in(
        conn, client, operation["entity_id"], payload, current
    ):
        raise ValueError("Matching private Lineage changed; review its adoption again")
    with sync_capture.suppress_capture(conn):
        result = conn.execute(
            "DELETE FROM paper_lineage_sets WHERE paper_id=? AND corpus_key=?",
            (expected["paper_id"], expected["corpus_key"]),
        )
    if result.rowcount != 1:
        raise ValueError("Matching private Lineage row is no longer available")
