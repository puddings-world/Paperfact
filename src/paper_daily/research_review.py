"""Bounded retained-work review over existing records, with displayed-base writes.

Explicit database paths only. Viewing, deciding and exporting never run an agent.
The source records are immutable; receipts describe local review decisions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle

MAX_DETAIL = 8 * 1024 * 1024
MAX_EXPORT = 2 * 1024 * 1024
COMPOUND_ORIGINS = {"compound", "compound_sidecar", "compound_recovery"}
FILE_ORIGINS = {"file", "file_draft", "local_deck", "enrolled_deck"}
RECEIPT_FIELDS = {
    "request_id",
    "fingerprint",
    "origin",
    "origin_id",
    "decision",
    "result",
    "provenance",
}
TABLES = {
    "generation": ("research_generation_requests", "request_id"),
    "capture": ("research_capture_candidates", "id"),
    "compound": ("research_compound_requests", "request_id"),
    "compound_recovery": ("recovery_records", "rowid"),
    "file": ("research_file_candidates", "candidate_id"),
    "file_draft": ("research_file_drafts", "candidate_id"),
    "local_deck": ("research_local_deck_proposals", "proposal_id"),
    "enrolled_deck": ("research_enrolled_deck_proposals", "proposal_id"),
    "remote": ("paperfact_sync_conflicts", "sequence"),
    "recovery": ("recovery_records", "rowid"),
}


def encode(value):
    result = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if len(result.encode("utf-8")) > MAX_DETAIL:
        raise ValueError("Review detail exceeds the supported size")
    return result


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


SOURCE_AWARE_REASON = "Claim sets require source-aware review"


def _source_aware_required(view):
    scope = view.get("scope") or {}
    retained = view.get("retained")
    return scope.get("table") == "paper_claim_sets" or (
        view.get("origin") == "remote"
        and isinstance(retained, dict)
        and retained.get("feature") == "claims"
    )


def _source_aware_block(view):
    view.update(apply=False, editable=False, reason=SOURCE_AWARE_REASON)
    return view


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _setup(conn):
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_review_receipts("
            "request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,origin TEXT NOT NULL,"
            "origin_id TEXT NOT NULL,decision TEXT NOT NULL,result TEXT NOT NULL,"
            "provenance TEXT NOT NULL)"
        )


def validate_receipt(row):
    if not isinstance(row, dict) or set(row) != RECEIPT_FIELDS:
        raise ValueError("Invalid review receipt")
    for key in ("request_id", "origin_id"):
        if not isinstance(row[key], str) or not 1 <= len(row[key]) <= 256:
            raise ValueError("Invalid review receipt identity")
    if row["origin"] not in {
        *TABLES,
        "sidecar",
        "compound_sidecar",
        "archived_resume",
        "archived_note_resume",
        "claim_resume",
        "highlight_resume",
    } or row["decision"] not in {"applied", "kept"}:
        raise ValueError("Invalid review receipt decision")
    if not isinstance(row["fingerprint"], str) or len(row["fingerprint"]) != 64:
        raise ValueError("Invalid review fingerprint")
    if any(c not in "0123456789abcdef" for c in row["fingerprint"]):
        raise ValueError("Invalid review fingerprint")
    result = json.loads(row["result"])
    if not isinstance(result, dict) or set(result) != {"decision", "operation_id"}:
        raise ValueError("Invalid review result")
    if result["decision"] != row["decision"] or (
        result["operation_id"] is not None
        and (not isinstance(result["operation_id"], str) or len(result["operation_id"]) > 128)
    ):
        raise ValueError("Invalid review result")
    provenance = json.loads(row["provenance"])
    if not isinstance(provenance, dict) or set(provenance) != {
        "source_document_hash",
        "target_kind",
        "target_id",
        "parent_token",
    }:
        raise ValueError("Invalid review provenance")
    for key, size in (("source_document_hash", 64), ("parent_token", 32)):
        value = provenance[key]
        if value is not None and (
            not isinstance(value, str)
            or len(value) != size
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("Invalid review provenance hash")
    if provenance["target_kind"] not in {None, "paper", "list", "note", "research_content"}:
        raise ValueError("Invalid review provenance target")
    if provenance["target_id"] is not None and (
        not isinstance(provenance["target_id"], str) or len(provenance["target_id"]) > 4096
    ):
        raise ValueError("Invalid review provenance identity")
    encode(row)
    return row


@dataclass(frozen=True)
class Preview:
    """Immutable displayed snapshot. Never rebuild this token on Save."""

    serialized: str
    seal: str = ""

    @property
    def data(self):
        return json.loads(self.serialized)


class ResearchReview:
    def __init__(self, database, *, presentation_root=None):
        self.path = Path(database).resolve(strict=True)
        if presentation_root is None:
            from paper_daily import presentations, store

            if Path(store.DB_PATH).resolve() == self.path:
                presentation_root = presentations.DECK_DIR
            else:
                presentation_root = self.path.parent / "presentations"
        self.presentation_root = Path(presentation_root).absolute()
        self.identity = generation._identity(self.path)
        with closing(generation._connect(self.path)) as conn:
            self.binding = generation._binding(conn)
            self.recovery = "recovery_identity" in _tables(conn)
        self.session = str(uuid4())
        self._seal_key = secrets.token_bytes(32)
        self.closed = False
        self._file_apply_lock = threading.RLock()
        self._claim_revisions = {}
        self._highlight_verifications = {}
        self._resume_sources = {}
        self._resume_documents = {}
        self._resume_cache_owners = {}

    def close(self):
        self.closed = True

    def _check(self, conn):
        if self.closed or generation._identity(self.path) != self.identity:
            raise ValueError("Original review workspace is closed or was replaced")
        if generation._path(conn) != str(self.path) or generation._binding(conn) != self.binding:
            raise ValueError("Original workspace binding changed")

    def _connect(self):
        if self.closed or generation._identity(self.path) != self.identity:
            raise ValueError("Original review workspace is closed or was replaced")
        conn = generation._connect(self.path)
        try:
            self._check(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _sidecars(self, kind="generation"):
        """Index filenames, not multi-megabyte contents, with a hard scan bound."""
        root = self.path.parent / (".paperfact-" + kind)
        if not root.exists():
            return {}
        if any(generation._is_link(p) for p in (root, *root.parents)):
            raise ValueError("Recovery index cannot traverse links")
        result = {}
        scanned = 0
        for namespace in root.iterdir():
            scanned += 1
            if scanned > 10000:
                raise ValueError("Recovery index exceeds the supported size")
            if generation._is_link(namespace) or not namespace.is_dir():
                raise ValueError("Invalid recovery namespace")
            for path in namespace.iterdir():
                scanned += 1
                if scanned > 10000:
                    raise ValueError("Recovery index exceeds the supported size")
                if generation._is_link(path) or not path.is_file() or path.suffix != ".json":
                    raise ValueError("Invalid recovery record")
                if len(result) >= 10000:
                    raise ValueError("Recovery index exceeds the supported size")
                result[namespace.name + "/" + path.name] = path
        return result

    def page(self, *, after=None, limit=30):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Review page size must be between 1 and 100")
        if after is not None and (
            not isinstance(after, (list, tuple))
            or len(after) != 2
            or not all(isinstance(x, str) for x in after)
        ):
            raise ValueError("Invalid review cursor")
        after = tuple(after or ("", ""))
        items = []
        with closing(self._connect()) as conn:
            tables = _tables(conn)
            for origin, (table, column) in TABLES.items():
                if table not in tables or origin < after[0]:
                    continue
                lower = after[1] if origin == after[0] else ""
                condition = (
                    " AND status='candidate'" if origin in {"generation", "compound"} else ""
                )
                if origin in {"recovery", "compound_recovery"}:
                    comparison = "IN" if origin == "compound_recovery" else "NOT IN"
                    condition = (
                        f" AND table_name {comparison} "
                        "('research_compound_requests','research_compound_recovery')"
                    )
                    if origin == "recovery":
                        from paper_daily.archived_review_drafts import RECOVERY_FILTER

                        condition += RECOVERY_FILTER
                summary = "NULL"
                if origin in {"generation", "compound"}:
                    field = "phase" if origin == "compound" else "table"
                    summary = (
                        "CASE WHEN json_valid(context_json) THEN "
                        f"substr(json_extract(context_json,'$.{field}'),1,40)||' · '||"
                        "coalesce((SELECT substr(title,1,100) FROM papers WHERE id="
                        "json_extract(context_json,'$.owner_id')),(SELECT substr(name,1,100) "
                        "FROM lists WHERE id=json_extract(context_json,'$.owner_id')),"
                        "substr(json_extract(context_json,'$.owner_id'),1,100)) ELSE NULL END"
                    )
                if origin in {"local_deck", "enrolled_deck"} and "papers" in tables:
                    owner = "paper_id" if origin == "local_deck" else "local_id"
                    summary = (
                        "coalesce((SELECT substr(title,1,100) FROM papers WHERE "
                        f"papers.id={table}.{owner}),substr({owner},1,100))"
                    )
                rows = conn.execute(
                    f'SELECT CAST("{column}" AS TEXT) AS identity,{summary} AS summary '
                    f'FROM "{table}" '
                    f'WHERE CAST("{column}" AS TEXT)>?{condition} ORDER BY identity LIMIT ?',
                    (lower, limit + 1),
                )
                for row in rows:
                    items.append(
                        {"origin": origin, "id": row[0], "decision": None, "summary": row[1]}
                    )
            from paper_daily.proposal_recovery_review import entries as recovered_proposals

            items.extend(
                row for row in recovered_proposals(self, conn) if (row["origin"], row["id"]) > after
            )
            from paper_daily.archived_review_drafts import entries as archived_drafts

            items.extend(archived_drafts(conn, after, limit))
            for sidecar, kind in (("sidecar", "generation"), ("compound_sidecar", "compound")):
                if after[0] > sidecar:
                    continue
                items.extend(
                    {"origin": sidecar, "id": identity, "decision": None}
                    for identity in self._sidecars(kind)
                    if (sidecar, identity) > after
                )
            items.sort(key=lambda item: (item["origin"], item["id"]))
            result = items[:limit]
            cursor = [result[-1]["origin"], result[-1]["id"]] if len(items) > limit else None
            from paper_daily.review_decisions import latest_in

            for row in result:
                row["decision"] = latest_in(conn, row["origin"], row["id"])
            self._check(conn)
        return {"items": result, "next": cursor}

    def _record(self, conn, origin, identity):
        if origin == "highlight_resume":
            from paper_daily.highlight_draft_resume import record

            return record(self, conn, identity)
        if origin == "claim_resume":
            from paper_daily.claim_draft_resume import record

            return record(self, conn, identity)
        from paper_daily import proposal_recovery_review

        if origin == "enrolled_deck" and proposal_recovery_review.virtual(identity):
            return proposal_recovery_review.record(conn, identity)
        if origin in {"sidecar", "compound_sidecar"}:
            adapter = generation
            if origin == "compound_sidecar":
                from paper_daily import research_compound as adapter
            path = self._sidecars("compound" if origin == "compound_sidecar" else "generation").get(
                identity
            )
            if path is None or path.stat().st_size > MAX_DETAIL:
                raise ValueError("Recovery record is missing or too large")
            record = adapter.validate_request_record(json.loads(path.read_text("utf-8")))
            context = (adapter.GenerationContext if origin == "sidecar" else adapter.Context)(
                record["context_json"]
            )
            if adapter._recovery_path(context) != path:
                raise ValueError("Recovery record path differs from its provenance")
            if context.data["db_path"] != str(self.path):
                raise ValueError("Recovery record belongs to another research database")
            return record
        if origin in {"archived_draft", "archived_resume", "archived_note_resume"}:
            from paper_daily.archived_review_drafts import record

            return record(conn, identity)
        if origin not in TABLES:
            raise ValueError("Unknown retained origin")
        table, column = TABLES[origin]
        # SQLite length does not allocate the value into Python. Bound before SELECT *.
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        size = "+".join(f'coalesce(length(CAST("{c}" AS BLOB)),0)' for c in columns)
        row = conn.execute(
            f'SELECT {size} FROM "{table}" WHERE "{column}"=?', (identity,)
        ).fetchone()
        if row is None or (row[0] or 0) > MAX_DETAIL:
            raise ValueError("Retained record is missing or exceeds the supported size")
        record = dict(
            conn.execute(f'SELECT * FROM "{table}" WHERE "{column}"=?', (identity,)).fetchone()
        )
        if origin == "compound_recovery":
            if record["table_name"] not in {
                "research_compound_requests",
                "research_compound_recovery",
            }:
                raise ValueError("Not a typed compound recovery record")
            from paper_daily.research_compound import validate_request_record

            return validate_request_record(json.loads(record["data"]))
        return record

    def preview(self, origin, identity):
        if origin == "highlight_resume":
            raise ValueError("Load the saved structured highlight draft with its displayed base")
        if origin == "claim_resume":
            raise ValueError("Load the saved structured claim draft with its displayed base")
        with closing(self._connect()) as conn:
            if not self.recovery:
                conn.execute("BEGIN IMMEDIATE")
                ensure_lifecycle(conn)
                conn.commit()
            conn.execute("BEGIN")
            record = self._record(conn, origin, str(identity))
            view = {
                "origin": origin,
                "id": str(identity),
                "session": self.session,
                "record_hash": digest(record),
                "original": None,
                "current": None,
                "retained": None,
                "source_hash": None,
                "apply": False,
                "editable": False,
                "reason": "Typed application is not available for this origin",
                "expected": None,
                "scope": None,
                "target": None,
                "requires_confirmation": False,
                "parent_token": None,
                "parent_row": None,
                "resume_state": "ready",
            }
            if origin == "archived_draft":
                from paper_daily.archived_review_drafts import preview

                view.update(preview(record))
            elif origin in {"generation", "sidecar"}:
                generation.validate_request_record(record)
                context = generation.GenerationContext(record["context_json"])
                original = context.data
                retained = json.loads(record["row_json"])
                view.update(
                    original=context.target,
                    retained=retained,
                    source_hash=(original["document"] or {}).get("sha256"),
                    scope={"table": context.table, "owner_id": context.owner_id},
                )
                if _source_aware_required(view):
                    _source_aware_block(view)
                    self._check(conn)
                    serialized = encode(view)
                    return Preview(
                        serialized,
                        hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest(),
                    )
                from paper_daily import research_annotation_review

                if research_annotation_review.handles(record):
                    view.update(research_annotation_review.preview(conn, record))
                    self._check(conn)
                    serialized = encode(view)
                    return Preview(
                        serialized,
                        hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest(),
                    )
                try:
                    displayed = generation.begin_generation(
                        conn, table=context.table, owner_id=context.owner_id, input_reader="target"
                    )
                    view.update(current=displayed.target, expected=displayed._json)
                    view["parent_token"] = parent_lifecycle(
                        conn, generation.REGISTRY[context.table][0], context.owner_id
                    )
                    root = "papers" if generation.REGISTRY[context.table][0] == "paper" else "lists"
                    view["parent_row"] = dict(
                        conn.execute(
                            f"SELECT * FROM {root} WHERE id=?", (context.owner_id,)
                        ).fetchone()
                    )
                    old_parents = (original["observation"] or {}).get("parents")
                    new_parents = (displayed.data["observation"] or {}).get("parents")
                    same_parent = old_parents == new_parents and all(
                        ref["active"] for ref in (new_parents or [])
                    )
                    same_database = (
                        original["db_path"] == str(self.path)
                        and original["database_identity"] == self.identity
                        and original["binding"] == self.binding
                    )
                    # Unknown legacy lifecycle requires explicit target selection.
                    capable = (
                        origin == "generation"
                        and record["status"] == "candidate"
                        and self.binding is not None
                        and same_database
                        and same_parent
                        and bool(new_parents)
                        and not self.recovery
                    )
                    view.update(
                        apply=capable,
                        editable=capable,
                        reason=""
                        if capable
                        else "Original parent lifecycle or binding cannot be reused safely",
                    )
                except (ValueError, sqlite3.DatabaseError):
                    view["reason"] = (
                        "Original target is unavailable; copy or export the retained result"
                    )
            elif origin in COMPOUND_ORIGINS:
                from paper_daily import research_compound_review

                view.update(
                    research_compound_review.preview(
                        conn, record, archived=origin == "compound_recovery"
                    )
                )
            elif origin == "remote":
                client = getattr(conn, "_capture_client", None)
                if client is None:
                    raise ValueError("Remote conflict requires its original enrolled workspace")
                state = client.conflict_observation_in(conn, int(identity))
                incoming = state["event"]["operation"]
                current = (
                    json.loads(state["head"]["operation"])
                    if state["head"] and state["head"]["operation"]
                    else None
                )
                base = conn.execute(
                    "SELECT event FROM paperfact_sync_inbox WHERE sequence=?",
                    (incoming["base_revision"],),
                ).fetchone()
                old = json.loads(base[0])["operation"] if base else None
                if old and (old["entity_type"], old["entity_id"]) != (
                    incoming["entity_type"],
                    incoming["entity_id"],
                ):
                    old = None
                view.update(
                    original=old["payload"] if old else None,
                    current=current["payload"] if current else None,
                    retained=incoming["payload"],
                    expected=state,
                    source_hash=incoming["payload"].get("source_document_hash"),
                    scope={"kind": incoming["entity_type"], "id": incoming["entity_id"]},
                )
                parents_current = all(
                    p["current"]
                    and p["current"]["active"]
                    and p["ref"]["incarnation"] == p["current"]["incarnation"]
                    for p in state["parents"]
                )
                parents_same = incoming.get("parents", []) == (state["state"] or incoming).get(
                    "parents", []
                )
                capable = (
                    incoming["entity_type"] in {"note", "research_content"}
                    and incoming["action"] == "put"
                    and not state["outstanding"]
                    and state["resolved_by"] is None
                    and parents_current
                    and parents_same
                    and (state["state"] or {}).get("active", True)
                    and not (
                        incoming["entity_type"] == "research_content"
                        and incoming["payload"].get("feature")
                        in {"highlight_analysis", "ai_highlight"}
                    )
                )
                view.update(
                    apply=capable,
                    editable=capable,
                    reason=""
                    if capable
                    else "Highlight conflicts require complete grouped source review"
                    if incoming["entity_type"] == "research_content"
                    and incoming["payload"].get("feature") in {"highlight_analysis", "ai_highlight"}
                    else "Conflict needs synchronization or an explicit supported target choice",
                )
                if _source_aware_required(view):
                    _source_aware_block(view)
                if (
                    incoming["entity_type"] == "research_content"
                    and incoming["payload"].get("feature") == "highlight_analysis"
                ):
                    from paper_daily import research_annotation_review

                    view.update(research_annotation_review.remote_preview(conn, state))
            elif origin == "capture":
                value = json.loads(record["content"])
                original, current, retained = _capture_preview(conn, value)
                view.update(original=original, current=current, retained=retained)
                view["reason"] = (
                    "Compound candidate stays grouped; typed application is not available"
                )
            elif origin == "file":
                from paper_daily.sync_files import validate_payload

                value = json.loads(record["payload"])
                validate_payload(value, entity_id=record["entity_id"])
                view["retained"] = value
                observation = json.loads(record["observation"])
                if not isinstance(observation, dict):
                    raise ValueError("Invalid artifact observation")
                old = observation.get("artifact")
                if old:
                    from paper_daily.sync_journal import canonical_operation

                    old = json.loads(canonical_operation(old))
                    if (
                        old["entity_type"] != "research_file"
                        or old["entity_id"] != record["entity_id"]
                    ):
                        raise ValueError("Artifact observation belongs to another target")
                    view["original"] = old["payload"]
                current = conn.execute(
                    "SELECT operation FROM research_file_desired WHERE entity_id=?",
                    (record["entity_id"],),
                ).fetchone()
                if current:
                    from paper_daily.sync_journal import canonical_operation

                    view["current"] = json.loads(canonical_operation(json.loads(current[0])))[
                        "payload"
                    ]
                view["reason"] = (
                    "Artifact application requires verified assets and explicit revision review"
                )
            elif origin == "enrolled_deck" and str(identity).startswith("recovered-deck:"):
                from paper_daily import proposal_recovery_review

                view.update(proposal_recovery_review.preview(self, conn, record))
            elif origin == "enrolled_deck":
                from paper_daily import enrolled_deck_proposals as catalog
                from paper_daily.research_file_review import _storage
                from paper_daily.sync_deck_publication import runtime

                client, storage = runtime(database=self.path), _storage(conn)
                if client is None or storage is None:
                    raise ValueError("Original enrolled proposal binding or storage is unavailable")
                retained = catalog.read(
                    client,
                    storage[0],
                    identity,
                    expected_native=self.identity,
                    current=lambda: not self.closed,
                )
                if retained.record != record:
                    raise ValueError("Retained enrolled proposal changed during preview")
                science = retained.content
                manifest = json.loads(record["manifest_json"])
                view.update(
                    retained=science["deck"],
                    source_hash=science["source_document_hash"],
                    scope={"kind": "paper", "id": record["local_id"]},
                    retained_evidence=science["evidence"],
                    image_manifest=manifest["images"],
                    original_manifest=manifest["originals"],
                    reason="Retained full presentation; verify before explicit Apply",
                )
            elif origin == "local_deck":
                from paper_daily import local_deck_proposals

                retained = local_deck_proposals.read(
                    self.path,
                    identity,
                    expected_native=self.identity,
                    current=lambda: not self.closed,
                )
                if retained.record != record:
                    raise ValueError("Retained local proposal changed during preview")
                science = retained.content
                view.update(
                    retained=science["deck"],
                    source_hash=science["source_document_hash"],
                    scope={"kind": "paper", "id": record["paper_id"]},
                    retained_evidence=science["evidence"],
                    image_manifest=json.loads(record["manifest_json"])["images"],
                    original_manifest=json.loads(record["manifest_json"])["originals"],
                    reason="Local retained presentation; verify it before explicit Apply",
                )
            elif origin == "file_draft":
                from paper_daily.presentations import deck_from_dict

                value = json.loads(record["deck"])
                deck_from_dict(value)
                view["retained"] = value
            else:
                # Detached records are provenance, never runnable old-device operations.
                value = json.loads(record["data"])
                view["retained"] = _safe_recovery(record["table_name"], value)
                if record["table_name"] == "research_review_drafts":
                    view["source_hash"] = json.loads(value["preview_json"])["source_hash"]
                view["reason"] = (
                    "Detached recovery provenance cannot be replayed as live operations"
                )
            self._check(conn)
            serialized = encode(view)
            seal = hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
            return Preview(serialized, seal)

    def _resume_adapter(self, preview):
        from paper_daily import review_draft_resumption as resumption

        data = self._verify_preview(preview)
        if data["origin"] == "archived_draft":
            with closing(self._connect()) as conn:
                return resumption.archived(self._record(conn, data["origin"], data["id"]))
        return resumption.adapter(data["origin"])

    def resume_targets(self, preview, *, after="", limit=30):
        return self._resume_adapter(preview).targets(self, preview, after=after, limit=limit)

    def resume_draft(self, preview, target_id):
        return self._resume_adapter(preview).select(self, preview, target_id)

    def verify_resumed_draft(self, preview):
        return self._resume_adapter(preview).verify(self, preview)

    def verify_highlight_draft(self, preview, body, *, cancelled=lambda: False):
        from paper_daily.highlight_draft_verification import verify

        return verify(self, preview, body, cancelled=cancelled)

    def apply_highlight_draft(self, preview, body, **options):
        from paper_daily.highlight_draft_apply import apply

        return apply(self, preview, body, **options)

    def highlight_draft_report(self, preview):
        from paper_daily.highlight_draft_verification import report

        return report(self, preview)

    def prepare_verified_highlight_original(self, preview, *, cancelled=lambda: False):
        from paper_daily.highlight_draft_verification import original

        return original(self, preview, cancelled=cancelled)

    def prepare_highlight_original(self, preview, *, reference=None, cancelled=lambda: False):
        from paper_daily import highlight_draft_originals

        data = self._verify_preview(preview)
        return highlight_draft_originals.prepare(
            self, preview, data["source_hash"], reference=reference, cancelled=cancelled
        )

    def highlight_draft_targets(self, preview, *, after="", limit=30):
        from paper_daily.highlight_draft_resume import targets

        return targets(self, preview, after=after, limit=limit)

    def select_highlight_draft(self, preview, target_id, *, body=None):
        from paper_daily.highlight_draft_resume import select

        return select(self, preview, target_id, body=body)

    def save_highlight_draft(self, preview, body, request_id, *, draft_id, revision=None):
        from paper_daily.highlight_draft_resume import save

        return save(self, preview, body, request_id, draft_id=draft_id, revision=revision)

    def load_highlight_draft(self, identity, **options):
        return self.load_draft("highlight_resume", identity, **options)

    def claim_draft_targets(self, preview, *, after="", limit=30):
        from paper_daily.claim_draft_resume import targets

        return targets(self, preview, after=after, limit=limit)

    def select_claim_draft(self, preview, target_id, *, body=None):
        from paper_daily.claim_draft_resume import select

        return select(self, preview, target_id, body=body)

    def save_claim_draft(self, preview, body, request_id, *, draft_id, revision=None):
        from paper_daily.claim_draft_resume import save

        return save(self, preview, body, request_id, draft_id=draft_id, revision=revision)

    def verify_claim_draft(self, preview, body, *, restore_deleted=False, cancelled=lambda: False):
        from paper_daily.claim_draft_apply import verify

        return verify(self, preview, body, restore_deleted=restore_deleted, cancelled=cancelled)

    def claim_draft_report(self, preview):
        from paper_daily.claim_draft_apply import report

        return report(self, preview)

    def apply_claim_draft(
        self, preview, body, *, request_id, confirm_target=False, _operation_receipt=None
    ):
        from paper_daily.claim_draft_apply import apply

        return apply(
            self,
            preview,
            body,
            request_id=request_id,
            confirm_target=confirm_target,
            _operation_receipt=_operation_receipt,
        )

    def load_claim_draft(self, identity, **options):
        return self.load_draft("claim_resume", identity, **options)

    def note_source_references(self, preview):
        from paper_daily.note_source_refs import intents

        if self.closed:
            raise ValueError("Review workspace is closed")
        return intents(self._verify_preview(preview))

    def inspect_note_source_reference(self, preview, reference, *, cancelled=lambda: False):
        from paper_daily.note_source_refs import inspect

        return inspect(self, preview, reference, cancelled=cancelled)

    def inspect_note_source(self, preview, selected, *, cancelled=lambda: False):
        from paper_daily.note_source_mapping import inspect

        return inspect(self, preview, selected, cancelled=cancelled)

    def note_source_page(self, preview, inspected, page_index, *, cancelled=lambda: False):
        from paper_daily.note_source_mapping import page

        return page(self, preview, inspected, page_index, cancelled=cancelled)

    def choose_note_source(self, preview, inspected, anchor, *, cancelled=lambda: False):
        from paper_daily.note_source_mapping import choose

        return choose(self, preview, inspected, anchor, cancelled=cancelled)

    def clear_note_position(self, preview):
        from paper_daily.note_source_mapping import clear

        return clear(self, preview)

    def require_draft_verification(self, preview):
        from paper_daily.review_draft_sources import require_verification

        return require_verification(self, preview)

    def targets(self, preview, *, after="", limit=30):
        data = self._verify_preview(preview)
        if data["origin"] in {"archived_draft", "archived_resume", "archived_note_resume"}:
            return self.resume_targets(preview, after=after, limit=limit)
        from paper_daily.research_annotation_review import remote_group

        if data["origin"] not in {"generation", "sidecar", *COMPOUND_ORIGINS} and not remote_group(
            data
        ):
            raise ValueError("Explicit target selection is not available for this origin")
        if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(after, str):
            raise ValueError("Invalid target page")
        kind = (
            "paper"
            if data["origin"] in COMPOUND_ORIGINS
            else generation.REGISTRY[data["scope"]["table"]][0]
        )
        root, title = ("papers", "title") if kind == "paper" else ("lists", "name")
        with closing(self._connect()) as conn:
            if remote_group(data):
                rows = conn.execute(
                    "SELECT id,substr(title,1,200) AS title FROM papers WHERE id=? AND id>?",
                    (data["scope"]["owner_id"], after),
                ).fetchall()
            else:
                rows = conn.execute(
                    f'SELECT id,substr("{title}",1,200) AS title FROM "{root}" '
                    "WHERE id>? ORDER BY id LIMIT ?",
                    (after, limit + 1),
                ).fetchall()
        items = [dict(row) for row in rows[:limit]]
        return {"items": items, "next": items[-1]["id"] if len(rows) > limit else None}

    def target_preview(self, preview, target_id):
        """Prepare an explicitly chosen target; applying requires separate confirmation.

        This does not infer that old and new parents share a lifecycle. Both the
        displayed target row and its new local epoch are rechecked on application.
        """
        data = self._verify_preview(preview)
        if data["origin"] in {"archived_resume", "archived_note_resume"}:
            return self.resume_draft(preview, target_id)
        if _source_aware_required(data):
            _source_aware_block(data)
            serialized = encode(data)
            return Preview(
                serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
            )
        from paper_daily.research_annotation_review import remote_group

        if data["origin"] not in {"generation", "sidecar", *COMPOUND_ORIGINS} and not remote_group(
            data
        ):
            raise ValueError("Explicit target selection is not available for this origin")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("Select a research target")
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            record = self._record(conn, data["origin"], data["id"])
            if digest(record) != data["record_hash"]:
                raise ValueError("Retained result changed; reload it first")
            if remote_group(data):
                from paper_daily import research_annotation_review

                state = conn._capture_client.conflict_observation_in(conn, int(data["id"]))
                data.update(
                    research_annotation_review.remote_preview(
                        conn, state, owner=target_id, confirmed=True
                    )
                )
                data["resume_state"] = "ready"
                self._check(conn)
                serialized = encode(data)
                return Preview(
                    serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
                )
            if data["origin"] in COMPOUND_ORIGINS:
                from paper_daily import research_compound_review

                data.update(
                    research_compound_review.preview(
                        conn,
                        record,
                        owner=target_id,
                        confirmed=True,
                        archived=data["origin"] == "compound_recovery",
                    )
                )
                data["resume_state"] = "ready"
                self._check(conn)
                serialized = encode(data)
                return Preview(
                    serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
                )
            from paper_daily import research_annotation_review

            if research_annotation_review.handles(record):
                data.update(
                    research_annotation_review.preview(
                        conn, record, owner=target_id, confirmed=True
                    )
                )
                data["resume_state"] = "ready"
                self._check(conn)
                serialized = encode(data)
                return Preview(
                    serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
                )
            original = generation.GenerationContext(record["context_json"])
            table = original.table
            kind, column, _feature, _reader = generation.REGISTRY[table]
            root, title = ("papers", "title") if kind == "paper" else ("lists", "name")
            target = conn.execute(
                f'SELECT id,"{title}" AS title FROM "{root}" WHERE id=?', (target_id,)
            ).fetchone()
            if target is None:
                raise ValueError("Selected target no longer exists")
            expected = generation.begin_generation(
                conn, table=table, owner_id=target_id, input_reader="target"
            )
            token = parent_lifecycle(conn, kind, target_id)
            if token is None:
                raise ValueError("Selected target has no durable local lifecycle")
            parent_row = dict(
                conn.execute(f"SELECT * FROM {root} WHERE id=?", (target_id,)).fetchone()
            )
            retained = dict(data["retained"])
            retained[column] = target_id
            data.update(
                retained=retained,
                current=expected.target,
                expected=expected._json,
                parent_token=token,
                parent_row=parent_row,
                scope={"table": table, "owner_id": target_id},
                target=dict(target),
                apply=True,
                editable=True,
                requires_confirmation=True,
                resume_state="ready",
                reason="Explicit target selected; confirmation is required",
            )
            self._check(conn)
            serialized = encode(data)
            return Preview(
                serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
            )

    def _verify_preview(self, preview):
        if not isinstance(preview, Preview):
            raise ValueError("A displayed preview is required")
        expected = hmac.new(self._seal_key, preview.serialized.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(preview.seal, expected):
            raise ValueError("Preview belongs to another review session or was modified")
        data = preview.data
        if data["session"] != self.session:
            raise ValueError("Preview belongs to another review session")
        return data

    def prepare_file(self, preview):
        """Explicitly verify a retained deck and display its current application base."""
        from paper_daily import research_file_review

        data = self._verify_preview(preview)
        if (
            data["origin"] == "enrolled_deck"
            and str(data["id"]).startswith("recovered-deck:")
            and not self.recovery
        ):
            from paper_daily.proposal_recovery_review import verify

            with self._file_apply_lock:
                data = verify(self, data)
            serialized = encode(data)
            return Preview(
                serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
            )
        if data["origin"] in {"local_deck", "enrolled_deck"} and not self.recovery:
            if data["origin"] == "local_deck":
                from paper_daily import local_deck_review as proposal_review
            else:
                from paper_daily import enrolled_deck_review as proposal_review

            with closing(self._connect()) as conn:
                record = self._record(conn, data["origin"], data["id"])
                if digest(record) != data["record_hash"]:
                    raise ValueError("Retained slides changed; reload the preview")
            data.update(proposal_review.prepare(self, record))
            serialized = encode(data)
            return Preview(
                serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
            )
        if data["origin"] not in {"file", "file_draft"} or self.recovery:
            raise ValueError("Select retained slides in their original workspace")
        with closing(self._connect()) as conn:
            record = self._record(conn, data["origin"], data["id"])
            if digest(record) != data["record_hash"]:
                raise ValueError("Retained slides changed; reload the preview")
            if data["origin"] == "file_draft":
                from paper_daily import raw_deck_closure, raw_deck_receipts

                # No schema/staging on catalog or read. This explicit action may
                # repair only an actually owned, verified receipt before review.
                if raw_deck_receipts.read_owned(conn, record, missing_ok=True) is not None:
                    raw_deck_closure.repair(
                        self.path,
                        record,
                        current=lambda: (
                            not self.closed and generation._identity(self.path) == self.identity
                        ),
                    )
            conn.execute("BEGIN")
            self._check(conn)
            record = self._record(conn, data["origin"], data["id"])
            if digest(record) != data["record_hash"]:
                raise ValueError("Retained slides changed during explicit preparation")
            files = {}
            if data["origin"] == "file_draft":
                from paper_daily.raw_deck_closure import verify_in

                record, files = verify_in(conn, record)
            data.update(research_file_review.prepare_in(conn, record))
            for path, identity in files.items():
                if (
                    path in data["expected"]["files"]
                    and data["expected"]["files"][path] != identity
                ):
                    raise ValueError("Raw draft files changed during preparation")
                data["expected"]["files"][path] = identity
            self._check(conn)
            serialized = encode(data)
            return Preview(
                serialized, hmac.new(self._seal_key, serialized.encode(), "sha256").hexdigest()
            )

    def _decide_file(self, data, fingerprint, request_id, body, confirm_target):
        from paper_daily import research_file_review
        from paper_daily.sync_artifacts import activate, materialize
        from paper_daily.sync_journal import canonical_operation

        if data.get("resume_state", "ready") != "ready":
            raise ValueError("Saved draft needs refreshed review before application")
        if not data["apply"]:
            raise ValueError(data["reason"])
        if body is not None:
            raise ValueError("Retained slides are applied as a typed deck, not edited JSON")
        if confirm_target is not True:
            raise ValueError("Confirm the reviewed slide target before applying")

        def previous(conn):
            if "research_review_receipts" not in _tables(conn):
                return None
            row = conn.execute(
                "SELECT fingerprint,result FROM research_review_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            if row["fingerprint"] != fingerprint:
                raise ValueError("Review retry changed its decision or draft")
            return json.loads(row["result"])

        def record_in(conn):
            record = self._record(conn, data["origin"], data["id"])
            if digest(record) != data["record_hash"]:
                raise ValueError("Retained record changed; reload the preview")
            if data["origin"] == "file_draft":
                from paper_daily.raw_deck_closure import candidate_in

                return candidate_in(conn, record)
            return record

        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            done = previous(conn)
            if done:
                return done
            client, store, root, payload = research_file_review.check_in(
                conn, record_in(conn), data
            )
            operation = client.new_graph_operation_in(
                conn,
                "research_file",
                data["expected"]["observation"]["entity_id"],
                payload,
                operation_id=request_id,
                restore=data["target"]["restoring"],
            )
            self._check(conn)
        # Complete and verify immutable version files before acquiring the write lock.
        directory = materialize(store, root, operation)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            done = previous(conn)
            if done:
                return done
            client, _store, _root, payload = research_file_review.check_in(
                conn, record_in(conn), data, allow_storage_creation=True
            )
            current = client.new_graph_operation_in(
                conn,
                "research_file",
                operation["entity_id"],
                payload,
                operation_id=request_id,
                restore=data["target"]["restoring"],
            )
            if canonical_operation(current) != canonical_operation(operation):
                raise ValueError("Displayed synchronization base changed; review again")
            with sync_capture.suppress_capture(conn):
                client.journal.apply_in(conn, operation, client.writer)
                if not activate(conn, operation, directory):
                    raise ValueError("Reviewed slide target changed before activation")
                _setup(conn)
                result = {"decision": "applied", "operation_id": request_id}
                self._receipt(conn, request_id, fingerprint, data, result)
                self._check(conn)
            conn.commit()
            return result

    def decide(
        self,
        preview,
        *,
        keep=False,
        body=None,
        request_id=None,
        confirm_target=False,
        _note_receipt=None,
    ):
        data = self._verify_preview(preview)
        if data["origin"] == "highlight_resume":
            raise ValueError("Use typed highlight verification and complete-group application")
        if data["origin"] == "claim_resume":
            raise ValueError("Use typed claim verification and application")
        if _note_receipt is not None and (
            data["origin"] != "archived_note_resume" or not callable(_note_receipt)
        ):
            raise ValueError("A local typed note receipt callback is required")
        if data["origin"] == "archived_draft":
            raise ValueError("Historical draft requires explicit current target/source review")
        request_id = request_id or str(uuid4())
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("Invalid review request identity")
        if type(keep) is not bool or (body is not None and not isinstance(body, str)):
            raise ValueError("Invalid review choice")
        stable = {
            key: value for key, value in data.items() if key not in {"session", "resume_state"}
        }
        fingerprint = digest(
            {"preview": stable, "keep": keep, "body": body, "confirm_target": confirm_target}
        )
        if data.get("resume_state") == "foreign":
            raise ValueError(
                "Draft belongs to an earlier workspace; select and review its target explicitly"
            )
        if data["origin"] in {"local_deck", "enrolled_deck"} and not keep:
            if data["origin"] == "local_deck":
                from paper_daily import local_deck_review as proposal_review
            else:
                from paper_daily import enrolled_deck_review as proposal_review

            with self._file_apply_lock:
                return proposal_review.apply(
                    self, data, fingerprint, request_id, body, confirm_target
                )
        if data["origin"] in {"file", "file_draft"} and not keep:
            with self._file_apply_lock:
                return self._decide_file(data, fingerprint, request_id, body, confirm_target)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._check(conn)
            _setup(conn)
            previous = conn.execute(
                "SELECT * FROM research_review_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("Review retry changed its decision or draft")
                return json.loads(previous["result"])
            record = self._record(conn, data["origin"], data["id"])
            if digest(record) != data["record_hash"]:
                raise ValueError("Retained record changed; keep your draft and reload the preview")
            operation_id = None
            if keep:
                result = {"decision": "kept", "operation_id": None}
                self._receipt(conn, request_id, fingerprint, data, result)
                if _note_receipt is not None:
                    _note_receipt(conn, result)
                self._check(conn)
                conn.commit()
                return result
            if data.get("resume_state", "ready") != "ready":
                raise ValueError("Saved draft needs refreshed review before application")
            if _source_aware_required(data):
                raise ValueError(SOURCE_AWARE_REASON)
            if not data["apply"]:
                raise ValueError(data["reason"])
            if data["requires_confirmation"] and confirm_target is not True:
                raise ValueError("Confirm the explicitly selected target before applying")
            if data["origin"] in {"archived_resume", "archived_note_resume"}:
                from paper_daily.review_draft_resumption import adapter

                apply_in = adapter(data["origin"]).apply_in
                result = {"decision": "applied", "operation_id": None}

                def complete():
                    self._receipt(conn, request_id, fingerprint, data, result)
                    if _note_receipt is not None:
                        _note_receipt(conn, result)
                    self._check(conn)
                    conn.commit()

                apply_in(self, conn, data, body, complete)
                return result
            if data["origin"] in COMPOUND_ORIGINS:
                from paper_daily import research_compound_review

                if body is not None:
                    raise ValueError(
                        "Compound groups are applied as typed records, not edited JSON"
                    )
                result = {"decision": "applied", "operation_id": None}

                def receipt():
                    self._receipt(conn, request_id, fingerprint, data, result)
                    self._check(conn)

                research_compound_review.apply_in(conn, record, data, receipt)
                return result
            if data["origin"] in {"generation", "sidecar"}:
                from paper_daily import research_annotation_review

                if research_annotation_review.handles(record):
                    if body is not None:
                        raise ValueError("Highlights require typed grouped application")
                    result = {"decision": "applied", "operation_id": None}

                    def receipt():
                        self._receipt(conn, request_id, fingerprint, data, result)
                        self._check(conn)

                    research_annotation_review.apply_in(conn, record, data, receipt)
                    return result
                expected = generation.GenerationContext(data["expected"])
                kind = generation.REGISTRY[expected.table][0]
                if (
                    not data["parent_token"]
                    or parent_lifecycle(conn, kind, expected.owner_id) != data["parent_token"]
                ):
                    raise ValueError("Selected parent lifecycle changed; your draft is retained")
                root = "papers" if kind == "paper" else "lists"
                parent = conn.execute(
                    f"SELECT * FROM {root} WHERE id=?", (expected.owner_id,)
                ).fetchone()
                if parent is None or dict(parent) != data["parent_row"]:
                    raise ValueError("Displayed target changed; your draft is retained")
                reason = generation._stale(conn, expected)
                if reason:
                    raise ValueError(reason + "; your draft is retained")
                row = dict(data["retained"])
                if body is not None:
                    field = "body" if "body" in row else "summary"
                    if field not in row:
                        raise ValueError("This candidate has no editable text")
                    row[field] = body
                    if "edited" in row:
                        row["edited"] = 1
                original = generation.GenerationContext(record["context_json"])
                if data["requires_confirmation"]:
                    original_data = original.data
                    original_data["owner_id"] = expected.owner_id
                    original = generation.GenerationContext(generation._context_json(original_data))
                generation._validate_row(original, row)
                observation = expected.data["observation"]
                with sync_capture.expecting(
                    conn,
                    [observation],
                    source_hashes=(
                        {observation["entity_id"]: data["source_hash"]} if observation else {}
                    ),
                ):
                    column = generation.REGISTRY[expected.table][1]
                    columns = list(row)
                    quoted = ",".join(f'"{key}"' for key in columns)
                    updates = ",".join(
                        f'"{key}"=excluded."{key}"' for key in columns if key != column
                    )
                    conn.execute(
                        f'INSERT INTO "{expected.table}"({quoted}) VALUES('
                        + ",".join("?" for _ in columns)
                        + f') ON CONFLICT("{column}") DO UPDATE SET {updates}',
                        tuple(row.values()),
                    )
                    result = {"decision": "applied", "operation_id": None}
                    self._receipt(conn, request_id, fingerprint, data, result)
                    self._check(conn)
                    conn.commit()
                    return result
            if data["origin"] == "remote":
                from paper_daily import research_annotation_review

                if research_annotation_review.remote_group(data):
                    if body is not None:
                        raise ValueError("Highlights require typed grouped application")
                    result = {"decision": "applied", "operation_id": None}

                    def receipt(operation_id):
                        result["operation_id"] = operation_id
                        self._receipt(conn, request_id, fingerprint, data, result)
                        self._check(conn)

                    research_annotation_review.apply_remote_in(conn, data, request_id, receipt)
                    return result
                payload = json.loads(encode(data["retained"]))
                if data["scope"]["kind"] == "research_content" and payload.get("feature") in {
                    "highlight_analysis",
                    "ai_highlight",
                }:
                    raise ValueError("Highlight conflicts require complete grouped source review")
                if body is not None:
                    target = payload.get("data", payload)
                    field = "body" if "body" in target else "summary"
                    if field not in target:
                        raise ValueError("This conflict has no editable text body")
                    target[field] = body
                    if "edited" in target:
                        target["edited"] = 1
                client = conn._capture_client
                with sync_capture.suppress_capture(conn):
                    result = client.resolve_conflict_in(
                        conn,
                        int(data["id"]),
                        expected=data["expected"],
                        payload=payload,
                        operation_id=request_id,
                    )
                operation_id = result["operation_id"]
            else:
                raise ValueError("Typed application is not available")
            result = {"decision": "applied", "operation_id": operation_id}
            self._receipt(conn, request_id, fingerprint, data, result)
            self._check(conn)
            conn.commit()
            return result

    @staticmethod
    def _receipt(conn, identity, fingerprint, data, result):
        scope = data.get("scope") or {}
        kind = generation.REGISTRY[scope["table"]][0] if "table" in scope else scope.get("kind")
        provenance = {
            "source_document_hash": data["source_hash"],
            "target_kind": kind,
            "target_id": scope.get("owner_id", scope.get("id")),
            "parent_token": data.get("parent_token"),
        }
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO research_review_receipts VALUES(?,?,?,?,?,?,?)",
                (
                    identity,
                    fingerprint,
                    data["origin"],
                    data["id"],
                    result["decision"],
                    encode(result),
                    encode(provenance),
                ),
            )

    def save_draft(self, preview, body, request_id, **options):
        from paper_daily.research_review_drafts import DraftStore

        return DraftStore(self).save(preview, body, request_id, **options)

    def load_draft(self, origin, identity, **options):
        from paper_daily.research_review_drafts import DraftStore

        return DraftStore(self).latest(origin, identity, **options)

    def list_drafts(self, origin, identity, **options):
        from paper_daily.research_review_drafts import DraftStore

        return DraftStore(self).list(origin, identity, **options)

    def export_text(self, preview, *, body=None):
        data = self._verify_preview(preview)
        # Explicit allowlist: no original contexts, paths, input receipts or credentials.
        value = {
            "format": "paperfact.review-text.v1",
            "origin": data["origin"],
            "source_document_hash": data["source_hash"],
            "content": (
                _claim_export(data["retained"])
                if _source_aware_required(data)
                else _export_content(data["retained"])
            ),
        }
        if body is not None:
            if not isinstance(body, str):
                raise ValueError("Invalid draft text")
            value["content"] = body
        encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_EXPORT:
            raise ValueError("Review export exceeds the supported size")
        return encoded

    def export(self, preview, destination, *, body=None):
        text = self.export_text(preview, body=body)
        # Exclusive create: never overwrite a research file or an existing export.
        with Path(destination).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)


def _claim_export(value):
    """Export only validated readable claim text, never report/source provenance."""
    from paper_daily import annotation_content

    row = value.get("data", value) if isinstance(value, dict) else {}
    raw = row.get("body_json") if isinstance(row, dict) else None
    if isinstance(raw, dict):
        raw = encode(raw)
    try:
        body = annotation_content.decode("claims", raw)
    except (ValueError, TypeError, KeyError):
        return {"unavailable": "Claim content could not be validated for readable export"}
    return {
        "claims": [
            {
                "text": claim["text"],
                "judgment": {
                    "status": claim["judgment"]["status"],
                    "reason": claim["judgment"]["reason"],
                },
                "passages": [
                    {"quote": item["quote"], "location": item["location"]["state"]}
                    for item in claim["passages"]
                ],
            }
            for claim in body["report"]["claims"]
        ]
    }


def _export_content(value):
    """Export readable text only; metadata and arbitrary stored paths are excluded."""
    if isinstance(value, list):
        return [_export_content(item) for item in value]
    if not isinstance(value, dict):
        return value if isinstance(value, (str, int, float, bool, type(None))) else None
    keys = {
        "body",
        "quote",
        "reason",
        "title",
        "summary",
        "text",
        "speaker_notes",
        "notes",
        "purpose",
        "gist",
        "verdict",
        "why",
        "relation",
        "context",
        "kind",
        "note",
        "url",
        "ref_key",
        "work_id",
    }
    result = {key: value[key] for key in keys & value.keys() if isinstance(value[key], str)}
    for key in (
        "data",
        "payload",
        "slides",
        "new",
        "old",
        "row",
        "rows",
        "puts",
        "deletes",
        "analysis",
        "marks",
        "unmatched",
        "body_json",
        "items",
        "links",
    ):
        if key in value:
            nested = value[key]
            if key == "body_json" and isinstance(nested, str):
                try:
                    nested = json.loads(nested)
                except ValueError:
                    nested = None
            result[key] = _export_content(nested)
    return result


def _safe_recovery(table, value):
    if table == "research_review_drafts":
        from paper_daily.research_review_drafts import validate_record

        validate_record(value)
        return {"body": value["body"]}
    if table in {"research_generation_requests", "research_generation_recovery"}:
        generation.validate_request_record(value)
        return json.loads(value["row_json"])
    if table == "research_capture_candidates":
        content = json.loads(value["content"])
        if set(content) != {"observations", "mutations"}:
            raise ValueError("Invalid detached capture record")
        return content["mutations"]
    if table in {"paperfact_sync_operations", "research_resolution_intents"}:
        from paper_daily.sync_journal import canonical_operation

        operation = json.loads(
            canonical_operation(json.loads(value.get("envelope", value.get("operation"))))
        )
        return operation["payload"]
    return {"summary": "Historical record retained; this record type has no text preview adapter"}


def _capture_preview(conn, value):
    """Read-only closed mutation adapter. Never executes retained SQL/mutations."""
    if (
        not isinstance(value, dict)
        or set(value) != {"observations", "mutations"}
        or not isinstance(value["observations"], list)
        or not isinstance(value["mutations"], list)
        or not 1 <= len(value["mutations"]) <= 2000
        or len(value["observations"]) > 2000
    ):
        raise ValueError("Invalid retained capture candidate")
    original, current, retained = [], [], []
    used = 0
    for mutation in value["mutations"]:
        if (
            not isinstance(mutation, dict)
            or set(mutation) != {"table_name", "row_key", "before_json", "after_json"}
            or mutation["table_name"] not in sync_capture.RESEARCH
        ):
            raise ValueError("Unsupported retained capture mutation")
        table = mutation["table_name"]
        primary = sync_capture._primary(conn, table)
        fields = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        key = json.loads(mutation["row_key"])
        if not isinstance(key, list) or len(key) != len(primary):
            raise ValueError("Invalid retained row identity")
        before = json.loads(mutation["before_json"]) if mutation["before_json"] else None
        after = json.loads(mutation["after_json"]) if mutation["after_json"] else None
        for row in (before, after):
            if row is not None and (
                not isinstance(row, dict)
                or set(row) != fields
                or [row[column] for column in primary] != key
            ):
                raise ValueError("Retained row differs from its closed schema")
        where = " AND ".join(f'"{column}" IS ?' for column in primary)
        size = "+".join(f'coalesce(length(CAST("{column}" AS BLOB)),0)' for column in fields)
        count = conn.execute(f'SELECT {size} FROM "{table}" WHERE {where}', key).fetchone()
        used += count[0] if count else 0
        if used > MAX_DETAIL:
            raise ValueError("Current compound preview exceeds the supported size")
        row = conn.execute(f'SELECT * FROM "{table}" WHERE {where}', key).fetchone()
        original.append({"table": table, "row": before})
        current.append({"table": table, "row": dict(row) if row else None})
        retained.append({"table": table, "row": after})
    return original, current, retained
