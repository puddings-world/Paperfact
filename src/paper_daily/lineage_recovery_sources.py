"""Staged fresh native originals for sealed detached-recovery inspections.

Only active current generated, imported or native cohorts are eligible.
RecoveryAdoptionService uses this helper before normal fresh enrollment.
This helper itself neither publishes a workspace nor replaces archive retention.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_package_targets as targets
from paper_daily import lineage_packages, lineage_sets
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.research_lifecycle import ensure_lifecycle
from paper_daily.sync_files import canonical_json
from paper_daily.workspace_service import Ticket, _binding, _safe_path, _tables

_KEY = secrets.token_bytes(32)
MAX_BATCH_ROWS = 16
BATCH_METADATA_TARGET = lineage_packages.MAX_METADATA // 4


def _active(records, parents):
    return all(
        p["paper_id"] in records.paper_ids
        and (actual := records.parent_lifecycles.get(("paper", p["paper_id"]))) is not None
        and actual["active"] == 1
        and actual["token"] == p["parent_lifecycle"]
        for p in parents
    )


def _authority(records, row):
    if records.workspace is not None:
        for marker, scientific in records.lineage.bound.markers.values():
            if (
                marker["active"] != 1
                or marker["paper_id"] != row["paper_id"]
                or marker["corpus_key"] != row["corpus_key"]
            ):
                continue
            if records.lineage.bound._local_row(scientific, records) != row:
                raise ValueError("Recovered Lineage differs from its selected scientific version")
            graph, operations = records.lineage.bound.optimistic(records.cursor)
            if operations.get(("research_content", scientific["entity_id"])) != scientific:
                raise ValueError("Recovered Lineage scientific head requires fresh review")
            from paper_daily.lineage_dependencies import active

            current = graph.get(("research_content", scientific["entity_id"]))
            if (
                current is None
                or not current["active"]
                or current["incarnation"] != scientific["incarnation"]
                or not active(
                    lambda kind, identity, graph=graph: graph.get((kind, identity)), scientific
                )
            ):
                raise ValueError("Recovered Lineage current input lifetime changed")
            parents = {parent["id"]: parent for parent in scientific["parents"]}
            for parent in parents.values():
                current = graph.get(("paper", parent["id"]))
                if (
                    current is None
                    or not current["active"]
                    or current["incarnation"] != parent["incarnation"]
                    or records.lineage.bound.papers.get(parent["id"]) != parent["incarnation"]
                    or records.paper_map.get(parent["id"]) not in records.paper_ids
                ):
                    raise ValueError("Recovered Lineage selected paper lifetime changed")
            originals = {}
            for pin in scientific["source_dependencies"]:
                active, original = records.lineage.bound.desired.get(pin["file_id"], (False, None))
                source = graph.get(("research_file", pin["file_id"]))
                parent = [parents[pin["paper_id"]]]
                if (
                    not active
                    or original is None
                    or source is None
                    or not source["active"]
                    or original["incarnation"] != pin["incarnation"]
                    or source["incarnation"] != pin["incarnation"]
                    or original["parents"] != parent
                    or source["parents"] != parent
                    or original["payload"]["feature"] != "original_source"
                ):
                    raise ValueError("Recovered Lineage original lifetime changed")
                asset = original["payload"]["assets"][0]
                originals[records.paper_map[pin["paper_id"]]] = {
                    key: asset[key] for key in ("sha256", "size", "media_type")
                }
            return originals
        raise ValueError("Recovered Lineage has no exact visible scientific provenance")
    encoded = lineage_packages._json(row)
    selected = {b["paper_id"] for b in lineage_sets.decode(row["body_json"])["bindings"]}
    for action in records.lineage.imported.actions.values():
        parents = [p for p in action["parents"] if p["paper_id"] in selected]
        for item in action["records"]:
            if item["row_json"] == encoded and _active(records, parents):
                return {
                    json.loads(source["owner_json"])["paper_id"]: source
                    for source in item["sources"]
                }
    from paper_daily.lineage_recovery import linked_publication

    for receipt in records.lineage.publications.values():
        if receipt["row_json"] != encoded:
            continue
        candidate = records.lineage.candidates[receipt["request_id"]]
        _row, sources, context = linked_publication(receipt, candidate)
        parents = context["inputs"]["parents"]
        if {p["paper_id"] for p in parents} == selected and _active(records, parents):
            return {json.loads(source["owner_json"])["paper_id"]: source for source in sources}
    raise ValueError("Recovered Lineage cohort is obsolete or lacks current original ownership")


def _parents(rows):
    return {
        b["paper_id"] for row in rows for b in lineage_sets.decode(row["body_json"])["bindings"]
    }


def _batches(rows, papers):
    batch = []
    for row in sorted(rows, key=lambda r: (r["paper_id"], r["corpus_key"])):
        candidate = [*batch, row]
        context = [papers[p] for p in sorted(_parents(candidate))]
        size = len(canonical_json(dict(papers=context, rows=candidate, targets=candidate)))
        if batch and (len(candidate) > MAX_BATCH_ROWS or size > BATCH_METADATA_TARGET):
            yield batch
            batch = [row]
        else:
            batch = candidate
    if batch:
        yield batch


def _seal(service, inspection, database, native, digest, papers, stages):
    encoded = canonical_json(
        [
            id(service),
            id(inspection),
            str(database),
            native,
            digest,
            papers,
            [stage._seal for stage in stages],
            os.getpid(),
        ]
    )
    return hmac.new(_KEY, encoded, "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedSources:
    _service: object = field(repr=False)
    _inspection: object = field(repr=False)
    _database: Path = field(repr=False)
    _native: tuple = field(repr=False)
    _digest: str = field(repr=False)
    _papers: str = field(repr=False)
    _stages: tuple = field(repr=False)
    _seal: str = field(repr=False)


def prepare(service, inspection, database, *, ticket=None):
    """Verify source snapshot and stage current originals in bounded off-SQL batches.

    The caller owns an independent unpublished destination baseline and copies
    exact research rows there in its later transaction. No destination SQL is
    written, original research is never edited and no history/authority is copied.
    """
    from paper_daily.recovery_adoption import RecoveryAdoptionService, RecoveryInspection, _records

    _worker()
    ticket = ticket or Ticket()
    if not isinstance(service, RecoveryAdoptionService) or not isinstance(
        inspection, RecoveryInspection
    ):
        raise ValueError("Lineage recovery needs a native service inspection")
    value = service._validate(inspection, ticket)
    database = _safe_path(Path(database).resolve(strict=True))
    root = service.root.resolve()
    if (
        database == service.database
        or database.is_relative_to(root)
        or root.is_relative_to(database.parent)
    ):
        raise ValueError("Lineage recovery destination must be independent of its source")
    native = tuple(generation._identity(database))
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        if generation._binding(conn) is not None or _binding(conn, _tables(conn)):
            raise ValueError("Lineage recovery needs an unbound private baseline")
    rows = value["tables"].get(lineage_sets.TABLE, [])
    records = _records(value)
    papers = {p["id"]: p for p in value["tables"].get("papers", [])}
    selected_papers = {p: papers[p] for p in sorted(_parents(rows))}
    authorities = {(r["paper_id"], r["corpus_key"]): _authority(records, r) for r in rows}
    stages = []
    digest = hashlib.sha256(inspection._snapshot).hexdigest()
    with tempfile.TemporaryDirectory(prefix="paperfact-lineage-recovery-") as temporary:
        for number, batch in enumerate(_batches(rows, papers)):
            ticket.check()
            selected = _parents(batch)
            focal = {r["paper_id"] for r in batch}
            context = {p: dict(id=p, title=papers[p]["title"]) for p in sorted(selected)}
            tables = dict(
                papers=[context[p] for p in sorted(focal)],
                cited_papers=[context[p] for p in sorted(selected - focal)],
                paper_lineage_sets=batch,
            )
            descriptors, files = [], {}
            for row in batch:
                original = authorities[row["paper_id"], row["corpus_key"]]
                body = lineage_sets.decode(row["body_json"])
                for binding, source in zip(
                    body["bindings"], body["report"]["sources"], strict=True
                ):
                    if source["availability"] == "unavailable":
                        continue
                    receipt = original[binding["paper_id"]]
                    path = lineage_packages.relative(
                        row["paper_id"], binding["paper_id"], receipt["sha256"]
                    ).as_posix()
                    descriptors.append(
                        dict(
                            focal_paper_id=row["paper_id"],
                            corpus_key=row["corpus_key"],
                            source_id=source["id"],
                            paper_id=binding["paper_id"],
                            sha256=receipt["sha256"],
                            size=receipt["size"],
                            path=path,
                        )
                    )
                    files[path] = receipt
            manifest = dict(
                format=2,
                capabilities=["lineage"],
                pdfs_included=True,
                lineage_sources=descriptors,
                file_hashes={path: r["sha256"] for path, r in files.items()},
            )
            archive_path = Path(temporary) / "sources.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("manifest.json", canonical_json(manifest))
                archive.writestr("tables.json", canonical_json(tables))
                for path, receipt in files.items():
                    ticket.check()
                    original = _safe_path(service.root / "objects" / receipt["sha256"])
                    archive.write(original, "files/" + path)
            with zipfile.ZipFile(archive_path) as archive:
                package = targets.validate(
                    archive, manifest, tables, cancelled=lambda: ticket.cancelled
                )
            request = str(
                uuid5(NAMESPACE_URL, "paperfact-lineage-recovery:" + digest + ":" + str(number))
            )
            stages.append(
                publisher.stage(
                    database,
                    package,
                    {p: p for p in selected},
                    request_id=request,
                    expected_native=native,
                    cancelled=lambda: ticket.cancelled,
                )
            )
            # Consumed native package bytes are no longer needed by the staged proof.
            del package
            service._metadata_current(inspection, ticket)
    if tuple(generation._identity(database)) != native:
        raise ValueError("Lineage recovery destination changed")
    selected_json = canonical_json(selected_papers).decode()
    stages = tuple(stages)
    return PreparedSources(
        service,
        inspection,
        database,
        native,
        digest,
        selected_json,
        stages,
        _seal(service, inspection, database, native, digest, selected_json, stages),
    )


def stage_in(conn, prepared, *, ticket=None):
    """Grant fresh current original ownership in one caller-owned staging transaction.

    All chunk writes share a savepoint. The caller separately retains archive
    history and publishes the fresh native enrollment; this step grants only
    the verified local original ownership required by that enrollment.
    """
    _worker()
    ticket = ticket or Ticket()
    if not isinstance(prepared, PreparedSources) or not hmac.compare_digest(
        prepared._seal,
        _seal(
            prepared._service,
            prepared._inspection,
            prepared._database,
            prepared._native,
            prepared._digest,
            prepared._papers,
            prepared._stages,
        ),
    ):
        raise ValueError("Lineage recovery requires its native prepared source proof")
    if not conn.in_transaction or generation._path(conn) != str(prepared._database):
        raise ValueError("Lineage recovery requires its exact caller transaction")
    prepared._service._metadata_current(prepared._inspection, ticket)
    if tuple(generation._identity(prepared._database)) != prepared._native:
        raise ValueError("Lineage recovery destination changed")
    for identity, expected in json.loads(prepared._papers).items():
        row = conn.execute("SELECT * FROM papers WHERE id=?", (identity,)).fetchone()
        columns = [c[1] for c in conn.execute("PRAGMA table_info(papers)")]
        actual = None if row is None else dict(zip(columns, row, strict=True))
        if actual is None or any(actual.get(k) != v for k, v in expected.items()):
            raise ValueError("Lineage staged receiver paper differs from its inspected source")
    point = "lineage_recovery_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + point)
    count = 0
    try:
        if prepared._stages:
            ensure_lifecycle(conn)
        for staged in prepared._stages:
            ticket.check()
            observed = publisher.observe_in(conn, staged, cancelled=lambda: ticket.cancelled)
            current = publisher._checked(staged)["rows"]
            if observed.rows != observed.before or observed.rows != current:
                raise ValueError("Lineage staged science differs from the inspected source")
            result = publisher.publish_in(
                conn, staged, observed, cancelled=lambda: ticket.cancelled
            )
            count += result["reports"]
        prepared._service._metadata_current(prepared._inspection, ticket)
        ticket.check()
        conn.execute("RELEASE " + point)
    except BaseException:
        conn.execute("ROLLBACK TO " + point)
        conn.execute("RELEASE " + point)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    return dict(lineage_reports=count, batches=len(prepared._stages))
