"""Raw retained slides and legacy PDF migration preserve one complete workspace."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from test_legacy_primary_migration import make as make  # noqa: F401
from test_sync_files import deck as make_deck
from test_sync_files import png
from test_workspace_primary_migration import controller

from paper_daily import store, sync_recovery
from paper_daily import sync_deck_publication as publication
from paper_daily.raw_deck_closure import read_detached
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_blobs import BlobManifest
from paper_daily.workspace_service import Ticket, _ReadOnlyStore


def test_mixed_raw_draft_and_legacy_originals_backup_to_fresh_editable_copy(
    make, monkeypatch, tmp_path
):
    fixture = make("A")
    deck = make_deck()
    deck.paper_id = "paper"
    deck.title = "Preserve raw slides alongside source A and primary B"
    deck._revision_figures = {"figure:1": png("red"), "figure:2": png("blue")}
    observed = publication.observe_deck("paper", "guide")
    raw = deck.to_dict()
    other = tmp_path / "unbound.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    monkeypatch.setattr(store, "DB_PATH", other)
    try:
        publication.publish_deck(deck, observation=observed, request_id="mixed-raw")
    except publication.StaleDeckError as error:
        assert error.candidate_id == "mixed-raw"
    else:
        raise AssertionError("Switched publication must retain original work")
    monkeypatch.setattr(store, "DB_PATH", fixture.database)
    worker = controller(fixture)
    plan = worker.stage(worker.catalog(), ("paper",))
    assert worker.commit(plan).outcome == "complete"
    service, _status = worker.refresh_readiness()
    package = tmp_path / "complete.zip"
    service.backup(package, Ticket())
    detached = tmp_path / "detached"
    sync_recovery.restore_detached(package, detached)
    read = read_detached(detached / "papers.db", "mixed-raw")
    assert read["deck"]["title"] == raw["title"]
    assert len(read["images"]) == 2 and read["publish"] is False
    adoption = RecoveryAdoptionService(detached / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    prepared = adoption.prepare(
        inspection, tmp_path / "editable", backup_output=tmp_path / "editable.zip",
        request_id=str(uuid4()))
    assert prepared["status"] == "prepared_for_review" and not prepared["uploaded"]
    with closing(sqlite3.connect(prepared["database"])) as conn:
        archived = [json.loads(row[0]) for row in conn.execute(
            "SELECT body_json FROM research_recovery_provenance")]
        source_rows = [row["record"] for row in archived if row["kind"] == "row"
                       and row["table"] == "research_file_drafts"]
        closures = [row["record"] for row in archived if row["kind"] == "row"
                    and row["table"] == "research_file_draft_closures"]
        assert len(source_rows) == 1 and json.loads(source_rows[0]["deck"]) == raw
        assert len(closures) == 1 and closures[0]["candidate_id"] == "mixed-raw"
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (0,)
        blob_root = Path(conn.execute(
            "SELECT blob_root FROM research_file_paths WHERE id=1").fetchone()[0])
        recorded = conn.execute("SELECT body_json FROM paper_later_outcomes").fetchone()[0]
        assert recorded == fixture.recorded["body_json"]
    blobs = _ReadOnlyStore(blob_root)
    for image in json.loads(closures[0]["inventory"])["images"]:
        expected = png("red") if image["id"] == "figure:1" else png("blue")
        assert (blobs.verified_path(BlobManifest(image["sha256"], image["size"])).read_bytes()
                == expected)
    assert fixture.path.read_bytes() == fixture.bytes
    assert sync_recovery.inspect(tmp_path / "editable.zip")["workspace_id"] != "workspace"
