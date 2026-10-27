"""Private, bounded review drafts; restoring never recaptures a newer edit base."""

from __future__ import annotations

import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID, uuid4

from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import MAX_DETAIL, Preview, digest, encode

TABLE = "research_review_drafts"
COLUMNS = {
    "draft_id",
    "origin",
    "origin_id",
    "owner_json",
    "preview_json",
    "body",
    "request_id",
    "revision",
    "updated_at",
    "save_order",
    "fingerprint",
}
SNAPSHOT = {
    "origin",
    "id",
    "record_hash",
    "original",
    "current",
    "retained",
    "source_hash",
    "apply",
    "editable",
    "reason",
    "expected",
    "scope",
    "target",
    "requires_confirmation",
    "parent_token",
    "parent_row",
}
MAX_BODY = 200 * 1024
MAX_DRAFTS = 500
MAX_TOTAL = 64 * 1024 * 1024


class DraftConflict(ValueError):
    """Another window saved this draft; neither version may overwrite silently."""


def _hash(value, size=64, nullable=False):
    if nullable and value is None:
        return
    if (
        not isinstance(value, str)
        or len(value) != size
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("Invalid saved draft hash")


def _body(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_BODY:
        raise ValueError("Draft text exceeds its supported size")


def _fingerprint(row):
    return digest({key: value for key, value in row.items() if key != "fingerprint"})


def validate_record(row):
    """Closed backup validator. Paths are provenance, never restore destinations."""
    if not isinstance(row, dict) or set(row) != COLUMNS:
        raise ValueError("Invalid saved review draft")
    if not isinstance(row["draft_id"], str) or str(UUID(row["draft_id"])) != row["draft_id"]:
        raise ValueError("Invalid draft identity")
    for key in ("origin_id", "request_id"):
        maximum = 128 if key == "request_id" else 256
        if not isinstance(row[key], str) or not 1 <= len(row[key]) <= maximum:
            raise ValueError("Invalid draft request identity")
    if row["origin"] not in {"generation", "sidecar", "remote"}:
        raise ValueError("Unsupported saved draft origin")
    if type(row["revision"]) is not int or row["revision"] < 1:
        raise ValueError("Invalid draft revision")
    if type(row["save_order"]) is not int or row["save_order"] < 1:
        raise ValueError("Invalid saved draft order")
    stamp = datetime.fromisoformat(row["updated_at"])
    if stamp.tzinfo is None or len(row["updated_at"]) > 64:
        raise ValueError("Invalid draft timestamp")
    _body(row["body"])
    owner = json.loads(row["owner_json"])
    if not isinstance(owner, dict) or set(owner) != {"path", "identity", "binding"}:
        raise ValueError("Invalid saved draft owner")
    if not isinstance(owner["path"], str) or not (
        PurePosixPath(owner["path"]).is_absolute() or PureWindowsPath(owner["path"]).is_absolute()
    ):
        raise ValueError("Invalid saved draft owner path")
    if (
        not isinstance(owner["identity"], list)
        or len(owner["identity"]) != 2
        or any(type(n) is not int or n < 0 for n in owner["identity"])
    ):
        raise ValueError("Invalid saved draft database identity")
    binding = owner["binding"]
    if binding is not None and (
        not isinstance(binding, dict)
        or set(binding) != {"workspace_id", "device_id"}
        or any(not isinstance(n, str) or not 1 <= len(n) <= 128 for n in binding.values())
    ):
        raise ValueError("Invalid saved draft workspace binding")
    snapshot = json.loads(row["preview_json"])
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT:
        raise ValueError("Invalid saved draft preview")
    if (snapshot["origin"], snapshot["id"]) != (row["origin"], row["origin_id"]):
        raise ValueError("Saved draft differs from its retained origin")
    _hash(snapshot["record_hash"])
    _hash(snapshot["source_hash"], nullable=True)
    _hash(snapshot["parent_token"], 32, nullable=True)
    for key in ("apply", "editable", "requires_confirmation"):
        if type(snapshot[key]) is not bool:
            raise ValueError("Invalid saved draft capability")
    if not isinstance(snapshot["reason"], str) or len(snapshot["reason"]) > 1000:
        raise ValueError("Invalid saved draft reason")
    if row["origin"] in {"generation", "sidecar"}:
        expected = generation.GenerationContext(snapshot["expected"])
        data = expected.data
        if (
            data["db_path"] != owner["path"]
            or data["database_identity"] != owner["identity"]
            or data["binding"] != owner["binding"]
            or data["input_reader"] != "target"
            or snapshot["scope"] != {"table": data["table"], "owner_id": data["owner_id"]}
            or snapshot["current"] != data["target"]
        ):
            raise ValueError("Saved draft base differs from its owner or displayed target")
        generation.validate_request_record(
            {
                "request_id": data["request_id"],
                "context_json": snapshot["expected"],
                "row_json": encode(snapshot["retained"]),
                "status": "accepted",
                "candidate_id": None,
                "reason": "review draft validation",
            }
        )
        if snapshot["requires_confirmation"]:
            target = snapshot["target"]
            if (
                not isinstance(target, dict)
                or set(target) != {"id", "title"}
                or target["id"] != data["owner_id"]
                or not isinstance(target["title"], str)
            ):
                raise ValueError("Invalid explicitly selected draft target")
    else:
        from paper_daily.sync_client import validate_event
        from paper_daily.sync_journal import canonical_operation

        expected = snapshot["expected"]
        if (
            not isinstance(expected, dict)
            or set(expected) != {"event", "resolved_by", "head", "state", "parents", "outstanding"}
            or binding is None
        ):
            raise ValueError("Invalid saved conflict observation")
        validate_event(expected["event"], binding["workspace_id"])
        incoming = expected["event"]["operation"]
        if (
            incoming["entity_type"] not in {"note", "research_content"}
            or snapshot["retained"] != incoming["payload"]
            or str(expected["event"]["sequence"]) != row["origin_id"]
        ):
            raise ValueError("Invalid saved conflict target")
        if expected["head"] and expected["head"]["operation"]:
            canonical_operation(json.loads(expected["head"]["operation"]))
    _hash(row["fingerprint"])
    if not hmac.compare_digest(row["fingerprint"], _fingerprint(row)):
        raise ValueError("Saved draft integrity check failed")
    encode(row)
    return row


class DraftStore:
    """One pinned original database; retention may finish after review is cancelled."""

    def __init__(self, review):
        self.review = review
        self.owner = {
            "path": str(review.path),
            "identity": review.identity,
            "binding": review.binding,
        }

    def _connect(self):
        if generation._identity(self.review.path) != self.owner["identity"]:
            raise ValueError(
                "Draft database was replaced; keep this window open or export its text"
            )
        conn = sqlite3.connect(
            self.review.path.as_uri() + "?mode=rw",
            uri=True,
            factory=sync_capture.CaptureConnection,
            timeout=0.25,
        )
        try:
            self._check(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _check(self, conn):
        if (
            generation._identity(self.review.path) != self.owner["identity"]
            or generation._path(conn) != self.owner["path"]
            or generation._binding(conn) != self.owner["binding"]
        ):
            raise ValueError("Draft workspace changed; keep this window open or export its text")

    @staticmethod
    def _setup(conn):
        with sync_capture.suppress_capture(conn):
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {TABLE}(draft_id TEXT PRIMARY KEY,"
                "origin TEXT NOT NULL,"
                "origin_id TEXT NOT NULL,owner_json TEXT NOT NULL,preview_json TEXT NOT NULL,"
                "body TEXT NOT NULL,request_id TEXT NOT NULL,revision INTEGER NOT NULL,"
                "updated_at TEXT NOT NULL,save_order INTEGER NOT NULL,fingerprint TEXT NOT NULL)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS research_review_draft_origin "
                f"ON {TABLE}(origin,origin_id,save_order,draft_id)"
            )

    def save(self, preview, body, request_id, *, draft_id=None, revision=None):
        """CAS-save an edited draft. Failures never modify research or the outbox."""
        data = self.review._verify_preview(preview)
        _body(body)
        snapshot = {key: data[key] for key in SNAPSHOT}
        draft_id = draft_id or str(uuid4())
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("Invalid expected draft revision")
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA busy_timeout=250")
            conn.execute("BEGIN IMMEDIATE")
            self._setup(conn)
            existing = conn.execute(
                f"SELECT * FROM {TABLE} WHERE draft_id=?", (draft_id,)
            ).fetchone()
            old = dict(existing) if existing else None
            if old:
                validate_record(old)
                if (old["origin"], old["origin_id"], old["owner_json"]) != (
                    data["origin"],
                    data["id"],
                    encode(self.owner),
                ):
                    raise ValueError("Draft identity belongs to another target or owner")
                if (old["body"], old["preview_json"], old["request_id"]) == (
                    body,
                    encode(snapshot),
                    request_id,
                ):
                    return {"draft_id": draft_id, "revision": old["revision"]}
                if revision != old["revision"]:
                    raise DraftConflict(
                        "This draft changed in another window; your text is still here"
                    )
            elif revision is not None:
                raise DraftConflict("Saved draft disappeared; your text is still here")
            row = {
                "draft_id": draft_id,
                "origin": data["origin"],
                "origin_id": data["id"],
                "owner_json": encode(self.owner),
                "preview_json": encode(snapshot),
                "body": body,
                "request_id": request_id,
                "revision": (old["revision"] + 1) if old else 1,
                "updated_at": datetime.now(UTC).isoformat(),
                "save_order": conn.execute(
                    f"SELECT coalesce(max(save_order),0)+1 FROM {TABLE}"
                ).fetchone()[0],
                "fingerprint": "",
            }
            row["fingerprint"] = _fingerprint(row)
            validate_record(row)
            count, used = conn.execute(
                f"SELECT count(*),coalesce(sum(length(CAST(owner_json AS BLOB)) + "
                f"length(CAST(preview_json AS BLOB)) + length(CAST(body AS BLOB))),0) FROM {TABLE}"
            ).fetchone()

            def size(value):
                return sum(
                    len(value[key].encode("utf-8"))
                    for key in ("owner_json", "preview_json", "body")
                )

            if (
                count + (0 if old else 1) > MAX_DRAFTS
                or used - (size(old) if old else 0) + size(row) > MAX_TOTAL
            ):
                raise ValueError("Draft storage limit reached; export your text before closing")
            columns = list(row)
            with sync_capture.suppress_capture(conn):
                conn.execute(
                    f"INSERT INTO {TABLE}({','.join(columns)}) VALUES("
                    + ",".join("?" for _ in columns)
                    + ") ON CONFLICT(draft_id) DO UPDATE SET "
                    + ",".join(f"{key}=excluded.{key}" for key in columns if key != "draft_id"),
                    tuple(row.values()),
                )
            self._check(conn)
            conn.commit()
            return {"draft_id": draft_id, "revision": row["revision"]}

    def list(self, origin, identity, *, before=None, limit=20):
        """Bounded lightweight variant list; details are validated only when opened."""
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid draft page size")
        if before is not None and (type(before) is not int or before < 1):
            raise ValueError("Invalid draft page cursor")
        with closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
                return {"items": [], "next": None}
            rows = conn.execute(
                f"SELECT draft_id,revision,updated_at,save_order,substr(body,1,100) AS excerpt "
                f"FROM {TABLE} WHERE origin=? AND origin_id=? AND (? IS NULL OR save_order<?) "
                "ORDER BY save_order DESC,draft_id DESC LIMIT ?",
                (origin, identity, before, before, limit + 1),
            ).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            if not isinstance(item["excerpt"], str):
                item["excerpt"] = "Unreadable text; original record retained"
            items.append(item)
        return {"items": items, "next": items[-1]["save_order"] if len(rows) > limit else None}

    def latest(self, origin, identity, *, draft_id=None):
        """Return a recoverable body even if its metadata fails validation."""
        with closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
                return None
            condition = " AND draft_id=?" if draft_id is not None else ""
            arguments = (origin, identity, draft_id) if draft_id is not None else (origin, identity)
            found = conn.execute(
                f"SELECT draft_id,length(CAST(body AS BLOB)),"
                f"length(CAST(preview_json AS BLOB))+length(CAST(owner_json AS BLOB)) FROM {TABLE} "
                f"WHERE origin=? AND origin_id=?{condition} "
                "ORDER BY save_order DESC,draft_id DESC LIMIT 1",
                arguments,
            ).fetchone()
            if not found:
                return None
            if (
                type(found[1]) is not int
                or type(found[2]) is not int
                or found[1] > MAX_BODY
                or found[2] > MAX_DETAIL
            ):
                return {
                    "state": "corrupt",
                    "body": None,
                    "reason": "Saved draft exceeds limits; the original record remains intact",
                }
            row = dict(
                conn.execute(f"SELECT * FROM {TABLE} WHERE draft_id=?", (found[0],)).fetchone()
            )
            result = {
                "draft_id": row["draft_id"],
                "revision": row["revision"],
                "body": row["body"],
                "request_id": row["request_id"],
                "preview": None,
            }
            try:
                validate_record(row)
            except (ValueError, TypeError, KeyError):
                if not isinstance(result["body"], str):
                    result["body"] = None
                result.update(
                    state="corrupt",
                    reason="Saved draft metadata is damaged; export the retained text",
                )
                return result
            data = json.loads(row["preview_json"])
            state, reason = "ready", "Saved draft restored with its original displayed base"
            if json.loads(row["owner_json"]) != self.owner:
                state, reason = (
                    "foreign",
                    "Draft belongs to an earlier workspace; explicitly review its target",
                )
            else:
                try:
                    original = self.review._record(conn, origin, identity)
                    if digest(original) != data["record_hash"]:
                        raise ValueError("Retained record changed")
                    if origin in {"generation", "sidecar"}:
                        expected = generation.GenerationContext(data["expected"])
                        stale = generation._stale(conn, expected)
                        kind = generation.REGISTRY[expected.table][0]
                        root = "papers" if kind == "paper" else "lists"
                        parent = conn.execute(
                            f"SELECT * FROM {root} WHERE id=?", (expected.owner_id,)
                        ).fetchone()
                        if (
                            stale
                            or not parent
                            or dict(parent) != data["parent_row"]
                            or parent_lifecycle(conn, kind, expected.owner_id)
                            != data["parent_token"]
                        ):
                            raise ValueError(stale or "Selected parent changed")
                    elif (
                        conn._capture_client.conflict_observation_in(conn, int(identity))
                        != data["expected"]
                    ):
                        raise ValueError("Conflict changed")
                except (ValueError, KeyError, TypeError, sqlite3.DatabaseError, OSError):
                    state, reason = (
                        "stale",
                        "Research changed; review the latest version before applying this draft",
                    )
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "research_review_receipts" in tables:
                receipt = conn.execute(
                    "SELECT decision FROM research_review_receipts WHERE request_id=?",
                    (row["request_id"],),
                ).fetchone()
                if receipt and state != "foreign":
                    state, reason = (
                        "decided",
                        "This draft already has a saved decision; review again before new changes",
                    )
            data["session"] = self.review.session
            data["resume_state"] = state
            serialized = encode(data)
            seal = hmac.new(self.review._seal_key, serialized.encode(), "sha256").hexdigest()
            result.update(state=state, reason=reason, preview=Preview(serialized, seal))
            return result
