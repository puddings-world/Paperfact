"""Result callers share admission, failure handling and retryable persistence."""

import pytest
from test_analysis_coverage import PID
from test_analysis_coverage import conn as conn

from paper_daily import citegraph, followups, llm, research_job_lock, store
from paper_daily.http import FetchError


@pytest.mark.parametrize("entry", ["analyse", "analyse_result"])
def test_service_failure_is_not_completion_and_retry_releases_lock(conn, monkeypatch, entry):
    def offline(_row):
        raise FetchError("429 from OpenAlex")

    monkeypatch.setattr(followups, "work_id", offline)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no AI for empty lookup"))
    monkeypatch.setattr(citegraph, "links", lambda *a, **k: None)
    operation = getattr(followups, entry)
    messages = []
    failed = operation(PID, log=messages.append, overview_too=False)
    assert (failed[0] if isinstance(failed, tuple) else failed) == 0
    assert any("429" in message for message in messages)
    assert not followups.done(conn, PID)
    assert not followups.nothing_to_tell(conn, PID)
    assert conn.execute("SELECT COUNT(*) FROM followups").fetchone()[0] == 0

    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    result = operation(PID, overview_too=False)
    assert result == ((0, "") if entry == "analyse_result" else 0)
    assert followups.nothing_to_tell(conn, PID)


def test_duplicate_request_returns_busy_without_querying(conn, monkeypatch):
    monkeypatch.setattr(followups, "work_id", lambda _: pytest.fail("duplicate query"))
    with research_job_lock.claim(store.DB_PATH, "followups", PID) as acquired:
        assert acquired
        count, reason = followups.analyse_result(PID)
    assert count == 0 and "already in progress" in reason
    assert not followups.done(conn, PID)


def test_missing_paper_returns_reason_without_querying(conn, monkeypatch):
    monkeypatch.setattr(followups, "work_id", lambda _: pytest.fail("missing paper query"))
    assert followups.analyse_result("missing-paper") == (0, "The selected paper no longer exists")
