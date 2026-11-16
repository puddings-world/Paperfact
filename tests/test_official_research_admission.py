"""Official admission never accepts research that supported native peers cannot apply."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_sync_capture import make
from test_sync_graph_service import operation
from test_sync_http import request, running

from paper_daily import sync_admin
from paper_daily.sync_http import HttpTransport, make_server


def dump(service):
    with closing(sqlite3.connect(service.path)) as conn:
        return list(conn.iterdump())


def seed(tmp_path):
    state = tmp_path / "official"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token, peer = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    point = service.history_page(token)["checkpoint"]
    receipt = service.push_verified(token, operation("paper-create", "paper"), checkpoint=point)
    removed = operation("paper-delete", "paper", action="delete", payload={},
                        incarnation="paper-create", base=1)
    return service, token, peer, receipt["checkpoint"], removed


def test_official_paper_delete_is_refused_without_poisoning_peer_history(tmp_path):
    service, token, peer, point, removed = seed(tmp_path)
    receiver = make(tmp_path / "peer.sqlite", "b")
    receiver.receive(service.pull(peer))
    before = dump(service)
    for _ in range(2):
        with pytest.raises(ValueError, match="Paper deletion"):
            service.push_verified(token, removed, checkpoint=point)
        assert dump(service) == before
    # Supported list retirement remains available and never deletes paper research.
    added = service.push_verified(token, operation("list-create"), checkpoint=point)
    receiver.receive(service.pull(peer))
    deleted = receiver.new_graph_operation("list", "list-1", {}, action="delete")
    receiver.save(deleted)
    receipt = service.push_verified(peer, deleted, checkpoint=added["checkpoint"])
    receiver.sync_verified_once(service, peer)
    with receiver.journal.transaction() as conn:
        assert tuple(conn.execute("SELECT title FROM papers").fetchone()) == ("Synthetic research",)
        assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    assert json.loads(receipt["record"])["outcome"] == "accepted"
    assert len(service.pull(peer)) == 3
    assert not receiver.journal.pending()


def test_http_refusal_is_sanitized_after_identity_checks_and_keeps_history(tmp_path):
    service, token, _peer, point, removed = seed(tmp_path)
    before = dump(service)
    with running(make_server(service, allow_unverified_mutations=False)) as url:
        body = json.dumps(dict(operation=removed, checkpoint=point)).encode()
        status, _headers, content = request(url, token, path="/v1/history/push", body=body)
        assert status == 400 and content == b'{"error":"invalid_request"}'
        with (HttpTransport(url) as transport,
              pytest.raises(ValueError, match="Paper deletion")):
            transport.push_verified(token, removed, checkpoint=point)
        wrong = operation("wrong-owner", "paper", device="someone-else")
        status, _, _ = request(url, token, path="/v1/history/push",
                               body=json.dumps(dict(operation=wrong, checkpoint=point)).encode())
        assert status == 403
    assert dump(service) == before
