"""Claim commits invalidate list-visible reading state, not partial work or retries."""

from contextlib import closing

from test_claim_jobs import claims as _claims
from test_claim_jobs import job
from test_claim_jobs import ready as _ready
from test_claim_jobs import workspace as _workspace

from paper_daily import claim_jobs, sync_capture
from paper_daily import research_generation as generation

claims = _claims
ready = _ready
workspace = _workspace


def revision(database):
    with closing(generation._connect(database)) as conn:
        return conn.execute("SELECT revision FROM workspace_revision WHERE id=1").fetchone()[0]


def member(claims):
    with (
        closing(generation._connect(claims[0][0])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        conn.execute(
            "INSERT INTO lists(id,name,created_at) "
            "VALUES('l','Research','2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('l','paper',0,'2026-01-01T00:00:00+00:00')"
        )


def test_claim_publication_delete_restore_and_duplicate_delivery_revision(claims):
    database = claims[0][0]
    member(claims)
    before = revision(database)
    current = job(claims)
    assert current.run().status == "accepted"
    committed = revision(database)
    assert committed > before  # Projection can perform multiple SQL mutations.
    current.run()
    assert revision(database) == committed
    with closing(generation._connect(database)) as conn:
        observed = sync_capture.observe_target(conn, "paper", "paper", "claims", "main")
        with sync_capture.expecting(conn, [observed]):
            conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
            conn.commit()
    removed = revision(database)
    assert removed > committed
    value, _ = claim_jobs.ensure(
        database, "paper", legacy_root=claims[0][2].path.parent, force=True
    )
    assert value == {"claims": [], "known": True} and revision(database) == removed
    value, _ = claim_jobs.ensure(
        database, "paper", legacy_root=claims[0][2].path.parent, restore_deleted=True
    )
    assert value["report"]["claims"] and revision(database) > removed


def test_unlisted_claims_and_rolled_back_changes_do_not_advance_list_revision(claims):
    database = claims[0][0]
    before = revision(database)
    assert job(claims).run().status == "accepted"
    assert revision(database) == before
    member(claims)
    before = revision(database)
    with closing(generation._connect(database)) as conn:
        conn.execute("UPDATE paper_claim_sets SET written_at=written_at WHERE paper_id='paper'")
        assert conn.execute("SELECT revision FROM workspace_revision").fetchone()[0] == before + 1
        conn.rollback()
    assert revision(database) == before
