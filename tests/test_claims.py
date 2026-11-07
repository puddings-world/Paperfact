"""核心論點 cards: picked from the verified highlights, linked to their sentence, and
never written over once the reader has made them their own."""

from __future__ import annotations

import json
import sqlite3

import pytest

from paper_daily import claims, llm, paper_highlights, pdf_highlights, store

PID = "ref:wet"
QUOTES = [
    "Existing datasets come from real surgeries and cover isolated tasks only.",
    "We introduce WetCat, the first wet-lab cataract surgery video dataset for skill assessment.",
    "Phase annotations cover capsulorhexis and phacoemulsification in every video.",
    "The baseline reaches 0.82 accuracy on phase recognition under five-fold validation.",
]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(claims, "PDF_DIR", tmp_path)
    pdf = tmp_path / "ref_wet.pdf"
    pdf.write_bytes(b"%PDF-1.4 wetcat")
    store.init_db()
    with store.connect() as c:
        store.upsert_papers(c, [{"id": PID, "title": "WetCat", "venue": "ACM MM",
                                 "year": 2025, "source": "test", "abstract": "A dataset."}])
        for i, quote in enumerate(QUOTES):
            c.execute(
                "INSERT INTO pdf_ai_highlights(paper_id, document_hash, source_key, "
                "analysis_hash, anchor, quote, reason) VALUES (?,?,?,?,?,?,?)",
                (PID, pdf_highlights.document_hash(pdf), f"k{i}", "a",
                 json.dumps({"p0": i, "o0": 3, "p1": i, "o1": 9}), quote, f"理由 {i}"),
            )
    monkeypatch.setattr(
        paper_highlights, "cached",
        lambda pid, pages=None: {"items": [{"text": QUOTES[1], "kind": "contribution"}]},
    )
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    return c


def _reply(*picks):
    return json.dumps(
        {"claims": [{"id": i, "claim": f"論點 {i}", "explain": f"解釋 {i}"} for i in picks]},
        ensure_ascii=False,
    )


def _cards(conn):
    return conn.execute(
        "SELECT body, page, anchor FROM notes WHERE paper_id=? AND kind='claim' "
        "ORDER BY id DESC", (PID,),
    ).fetchall()


def test_core_claims_become_cards_that_point_at_their_sentence(conn, monkeypatch):
    prompts = []

    def complete(prompt, **k):
        prompts.append((prompt, k["task"]))
        return _reply(1, 3), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert claims.write(PID) == (2, "")
    first, second = _cards(conn)
    # Newest first in the notes tab, so the first claim is stored last.
    assert first["body"].startswith(f"> {QUOTES[1]}\n\n論點 1\n\n解釋 1")
    assert first["page"] == 2 and json.loads(first["anchor"])["p0"] == 1
    assert second["body"].startswith(f"> {QUOTES[3]}")
    # The candidates carry their kind, and the call uses the highlights' AI route.
    assert '"kind": "contribution"' in prompts[0][0] and prompts[0][1] == "paper_highlights"


def test_ids_that_are_not_candidates_are_dropped_not_fatal(conn, monkeypatch):
    reply = "好的：\n" + json.dumps({"claims": [
        {"id": 9, "claim": "不存在", "explain": "x"},
        {"id": "1", "claim": "字串 id", "explain": "x"},
        {"id": 2, "claim": "", "explain": "x"},
        {"id": 0, "claim": "論點 0", "explain": "解釋 0"},
        {"id": 0, "claim": "重複", "explain": "x"},
    ]}, ensure_ascii=False)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (reply, "ok"))
    assert claims.write(PID) == (1, "")
    assert [c["body"].split("\n\n")[1] for c in _cards(conn)] == ["論點 0"]


def test_a_rerun_keeps_the_cards_the_reader_edited(conn, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_reply(0, 1), "ok"))
    claims.write(PID)
    edited = conn.execute(
        "SELECT id FROM notes WHERE kind='claim' AND body LIKE '%論點 0%'"
    ).fetchone()["id"]
    conn.execute("UPDATE notes SET body = body || '\n我的補充' WHERE id=?", (edited,))
    conn.commit()
    # Without force, cards that exist are left alone and no call is made.
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no call expected"))
    assert claims.write(PID) == (0, "已有核心論點卡")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_reply(2, 3), "ok"))
    assert claims.write(PID, force=True) == (2, "")
    bodies = [c["body"] for c in _cards(conn)]
    assert any("我的補充" in b for b in bodies)
    assert not any("論點 1" in b for b in bodies)
    assert sum("論點 2" in b or "論點 3" in b for b in bodies) == 2


def test_a_failed_answer_leaves_the_cards_alone(conn, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_reply(0), "ok"))
    claims.write(PID)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("I cannot help with that.", "ok"))
    made, reason = claims.write(PID, force=True)
    assert made == 0 and "無法解析" in reason
    assert len(_cards(conn)) == 1


def test_too_few_highlights_asks_for_them_first(conn, monkeypatch):
    conn.execute("UPDATE pdf_ai_highlights SET hidden=1 WHERE source_key IN ('k0', 'k1')")
    conn.commit()
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no call expected"))
    made, reason = claims.write(PID)
    assert made == 0 and "分析原文重點" in reason
