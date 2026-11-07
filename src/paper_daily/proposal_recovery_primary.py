"""Observed unbound common-proposal primaries for archive-only recovery.

Resolve through the maintained canonical local reader and capture native parent
and byte observations. This never enrolls, binds or migrates the source workspace.
"""

from __future__ import annotations

import hashlib
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import local_deck_proposals as local
from paper_daily.document_reader import from_workspace
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_files import canonical_json, closed, digest, text
from paper_daily.sync_legacy_sources import validate_pdf

TABLE = "research_common_primary_recovery"
COLUMNS = "paper_id parent_token sha256 size media_type"
MAX_PDF_BYTES = 150 * 1024**2
MAX_BYTES = 512 * 1024**2
_SEAL = object()


def validate(row):
    closed(row, COLUMNS.split())
    text(row["paper_id"], 4096)
    token = row["parent_token"]
    if (
        not isinstance(token, str)
        or len(token) != 32
        or any(c not in "0123456789abcdef" for c in token)
    ):
        raise ValueError("Observed local primary requires its actual parent lifetime")
    digest(row["sha256"])
    if (
        type(row["size"]) is not int
        or not 0 < row["size"] <= MAX_PDF_BYTES
        or row["media_type"] != "application/pdf"
    ):
        raise ValueError("Invalid observed local primary descriptor")
    return row


def _parent(database, native, identity):
    if local._native(database) != native:
        raise ValueError("Original observed-primary workspace was replaced")
    with closing(local._connect(database)) as conn:
        local._database(conn, database, native)  # Genuinely unbound, no read-side enrollment.
        paper = local._paper(conn, identity)
        token = parent_lifecycle(conn, "paper", identity)
    if paper is None or token is None:
        raise ValueError("Observed local primary has no actual canonical parent")
    return paper, token


@dataclass(frozen=True)
class Observation:
    _database: Path = field(repr=False)
    _native: tuple = field(repr=False)
    _captured: tuple = field(repr=False)
    _rows: tuple = field(repr=False)
    _objects: tuple = field(repr=False)
    _aliases: tuple = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def rows(self):
        import json

        return [json.loads(value) for value in self._rows]

    @property
    def objects(self):
        return dict(self._objects)

    @property
    def aliases(self):
        return dict(self._aliases)

    def check(self, *, current=lambda: True):
        if self._seal is not _SEAL:
            raise ValueError("Use actual observed local-primary proof")
        local._check(current)
        for identity, paper_json, token, path, version, sha in self._captured:
            paper, now = _parent(self._database, self._native, identity)
            if canonical_json(paper).decode() != paper_json or now != token:
                raise ValueError("Observed local primary parent changed")
            if sha is not None:
                local._files_current([(path, version)])
            reader = from_workspace(self._database, legacy_root=self._database.parent / "pdf")
            try:
                document = reader.resolve(identity)
                if sha is None:
                    if document.available or document.status != "missing":
                        raise ValueError(
                            "Observed missing primary became available or changed scope"
                        )
                elif (
                    not document.available
                    or document.managed
                    or document.sha256 != sha
                    or document.path != Path(path)
                    or not reader.current(document)
                ):
                    raise ValueError("Observed local primary reader/source changed")
            finally:
                reader.close()
            final_paper, final_token = _parent(self._database, self._native, identity)
            if canonical_json(final_paper).decode() != paper_json or final_token != token:
                raise ValueError("Observed local primary parent changed during final read")
        if local._native(self._database) != self._native:
            raise ValueError("Original observed-primary database changed")
        local._check(current)
        return True


def collect(database, snapshot, identities, temporary, *, expected_native, current=lambda: True):
    database, native = local._path(database), local._expected(expected_native)
    local._check(current)
    rows, objects, aliases, captured, total = [], {}, {}, [], 0
    folder = local._path(temporary) / "observed-common-primaries"
    # No scope broadening: callers select only genuinely local common-catalog parents.
    for identity in sorted(set(identities)):
        paper, token = _parent(database, native, identity)
        if (
            paper != local._paper(snapshot, identity)
            or parent_lifecycle(snapshot, "paper", identity) != token
        ):
            raise ValueError("SQL snapshot differs from original observed-primary parent")
        reader = from_workspace(database, legacy_root=database.parent / "pdf")
        try:
            document = reader.resolve(identity)
            if not document.available:
                if document.status == "missing":
                    captured.append(
                        (identity, canonical_json(paper).decode(), token, None, None, None)
                    )
                    continue
                raise ValueError("Local primary is unavailable or ambiguous")
            if document.managed:
                raise ValueError("Managed/retired originals require their existing typed protocol")
            path = local._path(document.path)
            before = local.file_change.version(path)
            if before[2] > MAX_PDF_BYTES or not reader.current(document):
                raise ValueError("Observed local primary source changed")
            with path.open("rb") as stream:
                if local.file_change.version(path, stream=stream) != before:
                    raise ValueError("Observed local primary changed before read")
                data = stream.read(MAX_PDF_BYTES + 1)
                if local.file_change.version(path, stream=stream) != before:
                    raise ValueError("Observed local primary changed during read")
            validate_pdf(data)
            if (
                len(data) != before[2]
                or hashlib.sha256(data).hexdigest() != document.sha256
                or not reader.current(document)
                or _parent(database, native, identity) != (paper, token)
            ):
                raise ValueError("Observed local primary source/parent changed after read")
            local._check(current)
            total += len(data)
            if total > MAX_BYTES:
                raise ValueError("Observed common primaries exceed 512 MiB")
            local._no_link(folder)
            folder.mkdir(exist_ok=True)
            local._path(folder)
            target = folder / document.sha256
            local._no_link(target)
            if target.exists():
                local._path(target)
            if not target.exists():
                target.write_bytes(data)
            if target.read_bytes() != data:
                raise ValueError("Observed primary temporary object changed")
            row = dict(
                paper_id=identity,
                parent_token=token,
                sha256=document.sha256,
                size=len(data),
                media_type="application/pdf",
            )
            validate(row)
            rows.append(canonical_json(row).decode())
            objects[document.sha256] = target
            aliases[path] = (document.sha256, len(data))
            captured.append(
                (
                    identity,
                    canonical_json(paper).decode(),
                    token,
                    str(path),
                    before,
                    document.sha256,
                )
            )
        finally:
            reader.close()
    value = Observation(
        database,
        native,
        tuple(captured),
        tuple(rows),
        tuple(objects.items()),
        tuple(aliases.items()),
        _SEAL,
    )
    value.check(current=current)
    return value
