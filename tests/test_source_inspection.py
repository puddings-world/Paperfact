"""A local exact desired original is inspectable without waiting for cloud binding."""

import hashlib
import sqlite3
from contextlib import closing

from test_claim_jobs import (
    claims as claims_fixture,
)
from test_claim_jobs import (
    job,
)
from test_claim_jobs import (
    ready as ready_fixture,
)
from test_claim_jobs import (
    workspace as workspace_fixture,
)
from test_sync_source_files import pdf

from paper_daily import research_generation as generation
from paper_daily.sync_source_files import inspectable, resolved

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


def test_claim_original_A_is_inspectable_locally_after_B_without_applied_or_network(claims):
    original = claims[0][2].path.read_bytes()
    assert job(claims).run().status == "accepted"
    if claims[0][1] is None:
        assert not list(claims[0][0].parent.glob("blobs/index.sqlite"))
        return
    db = claims[0][0]
    claims[0][2].path.write_bytes(pdf("A newer current primary B"))
    before = db.read_bytes()
    with closing(generation._connect(db)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        digest = hashlib.sha256(original).hexdigest()
        assert resolved(conn, portable, digest) is None
        result = inspectable(conn, portable, digest)
        assert result.read_bytes() == original
        assert not conn.execute("SELECT * FROM research_file_applied").fetchall()
        assert inspectable(conn, portable, "0" * 64) is None
    assert db.read_bytes() == before
    assert claims[0][2].path.read_bytes() != original


def test_inspection_rechecks_parent_after_expensive_closure_verification(claims, monkeypatch):
    from paper_daily import sync_artifacts

    original = claims[0][2].path.read_bytes()
    assert job(claims).run().status == "accepted"
    if claims[0][1] is None:
        return
    db = claims[0][0]
    verify = sync_artifacts.verify_closure

    def retired(*args, **kwargs):
        result = verify(*args, **kwargs)
        with closing(sqlite3.connect(db)) as changed, changed:
            changed.create_function("paperfact_capture", 3, lambda *_args: 0)
            changed.execute("DELETE FROM papers WHERE id='paper'")
        return result

    monkeypatch.setattr(sync_artifacts, "verify_closure", retired)
    with closing(generation._connect(db)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        assert inspectable(conn, portable, hashlib.sha256(original).hexdigest()) is None


def test_missing_registered_store_is_never_created_by_source_inspection(claims, tmp_path):
    assert job(claims).run().status == "accepted"
    if claims[0][1] is None:
        return
    db = claims[0][0]
    missing = tmp_path / "missing-original-cache"
    with closing(sqlite3.connect(db)) as changed, changed:
        changed.execute("UPDATE research_file_paths SET blob_root=?", (str(missing),))
    before = db.read_bytes()
    with closing(generation._connect(db)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        assert inspectable(conn, portable, claims[0][2].sha256) is None
        assert resolved(conn, portable, claims[0][2].sha256) is None
    assert not missing.exists() and db.read_bytes() == before
