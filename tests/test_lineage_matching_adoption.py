"""Reviewed exact-content adoption preserves private legacy science without AI."""

import json
import zipfile
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_lineage_enrolled_import import mapping_options, receiver
from test_lineage_import_review import changed_package, dump
from test_lineage_import_review import corpus as corpus
from test_lineage_import_review import native_shared as native_shared
from test_lineage_import_review import shared as shared
from test_lineage_jobs import work
from test_sync_files import codec as codec
from test_sync_files import drain
from test_sync_files import pair as pair

from paper_daily import lineage_projection, lineage_sets, llm, sync_capture
from paper_daily.lineage_import_review import Decision, ReviewRequired
from paper_daily.workspace_service import Cancelled, Ticket


@pytest.fixture
def legacy(native_shared, pair, tmp_path, monkeypatch):
    client, importer = receiver(pair)
    receipt = work(
        importer.apply, work(importer.prepare, native_shared[0], allow_new_namespace=True)
    )
    corpus_id = str(uuid4())
    archive = tmp_path / "matching-legacy-analysis.zip"
    legacy_row = None
    with zipfile.ZipFile(native_shared[0]) as source, zipfile.ZipFile(archive, "w") as output:
        for name in source.namelist():
            data = source.read(name)
            if name == "tables.json":
                tables = json.loads(data)
                row = tables["paper_lineage_sets"][0]
                body = lineage_sets.decode(row["body_json"])
                body["corpus_id"] = corpus_id
                row.update(
                    corpus_key=corpus_id,
                    body_json=lineage_sets.canonical(body),
                    source_hash=lineage_sets.source_hash(body),
                )
                legacy_row = json.loads(json.dumps(row))
                local = lineage_sets.decode(legacy_row["body_json"])
                for binding in local["bindings"]:
                    binding["paper_id"] = receipt["identity_mapping"][binding["paper_id"]][
                        "local_id"
                    ]
                legacy_row["body_json"] = lineage_sets.canonical(local)
                legacy_row["paper_id"] = local["bindings"][0]["paper_id"]
                lineage_sets.validate_row(legacy_row)
                data = json.dumps(tables).encode()
            elif name == "manifest.json":
                manifest = json.loads(data)
                for item in manifest["lineage_sources"]:
                    item["corpus_key"] = corpus_id
                data = json.dumps(manifest).encode()
            output.writestr(name, data)
    # A real pre-native row: no scientific graph/head/history exists for this new corpus.
    with client.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
            tuple(legacy_row[k] for k in lineage_sets.COLUMNS.split()),
        )
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("Adoption invokes no AI")
    )
    before = dump(client)
    with pytest.raises(ReviewRequired) as caught:
        work(importer.prepare, archive, **mapping_options(receipt))
    assert dump(client) == before
    review = caught.value.review
    assert len(review.conflicts) == 1 and review.conflicts[0]["can_adopt"]
    assert not review.conflicts[0]["can_replace"]
    return client, importer, archive, receipt, legacy_row, review


def planned(legacy, choice="adopt"):
    _client, importer, archive, receipt, _row, review = legacy
    decision = review.decide({review.conflicts[0]["id"]: choice})
    return work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    ), decision


def test_exact_adoption_preserves_row_model_and_sources_and_has_retry_safe_native_history(legacy):
    client, importer, archive, receipt, row, review = legacy
    before = dump(client)
    prepared, decision = planned(legacy)
    assert dump(client) == before
    result = work(importer.apply, prepared)
    assert result["lineage_adopted"] == 1
    assert lineage_sets.saved(client.journal.path, row["paper_id"])[
        -1
    ] == row or row in lineage_sets.saved(client.journal.path, row["paper_id"])
    with closing(client.journal._connect()) as conn:
        marker, operation = lineage_projection._marker(conn, review.conflicts[0]["id"])
        assert (
            marker["active"]
            and operation["payload"]["data"]["body_json"]["generation"]
            == json.loads(row["body_json"])["generation"]
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM " + lineage_projection.HISTORY + " WHERE entity_id=?",
                (operation["entity_id"],),
            ).fetchone()[0]
            == 1
        )
    after = dump(client)
    assert work(importer.apply, prepared)["state"] == "previously_applied"
    assert dump(client) == after
    again = work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt))
    assert work(importer.apply, again)["state"] == "previously_applied"
    assert dump(client) == after


def test_keep_or_cancel_does_not_make_unowned_science_native(legacy):
    client, importer, _archive, _receipt, row, review = legacy
    before = dump(client)
    prepared, _decision = planned(legacy)
    cancelled = Ticket()
    cancelled.cancel()
    with pytest.raises(Cancelled):
        work(importer.apply, prepared, ticket=cancelled)
    assert dump(client) == before
    kept, _decision = planned(legacy, "keep")
    assert work(importer.apply, kept)["lineage_preserved"] == 1
    assert row in lineage_sets.saved(client.journal.path, row["paper_id"])
    with closing(client.journal._connect()) as conn:
        assert lineage_projection._marker(conn, review.conflicts[0]["id"])[0] is None


