"""Lossless legacy workflow values and explicitly declared Markdown bytes."""

import hashlib
import math
import os
import sqlite3
from contextlib import closing

import pytest

from paper_daily import legacy_workflow as legacy
from paper_daily import store
from paper_daily.workspace_service import Cancelled, Ticket

STAMP = "2026-10-30T12:34:56.123456+08:00"


def queue(**changes):
    return (
        dict(
            paper_id="child",
            rank=-2.75,
            state="deferred",
            role="manual",
            parent_id="parent",
            reason="A researcher's exact reason",
            queued_at=STAMP,
            delivered_at=None,
            read_at=STAMP,
        )
        | changes
    )


def event(**changes):
    return (
        dict(
            id=27,
            paper_id="child",
            delivered_at=STAMP,
            brief_path=None,
            role=None,
            note="Preserve original delivery note",
        )
        | changes
    )


def test_exact_queue_fields_custom_role_finite_rank_and_original_timestamps_remain():
    source = queue(role="custom-module-role")
    assert legacy.validate_queue(source) == source
    assert source["rank"] == -2.75 and source["queued_at"] == STAMP
    assert source["delivered_at"] is None and source["parent_id"] == "parent"
    assert legacy.validate_event(event())["id"] == 27


@pytest.mark.parametrize(
    "rank",
    [True, math.inf, -math.inf, math.nan, "2.5", 10**10000],
    ids=["boolean", "positive_inf", "negative_inf", "nan", "text", "overflow"],
)
def test_unknown_or_nonfinite_rank_refuses_without_coercion(rank):
    with pytest.raises(ValueError):
        legacy.validate_queue(queue(rank=rank))


@pytest.mark.parametrize(
    "change", [{"state": "invented"}, {"queued_at": "2026-10-30"}, {"extra": "future-unknown"}]
)
def test_unknown_queue_fields_or_naive_time_are_not_guessed(change):
    with pytest.raises(ValueError):
        legacy.validate_queue(queue(**change))


def test_declared_markdown_bytes_are_exact_and_metadata_read_has_no_writes(tmp_path):
    root = tmp_path / "briefs"
    root.mkdir()
    path = root / "paper-pack.md"
    content = b"# Exact brief\n\nClinical ? and ??.\n<script>not executed</script>\n"
    path.write_bytes(content)
    result = legacy.read_brief(path, trusted_root=root)
    assert result.data == content and result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.descriptor["media_type"] == "text/markdown"
    assert legacy.brief_current(result)
    stat = path.stat()
    path.write_bytes(b"X" + content[1:])
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert not legacy.brief_current(result)


@pytest.mark.parametrize("kind", ["outside", "binary", "cancel"])
def test_undeclared_binary_or_cancelled_brief_has_no_authority(tmp_path, kind):
    root = tmp_path / "briefs"
    root.mkdir()
    path = (tmp_path if kind == "outside" else root) / "pack.md"
    path.write_bytes(b"\x00binary" if kind == "binary" else b"# Text")
    ticket = Ticket()
    if kind == "cancel":
        ticket.cancel()
    with pytest.raises((ValueError, Cancelled)):
        legacy.read_brief(path, trusted_root=root, ticket=ticket)


def test_inventory_preserves_original_log_identity_without_synthesizing_lists(tmp_path):
    database = tmp_path / "papers.db"
    brief = tmp_path / "briefs" / "2026-10-30" / "child-pack.md"
    brief.parent.mkdir(parents=True)
    brief.write_bytes(b"# Exact saved pack")
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        for owner in ("child", "parent"):
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) "
                "VALUES(?,?,?,'Fixture',2026,'fixture')",
                (owner, owner, owner),
            )
        q = queue()
        conn.execute("INSERT INTO queue VALUES(?,?,?,?,?,?,?,?,?)", tuple(q.values()))
        delivery = event(brief_path=str(brief))
        conn.execute("INSERT INTO reading_log VALUES(?,?,?,?,?,?)", tuple(delivery.values()))
        captured = legacy.inventory(conn, source_root=tmp_path)
        assert captured["queue"] == [q] and captured["reading_log"] == [delivery]
        assert captured["briefs"][27].data == b"# Exact saved pack"
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
