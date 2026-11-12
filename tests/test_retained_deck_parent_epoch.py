"""A fresh review must not invent continuity for a deleted/recreated local paper."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_file_review import codec as _codec
from test_research_file_review import pair as _pair
from test_research_file_review import retained as _retained
from test_sync_files import LOCAL, PAPER, paper_payload

from paper_daily import presentations
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import ResearchReview

codec, pair, retained = _codec, _pair, _retained


def test_recreation_before_first_review_cannot_reauthorize_an_old_candidate(retained):
    client, identity = retained
    before = presentations.load_deck(LOCAL, "guide").to_dict()
    with client.journal.transaction() as conn:
        old_token = parent_lifecycle(conn, "paper", LOCAL)
        row = conn.execute("SELECT * FROM papers WHERE id=?", (LOCAL,)).fetchone()
        columns = [c[1] for c in conn.execute("PRAGMA table_info(papers)")]
        conn.execute("DELETE FROM papers WHERE id=?", (LOCAL,))
        conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in columns) + ")", row)
        assert old_token is not None
        assert parent_lifecycle(conn, "paper", LOCAL) != old_token
    pending = client.journal.pending()
    review = ResearchReview(client.journal.path)
    try:
        with pytest.raises(ValueError, match="lifecycle"):
            review.prepare_file(review.preview("file", identity))
    finally:
        review.close()
    assert client.journal.pending() == pending
    assert presentations.load_deck(LOCAL, "guide").to_dict() == before
    with closing(sqlite3.connect(client.journal.path)) as conn:
        assert conn.execute(
            "SELECT count(*) FROM research_file_candidates WHERE candidate_id=?", (identity,)
        ).fetchone() == (1,)
        receipts_exist = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_review_receipts'"
        ).fetchone()
        if receipts_exist:
            assert conn.execute("SELECT count(*) FROM research_review_receipts").fetchone() == (0,)


def test_same_parent_rename_still_allows_explicit_review_without_replacing_saved_deck(retained):
    client, identity = retained
    before = presentations.load_deck(LOCAL, "guide").to_dict()
    with client.journal.transaction() as conn:
        token = parent_lifecycle(conn, "paper", LOCAL)
    payload = paper_payload()
    payload["title"] = "Renamed paper, same identity"
    client.save(client.new_graph_operation("paper", PAPER, payload))
    with client.journal.transaction() as conn:
        assert parent_lifecycle(conn, "paper", LOCAL) == token
    pending = client.journal.pending()
    review = ResearchReview(client.journal.path)
    try:
        prepared = review.prepare_file(review.preview("file", identity))
        assert prepared.data["apply"] and prepared.data["requires_confirmation"]
        assert prepared.data["target"]["title"] == payload["title"]
    finally:
        review.close()
    assert client.journal.pending() == pending
    assert presentations.load_deck(LOCAL, "guide").to_dict() == before


def test_legacy_graph_observation_remains_explicitly_reviewable_without_inventing_old_token(
    retained,
):
    client, identity = retained
    with closing(sqlite3.connect(client.journal.path)) as conn, conn:
        raw = json.loads(
            conn.execute(
                "SELECT observation FROM research_file_candidates WHERE candidate_id=?", (identity,)
            ).fetchone()[0]
        )
        raw.pop("local_parent_lifecycle", None)
        encoded = json.dumps(raw)
        conn.execute(
            "UPDATE research_file_candidates SET observation=? WHERE candidate_id=?",
            (encoded, identity),
        )
    pending = client.journal.pending()
    review = ResearchReview(client.journal.path)
    try:
        prepared = review.prepare_file(review.preview("file", identity))
        assert prepared.data["apply"] and prepared.data["requires_confirmation"]
        with pytest.raises(ValueError, match="Confirm"):
            review.decide(prepared, request_id="legacy-without-confirmation")
    finally:
        review.close()
    assert client.journal.pending() == pending
    with closing(sqlite3.connect(client.journal.path)) as conn:
        assert (
            conn.execute(
                "SELECT observation FROM research_file_candidates WHERE candidate_id=?", (identity,)
            ).fetchone()[0]
            == encoded
        )


def test_save_after_parent_recreation_retains_old_result_without_automatic_publication(retained):
    from paper_daily.sync_deck_publication import StaleDeckError

    client, _identity = retained
    value = presentations.load_deck(LOCAL, "guide")
    observation = value._file_observation
    before = value.to_dict()
    value.title = "Completed before the paper was recreated"
    with client.journal.transaction() as conn:
        old = parent_lifecycle(conn, "paper", LOCAL)
        row = conn.execute("SELECT * FROM papers WHERE id=?", (LOCAL,)).fetchone()
        columns = [c[1] for c in conn.execute("PRAGMA table_info(papers)")]
        conn.execute("DELETE FROM papers WHERE id=?", (LOCAL,))
        conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in columns) + ")", row)
        assert parent_lifecycle(conn, "paper", LOCAL) != old
    pending = client.journal.pending()
    with pytest.raises(StaleDeckError) as caught:
        presentations.save_deck(value, observation=observation)
    assert presentations.load_deck(LOCAL, "guide").to_dict() == before
    assert client.journal.pending() == pending
    review = ResearchReview(client.journal.path)
    try:
        with pytest.raises(ValueError, match="lifecycle"):
            review.prepare_file(review.preview("file", caught.value.candidate_id))
    finally:
        review.close()
    assert client.journal.pending() == pending
