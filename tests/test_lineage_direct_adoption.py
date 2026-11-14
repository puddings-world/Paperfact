"""Direct saved-report adoption uses selected PDFs, not a matching input package."""

import json
import zipfile
from contextlib import closing
from dataclasses import replace

import pytest
from test_lineage_import_review import corpus as corpus
from test_lineage_import_review import dump
from test_lineage_import_review import native_shared as native_shared
from test_lineage_import_review import shared as shared
from test_lineage_jobs import work
from test_lineage_matching_adoption import legacy as legacy
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import lineage_projection, lineage_sets
from paper_daily.lineage_direct_adoption import DirectAdoption
from paper_daily.workspace_service import Cancelled, Ticket


@pytest.fixture
def selected(legacy, tmp_path):
    client, importer, archive, _receipt, row, _review = legacy
    paths = {}
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
        for item in manifest["lineage_sources"]:
            path = tmp_path / (item["source_id"] + ".pdf")
            path.write_bytes(source.read("files/" + item["path"]))
            paths[item["source_id"]] = path
    service = DirectAdoption(client.journal.path, importer.root)
    return service, paths, row, client


def prepare(selected, **kwargs):
    service, originals, row, _client = selected
    return work(service.prepare, row["paper_id"], row["corpus_key"], originals, **kwargs)


def test_direct_selection_preserves_exact_saved_science_and_only_adds_native_authority(
    selected, monkeypatch
):
    service, paths, row, client = selected
    before = dump(client)
    # The service must not require an existing matching ZIP or create one.
    monkeypatch.setattr(zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("No list package needed"))
    info = work(service.inspect, row["paper_id"], row["corpus_key"])
    assert info["row"] == row and len(info["sources"]) == len(paths) == 3
    plan = prepare(selected)
    assert plan.preview()["row"] == row and not plan.preview()["applied"]
    assert dump(client) == before
    result = work(service.apply, plan)
    assert result["state"] == "adopted_locally" and result["lineage_adopted"] == 1
    assert row in lineage_sets.saved(client.journal.path, row["paper_id"])
    with closing(client.journal._connect()) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM " + lineage_projection.HISTORY + " WHERE operation_id=?",
                (result["request_id"],),
            ).fetchone()[0]
            == 1
        )
    after = dump(client)
    assert work(service.apply, plan)["state"] == "previously_applied"
    assert dump(client) == after


@pytest.mark.parametrize("failure", ["missing", "extra", "wrong-pdf", "cancel"])
def test_failed_selection_does_not_publish_or_change_saved_research(selected, tmp_path, failure):
    service, paths, row, client = selected
    before = dump(client)
    paths = dict(paths)
    ticket = Ticket()
    if failure == "missing":
        paths.pop(next(iter(paths)))
    elif failure == "extra":
        paths["extra"] = next(iter(paths.values()))
    elif failure == "wrong-pdf":
        wrong = tmp_path / "wrong.pdf"
        wrong.write_bytes(b"not the saved original")
        paths[next(iter(paths))] = wrong
    else:
        ticket.cancel()
    with pytest.raises((ValueError, Cancelled)):
        work(service.prepare, row["paper_id"], row["corpus_key"], paths, ticket=ticket)
    assert dump(client) == before and row in lineage_sets.saved(
        client.journal.path, row["paper_id"]
    )


def test_cancelled_apply_and_changed_report_leave_private_row_intact(selected):
    service, _paths, row, client = selected
    plan = prepare(selected)
    before = dump(client)
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        work(service.apply, plan, ticket=ticket)
    assert dump(client) == before
    with client.journal.transaction() as conn:
        from paper_daily import sync_capture

        with sync_capture.suppress_capture(conn):
            conn.execute(
                "UPDATE paper_lineage_sets SET written_at=? WHERE corpus_key=?",
                ("2026-11-01T00:00:00+00:00", row["corpus_key"]),
            )
    changed = dump(client)
    with pytest.raises(ValueError):
        work(service.apply, plan)
    assert dump(client) == changed


def test_forged_plan_or_foreign_service_cannot_grant_adoption(selected):
    service, _paths, row, client = selected
    plan = prepare(selected)
    data = json.loads(plan.context)
    data["row"]["written_at"] = "forged"
    before = dump(client)
    with pytest.raises(ValueError, match="unchanged reviewed plan"):
        work(service.apply, replace(plan, context=json.dumps(data)))
    other = DirectAdoption(client.journal.path, service.receiver.root)
    with pytest.raises(ValueError, match="unchanged reviewed plan"):
        work(other.apply, plan)
    assert dump(client) == before