def test_exact_decision_cannot_be_forged_or_used_after_sql_change(legacy):
    client, importer, archive, receipt, _row, review = legacy
    decision = review.decide({review.conflicts[0]["id"]: "adopt"})
    before = dump(client)
    for forged in (Decision(decision._json, "bad"), replace(decision, _json="{}")):
        with pytest.raises(ValueError):
            work(importer.prepare, archive, lineage_decision=forged, **mapping_options(receipt))
    assert dump(client) == before
    with client.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-14T16:00:00+00:00'")
    changed = dump(client)
    with pytest.raises(ValueError, match="changed"):
        work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt))
    assert dump(client) == changed


def test_late_failure_after_private_row_consumption_rolls_back_science_outbox_and_receipt(
    legacy, monkeypatch
):
    client, importer, _archive, _receipt, row, _review = legacy
    prepared, _decision = planned(legacy)
    before = dump(client)
    original = importer.client.writer

    def failure(conn, operation):
        original(conn, operation)
        if operation["payload"].get("feature") == "lineage":
            assert lineage_sets.validate_row(row)
            raise ValueError("Failure after exact adoption write")

    monkeypatch.setattr(importer.client, "writer", failure)
    with pytest.raises(ValueError, match="after exact"):
        work(importer.apply, prepared)
    assert dump(client) == before
    monkeypatch.setattr(importer.client, "writer", original)
    assert work(importer.apply, planned(legacy)[0])["lineage_adopted"] == 1


def test_changed_target_after_preview_preserves_private_result(legacy):
    client, importer, _archive, _receipt, row, _review = legacy
    prepared, _decision = planned(legacy)
    with client.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "UPDATE paper_lineage_sets SET written_at='2026-11-14T17:00:00+00:00' "
            "WHERE paper_id=? AND corpus_key=?",
            (row["paper_id"], row["corpus_key"]),
        )
    changed = dump(client)
    with pytest.raises(ValueError, match="changed"):
        work(importer.apply, prepared)
    assert dump(client) == changed


def test_adopted_report_and_three_originals_reach_an_actual_peer(legacy, pair, native_shared):
    client, importer, _archive, receipt, row, _review = legacy
    work(importer.apply, planned(legacy)[0])
    server, _same, peer, files, peer_files, token, peer_token = pair
    for operation in client.journal.pending():
        if operation["entity_type"] == "research_file":
            drain(lambda op=operation: files.upload(op), "uploaded")
    for _ in range(20):
        result = importer.client.sync_once(server, token, prepare_push=files.ready_to_push)
        if not result["pending"]:
            break
    assert result["pending"] == result["conflicts"] == 0
    from test_package_import import enroll_capture

    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_projection_writer
    from paper_daily.sync_source_files import resolved

    enroll_capture(peer)
    receiving = SyncClient.attach_existing(
        peer.journal, peer.writer, projection_writer=research_projection_writer
    )
    receiving.sync_once(server, peer_token)
    assert row in lineage_sets.saved(peer.journal.path, row["paper_id"])
    body = lineage_sets.decode(row["body_json"])
    science = next(
        event["operation"]
        for event in receiving.history()
        if event["operation"]["payload"].get("feature") == "lineage"
        and event["operation"]["payload"]["key"] == row["corpus_key"]
    )
    for pin in science["source_dependencies"]:
        drain(lambda key=pin["file_id"]: peer_files.download(key), "bound")
    with closing(peer.journal._connect()) as conn:
        for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
            old = next(
                key
                for key, value in receipt["identity_mapping"].items()
                if value["local_id"] == binding["paper_id"]
            )
            assert (
                resolved(
                    conn, receipt["identity_mapping"][old]["portable_id"], source["document_hash"]
                ).read_bytes()
                == native_shared[2][old]
            )


@pytest.mark.parametrize("replace_all", [False, True])
def test_general_import_replace_does_not_authorize_private_adoption(legacy, replace_all):
    client, importer, archive, receipt, _row, review = legacy
    before = dump(client)
    with pytest.raises(ReviewRequired) as caught:
        work(importer.prepare, archive, replace=replace_all, **mapping_options(receipt))
    assert caught.value.review.conflicts[0]["can_adopt"]
    with pytest.raises(ValueError):
        review.decide({review.conflicts[0]["id"]: "replace"})
    assert dump(client) == before


