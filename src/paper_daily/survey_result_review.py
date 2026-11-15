"""Explicit review of retained reports using existing local/native import boundaries."""

from __future__ import annotations

import hmac
import json
import secrets
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from paper_daily import (
    file_change,
    position_source_snapshots,
    reading_goals,
    survey_local,
    survey_package_import,
    survey_package_native,
    survey_packages,
    survey_reader,
)
from paper_daily import research_generation as generation
from paper_daily.local_source_owners import _read_pdf
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_files import canonical_json, descriptor

_KEY = secrets.token_bytes(32)


def _signature(value):
    return hmac.new(
        _KEY,
        canonical_json(
            [
                value.original._seal,
                survey_reader._signature(value.original),
                value.current._seal,
                survey_reader._signature(value.current),
                id(value.staged),
                id(value.lease),
                value.native,
                value.origin,
                value.files,
                value.package_version,
            ]
        ),
        "sha256",
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Review:
    original: object = field(repr=False)
    current: object = field(repr=False)
    staged: object = field(repr=False)
    lease: object = field(repr=False)
    native: bool
    origin: dict = field(repr=False)
    files: tuple = field(repr=False)
    package_version: tuple = field(repr=False)
    _seal: str = field(repr=False)

    def close(self):
        # This exact owned TemporaryDirectory is never a caller-selected path.
        self.lease.cleanup()

    def summary(self):
        if not hmac.compare_digest(self._seal, _signature(self)):
            raise ValueError("Report summary changed after preparation")
        report = self.original.data["report"]
        current = self.current.data
        return dict(
            report_id=report["id"],
            current_report_id=current["report"]["id"] if current["kind"] != "none" else None,
            goal=report["inputs"].get("goal"),
            generation=report["generation"],
            sources=len(self.original.data["sources"]),
        )


def _owner_in(conn, original, origin):
    report = original.data["report"]
    inputs = report["inputs"]
    if (
        generation._path(conn) != str(original._database)
        or generation._identity(original._database) != origin["database_identity"]
        or generation._binding(conn) != origin["binding"]
        or parent_lifecycle(conn, "list", inputs["list_id"]) != inputs["list_lifecycle"]
    ):
        raise ValueError("Retained report belongs to another list or workspace lifetime")
    members = {
        row[0]
        for row in conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id=?", (inputs["list_id"],)
        )
    }
    for member in inputs["members"]:
        paper = member["paper_id"]
        if (
            paper not in members
            or parent_lifecycle(conn, "paper", paper) != member["paper_lifecycle"]
        ):
            raise ValueError("Retained report members require a new explicit mapping")


def _checked(value):
    if not isinstance(value, Review) or not hmac.compare_digest(value._seal, _signature(value)):
        raise ValueError("Report application requires its explicit prepared review")
    if file_change.version(Path(value.lease.name) / "report.zip") != value.package_version:
        raise ValueError("The prepared report package changed or was closed")
    archive, version = value.original._archive
    if survey_reader._archive_stamp(Path(archive)) != version:
        raise ValueError("The retained result changed after review")
    for path, observed in value.files:
        if file_change.version(Path(path)) != observed:
            raise ValueError("A retained original or receipt changed after review")
    with closing(generation._connect(value.original._database)) as conn:
        conn.execute("BEGIN")
        _owner_in(conn, value.original, value.origin)
    return value


def _archive_current(original):
    return (
        isinstance(original, survey_reader.SavedReport)
        and original._archive is not None
        and hmac.compare_digest(original._seal, survey_reader._signature(original))
        and original.data["kind"] == "retained"
        and survey_reader._archive_stamp(Path(original._archive[0])) == original._archive[1]
    )


def _read_current(database, list_id, cancelled):
    for attempt in range(2):
        try:
            return survey_reader.read(database, list_id, cancelled=cancelled)
        except survey_reader.ReadChanged:
            if attempt:
                raise


def _same_report(first, second):
    return all(
        first.data.get(key) == second.data.get(key)
        for key in ("kind", "report", "update_pending", "list_id")
    )


def _goal_in(conn, origin, list_id):
    if reading_goals._snapshot_in(conn, list_id) != origin["goal"]:
        raise ValueError("The current research goal changed after review; review again")


