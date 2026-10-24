"""Bounded, offline research operations shared by desktop, CLI and MCP.

The process selects one workspace at startup. No operation accepts a filesystem
path, executes paper text, downloads a URL, or calls an AI provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from paper_daily import store

PREVIEW_TTL = 7 * 86400
MAX_BYTES = 2_000_000


class OperationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=200)
    year: int = Field(default=0, ge=0, le=2200)
    venue: str = Field(default="unknown", max_length=120)
    doi: str = Field(default="", max_length=512)
    arxiv_id: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=4096)
    pdf_url: str = Field(default="", max_length=4096)
    reason: str = Field(default="", max_length=4000)

    @field_validator("authors")
    @classmethod
    def authors_valid(cls, value):
        if any(not a.strip() or len(a) > 300 for a in value):
            raise ValueError("Authors must be nonempty names of at most 300 characters")
        return [a.strip() for a in value]

    @field_validator("doi")
    @classmethod
    def doi_valid(cls, value):
        value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
        if value and not re.fullmatch(r"10\.\d{4,9}/\S+", value):
            raise ValueError("Use a DOI such as 10.1234/example")
        return value.lower()

    @field_validator("arxiv_id")
    @classmethod
    def arxiv_valid(cls, value):
        value = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", value, flags=re.I)
        value = re.sub(r"(?:\.pdf)?$", "", value)
        value = re.sub(r"v\d+$", "", value)
        if value and not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", value):
            raise ValueError("Use an arXiv identifier or arxiv.org URL")
        return value

    @field_validator("url", "pdf_url")
    @classmethod
    def url_valid(cls, value):
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or any(c.isspace() for c in value)
            ):
                raise ValueError("Source URLs must be HTTP(S), without embedded credentials")
        return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise OperationError("invalid_input", f"{field}: use 1–128 letters, numbers, . _ : -")
    return value


def _page(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise OperationError("invalid_input", "limit must be 1–100; offset must be nonnegative")


def list_collections(limit=100, offset=0):
    _page(limit, offset)
    with store.connect(timeout=0.2) as conn:
        total = conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0]
        rows = conn.execute(
            "SELECT l.id,l.name,COUNT(lp.paper_id) AS count FROM lists l "
            "LEFT JOIN list_papers lp ON lp.list_id=l.id GROUP BY l.id "
            "ORDER BY l.created_at,l.id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return {
            "lists": [dict(r) for r in rows],
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        }


def read_collection(list_id, limit=100, offset=0):
    _id(list_id, "list_id")
    _page(limit, offset)
    with store.connect(timeout=0.2) as conn:
        listing = conn.execute("SELECT id,name FROM lists WHERE id=?", (list_id,)).fetchone()
        if not listing:
            raise OperationError("not_found", "List does not exist in this workspace")
        total = conn.execute(
            "SELECT COUNT(*) FROM list_papers WHERE list_id=?", (list_id,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT p.id,p.title,p.year,p.doi,p.arxiv_id,p.page_url,p.pdf_url,lp.position "
            "FROM list_papers lp JOIN papers p ON p.id=lp.paper_id WHERE lp.list_id=? "
            "ORDER BY lp.position,p.id LIMIT ? OFFSET ?",
            (list_id, limit, offset),
        )
        return {
            **dict(listing),
            "papers": [dict(r) for r in rows],
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        }


def _matches(conn, paper):
    exact = set()
    if paper["doi"]:
        exact.update(
            r[0]
            for r in conn.execute(
                "SELECT id FROM papers WHERE doi=? COLLATE NOCASE", (paper["doi"],)
            )
        )
    if paper["arxiv_id"]:
        # Stored IDs from older importers may still carry a version suffix.
        for row in conn.execute(
            "SELECT id,arxiv_id FROM papers WHERE arxiv_id=? OR arxiv_id LIKE ?",
            (paper["arxiv_id"], paper["arxiv_id"] + "v%"),
        ):
            if re.sub(r"v\d+$", "", row["arxiv_id"]) == paper["arxiv_id"]:
                exact.add(row["id"])
    similar = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM papers WHERE title_key=? ORDER BY id LIMIT 20",
            (store.title_key(paper["title"]),),
        )
    ]
    return sorted(exact), similar


def propose(name: str, papers: list[dict], target_list_id: str | None = None) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise OperationError("invalid_input", "name must contain 1–200 characters")
    if not isinstance(papers, list) or not 1 <= len(papers) <= 500:
        raise OperationError("invalid_input", "Provide between 1 and 500 papers")
    if len(_json(papers).encode("utf-8")) > MAX_BYTES:
        raise OperationError("invalid_input", "Paper input exceeds 2 MB")
    try:
        normalized = [PaperInput.model_validate(p).model_dump() for p in papers]
    except ValidationError as exc:
        # Do not echo an arbitrary submitted document into logs or errors.
        issue = exc.errors(include_input=False)[0]
        raise OperationError("invalid_input", f"{issue['loc']}: {issue['msg']}") from None
    if target_list_id is not None:
        _id(target_list_id, "target_list_id")
    preview = {
        "preview_id": uuid.uuid4().hex,
        "name": name.strip(),
        "target_list_id": target_list_id,
        "expires_at": int(time.time()) + PREVIEW_TTL,
        "papers": normalized,
    }
    items = []
    with store.connect(timeout=0.2) as conn:
        if (
            target_list_id
            and not conn.execute("SELECT 1 FROM lists WHERE id=?", (target_list_id,)).fetchone()
        ):
            raise OperationError("not_found", "Target list does not exist")
        for i, paper in enumerate(normalized):
            exact, similar = _matches(conn, paper)
            items.append(
                {
                    "candidate_id": str(i),
                    "title": paper["title"],
                    "identity_matches": exact,
                    "title_matches": similar,
                    "warning": (
                        "Conflicting identities: resolve before saving"
                        if len(exact) > 1
                        else "Title match requires explicit reuse"
                        if similar and not exact
                        else "No identifiers; title is not proof of identity"
                        if not paper["doi"] and not paper["arxiv_id"]
                        else ""
                    ),
                }
            )
        conn.execute("DELETE FROM integration_previews WHERE expires_at < ?", (int(time.time()),))
        conn.execute(
            "INSERT INTO integration_previews VALUES(?,?,?)",
            (preview["preview_id"], _json(preview), preview["expires_at"]),
        )
    return {k: v for k, v in preview.items() if k != "papers"} | {"items": items}


def discard(preview_id: str) -> dict:
    _id(preview_id, "preview_id")
    with store.connect(timeout=0.2) as conn:
        conn.execute("DELETE FROM integration_previews WHERE id=?", (preview_id,))
    return {"discarded": True}


def inspect_operation(operation_id: str) -> dict:
    _id(operation_id, "operation_id")
    with store.connect(timeout=0.2) as conn:
        row = conn.execute(
            "SELECT result FROM integration_operations WHERE id=?", (operation_id,)
        ).fetchone()
        if not row:
            return {"operation_id": operation_id, "state": "not_committed"}
        return {"operation_id": operation_id, "state": "committed", "result": json.loads(row[0])}


def commit(
    preview_id: str, operation_id: str, selected: list[str], reuse: dict[str, str] | None = None
) -> dict:
    _id(preview_id, "preview_id")
    _id(operation_id, "operation_id")
    if (
        not isinstance(selected, list)
        or not 1 <= len(selected) <= 500
        or any(not isinstance(i, str) or not re.fullmatch(r"0|[1-9]\d{0,2}", i) for i in selected)
        or len(set(selected)) != len(selected)
    ):
        raise OperationError(
            "invalid_input", "Select 1–500 distinct candidate IDs in reading order"
        )
    reuse = {} if reuse is None else reuse
    if (
        not isinstance(reuse, dict)
        or any(k not in selected for k in reuse)
        or any(not isinstance(v, str) for v in reuse.values())
    ):
        raise OperationError(
            "invalid_input", "reuse maps selected candidate IDs to existing paper IDs"
        )
    digest = hashlib.sha256(_json([preview_id, selected, reuse]).encode()).hexdigest()
    with store.connect(timeout=0.2) as conn:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT fingerprint,result FROM integration_operations WHERE id=?", (operation_id,)
        ).fetchone()
        if prior:
            if prior["fingerprint"] != digest:
                raise OperationError(
                    "conflict", "operation_id already used for a different request"
                )
            return json.loads(prior["result"])
        row = conn.execute(
            "SELECT payload,expires_at FROM integration_previews WHERE id=?", (preview_id,)
        ).fetchone()
        if not row or row["expires_at"] < time.time():
            raise OperationError(
                "expired_preview", "Preview was discarded or expired; propose again"
            )
        preview = json.loads(row["payload"])
        if any(int(i) >= len(preview["papers"]) for i in selected):
            raise OperationError("invalid_input", "Selection contains an unknown candidate ID")
        list_id = preview["target_list_id"] or "list-" + uuid.uuid4().hex
        if preview["target_list_id"]:
            if not conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
                raise OperationError("not_found", "Target list was deleted; propose again")
        else:
            conn.execute(
                "INSERT INTO lists(id,name,created_at) VALUES(?,?,?)",
                (list_id, preview["name"], store.now()),
            )
        position = conn.execute(
            "SELECT COALESCE(MAX(position),0) FROM list_papers WHERE list_id=?", (list_id,)
        ).fetchone()[0]
        added, paper_ids, warnings = 0, [], []
        for candidate in selected:
            paper = preview["papers"][int(candidate)]
            exact, similar = _matches(conn, paper)
            if len(exact) > 1:
                raise OperationError(
                    "identity_conflict", f"Candidate {candidate} has conflicting IDs"
                )
            chosen = reuse.get(candidate)
            if chosen and (chosen not in (exact or similar)):
                raise OperationError(
                    "identity_conflict", f"Candidate {candidate}: invalid reuse match"
                )
            existing = chosen or (exact[0] if exact else None)
            if existing:
                saved = conn.execute(
                    "SELECT doi,arxiv_id FROM papers WHERE id=?", (existing,)
                ).fetchone()
                for field in ("doi", "arxiv_id"):
                    old = saved[field] or ""
                    old = old.lower() if field == "doi" else re.sub(r"v\d+$", "", old)
                    if old and paper[field] and old != paper[field]:
                        raise OperationError(
                            "identity_conflict", f"Candidate {candidate}: conflicting {field}"
                        )
                paper_id = existing
                # Curated metadata is not overwritten. Fill only missing identifiers/URLs.
                conn.execute(
                    "UPDATE papers SET doi=COALESCE(NULLIF(doi,''),?), "
                    "arxiv_id=COALESCE(NULLIF(arxiv_id,''),?), "
                    "page_url=COALESCE(NULLIF(page_url,''),?), "
                    "pdf_url=COALESCE(NULLIF(pdf_url,''),?) WHERE id=?",
                    (
                        paper["doi"] or None,
                        paper["arxiv_id"] or None,
                        paper["url"] or None,
                        paper["pdf_url"] or None,
                        paper_id,
                    ),
                )
            else:
                if similar:
                    warnings.append(f"Candidate {candidate}: similar title kept separate")
                paper_id = "ref:" + uuid.uuid4().hex
                store.upsert_papers(
                    conn,
                    [
                        dict(
                            id=paper_id,
                            title=paper["title"],
                            venue=paper["venue"] or "unknown",
                            year=paper["year"],
                            authors_json=_json(paper["authors"]),
                            doi=paper["doi"] or None,
                            arxiv_id=paper["arxiv_id"] or None,
                            page_url=paper["url"] or None,
                            pdf_url=paper["pdf_url"] or None,
                            source="local-integration",
                        )
                    ],
                )
            if not conn.execute(
                "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?", (list_id, paper_id)
            ).fetchone():
                position += 1
                conn.execute(
                    "INSERT INTO list_papers(list_id,paper_id,position,citation,added_at) "
                    "VALUES(?,?,?,?,?)",
                    (list_id, paper_id, position, paper["reason"] or paper["title"], store.now()),
                )
                added += 1
            paper_ids.append(paper_id)
        result = {
            "operation_id": operation_id,
            "list_id": list_id,
            "added": added,
            "selected": len(selected),
            "paper_ids": paper_ids,
            "warnings": warnings,
        }
        conn.execute(
            "INSERT INTO integration_operations VALUES(?,?,?,?)",
            (operation_id, digest, _json(result), store.now()),
        )
        conn.execute("INSERT INTO integration_changes(list_id) VALUES(?)", (list_id,))
        return result


OPERATIONS = {
    "lists.list": list_collections,
    "lists.read": read_collection,
    "imports.propose": propose,
    "imports.commit": commit,
    "imports.discard": discard,
    "operations.inspect": inspect_operation,
}


def dispatch(operation: str, arguments: dict) -> dict:
    """The same JSON envelope and error codes on all transports."""
    import inspect
    import sqlite3

    try:
        if operation not in OPERATIONS:
            raise OperationError("unknown_operation", "Unknown operation")
        fn = OPERATIONS[operation]
        if not isinstance(arguments, dict):
            raise OperationError("invalid_input", "Arguments must be a JSON object")
        try:
            inspect.signature(fn).bind(**arguments)
        except TypeError:
            raise OperationError("invalid_input", "Missing or unexpected arguments") from None
        return {"ok": True, "result": fn(**arguments)}
    except OperationError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except sqlite3.OperationalError:
        return {
            "ok": False,
            "error": {
                "code": "storage_unavailable",
                "message": "Workspace unavailable or busy; retry using the same operation_id",
            },
        }
