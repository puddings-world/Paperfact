"""Actual authenticated loopback events reach native and mobile metadata receivers."""

import copy

import pytest
from test_lineage_jobs import work
from test_lineage_live_journey import candidate, native, publish
from test_lineage_mobile_wire import node
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_sync_files import drain
from test_sync_http import running

from paper_daily import lineage_projection, lineage_sets
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_http import HttpTransport, make_server


def test_real_http_publication_uploads_sources_then_native_and_mobile_consume_actual_events(
    selected, monkeypatch
):
    service, original, other, files, _peer_files, token, peer_token = selected[0]
    client, peer = native(original), native(other)
    result = candidate(selected, monkeypatch)
    receipt = work(publish, client, selected[3], result)
    science = next(
        op for op in client.journal.pending() if op["operation_id"] == receipt["operation_id"]
    )
    sources = [op for op in client.journal.pending() if op["entity_type"] == "research_file"]
    with running(make_server(service)) as url, HttpTransport(url) as http:
        transfer = FileTransfers(
            client, files.store, http, origin=url, token=token, version_root=files.root
        )
        try:
            assert transfer.authenticate()
            assert (
                client.sync_once(http, token, prepare_push=transfer.ready_to_push)["deferred_push"]
                == 4
            )
            for source in sources:
                drain(lambda op=source: transfer.upload(op), "uploaded")
            assert (
                client.sync_once(http, token, prepare_push=transfer.ready_to_push)["deferred_push"]
                == 1
            )
            assert (
                client.sync_once(http, token, prepare_push=transfer.ready_to_push)["pending"] == 0
            )
            # The real HTTP adapter intentionally caps pages at four events;
            # one low-level pass is not a complete new-device catch-up.
            for _ in range(20):
                received = peer.sync_once(http, peer_token)
                assert received["conflicts"] == 0
                if received["received"] == 0:
                    break
            else:
                pytest.fail("Native peer did not exhaust the actual HTTP event stream")
            events = []
            cursor = 0
            for _ in range(20):
                page = http.pull(peer_token, after=cursor, limit=100)
                if not page:
                    break
                events.extend(page)
                cursor = page[-1]["sequence"]
            else:
                pytest.fail("Mobile fixture did not exhaust the actual HTTP event stream")
        finally:
            transfer.close()
    assert len(rows(peer, lineage_sets.TABLE)) == 1
    assert lineage_projection.validate_record(rows(peer, lineage_projection.TABLE)[0]) == science
    original_events = copy.deepcopy(events)
    mobile = node(
        dict(events=events, workspace=science["workspace_id"]),
        """
import {readFileSync} from 'node:fs';
import {receive,projection} from './mobile/domain.mjs';
import {emptyState} from './mobile/store.mjs';
const {events,workspace}=JSON.parse(readFileSync(0,'utf8'));
const state=emptyState(workspace,'phone');
receive(state,events);
const view=projection(state);
console.log(JSON.stringify({cursor:state.cursor,rows:view.papers.flatMap(p=>p.lineage ?? []),
 originals:view.original_sources,files:state.files,artifacts:state.artifactFiles,
 outbox:state.outbox}));
""",
    )
    assert events == original_events
    assert mobile["cursor"] == events[-1]["sequence"]
    assert len(mobile["rows"]) == 1 and len(mobile["originals"]) == 3
    assert mobile["rows"][0]["body"] == science["payload"]["data"]["body_json"]
    assert mobile["files"] == mobile["artifacts"] == {} and mobile["outbox"] == []