def prepare(original, *, cancelled=lambda: False):
    """Stage a review without research writes; no AI or generation-context recapture."""
    from paper_daily import source_snapshots, survey_jobs

    survey_packages._cancel(cancelled)
    if not _archive_current(original):
        raise ValueError("Open the retained report before preparing its application")
    data = original.data
    database, list_id = original._database, data["list_id"]
    current = _read_current(database, list_id, cancelled)
    if current.data["update_pending"]:
        raise ValueError("Finish receiving the pending current report before review")
    record = survey_jobs._retained_record(database, list_id, data["request_id"])
    context = json.loads(record["context_json"])
    origin = {key: context[key] for key in ("database_identity", "binding")}
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN")
        _owner_in(conn, original, origin)
        origin["goal"] = reading_goals._snapshot_in(conn, list_id)
    lease = tempfile.TemporaryDirectory(prefix="paperfact-survey-review-")
    try:
        report, records, bindings, files, versions = data["report"], [], [], {}, []
        for binding in data["sources"]:
            survey_packages._cancel(cancelled)
            row = binding["original"]
            path, _version = position_source_snapshots.verify(database, row)
            result = _read_pdf(path, row["sha256"], row["size"], cancelled)
            if result is None:
                raise ValueError("Retained report preparation cancelled")
            raw, version = result
            source = next(s for s in report["sources"] if s["id"] == binding["source_id"])
            survey_packages.verify_original(raw, source, report, cancelled=cancelled)
            receipt = source_snapshots.receipt_path(database, row)
            receipt_version = file_change.version(receipt)
            position_source_snapshots.verify(database, row, known_version=version)
            if file_change.version(receipt) != receipt_version:
                raise ValueError("A retained receipt changed during preparation")
            versions.extend(((str(path), version), (str(receipt), receipt_version)))
            relative = survey_packages.source_relative(list_id, binding["paper_id"], row["sha256"])
            files[relative.as_posix()] = raw
            records.append(
                dict(
                    source_id=source["id"],
                    paper_id=binding["paper_id"],
                    sha256=row["sha256"],
                    size=len(raw),
                    path=relative.as_posix(),
                )
            )
            bindings.append(dict(source_id=source["id"], paper_id=binding["paper_id"]))
        portable = dict(
            format=survey_packages.FORMAT, list_id=list_id, report=report, bindings=bindings
        )
        body = canonical_json(portable)
        relative = survey_packages.relative(list_id, report["id"]).as_posix()
        files[relative] = body
        table = dict(
            list_id=list_id,
            report_id=report["id"],
            path=relative,
            **descriptor(body, "application/json"),
        )
        tables = {
            survey_packages.TABLE: [table],
            "papers": [
                dict(id=member["paper_id"], title=member["title"])
                for member in report["inputs"]["members"]
            ],
        }
        manifest = dict(
            format=2,
            list=dict(id=list_id),
            pdfs_included=True,
            capabilities=[survey_packages.CAPABILITY],
            survey_sources=records,
            file_hashes={
                name: descriptor(raw, "application/pdf")["sha256"] for name, raw in files.items()
            },
        )
        archive = Path(lease.name) / "report.zip"
        with zipfile.ZipFile(archive, "x") as zipped:
            zipped.writestr("manifest.json", canonical_json(manifest))
            zipped.writestr("tables.json", canonical_json(tables))
            for name, raw in files.items():
                zipped.writestr("files/" + name, raw)
        mapping = {row["paper_id"]: row["paper_id"] for row in records}
        native = origin["binding"] is not None
        if native:
            staged = survey_package_import.prepare(
                database,
                archive,
                target_list_id=list_id,
                paper_mapping=mapping,
                replace=True,
                request_id=uuid4().hex,
                cancelled=cancelled,
            )
        else:
            with zipfile.ZipFile(archive) as zipped:
                frame = survey_package_native.validate(
                    zipped, manifest, tables, cancelled=cancelled
                )
            staged = survey_local.stage(database, frame, list_id, mapping, cancelled=cancelled)
        latest = _read_current(database, list_id, cancelled)
        if not _archive_current(original) or not _same_report(current, latest):
            raise ValueError("The report or workspace changed while preparing review")
        with closing(generation._connect(database)) as conn:
            conn.execute("BEGIN")
            _goal_in(conn, origin, list_id)
        survey_packages._cancel(cancelled)
        value = Review(
            original,
            current,
            staged,
            lease,
            native,
            origin,
            tuple(versions),
            file_change.version(archive),
            "",
        )
        value = Review(
            original,
            current,
            staged,
            lease,
            native,
            origin,
            tuple(versions),
            value.package_version,
            _signature(value),
        )
        return _checked(value)
    except BaseException:
        lease.cleanup()
        raise


def apply(review, *, cancelled=lambda: False):
    """Apply only a prepared review; preserve old versions and never reactivate on retry."""
    value = _checked(review)
    survey_packages._cancel(cancelled)
    database, list_id = value.original._database, value.original.data["list_id"]
    current = _read_current(database, list_id, cancelled)
    if (
        current.data["kind"] != "none"
        and not current.data["update_pending"]
        and current.data["report"] == value.original.data["report"]
    ):
        return dict(state="unchanged", report_id=current.data["report"]["id"])
    if value.native:
        data = survey_package_import._checked(value.staged)
        with closing(generation._connect(database)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            _owner_in(conn, value.original, value.origin)
            prior = conn.execute(
                "SELECT 1 FROM research_file_versions WHERE operation_id=?",
                (data["proof_operation"]["operation_id"],),
            ).fetchone()
            if not prior:
                _goal_in(conn, value.origin, list_id)
            result = survey_package_import.publish_in(conn, value.staged, cancelled=cancelled)
        if result["state"] != "preserved":
            from paper_daily.survey_publication import complete_pending

            complete_pending(value.staged._client, list_id, cancelled=cancelled)
        return result
    with closing(generation._connect(database)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _owner_in(conn, value.original, value.origin)
        _goal_in(conn, value.origin, list_id)
        survey_local.check_targets_in(conn, value.staged)
        return survey_local.publish_in(conn, value.staged, replace=True, cancelled=cancelled)