def test_late_scientific_write_failure_rolls_back_source_grants_history_and_receipt(
    selected, monkeypatch
):
    service, _paths, row, client = selected
    plan = prepare(selected)
    before = dump(client)
    original = service.receiver.client.journal.apply_in

    def fail(conn, operation, writer):
        result = original(conn, operation, writer)
        if operation["payload"].get("feature") == "lineage":
            raise OSError("Injected failure after scientific projection")
        return result

    monkeypatch.setattr(service.receiver.client.journal, "apply_in", fail)
    with pytest.raises(OSError):
        work(service.apply, plan)
    assert dump(client) == before and row in lineage_sets.saved(
        client.journal.path, row["paper_id"]
    )
    monkeypatch.setattr(service.receiver.client.journal, "apply_in", original)
    assert work(service.apply, plan)["state"] == "adopted_locally"


def test_aggregate_page_budget_and_cancellation_during_pdf_verification_publish_nothing(
    selected, monkeypatch
):
    from paper_daily import lineage_packages

    _service, _paths, _row, client = selected
    before = dump(client)
    monkeypatch.setattr(lineage_packages, "MAX_TOTAL_PAGES", 0)
    with pytest.raises(ValueError, match="aggregate page budget"):
        prepare(selected)
    assert dump(client) == before
    monkeypatch.setattr(lineage_packages, "MAX_TOTAL_PAGES", 4096)
    original = lineage_packages.verify_original
    ticket = Ticket()

    def cancelled(*args, **kwargs):
        ticket.cancel()
        return original(*args, **kwargs)

    monkeypatch.setattr(lineage_packages, "verify_original", cancelled)
    with pytest.raises(Cancelled):
        prepare(selected, ticket=ticket)
    assert dump(client) == before


def fresh_sources(selected, tmp_path):
    import hashlib

    from paper_daily import lineage_content, sync_capture

    service, paths, row, client = selected
    row = json.loads(json.dumps(row))
    body = lineage_sets.decode(row["body_json"])
    ids = {}
    for source in body["report"]["sources"]:
        if source["availability"] != "available":
            continue
        data = paths[source["id"]].read_bytes() + b"\n%new exact PDF version\n"
        old_id = source["id"]
        source["document_hash"] = hashlib.sha256(data).hexdigest()
        source["id"] = lineage_content.source_id(source["identity"], source["document_hash"])
        ids[old_id] = source["id"]
        path = tmp_path / (source["id"] + "-new-original.pdf")
        path.write_bytes(data)
        paths[source["id"]] = path
        del paths[old_id]

    def remap(value):
        if isinstance(value, str):
            return ids.get(value, value)
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    body = remap(body)
    report = body["report"]
    for statement in report["statements"]:
        for passage in statement["passages"]:
            passage["id"] = lineage_content.passage_id(passage)
        statement["id"] = lineage_content.statement_id(report["focal"], statement)
        statement["requirements"] = lineage_content.requirements(report["focal"], statement)
    report["id"] = lineage_content.hashed(
        {key: value for key, value in report.items() if key != "id"}
    )
    row.update(
        body_json=lineage_sets.canonical(body),
        source_hash=lineage_sets.source_hash(body),
        document_hash=body["report"]["sources"][0]["document_hash"],
    )
    lineage_sets.validate_row(row)
    with client.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "UPDATE paper_lineage_sets SET body_json=?,source_hash=?,document_hash=? "
            "WHERE paper_id=? AND corpus_key=?",
            (
                row["body_json"],
                row["source_hash"],
                row["document_hash"],
                row["paper_id"],
                row["corpus_key"],
            ),
        )
    return service, paths, row, client


