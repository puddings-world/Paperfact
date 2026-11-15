"""Observed native-owner import of portable survey data, without fake AI provenance.

This component requires explicitly selected existing enrolled list/paper owners.
Whole-list root creation, unbound persistence and public bundle wiring remain at
its caller boundary; success here imports only the saved source-aware report.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import (
    file_change,
    survey_packages,
    sync_capture,
    sync_source_files,
    sync_survey_files,
)
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_artifacts import desired_file, paths, stage_bytes, verify_closure
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_files import canonical_json, list_file_id
from paper_daily.sync_journal import _identifier
from paper_daily.workspace_service import _binding, _tables

_KEY = secrets.token_bytes(32)
MAX_ARCHIVE = 512 * 1024**2


def _seal(value):
    return hmac.new(_KEY, value.encode(), "sha256").hexdigest()


def _request(request, purpose):
    return "survey-import:" + hashlib.sha256(canonical_json([request, purpose])).hexdigest()


def _targets_in(conn, client, list_id, mapping, sources):
    graph = client._optimistic_graph(conn)[0]
    listing = conn.execute("SELECT * FROM lists WHERE id=?", (list_id,)).fetchone()
    parent = graph.get(("list", list_id))
    if listing is None or parent is None or not parent["active"]:
        raise ValueError("Survey import needs an explicitly selected active receiver list")
    observed = []
    for source in sources:
        local = mapping[source["paper_id"]]
        row = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local,)
        ).fetchone()
        paper = graph.get(("paper", row[0])) if row else None
        if paper is None or not paper["active"]:
            raise ValueError("Survey import needs each exact active receiver paper mapping")
        identity = sync_survey_files.file_id(row[0], "original_source", source["sha256"])
        original = graph.get(("research_file", identity))
        expected_parent = [dict(kind="paper", id=row[0], incarnation=paper["incarnation"])]
        if original is not None and (
            not original["active"] or original["parents"] != expected_parent
        ):
            raise ValueError("Survey import cannot silently restore retired original ownership")
        desired = desired_file(conn, identity)
        if (
            (original is None) != (desired is None)
            or original is not None
            and (
                desired["incarnation"] != original["incarnation"]
                or desired["parents"] != expected_parent
            )
        ):
            raise ValueError("Receiver original projection differs from its active lifetime")
        observed.append(
            dict(
                local_id=local,
                paper_id=row[0],
                paper_incarnation=paper["incarnation"],
                source_id=source["source_id"],
                document_hash=source["sha256"],
                file_id=identity,
                original=desired,
            )
        )
    identity = list_file_id(list_id)
    report = graph.get(("research_file", identity))
    expected_report_parent = [dict(kind="list", id=list_id, incarnation=parent["incarnation"])]
    if report is not None and (not report["active"] or report["parents"] != expected_report_parent):
        raise ValueError("Survey import cannot silently restore a retired report")
    target = desired_file(conn, identity)
    if (
        (report is None) != (target is None)
        or report is not None
        and (
            target["incarnation"] != report["incarnation"]
            or target["parents"] != expected_report_parent
        )
    ):
        raise ValueError("Receiver survey projection differs from its active lifetime")
    return dict(
        list_id=list_id,
        list_incarnation=parent["incarnation"],
        listing=dict(listing),
        sources=observed,
        target=target,
    )


@dataclass(frozen=True, slots=True)
class PreparedSurveyImport:
    _json: str = field(repr=False)
    _seal: str = field(repr=False)
    _originals: tuple = field(repr=False)
    _proof: object = field(repr=False)
    _proof_operation: dict = field(repr=False)
    _client: object = field(repr=False)

    def preview(self):
        data = _checked(self)
        current = data["observed"]["target"]
        decision = (
            "unchanged"
            if current and current["payload"] == data["proof_operation"]["payload"]
            else "preserve"
            if current and not data["replace"]
            else "replace"
            if current
            else "add"
        )
        return dict(
            list_id=data["list_id"],
            decision=decision,
            report_id=data["report_id"],
            state="prepared",
            replace=data["replace"],
            sources=len(data["sources"]),
        )


def _checked(prepared):
    if not isinstance(prepared, PreparedSurveyImport) or not hmac.compare_digest(
        prepared._seal, _seal(prepared._json)
    ):
        raise ValueError("Survey import requires its checked receiver preparation")
    data = json.loads(prepared._json)
    if (
        data["original_ids"] != [item.request for item in prepared._originals]
        or data["proof_operation"] != prepared._proof_operation
        or not prepared._proof.matches(prepared._proof_operation)
    ):
        raise ValueError("Survey import staged bytes or publication intent changed")
    return data


def prepare(
    database,
    archive,
    *,
    target_list_id,
    paper_mapping,
    replace=False,
    request_id=None,
    cancelled=lambda: False,
):
    """Verify/stage off-lock against explicit receiver owners; no research SQL writes."""
    survey_packages._cancel(cancelled)
    if type(replace) is not bool or not isinstance(paper_mapping, dict):
        raise ValueError("Choose an explicit receiver mapping and replacement policy")
    _identifier(target_list_id)
    database = Path(database).resolve(strict=True)
    archive = Path(archive).resolve(strict=True)
    stamp = file_change.version(archive)
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Survey import archive exceeds its byte bound")
    client = runtime(database=database)
    if client is None:
        raise ValueError("Survey report import requires an enrolled receiver")
    with zipfile.ZipFile(archive) as zipped:
        from paper_daily.lineage_packages import _metadata

        manifest, tables = _metadata(zipped, "manifest.json"), _metadata(zipped, "tables.json")
        if sum(info.file_size for info in zipped.infolist()) > MAX_ARCHIVE:
            raise ValueError("Survey import expanded archive exceeds its byte bound")
        portable = survey_packages.validate_package(zipped, manifest, tables, cancelled=cancelled)
        if portable is None:
            raise ValueError("The selected package has no saved survey report")
        sources = manifest.get("survey_sources", [])
        selected = {row["paper_id"] for row in sources}
        if (
            set(paper_mapping) != selected
            or any(not isinstance(value, str) or not value for value in paper_mapping.values())
            or len(set(paper_mapping.values())) != len(selected)
        ):
            raise ValueError("Survey import needs a complete distinct receiver paper mapping")
        with closing(_readonly_connection(database)) as conn:
            conn.execute("BEGIN")
            native = generation._identity(database)
            binding = _binding(conn, _tables(conn))
            observed = _targets_in(conn, client, target_list_id, paper_mapping, sources)
            configured = paths(conn)
            if configured is None:
                raise ValueError("Configure receiver artifact storage before survey import")
        store, root = configured
        request = (
            request_id
            or hashlib.sha256(
                canonical_json([portable["report"]["id"], target_list_id, paper_mapping, replace])
            ).hexdigest()
        )
        _identifier(request)
        originals, bindings = [], []
        entities = [
            dict(
                kind="list",
                id=target_list_id,
                incarnation=observed["list_incarnation"],
                revision=0,
                depends_on=None,
            )
        ]
        with tempfile.TemporaryDirectory(prefix=".survey-import-", dir=database.parent) as folder:
            for source, owner in zip(sources, observed["sources"], strict=True):
                survey_packages._cancel(cancelled)
                raw = survey_packages._read(
                    zipped,
                    source["path"],
                    source["sha256"],
                    source["size"],
                    survey_packages.MAX_PDF_BYTES,
                )
                selected_file = Path(folder) / (source["sha256"] + ".pdf")
                selected_file.write_bytes(raw)
                original = sync_source_files.prepare_source(
                    client,
                    owner["paper_id"],
                    selected_file,
                    document_hash=source["sha256"],
                    parent_incarnation=owner["paper_incarnation"],
                    store=store,
                    version_root=root,
                    request_id=_request(request, source["source_id"]),
                )
                previous = owner["original"]
                if previous is not None and previous["payload"] != json.loads(original.payload):
                    raise ValueError("Receiver original differs from the exact incoming version")
                incarnation = previous["incarnation"] if previous else original.request
                bindings.append(
                    {
                        key: owner[key]
                        for key in (
                            "source_id",
                            "paper_id",
                            "paper_incarnation",
                            "document_hash",
                            "file_id",
                        )
                    }
                    | dict(incarnation=incarnation)
                )
                entities.extend(
                    dict(kind=kind, id=identity, incarnation=life, revision=0, depends_on=None)
                    for kind, identity, life in (
                        ("paper", owner["paper_id"], owner["paper_incarnation"]),
                        ("research_file", owner["file_id"], incarnation),
                    )
                )
                originals.append(original)
        versions = dict(
            schema_version=2,
            workspace_id=client.journal.workspace_id,
            complete=False,
            entities=entities,
            documents=[],
            inputs_sha256=portable["report"]["inputs"]["prompt_hash"],
        )
        payload, blobs = sync_survey_files.encode(
            portable["report"], target_list_id, bindings, input_versions=versions
        )
        stage_bytes(store, blobs)
        target = observed["target"]
        operation = dict(
            version=2,
            operation_id=_request(request, "report"),
            workspace_id=client.journal.workspace_id,
            device_id=client.journal.device_id,
            entity_type="research_file",
            entity_id=list_file_id(target_list_id),
            action="put",
            base_revision=0,
            depends_on=None,
            payload=payload,
            incarnation=target["incarnation"] if target else _request(request, "report"),
            parents=[
                dict(kind="list", id=target_list_id, incarnation=observed["list_incarnation"])
            ],
            structure_revision=0,
        )
        proof, _body, _blobs = verify_closure(store, operation)
    survey_packages._cancel(cancelled)
    if file_change.version(archive) != stamp:
        raise ValueError("The selected survey package changed during preparation")
    data = dict(
        database=str(database),
        native=native,
        binding=binding,
        archive=str(archive),
        archive_version=stamp,
        list_id=target_list_id,
        mapping=paper_mapping,
        sources=sources,
        observed=observed,
        report_id=portable["report"]["id"],
        replace=replace,
        proof_operation=operation,
        original_ids=[item.request for item in originals],
    )
    encoded = canonical_json(data).decode()
    return PreparedSurveyImport(encoded, _seal(encoded), tuple(originals), proof, operation, client)


def publish_in(conn, prepared, *, cancelled=lambda: False):
    """Use the caller's transaction/savepoint; earlier unrelated edits are preserved."""
    data = _checked(prepared)
    survey_packages._cancel(cancelled)
    main = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), None)
    if (
        not conn.in_transaction
        or main is None
        or Path(main).resolve() != Path(data["database"])
        or generation._identity(data["database"]) != data["native"]
        or canonical_json(_binding(conn, _tables(conn))) != canonical_json(data["binding"])
    ):
        raise ValueError("Survey import receiver database/device binding changed")
    if canonical_json(file_change.version(Path(data["archive"]))) != canonical_json(
        data["archive_version"]
    ):
        raise ValueError("The selected survey package changed before publication")
    client = prepared._client
    operation = data["proof_operation"]
    payload, request = operation["payload"], operation["operation_id"]
    current = desired_file(conn, operation["entity_id"])
    prior = conn.execute(
        "SELECT operation FROM research_file_versions WHERE operation_id=?", (request,)
    ).fetchone()
    if prior:
        saved = json.loads(prior[0])
        if (
            saved["payload"] != payload
            or saved["parents"] != operation["parents"]
            or current != saved
            or not sync_survey_files.active(
                lambda kind, identity: client._optimistic_graph(conn)[0].get((kind, identity)),
                saved,
            )
        ):
            raise ValueError(
                "Survey import request no longer matches the current exact publication"
            )
        return dict(state="unchanged", report_id=data["report_id"], operation=saved)
    observed = _targets_in(conn, client, data["list_id"], data["mapping"], data["sources"])
    if canonical_json(observed) != canonical_json(data["observed"]):
        raise ValueError("Survey import receiver targets changed after review")
    if current is not None and current["payload"] == payload:
        return dict(state="unchanged", report_id=data["report_id"], operation=current)
    if current is not None and not data["replace"]:
        return dict(state="preserved", report_id=data["report_id"], operation=current)
    conn.execute("SAVEPOINT survey_package_import")
    try:
        for original, expected in zip(prepared._originals, payload["source_bindings"], strict=True):
            survey_packages._cancel(cancelled)
            actual = sync_source_files.publish_source_in(conn, client, original)
            if (
                actual["entity_id"] != expected["file_id"]
                or actual["incarnation"] != expected["incarnation"]
            ):
                raise ValueError("Survey import original owner/version changed")
        survey_packages._cancel(cancelled)
        result = client.new_graph_operation_in(
            conn, "research_file", operation["entity_id"], payload, operation_id=request
        )
        with sync_capture.suppress_capture(conn):
            if not client.journal.apply_in(conn, result, client.writer)["applied"]:
                raise ValueError("Survey report import was not applied atomically")
        survey_packages._cancel(cancelled)
        conn.execute("RELEASE survey_package_import")
    except BaseException:
        conn.execute("ROLLBACK TO survey_package_import")
        conn.execute("RELEASE survey_package_import")
        raise
    finally:
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
    return dict(state="imported", report_id=data["report_id"], operation=result)


def publish(prepared, *, cancelled=lambda: False):
    """Pin the captured receiver; commit once, then complete local report bytes off-lock."""
    data = _checked(prepared)
    with closing(generation._connect(data["database"])) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        result = publish_in(conn, prepared, cancelled=cancelled)
    if result["state"] != "preserved":
        from paper_daily.survey_publication import complete_pending

        complete_pending(
            prepared._client, data["list_id"], expected=result["operation"],
            expected_database=data["native"], cancelled=cancelled)
    return result
