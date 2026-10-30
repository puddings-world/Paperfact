"""Read canonical questions or explicitly unverified legacy suggestions.

Reading never adopts a cache, runs AI, enrolls sync, or creates a database.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from paper_daily import annotation_content as annotations


def saved(database, paper_id, feature):
    """Read owned canonical content; None means no canonical authority exists yet.

    An empty known result means deletion or a missing parent. Neither case grants
    permission to revive a cache or run AI. Sources are returned without opening
    the PDF, so saved research stays readable while source bytes are offline.
    """
    if feature not in annotations.FEATURES:
        raise ValueError("Unsupported reading annotation feature")
    table = annotations.FEATURES[feature]
    key = "claims" if feature == "claims" else "links" if feature == "reading_links" else "items"
    empty = {key: [], "known": True}
    database = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.25)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone():
            return empty
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if table in tables:
            size = conn.execute(
                f"SELECT length(CAST(body_json AS BLOB)) FROM {table} WHERE paper_id=?",
                (paper_id,),
            ).fetchone()
            if size is not None and (size[0] is None or size[0] > annotations.MAX_BYTES):
                raise ValueError("Saved reading annotation exceeds its supported budget")
            row = conn.execute(f"SELECT * FROM {table} WHERE paper_id=?", (paper_id,)).fetchone()
            if row:
                annotations.validate_row(feature, dict(row))
                result = {
                    **annotations.decode(feature, row["body_json"]),
                    "paper_id": paper_id,
                    "source_hash": row["source_hash"],
                    "document_hash": row["document_hash"],
                    "known": True,
                }
                if feature == "reading_links":
                    result["key"] = row["source_hash"]
                return result
        if (
            "paper_annotation_known" in tables
            and conn.execute(
                "SELECT 1 FROM paper_annotation_known WHERE feature=? AND paper_id=?",
                (feature, paper_id),
            ).fetchone()
        ):
            return empty
    return None


def questions(database, paper_id, *, cache_root):
    current = saved(database, paper_id, "research_questions")
    return current if current is not None else legacy_questions(cache_root, paper_id)


def legacy_questions(cache_root, paper_id):
    """Unknown historical ownership stays visible as an unverified preview only."""
    path = Path(cache_root) / (hashlib.sha256(paper_id.encode()).hexdigest() + ".json")
    try:
        from paper_daily.research_generation import _is_link

        if any(_is_link(entry) for entry in (path, *path.parents)):
            raise ValueError("Legacy question cache cannot traverse links")
        if not path.is_file() or path.stat().st_size > annotations.MAX_BYTES:
            return {"items": [], "known": False}
        with path.open("rb") as stream:
            encoded = stream.read(annotations.MAX_BYTES + 1)
        if len(encoded) > annotations.MAX_BYTES:
            raise ValueError("Legacy question cache exceeds its limit")
        data = json.loads(encoded)
        if not isinstance(data, dict) or data.get("paper_id") != paper_id:
            raise ValueError("Legacy question cache belongs to another paper")
        if not data.get("items"):
            return {"items": [], "known": False}
        body = annotations.validate("research_questions", {"items": data["items"]})
        source = data.get("source_hash")
        if not isinstance(source, str) or not annotations.HASH.fullmatch(source):
            raise ValueError("Legacy questions have no valid input digest")
        return {
            **body,
            "paper_id": paper_id,
            "source_hash": source,
            "document_hash": None,
            "legacy_unverified": True,
            "known": False,
        }
    except (OSError, ValueError, TypeError, RecursionError):
        return {"items": [], "known": False}
