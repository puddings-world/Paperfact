"Allowlisted read-only Inbox supplement; never a graph/bootstrap authority."

from paper_daily import inbox_content as content


def attach(conn, result, *, max_records):
    from paper_daily.research_inbox import _preflight, retained_count, root_status

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if content.ITEMS not in tables:
        return
    _preflight(conn, tables)
    count = conn.execute(f"SELECT count(*) FROM {content.ITEMS}").fetchone()[0]
    retained = retained_count(conn, tables)
    if not count and not retained:
        if (
            content.HISTORY in tables
            and conn.execute(f"SELECT 1 FROM {content.HISTORY} LIMIT 1").fetchone()
        ):
            raise ValueError("Inbox history has no workspace-owned capture roots")
        return
    total = count + sum(
        len(result[key]) for key in ("lists", "papers", "notes", "highlights", "decks", "assets")
    )
    if total > max_records:
        raise ValueError("Inbox read projection exceeds the record limit")
    items = []
    for raw in conn.execute(f"SELECT * FROM {content.ITEMS} ORDER BY id"):
        row = dict(zip(content.COLUMNS[content.ITEMS].split(), raw, strict=True))
        content.validate_row(content.ITEMS, row)
        previous = conn.execute(
            f"SELECT item_id,body_json,incarnation,active FROM {content.HISTORY} WHERE version=?",
            (row["version"],),
        ).fetchone()
        if previous is None or tuple(previous) != (
            row["id"],
            row["body_json"],
            row["incarnation"],
            row["active"],
        ):
            raise ValueError("Inbox projection differs from its owned saved version")
        status = root_status(conn, tables, row["id"], result["cursor"])
        items.append(
            dict(
                id=row["id"],
                payload=content.decode(row["body_json"]) if row["body_json"] else None,
                active=bool(row["active"]),
                version=row["version"],
                incarnation=row["incarnation"],
                sync_state=status,
            )
        )
    result["inbox"] = dict(items=items, retained=retained)
    result["required_capabilities"] = sorted(
        set(result.get("required_capabilities", [])) | {"inbox"}
    )
