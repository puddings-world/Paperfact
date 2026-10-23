import json
import threading
from pathlib import Path

import pytest

from paper_daily import list_create, llm, store
from paper_daily import research_plan as rp
from paper_daily.http import FetchError


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    with store.connect() as conn:
        yield conn


def paper(pid="p1", title="A verified study", **extra):
    return dict(paperId=pid, title=title, year=2025, abstract="Retrieved research evidence.",
                url="https://www.semanticscholar.org/paper/" + pid,
                provider="Semantic Scholar", **extra)


def selection(ids=("p1", "p2")):
    return dict(summary="A grounded reading route", gaps=["Full texts need review"], papers=[
        dict(id=pid, branch="Evaluation", role="method", why="Addresses the stated research need",
             prerequisites=list(ids[:i])) for i, pid in enumerate(ids)
    ])


def fake_plan(monkeypatch, response=None, depth="quick"):
    answers = [dict(queries=["reasoning compression", "counterevidence"])]
    answers += [dict(queries=[f"gap {i}"]) for i in range(rp.DEPTHS[depth]["rounds"] - 1)]
    answers.append(response if response is not None else selection())
    iterator = iter(answers)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (json.dumps(next(iterator)), "ok"))
    calls = []

    def search(query):
        calls.append(query)
        return [paper(), paper("p2", "An opposing study")], []

    monkeypatch.setattr(rp, "search", search)
    return calls


def test_preview_writes_no_list_then_commits_only_selected_with_report(db, monkeypatch):
    calls = fake_plan(monkeypatch)
    plan = rp.propose("Research questions and a seed paper", "quick")
    assert len(calls) == 2 and len(plan["items"]) == 2
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("commit called AI"))
    result = rp.commit("My route", plan, ["p2"])
    assert result["added"] == 1
    assert db.execute("SELECT title FROM papers").fetchone()[0] == "An opposing study"
    survey = db.execute("SELECT body,papers FROM list_surveys").fetchone()
    assert survey[1] == 1 and "Full texts need review" in survey[0]
    assert "未勾選" in survey[0] and "https://www.semanticscholar.org/paper/p2" in survey[0]
    assert "reasoning compression" in survey[0] and "摘要層級" in survey[0]
    assert rp.commit("My route", plan, ["p2"]) == result
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 1


@pytest.mark.parametrize("ids", [("invented",), ("p1", "p1")])
def test_rejects_unverified_and_duplicate_selections_without_writes(db, monkeypatch, ids):
    fake_plan(monkeypatch, selection(ids))
    with pytest.raises(ValueError, match="以外"):
        rp.propose("Research topic", "quick")
    assert db.execute("SELECT count(*) FROM papers").fetchone()[0] == 0


def test_rejects_invalid_reading_dependencies(db, monkeypatch):
    result = selection()
    result["papers"][0]["prerequisites"] = ["p2"]
    fake_plan(monkeypatch, result)
    with pytest.raises(ValueError, match="閱讀關係"):
        rp.propose("Research topic", "quick")


@pytest.mark.parametrize("depth,rounds", [("quick", 1), ("standard", 2), ("deep", 3)])
def test_depth_bounds_search_and_gap_review(db, monkeypatch, depth, rounds):
    calls = fake_plan(monkeypatch, depth=depth)
    plan = rp.propose("Research topic", depth)
    assert len(calls) == rounds + 1
    assert plan["queries"] == calls and plan["depth"] == depth


def test_no_results_never_turn_model_memory_into_papers(db, monkeypatch):
    fake_plan(monkeypatch)
    monkeypatch.setattr(rp, "search", lambda q: ([], ["search unavailable"]))
    with pytest.raises(ValueError, match="沒有取得"):
        rp.propose("Research topic", "quick")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_partial_search_failure_preserves_coverage_warning(db, monkeypatch):
    fake_plan(monkeypatch)
    monkeypatch.setattr(rp, "search", lambda q: (
        [paper(), paper("p2", "An opposing study")], ["OpenAlex unavailable"]))
    plan = rp.propose("Research topic", "quick")
    assert plan["warnings"] == ["OpenAlex unavailable"]
    assert "OpenAlex unavailable" in rp.report(plan)


def test_search_fallback_retains_openalex_identity_without_fake_s2_id(db, monkeypatch):
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        if "semanticscholar" in url:
            raise FetchError("429 fixture")
        return json.dumps(dict(results=[dict(
            id="https://openalex.org/W123", display_name="A real index entry",
            publication_year=2025, doi="https://doi.org/10.1234/example",
            abstract_inverted_index={"Verified": [0], "abstract": [1]},
            authorships=[],
        )])).encode()

    monkeypatch.setattr(rp, "fetch", fetch)
    rows, warnings = rp.search("reasoning")
    assert rows[0]["paperId"] == "OA:W123" and rows[0]["abstract"] == "Verified abstract"
    assert warnings and all(kw["retries"] == 1 for _, kw in calls)
    fake_plan(monkeypatch, selection(("OA:W123",)))
    monkeypatch.setattr(rp, "search", lambda q: (rows, warnings))
    plan = rp.propose("Research topic", "quick")
    rp.commit("Research", plan, ["OA:W123"])
    row = db.execute("SELECT s2_id,doi,page_url FROM papers").fetchone()
    assert row[0] is None and row[1] == "10.1234/example"
    assert row[2] == "https://openalex.org/W123"


