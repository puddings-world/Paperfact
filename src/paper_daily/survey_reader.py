"""Read saved survey evidence and exact originals without publication or AI."""

from __future__ import annotations

import hmac
import json
import secrets
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import (
    file_change,
    source_snapshots,
    survey_local,
    survey_packages,
    sync_survey_files,
)
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_artifacts import applied_file, desired_file, owner_current, verify_closure
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_files import canonical_json, list_file_id
from paper_daily.sync_source_files import _inspection_paths
from paper_daily.workspace_service import _binding, _tables

_KEY = secrets.token_bytes(32)


class ReadChanged(ValueError):
    """A saved read lost its version observation; retry may capture a fresh one."""


def _signature(value):
    return hmac.new(
        _KEY,
        canonical_json(
            [
                str(value._database),
                value._stamp,
                value._json,
                value._operation,
                id(value._proof),
                id(value._store),
                value._archive,
                value._desired,
            ]
        ),
        "sha256",
    ).hexdigest()


def _stamp(database):
    result = []
    for path in (database, Path(str(database) + "-wal")):
        version = file_change.version(path) if path.exists() else None
        # SQLite may create a zero-byte WAL on a read-only open. It has no frames;
        # a nonempty WAL and the database retain their complete mutation guards.
        if path != database and version is not None and version[2] == 0:
            version = None
        result.append((str(path), version))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class SavedReport:
    _database: Path = field(repr=False)
    _stamp: tuple = field(repr=False)
    _json: str = field(repr=False)
    _proof: object = field(repr=False)
    _operation: object = field(repr=False)
    _store: object = field(repr=False)
    _seal: object = field(repr=False)
    _archive: tuple | None = field(default=None, repr=False)
    _desired: object = field(default=None, repr=False)

    @property
    def data(self):
        return json.loads(self._json)

    def current(self):
        try:
            return (
                isinstance(self._seal, str)
                and hmac.compare_digest(self._seal, _signature(self))
                and _stamp(self._database) == self._stamp
                and (self._proof is None or self._proof.matches(self._operation))
                and (self._archive is None
                     or _archive_stamp(Path(self._archive[0])) == self._archive[1])
            )
        except (OSError, ValueError):
            return False


def _cancel(cancelled):
    if cancelled():
        raise ValueError("Saved report reading cancelled")


