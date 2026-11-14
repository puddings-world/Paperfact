"""Removed/generated, imported and peer-native originals remain read-only proofs."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_import_originals import loaded as loaded
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_package_publish import incoming as incoming
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_research_lineage import corpus as corpus
from test_sync_files import drain

from paper_daily import lineage_history_originals as history
from paper_daily import lineage_lifecycle, lineage_originals, lineage_sets, lineage_versions, llm
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner


def remove(owner, row):
    work(lineage_lifecycle.change, owner, row, request_id=str(uuid4()), action="retire")
    return work(lineage_versions.collect, owner)["items"][0]["origin"]


def check(owner, row, origin, index):
    source = lineage_sets.decode(row["body_json"])["report"]["sources"][index]
    before = owner.database.read_bytes()
    proof = work(history.prepare, owner, row, origin, source["id"])
    data = history.for_delivery(proof, owner, row, source["id"])
    assert hashlib.sha256(data).hexdigest() == source["document_hash"]
    assert history.metadata_current(proof)
    assert owner.database.read_bytes() == before
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    return proof, source


@pytest.mark.parametrize("index", [0, 1, 2])
def test_generated_removed_history_reads_exact_originals_without_activation_or_ai(active, index):
    owner, row = active
    origin = remove(owner, row)
    proof, source = check(owner, row, origin, index)
    with pytest.raises(ValueError, match="Displayed Lineage result is unavailable"):
        work(lineage_originals.prepare, owner, row, source["id"])
    with pytest.raises(ValueError, match="native verified snapshot"):
        history.for_delivery(replace(proof, _data=b"different"), owner, row, source["id"])
    other_owner = observe_owner(
        owner.database, owner.paper_id, expected_native=generation._identity(owner.database)
    )
    with pytest.raises(ValueError, match="Historical view changed"):
        history.for_delivery(proof, other_owner, row, source["id"])


@pytest.mark.parametrize("index", [0, 1, 2])
def test_imported_removed_history_keeps_exact_receiver_source_ownership(loaded, index):
    _incoming, owner, row = loaded
    origin = remove(owner, row)
    assert origin["kind"] == "import"
    check(owner, row, origin, index)


def test_received_native_removed_history_reads_owned_exact_pdf_without_new_outbox(
    selected, monkeypatch
):
    client, _candidate, _receipt, _scientific, sources = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, sources)
    for source in sources:
        drain(lambda identity=source["entity_id"]: selected[0][4].download(identity), "bound")
    row = rows(peer, lineage_sets.TABLE)[0]
    owner = observe_owner(
        peer.journal.path, row["paper_id"], expected_native=generation._identity(peer.journal.path)
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No history AI"))
    origin = remove(owner, row)
    pending = peer.journal.pending()
    for index in range(3):
        check(owner, row, origin, index)
    assert peer.journal.pending() == pending


@pytest.mark.parametrize("broken", ["association", "parent", "bytes", "publication"])
def test_generated_original_invalidates_after_exact_source_or_provenance_change(active, broken):
    owner, row = active
    origin = remove(owner, row)
    proof, source = check(owner, row, origin, 1)
    if broken == "bytes":
        proof._path.write_bytes(b"x" * proof._path.stat().st_size)
    else:
        with closing(sqlite3.connect(owner.database)) as conn, conn:
            if broken == "association":
                conn.execute("DELETE FROM research_local_source_owners")
            elif broken == "parent":
                old = conn.execute("SELECT * FROM papers WHERE id='prior'").fetchone()
                conn.execute("DELETE FROM papers WHERE id='prior'")
                conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in old) + ")", old)
            else:
                conn.execute("DELETE FROM research_lineage_publications")
    assert not history.metadata_current(proof)
    with pytest.raises(ValueError, match="Historical view changed"):
        history.for_delivery(proof, owner, row, source["id"])
    assert lineage_sets.saved(owner.database, owner.paper_id) == []


def test_historical_read_cancel_or_wrong_source_never_mutates_or_falls_back(active):
    owner, row = active
    origin = remove(owner, row)
    before = owner.database.read_bytes()
    source = lineage_sets.decode(row["body_json"])["report"]["sources"][0]
    assert work(history.prepare, owner, row, origin, source["id"], cancelled=lambda: True) is None
    with pytest.raises(ValueError, match="outside the selected report"):
        work(history.prepare, owner, row, origin, "0" * 64)
    assert owner.database.read_bytes() == before


@pytest.mark.parametrize("recreated", [False, True])
def test_native_old_grant_does_not_revive_after_source_retirement_or_recreation(
    selected, monkeypatch, recreated
):
    client, _candidate, _receipt, _scientific, sources = setup_publication(selected, monkeypatch)
    sync_all(selected, client, sources)
    row = rows(client, lineage_sets.TABLE)[0]
    owner = observe_owner(
        client.journal.path,
        row["paper_id"],
        expected_native=generation._identity(client.journal.path),
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No history AI"))
    origin = remove(owner, row)
    proof, source = check(owner, row, origin, 0)
    selected_source = sources[0]
    client.save(
        client.new_graph_operation(
            "research_file", selected_source["entity_id"], {}, action="delete"
        )
    )
    if recreated:
        new = client.new_graph_operation(
            "research_file", selected_source["entity_id"], selected_source["payload"], restore=True
        )
        client.save(new)
        assert new["incarnation"] != selected_source["incarnation"]
    before = client.journal.pending()
    assert not history.metadata_current(proof)
    with pytest.raises(ValueError, match="lifetime changed"):
        work(history.prepare, owner, row, origin, source["id"])
    assert client.journal.pending() == before
    assert rows(client, lineage_sets.TABLE) == []


def test_imported_previous_pdf_is_readable_while_a_newer_analysis_occupies_slot(loaded, tmp_path):
    from test_lineage_import_recovery import replaced_versions

    incoming, owner, old = loaded
    old, new = replaced_versions(incoming, tmp_path)
    item = next(
        item for item in work(lineage_versions.collect, owner)["items"] if item["row"] == old
    )
    old_source = lineage_sets.decode(old["body_json"])["report"]["sources"][1]
    new_source = lineage_sets.decode(new["body_json"])["report"]["sources"][1]
    assert old_source["document_hash"] != new_source["document_hash"]
    before = owner.database.read_bytes()
    proof = work(history.prepare, owner, old, item["origin"], old_source["id"])
    data = history.for_delivery(proof, owner, old, old_source["id"])
    assert hashlib.sha256(data).hexdigest() == old_source["document_hash"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == [new]
    assert owner.database.read_bytes() == before


@pytest.mark.parametrize(
    "origin",
    [None, dict(kind=[], id="x"), dict(kind="generated", id=[]), dict(kind="unknown", id="x")],
)
def test_invalid_historical_origin_is_rejected_before_any_file_read(active, origin):
    owner, row = active
    source = lineage_sets.decode(row["body_json"])["report"]["sources"][0]
    before = owner.database.read_bytes()
    with pytest.raises(ValueError):
        work(history.prepare, owner, row, origin, source["id"])
    assert owner.database.read_bytes() == before
