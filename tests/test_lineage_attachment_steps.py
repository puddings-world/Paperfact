"""The desktop attachment coordinator shares exact original readiness."""

import copy

import pytest
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_transfer_readiness import prepared as prepared
from test_lineage_transfer_readiness import upload
from test_workspace_sync import Native

from paper_daily.workspace_sync_files import AttachmentSteps


def coordinator(pair):
    service, client, _peer, _files, _peer_files, token, _peer_token = pair
    calls, progress = [], []
    transport = Native("https://fixture.invalid", service, calls)
    steps = AttachmentSteps(client, transport, token, lambda: None, progress.append)
    return steps, calls, progress


def test_desktop_prepare_waits_for_received_sources_without_starting_an_upload(prepared):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    steps, calls, progress = coordinator(pair)
    try:
        before = copy.deepcopy(frame), client.journal.pending()
        assert steps.prepare(frame) is False
        assert steps.prepare(frame) is False
        assert steps.steps == 0 and calls == [] and progress == []
        assert client.journal.pending() == before[1]
        upload(pair, originals)
        assert steps.prepare(frame) is False
        client.sync_once(service, token, prepare_push=files.ready_to_push)
        assert steps.prepare(frame) is True
        assert steps.steps == 0 and calls == [] and progress == []
        assert frame == before[0]
    finally:
        steps.close()


def test_desktop_prepare_checks_metadata_even_without_an_attachment_registration(prepared):
    pair, frame, _originals = prepared
    with pair[1].journal.transaction() as conn:
        conn.execute("DELETE FROM research_file_paths")
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='document_reader_paths'"
        ).fetchone()
    steps, calls, progress = coordinator(pair)
    try:
        assert steps.pdf is None and steps.artifact is None
        assert steps.prepare(frame) is False
        retirement = dict(frame, action="delete", payload={}, source_dependencies=[])
        assert steps.prepare(retirement) is True
        foreign = dict(frame, workspace_id="another-workspace")
        with pytest.raises(ValueError):
            steps.prepare(foreign)
        assert calls == [] and progress == []
    finally:
        steps.close()