def read(database, list_id, *, cancelled=lambda: False):
    """Worker read: verify report bytes now; verify PDF bytes only on inspection."""
    database = Path(database).resolve(strict=True)
    before = _stamp(database)
    _cancel(cancelled)
    operation = proof = store = desired = None
    data = None
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if not conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
            raise ValueError("The selected research list no longer exists")
        if "research_file_desired" in tables:
            desired = desired_file(conn, list_file_id(list_id))
            if desired is not None:
                client = runtime(database=database)
                if client is None:
                    raise ValueError("Saved report requires its enrolled workspace")
                graph = client._optimistic_graph(conn)[0]
                applied = applied_file(conn, desired["entity_id"])
                operation = applied or desired
                if (
                    not owner_current(conn, operation)
                    or operation["parents"] != desired["parents"]
                    or not sync_survey_files.active(
                        lambda kind, identity: graph.get((kind, identity)), operation
                    )
                ):
                    raise ValueError("Saved report source lifetimes require review")
                configured = _inspection_paths(conn)
                if configured is None:
                    raise ValueError("Saved report artifact storage is unavailable")
                store, _root = configured
                sources = []
                for binding in operation["payload"]["source_bindings"]:
                    row = conn.execute(
                        "SELECT p.local_id,CASE WHEN length(CAST(r.title AS BLOB))<=8000 "
                        "THEN r.title END FROM research_paper_identity p JOIN papers r "
                        "ON r.id=p.local_id WHERE p.sync_id=?",
                        (binding["paper_id"],),
                    ).fetchone()
                    original = desired_file(conn, binding["file_id"])
                    if row is None or row[1] is None or original is None:
                        raise ValueError("Saved report original owner is unavailable")
                    sources.append(
                        dict(
                            source_id=binding["source_id"],
                            paper_id=row[0],
                            title=row[1],
                            operation=original,
                        )
                    )
                data = dict(kind="native", sources=sources, update_pending=applied != desired)
        if data is None:
            if _binding(conn, tables):
                data = dict(kind="none", sources=[], update_pending=False)
            else:
                row = survey_local.current_in(conn, list_id)
                if row is not None:
                    body = survey_local._current_sources(conn, row, list(before[0][1][:2]))
                    contexts = survey_local._bounded_rows(
                        conn, "papers", [b["paper_id"] for b in body["bindings"]]
                    )
                    sources = [
                        dict(
                            source_id=b["source_id"],
                            paper_id=b["paper_id"],
                            title=p["title"],
                            original=b["original"],
                        )
                        for b, p in zip(body["bindings"], contexts, strict=True)
                    ]
                    data = dict(
                        kind="local", report=body["report"], sources=sources, update_pending=False
                    )
                else:
                    survey_local._detached_guard(conn, list_id)
                    data = dict(kind="none", sources=[], update_pending=False)
    _cancel(cancelled)
    if operation is not None:
        try:
            proof, body, _blobs = verify_closure(store, operation)
        except (OSError, ValueError) as error:
            raise ValueError(
                "Saved report bytes are unavailable; finish downloading and refresh"
            ) from error
        data["report"] = body["report"]
    data["list_id"] = list_id
    result = SavedReport(
        database, before, canonical_json(data).decode(), proof, operation, store, "",
        _desired=desired,
    )
    object.__setattr__(result, "_seal", _signature(result))
    if not result.current():
        raise ReadChanged(
            "Saved report changed while reading; refresh to inspect its current version"
        )
    return result


def complete_pending(saved, *, cancelled=lambda: False):
    """Finish only the displayed owned pending intent, with no AI/network or new grant."""
    from paper_daily import survey_publication

    _cancel(cancelled)
    if (not isinstance(saved, SavedReport) or saved._archive is not None
            or not hmac.compare_digest(saved._seal, _signature(saved))
            or saved.data["kind"] != "native" or not saved.data["update_pending"]
            or saved._desired is None):
        raise ValueError("Completion requires an observed pending native report")
    expected = json.loads(canonical_json(saved._desired))
    identity = list(saved._stamp[0][1][:2])
    if identity[1] <= 0:
        raise ValueError("Pending report has no stable database identity")
    client = runtime(database=saved._database)
    if client is None or client.journal.workspace_id != expected["workspace_id"]:
        raise ValueError("Pending report workspace changed; refresh first")
    return survey_publication.complete_pending(
        client, saved.data["list_id"], expected=expected, expected_database=identity,
        cancelled=cancelled)


def _archive_stamp(path):
    from paper_daily import research_generation as generation

    if any(generation._is_link(parent) for parent in (path, *path.parents)):
        raise ValueError("Retained report cannot traverse links")
    return file_change.version(path)


