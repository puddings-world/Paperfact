"""Portable saved survey/owned-original closure; no sender writer or import grant.

This codec/collector is internal until receiver mapping and publication are wired
into the existing bundle transaction. It never enrolls or mutates a workspace.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import research_evidence, survey_content, sync_survey_files
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_artifacts import desired_file, owner_current, verify_closure
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_files import (
    canonical_json,
    closed,
    descriptor,
    digest,
    list_file_id,
    read_json,
)
from paper_daily.sync_source_files import _inspection_paths

FORMAT = "paperfact.survey-package.v1"
TABLE = "survey_reports"
CAPABILITY = "survey_evidence"
MAX_PDF_BYTES = 64 * 1024**2
MAX_FILES = 4096
MAX_METADATA = 8 * 1024**2
MAX_PACKAGE_BODY = 3 * 1024**2
_KEY = secrets.token_bytes(32)


def relative(list_id, report_id):
    survey_content.content.text(list_id, 4096)
    digest(report_id)
    return (
        Path("survey-reports") / survey_content.content.hashed(list_id)[:24] / (report_id + ".json")
    )


def source_relative(list_id, paper_id, sha):
    survey_content.content.text(paper_id, 4096)
    digest(sha)
    return (
        Path("survey-sources")
        / survey_content.content.hashed(list_id)[:24]
        / survey_content.content.hashed(paper_id)[:24]
        / (sha + ".pdf")
    )


def _cancel(cancelled):
    if cancelled():
        raise ValueError("Survey package work cancelled")


def _snapshot(database, list_id):
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "research_file_desired" not in tables:
            return None
        operation = desired_file(conn, list_file_id(list_id))
        if operation is None:
            return None
        client = runtime(database=database)
        if client is None or not owner_current(conn, operation):
            raise ValueError("Survey package requires its actual current list owner")
        graph = client._optimistic_graph(conn)[0]
        if not sync_survey_files.active(
            lambda kind, identity: graph.get((kind, identity)), operation
        ):
            raise ValueError("Survey package original lifetimes are no longer active")
        registered = _inspection_paths(conn)
        if registered is None:
            raise ValueError("Survey package has no owned artifact storage")
        sources = []
        total_metadata = 0
        columns = [row[1] for row in conn.execute("PRAGMA table_info(papers)")]
        lengths = "+".join(
            'COALESCE(length(CAST("' + key.replace('"', '""') + '" AS BLOB)),0)' for key in columns
        )
        for binding in operation["payload"]["source_bindings"]:
            row = conn.execute(
                "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
                (binding["paper_id"],),
            ).fetchone()
            size = (
                conn.execute("SELECT " + lengths + " FROM papers WHERE id=?", (row[0],)).fetchone()
                if row
                else None
            )
            if size is None or total_metadata + size[0] > MAX_METADATA:
                raise ValueError("Survey package paper context exceeds its metadata bound")
            total_metadata += size[0]
            paper = conn.execute("SELECT * FROM papers WHERE id=?", (row[0],)).fetchone()
            original = desired_file(conn, binding["file_id"])
            if (
                paper is None
                or original is None
                or original["incarnation"] != binding["incarnation"]
            ):
                raise ValueError("Survey package source has no exact native owner/version")
            sources.append(dict(binding=binding, paper=dict(paper), operation=original))
        listing = conn.execute("SELECT * FROM lists WHERE id=?", (list_id,)).fetchone()
        return dict(
            operation=operation,
            sources=sources,
            listing=dict(listing),
            storage=[str(registered[0].root), str(registered[1])],
        )


def _signature(value):
    return hmac.new(
        _KEY,
        canonical_json(
            [
                str(value.database),
                value.native,
                value.observed,
                value.record_json,
                value.sources_json,
                [[name, id(data)] for name, data in value._files],
                [[id(proof), operation] for proof, operation in value._proofs],
                os.getpid(),
            ]
        ),
        "sha256",
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SurveyExport:
    database: Path = field(repr=False)
    native: tuple = field(repr=False)
    observed: str = field(repr=False)
    record_json: str = field(repr=False)
    sources_json: str = field(repr=False)
    _files: tuple = field(repr=False)
    _proofs: tuple = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def record(self):
        return json.loads(self.record_json)

    @property
    def sources(self):
        return json.loads(self.sources_json)

    @property
    def papers(self):
        return [row["paper"] for row in json.loads(self.observed)["sources"]]

    @property
    def files(self):
        return tuple((Path(name), data) for name, data in self._files)


def check_export(value):
    """Check the actual native capture at final publication, without new ownership."""
    if value is None:
        return
    from paper_daily import survey_local

    if isinstance(value, survey_local.LocalSurveyExport):
        return survey_local.check_export(value)
    if not isinstance(value, SurveyExport) or not isinstance(value._seal, str):
        raise ValueError("Survey package requires its sealed native export")
    if not hmac.compare_digest(value._seal, _signature(value)):
        raise ValueError("Survey package capture changed")
    observed = json.loads(value.observed)
    if (
        tuple(generation._identity(value.database)) != value.native
        or canonical_json(_snapshot(value.database, observed["listing"]["id"])).decode()
        != value.observed
    ):
        raise ValueError("Survey research or native owners changed during export")
    for proof, operation in value._proofs:
        if not proof.matches(json.loads(operation)):
            raise ValueError("Survey original/report bytes changed during export")


def collect(database, list_id, *, with_pdfs=True, cancelled=lambda: False):
    """Worker operation: retain exact report and every declared original as data."""
    _cancel(cancelled)
    if type(with_pdfs) is not bool:
        raise ValueError("Survey package PDF choice must be explicit")
    database = Path(database).resolve(strict=True)
    native = tuple(generation._identity(database))
    observed = _snapshot(database, list_id)
    if len(canonical_json(observed)) > MAX_METADATA:
        raise ValueError("Survey package native observation exceeds its metadata bound")
    if observed is None:
        from paper_daily import survey_local

        return survey_local.collect(database, list_id, with_pdfs=with_pdfs, cancelled=cancelled)
    if not with_pdfs:
        raise ValueError("Include exact original PDFs to share source-aware surveys")
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        store, _root = _inspection_paths(conn)
    operation = observed["operation"]
    proof, body, _blobs = verify_closure(store, operation)
    proofs = [(proof, canonical_json(operation).decode())]
    report = body["report"]
    bindings, sources, files = [], [], {}
    total = 0
    for row in observed["sources"]:
        _cancel(cancelled)
        binding, original = row["binding"], row["operation"]
        if (
            original["payload"]["feature"] != "original_source"
            or original["payload"]["paper_id"] != binding["paper_id"]
            or original["payload"]["slot"] != binding["document_hash"]
        ):
            raise ValueError("Survey package original differs from its native binding")
        source_proof, _source_body, blobs = verify_closure(store, original)
        data = blobs[binding["document_hash"]]
        total += len(data)
        if total > MAX_PDF_BYTES:
            raise ValueError("Survey package originals exceed aggregate bounds")
        source = next(item for item in report["sources"] if item["id"] == binding["source_id"])
        verify_original(data, source, report, cancelled=cancelled)
        path = source_relative(list_id, row["paper"]["id"], binding["document_hash"]).as_posix()
        bindings.append(dict(source_id=source["id"], paper_id=row["paper"]["id"]))
        sources.append(
            dict(
                source_id=source["id"],
                paper_id=row["paper"]["id"],
                sha256=binding["document_hash"],
                size=len(data),
                path=path,
            )
        )
        files[path] = data
        proofs.append((source_proof, canonical_json(original).decode()))
    portable = dict(format=FORMAT, list_id=list_id, report=report, bindings=bindings)
    data = canonical_json(portable)
    path = relative(list_id, report["id"]).as_posix()
    files[path] = data
    record = dict(
        list_id=list_id, report_id=report["id"], path=path, **descriptor(data, "application/json")
    )
    _cancel(cancelled)
    value = SurveyExport(
        database,
        native,
        canonical_json(observed).decode(),
        canonical_json(record).decode(),
        canonical_json(sources).decode(),
        tuple(files.items()),
        tuple(proofs),
        "",
    )
    object.__setattr__(value, "_seal", _signature(value))
    check_export(value)
    return value


def verify_original(data, source, report, *, cancelled=lambda: False):
    """Byte/page/located-quote verification only; no scientific or ownership grant."""
    _cancel(cancelled)
    if (
        not isinstance(data, bytes)
        or not 0 < len(data) <= MAX_PDF_BYTES
        or hashlib.sha256(data).hexdigest() != source["document_hash"]
    ):
        raise ValueError("Survey package original bytes differ")
    pages, indexes, whole = research_evidence._extract(data, cancelled)
    if len(pages) != source["page_count"]:
        raise ValueError("Survey package original page count differs")
    for section in report["sections"]:
        for statement in section["statements"]:
            for passage in statement["passages"]:
                _cancel(cancelled)
                location = passage["location"]
                if (
                    passage["source_id"] == source["id"]
                    and location is not None
                    and location["state"] == "located"
                ):
                    proposed = dict(
                        quote=passage["quote"], page=location["page"], anchor=location["anchor"]
                    )
                    if research_evidence._locate(proposed, pages, indexes, whole) != location:
                        raise ValueError("Survey located quote differs from its exact original")


def _read(archive, path, sha, size, maximum):
    digest(sha)
    if type(size) is not int or not 0 < size <= maximum:
        raise ValueError("Survey package file exceeds its byte bound")
    entries = [item for item in archive.infolist() if item.filename == "files/" + path]
    if len(entries) != 1 or entries[0].file_size != size or entries[0].is_dir():
        raise ValueError("Survey package requires one exact declared file")
    if (entries[0].external_attr >> 16) & 0o170000 == 0o120000:
        raise ValueError("Survey package cannot follow linked files")
    with archive.open(entries[0]) as stream:
        data = stream.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("Survey package file bytes differ")
    return data


def validate_package(archive, manifest, tables, *, cancelled=lambda: False):
    """Validate portable data only; the receiver must supply its own publication grant."""
    from paper_daily.lineage_packages import _metadata

    _cancel(cancelled)
    if not isinstance(manifest, dict) or not isinstance(tables, dict):
        raise ValueError("Survey package metadata must be objects")
    infos = archive.infolist()
    if len(infos) > MAX_FILES or len(infos) != len({item.filename.casefold() for item in infos}):
        raise ValueError("Survey package members are repeated or excessive")
    # Reuse the maintained strict, duplicate-key/bounded ZIP metadata decoder.
    if canonical_json(_metadata(archive, "manifest.json")) != canonical_json(
        manifest
    ) or canonical_json(_metadata(archive, "tables.json")) != canonical_json(tables):
        raise ValueError("Survey package metadata differs from its admitted snapshot")
    reports = tables.get(TABLE, [])
    if not isinstance(reports, list) or len(reports) > 1:
        raise ValueError("A list package needs at most one current survey report")
    declared = manifest.get("survey_sources", [])
    if not isinstance(declared, list) or len(declared) > sync_survey_files.MAX_SOURCES:
        raise ValueError("Survey package source collection exceeds its bound")
    caps = manifest.get("capabilities", [])
    if (
        not isinstance(caps, list)
        or any(not isinstance(cap, str) for cap in caps)
        or caps != sorted(set(caps))
        or (CAPABILITY in caps) != bool(reports)
        or reports
        and (manifest.get("format") != 2 or manifest.get("pdfs_included") is not True)
    ):
        raise ValueError("Survey package needs its exact capability and original PDFs")
    if not reports and (declared or "survey_sources" in manifest):
        raise ValueError("Survey sources require their declared report")
    listing = manifest.get("list")
    if not isinstance(listing, dict):
        raise ValueError("Survey package needs its actual list metadata")
    survey_content.content.text(listing.get("id"), 4096)
    papers = {}
    for name in ("papers", "cited_papers"):
        rows = tables.get(name, [])
        if not isinstance(rows, list) or len(rows) > survey_content.MAX_MEMBERS:
            raise ValueError("Survey package paper context exceeds its collection bound")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Survey package paper context is invalid")
            survey_content.content.text(row.get("id"), 4096)
            survey_content.content.text(row.get("title"), 2000)
            if row["id"] in papers:
                raise ValueError("Survey package paper context is repeated")
            papers[row["id"]] = row
    actual = {}
    portable = None
    if reports:
        record = reports[0]
        closed(record, {"list_id", "report_id", "path", "sha256", "size", "media_type"})
        if (
            record["list_id"] != manifest["list"]["id"]
            or record["path"] != relative(record["list_id"], record["report_id"]).as_posix()
            or record["media_type"] != "application/json"
        ):
            raise ValueError("Survey package report belongs to another list/path")
        raw = _read(
            archive,
            record["path"],
            record["sha256"],
            record["size"],
            MAX_PACKAGE_BODY,
        )
        actual[record["path"]] = record["sha256"]
        portable = read_json(raw)
        closed(portable, {"format", "list_id", "report", "bindings"})
        report = survey_content.validate(portable["report"])
        if (
            portable["format"] != FORMAT
            or portable["list_id"] != record["list_id"]
            or report["id"] != record["report_id"]
        ):
            raise ValueError("Survey package report identity differs")
        captured = [source for source in report["sources"] if source["state"] == "captured"]
        bindings = portable["bindings"]
        if (
            not isinstance(bindings, list)
            or len(bindings) != len(captured)
            or len(declared) != len(captured)
        ):
            raise ValueError("Survey package omits or adds selected source owners")
        owners, total = set(), 0
        for source, binding, item in zip(captured, bindings, declared, strict=True):
            _cancel(cancelled)
            closed(binding, {"source_id", "paper_id"})
            closed(item, {"source_id", "paper_id", "sha256", "size", "path"})
            paper = binding["paper_id"]
            if (
                not isinstance(paper, str)
                or paper not in papers
                or paper in owners
                or binding["source_id"] != source["id"]
                or item["source_id"] != source["id"]
                or item["paper_id"] != paper
                or item["sha256"] != source["document_hash"]
                or item["path"]
                != source_relative(record["list_id"], paper, item["sha256"]).as_posix()
            ):
                raise ValueError("Survey package source owner/hash/path differs")
            owners.add(paper)
            data = _read(archive, item["path"], item["sha256"], item["size"], MAX_PDF_BYTES)
            total += len(data)
            if total > MAX_PDF_BYTES:
                raise ValueError("Survey package originals exceed aggregate bounds")
            verify_original(data, source, report, cancelled=cancelled)
            actual[item["path"]] = item["sha256"]
    expected = {
        item.filename.removeprefix("files/")
        for item in infos
        if item.filename.casefold().startswith(("files/survey-reports/", "files/survey-sources/"))
        or item.filename.casefold() in {"files/survey-reports", "files/survey-sources"}
    }
    if expected != set(actual) or any(
        manifest.get("file_hashes", {}).get(path) != sha for path, sha in actual.items()
    ):
        raise ValueError("Survey package member/hash inventory differs")
    _cancel(cancelled)
    return portable
