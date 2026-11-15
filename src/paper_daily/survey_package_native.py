"""Checked portable survey data for one compound receiver transaction.

Prospective root planning and actual publication share the receiver's graph. The
portable frame proves only validated content/bytes, never sender write authority.
"""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass, field

from paper_daily import survey_packages, sync_survey_files
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_files import canonical_json, file_id, list_file_id

_KEY = secrets.token_bytes(32)


def _signature(value):
    return hmac.new(
        _KEY,
        canonical_json([value._json, [[name, id(raw)] for name, raw in value.files]]),
        "sha256",
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ValidatedSurvey:
    _json: str = field(repr=False)
    files: tuple = field(repr=False)
    _seal: str = field(repr=False)


def checked(value):
    if not isinstance(value, ValidatedSurvey) or not hmac.compare_digest(
        value._seal, _signature(value)
    ):
        raise ValueError("Survey compound import needs its validated archive frame")
    return json.loads(value._json)


def validate(archive, manifest, tables, *, cancelled=lambda: False):
    portable = survey_packages.validate_package(archive, manifest, tables, cancelled=cancelled)
    if portable is None:
        return None
    records = list(manifest.get("survey_sources", []))
    files = tuple(
        (
            item["path"],
            survey_packages._read(
                archive,
                item["path"],
                item["sha256"],
                item["size"],
                survey_packages.MAX_PDF_BYTES,
            ),
        )
        for item in records
    )
    content = canonical_json(dict(portable=portable, sources=records)).decode()
    value = ValidatedSurvey(content, files, "")
    return ValidatedSurvey(content, files, _signature(value))


def payload_in(conn, client, frame, list_id, identities, originals):
    """Bind checked data to exact prospective/actual receiver native owners."""
    data = checked(frame)
    graph = client._optimistic_graph(conn)[0]
    parent = graph.get(("list", list_id))
    if not parent or not parent["active"]:
        raise ValueError("Survey package needs its active receiver list")
    bindings = []
    entities = [
        dict(
            kind="list", id=list_id, incarnation=parent["incarnation"], revision=0, depends_on=None
        )
    ]
    for source in data["sources"]:
        paper_id = identities.get(source["paper_id"])
        paper = graph.get(("paper", paper_id))
        key = file_id(paper_id, "original_source", source["sha256"]) if paper else None
        original = originals.get(key)
        expected_parent = (
            [dict(kind="paper", id=paper_id, incarnation=paper["incarnation"])] if paper else []
        )
        if (
            not paper
            or not paper["active"]
            or not original
            or original["workspace_id"] != client.journal.workspace_id
            or original["entity_type"] != "research_file"
            or original["action"] != "put"
            or original["entity_id"] != key
            or original["parents"] != expected_parent
            or original["payload"]["feature"] != "original_source"
            or original["payload"]["slot"] != source["sha256"]
        ):
            raise ValueError("Survey package needs every exact prepared receiver original")
        bindings.append(
            dict(
                source_id=source["source_id"],
                paper_id=paper_id,
                paper_incarnation=paper["incarnation"],
                document_hash=source["sha256"],
                file_id=key,
                incarnation=original["incarnation"],
            )
        )
        entities.extend(
            dict(kind=kind, id=identity, incarnation=life, revision=0, depends_on=None)
            for kind, identity, life in (
                ("paper", paper_id, paper["incarnation"]),
                ("research_file", key, original["incarnation"]),
            )
        )
    versions = dict(
        schema_version=2,
        workspace_id=client.journal.workspace_id,
        complete=False,
        entities=entities,
        documents=[],
        inputs_sha256=data["portable"]["report"]["inputs"]["prompt_hash"],
    )
    return sync_survey_files.encode(
        data["portable"]["report"], list_id, bindings, input_versions=versions
    )


def rebuild_in(conn, client, frame, list_id, identities, operation):
    """Recheck actual same-transaction originals before the report ownership grant."""
    data = checked(frame)
    originals = {}
    for source in data["sources"]:
        paper = identities[source["paper_id"]]
        key = file_id(paper, "original_source", source["sha256"])
        originals[key] = desired_file(conn, key)
    payload, _blobs = payload_in(conn, client, frame, list_id, identities, originals)
    if payload != operation["payload"] or operation["entity_id"] != list_file_id(list_id):
        raise ValueError("Survey package receiver owners changed before publication")
    return client.new_graph_operation_in(
        conn,
        "research_file",
        operation["entity_id"],
        payload,
        operation_id=operation["operation_id"],
    )