def test_new_original_grants_roll_back_with_a_late_scientific_failure(
    selected, tmp_path, monkeypatch
):
    selected = fresh_sources(selected, tmp_path)
    service, _paths, row, client = selected
    plan = prepare(selected)
    before = dump(client)
    original = service.receiver.client.journal.apply_in

    def fail(conn, operation, writer):
        result = original(conn, operation, writer)
        if operation["payload"].get("feature") == "lineage":
            raise OSError("Late failure after new original grants")
        return result

    monkeypatch.setattr(service.receiver.client.journal, "apply_in", fail)
    with pytest.raises(OSError):
        work(service.apply, plan)
    assert dump(client) == before
    assert row in lineage_sets.saved(client.journal.path, row["paper_id"])
    monkeypatch.setattr(service.receiver.client.journal, "apply_in", original)
    assert work(service.apply, plan)["originals"] == 3


def test_direct_new_sources_survive_real_sync_authority_backup_and_fresh_peer_recovery(
    selected, pair, tmp_path, tmp_path_factory
):
    import sqlite3

    from test_sync_authority_restore_native import join_and_download, publish

    from paper_daily import lineage_bound_originals
    from paper_daily import research_generation as generation
    from paper_daily.manual_highlight_ops import observe_owner

    selected = fresh_sources(selected, tmp_path)
    service, paths, row, client = selected
    assert work(service.apply, prepare(selected))["state"] == "adopted_locally"
    recovered = publish(pair, tmp_path, client=service.receiver.client)
    destination = tmp_path_factory.mktemp("direct-lineage-recovered-peer") / "workspace"

    def choose(database):
        with closing(sqlite3.connect(database)) as conn:
            encoded = conn.execute(
                "SELECT body_json FROM paper_lineage_sets WHERE corpus_key=?", (row["corpus_key"],)
            ).fetchone()[0]
        return [item["paper_id"] for item in lineage_sets.decode(encoded)["bindings"]]

    database = join_and_download(
        recovered, client.journal.path, destination, choose, missing_primary=2
    )
    with closing(sqlite3.connect(database)) as conn:
        focal = conn.execute(
            "SELECT paper_id FROM paper_lineage_sets WHERE corpus_key=?", (row["corpus_key"],)
        ).fetchone()[0]
    saved = next(
        item
        for item in lineage_sets.saved(database, focal)
        if item["corpus_key"] == row["corpus_key"]
    )
    body, expected = lineage_sets.decode(saved["body_json"]), lineage_sets.decode(row["body_json"])
    assert body["report"] == expected["report"] and body["generation"] == expected["generation"]
    owner = observe_owner(database, focal, expected_native=generation._identity(database))
    for source in body["report"]["sources"]:
        proof = work(lineage_bound_originals.prepare, owner, saved, source["id"])
        actual = work(lineage_bound_originals.for_delivery, proof, owner, saved, source["id"])
        assert actual == paths[source["id"]].read_bytes()


def test_valid_pdf_hash_cannot_authorize_a_falsely_located_saved_quote(selected):
    from paper_daily import lineage_content, sync_capture

    service, paths, row, client = selected
    row = json.loads(json.dumps(row))
    body = lineage_sets.decode(row["body_json"])
    passage = body["report"]["statements"][0]["passages"][0]
    assert passage["location"]["state"] == "located"
    passage["quote"] = "This synthetic sentence is absent from the original paper."
    passage["id"] = lineage_content.passage_id(passage)
    report = body["report"]
    report["id"] = lineage_content.hashed(
        {key: value for key, value in report.items() if key != "id"}
    )
    row["body_json"] = lineage_sets.canonical(body)
    lineage_sets.validate_row(row)
    with client.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "UPDATE paper_lineage_sets SET body_json=? WHERE corpus_key=?",
            (row["body_json"], row["corpus_key"]),
        )
    before = dump(client)
    with pytest.raises(ValueError, match="located quote"):
        work(service.prepare, row["paper_id"], row["corpus_key"], paths)
    assert dump(client) == before


def test_foreign_service_cannot_apply_review_even_if_runtime_object_ids_alias(
    selected, monkeypatch
):
    from paper_daily import lineage_direct_adoption as module

    service, _paths, _row, client = selected
    # Model address reuse at the process-local signature seam, without forcing
    # garbage collection or weakening any source/row/publication checks.
    monkeypatch.setattr(module, "id", lambda _value: 42, raising=False)
    plan = prepare(selected)
    other = DirectAdoption(client.journal.path, service.receiver.root)
    before = dump(client)
    with pytest.raises(ValueError, match="unchanged reviewed plan"):
        work(other.apply, plan)
    assert dump(client) == before
    assert work(service.apply, plan)["state"] == "adopted_locally"
