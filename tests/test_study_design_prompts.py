"""Study-design prompt contracts through actual producers, with fixture evidence only.

Fake completions verify request text and persistence, not scientific model quality.
"""

import json
import sqlite3
from contextlib import closing

import pymupdf
import pytest

from paper_daily import brief, closeread, dive, llm, paper_highlights, research_questions, store
from paper_daily.ai_types import Completion
from paper_daily.document_reader import from_workspace
from paper_daily.sync_capture import install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer


@pytest.fixture(params=["theory", "qualitative"])
def material(request):
    if request.param == "theory":
        return (
            "theory",
            "Under compactness, every sequence has a convergent subsequence.",
            "## 3 Theorem and proof\nThe stated compactness assumption bounds the claim.\n",
        )
    return (
        "qualitative",
        "Participants described conflicting interpretations during reflective coding.",
        "## 3 Materials and interpretation\nThe interview material permits alternative readings.\n",
    )


@pytest.fixture(params=[False, True], ids=["unbound", "enrolled"])
def workspace(tmp_path, monkeypatch, request, material):
    database = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
    if request.param:
        prepare(database, workspace_id="workspace", device_id="device")
        SyncClient(Journal(database, workspace_id="workspace", device_id="device"), research_writer)
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        if request.param:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="workspace", device_id="device")
        store.upsert_papers(
            conn,
            [
                dict(
                    id="paper",
                    title="Fixture " + material[0],
                    year=2026,
                    venue="Fixture",
                    source="fixture",
                )
            ],
        )
        conn.execute(
            "INSERT INTO queue(paper_id,rank,state,role) VALUES('paper',1,'pending','main')"
        )
    root = tmp_path / "pdf"
    root.mkdir()
    path = root / "paper.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30, 40), material[1])
        pdf.save(path)
    document = from_workspace(database, legacy_root=root).resolve("paper")
    assert document.available
    with pymupdf.open(document.path) as pdf:
        text = "".join(page.get_text() for page in pdf)
    assert material[1] in text
    pack = "Study material (" + material[0] + "):\n" + text

    def prepared(conn, row):
        return brief.PreparedPack(
            pack, document.path, snapshot=brief.input_snapshot(conn, row["id"]), document=document
        )

    monkeypatch.setattr(brief, "pack_text", prepared)
    monkeypatch.setattr(llm, "settings", lambda **kwargs: "fixture-route")
    return database, document, pack


def test_close_reading_request_uses_applicable_design_and_keeps_actual_saved_body(
    workspace, material, monkeypatch
):
    database, document, pack = workspace
    body = material[2] + (material[1] + "\n") * 65
    calls = []

    def complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        system = kwargs["system"]
        for clause in (
            "理論研究",
            "質性研究",
            "文獻綜述",
            "原文有資料集或評估指標時",
            "只在原文實際使用時",
            "不適用",
            "原文的編號與名稱",
            "不要四捨五入",
            "逐字保留",
            "你看不到",
            "不宣稱已完成形式驗證",
        ):
            assert clause in system
        assert prompt == pack and kwargs["task"] == "dive" and kwargs["timeout"] == 1800
        return body, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert closeread.write("paper", database=database) == (body, "ok")
    assert len(calls) == 1
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute(
            "SELECT body,spec FROM close_readings WHERE paper_id='paper'"
        ).fetchone() == (body, "2026-10-study-design")
        conn.row_factory = sqlite3.Row
        assert closeread.get(conn, "paper") == body
        assert closeread.select(conn, ["paper"]) == []
    assert document.available


def test_deep_dive_request_keeps_design_specific_evidence_and_actual_storage(
    workspace, material, monkeypatch
):
    database, _document, pack = workspace
    body = material[2] + (material[1] + "\n") * 20
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        system = kwargs["system"]
        assert "定理與證明、觀察、材料" in system
        assert "最多五個,不必湊數" in system
        assert "後續方法、論證或證據章節" in system
        assert "不可套用同一組品質分數" in system
        assert prompt == pack and kwargs["task"] == "dive" and kwargs["cfg"] == "fixture-route"
        return body, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert tuple(dive._generate_for("paper", database=database)) == (body, "ok")
    assert calls == [pack]
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT body,spec FROM dives WHERE paper_id='paper'").fetchone() == (
            body,
            "2026-10-study-design",
        )


