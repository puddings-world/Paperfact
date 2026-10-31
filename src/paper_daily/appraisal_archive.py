"""Private bounded derived-review history, outside research sync and bundles.

No folder is created on construction or reads. Saving follows an explicit model
appraisal; never infer model permission from a cached result or replay a request.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from paper_daily import audit_appraisal, claim_content, research_audit
from paper_daily import research_evidence as evidence
from paper_daily.sync_legacy_sources import path as owned_path

FORMAT = "paperfact.appraisal-archive.v1"
MAX_BYTES = 512 * 1024
MAX_RECORDS = 128


def _fail(code):
    raise research_audit.AuditError(code)


def _uuid(value):
    if not isinstance(value, str):
        _fail("invalid_appraisal_record")
    try:
        if str(UUID(value)) != value:
            _fail("invalid_appraisal_record")
    except (ValueError, AttributeError):
        _fail("invalid_appraisal_record")


def validate(report):
    fields = {
        "format",
        "request_id",
        "source",
        "input_hash",
        "selected",
        "generation",
        "findings",
        "semantic_validation",
        "retrieval",
        "inputs_current",
        "cancelled_after_call",
        "recorded_scope",
        "persistence",
        "id",
    }
    if not isinstance(report, dict) or set(report) != fields:
        _fail("invalid_appraisal_record")
    if (
        report["format"] != audit_appraisal.FORMAT
        or report["semantic_validation"] != "model_proposal"
        or report["retrieval"] != "bounded_lexical_not_exhaustive"
        or report["recorded_scope"] != "original_snapshot"
        or report["persistence"] != "local_derived"
    ):
        _fail("invalid_appraisal_record")
    _uuid(report["request_id"])
    claim_content.closed(report["source"], {"paper_id", "document_hash"})
    claim_content.text(report["source"]["paper_id"], 512)
    claim_content.digest(report["source"]["document_hash"])
    claim_content.digest(report["input_hash"])
    if (
        type(report["inputs_current"]) is not bool
        or type(report["cancelled_after_call"]) is not bool
    ):
        _fail("invalid_appraisal_record")
    selected = report["selected"]
    if not isinstance(selected, list) or not 1 <= len(selected) <= audit_appraisal.MAX_ITEMS:
        _fail("invalid_appraisal_record")
    if any(not isinstance(v, str) or not v or len(v) > 512 for v in selected) or len(
        set(selected)
    ) != len(selected):
        _fail("invalid_appraisal_record")
    generation = report["generation"]
    claim_content.closed(generation, {"task", "backend", "requested_model", "returned_model"})
    if generation["task"] != "audit":
        _fail("invalid_appraisal_record")
    claim_content.text(generation["backend"], 64)
    for key in ("requested_model", "returned_model"):
        claim_content.text(generation[key], 512, nullable=True)
    findings = report["findings"]
    if not isinstance(findings, list) or len(findings) != len(selected):
        _fail("invalid_appraisal_record")
    for identity, row in zip(selected, findings, strict=True):
        claim_content.closed(
            row,
            {"item_id", "proposed_status", "reason", "state", "evidence", "semantic_validation"},
        )
        if (
            row["item_id"] != identity
            or row["proposed_status"] not in ("supported", "contradicted", "not_found")
            or row["state"] not in ("proposed", "evidence_unverified")
            or row["semantic_validation"] != "model_proposal"
        ):
            _fail("invalid_appraisal_record")
        claim_content.text(row["reason"], 2000)
        if not isinstance(row["evidence"], list) or len(row["evidence"]) > 4:
            _fail("invalid_appraisal_record")
        for passage in row["evidence"]:
            claim_content.closed(
                passage, {"span_id", "quote", "state", "anchor", "page", "document_hash"}
            )
            claim_content.digest(passage["span_id"])
            claim_content.text(passage["quote"], 4000)
            if passage["document_hash"] != report["source"]["document_hash"]:
                _fail("invalid_appraisal_record")
            if passage["state"] == "located":
                claim_content.anchor(passage["anchor"], 500)
                if (
                    type(passage["page"]) is not int
                    or passage["page"] != passage["anchor"]["p0"] + 1
                ):
                    _fail("invalid_appraisal_record")
            elif (
                passage["state"] not in ("missing", "ambiguous")
                or passage["anchor"] is not None
                or passage["page"] is not None
            ):
                _fail("invalid_appraisal_record")
        usable = bool(row["evidence"]) and all(p["state"] == "located" for p in row["evidence"])
        expected = (
            "proposed"
            if usable or not row["evidence"] and row["proposed_status"] == "not_found"
            else "evidence_unverified"
        )
        if row["state"] != expected:
            _fail("invalid_appraisal_record")
    claim_content.digest(report["id"])
    if report["id"] != claim_content.hashed({k: v for k, v in report.items() if k != "id"}):
        _fail("invalid_appraisal_record")
    return report


def default_root():
    from paper_daily.runtime import user_cache_dir

    return user_cache_dir() / "model-reviews"


class AppraisalArchive:
    def __init__(self, root, capture):
        self.root = owned_path(root)
        self.scope = claim_content.hashed(
            [str(capture.database), capture.paper_id, json.loads(capture._state_json)]
        )
        self.folder = owned_path(self.root / self.scope)

    def _files(self):
        if not self.folder.exists():
            return []
        files = []
        for number, path in enumerate(self.folder.iterdir(), 1):
            if number > MAX_RECORDS * 2:
                _fail("appraisal_archive_limit")
            if path.name.startswith(".stage-") and path.name.endswith(".tmp"):
                continue  # An interrupted writer has no accepted report.
            _uuid(path.stem)
            if path.suffix != ".json" or len(files) >= MAX_RECORDS:
                _fail("appraisal_archive_limit")
            files.append(owned_path(path))
        return files

    def save(self, report):
        report = validate(report)
        # Freeze caller data before IO; an edited UI object cannot change stored fields.
        encoded = json.dumps(report, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            _fail("appraisal_archive_limit")
        report = validate(json.loads(encoded))
        destination = owned_path(self.folder / (report["request_id"] + ".json"))
        if destination.exists():
            previous = self._read(destination)
            if previous["report"] != report:
                _fail("appraisal_retry_changed")
            return destination
        self._files()  # Refuse capacity or unknown paths before staging.
        if len(self._files()) >= MAX_RECORDS:
            _fail("appraisal_archive_limit")
        record = dict(
            format=FORMAT, scope=self.scope, created_at=datetime.now(UTC).isoformat(), report=report
        )
        data = (
            json.dumps(
                record, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode()
        if len(data) > MAX_BYTES:
            _fail("appraisal_archive_limit")
        self.folder.mkdir(parents=True, exist_ok=True)
        owned_path(self.folder)
        fd, name = tempfile.mkstemp(prefix=".stage-", suffix=".tmp", dir=self.folder)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            owned_path(destination)
            try:
                os.link(temporary, destination)  # Never replace an existing review.
            except FileExistsError:
                if self._read(destination)["report"] != report:
                    _fail("appraisal_retry_changed")
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
        return destination

    def _read(self, path):
        with owned_path(path).open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            _fail("appraisal_archive_limit")

        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    _fail("invalid_appraisal_record")
                result[key] = value
            return result

        try:
            record = json.loads(data, object_pairs_hook=pairs)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            _fail("invalid_appraisal_record")
        claim_content.closed(record, {"format", "scope", "created_at", "report"})
        if record["format"] != FORMAT or record["scope"] != self.scope:
            _fail("invalid_appraisal_record")
        claim_content.text(record["created_at"], 64)
        validate(record["report"])
        if path.stem != record["report"]["request_id"]:
            _fail("invalid_appraisal_record")
        return record

    def current(self, capture):
        expected_scope = claim_content.hashed(
            [str(capture.database), capture.paper_id, json.loads(capture._state_json)]
        )
        if expected_scope != self.scope:
            _fail("appraisal_workspace_changed")
        if not capture.current():
            _fail("saved_content_changed")
        lookup = {item["id"]: item for item in json.loads(capture._items_json)}
        records = []
        for path in self._files():
            record = self._read(path)
            report = record["report"]
            selected = report["selected"]
            if (
                report["source"] != capture.snapshot.source
                or any(key not in lookup for key in selected)
                or claim_content.hashed([lookup[key] for key in selected]) != report["input_hash"]
            ):
                continue
            records.append(record)
        if records:
            _source, data = evidence._checked_snapshot(capture.snapshot)
            pages, indexes, whole = evidence._extract(data)
            for record in records:
                for finding in record["report"]["findings"]:
                    for passage in finding["evidence"]:
                        if passage["state"] != "located":
                            continue
                        located = evidence._locate(passage, pages, indexes, whole)
                        if located["state"] != "located" or located["anchor"] != passage["anchor"]:
                            _fail("invalid_appraisal_record")
        return sorted(
            records, key=lambda row: (row["created_at"], row["report"]["request_id"]), reverse=True
        )
