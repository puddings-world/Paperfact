"""Bound active Lineage corpora without blocking canonical receive progress."""

from paper_daily import lineage_sets


def local_room_in(conn, paper_id, corpus_key):
    """Updates of existing corpora need no additional visible slot."""
    storage = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,),
    ).fetchone()
    if storage is None:
        return True
    if storage[0] != "table":
        raise ValueError("Lineage capacity requires its actual report table")
    if conn.execute(
        "SELECT 1 FROM paper_lineage_sets WHERE paper_id=? AND corpus_key=?",
        (paper_id, corpus_key),
    ).fetchone():
        return True
    return (
        conn.execute(
            "SELECT count(*) FROM paper_lineage_sets WHERE paper_id=?", (paper_id,)
        ).fetchone()[0]
        < lineage_sets.MAX_SETS
    )


def authority_room_in(conn, operation):
    """Count accepted active typed corpora in this workspace/focal paper only.

    Retired source lifetimes retain their scientific slot until explicit corpus
    retirement. A same-entity update or retirement never consumes another slot.
    The sync authority owns the serialized acceptance transaction.
    """
    if operation["action"] == "delete":
        return True
    return (
        conn.execute(
            "SELECT count(*) FROM sync_graph WHERE workspace=? AND entity_type='research_content' "
            "AND entity_id<>? AND json_extract(metadata,'$.active')=1 "
            "AND json_extract(metadata,'$.content_address.feature')='lineage' "
            "AND json_extract(metadata,'$.parents[0].id')=?",
            (operation["workspace_id"], operation["entity_id"], operation["parents"][0]["id"]),
        ).fetchone()[0]
        < lineage_sets.MAX_SETS
    )
