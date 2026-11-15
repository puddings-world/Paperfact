"""Fresh native survey/source authority in an isolated first-enrollment candidate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from uuid import UUID, uuid5

from paper_daily import research_generation as generation
from paper_daily import survey_local, survey_package_native, survey_packages
from paper_daily.sync_artifacts import (
    activate,
    desired_file,
    materialize,
    stage_bytes,
    verify_closure,
)
from paper_daily.sync_files import canonical_json, file_id, list_file_id
from paper_daily.sync_journal import canonical_operation

MAX_REPORTS = 256
MAX_BYTES = 512 * 1024**2


@dataclass(frozen=True, slots=True)
class Inventory:
    reports: tuple = field(compare=False, repr=False)
    sources: tuple
    fingerprint: str


def inventory(database, conn, ticket):
    """Capture actual current local reports; archived versions remain data only."""
    if not survey_local._schema(conn):
        return Inventory((), (), hashlib.sha256(b"[]").hexdigest())
    listing_ids = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT s.list_id FROM research_local_surveys s "
            "JOIN lists l ON l.id=s.list_id "
            "WHERE s.is_current=1 ORDER BY s.list_id LIMIT ?",
            (MAX_REPORTS + 1,),
        )
    ]
    if len(listing_ids) > MAX_REPORTS:
        raise ValueError("Survey enrollment report count exceeds its bounded inventory")
    captured, originals, shared = [], {}, {}
    for list_id in listing_ids:
        ticket.check()
        row = survey_local.current_in(conn, list_id)
        body = survey_local._current_sources(conn, row, generation._identity(database))
        value = survey_packages.collect(database, list_id, cancelled=lambda: ticket.cancelled)
        if not isinstance(value, survey_local.LocalSurveyExport) or value.captured_record != row:
            raise ValueError("Survey enrollment source changed during its inventory")
        frame = survey_package_native.from_export(value, shared_bytes=shared)
        if sum(len(raw) for raw in shared.values()) > MAX_BYTES:
            raise ValueError("Survey enrollment originals exceed their bounded inventory")
        for binding in body["bindings"]:
            from paper_daily.source_snapshots import source_path

            original = binding["original"]
            key = binding["paper_id"], original["sha256"]
            originals[key] = dict(
                path=str(source_path(database, original)),
                sha256=original["sha256"],
                size=original["size"],
            )
        captured.append((list_id, frame))
    fingerprint = hashlib.sha256(
        canonical_json(
            [[list_id, survey_package_native.checked(frame)] for list_id, frame in captured]
        )
    ).hexdigest()
    return Inventory(tuple(captured), tuple(sorted(originals.items())), fingerprint)


def _payload_in(conn, client, frame, list_id):
    data = survey_package_native.checked(frame)
    identities, sources = {}, {}
    for source in data["sources"]:
        row = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (source["paper_id"],)
        ).fetchone()
        if row is None:
            raise ValueError("Survey enrollment needs its freshly mapped receiver paper")
        identities[source["paper_id"]] = row[0]
        key = file_id(row[0], "original_source", source["sha256"])
        sources[key] = desired_file(conn, key)
    return survey_package_native.payload_in(conn, client, frame, list_id, identities, sources)


def publish(client, store, version_root, captured, *, request_id, ticket):
    """Publish in the private candidate; the outer enrollment owns final exposure.

    Report staging/materialization is off-lock. Source grants are already present
    in this candidate. The report and activation share one checked transaction.
    Old local receipts/epochs never authorize publication to a different workspace.
    """
    request = UUID(request_id)
    if (
        str(request) != request_id
        or not isinstance(captured, Inventory)
        or (client.journal.workspace_id, client.journal.device_id)
        != (str(uuid5(request, "workspace")), str(uuid5(request, "device")))
    ):
        raise ValueError("Survey enrollment requires its exact fresh request workspace/device")
    done = []
    for list_id, frame in captured.reports:
        ticket.check()
        identity = list_file_id(list_id)
        action = str(uuid5(request, "survey:" + identity))
        with client.journal.transaction() as conn:
            payload, blobs = _payload_in(conn, client, frame, list_id)
            previous = conn.execute(
                "SELECT operation FROM research_file_versions WHERE operation_id=?", (action,)
            ).fetchone()
            current = desired_file(conn, identity)
            if previous:
                operation = json.loads(previous[0])
                if (
                    operation != current
                    or operation["payload"] != payload
                    or operation["workspace_id"] != client.journal.workspace_id
                    or operation["device_id"] != client.journal.device_id
                ):
                    raise ValueError("Survey enrollment retry no longer owns its exact report")
            else:
                if current is not None:
                    raise ValueError("Survey enrollment cannot overwrite another saved report")
                operation = client.new_graph_operation_in(
                    conn, "research_file", identity, payload, operation_id=action
                )
        stage_bytes(store, blobs)
        proof, _body, _blobs = verify_closure(store, operation)
        directory = materialize(store, version_root, operation)
        ticket.check()
        with client.journal.transaction() as conn:
            payload, _blobs = _payload_in(conn, client, frame, list_id)
            if payload != operation["payload"] or not proof.matches(operation):
                raise ValueError("Survey enrollment exact original or report bytes changed")
            if previous:
                if desired_file(conn, identity) != operation:
                    raise ValueError("Survey enrollment retry target changed")
            else:
                actual = client.new_graph_operation_in(
                    conn, "research_file", identity, payload, operation_id=action
                )
                if canonical_operation(actual) != canonical_operation(operation):
                    raise ValueError("Survey enrollment graph changed before its write")
                if not client.journal.apply_in(conn, operation, client.writer)["applied"]:
                    raise ValueError("Survey enrollment report publication failed")
            if not activate(conn, operation, directory):
                raise ValueError("Survey enrollment report activation changed")
            ticket.check()
        done.append(action)
    return dict(survey_reports=len(done), operation_ids=done)
