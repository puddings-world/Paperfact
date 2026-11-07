"""The share page: a draft a person edits, then a page built from that draft."""

from __future__ import annotations

import json

import pytest

from paper_daily import share


def test_a_quote_and_the_thought_after_it_stay_apart():
    quote, thought = share._split_quote("> a passage\n> continues\nwhat I made of it")
    assert quote == "> a passage\n> continues"
    assert thought == "what I made of it"
    md = share._note_md({"body": "> q\nmine", "kind": "note", "page": 3})
    # A blank line is what stops Markdown reading the thought as more quote.
    assert "> q\n\nmine" in md
    assert "第 3 頁" in md


def test_dive_headings_sit_under_the_paper():
    assert share._demote("## 問題\ntext\n### 細節", 2) == "#### 問題\ntext\n##### 細節"
    assert share._demote("###### deep", 2) == "###### deep"


def test_short_names():
    assert share._short("StepAL: Step-aware Active Learning") == "StepAL"
    assert share._short("Cataract-LMM Large-Scale Multi-Source Benchmark") == "Cataract-LMM"


@pytest.fixture
def share_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(share, "SHARE_DIR", tmp_path)
    monkeypatch.setattr(
        share, "_paper_md", lambda conn, pid, out: (f"## {pid}\n", {"short": pid})
    )
    return tmp_path


def test_an_edited_draft_is_never_overwritten(share_dir):
    first = share.draft(["p1"], slug="s")
    first["path"].write_text("# mine, edited", encoding="utf-8")
    second = share.draft(["p1"], slug="s")
    assert second["path"].name == "draft.new.md"
    assert first["path"].read_text(encoding="utf-8") == "# mine, edited"


def test_build_keeps_the_draft_inside_its_script(share_dir):
    (share_dir / "s").mkdir()
    (share_dir / "s" / "draft.md").write_text(
        "# T\n\n> a quote with </script> in it\n\n![f](fig/x/a.png)\n", encoding="utf-8"
    )
    built = share.build("s")
    html = built["page"].read_text(encoding="utf-8")
    assert "<title>T</title>" in html
    assert html.count("</script>") == html.count("<script")
    start = html.index("const DRAFT = ") + len("const DRAFT = ")
    end = html.index(";\n", start)
    assert "</script>" in json.loads(html[start:end].replace("<\/", "</"))
    assert built["missing"] == ["fig/x/a.png"]


def _facts(pid):
    return {"short": pid, "title": pid, "venue": "V", "authors": "A", "doi": "", "figures": 0,
            "tables": 0, "cites": 0, "worth": 0, "notes": 0, "dive": "d", "abstract": "a"}


@pytest.fixture
def compare_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(share, "SHARE_DIR", tmp_path)
    monkeypatch.setattr(share, "_paper_md", lambda conn, pid, out: (f"## {pid}\n", _facts(pid)))
    calls = []
    monkeypatch.setattr(
        share, "compare", lambda facts: (calls.append(facts), ("#### 對照", "ok"))[1]
    )
    return calls


def test_a_second_compare_draft_does_not_pay_for_an_unused_comparison(compare_dir):
    ids = ["p1", "p2", "p3"]
    first = share.draft(ids, slug="s", with_compare=True)
    text = first["path"].read_text(encoding="utf-8")
    assert len(compare_dir) == 1 and "#### 對照" in text
    assert "依各篇的深度講解" in text and "兩篇" not in text
    again = share.draft(ids, slug="s", with_compare=True)
    assert len(compare_dir) == 1
    assert "draft.md 已存在" in again["compare_failed"]
    forced = share.draft(ids, slug="s", with_compare=True, force=True)
    assert len(compare_dir) == 2 and forced["path"].name == "draft.new.md"
