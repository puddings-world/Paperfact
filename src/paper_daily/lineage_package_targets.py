"""Observed receiver mappings for staged Lineage packages; grants no import authority.

The receiver chooses explicit existing paper owners. PDF verification runs before
SQL observation, and the caller rechecks this lease in its final transaction.
Scientific content is unchanged except for the local paper bindings. Source
publication and compound sync admission remain separate required boundaries.
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

from paper_daily import claim_content, lineage_packages, lineage_sets
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.workspace_service import _binding, _tables

_KEY = secrets.token_bytes(32)


def _seal(encoded):
    return hmac.new(
        _KEY, lineage_packages._json([encoded, os.getpid()]).encode(), "sha256"
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Targets:
    _json: str = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def rows(self):
        return checked(self)["rows"]

    @property
    def paper_map(self):
        return checked(self)["paper_map"]

    @property
    def sources(self):
        """Original archive descriptors; paths and sender owners are not rewritten."""
        return checked(self)["sources"]

    @property
    def before(self):
        return checked(self)["observed"]["targets"]

    @property
    def conflicts(self):
        return [
            {"incoming": row, "receiver": before}
            for row, before in zip(self.rows, self.before, strict=True)
            if before is not None and before != row
        ]


def checked(prepared):
    if not isinstance(prepared, Targets) or not hmac.compare_digest(
        prepared._seal, _seal(prepared._json)
    ):
        raise ValueError("Lineage targets require their native observed mapping")
    return json.loads(prepared._json)


def _mapping(rows, paper_map):
    ids = {b["paper_id"] for row in rows for b in lineage_sets.decode(row["body_json"])["bindings"]}
    if not isinstance(paper_map, dict) or set(paper_map) != ids:
        raise ValueError("Lineage requires an explicit complete receiver paper mapping")
    for value in paper_map.values():
        claim_content.text(value, 4096)
    if len(set(paper_map.values())) != len(ids):
        raise ValueError("Lineage selected papers cannot share a receiver owner")
    result = []
    for incoming in rows:
        body = lineage_sets.decode(incoming["body_json"])
        for binding in body["bindings"]:
            binding["paper_id"] = paper_map[binding["paper_id"]]
        row = dict(incoming, paper_id=paper_map[incoming["paper_id"]])
        row["body_json"] = lineage_sets.canonical(body)
        result.append(lineage_sets.validate_row(row))
    return result


def _target_rows(conn, rows):
    kind = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,)
    ).fetchone()
    if kind is None:
        return [None for _ in rows]
    columns = [r[1] for r in conn.execute("PRAGMA table_info(paper_lineage_sets)")]
    if tuple(kind) != ("table",) or columns != lineage_sets.COLUMNS.split():
        raise ValueError("Lineage receiver requires its stored research table")
    result = []
    for row in rows:
        raw = conn.execute(
            "SELECT paper_id,corpus_key,CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END,source_hash,document_hash,written_at "
            "FROM paper_lineage_sets WHERE paper_id=? AND corpus_key=?",
            (lineage_sets.MAX_BYTES, row["paper_id"], row["corpus_key"]),
        ).fetchone()
        result.append(
            None
            if raw is None
            else lineage_sets.validate_row(
                dict(zip(lineage_sets.COLUMNS.split(), raw, strict=True))
            )
        )
    return result


def _read_in(conn, rows, paper_map):
    tables = _tables(conn)
    if generation._binding(conn) is not None or _binding(conn, tables):
        raise ValueError("Lineage synchronized imports require compound source admission")
    ids = sorted(paper_map.values())
    fields = [r[1] for r in conn.execute("PRAGMA table_info(papers)")]
    quoted = ['"' + f.replace('"', '""') + '"' for f in fields]
    marks = ",".join("?" for _ in ids)
    lengths = "+".join("COALESCE(length(CAST(" + f + " AS BLOB)),0)" for f in quoted)
    size = conn.execute(
        "SELECT COALESCE(SUM(" + lengths + "),0) FROM papers WHERE id IN (" + marks + ")",
        ids,
    ).fetchone()[0]
    if size > lineage_packages.MAX_METADATA:
        raise ValueError("Lineage receiver metadata exceeds its observation budget")
    papers = [
        dict(zip(fields, r, strict=True))
        for r in conn.execute(
            "SELECT " + ",".join(quoted) + " FROM papers WHERE id IN (" + marks + ") ORDER BY id",
            ids,
        )
    ]
    if {p["id"] for p in papers} != set(ids):
        raise ValueError("Lineage receiver paper is missing; complete identity matching first")
    parents = [(p, parent_lifecycle(conn, "paper", p)) for p in ids]
    if any(not token for _p, token in parents):
        raise ValueError("Lineage receiver needs existing native paper lifetimes")
    result = dict(papers=papers, parents=parents, targets=_target_rows(conn, rows))
    lineage_packages._json(result)
    return result


def observe(database, archive, manifest, tables, paper_map, *, cancelled=lambda: False):
    """Validate actual package bytes and observe explicit existing receiver owners.

    No schema, source receipt, file, journal or research row is written. The
    normal package importer must first resolve/create paper identities within
    its own transaction workflow; this component does not match titles or DOI.
    Existing conflicting rows are returned for review rather than overwritten.
    """
    _worker()
    if cancelled():
        raise ValueError("Lineage target observation cancelled")
    # Own JSON input values before delayed validation/observation. Caller-owned
    # dictionaries may still be edited by a different view while this worker runs.
    manifest = json.loads(lineage_packages._json(manifest))
    tables = json.loads(lineage_packages._json(tables))
    if not isinstance(paper_map, dict):
        raise ValueError("Lineage requires an explicit complete receiver paper mapping")
    paper_map = dict(paper_map)
    incoming = lineage_packages.validate_package(archive, manifest, tables, cancelled=cancelled)
    rows = _mapping(incoming, paper_map)
    if not rows:
        return None
    database = Path(database).resolve(strict=True)
    native = generation._identity(database)
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        observed = _read_in(conn, rows, paper_map)
        if generation._identity(database) != native:
            raise ValueError("Lineage receiver database changed during observation")
    if cancelled():
        raise ValueError("Lineage target observation cancelled")
    data = dict(
        database=str(database),
        native=native,
        observed=observed,
        paper_map=paper_map,
        rows=rows,
        sources=lineage_packages.records(manifest, tables)[1],
    )
    encoded = lineage_packages._json(data)
    return Targets(encoded, _seal(encoded))


def check_in(conn, prepared):
    """Recheck native target/parent state in the caller transaction; never commit.

    This is an optimistic target lease, not permission to adopt PDF bytes or
    write a report. A source-preserving importer must perform those boundaries
    separately in the same caller transaction after this check.
    """
    if prepared is None or not conn.in_transaction:
        raise ValueError("Lineage target check requires an observed caller transaction")
    data = checked(prepared)
    if (
        generation._path(conn) != data["database"]
        or generation._identity(Path(data["database"])) != data["native"]
        or lineage_packages._json(_read_in(conn, data["rows"], data["paper_map"]))
        != lineage_packages._json(data["observed"])
    ):
        raise ValueError("Lineage receiver changed; review the package mapping again")
    return prepared.rows


@dataclass(frozen=True, slots=True)
class ValidatedPackage:
    """Process-local byte-validated scientific metadata, never source ownership."""

    _json: str = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def files(self):
        _validated(self)
        return self._files


def _validation_seal(encoded, files):
    if not isinstance(files, tuple) or any(
        not isinstance(pair, tuple)
        or len(pair) != 2
        or not isinstance(pair[0], str)
        or not isinstance(pair[1], bytes)
        for pair in files
    ):
        raise ValueError("Lineage import requires its native validated package data")
    value = lineage_packages._json(
        [
            "lineage-package-data",
            encoded,
            [(path, id(data), len(data)) for path, data in files],
            os.getpid(),
        ]
    )
    return hmac.new(_KEY, value.encode(), "sha256").hexdigest()


def _validated(prepared):
    if not isinstance(prepared, ValidatedPackage) or not hmac.compare_digest(
        prepared._seal, _validation_seal(prepared._json, prepared._files)
    ):
        raise ValueError("Lineage import requires its native validated package data")
    return json.loads(prepared._json)


def validate(archive, manifest, tables, *, cancelled=lambda: False):
    """Verify real ZIP/PDF content off-lock for a later caller-owned transaction.

    Retain immutable exact PDF bytes with defensive scientific/source metadata.
    This creates no paper identity, file, source ownership or import grant. A
    source publisher must use these pinned bytes rather than reopen the archive.
    The normal list-package validator is also required.
    """
    _worker()
    if cancelled():
        raise ValueError("Lineage package validation cancelled")
    manifest = json.loads(lineage_packages._json(manifest))
    tables = json.loads(lineage_packages._json(tables))
    rows = lineage_packages.validate_package(archive, manifest, tables, cancelled=cancelled)
    sources = lineage_packages.records(manifest, tables)[1]
    files, retained = [], {}
    for path, descriptor in {item["path"]: item for item in sources}.items():
        if cancelled():
            raise ValueError("Lineage package validation cancelled")
        with archive.open("files/" + path) as stream:
            data = stream.read(descriptor["size"] + 1)
        if (
            len(data) != descriptor["size"]
            or hashlib.sha256(data).hexdigest() != descriptor["sha256"]
        ):
            raise ValueError("Lineage original changed before byte retention")
        data = retained.setdefault(descriptor["sha256"], data)
        files.append((path, data))
    if cancelled():
        raise ValueError("Lineage package validation cancelled")
    encoded = lineage_packages._json(dict(rows=rows, sources=sources))
    files = tuple(files)
    return ValidatedPackage(encoded, files, _validation_seal(encoded, files))


def observe_in(conn, package, paper_map, *, expected_native, cancelled=lambda: False):
    """Observe receiver rows, including new uncommitted owners, without committing.

    The caller captures expected_native before opening its connection. It owns
    paper matching/creation and lifecycle initialization in the same transaction.
    No archive/PDF parsing, source-file publication or SQL write occurs here.
    Cancellation/failure leaves earlier caller work uncommitted for its caller.
    """
    _worker()
    if not conn.in_transaction:
        raise ValueError("Lineage receiver observation requires a caller transaction")
    if cancelled():
        raise ValueError("Lineage target observation cancelled")
    content = _validated(package)
    if not isinstance(paper_map, dict):
        raise ValueError("Lineage requires an explicit complete receiver paper mapping")
    paper_map = dict(paper_map)
    rows = _mapping(content["rows"], paper_map)
    if not rows:
        return None
    database = Path(generation._path(conn))
    native = list(expected_native) if isinstance(expected_native, (tuple, list)) else []
    if (
        len(native) != 2
        or any(type(n) is not int or n < 0 for n in native)
        or generation._identity(database) != native
    ):
        raise ValueError("Lineage receiver database changed before observation")
    observed = _read_in(conn, rows, paper_map)
    if generation._identity(database) != native:
        raise ValueError("Lineage receiver database changed during observation")
    if cancelled():
        raise ValueError("Lineage target observation cancelled")
    encoded = lineage_packages._json(
        dict(
            database=str(database),
            native=native,
            observed=observed,
            paper_map=paper_map,
            rows=rows,
            sources=content["sources"],
        )
    )
    return Targets(encoded, _seal(encoded))



def validate_selected(row, originals, *, cancelled=lambda: False):
    """Worker-only exact PDF proof for a saved-row adoption, not a list import.

    The caller must independently observe the current saved row and real native
    paper lifetimes. This returns scientific/byte data, never publication authority.
    Unlike validate(), no generic list/archive metadata is admitted here.
    """
    _worker()
    row = lineage_sets.validate_row(json.loads(lineage_packages._json(row)))
    body = lineage_sets.decode(row["body_json"])
    available = {
        source["id"] for source in body["report"]["sources"]
        if source["availability"] == "available"
    }
    if not isinstance(originals, dict) or set(originals) != available:
        raise ValueError("Select every exact available original, with no additional source")
    sources, files, total, pages = [], [], 0, 0
    for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
        if cancelled():
            raise ValueError("Saved Lineage original verification cancelled")
        if source["availability"] != "available":
            continue
        data = originals[source["id"]]
        total += len(data) if isinstance(data, bytes) else 0
        if total > lineage_packages.MAX_TOTAL:
            raise ValueError("Selected originals exceed the byte budget")
        pages += lineage_packages.verify_original(
            data, source["document_hash"], [(body["report"], source)], cancelled=cancelled)
        if pages > lineage_packages.MAX_TOTAL_PAGES:
            raise ValueError("Selected originals exceed the aggregate page budget")
        relative = lineage_packages.relative(
            row["paper_id"], binding["paper_id"], source["document_hash"]).as_posix()
        sources.append(dict(focal_paper_id=row["paper_id"], corpus_key=row["corpus_key"],
                            source_id=source["id"], paper_id=binding["paper_id"],
                            sha256=source["document_hash"], size=len(data), path=relative))
        files.append((relative, data))
    encoded = lineage_packages._json(dict(rows=[row], sources=sources))
    files = tuple(files)
    return ValidatedPackage(encoded, files, _validation_seal(encoded, files))
