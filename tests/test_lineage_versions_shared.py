"""History across actual receiver imports and replicated native scientific edits."""

from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_import_recovery import imported as imported
from test_lineage_import_recovery import replaced_versions
from test_lineage_jobs import work
from test_lineage_live_conflicts import edit
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_package_publish import incoming as incoming
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows

from paper_daily import lineage_lifecycle, lineage_sets, lineage_versions, llm
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner


def test_real_replaced_import_versions_keep_their_distinct_receiver_origins(imported, tmp_path):
    old, new = replaced_versions(imported, tmp_path)
    owner = observe_owner(imported[0], "receiver-focal", expected_native=imported[1])
    before = imported[0].read_bytes()
    versions = work(lineage_versions.collect, owner)
    assert versions["total"] == 2
    assert {generation._json(item["row"]) for item in versions["items"]} == {
        generation._json(old),
        generation._json(new),
    }
    current = next(item for item in versions["items"] if item["current"])
    historical = next(item for item in versions["items"] if not item["current"])
    assert current["row"] == new and historical["row"] == old
    assert current["origin"]["kind"] == historical["origin"]["kind"] == "import"
    assert current["origin"]["id"] != historical["origin"]["id"]
    assert current["occupied"] and historical["occupied"]
    assert imported[0].read_bytes() == before


def test_actual_peer_received_history_lists_original_and_edited_report_without_ai(
    selected, monkeypatch
):
    client, _candidate, _receipt, original, sources = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, sources)
    old = rows(peer, lineage_sets.TABLE)[0]
    changed = edit(client, original, "2026-11-14T03:00:00+00:00")
    service, _a, _b, files, _peer_files, token, peer_token = selected[0]
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    current = rows(peer, lineage_sets.TABLE)[0]
    owner = observe_owner(
        peer.journal.path, old["paper_id"], expected_native=generation._identity(peer.journal.path)
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No history AI"))
    pending = peer.journal.pending()
    versions = work(lineage_versions.collect, owner)
    assert versions["total"] == 2
    old_item = next(item for item in versions["items"] if item["row"] == old)
    new_item = next(item for item in versions["items"] if item["row"] == current)
    assert old_item["origin"] == dict(kind="native", id=original["operation_id"])
    assert new_item["origin"] == dict(kind="native", id=changed["operation_id"])
    assert not old_item["current"] and old_item["occupied"] and new_item["current"]
    assert peer.journal.pending() == pending
    work(lineage_lifecycle.change, owner, current, request_id=str(uuid4()), action="retire")
    removed = work(lineage_versions.collect, owner)
    assert all(not item["occupied"] for item in removed["items"])
    work(
        lineage_lifecycle.change,
        owner,
        old,
        request_id=str(uuid4()),
        action="restore",
        origin=old_item["origin"],
    )
    restored = work(lineage_versions.collect, owner)
    assert restored["total"] == 2
    assert [item["row"] for item in restored["items"] if item["current"]] == [old]
    assert rows(peer, lineage_sets.TABLE) == [old]
