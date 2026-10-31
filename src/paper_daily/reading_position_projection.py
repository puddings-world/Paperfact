"""Read-only position/source declarations, never document or graph authority."""

from paper_daily import reading_positions

MAX_POSITIONS = 500
UNSUPPORTED = "Source-bound reading positions are not supported without exact source closure"


def declarations(conn):
    """Read a bounded current declaration without opening files or repairing SQL."""
    from paper_daily.sync_artifacts import desired_file, paper_current
    from paper_daily.sync_files import file_id

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if (
        reading_positions.TABLE not in tables
        or not conn.execute("SELECT 1 FROM reading_positions LIMIT 1").fetchone()
    ):
        return []
    if (
        not reading_positions.ready(conn)
        or not {"research_paper_identity", "research_paper_projection", "research_file_desired"}
        <= tables
    ):
        raise ValueError(UNSUPPORTED)
    count = conn.execute("SELECT count(*) FROM reading_positions").fetchone()[0]
    if count > MAX_POSITIONS:
        raise ValueError(UNSUPPORTED)
    rows = []
    try:
        for raw in conn.execute(
            "SELECT paper_id,document_hash,page,recorded_at,method FROM reading_positions "
            "ORDER BY paper_id,document_hash"
        ):
            row = dict(zip(reading_positions.FIELDS.split(), raw, strict=True))
            reading_positions.validate_row(row)
            mapping = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (row["paper_id"],)
            ).fetchone()
            if mapping is None:
                raise ValueError(UNSUPPORTED)
            paper = mapping[0]
            identity = file_id(paper, "original_source", row["document_hash"])
            source = desired_file(conn, identity)
            if source is None or not paper_current(conn, source):
                raise ValueError(UNSUPPORTED)
            payload = source["payload"]
            if (payload["feature"], payload["paper_id"], payload["slot"]) != (
                "original_source",
                paper,
                row["document_hash"],
            ):
                raise ValueError(UNSUPPORTED)
            rows.append(
                dict(
                    row,
                    paper_id=paper,
                    source=dict(
                        id=identity,
                        parents=source["parents"],
                        manifest=payload,
                    ),
                )
            )
    except (ValueError, TypeError, KeyError):
        raise ValueError(UNSUPPORTED) from None
    return sorted(rows, key=lambda row: (row["paper_id"], row["document_hash"]))


def attach(result, rows):
    if not rows:
        return
    known = {paper["id"] for paper in result["papers"]}
    if any(row["paper_id"] not in known for row in rows):
        raise ValueError(UNSUPPORTED)
    assets = {asset["id"]: asset for asset in result["assets"]}
    for row in rows:
        declared = row["source"]["manifest"]["assets"][0]
        identity = "sha256:" + declared["sha256"]
        asset = dict(
            id=identity,
            **{key: declared[key] for key in ("sha256", "size", "media_type")},
            availability="unchecked",
        )
        prior = assets.get(identity)
        if prior and any(prior[key] != asset[key] for key in ("sha256", "size", "media_type")):
            raise ValueError("Conflicting position source descriptor")
        assets.setdefault(identity, asset)
    result["assets"] = [assets[key] for key in sorted(assets)]
    result["reading_positions"] = rows
    result["required_capabilities"] = sorted(
        set(result.get("required_capabilities", [])) | {"reading_position"}
    )
