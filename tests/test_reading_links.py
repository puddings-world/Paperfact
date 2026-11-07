import json

from paper_daily import reading_links, store
from paper_daily.ai_types import Completion
from paper_daily.desktop import reading
from paper_daily.desktop.main import palette


def test_links_follow_explanation_sections_and_cache_tracks_both_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(reading_links, "CACHE_DIR", tmp_path / "links")
    store.init_db()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO dives VALUES ('p','## Method\nThe controlled comparison.','now',NULL)"
        )
    analysis = dict(
        source_hash="pdf1", items=[dict(text="The original <claim>", page=2, reason="理由")]
    )
    calls = []

    def model(*args, **kwargs):
        calls.append(kwargs["task"])
        return Completion(
            json.dumps(
                dict(
                    links=[
                        dict(quote=0, section="dive:0", explanation="這段限定了方法適用範圍"),
                        dict(quote=1, section="missing", explanation="invented"),
                    ]
                )
            )
        )

    monkeypatch.setattr(reading_links.llm, "complete_result", model)
    result, reason = reading_links.prepare("p", analysis)
    assert reason == "ok" and len(result["links"]) == 1
    assert reading_links.prepare("p", analysis)[1] == "cached"
    assert calls == ["paper_highlights"]
    text = reading.render(
        "## Method\nThe controlled comparison.",
        None,
        [],
        palette(),
        highlights=analysis,
        links=result,
    )
    assert text.index("controlled comparison") < text.index("為何畫重點")
    assert "這段限定了方法適用範圍" in text and "paperfact-highlight:0" in text
    assert "&lt;claim&gt;" in text and "invented" not in text
    parts = reading_links.sections("## Changed\nNew explanation", None)
    assert reading_links.cached("p", parts, analysis) is None


def test_unlinked_quotes_are_explicit_and_never_invent_section_support():
    analysis = dict(items=[dict(text="Original statement", page=3, reason="Important limit")])
    rendered = reading.render("## Method\nSomething else", None, [], palette(), highlights=analysis)
    assert "尚未對應到講解段落" in rendered
    assert "Important limit" in rendered
    assert "與這段講解的關係" not in rendered


def test_an_answer_that_links_nothing_is_not_requested_on_every_open(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(reading_links, "CACHE_DIR", tmp_path / "links")
    store.init_db()
    with store.connect() as conn:
        conn.execute("INSERT INTO dives VALUES ('p','## Method\nThe comparison.','now',NULL)")
    analysis = dict(source_hash="pdf1", items=[dict(text="Original", page=1, reason="理由")])
    replies = iter(["These quotes do not support any section.", '說明：{"links": []}'])
    calls = []

    def model(*args, **kwargs):
        calls.append(1)
        return Completion(next(replies))

    monkeypatch.setattr(reading_links.llm, "complete_result", model)
    result, reason = reading_links.prepare("p", analysis)
    assert result["links"] == [] and "格式無法解析" in reason
    again, reason = reading_links.prepare("p", analysis)
    assert again["links"] == [] and "格式無法解析" in reason and len(calls) == 1
    parts = reading_links._context("p")
    assert reading_links.cached("p", parts, analysis) is not None
    reading_links.forget_unlinked("p")
    result, reason = reading_links.prepare("p", analysis)
    assert result["links"] == [] and "尚未找到" in reason and len(calls) == 2


def test_found_links_survive_an_explicit_retry_and_prose_around_json(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(reading_links, "CACHE_DIR", tmp_path / "links")
    store.init_db()
    with store.connect() as conn:
        conn.execute("INSERT INTO dives VALUES ('p','## Method\nThe comparison.','now',NULL)")
    analysis = dict(source_hash="pdf1", items=[dict(text="Original", page=1, reason="理由")])
    link = dict(quote=0, section="dive:0", explanation="支撐方法段落")
    monkeypatch.setattr(
        reading_links.llm,
        "complete_result",
        lambda *a, **k: Completion("結果如下 [1]：\n" + json.dumps({"links": [link]})),
    )
    assert reading_links.prepare("p", analysis)[0]["links"] == [link]
    reading_links.forget_unlinked("p")
    assert reading_links.prepare("p", analysis)[1] == "cached"
