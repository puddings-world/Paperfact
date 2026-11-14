"""Explicit native import decisions retain science/history without bypassing default guards."""

import json
import zipfile
from contextlib import closing
from dataclasses import replace

import pytest
from test_lineage_bundle_journey import shared as shared
from test_lineage_enrolled_import import mapping_options, receiver
from test_lineage_enrolled_import import native_shared as native_shared
from test_lineage_jobs import work
from test_package_import import package as package
from test_research_lineage import corpus as corpus
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import claim_content, lineage_content, lineage_projection, lineage_sets
from paper_daily.lineage_import_review import Decision, ReviewRequired
from paper_daily.workspace_service import Cancelled, Ticket


def changed_package(source, destination):
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(destination, "w") as output:
        for name in old.namelist():
            data = old.read(name)
            if name == "tables.json":
                tables = json.loads(data)
                row = tables["paper_lineage_sets"][0]
                body = lineage_sets.decode(row["body_json"])
                statement = body["report"]["statements"][0]
                statement["text"] = "An alternative bounded interpretation for explicit comparison."
                statement["id"] = lineage_content.statement_id(body["report"]["focal"], statement)
                body["report"]["id"] = claim_content.hashed(
                    {k: v for k, v in body["report"].items() if k != "id"}
                )
                lineage_sets.validate(body)
                row["body_json"] = lineage_sets.canonical(body)
                row["written_at"] = "2026-11-14T05:00:00+00:00"
                data = json.dumps(tables).encode()
            output.writestr(name, data)
    return destination


def dump(client):
    with closing(client.journal._connect()) as conn:
        return tuple(conn.iterdump())


@pytest.fixture
def compared(native_shared, pair, tmp_path):
    client, importer = receiver(pair)
    first = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    receipt = work(importer.apply, first)
    archive = changed_package(native_shared[0], tmp_path / "updated.zip")
    before = dump(client)
    with pytest.raises(ReviewRequired) as caught:
        work(importer.prepare, archive, **mapping_options(receipt))
    assert dump(client) == before
    return client, importer, archive, receipt, caught.value.review


@pytest.mark.parametrize("choice", ["keep", "replace"])
def test_explicit_native_choice_preserves_old_version_and_exact_retry(compared, choice):
    client, importer, archive, receipt, review = compared
    assert len(review.conflicts) == 1 and review.conflicts[0]["can_replace"]
    old = review.conflicts[0]["current"]
    incoming = json.loads(json.dumps(review.conflicts[0]["incoming"]))
    portable_to_local = {
        m["portable_id"]: m["local_id"] for m in receipt["identity_mapping"].values()
    }
    for binding in incoming["bindings"]:
        binding["paper_id"] = portable_to_local[binding["paper_id"]]
    key = review.conflicts[0]["id"]
    decision = review.decide({key: choice})
    before = dump(client)
    prepared = work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    )
    assert dump(client) == before
    result = work(importer.apply, prepared)
    assert result["lineage_preserved" if choice == "keep" else "lineage_replaced"] == 1
    local = receipt["identity_mapping"]["focal"]["local_id"]
    current = lineage_sets.decode(lineage_sets.saved(client.journal.path, local)[0]["body_json"])
    assert current == (old if choice == "keep" else incoming)
    with closing(client.journal._connect()) as conn:
        from paper_daily.lineage_wire import decode_row

        reports = [
            lineage_sets.decode(decode_row(conn, json.loads(row[0])["payload"])["body_json"])
            for row in conn.execute("SELECT operation_json FROM " + lineage_projection.HISTORY)
        ]
    assert old in reports
    assert len(reports) == (1 if choice == "keep" else 2)
    pending = client.journal.pending()
    assert work(importer.apply, prepared)["state"] == "previously_applied"
    assert client.journal.pending() == pending


def test_forged_decision_or_incomplete_choices_cannot_publish(compared):
    client, importer, archive, receipt, review = compared
    before = dump(client)
    with pytest.raises(ValueError, match="every compared"):
        review.decide({})
    with pytest.raises(ValueError, match="cannot be replaced"):
        review.decide({review.conflicts[0]["id"]: True})
    genuine = review.decide({review.conflicts[0]["id"]: "replace"})
    for forged in (Decision(genuine._json, "wrong"), replace(genuine, _json="{}"), {}):
        with pytest.raises(ValueError, match="review|decision"):
            work(importer.prepare, archive, lineage_decision=forged, **mapping_options(receipt))
    assert dump(client) == before


def test_approved_choice_cannot_overwrite_sql_changed_since_comparison(compared):
    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    with client.journal.transaction() as conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-14T06:00:00+00:00'")
    before = dump(client)
    with pytest.raises(ValueError, match="outside|changed"):
        work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt))
    assert dump(client) == before


def test_cancel_after_approved_preview_rolls_back_all_research(compared):
    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    prepared = work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    )
    before = dump(client)
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        work(importer.apply, prepared, ticket=ticket)
    assert dump(client) == before


def test_late_replacement_writer_failure_keeps_both_history_and_old_research(compared, monkeypatch):
    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    prepared = work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    )
    before = dump(client)
    original = importer.client.writer

    def failed(conn, operation):
        original(conn, operation)
        if operation["payload"].get("feature") == "lineage":
            raise ValueError("Late scientific writer failure")

    monkeypatch.setattr(importer.client, "writer", failed)
    with pytest.raises(ValueError, match="Late scientific"):
        work(importer.apply, prepared)
    assert dump(client) == before
    monkeypatch.setattr(importer.client, "writer", original)
    again = work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt))
    assert work(importer.apply, again)["lineage_replaced"] == 1


