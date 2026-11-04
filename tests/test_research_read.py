"""External agents read everything a workspace holds about a paper, read-only."""

import json

import pytest

from paper_daily import local_operations as ops
from paper_daily import store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    anchor = json.dumps({"p0": 2})
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(id="ref:a", title="HoughSAM geometry", venue="MICCAI",
                                        year=2026, source="test", abstract="Abstract A")])
        conn.execute("INSERT INTO lists(id,name,note,created_at) VALUES ('l','Cataract','why','t')")
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,state,added_at) "
                     "VALUES ('l','ref:a',0,'read','t')")
        conn.execute("INSERT INTO dives(paper_id,body,written_at) VALUES ('ref:a',?, 't')",
                     ("講解" * 50,))
        conn.execute("INSERT INTO close_readings(paper_id,body,spec,written_at) "
                     "VALUES ('ref:a','精讀','s','t')")
        conn.executemany(
            "INSERT INTO notes(paper_id,body,created_at,kind,page) VALUES ('ref:a',?,?,?,?)",
            [("我的筆記 incision", "t1", "note", 3), ("## 主張", "t2", "key", 4)],
        )
        conn.executemany(
            "INSERT INTO chat(paper_id,role,body,created_at) VALUES ('ref:a',?,?,?)",
            [("user", "怎麼定義 skill?", "t1"), ("assistant", "結論 (p.2)", "t2")],
        )
        conn.execute("INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,"
                     "analysis_hash,anchor,quote,reason,hidden) VALUES "
                     "('ref:a','h','k','a',?,'AI quote','method',0)", (anchor,))
        conn.execute("INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,"
                     "analysis_hash,anchor,quote,reason,hidden) VALUES "
                     "('ref:a','h','k2','a',?,'Hidden quote','x',1)", (anchor,))
        conn.execute("INSERT INTO cites(paper_id,ref_key,title,purpose,contexts_json,edited,"
                     "written_at) VALUES ('ref:a','1','Prior work','baseline','[\"ctx\"]',0,'t')")
        conn.execute("INSERT INTO list_surveys(list_id,body,papers,spec,written_at,edited) "
                     "VALUES ('l','Survey body','[]','s','t',0)")
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "ref_a.txt").write_text("x" * 250, encoding="utf-8")
    return tmp_path


def read(**args):
    result = ops.dispatch("papers.read", args)
    assert result["ok"], result
    return result["result"]["sections"]


def test_everything_but_the_extracted_text_comes_back_by_default(workspace):
    sections = read(paper_id="ref:a")
    assert set(sections) == set(ops_sections()) - {"full_text"}
    assert sections["paper"]["lists"][0]["name"] == "Cataract"
    assert sections["paper"]["lists"][0]["state"] == "read"
    assert sections["close_reading"]["text"] == "精讀"
    assert [n["kind"] for n in sections["notes"]["items"]] == ["note", "key"]
    assert [t["role"] for t in sections["chat"]["items"]] == ["user", "assistant"]
    marks = sections["highlights"]["ai_marks"]["items"]
    assert marks == [{"quote": "AI quote", "page": 3, "reason": "method"}]  # Hidden left out.
    assert sections["citations"]["items"][0]["contexts"] == ["ctx"]
    assert sections["questions"] is None and sections["context"] is None


def ops_sections():
    from paper_daily.research_read import SECTIONS

    return SECTIONS


def test_a_long_text_is_paged_one_section_at_a_time(workspace):
    first = read(paper_id="ref:a", sections=["full_text"], max_chars=100)["full_text"]
    assert len(first["text"]) == 100 and first["length"] == 250 and first["next_offset"] == 100
    last = read(paper_id="ref:a", sections=["full_text"], max_chars=100, offset=200)["full_text"]
    assert len(last["text"]) == 50 and last["next_offset"] is None
    dive = read(paper_id="ref:a", sections=["dive"], max_chars=10)["dive"]
    assert dive["length"] == 100 and dive["next_offset"] == 10


@pytest.mark.parametrize("args, code", [
    (dict(paper_id="missing"), "not_found"),
    (dict(paper_id="ref:a", sections=["secrets"]), "invalid_input"),
    (dict(paper_id="ref:a", sections=["dive", "notes"], offset=5), "invalid_input"),
    (dict(paper_id="ref:a", max_chars=10**6), "invalid_input"),
])
def test_bad_requests_say_what_to_fix(workspace, args, code):
    result = ops.dispatch("papers.read", args)
    assert not result["ok"] and result["error"]["code"] == code


def test_reading_writes_nothing(workspace):
    def snapshot():
        with store.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("notes", "chat", "dives", "lists", "list_papers", "kv")}

    before = snapshot()
    read(paper_id="ref:a", sections=list(ops_sections()))
    ops.dispatch("lists.context", dict(list_id="l"))
    ops.dispatch("papers.search", dict(query="incision"))
    assert snapshot() == before


def test_search_finds_papers_by_title_notes_or_answers(workspace):
    found = ops.dispatch("papers.search", dict(query="incision"))["result"]["papers"]
    assert [(p["id"], p["matched"]) for p in found] == [("ref:a", ["notes"])]
    found = ops.dispatch("papers.search", dict(query="geometry", list_id="l"))["result"]["papers"]
    assert found[0]["matched"] == ["title"]
    assert ops.dispatch("papers.search", dict(query="geometry", list_id="other"))[
        "result"]["papers"] == []


def test_a_list_says_what_it_is_for_and_how_far_it_is_read(workspace):
    context = ops.dispatch("lists.context", dict(list_id="l"))["result"]
    assert context["note"] == "why" and context["survey"]["body"] == "Survey body"
    assert context["states"] == {"read": 1} and context["reading_goal"] is None
    assert ops.dispatch("lists.context", dict(list_id="nope"))["error"]["code"] == "not_found"