def read_retained(database, list_id, request_id, *, cancelled=lambda: False):
    """Seal read-only archive data; current originals and writer grants are irrelevant."""
    from paper_daily import research_generation as generation
    from paper_daily import survey_content, survey_jobs

    database = Path(database).resolve(strict=True)
    before = _stamp(database)
    _cancel(cancelled)
    record = survey_jobs._retained_record(database, list_id, request_id)
    context = generation.GenerationContext(record["context_json"])
    path = generation._recovery_path(context)
    stamp = _archive_stamp(path)
    if stamp[2] > generation.MAX_BYTES:
        raise ValueError("Retained report exceeds its archive budget")
    with path.open("rb") as stream:
        raw = stream.read(generation.MAX_BYTES + 1)
    if len(raw) > generation.MAX_BYTES or json.loads(raw) != record:
        raise ValueError("Retained report changed while reading")
    report = survey_content.decode(record["row_json"])
    originals = survey_jobs.retained_originals(record)
    titles = {member["paper_id"]: member["title"] for member in report["inputs"]["members"]}
    captured = [source for source in report["sources"] if source["state"] == "captured"]
    sources = [dict(source_id=source["id"], paper_id=source["paper_id"],
                    title=titles[source["paper_id"]], original=row)
               for source, row in zip(captured, originals, strict=True)]
    data = dict(kind="retained", report=report, sources=sources, update_pending=False,
                list_id=list_id, request_id=request_id)
    result = SavedReport(database, before, canonical_json(data).decode(), None, None, None, "",
                         (str(path), stamp))
    object.__setattr__(result, "_seal", _signature(result))
    _cancel(cancelled)
    if not result.current():
        raise ReadChanged("Retained report or workspace changed while reading")
    return result


def _checked_original(report, source, binding, cancelled):
    """Verify one exact original once; callers recheck the returned observation."""
    from paper_daily.local_source_owners import _read_pdf

    data = report.data
    if data["kind"] == "native":
        proof, _body, blobs = verify_closure(report._store, binding["operation"])
        raw = blobs[source["document_hash"]]

        def fresh():
            return proof.matches(binding["operation"])
    else:
        original = binding["original"]
        path = source_snapshots.source_path(report._database, original)
        if data["kind"] == "retained":
            from paper_daily import position_source_snapshots

            path, _initial = position_source_snapshots.verify(report._database, original)
        result = _read_pdf(path, original["sha256"], original["size"], cancelled)
        if result is None:
            raise ValueError("Saved report inspection cancelled")
        raw, version = result

        def fresh():
            if data["kind"] == "retained":
                try:
                    checked, observed = position_source_snapshots.verify(
                        report._database, original, known_version=version)
                    return checked == path and observed == version
                except (OSError, ValueError):
                    return False
            return file_change.version(path) == version

    survey_packages.verify_original(raw, source, data["report"], cancelled=cancelled)
    return raw, fresh


def inspect(report, section, statement, passage, *, page=None, cancelled=lambda: False):
    """Verify one captured original and render a bounded page; never change a reader."""
    if not isinstance(report, SavedReport) or not report.current():
        raise ValueError("Saved report changed; refresh before inspecting originals")
    _cancel(cancelled)
    data = report.data
    for index in (section, statement, passage):
        if type(index) is not int or index < 0:
            raise ValueError("Choose an actual saved quotation")
    try:
        item = data["report"]["sections"][section]["statements"][statement]["passages"][passage]
    except (KeyError, IndexError) as error:
        raise ValueError("Choose an actual saved quotation") from error
    source = next(s for s in data["report"]["sources"] if s["id"] == item["source_id"])
    binding = next((s for s in data["sources"] if s["source_id"] == source["id"]), None)
    if source["state"] != "captured" or binding is None:
        raise ValueError("This quotation has no captured original; no substitute was opened")
    raw, fresh = _checked_original(report, source, binding, cancelled)
    location = item["location"]
    selected = (
        page
        if page is not None
        else location["page"]
        if location and location["state"] == "located"
        else 1
    )
    if type(selected) is not int or not 1 <= selected <= source["page_count"]:
        raise ValueError("Choose a page within the captured original")
    import pymupdf

    with pymupdf.open(stream=raw, filetype="pdf") as document:
        sheet = document[selected - 1]
        scale = min(2.0, 1100 / max(sheet.rect.width, sheet.rect.height))
        image = sheet.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
    _cancel(cancelled)
    if not report.current() or not fresh():
        raise ValueError("Saved report or original changed during inspection")
    return dict(
        image=image,
        page=selected,
        pages=source["page_count"],
        quote=item["quote"],
        title=binding["title"],
        document_hash=source["document_hash"],
        located=bool(location and location["state"] == "located"),
    )
