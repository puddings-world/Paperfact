"""Observed desktop review uses the actual native importer and isolated research."""

import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_lineage_jobs import work
from test_package_import import enroll_capture
from test_package_import import package as package
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import store
from paper_daily.package_review import PackageReview
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged


def dump(session):
    with closing(sqlite3.connect(session.importer.database)) as conn:
        return tuple(conn.iterdump())


@pytest.fixture
def review(package, pair, monkeypatch):
    client = pair[1]
    enroll_capture(client)
    monkeypatch.setattr(store, "DB_PATH", client.journal.path)
    session = PackageReview(
        client.journal.path,
        client.journal.path.parent,
        package[0],
        current_path=lambda: store.DB_PATH,
    )
    yield session
    session.close()
    session.discard()


def test_inspect_search_prepare_and_apply_share_one_native_operation(review):
    before = dump(review)
    info = work(review.inspect)
    assert info["name"] == "Reading" and info["papers"][0]["title"] == "Original paper"
    assert dump(review) == before
    preview = work(review.prepare)
    assert preview["state"] == "prepared" and dump(review) == before
    receipt = work(review.apply)
    assert receipt["state"] == "applied_locally"
    identity = receipt["identity_mapping"]["ref:example"]["local_id"]
    found = work(review.search, "Original")
    assert any(p["id"] == identity for p in found["papers"])
    assert work(review.search, "%_")["papers"] == []
    assert work(review.search, identity)["papers"][0]["id"] == identity
    info = work(review.inspect)
    assert any(row["id"] == receipt["list"] for row in info["lists"])
    prepared = work(
        review.prepare, target_list_id=receipt["list"], paper_mapping={"ref:example": identity}
    )
    assert prepared["identity_mapping"]["ref:example"]["local_id"] == identity
    result = work(review.apply)
    assert result["list"] == receipt["list"]
    with closing(sqlite3.connect(review.importer.database)) as conn:
        assert (
            conn.execute("SELECT count(*) FROM papers WHERE title='Original paper'").fetchone()[0]
            == 1
        )


def test_cancel_after_preview_preserves_research_and_removes_staging(review):
    work(review.inspect)
    work(review.prepare)
    directory = review.prepared.work
    before = dump(review)
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        work(review.apply, ticket)
    assert dump(review) == before and not directory.exists()
    work(review.prepare)
    assert work(review.apply)["state"] == "applied_locally"


def test_changed_archive_after_inspection_cannot_apply_old_mapping(review):
    work(review.inspect)
    with zipfile.ZipFile(review.archive) as old:
        contents = {n: old.read(n) for n in old.namelist()}
    manifest = json.loads(contents["manifest.json"])
    manifest["list"]["name"] = "Different package"
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(review.archive, "w") as new:
        for name, data in contents.items():
            new.writestr(name, data)
    before = dump(review)
    with pytest.raises(ValueError, match="package changed"):
        work(review.prepare)
    assert review.prepared is None and dump(review) == before


def test_workspace_change_and_closed_session_cannot_publish(review, monkeypatch, tmp_path):
    work(review.inspect)
    work(review.prepare)
    before = dump(review)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "different.sqlite")
    assert not review.current()
    with pytest.raises(WorkspaceChanged):
        work(review.apply)
    assert dump(review) == before
    review.close()
    with pytest.raises(WorkspaceChanged):
        work(review.inspect)


def test_duplicate_destinations_and_apply_before_review_do_not_write(review):
    before = dump(review)
    with pytest.raises(ValueError, match="Review changes"):
        work(review.apply)
    work(review.inspect)
    with pytest.raises(ValueError, match="separate destination"):
        work(review.prepare, paper_mapping={"first": "one", "second": "one"})
    assert dump(review) == before


def test_session_close_at_final_publication_cancels_without_a_second_ui_signal(review):
    work(review.inspect)
    work(review.prepare)
    before = dump(review)

    class ClosingTicket(Ticket):
        def publish(self, action):
            review.close()
            return super().publish(action)

    with pytest.raises(Cancelled):
        work(review.apply, ClosingTicket())
    assert dump(review) == before


def test_search_limit_counts_only_active_targets_in_a_simulated_lifecycle_view(review, monkeypatch):
    import copy
    from uuid import uuid4

    from test_sync_files import LOCAL, paper_payload

    from paper_daily import package_review

    monkeypatch.setattr(package_review, "MAX_SEARCH_RESULTS", 1)
    work(review.inspect)
    work(review.prepare)
    receipt = work(review.apply)
    original = receipt["identity_mapping"]["ref:example"]["portable_id"]
    client = review.importer.client
    earlier = str(uuid4())
    client.save(
        client.new_graph_operation("paper", earlier, {**paper_payload(), "title": "Earlier paper"})
    )
    observed_graph = client._optimistic_graph

    def inactive_view(conn):
        graph = copy.deepcopy(observed_graph(conn))
        for identity in (earlier, original):
            graph[0][("paper", identity)]["active"] = False
        return graph

    # The current protocol refuses paper deletion. Simulate the defensive read
    # boundary without admitting a fake tombstone or changing that protocol.
    monkeypatch.setattr(client, "_optimistic_graph", inactive_view)
    before = dump(review)
    result = work(review.search, "")
    assert result == {"papers": [{"id": LOCAL, "title": "Paper", "year": 2026}], "more": False}
    assert dump(review) == before
