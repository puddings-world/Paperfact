"""The phone page carries what the desk has: close readings, decks, the list's survey."""

from __future__ import annotations

import json
import sqlite3

import pytest

from paper_daily import pocket, presentations, store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    for module, name, folder in (
        (pocket, "PDF_DIR", "pdf"),
        (pocket, "FIG_DIR", "figures"),
        (pocket, "OUT_DIR", "pocket"),
        (pocket, "SLIDES_DIR", "pocket/slides"),
        (presentations, "DECK_DIR", "decks"),
        (presentations, "FIG_DIR", "figures"),
    ):
        dest = tmp_path / folder
        dest.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(module, name, dest)
    monkeypatch.setattr(pocket, "ensure_pdfjs", dict)
    monkeypatch.setattr(pocket, "ensure_typesetting", dict)
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    store._migrate(conn)
    store.upsert_papers(
        conn,
        [
            {
                "id": "ref:a",
                "title": "A Paper",
                "venue": "MICCAI",
                "year": 2025,
                "source": "test",
                "abstract": "About A.",
            },
            {
                "id": "ref:b",
                "title": "B Paper",
                "venue": "MICCAI",
                "year": 2024,
                "source": "test",
                "abstract": "About B.",
            },
        ],
    )
    conn.execute(
        "INSERT INTO dives(paper_id, body, written_at) VALUES "
        "('ref:a', '## 一句話結論\n結論。', 'now')"
    )
    conn.execute(
        "INSERT INTO close_readings(paper_id, body, written_at) VALUES "
        "('ref:a', '## 3 Method\n說明。\n[[Figure 1]]\n看這張。', 'now')"
    )
    conn.execute("INSERT INTO lists(id, name, created_at) VALUES ('cat', 'Cataract', 'now')")
    conn.execute("INSERT INTO lists(id, name, created_at) VALUES ('other', 'Other', 'now')")
    conn.execute(
        "INSERT INTO list_papers(list_id, paper_id, position, added_at) VALUES "
        "('cat', 'ref:a', 0, 'now'), ('other', 'ref:b', 0, 'now')"
    )
    conn.execute(
        "INSERT INTO list_surveys(list_id, body, papers, written_at) VALUES "
        "('cat', '## 這個領域在解決什麼\n白內障。', 3, '2026-10-12T00:00')"
    )
    conn.commit()
    conn.close()
    return tmp_path


def _deck(tmp_path) -> presentations.Deck:
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    figures = tmp_path / "figures" / "ref_a"
    figures.mkdir(parents=True)
    (figures / "p02-Figure_1.png").write_bytes(png)
    (figures / "index.json").write_text(
        json.dumps(
            [
                {
                    "label": "Figure 1",
                    "caption": "Figure 1: Overview.",
                    "page": 2,
                    "file": "p02-Figure_1.png",
                    "kind": "figure",
                }
            ]
        ),
        encoding="utf-8",
    )
    slide = presentations.Slide(
        "Overview",
        "Method",
        "One idea",
        ["A point."],
        "Say this.",
        ["original", "figure:1"],
        figure="figure:1",
    )
    return presentations.Deck(
        "ref:a",
        "A Paper",
        "A Paper, explained",
        "guide",
        "Newcomers",
        10,
        [slide],
        [
            {
                "id": "original",
                "label": "Original text",
                "kind": "original",
                "page": None,
                "url": "https://doi.org/10.1/a",
            },
            {"id": "figure:1", "label": "Figure 1", "kind": "figure"},
        ],
        [
            {
                "id": "figure:1",
                "label": "Figure 1",
                "caption": "Figure 1: Overview.",
                "page": 2,
                "file": "p02-Figure_1.png",
            }
        ],
        [],
        "2026-10-12",
    )


def test_the_page_carries_close_reading_deck_and_survey(workspace):
    presentations.save_deck(_deck(workspace))
    papers, files, surveys = pocket.collect(["ref:a", "ref:b"])

    a, b = papers
    assert "[[Figure 1]]" in a["close"] and b["close"] == ""
    assert [f["label"] for f in a["figures"]] == ["Figure 1"]

    (deck,) = a["decks"]
    assert deck["mode"] == "guide" and deck["label"] == "論文導讀"
    assert deck["href"] in files and files[deck["href"]].endswith("ref_a-guide.html")
    (slide,) = deck["slides"]
    assert slide["title"] == "Overview" and slide["notes"] == "Say this."
    assert slide["figure"]["label"] == "Figure 1" and slide["figure"]["src"] in files
    assert slide["tables"] == []
    assert b["decks"] == []

    # The survey goes out once per list, with the page's papers that are in it;
    # a list without a survey is not mentioned.
    assert [(s["id"], s["papers"], s["papers_total"]) for s in surveys] == [("cat", ["ref:a"], 3)]


def test_the_written_page_embeds_both_data_blocks(workspace):
    built = pocket.write(["ref:a"], workspace / "pocket" / "index.html")
    html = built["out"].read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert "/*__PAPERS__*/null" not in html and "/*__SURVEYS__*/null" not in html
    assert "白內障。" in html and "看這張。" in html
    assert built["surveys"][0]["name"] == "Cataract"


def test_a_table_dropped_on_the_canvas_reaches_the_outline(workspace):
    made = _deck(workspace)
    made.slides[0].elements = [
        {
            "kind": "table",
            "x": 40,
            "y": 120,
            "w": 600,
            "h": 200,
            "size": 18,
            "header": True,
            "rows": [["Method", "Dice"], ["SASVi", "0.754"]],
        },
    ]
    presentations.save_deck(made)
    papers, _files, _surveys = pocket.collect(["ref:a"])
    (slide,) = papers[0]["decks"][0]["slides"]
    assert slide["tables"] == [{"rows": [["Method", "Dice"], ["SASVi", "0.754"]], "header": True}]
