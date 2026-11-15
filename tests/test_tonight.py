"""The nightly run names its paper, the reader opens on it, and asks before analysing."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from paper_daily import cli, store, tonight
from paper_daily import queue as qmod


def add_paper(conn, paper_id, title="A paper", year=2026):
    conn.execute(
        "INSERT INTO papers(id, venue, year, title, title_key, authors_json, source, "
        "is_canon, score, crawled_at) VALUES (?,?,?,?,?,'[]','test',0,0.5,'now')",
        (paper_id, "ICLR", year, title, paper_id),
    )


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    add_paper(c, "ICLR:2026:new", "The newest paper")
    add_paper(c, "ICLR:2016:old", "An old reference", 2016)
    c.commit()
    yield c
    c.close()


def test_the_delivered_paper_is_the_one_to_open_and_to_ask_about(conn):
    assert tonight.paper(conn) is None and tonight.offer(conn) is None
    tonight.record(conn, "ICLR:2026:new")
    assert tonight.paper(conn) == "ICLR:2026:new"
    assert tonight.offer(conn) == "ICLR:2026:new"


def test_a_delivery_from_more_than_a_day_ago_is_not_tonights(conn):
    tonight.record(conn, "ICLR:2026:new")
    later = datetime.now(UTC) + timedelta(hours=25)
    assert tonight.paper(conn, later) is None
    assert tonight.offer(conn, later) is None
    assert tonight.paper(conn, datetime.now(UTC) + timedelta(hours=23)) == "ICLR:2026:new"


def test_a_paper_already_explained_is_opened_but_not_asked_about(conn):
    tonight.record(conn, "ICLR:2026:new")
    conn.execute(
        "INSERT INTO dives(paper_id, body, written_at) VALUES ('ICLR:2026:new', 'x', 'now')"
    )
    assert tonight.paper(conn) == "ICLR:2026:new"
    assert tonight.offer(conn) is None


def test_an_answer_ends_the_question_until_the_next_delivery(conn):
    tonight.record(conn, "ICLR:2026:new")
    tonight.answer(conn)
    assert tonight.offer(conn) is None
    assert tonight.paper(conn) == "ICLR:2026:new"
    store.set_kv(conn, tonight.KEY, {"at": "2099-01-01T00:00:00+00:00", "id": "ICLR:2016:old"})
    assert tonight.offer(conn, datetime(2099, 1, 1, 1, tzinfo=UTC)) == "ICLR:2016:old"


def test_a_paper_that_is_gone_or_a_damaged_record_offers_nothing(conn):
    tonight.record(conn, "no-such-paper")
    assert tonight.paper(conn) is None and tonight.offer(conn) is None
    store.set_kv(conn, tonight.KEY, {"at": "not a time", "id": "ICLR:2026:new"})
    assert tonight.paper(conn) is None and tonight.offer(conn) is None
    store.set_kv(conn, tonight.KEY, "nonsense")
    assert tonight.paper(conn) is None
    tonight.answer(conn)


def test_a_companion_brings_no_companions_of_its_own(conn):
    for paper_id in ("ref1", "ref2"):
        add_paper(conn, paper_id, year=2020)
    conn.execute(
        "INSERT INTO queue(paper_id, rank, state, role, queued_at) "
        "VALUES ('ICLR:2026:new', 10, 'delivered', 'main', 'now')"
    )
    conn.executemany(
        "INSERT INTO refs(paper_id, ref_paper_id, influential) VALUES (?,?,1)",
        [("ICLR:2026:new", "ICLR:2016:old"), ("ICLR:2016:old", "ref1"),
         ("ICLR:2016:old", "ref2")],
    )
    assert qmod.add_companions(conn, "ICLR:2026:new") == ["ICLR:2016:old"]
    # Delivered in its turn, the reference queues nothing ahead of the next new paper.
    qmod.mark(conn, "ICLR:2016:old", "delivered")
    assert qmod.add_companions(conn, "ICLR:2016:old") == []
    queued = {r["paper_id"] for r in conn.execute("SELECT paper_id FROM queue")}
    assert queued == {"ICLR:2026:new", "ICLR:2016:old"}


def app_args(**given):
    return SimpleNamespace(**{"next": False, "restart": False, "paper": None, "pdf": None,
                              "tonight": False, **given})


def test_app_tonight_opens_the_delivered_paper_or_falls_back_to_next(conn, monkeypatch):
    from paper_daily.desktop import main

    calls = []
    monkeypatch.setattr(main, "run", lambda **kw: calls.append(kw) or 0)
    cli.cmd_app(app_args(tonight=True))
    assert calls[-1]["open_next"] is True and calls[-1]["paper"] is None

    tonight.record(conn, "ICLR:2026:new")
    conn.commit()
    cli.cmd_app(app_args(tonight=True))
    assert calls[-1]["open_next"] is False and calls[-1]["paper"] == "ICLR:2026:new"
    # An explicit paper is not overridden.
    cli.cmd_app(app_args(tonight=True, paper="ICLR:2016:old"))
    assert calls[-1]["paper"] == "ICLR:2016:old"
    cli.cmd_app(app_args())
    assert calls[-1]["open_next"] is False and calls[-1]["paper"] is None


def test_the_nightly_script_opens_tonights_paper_through_the_launcher():
    from paper_daily.config import ROOT

    assert '"--tonight"' in (ROOT / "scripts" / "nightly.ps1").read_text(encoding="utf-8")
    assert '= "--tonight" Then args = " --tonight"' in (
        ROOT / "scripts" / "launch-app.vbs"
    ).read_text(encoding="utf-8")


def test_the_banner_asks_once_and_either_answer_is_remembered(conn):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.analysis_settings import TonightBanner
    from paper_daily.desktop.main import LIGHT

    QApplication.instance() or QApplication([])
    tonight.record(conn, "ICLR:2026:new")
    conn.commit()
    banner = TonightBanner(LIGHT)
    asked = []
    banner.analyse.connect(asked.append)
    assert banner.isHidden()
    banner.ask("ICLR:2026:new", "The newest paper", "ICLR 2026")
    assert not banner.isHidden() and "The newest paper" in banner.label.text()
    banner.no.click()
    assert banner.isHidden() and asked == []
    assert tonight.offer(conn) is None

    store.set_kv(conn, tonight.ANSWERED, None)
    conn.commit()
    assert tonight.offer(conn) == "ICLR:2026:new"
    banner.ask("ICLR:2026:new", "The newest paper", "ICLR 2026")
    banner.yes.click()
    assert banner.isHidden() and asked == ["ICLR:2026:new"]
    assert tonight.offer(conn) is None
