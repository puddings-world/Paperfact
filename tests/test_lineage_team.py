"""The 脈絡 tab's 作者團隊 filter: earlier and later work sharing an author or an
institution with the paper, by OpenAlex ids."""

import json
import time
import urllib.parse

import pytest
from PySide6.QtWidgets import QApplication
from test_cites_views import _titles
from test_cites_views import pane as _pane

from paper_daily import lineage_team

pane = _pane


def _work(wid, doi, title, authors, places):
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "display_name": title,
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{a}", "display_name": a.lower()},
                "institutions": [{"id": f"https://openalex.org/{p}", "display_name": p}],
            }
            for a, p in zip(authors, places, strict=True)
        ],
    }


WORKS = [
    _work("W1", "10.1/own", "Centre paper", ["A1", "A2"], ["I1", "I2"]),
    _work("W10", "10.1/ref-a", "Shares an author", ["A1", "A9"], ["I9", "I9"]),
    _work("W11", "10.1/ref-b", "Unrelated reference", ["A8"], ["I8"]),
    _work("W20", None, "Shares an institution", ["A7"], ["I2"]),
    _work("W30", None, "A reference without identifiers", ["A2"], ["I7"]),
]


@pytest.fixture
def openalex(monkeypatch):
    asked = []

    def fetch_text(url, **_kw):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        key, _, value = query["filter"][0].partition(":")
        asked.append(key)
        if key == "ids.openalex":
            wanted = set(value.split("|"))
            hits = [w for w in WORKS if w["id"].rsplit("/", 1)[1] in wanted]
        elif key == "doi":
            wanted = set(value.split("|"))
            hits = [w for w in WORKS if w["doi"] and w["doi"].split("doi.org/")[1] in wanted]
        else:
            hits = [w for w in WORKS if w["display_name"] == value]
        return json.dumps({"results": hits})

    monkeypatch.setattr(lineage_team, "fetch_text", fetch_text)
    return asked


def test_works_are_found_by_id_then_doi_then_title_and_unknowns_stay_unknown(openalex):
    found = lineage_team.lookup(
        [
            {"work_id": "W20"},
            {"doi": "https://doi.org/10.1/REF-A"},
            {"title": "A reference without identifiers"},
            {"doi": "10.1/missing"},
            {"title": "Nobody wrote this"},
        ]
    )
    assert set(found[0]["institutions"]) == {"https://openalex.org/I2"}
    assert set(found[1]["authors"]) == {"https://openalex.org/A1", "https://openalex.org/A9"}
    assert set(found[2]["authors"]) == {"https://openalex.org/A2"}
    assert found[3] is None and found[4] is None
    # Identifiers are looked up in batches; only the bare reference costs a search.
    assert openalex.count("ids.openalex") == 1 and openalex.count("doi") == 1


def test_team_keeps_works_sharing_an_author_or_institution(openalex):
    refs = [
        {"ref_key": "1", "doi": "10.1/ref-a", "title": "Shares an author"},
        {"ref_key": "2", "doi": "10.1/ref-b", "title": "Unrelated reference"},
        {"ref_key": "3", "title": "A reference without identifiers"},
    ]
    later = [{"work_id": "W20", "title": "Shares an institution"}, {"work_id": "W99"}]
    result = lineage_team.team({"title": "Centre paper", "doi": "10.1/own"}, refs, later)
    assert result["refs"] == {
        "1": {"authors": ["a1"], "institutions": []},
        "3": {"authors": ["a2"], "institutions": []},
    }
    assert result["later"] == {"W20": {"authors": [], "institutions": ["I2"]}}
    assert (result["known"], result["total"], result["own"]) == (4, 5, True)


def test_a_paper_openalex_cannot_find_matches_nothing(openalex):
    result = lineage_team.team({"title": "Not indexed", "doi": None}, [{"ref_key": "1"}], [])
    assert result == {"refs": {}, "later": {}, "known": 0, "total": 1, "own": False}


def test_the_switch_filters_both_sides_and_labels_why(pane, monkeypatch):
    pane.settle()
    result = {
        "refs": {"7": {"authors": ["Ada"], "institutions": []}},
        "later": {"w3": {"authors": [], "institutions": ["NTU"]}},
        "known": 60,
        "total": 65,
        "own": True,
    }
    monkeypatch.setattr(lineage_team, "team", lambda *a, **k: result)
    pane._set_team("team")
    end = time.monotonic() + 5
    while pane._team_data is None and time.monotonic() < end:
        QApplication.processEvents()
    pane.settle()
    assert _titles(pane, "refs") == ["referencenumber7onmatrixfunctions"]
    assert _titles(pane, "later") == ["laterwork3buildingonit"]
    card = pane._cards[("title", "referencenumber7onmatrixfunctions")][1]
    assert "同作者：Ada" in card.layout().itemAt(0).widget().text()
    assert "參考文獻 1 篇、後續研究 1 篇" in pane._team_note.text()
    pane._set_team("all")
    pane.settle()
    assert len(_titles(pane, "refs")) == 40 and not pane._team_note.isVisible()