def test_search_deduplicates_doi_and_title(db, monkeypatch):
    fake_plan(monkeypatch, selection(("p1",)))
    monkeypatch.setattr(rp, "search", lambda q: ([
        paper(externalIds={"DOI": "10.1/X"}),
        paper("p2", "Another title version", externalIds={"DOI": "10.1/x"}),
        paper("p3", "A verified study"),
    ], []))
    assert list(rp.propose("Research topic", "quick")["candidates"]) == ["p1"]


def test_cancel_during_search_discards_result_before_next_ai_call(db, monkeypatch):
    fake_plan(monkeypatch)
    cancel = threading.Event()

    def search(query):
        cancel.set()
        return [paper()], []

    monkeypatch.setattr(rp, "search", search)
    with pytest.raises(rp.Cancelled):
        rp.propose("Research topic", "quick", cancel=cancel)
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_account_and_model_snapshot_survives_settings_change(db, monkeypatch):
    llm.save_settings(profile="one", backend="cli", model="model-a")
    llm.use_profile("one")
    fake_plan(monkeypatch)
    answers = iter([dict(queries=["topic"]), selection()])
    observed = []

    def complete(*args, **kwargs):
        observed.append(llm.settings(task="list_parse").model)
        llm.save_settings(profile="one", model="model-b")
        return json.dumps(next(answers)), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    rp.propose("Research topic", "quick")
    assert observed == ["model-a", "model-a"]
    assert llm.settings(task="list_parse").model == "model-b"


def test_commit_failure_rolls_back_and_can_retry_without_ai(db, monkeypatch):
    fake_plan(monkeypatch)
    plan = rp.propose("Research topic", "quick")
    original = rp.upsert_papers
    monkeypatch.setattr(rp, "upsert_papers", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        rp.commit("Research", plan, ["p1"])
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    monkeypatch.setattr(rp, "upsert_papers", original)
    assert rp.commit("Research", plan, ["p1"])["added"] == 1


def test_existing_paper_content_is_not_replaced_by_discovery(db, monkeypatch):
    row = list_create.lists._paper_from_match(dict(title="A verified study"), paper())
    row["abstract"] = "Locally curated abstract"
    store.upsert_papers(db, [row])
    db.commit()
    fake_plan(monkeypatch)
    plan = rp.propose("Research topic", "quick")
    rp.commit("Research", plan, ["p1"])
    assert db.execute("SELECT abstract FROM papers").fetchone()[0] == "Locally curated abstract"


@pytest.mark.parametrize("chosen", [[], ["unknown"]])
def test_empty_or_tampered_review_selection_is_not_committed(db, monkeypatch, chosen):
    fake_plan(monkeypatch)
    plan = rp.propose("Research topic", "quick")
    with pytest.raises(ValueError, match="勾選"):
        rp.commit("Research", plan, chosen)
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


@pytest.mark.parametrize("bad", ["not JSON", "[]", "null"])
def test_invalid_model_response_is_retryable_and_leaves_no_list(db, monkeypatch, bad):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (bad, "ok"))
    with pytest.raises(ValueError, match="格式"):
        rp.propose("Research topic", "quick")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_research_route_survives_offline_bundle_transfer(db, monkeypatch, tmp_path):
    from paper_daily import bundle

    fake_plan(monkeypatch)
    plan = rp.propose("Research topic", "quick")
    result = rp.commit("Research", plan, ["p1", "p2"])
    (tmp_path / "files").mkdir()
    monkeypatch.setattr(bundle, "DATA_DIR", tmp_path / "files")
    monkeypatch.setattr(bundle, "PDF_DIR", tmp_path / "files" / "pdf")
    path = tmp_path / "research.zip"
    bundle.export(result["id"], path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "recipient.db")
    monkeypatch.setattr(bundle, "fetch", lambda *a, **k: pytest.fail("offline import used network"))
    bundle.import_(path)
    with store.connect() as recipient:
        saved = recipient.execute("SELECT body,papers FROM list_surveys").fetchone()
        assert saved[0] == rp.report(plan) and saved[1] == 2
        assert recipient.execute("SELECT name FROM lists").fetchone()[0] == "Research"


def test_observed_public_openalex_search_shape(monkeypatch):
    data = (Path(__file__).parent / "fixtures" / "research_search_openalex.json").read_bytes()

    def fetch(url, **kwargs):
        if "semanticscholar" in url:
            raise FetchError("fixture unavailable")
        return data

    monkeypatch.setattr(rp, "fetch", fetch)
    rows, warnings = rp.search("chain of thought faithfulness")
    assert len(rows) == 1 and warnings
    assert rows[0]["paperId"] == "OA:W7172327399"
    assert rows[0]["year"] == 2026 and not rows[0]["abstract"]
    assert rows[0]["url"] == "https://openalex.org/W7172327399"
