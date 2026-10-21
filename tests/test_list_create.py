import json

import pytest

from paper_daily import list_create, lists, llm, store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        yield conn


def test_empty_lists_need_no_ai_and_same_names_get_distinct_ids(db, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("empty list used AI"))
    first = list_create.create("同名研究", mode="empty")
    second = list_create.create("同名研究", mode="empty")
    assert first["id"] != second["id"] and first["added"] == second["added"] == 0
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 2


def test_failed_ai_parsing_does_not_create_a_garbage_list(db, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (None, "login required"))
    with pytest.raises(ValueError, match="login required"):
        list_create.create("Research", "a messy bibliography")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_reference_list_resolves_and_preserves_order(db, monkeypatch):
    monkeypatch.setattr(
        llm,
        "complete",
        lambda *a, **k: (
            json.dumps([dict(title="First", year=2025), dict(title="Second", year=2024)]),
            "ok",
        ),
    )
    monkeypatch.setattr(lists.s2, "match_title", lambda title: None)
    monkeypatch.setattr(lists.resolve, "fill_gaps", lambda row: (row, False))
    result = list_create.create("References", "messy reference text")
    rows = db.execute(
        "SELECT citation FROM list_papers WHERE list_id=? ORDER BY position", (result["id"],)
    ).fetchall()
    assert [r[0] for r in rows] == ["First", "Second"]


def _topic(monkeypatch, chosen):
    responses = iter([json.dumps(dict(queries=["surgery video"])), json.dumps(dict(ids=chosen))])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (next(responses), "ok"))
    paper = dict(paperId="verified", title="An actual retrieved study", year=2025, venue="Medicine")
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return json.dumps(dict(data=[paper])).encode()

    monkeypatch.setattr(list_create, "fetch", fetch)
    return calls


def test_topic_only_imports_papers_from_real_search_results(db, monkeypatch):
    calls = _topic(monkeypatch, ["verified", "verified"])
    result = list_create.create("Clinical video", "研究手術影片", "topic")
    assert result["added"] == 1 and "query=surgery+video" in calls[0]
    assert db.execute("SELECT title FROM papers").fetchone()[0] == "An actual retrieved study"


def test_topic_rejects_hallucinated_paper_ids_before_creating_list(db, monkeypatch):
    _topic(monkeypatch, ["invented"])
    with pytest.raises(ValueError, match="以外"):
        list_create.create("Clinical video", "研究手術影片", "topic")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


@pytest.mark.parametrize("response", ["null", "[]", "not JSON"])
def test_malformed_topic_response_leaves_workspace_unchanged(db, monkeypatch, response):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (response, "ok"))
    with pytest.raises(ValueError, match="格式"):
        list_create.create("Research", "a research topic", "topic")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
