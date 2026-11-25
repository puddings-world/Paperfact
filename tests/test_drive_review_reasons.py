"""A waiting list says why, in Chinese, and the reason reaches sync.log once."""

import sqlite3

from paper_daily import drive_paper_receive, drive_review_reasons
from paper_daily.drive_review_reasons import LOG_NAME, explain, record


def test_reasons_are_explained_by_cause_and_unknown_ones_still_say_something():
    assert "PDF" in explain("The local PDF differs from Drive (3)")
    assert "筆記" in explain("Existing note changed; retain both copies for review")
    assert "自動重試" in explain("Bibliography changed while receiving; retry")
    assert explain("Something nobody anticipated") == "需要核對。"
    joined = explain("The local PDF differs from Drive (1) · Reading progress differs on 2 papers")
    assert "PDF" in joined and "閱讀進度" in joined
    assert explain("") == ""


def test_log_records_a_reason_once_and_its_clearing(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_review_reasons, "_written", {})
    for _ in range(3):
        record(tmp_path, {"a": "Unknown history", "b": ""}, names={"a": "Reading group"})
    record(tmp_path, {"a": ""}, names={"a": "Reading group"})
    lines = (tmp_path / LOG_NAME).read_text(encoding="utf-8").splitlines()
    assert [line.split("\t")[1:] for line in lines] == [
        ["a", "Reading group", "Unknown history"],
        ["b", "b", "ok"],
        ["a", "Reading group", "ok"],
    ]


def test_same_work_needs_agreeing_identifiers_and_years():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE papers(id TEXT, year INT, doi TEXT, arxiv_id TEXT)")
    conn.execute("INSERT INTO papers VALUES('p', 2017, '10.1/ABC', NULL)")
    same = drive_paper_receive._same_work
    assert same(conn, "p", {"doi": "10.1/abc", "arxiv_id": "1706.1", "year": 2018})
    assert same(conn, "p", {"doi": None, "arxiv_id": None, "year": None})
    assert not same(conn, "p", {"doi": "10.1/other", "arxiv_id": None, "year": 2017})
    # A survey and its namesake a decade later share a title, not an identity.
    assert not same(conn, "p", {"doi": None, "arxiv_id": None, "year": 2026})
