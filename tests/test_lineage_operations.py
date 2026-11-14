"""Native observed construction preserves target/source intent without publishing science."""

import copy
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_lineage_dependencies import compound, recapture
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import verified_report
from test_sync_files import drain, paper_payload

from paper_daily import claim_content, lineage_dependencies, lineage_sets, lineage_wire
from paper_daily.sync_journal import canonical_operation


def build(selected, change=None):
    client, staged = selected[0][1], selected[3]
    report = work(verified_report, selected[1])
    with client.journal.transaction() as conn:
        expected, originals = compound(selected, connection=conn, verified=report)
        payload = copy.deepcopy(expected["payload"])
        if change is not None:
            change(payload)
        before = list(conn.iterdump()), copy.deepcopy(payload)
        actual = client.new_lineage_operation_in(conn, staged, originals, payload)
        assert list(conn.iterdump()) == before[0] and payload == before[1]
        return actual, expected, originals


def test_actual_native_builder_matches_observed_frame_and_never_creates_scientific_receipts(
    selected,
):
    actual, expected, originals = work(build, selected)
    assert actual == expected
    assert len(actual["parents"]) == len(actual["source_dependencies"]) == len(originals) == 3
    client = selected[0][1]
    assert all(op["entity_type"] != "research_content" for op in client.journal.pending())
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM paper_lineage_sets").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM research_lineage_sync_history").fetchone()[0] == 0
    assert json.loads(canonical_operation(actual)) == actual


def test_valid_but_falsified_source_metadata_is_not_observed_original_authority(selected):
    def altered(payload):
        body = payload["data"]["body_json"]
        report = body["report"]
        report["sources"][0]["page_count"] += 1
        report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
        payload["data"]["source_hash"] = lineage_sets.source_hash(body)
        lineage_wire.validate_payload(payload)  # Closed valid JSON still cannot mint source facts.

    before = selected[0][1].journal.pending()
    with pytest.raises(ValueError, match="original observed corpus"):
        work(build, selected, altered)
    assert selected[0][1].journal.pending() == before


def test_wrong_observed_corpus_cannot_retarget_a_valid_report(selected):
    def altered(payload):
        payload["key"] = str(uuid4())
        payload["data"]["body_json"]["corpus_id"] = payload["key"]
        payload["data"]["source_hash"] = lineage_sets.source_hash(payload["data"]["body_json"])
        lineage_wire.validate_payload(payload)

    with pytest.raises(ValueError, match="original observed corpus"):
        work(build, selected, altered)


def test_acknowledged_originals_do_not_rebase_or_change_the_built_operation(selected):
    first, expected, originals = work(build, selected)
    service, client, _peer, files, _peer_files, token, _peer_token = selected[0]
    for original in originals.values():
        drain(lambda op=original: files.upload(op), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)

    def again():
        with client.journal.transaction() as conn:
            return client.new_lineage_operation_in(
                conn, selected[3], originals, expected["payload"]
            )

    assert work(again) == first


@pytest.mark.parametrize("restore", [False, True])
def test_build_after_source_retirement_refuses_without_restoring_or_adding_an_outbox(
    selected, restore
):
    first, expected, originals = work(build, selected)
    client = selected[0][1]
    original = next(iter(originals.values()))
    retired = client.new_graph_operation(
        "research_file", original["entity_id"], {}, action="delete"
    )
    client.save(retired)
    if restore:
        replacement = client.new_graph_operation(
            "research_file", original["entity_id"], original["payload"], restore=True
        )
        client.save(replacement)
        assert replacement["incarnation"] != original["incarnation"]
    before = client.journal.pending()

    def again():
        with client.journal.transaction() as conn:
            return client.new_lineage_operation_in(
                conn, selected[3], originals, expected["payload"]
            )

    with pytest.raises(ValueError):
        work(again)
    assert client.journal.pending() == before
    assert first["source_dependencies"][0]["incarnation"] == original["incarnation"]


def test_unavailable_fourth_source_keeps_its_observed_paper_parent_without_a_fake_file_pin(
    selected,
):
    client = selected[0][1]
    missing = str(uuid4())
    client.save(
        client.new_graph_operation(
            "paper", missing, dict(paper_payload(), title="Unavailable fourth selected source")
        )
    )
    with client.journal.transaction() as conn:
        local = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (missing,)
        ).fetchone()[0]
    chosen = recapture(
        selected, [p["local_id"] for p in json.loads(selected[1]._json)["observed"]] + [local]
    )
    actual, expected, _originals = work(build, chosen)
    assert actual == expected and len(actual["parents"]) == 4
    assert len(actual["source_dependencies"]) == 3
    assert actual["parents"][-1]["id"] == missing


def test_native_builder_does_not_read_or_hash_originals_inside_the_write_transaction(
    selected, monkeypatch
):
    client, staged = selected[0][1], selected[3]
    report = work(verified_report, selected[1])

    def run():
        with client.journal.transaction() as conn:
            expected, originals = compound(selected, connection=conn, verified=report)

            def unexpected(*_a, **_k):
                pytest.fail("Builder must use sealed source metadata, not read PDFs")

            with monkeypatch.context() as patch:
                patch.setattr(Path, "read_bytes", unexpected)
                return client.new_lineage_operation_in(conn, staged, originals, expected["payload"])

    actual = work(run)
    assert json.loads(lineage_dependencies.canonical_operation(actual)) == actual


def test_foreign_client_or_database_cannot_use_a_staged_original_capture(selected):
    expected, _frame, originals = work(build, selected)
    _service, client, peer, _files, _peer_files, _token, _peer_token = selected[0]
    before = client.journal.pending(), peer.journal.pending()

    def run():
        with peer.journal.transaction() as conn:
            client.new_lineage_operation_in(conn, selected[3], originals, expected["payload"])

    with pytest.raises(ValueError):
        work(run)
    assert (client.journal.pending(), peer.journal.pending()) == before


@pytest.mark.parametrize("missing", ["native-staging", "source-operations"])
def test_untrusted_or_incomplete_source_publication_cannot_build_an_operation(selected, missing):
    expected, _frame, originals = work(build, selected)
    client = selected[0][1]
    before = client.journal.pending()

    def run():
        with client.journal.transaction() as conn:
            return client.new_lineage_operation_in(
                conn,
                None if missing == "native-staging" else selected[3],
                {} if missing == "source-operations" else originals,
                expected["payload"],
            )

    with pytest.raises(ValueError):
        work(run)
    assert client.journal.pending() == before


def test_local_target_created_after_observation_is_retained_without_building_over_it(selected):
    expected, _frame, originals = work(build, selected)
    client = selected[0][1]
    with client.journal.transaction() as conn:
        row = lineage_wire.decode_row(conn, expected["payload"])
        conn.execute(
            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
            tuple(row[k] for k in lineage_sets.COLUMNS.split()),
        )
    with closing(client.journal._connect()) as conn:
        before = list(conn.iterdump())

    def run():
        with client.journal.transaction() as conn:
            return client.new_lineage_operation_in(
                conn, selected[3], originals, expected["payload"]
            )

    with pytest.raises(ValueError):
        work(run)
    with closing(client.journal._connect()) as conn:
        assert list(conn.iterdump()) == before