def test_different_scientific_content_is_never_adopted_or_covered_by_old_approval(legacy, tmp_path):
    client, importer, archive, receipt, _row, review = legacy
    decision = review.decide({review.conflicts[0]["id"]: "adopt"})
    different = changed_package(archive, tmp_path / "different-science.zip")
    before = dump(client)
    with pytest.raises(ReviewRequired) as caught:
        work(importer.prepare, different, **mapping_options(receipt))
    assert not caught.value.review.conflicts[0]["can_adopt"]
    assert not caught.value.review.conflicts[0]["can_replace"]
    with pytest.raises(ValueError):
        caught.value.review.decide({caught.value.review.conflicts[0]["id"]: "adopt"})
    with pytest.raises(ValueError, match="comparison changed"):
        work(importer.prepare, different, lineage_decision=decision, **mapping_options(receipt))
    assert dump(client) == before


@pytest.mark.parametrize("record", ["journal", "history", "missing-marker"])
def test_known_native_authority_cannot_be_recreated_through_private_adoption(legacy, record):
    from paper_daily.sync_journal import canonical_operation

    client, importer, archive, receipt, _row, review = legacy
    prepared, _decision = planned(legacy)
    science = next(
        op for op in json.loads(prepared.operations) if op["payload"].get("feature") == "lineage"
    )
    identity = review.conflicts[0]["id"]
    if record == "missing-marker":
        work(importer.apply, prepared)
        with client.journal.transaction() as conn:
            conn.execute(
                "DELETE FROM " + lineage_projection.TABLE + " WHERE entity_id=?", (identity,)
            )
    else:
        with client.journal.transaction() as conn:
            if record == "history":
                conn.execute(
                    "INSERT INTO " + lineage_projection.HISTORY + " VALUES(?,?,?)",
                    (science["operation_id"], identity, canonical_operation(science)),
                )
            else:
                import hashlib

                encoded = canonical_operation(science)
                conn.execute(
                    "INSERT INTO paperfact_sync_operations(operation_id,fingerprint,"
                    "entity_type,entity_id,envelope) VALUES(?,?,?,?,?)",
                    (
                        science["operation_id"],
                        hashlib.sha256(encoded.encode()).hexdigest(),
                        "research_content",
                        identity,
                        encoded,
                    ),
                )
    before = dump(client)
    with pytest.raises(ReviewRequired) as caught:
        work(importer.prepare, archive, **mapping_options(receipt))
    assert not caught.value.review.conflicts[0]["can_adopt"]
    with pytest.raises(ValueError):
        caught.value.review.decide({identity: "adopt"})
    assert dump(client) == before


def test_cancel_after_private_row_is_removed_rolls_back_the_entire_action(legacy, monkeypatch):
    from paper_daily import lineage_matching_adoption

    client, importer, _archive, _receipt, row, _review = legacy
    prepared, _decision = planned(legacy)
    before = dump(client)
    ticket = Ticket()
    original = lineage_matching_adoption.consume_in

    def cancel(*args, **kwargs):
        original(*args, **kwargs)
        ticket.cancel()

    monkeypatch.setattr(lineage_matching_adoption, "consume_in", cancel)
    with pytest.raises(Cancelled):
        work(importer.apply, prepared, ticket=ticket)
    assert dump(client) == before and row in lineage_sets.saved(
        client.journal.path, row["paper_id"]
    )


@pytest.mark.parametrize("change", ["missing", "incarnation"])
def test_private_adoption_requires_actual_selected_paper_materialization(legacy, change):
    client, importer, archive, receipt, row, review = legacy
    decision = review.decide({review.conflicts[0]["id"]: "adopt"})
    portable = receipt["identity_mapping"]["focal"]["portable_id"]
    with client.journal.transaction() as conn:
        if change == "missing":
            conn.execute("DELETE FROM research_paper_projection WHERE sync_id=?", (portable,))
        else:
            conn.execute(
                "UPDATE research_paper_projection SET incarnation='changed-parent' WHERE sync_id=?",
                (portable,),
            )
    before = dump(client)
    with pytest.raises(ValueError, match="comparison changed"):
        work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt))
    assert dump(client) == before and row in lineage_sets.saved(
        client.journal.path, row["paper_id"]
    )


def test_review_binds_selected_parent_lifetimes_even_when_science_and_mapping_match(
    legacy, monkeypatch
):
    from paper_daily import lineage_matching_adoption

    client, importer, archive, receipt, _row, review = legacy
    decision = review.decide({review.conflicts[0]["id"]: "adopt"})
    before = dump(client)
    original = lineage_matching_adoption.parents_in

    def changed(*args, **kwargs):
        parents = original(*args, **kwargs)
        if parents is not None:
            parents = [dict(item) for item in parents]
            parents[0]["incarnation"] = "new-selected-paper-lifetime"
        return parents

    monkeypatch.setattr(lineage_matching_adoption, "parents_in", changed)
    with pytest.raises(ValueError, match="comparison changed"):
        work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt))
    assert dump(client) == before
