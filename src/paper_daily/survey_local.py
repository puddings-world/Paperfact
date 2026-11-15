"""Local-only saved survey versions and exact imported-original associations.

No enrollment, sender authority or fabricated AI request is introduced. The bundle
transaction owns parent creation, source grants and current-version selection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import (
    file_change,
    source_snapshots,
    survey_content,
    survey_package_native,
    survey_packages,
)
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation
from paper_daily.lineage_package_publish import _stage_file
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.sync_files import canonical_json, closed, descriptor, digest
from paper_daily.workspace_service import _binding, _tables

TABLE = "research_local_surveys"
COLUMNS = "version_id list_id body_json is_current"
FORMAT = "paperfact.local-survey.v1"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_local_surveys("
    "version_id TEXT PRIMARY KEY,list_id TEXT NOT NULL,body_json TEXT NOT NULL,"
    "is_current INTEGER NOT NULL CHECK(is_current IN(0,1)))"
)
MAX_HISTORY = 32 * 1024**2
MAX_VERSIONS = 1000
_KEY = secrets.token_bytes(32)


def _json(value):
    return canonical_json(value).decode()


def _schema(conn):
    if TABLE not in _tables(conn):
        return False
    info = list(conn.execute("PRAGMA table_info(" + TABLE + ")"))
    if (
        [r[1] for r in info] != COLUMNS.split()
        or [r[2].upper() for r in info] != ["TEXT", "TEXT", "TEXT", "INTEGER"]
        or [r[5] for r in info] != [1, 0, 0, 0]
    ):
        raise ValueError("Local survey schema requires review")
    return True


def _receipt(body, source, paper, lifecycle, size):
    owner = dict(
        format="paperfact.source-owner.v1",
        database_identity=body["database_identity"],
        binding=None,
        paper_id=paper,
        parent_lifecycle=lifecycle,
        source_owner_id=paper,
    )
    key = hashlib.sha256(
        canonical_json(
            [
                FORMAT,
                body["list_id"],
                body["list_lifecycle"],
                body["report"]["id"],
                source["id"],
                owner,
            ]
        )
    ).hexdigest()
    return owners.validate(
        dict(
            request_id="import:" + key,
            owner_json=_json(owner),
            sha256=source["document_hash"],
            size=size,
            media_type="application/pdf",
        )
    )


def validate_record(row):
    """Validate retained content only; never a grant on another database/device."""
    closed(row, COLUMNS.split())
    digest(row["version_id"])
    if (
        not isinstance(row["body_json"], str)
        or len(row["body_json"].encode()) > survey_packages.MAX_PACKAGE_BODY
        or type(row["is_current"]) is not int
        or row["is_current"] not in (0, 1)
    ):
        raise ValueError("Invalid bounded local survey version")
    body = json.loads(row["body_json"])
    closed(body, {"format", "database_identity", "list_id", "list_lifecycle", "report", "bindings"})
    survey_content.content.text(body["list_id"], 4096)
    token = body["list_lifecycle"]
    if (
        body["format"] != FORMAT
        or row["list_id"] != body["list_id"]
        or not isinstance(token, str)
        or len(token) != 32
        or any(c not in "0123456789abcdef" for c in token)
    ):
        raise ValueError("Invalid local survey list lifetime")
    native = body["database_identity"]
    if (
        not isinstance(native, list)
        or len(native) != 2
        or any(type(n) is not int or n < 0 for n in native)
    ):
        raise ValueError("Invalid local survey database observation")
    report = survey_content.validate(body["report"])
    captured = [s for s in report["sources"] if s["state"] == "captured"]
    if not isinstance(body["bindings"], list) or len(body["bindings"]) != len(captured):
        raise ValueError("Local survey needs all exact original bindings")
    seen = set()
    for source, binding in zip(captured, body["bindings"], strict=True):
        closed(binding, {"source_id", "paper_id", "parent_lifecycle", "original"})
        paper = binding["paper_id"]
        survey_content.content.text(paper, 4096)
        original = owners.validate(binding["original"])
        if (
            binding["source_id"] != source["id"]
            or paper in seen
            or original
            != _receipt(body, source, paper, binding["parent_lifecycle"], original["size"])
        ):
            raise ValueError("Local survey original differs from its actual receiver owner")
        seen.add(paper)
    if (
        _json(body) != row["body_json"]
        or hashlib.sha256(canonical_json(body)).hexdigest() != row["version_id"]
    ):
        raise ValueError("Local survey version digest differs")
    return body


def current_in(conn, list_id):
    if not _schema(conn):
        return None
    rows = list(
        conn.execute(
            "SELECT version_id,list_id,CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END,is_current FROM "
            + TABLE
            + " WHERE list_id=? AND is_current=1 LIMIT 2",
            (survey_packages.MAX_PACKAGE_BODY, list_id),
        )
    )
    if len(rows) > 1:
        raise ValueError("Local survey has multiple current versions")
    if not rows:
        return None
    row = dict(zip(COLUMNS.split(), rows[0], strict=True))
    validate_record(row)
    return row


def _bounded_rows(conn, table, identities):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")]
    lengths = "+".join(
        'COALESCE(length(CAST("' + key.replace('"', '""') + '" AS BLOB)),0)' for key in columns
    )
    result, total = [], 0
    for identity in identities:
        size = conn.execute(
            "SELECT " + lengths + " FROM " + table + " WHERE id=?", (identity,)
        ).fetchone()
        if size is None:
            result.append(None)
            continue
        total += size[0]
        if total > survey_packages.MAX_METADATA:
            raise ValueError("Local survey paper context exceeds its bound")
        row = conn.execute("SELECT * FROM " + table + " WHERE id=?", (identity,)).fetchone()
        result.append(dict(row))
    return result


def _snapshot(conn, list_id, papers):
    if _binding(conn, _tables(conn)) or generation._binding(conn):
        raise ValueError("Local survey storage requires an unbound workspace")
    contexts = _bounded_rows(conn, "papers", papers)
    return dict(
        list=_bounded_rows(conn, "lists", [list_id])[0],
        list_lifecycle=parent_lifecycle(conn, "list", list_id),
        papers=[
            [
                paper,
                parent_lifecycle(conn, "paper", paper),
                hashlib.sha256(canonical_json(row)).hexdigest() if row else None,
            ]
            for paper, row in zip(papers, contexts, strict=True)
        ],
        current=current_in(conn, list_id),
    )


def _seal(encoded, files):
    return hmac.new(_KEY, canonical_json([encoded, files]), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class StagedLocalSurvey:
    _json: str = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: str = field(repr=False)


def checked(value):
    if not isinstance(value, StagedLocalSurvey) or not hmac.compare_digest(
        value._seal, _seal(value._json, value._files)
    ):
        raise ValueError("Local survey import requires its staged receiver proof")
    data = json.loads(value._json)
    if generation._identity(data["database"]) != data["native"]:
        raise ValueError("Local survey receiver database changed")
    for _paper, _sha, path, version, _size in value._files:
        if file_change.version(Path(path)) != version:
            raise ValueError("Local survey staged original changed")
    return data


def stage(database, frame, list_id, paper_map, *, cancelled=lambda: False):
    data = survey_package_native.checked(frame)
    database = Path(database).resolve(strict=True)
    native = generation._identity(database)
    sources = data["sources"]
    if set(paper_map) != {s["paper_id"] for s in sources} or len(set(paper_map.values())) != len(
        paper_map
    ):
        raise ValueError("Local survey needs its complete distinct paper mapping")
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        observed = _snapshot(conn, list_id, sorted(paper_map.values()))
    files = dict(frame.files)
    selected = []
    for item in sources:
        survey_packages._cancel(cancelled)
        selected.append(
            _stage_file(database, paper_map[item["paper_id"]], item, files[item["path"]], cancelled)
        )
    value = dict(
        database=str(database),
        native=native,
        list_id=list_id,
        paper_map=paper_map,
        portable=data["portable"],
        observed=observed,
    )
    encoded = _json(value)
    result = StagedLocalSurvey(encoded, tuple(selected), _seal(encoded, tuple(selected)))
    checked(result)
    return result


def check_targets_in(conn, staged):
    data = checked(staged)
    if generation._path(conn) != data["database"] or _json(
        _snapshot(conn, data["list_id"], sorted(data["paper_map"].values()))
    ) != _json(data["observed"]):
        raise ValueError("Local survey receiver changed during import")


def publish_in(conn, staged, *, replace=False, cancelled=lambda: False):
    data = checked(staged)
    survey_packages._cancel(cancelled)
    if (
        not conn.in_transaction
        or type(replace) is not bool
        or generation._path(conn) != data["database"]
        or _binding(conn, _tables(conn))
        or generation._binding(conn)
    ):
        raise ValueError("Local survey publication needs its unbound caller transaction")
    ensure_lifecycle(conn)
    list_id = data["list_id"]
    life = parent_lifecycle(conn, "list", list_id)
    if life is None:
        raise ValueError("Local survey needs its existing receiver list")
    body = dict(
        format=FORMAT,
        database_identity=data["native"],
        list_id=list_id,
        list_lifecycle=life,
        report=data["portable"]["report"],
        bindings=[],
    )
    files = {(p, sha): (path, version, size) for p, sha, path, version, size in staged._files}
    mapping = {
        b["source_id"]: data["paper_map"][b["paper_id"]] for b in data["portable"]["bindings"]
    }
    for source in body["report"]["sources"]:
        if source["state"] != "captured":
            continue
        paper = mapping[source["id"]]
        token = parent_lifecycle(conn, "paper", paper)
        if token is None:
            raise ValueError("Local survey original has no receiver paper lifetime")
        _path, _version, size = files[paper, source["document_hash"]]
        original = _receipt(body, source, paper, token, size)
        if source_snapshots.source_path(Path(data["database"]), original) != Path(_path):
            raise ValueError("Local survey original path differs from its canonical owner")
        body["bindings"].append(
            dict(source_id=source["id"], paper_id=paper, parent_lifecycle=token, original=original)
        )
    row = dict(
        version_id=hashlib.sha256(canonical_json(body)).hexdigest(),
        list_id=list_id,
        body_json=_json(body),
        is_current=1,
    )
    validate_record(row)
    current = current_in(conn, list_id)
    if current and current["version_id"] == row["version_id"]:
        _current_sources(conn, current, data["native"])
        return dict(state="unchanged", reports=0, report_id=body["report"]["id"])
    if current and not replace:
        return dict(state="preserved", reports=0, report_id=body["report"]["id"])
    conn.execute("SAVEPOINT survey_local_import")
    try:
        conn.execute(SCHEMA)
        conn.execute(owners.SCHEMA)
        count, size = conn.execute(
            "SELECT count(*),COALESCE(sum(length(CAST(body_json AS BLOB))),0) FROM " + TABLE
        ).fetchone()
        if count >= MAX_VERSIONS or size + len(row["body_json"].encode()) > MAX_HISTORY:
            raise ValueError("Local survey history exceeds its bounded storage")
        for binding in body["bindings"]:
            original = binding["original"]
            prior = conn.execute(
                "SELECT "
                + ",".join(owners.COLUMNS.split())
                + " FROM "
                + owners.TABLE
                + " WHERE request_id=?",
                (original["request_id"],),
            ).fetchone()
            if prior and dict(zip(owners.COLUMNS.split(), prior, strict=True)) != original:
                raise ValueError("Local survey original receipt changed")
            if not prior:
                if (
                    conn.execute("SELECT count(*) FROM " + owners.TABLE).fetchone()[0]
                    >= source_snapshots.MAX_RECEIPTS
                ):
                    raise ValueError("Local survey original history exceeds its bound")
                conn.execute(
                    "INSERT INTO " + owners.TABLE + " VALUES(?,?,?,?,?)",
                    [original[k] for k in owners.COLUMNS.split()],
                )
        conn.execute("UPDATE " + TABLE + " SET is_current=0 WHERE list_id=?", (list_id,))
        conn.execute(
            "INSERT INTO "
            + TABLE
            + " VALUES(?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET is_current=1",
            [row[k] for k in COLUMNS.split()],
        )
        checked(staged)
        survey_packages._cancel(cancelled)
        conn.execute("RELEASE survey_local_import")
    except BaseException:
        conn.execute("ROLLBACK TO survey_local_import")
        conn.execute("RELEASE survey_local_import")
        raise
    return dict(state="imported", reports=1, report_id=body["report"]["id"])


def _current_sources(conn, row, native):
    body = validate_record(row)
    if (
        body["database_identity"] != list(native)
        or parent_lifecycle(conn, "list", body["list_id"]) != body["list_lifecycle"]
    ):
        raise ValueError("Local survey requires reviewed reattachment to this list/database")
    for binding in body["bindings"]:
        if parent_lifecycle(conn, "paper", binding["paper_id"]) != binding["parent_lifecycle"]:
            raise ValueError("Local survey original paper lifetime changed")
        original = binding["original"]
        found = (
            conn.execute(
                "SELECT "
                + ",".join(owners.COLUMNS.split())
                + " FROM "
                + owners.TABLE
                + " WHERE request_id=?",
                (original["request_id"],),
            ).fetchone()
            if owners.TABLE in _tables(conn)
            else None
        )
        if not found or dict(zip(owners.COLUMNS.split(), found, strict=True)) != original:
            raise ValueError("Local survey original has no exact receiver association")
    return body


@dataclass(frozen=True, slots=True)
class LocalSurveyExport:
    _json: str = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def record(self):
        return json.loads(self._json)["record"]

    @property
    def sources(self):
        return json.loads(self._json)["sources"]

    @property
    def papers(self):
        return json.loads(self._json)["papers"]

    @property
    def files(self):
        return tuple((Path(name), raw) for name, raw in self._files)


def _export_seal(encoded, files):
    return _seal(encoded, [[name, id(raw)] for name, raw in files])


def check_export(value):
    if not isinstance(value, LocalSurveyExport) or not hmac.compare_digest(
        value._seal, _export_seal(value._json, value._files)
    ):
        raise ValueError("Local survey export needs its checked capture")
    data = json.loads(value._json)
    if generation._identity(data["database"]) != data["native"]:
        raise ValueError("Local survey export database changed")
    with closing(_readonly_connection(data["database"])) as conn:
        conn.execute("BEGIN")
        observed = _snapshot(conn, data["record"]["list_id"], [r["id"] for r in data["papers"]])
        if _json(observed) != _json(data["observed"]):
            raise ValueError("Local survey or receiver originals changed during export")
        _current_sources(conn, observed["current"], data["native"])
    for path, version in data["versions"]:
        if canonical_json(file_change.version(Path(path))) != canonical_json(version):
            raise ValueError("Local survey original bytes changed during export")


def collect(database, list_id, *, with_pdfs=True, cancelled=lambda: False):

    database = Path(database).resolve(strict=True)
    native = generation._identity(database)
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        row = current_in(conn, list_id)
        if row is None:
            _detached_guard(conn, list_id)
            return None
        if not with_pdfs:
            raise ValueError("Include exact original PDFs to share source-aware surveys")
        body = _current_sources(conn, row, native)
        papers = _bounded_rows(conn, "papers", [b["paper_id"] for b in body["bindings"]])
        if any(row is None for row in papers):
            raise ValueError("Local survey original paper context is missing")
        observed = _snapshot(conn, list_id, [p["id"] for p in papers])
    files, sources, bindings, versions = {}, [], [], []
    total = 0
    for binding in body["bindings"]:
        survey_packages._cancel(cancelled)
        original = binding["original"]
        path = source_snapshots.source_path(database, original)
        read = owners._read_pdf(path, original["sha256"], original["size"], cancelled)
        if read is None:
            raise ValueError("Local survey export cancelled")
        raw, version = read
        total += len(raw)
        if total > survey_packages.MAX_PDF_BYTES:
            raise ValueError("Local survey originals exceed the package bound")
        source = next(s for s in body["report"]["sources"] if s["id"] == binding["source_id"])
        survey_packages.verify_original(raw, source, body["report"], cancelled=cancelled)
        name = survey_packages.source_relative(
            list_id, binding["paper_id"], original["sha256"]
        ).as_posix()
        files[name] = raw
        versions.append([str(path), version])
        bindings.append(dict(source_id=source["id"], paper_id=binding["paper_id"]))
        sources.append(
            dict(
                source_id=source["id"],
                paper_id=binding["paper_id"],
                sha256=original["sha256"],
                size=len(raw),
                path=name,
            )
        )
    portable = dict(
        format=survey_packages.FORMAT, list_id=list_id, report=body["report"], bindings=bindings
    )
    raw = canonical_json(portable)
    name = survey_packages.relative(list_id, body["report"]["id"]).as_posix()
    files[name] = raw
    record = dict(
        list_id=list_id,
        report_id=body["report"]["id"],
        path=name,
        **descriptor(raw, "application/json"),
    )
    encoded = _json(
        dict(
            database=str(database),
            native=native,
            observed=observed,
            record=record,
            sources=sources,
            papers=papers,
            versions=versions,
        )
    )
    captured = tuple(files.items())
    value = LocalSurveyExport(encoded, captured, _export_seal(encoded, captured))
    check_export(value)
    return value


def _detached_guard(conn, list_id):
    if "recovery_records" not in _tables(conn):
        return
    local = conn.execute(
        "SELECT 1 FROM recovery_records WHERE table_name='research_local_surveys' "
        "AND CASE WHEN json_valid(data) THEN json_extract(data,'$.list_id')=? END LIMIT 1",
        (list_id,),
    ).fetchone()
    native = conn.execute(
        "SELECT 1 FROM recovery_records WHERE table_name IN "
        "('research_file_desired','research_file_applied','research_file_versions') AND "
        "CASE WHEN json_valid(data) THEN CASE WHEN json_valid(json_extract(data,'$.operation')) "
        "THEN json_extract(json_extract(data,'$.operation'),'$.payload.feature')='survey' AND "
        "json_extract(json_extract(data,'$.operation'),'$.payload.list_id')=? END END LIMIT 1",
        (list_id,),
    ).fetchone()
    if local or native:
        raise ValueError(
            "Keep the original archive: saved surveys need reviewed reattachment "
            "before detached list export"
        )