def test_old_recipe_outputs_remain_readable_and_only_explicit_rewrite_selects_them(
    workspace, monkeypatch
):
    database, _document, _pack = workspace
    old_close = "saved close\n" * 300
    old_dive = "saved dive\n" * 100
    calls = []

    def complete(_prompt, **kwargs):
        calls.append(kwargs["task"])
        return (old_close if kwargs["system"] == closeread.CLOSE_INSTRUCTIONS else old_dive), "ok"

    # Use the actual observed producers, including enrolled source/target receipts,
    # to seed previous-recipe saved output; raw SQL must not bypass those guards.
    with monkeypatch.context() as legacy:
        legacy.setattr(closeread, "CLOSE_SPEC", "2026-10-sections")
        legacy.setattr(dive, "DIVE_SPEC", "2026-10-research-evidence")
        legacy.setattr(llm, "complete", complete)
        assert closeread.write("paper", database=database) == (old_close, "ok")
        assert tuple(dive._generate_for("paper", database=database)) == (old_dive, "ok")
    assert calls == ["dive", "dive"]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("saved read invoked AI"))
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        assert closeread.get(conn, "paper") == old_close
        assert closeread.select(conn, ["paper"]) == []
        assert closeread.select(conn, ["paper"], rewrite=True) == ["paper"]
        assert dive._select(conn, 5, None, None, rewrite=False) == []
        assert [r["id"] for r in dive._select(conn, 5, None, None, rewrite=True)] == ["paper"]
        assert conn.execute("SELECT body,spec FROM dives").fetchone()[:] == (
            old_dive,
            "2026-10-research-evidence",
        )


def test_questions_accept_one_grounded_theoretical_or_qualitative_question_and_keep_cache(
    material, tmp_path, monkeypatch
):
    source = dict(
        pages=[dict(page=1, text=material[1])], explanation=material[2], close_reading=material[2]
    )
    monkeypatch.setattr(research_questions, "CACHE_DIR", tmp_path / "questions")
    monkeypatch.setattr(research_questions, "context", lambda _pid: source)
    calls = []
    question = dict(
        question="Which stated condition limits this conclusion?",
        why="Inspect the scope in the original.",
        evidence=material[1],
    )

    def complete(prompt, **kwargs):
        calls.append(prompt)
        system = kwargs["system"]
        for text in (
            "最多 6 個",
            "不必湊數",
            "觀察、證明、材料",
            "不要泛用問題",
            "逐字引用",
        ):
            assert text in system
        assert json.loads(prompt) == source and kwargs["task"] == "ask"
        return Completion(json.dumps(dict(questions=[question])))

    monkeypatch.setattr(llm, "complete_result", complete)
    result, _reason = research_questions.ensure("paper")
    assert result["items"] == [dict(question, page=1)]
    path = research_questions._path("paper")
    saved = path.read_bytes()
    assert research_questions.ensure("paper")[0] == result and len(calls) == 1
    assert research_questions.cached("paper") == result and path.read_bytes() == saved
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: Completion(json.dumps(dict(questions=[])))
    )
    assert research_questions.ensure("paper", force=True)[0] is None
    assert research_questions.cached("paper")["items"] == result["items"]


def test_highlights_accept_one_exact_proof_or_observation_without_filling_quota(
    material, tmp_path, monkeypatch
):
    pages = [dict(page=1, text=material[1])]
    monkeypatch.setattr(paper_highlights, "CACHE_DIR", tmp_path / "highlights")
    monkeypatch.setattr(paper_highlights, "read_original", lambda _pid: pages)
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        system = kwargs["system"]
        assert "觀察、證明、材料或實驗" in system
        assert "不必湊數" in system
        assert "不宣稱形式驗證" in system
        assert material[1] in prompt and kwargs["task"] == "paper_highlights"
        assert kwargs["cfg"] == "fixture-route"
        return Completion(
            json.dumps(
                dict(
                    items=[
                        dict(
                            id=0,
                            kind="evidence",
                            reason="The exact stated condition or observation.",
                        )
                    ]
                )
            )
        )

    monkeypatch.setattr(llm, "complete_result", complete)
    result, reason = paper_highlights.generate("paper", cfg="fixture-route")
    assert reason == "ok" and len(result["items"]) == 1
    assert result["items"][0]["text"] == material[1]
    assert result["items"][0]["page"] == 1 and result["version"] == 2
    path = paper_highlights._path("paper")
    saved = path.read_bytes()
    assert paper_highlights.generate("paper")[1] == "cached"
    assert len(calls) == 1 and path.read_bytes() == saved
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: Completion(json.dumps(dict(items=[])))
    )
    assert paper_highlights.generate("paper", force=True, cfg="fixture-route")[0] is None
    assert path.read_bytes() == saved


