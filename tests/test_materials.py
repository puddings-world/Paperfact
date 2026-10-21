"""素材: exhibits with the rows the close reading reproduced, headings and quotable
sentences, with IDs a generated deck would cite."""

import json
import sqlite3

import pymupdf
import pytest

from paper_daily import materials, presentations, store

CLOSE = """## 3 Method

Text about the method.

## 4 Experiments

### 4.2 Results

This table answers the main question.

[[Table 1]]

| Dataset | Method | Dice |
|---|---|---|
| A | Ours | **0.754** |
| A | Base | 0.625 |

[[Figure 2]]

Later, Table 2 reports the ablation:

| Setting | IoU |
|---|---|
| full | 0.66 |
| no-reprompt | 0.40 |
"""

PAGE = """3 Method
We propose a re-prompting mechanism that significantly improves temporal consistency.
The threshold is defined as the number of frames the class set must differ.
Plain sentence without anything quotable here at all.
3.1 Overseer Model
Our method improves Dice by 12.9% over the frame-wise baseline.
0.5 To match the training configurations we rescale images to a fixed size
4 Experiments & Results
"""


@pytest.fixture
def paper(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(materials, "DATA_DIR", tmp_path)
    for name in ("PDF_DIR", "TEXT_DIR", "FIG_DIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(materials, name, tmp_path / name)
        monkeypatch.setattr(presentations, name, tmp_path / name)
    conn = sqlite3.connect(store.DB_PATH)
    conn.executescript(store.SCHEMA)
    store.upsert_papers(
        conn,
        [{"id": "ref:m", "title": "Material fixture", "venue": "J", "year": 2025, "source": "t"}],
    )
    conn.execute(
        "INSERT INTO close_readings(paper_id, body, written_at) VALUES (?,?,?)",
        ("ref:m", CLOSE, "now"),
    )
    conn.execute(
        "INSERT INTO dives(paper_id, body, written_at) VALUES (?,?,?)", ("ref:m", "dive", "now")
    )
    conn.commit()
    conn.close()
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 60), PAGE, fontsize=9)
    doc.save(tmp_path / "PDF_DIR" / "ref_m.pdf")
    folder = tmp_path / "FIG_DIR" / "ref_m"
    folder.mkdir()
    manifest = []
    for label, kind, name in (
        ("Table 1", "table", "t1.png"),
        ("Fig. 2", "figure", "f2.png"),
        ("Table 2", "table", "t2.png"),
    ):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        pix.save(folder / name)
        manifest.append(
            {"label": label, "caption": label + " caption", "page": 4, "file": name, "kind": kind}
        )
    (folder / "index.json").write_text(json.dumps(manifest), encoding="utf-8")
    return "ref:m"


def test_markdown_tables_drop_separators_and_bold():
    tables = materials.markdown_tables(CLOSE)
    assert [rows[0] for _start, rows in tables] == [
        ["Dataset", "Method", "Dice"],
        ["Setting", "IoU"],
    ]
    assert tables[0][1][1] == ["A", "Ours", "0.754"]


def test_tables_are_matched_by_marker_then_by_mention(paper):
    found = materials.collect(paper)
    by_label = {e["label"]: e for e in found.exhibits}
    assert by_label["Table 1"]["rows"][0] == ["Dataset", "Method", "Dice"]
    assert by_label["Table 1"]["section"] == "4.2 Results"
    assert by_label["Fig. 2"]["section"] == "4.2 Results" and "rows" not in by_label["Fig. 2"]
    assert by_label["Table 2"]["rows"] == [
        ["Setting", "IoU"],
        ["full", "0.66"],
        ["no-reprompt", "0.40"],
    ]


def test_exhibit_ids_match_generated_deck_evidence(paper):
    found = materials.collect(paper)
    evidence = presentations.collect_evidence(paper, {"original", "dive"})
    assert [e["id"] for e in found.exhibits] == [f["id"] for f in evidence["figures"]]
    assert [e["id"] for e in found.exhibits] == ["figure:1", "figure:2", "figure:3"]


def test_headings_keep_numbered_titles_and_drop_wrapped_sentences(paper):
    found = materials.collect(paper)
    assert [h["text"] for h in found.headings] == [
        "3 Method",
        "3.1 Overseer Model",
        "4 Experiments & Results",
    ]
    assert [h["level"] for h in found.headings] == [1, 2, 1]


def test_key_sentences_require_ai_analysis_and_show_cached_reasons(paper, monkeypatch):
    from paper_daily import paper_highlights

    monkeypatch.setattr(paper_highlights, "cached", lambda _id: None)
    assert materials.collect(paper).sentences == []
    item = dict(
        text="An exact original quote",
        page=1,
        kind="method",
        source="page:1",
        reason="研究方法的關鍵設計",
    )
    monkeypatch.setattr(paper_highlights, "cached", lambda _id: {"items": [item]})
    found = materials.collect(paper)
    assert found.sentences == [dict(item, origin="ai")]
    assert found.highlights["items"][0]["reason"]


def test_material_locations_are_cached_for_the_exact_pdf(paper, monkeypatch):
    item = dict(text="3 Method", page=1)
    materials._locate_materials(paper, [item])
    assert item["rect"] and item["document_hash"]
    fresh = dict(text="3 Method", page=1)
    monkeypatch.setattr(
        pymupdf, "open", lambda *a, **kw: pytest.fail("cached location rescanned PDF")
    )
    materials._locate_materials(paper, [fresh])
    assert fresh == item


def test_headings_fall_back_to_the_close_reading_without_a_pdf(paper, tmp_path):
    (tmp_path / "PDF_DIR" / "ref_m.pdf").unlink()
    found = materials.collect(paper)
    assert [h["text"] for h in found.headings][:2] == ["3 Method", "4 Experiments"]
    assert found.sentences == []
