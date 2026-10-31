"""Explicit selected retained deck audit. No cache lookup, materialization or source adoption."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import audit_inputs, claim_content, file_change, research_audit
from paper_daily import research_evidence as evidence
from paper_daily.sync_artifacts import paper_current, verify_closure
from paper_daily.sync_deck_files import FIGURE_FIELDS, SOURCE_FIELDS
from paper_daily.sync_documents import _paper_current, _validate_target, desired_document
from paper_daily.sync_files import canonical_json, file_id, read_json
from paper_daily.sync_journal import _identifier, canonical_operation
from paper_daily.workspace_activity import _versions
from paper_daily.workspace_service import Ticket, _binding, _safe_path, _tables

MAX_BODY = 1024**2
MAX_ASSETS = 16 * 1024**2
MAX_SOURCE_IDS = 32
MAX_ORIGINALS = 4
MAX_PDF_BYTES = 32 * 1024**2
MAX_PAGES = 96
MAX_WORDS = 50_000
_SEAL = object()


def _fail(code):
    raise research_audit.AuditError(code) from None


def _operation(conn, table, key, value, *, active=False):
    if (table, key) not in {
        ("research_file_versions", "operation_id"),
        ("research_file_desired", "entity_id"),
        ("research_file_applied", "entity_id"),
    }:
        _fail("invalid_deck_scope")
    rows = conn.execute(
        "SELECT entity_id,CASE WHEN length(CAST(operation AS BLOB))<=? THEN operation END "
        f"FROM {table} "
        f"WHERE {key}=?" + (" AND active=1" if active else "") + " LIMIT 2",
        (256 * 1024, value),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or rows[0][1] is None:
        _fail("input_limit")
    if not isinstance(rows[0][1], str):
        _fail("invalid_saved_deck")
    operation = read_json(rows[0][1].encode("utf-8"))
    if (
        canonical_operation(operation) != rows[0][1]
        or operation["entity_type"] != "research_file"
        or operation["action"] != "put"
        or operation["entity_id"] != rows[0][0]
        or operation[key] != value
    ):
        _fail("invalid_saved_deck")
    return operation


def _slide_text(slide):
    pieces = [slide[key] for key in ("title", "section", "takeaway")]
    pieces.extend(slide["bullets"])
    pieces.append(slide["speaker_notes"])
    for entry in slide["elements"] or []:
        if entry["kind"] == "text":
            pieces.append(entry["text"])
        elif entry["kind"] == "table":
            pieces.extend("\t".join(row) for row in entry["rows"])
    return "\n\n".join(pieces)


def _items(raw, source, digest):
    sid = source["id"]
    values = [
        dict(
            id="slide:" + str(index + 1),
            feature="slides",
            text=_slide_text(slide),
            document_hash=digest,
            passages=[],
            reference=None,
        )
        for index, slide in enumerate(raw["slides"])
        if sid in slide["sources"]
    ]
    if source.get("text", "").strip():
        passages = []
        if source["kind"] == "original":
            passages = [
                dict(
                    quote=source["text"], page=source.get("page"), anchor=None, document_hash=digest
                )
            ]
        values.append(
            dict(
                id="source:" + sid,
                feature="slides",
                text=source["text"],
                document_hash=digest,
                passages=passages,
                reference=None,
            )
        )
    figure = next((row for row in raw["figures"] if row["id"] == sid), None)
    if figure and figure.get("caption", "").strip():
        values.append(
            dict(
                id="figure:" + sid,
                feature="slides",
                text=figure["caption"],
                document_hash=digest,
                passages=[],
                reference=None,
            )
        )
    return research_audit.validate(values)


def _unavailable(items):
    checks = []
    for item in items:
        base = dict(item_id=item["id"], feature="slides", binding="unknown")
        for index, passage in enumerate(item["passages"]):
            checks.append(
                dict(
                    base,
                    rule="quote_location",
                    state="source_unknown",
                    passage=index,
                    quote=passage["quote"],
                    location=None,
                )
            )
        for value in research_audit.quantities(item["text"]):
            checks.append(
                dict(base, rule="quantity_occurrence", state="source_unknown", quantity=value)
            )
    return dict(items=items, checks=checks, semantics="not_checked")


def _visible_saved(selected, operation):
    """Compare editor narrative through the exact existing portable-deck field projection."""
    from paper_daily.presentations import deck_from_dict
    from paper_daily.slide_layout import used_figures

    raw = copy.deepcopy(selected)
    parsed = deck_from_dict(raw)
    raw["paper_id"] = operation["payload"]["paper_id"]
    raw["generation"] = {
        k: v
        for k, v in raw["generation"].items()
        if k in {"inputs", "backend", "model"} and v is not None
    }
    assets = {row["id"]: row for row in operation["payload"]["assets"] if row["role"] == "figure"}
    figures = []
    for row in raw["figures"]:
        if row["id"] not in used_figures(parsed):
            continue
        if row.get("asset") != assets[row["id"]]["sha256"] + ".png":
            _fail("selected_deck_changed")
        figures.append(
            {**{k: v for k, v in row.items() if k in FIGURE_FIELDS}, "asset_id": row["id"]}
        )
    raw["figures"] = figures
    raw["sources"] = [
        {k: v for k, v in row.items() if k in SOURCE_FIELDS} for row in raw["sources"]
    ]
    return raw


@dataclass(frozen=True)
class PreparedDeckAudit:
    _json: str = field(repr=False)
    _versions: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    _reader: object = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def report(self):
        return json.loads(self._json)


class DeckAuditReader:
    def __init__(
        self,
        database,
        paper_id,
        slot,
        operation_id,
        *,
        selected=None,
        selected_operation=None,
        owner=None,
        expected_binding=None,
        current_path=None,
    ):
        self.path = _safe_path(database)
        info = self.path.stat()
        self.identity = info.st_dev, info.st_ino
        self._initial = _versions(self.path)
        self.current_path = current_path or (lambda: self.path)
        if slot not in {"notes", "guide"} or not isinstance(paper_id, str) or not paper_id:
            _fail("invalid_deck_scope")
        _identifier(operation_id)
        self.paper_id, self.slot, self.operation_id = paper_id, slot, operation_id
        self.selected = canonical_json(selected).decode() if selected is not None else None
        self.selected_operation = (
            canonical_json(selected_operation).decode() if selected_operation is not None else None
        )
        if self.selected is not None and len(self.selected.encode()) > MAX_BODY:
            _fail("input_limit")
        if owner is not None:
            from paper_daily.manual_highlight_ops import HighlightOwner

            if not isinstance(owner, HighlightOwner):
                _fail("invalid_deck_scope")
        self.owner = owner
        self.expected_binding = tuple(expected_binding) if expected_binding is not None else None
        self.binding = None
        self._token = object()

    def _path(self):
        if Path(self.current_path()).resolve() != self.path:
            _fail("saved_content_changed")
        info = _safe_path(self.path).stat()
        if not info.st_ino or (info.st_dev, info.st_ino) != self.identity:
            _fail("saved_content_changed")

    def current(self, prepared):
        try:
            self._path()
            return (
                isinstance(prepared, PreparedDeckAudit)
                and prepared._seal is _SEAL
                and prepared._reader is self._token
                and _versions(self.path) == prepared._versions
                and all(file_change.version(path) == version for path, version in prepared._files)
            )
        except (OSError, ValueError):
            return False

    def _scope(self, conn, versions):
        binding = _binding(conn, _tables(conn))
        if self.binding is None:
            if versions != self._initial:
                _fail("saved_content_changed")
        elif binding != self.binding:
            _fail("saved_content_changed")
        named = dict(binding)
        workspace, device = named.get("research_sync_binding", (None, None))
        if workspace is None or (
            self.expected_binding is not None
            and tuple(self.expected_binding) != (workspace, device)
        ):
            _fail("invalid_deck_scope")
        if self.owner is not None:
            if self.owner.database != self.path or self.owner.paper_id != self.paper_id:
                _fail("invalid_deck_scope")
            self.owner.check(conn)
        return binding, workspace

    def _deck(self, conn, workspace):
        mapping = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=? LIMIT 2", (self.paper_id,)
        ).fetchall()
        if len(mapping) != 1:
            _fail("invalid_deck_scope")
        identity = file_id(mapping[0][0], "deck", self.slot)
        operation = _operation(conn, "research_file_versions", "operation_id", self.operation_id)
        desired = _operation(conn, "research_file_desired", "entity_id", identity, active=True)
        if (
            operation is None
            or desired is None
            or operation["entity_id"] != identity
            or operation["action"] != "put"
            or operation["workspace_id"] != workspace
            or desired["workspace_id"] != workspace
            or operation["payload"]["feature"] != "deck"
            or operation["payload"]["paper_id"] != mapping[0][0]
            or operation["payload"]["slot"] != self.slot
            or (operation["incarnation"], operation["parents"])
            != (desired["incarnation"], desired["parents"])
            or not paper_current(conn, operation)
        ):
            _fail("saved_deck_unavailable")
        if (
            self.selected_operation is not None
            and canonical_json(operation).decode() != self.selected_operation
        ):
            _fail("selected_deck_changed")
        payload = operation["payload"]
        if (
            payload["body"]["size"] > MAX_BODY
            or sum(row["size"] for row in payload["assets"]) > MAX_ASSETS
        ):
            _fail("input_limit")
        from paper_daily.sync_source_files import _inspection_paths

        configured = _inspection_paths(conn)
        if configured is None:
            _fail("saved_deck_unavailable")
        store = configured[0]
        proof, body, _blobs = verify_closure(store, operation)
        raw = body["deck"]
        if (
            self.selected is not None
            and _visible_saved(json.loads(self.selected), operation) != raw
        ):
            _fail("selected_deck_changed")
        return operation, raw, proof, store

    def _original(self, conn, ref, workspace, store, budget, ticket):
        from paper_daily.sync_source_files import FEATURE

        rows = conn.execute(
            "SELECT CASE WHEN length(CAST(target AS BLOB))<=4096 THEN target END "
            "FROM research_document_intents WHERE operation_id=? AND paper_id=? LIMIT 2",
            (ref["operation_id"], ref["paper_id"]),
        ).fetchall()
        if not rows:
            return "document_scope_unavailable", None
        if len(rows) != 1 or rows[0][0] is None:
            _fail("invalid_source_scope")
        target = read_json(rows[0][0].encode())
        _validate_target(target)
        if target["workspace_id"] != workspace or any(target[key] != ref[key] for key in ref):
            _fail("invalid_source_scope")
        if not _paper_current(conn, target):
            return "source_parent_replaced", None
        identity = file_id(ref["paper_id"], FEATURE, ref["sha256"])
        operation = _operation(conn, "research_file_desired", "entity_id", identity, active=True)
        if operation is None:
            return "original_unavailable", None
        if (
            operation["workspace_id"] != workspace
            or operation["payload"]["feature"] != FEATURE
            or operation["parents"]
            != [dict(kind="paper", id=ref["paper_id"], incarnation=ref["parent_incarnation"])]
            or not paper_current(conn, operation)
        ):
            return "source_parent_replaced", None
        retained = _operation(
            conn, "research_file_versions", "operation_id", operation["operation_id"]
        )
        if retained != operation:
            _fail("invalid_source_scope")
        payload = operation["payload"]
        if payload["slot"] != ref["sha256"]:
            _fail("invalid_source_scope")
        amount = payload["assets"][0]["size"]
        budget[0] += amount
        if payload["body"]["size"] > 65536 or budget[0] > MAX_PDF_BYTES:
            _fail("input_limit")
        ticket.check()
        try:
            proof, body, blobs = verify_closure(store, operation)
        except FileNotFoundError:
            return "original_unavailable", None
        data = blobs[ref["sha256"]]
        if body["document_hash"] != ref["sha256"]:
            _fail("invalid_source_scope")
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            budget[1] += len(pdf)
            if budget[1] > MAX_PAGES:
                _fail("input_limit")
        extracted = evidence._extract(data, lambda: ticket.cancelled)
        budget[2] += sum(len(words) for words in extracted[0])
        if budget[2] > MAX_WORDS:
            _fail("input_limit")
        title = conn.execute(
            "SELECT p.title FROM research_paper_identity m JOIN papers p "
            "ON p.id=m.local_id WHERE m.sync_id=?",
            (ref["paper_id"],),
        ).fetchone()
        current = desired_document(conn, ref["paper_id"])
        return "available", dict(
            ref=ref,
            operation=operation,
            proof=proof,
            extracted=extracted,
            title=title[0],
            current_primary_matches=current["sha256"] == ref["sha256"] if current else None,
        )

    def prepare(self, ticket=None):
        ticket = ticket or Ticket()
        ticket.check()
        self._path()
        versions = _versions(self.path)
        try:
            with closing(audit_inputs._connect(self.path)) as conn:
                steps = [0]

                def bounded():
                    steps[0] += 2000
                    return steps[0] > 500000 or ticket.cancelled

                conn.set_progress_handler(bounded, 2000)
                conn.execute("BEGIN")
                binding, workspace = self._scope(conn, versions)
                operation, raw, closure, store = self._deck(conn, workspace)
                used = {sid for slide in raw["slides"] for sid in slide["sources"]}
                if len(used) > MAX_SOURCE_IDS:
                    _fail("input_limit")
                sources = [row for row in raw["sources"] if row["id"] in used]
                refs = operation["payload"]["input_versions"]["documents"]
                figures = {row["id"]: row for row in raw["figures"]}
                originals, results, files, budget = {}, [], dict(closure.files), [0, 0, 0]
                index = store.root / "index.sqlite"
                files["registered:index"] = (index, file_change.version(index))
                item_count = passage_count = quantity_count = input_bytes = 0
                for source in sources:
                    ticket.check()
                    digest = source.get("document_hash")
                    figure = figures.get(source["id"])
                    if (
                        figure
                        and digest
                        and figure.get("document_hash")
                        and digest != figure["document_hash"]
                    ):
                        _fail("invalid_saved_deck")
                    matches = [
                        ref for ref in refs if digest is not None and ref["sha256"] == digest
                    ]
                    state, original = "source_unknown", None
                    if digest is not None:
                        if not matches:
                            state = "source_owner_unrecorded"
                        elif len(matches) != 1:
                            state = "source_owner_ambiguous"
                        else:
                            key = (matches[0]["paper_id"], digest, matches[0]["parent_incarnation"])
                            if key not in originals:
                                if len(originals) >= MAX_ORIGINALS:
                                    _fail("input_limit")
                                originals[key] = self._original(
                                    conn, matches[0], workspace, store, budget, ticket
                                )
                            state, original = originals[key]
                    items = _items(raw, source, digest if original else None)
                    input_bytes += len(canonical_json(items))
                    if input_bytes > research_audit.MAX_BYTES:
                        _fail("input_limit")
                    item_count += len(items)
                    passage_count += sum(len(item["passages"]) for item in items)
                    quantity_count += sum(
                        len(research_audit.quantities(item["text"])) for item in items
                    )
                    if (
                        item_count > research_audit.MAX_ITEMS
                        or passage_count > research_audit.MAX_PASSAGES
                        or quantity_count > research_audit.MAX_QUANTITIES
                    ):
                        _fail("input_limit")
                    if original:
                        files.update(original["proof"].files)
                        report = research_audit._run_checked_pages(
                            dict(paper_id=original["ref"]["paper_id"], document_hash=digest),
                            items,
                            original["extracted"],
                            cancelled=lambda: ticket.cancelled,
                            progress=lambda _a, _b: None,
                        )
                    else:
                        report = _unavailable(items)
                    results.append(
                        dict(
                            id=source["id"],
                            label=source["label"],
                            kind=source["kind"],
                            recorded_document_hash=digest,
                            state=state,
                            owner=original["ref"] if original else None,
                            original_operation_id=original["operation"]["operation_id"]
                            if original
                            else None,
                            original_incarnation=original["operation"]["incarnation"]
                            if original
                            else None,
                            paper_title=original["title"] if original else None,
                            current_primary_matches=original["current_primary_matches"]
                            if original
                            else None,
                            report=report,
                        )
                    )
                if not closure.matches(operation) or any(
                    value and not value["proof"].matches(value["operation"])
                    for _state, value in originals.values()
                ):
                    _fail("saved_content_changed")
                result = dict(
                    format="paperfact.deck-audit.v1",
                    rule_version=research_audit.RULE,
                    paper_id=self.paper_id,
                    deck_id=raw["deck_id"],
                    title=raw["title"],
                    slot=self.slot,
                    operation_id=operation["operation_id"],
                    body_hash=operation["payload"]["body"]["sha256"],
                    input_digest=raw["source_hash"],
                    sources=results,
                    source_catalog_count=len(raw["sources"]),
                    covered_sources=sum(row["state"] == "available" for row in results),
                    coverage_complete=bool(results)
                    and all(row["state"] == "available" for row in results),
                    slides=len(raw["slides"]),
                    coverage_notes=raw["coverage"],
                    semantics="not_checked",
                    not_checked=[
                        "semantic_support",
                        "scientific_validity",
                        "causal_influence",
                        "image_content",
                        "figure_table_interpretation",
                        "figure_locator",
                        "unused_source_catalog",
                        "legacy_unbound_decks",
                        "detached_recovery",
                        "source_jump",
                    ],
                )
                if len(canonical_json(result)) > 4 * research_audit.MAX_BYTES:
                    _fail("input_limit")
            ticket.check()
            self._path()
            if _versions(self.path) != versions:
                _fail("saved_content_changed")
            witnesses = tuple(value for value in files.values())
            if any(file_change.version(path) != version for path, version in witnesses):
                _fail("saved_content_changed")
            self.binding = binding
            result["id"] = claim_content.hashed(result)
            return PreparedDeckAudit(
                canonical_json(result).decode(), versions, witnesses, self._token, _SEAL
            )
        except research_audit.AuditError:
            raise
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, RecursionError):
            _fail("invalid_saved_deck")
