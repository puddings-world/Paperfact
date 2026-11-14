"""Source-complete Lineage list packages; synchronized import remains gated.

Portable scientific rows and PDF bytes are data, never sender device/lifecycle or
publication authority. The caller owns the list selection and final publication.
Unbound bundles use native receiver ownership; bound imports need compound enrollment.
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

from paper_daily import (
    claim_content,
    lineage_bound_originals,
    lineage_originals,
    lineage_read_projection,
    lineage_sets,
    research_evidence,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import _readonly_connection, observe_owner

TABLE = lineage_sets.TABLE
CAPABILITY = "lineage"
MAX_REPORTS = 128
MAX_PAPERS = 500
MAX_PDF_BYTES = 32 * 1024**2
MAX_METADATA = 8 * 1024**2
MAX_TOTAL = 512 * 1024**2
MAX_FILES = 4096
MAX_TOTAL_PAGES = 4096
_KEY = secrets.token_bytes(32)


def _json(value):
    result = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(result.encode()) > MAX_METADATA:
        raise ValueError("Lineage package metadata exceeds its budget")
    return result


def relative(focal_id, paper_id, sha):
    claim_content.text(focal_id, 4096)
    claim_content.text(paper_id, 4096)
    claim_content.digest(sha)
    return (
        Path("lineage-sources")
        / claim_content.hashed(["lineage-focal", focal_id])[:24]
        / claim_content.hashed(["lineage-source-owner", paper_id])[:24]
        / (sha + ".pdf")
    )


def _selection(paper_ids):
    if not isinstance(paper_ids, (tuple, list)) or len(paper_ids) > MAX_PAPERS:
        raise ValueError("Lineage package needs a bounded explicit paper selection")
    for paper in paper_ids:
        claim_content.text(paper, 4096)
    return tuple(sorted(set(paper_ids)))


def _snapshot(database, selection):
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        reports = []
        if selection and lineage_read_projection.present(conn):
            raw = conn.execute(
                "SELECT paper_id,corpus_key,CASE WHEN length(CAST(body_json AS BLOB))<=? "
                "THEN body_json END,source_hash,document_hash,written_at FROM paper_lineage_sets "
                "WHERE paper_id IN (" + ",".join("?" for _ in selection) + ") "
                "ORDER BY paper_id,corpus_key LIMIT ?",
                (lineage_sets.MAX_BYTES, *selection, MAX_REPORTS + 1),
            )
            for item in raw:
                reports.append(
                    lineage_sets.validate_row(
                        dict(zip(lineage_sets.COLUMNS.split(), item, strict=True))
                    )
                )
                _json(reports)
            if len(reports) > MAX_REPORTS:
                raise ValueError("Too many Lineage reports for one package")
        ids = sorted(
            set(selection)
            | {
                b["paper_id"]
                for row in reports
                for b in lineage_sets.decode(row["body_json"])["bindings"]
            }
        )
        if len(ids) > MAX_PAPERS:
            raise ValueError("Lineage selected/context papers exceed their package budget")
        papers = []
        if ids:
            # Bound the complete rows before loading potentially large native metadata.
            fields = [
                '"' + row[1].replace('"', '""') + '"'
                for row in conn.execute("PRAGMA table_info(papers)")
            ]
            marks = ",".join("?" for _ in ids)
            lengths = "+".join("COALESCE(length(CAST(" + key + " AS BLOB)),0)" for key in fields)
            size = conn.execute(
                "SELECT COALESCE(SUM(" + lengths + "),0) FROM papers WHERE id IN (" + marks + ")",
                ids,
            ).fetchone()[0]
            if size > MAX_METADATA:
                raise ValueError("Lineage context metadata exceeds its package budget")
            papers = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM papers WHERE id IN (" + marks + ") ORDER BY id", ids
                )
            ]
            if {p["id"] for p in papers} != set(ids):
                raise ValueError("Lineage package lacks an actual selected/context paper")
        return _json(dict(binding=generation._binding(conn), reports=reports, papers=papers))


def _signature(database, native, selection, observed, sources, proofs, files):
    value = [
        str(database),
        native,
        selection,
        observed,
        sources,
        [[kind, id(proof)] for kind, proof in proofs],
        [[name, id(data)] for name, data in files],
        os.getpid(),
    ]
    # A native signature is private process state, not a package field.
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new(_KEY, raw, "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class LineageExport:
    database: Path = field(repr=False)
    _native: tuple = field(repr=False)
    _selection: tuple = field(repr=False)
    _observed: str = field(repr=False)
    _sources: str = field(repr=False)
    _proofs: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def rows(self):
        return json.loads(self._observed)["reports"]

    @property
    def papers(self):
        return json.loads(self._observed)["papers"]

    @property
    def records(self):
        return json.loads(self._sources)

    @property
    def files(self):
        return tuple((Path(name), data) for name, data in self._files)


def check_export(prepared):
    """Metadata/native proof check at final package publication; no hashing or writes."""
    if prepared is None:
        return
    if not isinstance(prepared, LineageExport) or not isinstance(prepared._seal, str):
        raise ValueError("Lineage package requires its native observed export")
    expected = _signature(
        prepared.database,
        prepared._native,
        prepared._selection,
        prepared._observed,
        prepared._sources,
        prepared._proofs,
        prepared._files,
    )
    if not hmac.compare_digest(prepared._seal, expected):
        raise ValueError("Lineage package requires its native observed export")
    if (
        tuple(generation._identity(prepared.database)) != prepared._native
        or _snapshot(prepared.database, prepared._selection) != prepared._observed
    ):
        raise ValueError("Lineage research/context changed during package export")
    for kind, snapshot in prepared._proofs:
        if kind == "import":
            from paper_daily import lineage_import_originals

            reader = lineage_import_originals
        else:
            reader = lineage_bound_originals if kind == "bound" else lineage_originals
        if not reader.metadata_current(snapshot):
            raise ValueError("Lineage original ownership changed during package export")


def collect(database, paper_ids, *, with_pdfs=True, cancelled=lambda: False):
    """Worker-only source-complete observation, including context outside list membership."""
    _worker()
    selection = _selection(paper_ids)
    if type(with_pdfs) is not bool:
        raise ValueError("Lineage package PDF choice must be explicit")
    if cancelled():
        raise ValueError("Lineage package export cancelled")
    database = Path(database).resolve(strict=True)
    native = tuple(generation._identity(database))
    observed = _snapshot(database, selection)
    state = json.loads(observed)
    if not state["reports"]:
        return None
    if not with_pdfs:
        raise ValueError("Include exact originals to share Lineage research")
    sources, proofs, files = [], [], {}
    retained_bytes = 0
    for row in state["reports"]:
        from paper_daily import lineage_import_originals, lineage_source_reader

        owner = observe_owner(database, row["paper_id"], expected_native=native)
        with closing(_readonly_connection(database)) as conn:
            conn.execute("BEGIN")
            reader = lineage_source_reader.reader_in(conn, owner, row)
        kind = (
            "bound" if reader is lineage_bound_originals
            else "import" if reader is lineage_import_originals else "local"
        )
        body = lineage_sets.decode(row["body_json"])
        for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
            if cancelled():
                raise ValueError("Lineage package export cancelled")
            if source["availability"] == "unavailable":
                continue
            snapshot = reader.prepare(owner, row, source["id"], cancelled=cancelled)
            if snapshot is None:
                raise ValueError("Lineage exact original is unavailable or export was cancelled")
            data = reader.for_delivery(snapshot, owner, row, source["id"])
            if not 0 < len(data) <= MAX_PDF_BYTES:
                raise ValueError("Lineage original exceeds its PDF byte budget")
            retained_bytes += len(data)
            if retained_bytes > MAX_TOTAL:
                raise ValueError("Lineage native byte proofs exceed the export memory budget")
            path = relative(
                row["paper_id"], binding["paper_id"], source["document_hash"]
            ).as_posix()
            if path not in files and sum(map(len, files.values())) + len(data) > MAX_TOTAL:
                raise ValueError("Lineage originals exceed the package byte budget")
            if path in files and files[path] != data:
                raise ValueError("Lineage original path has conflicting bytes")
            files[path] = data
            sources.append(
                dict(
                    focal_paper_id=row["paper_id"],
                    corpus_key=row["corpus_key"],
                    source_id=source["id"],
                    paper_id=binding["paper_id"],
                    sha256=source["document_hash"],
                    size=len(data),
                    path=path,
                )
            )
            proofs.append((kind, snapshot))
    if cancelled():
        raise ValueError("Lineage package export cancelled")
    encoded = _json(sources)
    proofs, files = tuple(proofs), tuple(files.items())
    prepared = LineageExport(
        database,
        native,
        selection,
        observed,
        encoded,
        proofs,
        files,
        _signature(database, native, selection, observed, encoded, proofs, files),
    )
    check_export(prepared)
    return prepared


def _metadata(archive, name):
    matches = [i for i in archive.infolist() if i.filename == name]
    if len(matches) != 1 or not 0 < matches[0].file_size <= MAX_METADATA:
        raise ValueError("Lineage package requires one bounded metadata document")
    with archive.open(matches[0]) as stream:
        data = stream.read(matches[0].file_size + 1)
    if len(data) != matches[0].file_size:
        raise ValueError("Lineage package metadata changed during read")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate Lineage package metadata field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Nonfinite Lineage package metadata value")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid bounded Lineage package metadata") from exc
    if not isinstance(value, dict):
        raise ValueError("Lineage package metadata must be an object")
    return value


def records(manifest, tables):
    """Closed ordered content/source declarations; no receiver ownership is inferred."""
    selected = tables.get(TABLE, [])
    if not isinstance(selected, list) or len(selected) > MAX_REPORTS:
        raise ValueError("Invalid bounded Lineage report collection")
    papers, seen, expected = {}, set(), []
    for name in ("papers", "cited_papers"):
        values = tables.get(name, [])
        if not isinstance(values, list):
            raise ValueError("Lineage package paper context must be a collection")
        for paper in values:
            if not isinstance(paper, dict):
                raise ValueError("Invalid Lineage paper context")
            pid = paper.get("id")
            claim_content.text(pid, 4096)
            claim_content.text(paper.get("title"), 2000)
            if pid in papers or len(papers) >= MAX_PAPERS:
                raise ValueError("Duplicate or excessive Lineage context paper")
            papers[pid] = paper
    members = {p["id"] for p in tables.get("papers", [])}
    for row in selected:
        lineage_sets.validate_row(row)
        key = row["paper_id"], row["corpus_key"]
        if key in seen or row["paper_id"] not in members:
            raise ValueError("Lineage focal owner is repeated or outside the shared list")
        seen.add(key)
        body = lineage_sets.decode(row["body_json"])
        for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
            if binding["paper_id"] not in papers:
                raise ValueError("Lineage package omits a selected context paper")
            if source["availability"] == "available":
                expected.append(
                    dict(
                        focal_paper_id=row["paper_id"],
                        corpus_key=row["corpus_key"],
                        source_id=source["id"],
                        paper_id=binding["paper_id"],
                        sha256=source["document_hash"],
                    )
                )
    actual = manifest.get("lineage_sources", [])
    caps = manifest.get("capabilities", [])
    if (
        not isinstance(caps, list)
        or any(not isinstance(cap, str) for cap in caps)
        or caps != sorted(set(caps))
        or (CAPABILITY in caps) != bool(selected)
        or (
            selected
            and (
                type(manifest.get("format")) is not int
                or manifest.get("format") != 2
                or manifest.get("pdfs_included") is not True
            )
        )
    ):
        raise ValueError("Lineage package requires its exact capability and included originals")
    if (
        not isinstance(actual, list)
        or len(actual) != len(expected)
        or (not expected and "lineage_sources" in manifest)
    ):
        raise ValueError("Lineage package original closure differs from its selected reports")
    sizes, total = {}, 0
    for item, needed in zip(actual, expected, strict=True):
        claim_content.closed(item, {*needed, "size", "path"})
        if any(item[k] != v for k, v in needed.items()):
            raise ValueError("Lineage original owner/corpus/source differs")
        claim_content.number(item["size"], MAX_PDF_BYTES, 1)
        if (
            item["path"]
            != relative(item["focal_paper_id"], item["paper_id"], item["sha256"]).as_posix()
        ):
            raise ValueError("Lineage original path differs from its exact source owner")
        prior = sizes.get(item["path"])
        if prior is None:
            sizes[item["path"]] = item["size"]
            total += item["size"]
        elif prior != item["size"]:
            raise ValueError("Lineage original size has conflicting declarations")
        if total > MAX_TOTAL:
            raise ValueError("Lineage originals exceed aggregate package bounds")
    return selected, actual


def validate_package(archive, manifest, tables, *, cancelled=lambda: False):
    """Validate actual ZIP metadata, byte closure, PDF pages and every located quote.

    This staged codec grants no write, import, source or replay authority. The
    eventual caller must also run the common list-package validation and perform
    observed receiver mapping/publication, never copy sender-native receipts.
    """
    if cancelled():
        raise ValueError("Lineage package validation cancelled")
    infos = archive.infolist()
    if len(infos) > MAX_FILES or len({i.filename.casefold() for i in infos}) != len(infos):
        raise ValueError("Lineage package archive members are repeated or excessive")
    actual_manifest, actual_tables = (
        _metadata(archive, "manifest.json"),
        _metadata(archive, "tables.json"),
    )
    if _json(actual_manifest) != _json(manifest) or _json(actual_tables) != _json(tables):
        raise ValueError("Lineage package differs from the admitted metadata")
    selected, sources = records(actual_manifest, actual_tables)
    owned = {item["path"]: item for item in sources}
    actual_paths = {
        i.filename.removeprefix("files/")
        for i in infos
        if i.filename.startswith("files/lineage-sources/")
    }
    if actual_paths != set(owned):
        raise ValueError("Lineage package has missing or undeclared source files")
    usages = {}
    for row in selected:
        body = lineage_sets.decode(row["body_json"])
        for source in body["report"]["sources"]:
            if source["availability"] == "available":
                usages.setdefault(source["document_hash"], []).append((body["report"], source))
    verified, pages_seen = set(), 0
    hashes = actual_manifest.get("file_hashes", {})
    if not isinstance(hashes, dict):
        raise ValueError("Lineage package lacks its exact source hashes")
    for path, item in owned.items():
        if cancelled():
            raise ValueError("Lineage package validation cancelled")
        if hashes.get(path) != item["sha256"]:
            raise ValueError("Lineage original lacks its declared file hash")
        info = archive.getinfo("files/" + path)
        if info.file_size != item["size"]:
            raise ValueError("Lineage original file size differs")
        with archive.open(info) as stream:
            data = stream.read(item["size"] + 1)
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Lineage original PDF bytes differ")
        if item["sha256"] in verified:
            continue
        pages_seen += verify_original(
            data, item["sha256"], usages[item["sha256"]], cancelled=cancelled
        )
        if pages_seen > MAX_TOTAL_PAGES:
            raise ValueError("Lineage package exceeds its original-page budget")
        verified.add(item["sha256"])
    if cancelled():
        raise ValueError("Lineage package validation cancelled")
    return selected


def verify_original(data, digest, usages, *, cancelled=lambda: False):
    """Verify a single original and all located uses; caller owns aggregate limits."""
    claim_content.digest(digest)
    if (
        not isinstance(data, bytes) or not 0 < len(data) <= MAX_PDF_BYTES
        or hashlib.sha256(data).hexdigest() != digest
    ):
        raise ValueError("Lineage original PDF bytes differ")
    if cancelled():
        raise ValueError("Lineage original verification cancelled")
    pages, indexes, whole = research_evidence._extract(data, cancelled)
    for report, source in usages:
        if source["document_hash"] != digest or len(pages) != source["page_count"]:
            raise ValueError("Lineage original page count differs from its report")
        for statement in report["statements"]:
            for passage in statement["passages"]:
                if (
                    passage["source_id"] != source["id"]
                    or passage["location"]["state"] != "located"
                ):
                    continue
                if cancelled():
                    raise ValueError("Lineage original verification cancelled")
                proposed = dict(
                    quote=passage["quote"], page=passage["location"]["page"],
                    anchor=passage["location"]["anchor"],
                )
                if (
                    research_evidence._locate(proposed, pages, indexes, whole)
                    != passage["location"]
                ):
                    raise ValueError("Lineage located quote does not match its exact original")
    return len(pages)
