"""Closed saved-Lineage read projection; metadata never activates source bytes."""

from paper_daily import lineage_sets, lineage_wire


def present(conn):
    schema = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,)
    ).fetchone()
    if schema is None:
        return False
    if schema[0] != "table":
        raise ValueError("Lineage read projection requires its stored research table")
    return conn.execute("SELECT 1 FROM paper_lineage_sets LIMIT 1").fetchone() is not None


def attach(conn, result):
    """Attach exact portable reports to existing papers; never mint an identity."""
    if not present(conn):
        return
    if result["schema_version"] != 2:
        raise ValueError("Lineage read projection requires portable schema version 2")
    papers = {row["id"]: row for row in result["papers"]}
    for raw in conn.execute(
        "SELECT paper_id,corpus_key,CASE WHEN length(CAST(body_json AS BLOB))<=? "
        "THEN body_json END,source_hash,document_hash,written_at FROM paper_lineage_sets "
        "ORDER BY paper_id,corpus_key",
        (lineage_sets.MAX_BYTES,),
    ):
        row = dict(zip(lineage_sets.COLUMNS.split(), raw, strict=True))
        payload = lineage_wire.encode_row(conn, row)
        body = payload["data"]["body_json"]
        if any(binding["paper_id"] not in papers for binding in body["bindings"]):
            raise ValueError("Lineage projection lacks its actual selected paper")
        target = papers[payload["scope"]["id"]].setdefault("lineage", [])
        if len(target) >= lineage_sets.MAX_SETS:
            raise ValueError("Lineage projection exceeds its corpus budget")
        target.append(
            dict(
                body=body,
                **{key: row[key] for key in ("source_hash", "document_hash", "written_at")},
            )
        )
    result["required_capabilities"] = sorted({*result.get("required_capabilities", []), "lineage"})