def test_changed_archive_cannot_reuse_old_scientific_approval(compared, tmp_path):
    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    different = tmp_path / "another.zip"
    with zipfile.ZipFile(archive) as old, zipfile.ZipFile(different, "w") as new:
        for name in old.namelist():
            data = old.read(name)
            if name == "manifest.json":
                value = json.loads(data)
                value["list"]["name"] = "Another incoming package"
                data = json.dumps(value).encode()
            new.writestr(name, data)
    before = dump(client)
    with pytest.raises(ValueError, match="comparison changed"):
        work(importer.prepare, different, lineage_decision=decision, **mapping_options(receipt))
    assert dump(client) == before


def test_missing_native_marker_never_grants_replacement_but_can_keep_saved_result(compared):
    client, importer, archive, receipt, review = compared
    old = review.conflicts[0]["current"]
    old_decision = review.decide({review.conflicts[0]["id"]: "replace"})
    with client.journal.transaction() as conn:
        conn.execute("DELETE FROM " + lineage_projection.TABLE)
    before = dump(client)
    with pytest.raises(ValueError, match="comparison changed"):
        work(importer.prepare, archive, lineage_decision=old_decision, **mapping_options(receipt))
    with pytest.raises(ReviewRequired) as caught:
        work(importer.prepare, archive, **mapping_options(receipt))
    fresh = caught.value.review
    assert not fresh.conflicts[0]["can_replace"]
    with pytest.raises(ValueError, match="cannot be replaced"):
        fresh.decide({fresh.conflicts[0]["id"]: "replace"})
    decision = fresh.decide({fresh.conflicts[0]["id"]: "keep"})
    prepared = work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    )
    assert dump(client) == before
    assert work(importer.apply, prepared)["lineage_preserved"] == 1
    local = receipt["identity_mapping"]["focal"]["local_id"]
    assert (
        lineage_sets.decode(lineage_sets.saved(client.journal.path, local)[0]["body_json"]) == old
    )
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM " + lineage_projection.TABLE).fetchone()[0] == 0


def test_replacement_and_both_versions_reach_peer_and_independent_backup(
    compared,
    pair,
    native_shared,
    tmp_path,
):
    from test_sync_files import drain
    from test_sync_recovery import archive_rows

    from paper_daily import sync_recovery
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_files import file_id
    from paper_daily.sync_research import research_projection_writer
    from paper_daily.sync_source_files import resolved

    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    prepared = work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    )
    work(importer.apply, prepared)
    service, _same, peer, files, peer_files, token, peer_token = pair
    for operation in client.journal.pending():
        if operation["entity_type"] == "research_file":
            drain(lambda op=operation: files.upload(op), "uploaded")
    for _ in range(20):
        synced = importer.client.sync_once(service, token, prepare_push=files.ready_to_push)
        if not synced["pending"]:
            break
    assert synced["pending"] == 0 and synced["conflicts"] == 0
    from test_package_import import enroll_capture

    enroll_capture(peer)
    receiving = SyncClient.attach_existing(
        peer.journal, peer.writer, projection_writer=research_projection_writer
    )
    for _ in range(20):
        received = receiving.sync_once(service, peer_token)
        if not received["received"]:
            break
    assert received["conflicts"] == 0
    local = receipt["identity_mapping"]["focal"]["local_id"]
    peer_row = lineage_sets.saved(peer.journal.path, local)[0]
    assert (
        "alternative bounded interpretation"
        in json.loads(peer_row["body_json"])["report"]["statements"][0]["text"].lower()
    )
    with closing(peer.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM " + lineage_projection.HISTORY).fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM research_file_applied").fetchone()[0] == 0
    body = json.loads(peer_row["body_json"])
    for source, binding in zip(body["report"]["sources"], body["bindings"], strict=True):
        old = next(
            old
            for old, mapped in receipt["identity_mapping"].items()
            if mapped["local_id"] == binding["paper_id"]
        )
        portable = receipt["identity_mapping"][old]["portable_id"]
        key = file_id(portable, "original_source", source["document_hash"])
        drain(lambda selected=key: peer_files.download(selected), "bound")
        with closing(peer.journal._connect()) as conn:
            assert (
                resolved(conn, portable, source["document_hash"]).read_bytes()
                == native_shared[2][old]
            )
    from paper_daily import lineage_versions
    from paper_daily import research_generation as generation
    from paper_daily.manual_highlight_ops import observe_owner

    owner = observe_owner(
        peer.journal.path, local, expected_native=generation._identity(peer.journal.path)
    )
    catalog = work(lineage_versions.collect, owner)
    assert catalog["total"] == 2 and sum(item["current"] for item in catalog["items"]) == 1
    assert {json.loads(item["row"]["body_json"])["report"]["id"] for item in catalog["items"]} == {
        review.conflicts[0]["current"]["report"]["id"],
        review.conflicts[0]["incoming"]["report"]["id"],
    }
    backup = tmp_path / "reviewed-replacement.zip"
    manifest = sync_recovery.create(client.journal.path, backup, blob_store=files.store)
    assert sync_recovery.inspect(backup) == manifest
    assert len(archive_rows(backup, lineage_projection.HISTORY)) == 2
    restored = tmp_path / "reviewed-detached"
    sync_recovery.restore_detached(backup, restored)
    assert lineage_sets.saved(restored / "papers.db", local) == lineage_sets.saved(
        client.journal.path, local
    )


def test_lineage_approval_cannot_authorize_a_package_without_lineage(compared, package):
    client, importer, _archive, _receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    before = dump(client)
    with pytest.raises(ValueError, match="no Lineage comparison"):
        work(importer.prepare, package[0], lineage_decision=decision, allow_new_namespace=True)
    assert dump(client) == before
