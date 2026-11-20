"""The reader leaves work for an agent host; a saved answer closes the request."""

import pytest
from test_dive import conn as conn

from paper_daily import brief, host_requests, llm, local_operations

DIVE = "## 一句話結論\n" + "這篇的主張有實驗支持。" * 100


@pytest.fixture
def host(conn, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Paperfact called a model"))
    monkeypatch.setattr(brief, "pack_text", lambda c, row: (f"pack for {row['title']}", None))
    return conn


def pending():
    listed = local_operations.dispatch("research.tasks.pending", {})
    assert listed["ok"]
    return listed["result"]["requests"]


def test_a_request_names_the_paper_and_the_tools_that_answer_it(host):
    host_requests.request("dive", "p2")
    [request] = pending()
    assert (request["feature"], request["paper_id"], request["title"]) == ("dive", "p2", "Second")
    assert request["task_tool"] == "research.dive.task"
    assert request["save_tool"] == "research.dive.save"
    assert request["task_tool"] in local_operations.OPERATIONS
    assert request["save_tool"] in local_operations.OPERATIONS


def test_asking_twice_queues_once_and_requests_come_oldest_first(host):
    first = host_requests.request("dive", "p2")
    assert host_requests.request("dive", "p2") == first
    host_requests.request("citations", "p2")
    host_requests.request("dive", "p1")
    assert [(r["feature"], r["paper_id"]) for r in pending()] == [
        ("dive", "p2"),
        ("citations", "p2"),
        ("dive", "p1"),
    ]
    limited = local_operations.dispatch("research.tasks.pending", {"limit": 1})
    assert len(limited["result"]["requests"]) == 1


def test_a_saved_dive_closes_its_request_and_a_rejected_one_does_not(host):
    host_requests.request("dive", "p2")
    host_requests.request("dive", "p1")
    rejected = local_operations.dispatch("research.dive.save", {"paper_id": "p2", "body": "no"})
    assert rejected["error"]["code"] == "dive_answer_rejected"
    assert host_requests.waiting("dive", "p2")
    saved = local_operations.dispatch("research.dive.save", {"paper_id": "p2", "body": DIVE})
    assert saved["ok"]
    assert not host_requests.waiting("dive", "p2")
    assert [r["paper_id"] for r in pending()] == ["p1"]


def test_a_dive_saved_without_a_request_is_still_saved(host):
    saved = local_operations.dispatch("research.dive.save", {"paper_id": "p2", "body": DIVE})
    assert saved["ok"] and pending() == []


def test_a_cancelled_request_is_no_longer_offered_and_can_be_asked_again(host):
    request_id = host_requests.request("dive", "p2")
    assert host_requests.cancel(request_id)
    assert pending() == [] and not host_requests.cancel(request_id)
    assert host_requests.request("dive", "p2") != request_id
    assert len(pending()) == 1


def test_only_features_with_host_tools_and_existing_papers_can_be_queued(host):
    with pytest.raises(ValueError):
        host_requests.request("ask", "p1")
    with pytest.raises(ValueError):
        host_requests.request("dive", "absent")
    assert pending() == []


def test_the_queue_is_bounded(host, monkeypatch):
    monkeypatch.setattr(host_requests, "MAX_PENDING", 2)
    host_requests.request("dive", "p1")
    host_requests.request("dive", "p2")
    with pytest.raises(ValueError):
        host_requests.request("dive", "p3")
    assert host_requests.request("dive", "p1")  # The open one is returned, not refused.


def test_listing_rejects_a_limit_out_of_range(host):
    for limit in (0, 101, True, "5"):
        result = local_operations.dispatch("research.tasks.pending", {"limit": limit})
        assert result["error"]["code"] == "invalid_input"