# A deliberate empty reply is an outcome, not a malformed candidate count.
EMPTY_QUESTION_REASON = "本次未辨識出有原文支持的研究問題。"


@pytest.fixture
def question_cache(material, tmp_path, monkeypatch):
    source = dict(
        pages=[dict(page=1, text=material[1])],
        explanation=material[2],
        close_reading=material[2],
    )
    item = dict(
        question="Which stated condition limits this conclusion?",
        why="Inspect the scope in the original.",
        evidence=material[1],
    )
    state = {"reply": {"questions": [item]}}
    calls = []
    monkeypatch.setattr(research_questions, "CACHE_DIR", tmp_path / "questions")
    monkeypatch.setattr(paper_highlights, "CACHE_DIR", tmp_path / "highlights")
    monkeypatch.setattr(research_questions, "context", lambda _pid: source)

    def complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        assert kwargs["task"] == "ask"
        return Completion(json.dumps(state["reply"]))

    monkeypatch.setattr(llm, "complete_result", complete)
    return source, state, calls


def test_no_supported_questions_is_cached_once_without_a_saved_result(question_cache):
    source, state, calls = question_cache
    state["reply"] = {"questions": []}
    assert research_questions.ensure("paper") == (None, EMPTY_QUESTION_REASON)
    cached = research_questions.cached("paper")
    assert cached["items"] == [] and cached["reason"] == EMPTY_QUESTION_REASON
    assert 0 < len(cached["reason"]) <= 80
    path = research_questions._path("paper")
    saved = path.read_bytes()
    for _ in range(3):
        assert research_questions.ensure("paper") == (None, EMPTY_QUESTION_REASON)
        assert research_questions.cached("paper") == cached
        assert path.read_bytes() == saved
    assert len(calls) == 1
    assert research_questions.ensure("paper", force=True) == (None, EMPTY_QUESTION_REASON)
    assert len(calls) == 2
    with pytest.raises(ValueError):
        research_questions.validate([], source["pages"])


@pytest.mark.parametrize("changed_source", [False, True], ids=["forced", "changed"])
def test_no_supported_refresh_preserves_existing_items(question_cache, changed_source):
    source, state, calls = question_cache
    old, _reason = research_questions.ensure("paper")
    assert old["items"] and len(calls) == 1
    if changed_source:
        source["explanation"] += " Changed interpretation."
    state["reply"] = {"questions": []}
    assert research_questions.ensure("paper", force=not changed_source) == (
        None,
        EMPTY_QUESTION_REASON,
    )
    retained = research_questions.cached("paper")
    assert retained["items"] == old["items"]
    assert retained["source_hash"] == old["source_hash"]
    assert retained["reason"] == EMPTY_QUESTION_REASON
    assert (retained["failed_source_hash"] != old["source_hash"]) is changed_source
    path = research_questions._path("paper")
    saved = path.read_bytes()
    for _ in range(3):
        value, reason = research_questions.ensure("paper")
        if changed_source:
            assert value is None and reason == EMPTY_QUESTION_REASON
        else:
            assert value["items"] == old["items"]
        assert research_questions.cached("paper") == retained
        assert path.read_bytes() == saved
    assert len(calls) == 2


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"questions": None},
        {"questions": False},
        {"questions": 0},
        {"questions": ""},
        {"questions": {}},
        {"questions": [{}]},
        {"questions": ["malformed"]},
    ],
)
def test_malformed_question_shapes_remain_refused_without_empty_outcome(question_cache, reply):
    source, state, calls = question_cache
    state["reply"] = reply
    result = research_questions.produce(source)
    assert result["items"] == []
    assert result["reason"] and result["reason"] != EMPTY_QUESTION_REASON
    assert len(calls) == 1
    assert not research_questions._path("paper").exists()
    with pytest.raises(ValueError):
        research_questions.validate(reply.get("questions"), source["pages"])
