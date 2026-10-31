"""Provider formatting tolerance never grants authority to invented paper IDs."""

import json

import pytest
from test_list_create import db as db_fixture

from paper_daily import list_create, lists, llm

db = db_fixture


@pytest.mark.parametrize("prefix", ["References [12]: ", "```json\n", "A preface [3].\n```\n"])
def test_messy_model_bibliography_keeps_actual_entries(monkeypatch, prefix):
    entries = [{"title": "Verified first study"}, {"title": "Verified second study"}]
    reply = prefix + json.dumps(entries) + "\n```\nFurther reading [9]."
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (reply, "ok"))
    assert lists.parse_bibliography("A messy bibliography", strict=True) == entries


@pytest.mark.parametrize("prefix", ["Here is the answer [12]: ", "```\n", "Commentary\n```json\n"])
def test_topic_parser_accepts_preface_without_changing_payload(prefix):
    assert list_create._json(prefix + '{"queries":["cohort design"]}\n```') == {
        "queries": ["cohort design"]
    }


def test_prefaced_topic_still_rejects_invented_ids_without_creating_data(db, monkeypatch):
    replies = iter(
        [
            'Question [12]: {"queries":["cohort design"]}',
            'Choice [3]: {"ids":["invented"]}',
        ]
    )
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (next(replies), "ok"))
    monkeypatch.setattr(
        list_create,
        "fetch",
        lambda *a, **k: json.dumps(
            {"data": [{"paperId": "retrieved", "title": "A retrieved study"}]}
        ).encode(),
    )
    with pytest.raises(ValueError):
        list_create.create("Research", "cohort design", "topic")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM papers").fetchone()[0] == 0


@pytest.mark.parametrize(
    "reply,expect,items,wanted",
    [
        ('{"queries":["cohort"]}', dict, None, {"queries": ["cohort"]}),
        ('Preamble [12]\n[{"title":"A"}]\nAppendix [9]', list, dict, [{"title": "A"}]),
        (
            '```json\n{"a":"brackets [12] in a string"}\n```',
            dict,
            None,
            {"a": "brackets [12] in a string"},
        ),
        ('Bad prefix {not JSON} then {"ok":true}', dict, None, {"ok": True}),
        ("[]", list, dict, []),
    ],
)
def test_typed_json_helper_is_pure_and_preserves_values(monkeypatch, reply, expect, items, wanted):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Pure parse called AI"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Pure parse called AI"))
    assert llm.reply_json(reply, expect, items) == wanted


@pytest.mark.parametrize(
    "reply,expect,items",
    [
        ("null", dict, None),
        ("[]", dict, None),
        ("not JSON", list, dict),
        ("[12]", list, dict),
        ('{"not":"a list"}', list, dict),
    ],
)
def test_typed_json_helper_refuses_missing_requested_shape(reply, expect, items):
    with pytest.raises(ValueError):
        llm.reply_json(reply, expect, items)


def test_prefaced_bibliography_creates_exact_stored_order_and_preserves_existing_list(
    db, monkeypatch
):
    existing = list_create.create("Existing research", mode="empty")
    entries = [
        {"title": "First research paper", "year": 2025},
        {"title": "Second research paper", "year": 2024},
    ]
    calls = []

    def reply(*args, **kwargs):
        calls.append(kwargs["task"])
        return "References [12]:\n" + json.dumps(entries) + "\nAppendix [9].", "ok"

    monkeypatch.setattr(llm, "complete", reply)
    monkeypatch.setattr(lists.s2, "match_title", lambda title: None)
    monkeypatch.setattr(lists.resolve, "fill_gaps", lambda row: (row, False))
    imported = list_create.create("New reading", "a messy bibliography")
    assert imported["added"] == 2 and imported["id"] != existing["id"]
    rows = db.execute(
        "SELECT citation FROM list_papers WHERE list_id=? ORDER BY position", (imported["id"],)
    ).fetchall()
    assert [row[0] for row in rows] == ["First research paper", "Second research paper"]
    assert db.execute("SELECT name FROM lists WHERE id=?", (existing["id"],)).fetchone()[0] == (
        "Existing research"
    )
    assert calls == ["list_parse"]
