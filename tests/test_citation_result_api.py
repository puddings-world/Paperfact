"""The structured citation entry point shares safe publication and honest reasons."""

import json
from contextlib import closing

import pytest
from test_research_compound import driver as driver
from test_research_compound import workspace as workspace

from paper_daily import cites, llm
from paper_daily import research_generation as generation
from paper_daily.research_job_lock import claim


def test_structured_citation_result_publishes_the_same_verified_rows_and_count(driver):
    path, client, _document, calls, install, _invoke = driver
    install("citations")
    assert cites.analyse_result("paper", database=path) == (2, "")
    assert calls == ["citations"]
    with closing(generation._connect(path)) as conn:
        assert {row[0] for row in conn.execute("SELECT ref_key FROM cites")} == {"1", "2"}
        assert cites.coverage(conn, "paper", verify_source=True)["state"] == "complete"
        assert not cites.complete(conn, "paper")  # GUI metadata is not source verification.
    if client:
        assert (
            len([op for op in client.journal.pending() if op["entity_type"] == "research_content"])
            == 2
        )


@pytest.mark.parametrize(
    "reply,expected",
    [
        ((None, "fixture unavailable"), "fixture unavailable"),
        (("not JSON", "ok"), "The AI reply is not a valid citation JSON list"),
        (("[]", "ok"), "The AI reply contains no valid citation answers"),
    ],
)
def test_failed_result_reports_reason_without_publishing_partial_state(
    driver, monkeypatch, reply, expected
):
    path, client, _document, _calls, install, _invoke = driver
    install("citations")
    pending = client.journal.pending() if client else None
    monkeypatch.setattr(llm, "complete", lambda *_args, **_kwargs: reply)
    assert cites.analyse_result("paper", database=path) == (0, expected)
    with closing(generation._connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM cites").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_compound_requests'"
        ).fetchone()
    if client:
        assert client.journal.pending() == pending


def test_an_existing_job_refuses_a_repeat_without_calling_ai_or_writing(driver, monkeypatch):
    path, client, _document, _calls, install, _invoke = driver
    install("citations")
    before = path.read_bytes()

    def deny(*_args, **_kwargs):
        pytest.fail("A duplicate or missing-target request must not call AI")

    monkeypatch.setattr(llm, "complete", deny)
    with claim(path, "citations", "paper") as acquired:
        assert acquired
        assert cites.analyse_result("paper", database=path) == (
            0,
            "Citation analysis is already in progress",
        )
    assert cites.analyse_result("missing", database=path) == (
        0,
        "The selected paper no longer exists",
    )
    assert path.read_bytes() == before


def test_stale_generated_result_returns_retention_reason_and_never_overwrites(driver):
    path, _client, _document, _calls, install, _invoke = driver

    def rename():
        with closing(generation._connect(path)) as conn, conn:
            conn.execute("UPDATE papers SET title='Changed while AI was working' WHERE id='paper'")

    install("citations", rename)
    count, reason = cites.analyse_result("paper", database=path)
    assert count == 0 and "generated result retained:" in reason
    with closing(generation._connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM cites").fetchone()[0] == 0
        record = conn.execute(
            "SELECT mutations_json,status FROM research_compound_requests"
        ).fetchone()
        assert record["status"] == "candidate"
        assert len(json.loads(record["mutations_json"])["puts"]) == 2
