"""Reading list import.

The parsing half is the fragile part: bibliography text copied out of a PDF carries
line numbers, page headers and words broken across lines, and getting an entry
boundary wrong silently merges two papers into one.
"""

import json

from paper_daily.lists import _paper_from_match, clean_bibliography

RAW = """REFERENCES
Tim Dettmers, Mike Lewis, Younes Belkada, and Luke Zettlemoyer. GPT3.int8(): 8-bit matrix
multiplication for transformers at scale. In Advances in neural information processing systems,
volume 35, pp. 30318-30332, 2022.
8
432
433
Under review as a conference paper at ICLR 2027
Elias Frantar, Saleh Ashkboos, Torsten Hoefler, and Dan Alistarh. GPTQ, 2023.
"""


def test_clean_bibliography_strips_page_furniture():
    """Line numbers down the margin of a review PDF would otherwise read as years."""
    cleaned = clean_bibliography(RAW)
    assert "Under review as a conference paper" not in cleaned
    assert "REFERENCES" not in cleaned
    assert "\n8\n" not in f"\n{cleaned}\n"
    assert "432" not in cleaned
    assert "GPT3.int8()" in cleaned
    assert "GPTQ" in cleaned


def test_clean_bibliography_keeps_numbers_inside_entries():
    """Only whole lines that are just a number are furniture; page ranges are data."""
    cleaned = clean_bibliography(RAW)
    assert "30318-30332" in cleaned
    assert "volume 35" in cleaned


def test_paper_from_match_prefers_semantic_scholar():
    entry = {"title": "Rough Title", "authors": ["X"], "venue": "arXiv", "year": 2020}
    match = {
        "paperId": "abc123",
        "title": "GPTQ: Accurate Post-Training Quantization",
        "venue": "International Conference on Learning Representations",
        "year": 2023,
        "abstract": "an abstract",
        "citationCount": 2576,
        "externalIds": {"ArXiv": "2210.17323"},
        "openAccessPdf": {"url": "https://example/x.pdf"},
        "authors": [{"name": "Elias Frantar"}],
    }
    row = _paper_from_match(entry, match)
    assert row["title"].startswith("GPTQ")
    assert row["year"] == 2023
    assert row["arxiv_id"] == "2210.17323"
    assert row["citation_count"] == 2576
    assert "Elias Frantar" in row["authors_json"]
    assert row["source"] == "import"


def test_paper_from_match_falls_back_to_the_citation():
    """Software entries and old papers are not in Semantic Scholar; they still belong
    in the list, with whatever the citation itself said."""
    entry = {
        "title": "llama.cpp: LLM inference in C/C++",
        "authors": ["Georgi Gerganov"],
        "venue": "GitHub",
        "year": 2023,
        "url": "https://github.com/ggml-org/llama.cpp",
    }
    row = _paper_from_match(entry, None)
    assert row["title"] == entry["title"]
    assert row["venue"] == "GitHub"
    assert row["page_url"] == entry["url"]
    assert row["source"] == "import"
    assert row.get("s2_id") is None


def test_imported_ids_are_namespaced():
    """Imported papers share the table with the crawl, so their ids must not be able
    to collide with a conference paper's."""
    row = _paper_from_match({"title": "T", "year": 2020}, None)
    assert row["id"].startswith("ref:")


def test_cvf_venue_detection():
    """Imported venue strings arrive in many shapes, including truncated ones, and
    ICCV's long form contains CVPR's but for the word 'International'."""
    from paper_daily.sources.cvf import venue_code

    cvpr = [
        "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition",
        "Proceedings of the IEEE/CVF Conference on Computer Vision an",
        "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
    ]
    iccv = [
        "IEEE/CVF International Conference on Computer Vision",
        "Proceedings of the IEEE/CVF International Conferen",
    ]
    for v in cvpr:
        assert venue_code(v) == "CVPR", v
    for v in iccv:
        assert venue_code(v) == "ICCV", v
    assert venue_code("IEEE Winter Conference on Applications of Computer Vision") == "WACV"


def test_cvf_ignores_non_cvf_venues():
    """ECCV is not on CVF Open Access, and neither is anything from the big three."""
    from paper_daily.sources.cvf import venue_code

    for v in (
        "European Conference on Computer Vision",
        "Advances in Neural Information Processing Systems",
        "International Conference on Machine Learning",
        None,
        "",
    ):
        assert venue_code(v) is None, v


def _list_fixture(tmp_path, monkeypatch):
    """A three-paper list, with the network stubbed out."""
    import sqlite3

    from paper_daily import lists, store
    from paper_daily.enrich import s2
    from paper_daily.sources import arxiv, cvf, openalex

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(s2, "match_title", lambda title, **kw: None)
    monkeypatch.setattr(cvf, "pdf_url", lambda *a, **kw: None)
    monkeypatch.setattr(arxiv, "match_title", lambda *a, **kw: None)
    monkeypatch.setattr(openalex, "match_title", lambda *a, **kw: None)
    monkeypatch.setattr(lists, "parse_bibliography", lambda raw, log=None: [
        {"title": t.strip(), "authors": [], "venue": "arXiv", "year": 2024, "url": None}
        for t in raw.splitlines() if t.strip()
    ])

    conn = sqlite3.connect(tmp_path / "papers.db")
    conn.executescript(store.SCHEMA)
    conn.commit()
    conn.close()
    lists.import_list("Refs", "First paper\nSecond paper\nThird paper", list_id="refs")
    return lists


def test_remove_closes_the_gap_in_the_order(tmp_path, monkeypatch):
    from paper_daily.store import connect

    lists = _list_fixture(tmp_path, monkeypatch)
    with connect() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id='refs' ORDER BY position"
        )]
    assert lists.remove_paper("refs", ids[0])
    with connect() as conn:
        rows = conn.execute(
            "SELECT paper_id, position FROM list_papers WHERE list_id='refs' ORDER BY position"
        ).fetchall()
    # Holes in the positions would put the next added paper in the middle.
    assert [r[1] for r in rows] == [0, 1]
    assert [r[0] for r in rows] == ids[1:]


def test_remove_leaves_the_paper_in_the_corpus(tmp_path, monkeypatch):
    from paper_daily.store import connect

    lists = _list_fixture(tmp_path, monkeypatch)
    with connect() as conn:
        paper_id = conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id='refs' ORDER BY position"
        ).fetchone()[0]
    lists.remove_paper("refs", paper_id)
    with connect() as conn:
        assert conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone()


def test_remove_reports_a_paper_that_was_never_in_the_list(tmp_path, monkeypatch):
    lists = _list_fixture(tmp_path, monkeypatch)
    assert not lists.remove_paper("refs", "ref:nothing")


def test_add_appends_to_the_end(tmp_path, monkeypatch):
    from paper_daily.store import connect

    lists = _list_fixture(tmp_path, monkeypatch)
    result = lists.add_paper("refs", "Fourth paper")
    assert result["added"] == 1
    with connect() as conn:
        rows = conn.execute(
            "SELECT citation, position FROM list_papers WHERE list_id='refs' ORDER BY position"
        ).fetchall()
    assert rows[-1][0] == "Fourth paper"
    assert [r[1] for r in rows] == [0, 1, 2, 3]


def test_adding_a_paper_already_in_the_list_does_not_move_it(tmp_path, monkeypatch):
    from paper_daily.store import connect

    lists = _list_fixture(tmp_path, monkeypatch)
    result = lists.add_paper("refs", "First paper")
    assert result["added"] == 0
    assert result["reason"] == "already in this list"
    with connect() as conn:
        first = conn.execute(
            "SELECT citation FROM list_papers WHERE list_id='refs' ORDER BY position"
        ).fetchone()[0]
    assert first == "First paper"


def test_add_refuses_a_list_that_does_not_exist(tmp_path, monkeypatch):
    lists = _list_fixture(tmp_path, monkeypatch)
    assert lists.add_paper("nope", "Some paper")["added"] == 0


def test_openalex_reconstructs_the_inverted_abstract():
    from paper_daily.sources import openalex

    work = {"abstract_inverted_index": {"We": [0], "show": [1], "that": [2], "it": [3, 5],
                                        "works": [4], "well": [6]}}
    assert openalex._abstract(work) == "We show that it works it well"


def test_openalex_ignores_a_work_with_a_different_title(monkeypatch):
    """The search is fuzzy, so the title has to be checked or it hands back a
    neighbouring paper with full confidence."""
    from paper_daily.sources import openalex

    payload = {"results": [{"display_name": "A completely different paper",
                            "publication_year": 2020}]}
    monkeypatch.setattr(openalex, "fetch_text", lambda *a, **kw: json.dumps(payload))
    assert openalex.match_title("Cataract-1K Dataset") is None


def test_openalex_returns_the_open_access_pdf(monkeypatch):
    from paper_daily.sources import openalex

    payload = {"results": [{
        "display_name": "Cataract-1K Dataset",
        "publication_year": 2024,
        "doi": "https://doi.org/10.1038/x",
        "best_oa_location": {"pdf_url": "https://nature.com/x.pdf",
                             "source": {"display_name": "Scientific Data"}},
        "authorships": [{"author": {"display_name": "Negin Ghamsarian"}}],
        "cited_by_count": 42,
    }]}
    monkeypatch.setattr(openalex, "fetch_text", lambda *a, **kw: json.dumps(payload))
    got = openalex.match_title("Cataract-1K  dataset")
    assert got["pdf_url"] == "https://nature.com/x.pdf"
    assert got["venue"] == "Scientific Data"
    assert got["doi"] == "10.1038/x"
    assert got["year"] == 2024


def test_fill_gaps_leaves_an_existing_pdf_alone(monkeypatch):
    """A proceedings PDF beats anything a fallback would find."""
    from paper_daily import resolve
    from paper_daily.sources import arxiv, cvf, openalex

    monkeypatch.setattr(cvf, "pdf_url", lambda *a, **kw: "cvf.pdf")
    monkeypatch.setattr(arxiv, "match_title", lambda *a, **kw: "1234.5678")
    monkeypatch.setattr(openalex, "match_title", lambda *a, **kw: {"pdf_url": "oa.pdf"})
    row = {"title": "T", "venue": "ICML", "year": 2024, "pdf_url": "proceedings.pdf"}
    got, found = resolve.fill_gaps(dict(row))
    assert got["pdf_url"] == "proceedings.pdf"
    assert "cvf" not in found and "arxiv" not in found


def test_fill_gaps_uses_openalex_when_the_others_have_nothing(monkeypatch):
    from paper_daily import resolve
    from paper_daily.sources import arxiv, cvf, openalex

    monkeypatch.setattr(cvf, "pdf_url", lambda *a, **kw: None)
    monkeypatch.setattr(arxiv, "match_title", lambda *a, **kw: None)
    monkeypatch.setattr(openalex, "match_title", lambda *a, **kw: {
        "pdf_url": "https://nature.com/x.pdf", "venue": "Scientific Data", "year": 2024,
        "doi": "10.1038/x", "authors": ["Negin Ghamsarian"], "abstract": "words",
        "citation_count": 42, "page_url": None,
    })
    row = {"title": "Cataract-1K", "venue": "unknown", "year": 0}
    got, found = resolve.fill_gaps(row)
    assert got["pdf_url"] == "https://nature.com/x.pdf"
    assert (got["venue"], got["year"]) == ("Scientific Data", 2024)
    assert json.loads(got["authors_json"]) == ["Negin Ghamsarian"]
    assert "openalex-pdf" in found


def test_same_paper_accepts_a_paraphrased_citation():
    from paper_daily.sources.openalex import same_paper

    assert same_paper(
        "CSMAE: Cataract Surgery Masked Autoencoder",
        "CSMAE : Cataract Surgical Masked Autoencoder (MAE) Based Pre-Training",
    )
    assert same_paper(
        "BLINK: Multimodal LLMs Can See but Not Perceive",
        "BLINK: Multimodal Large Language Models Can See but Not Perceive",
    )


def test_same_paper_refuses_a_short_title_that_merely_shares_words():
    """A two-word entry is not enough to identify a paper.

    "llama.cpp" is a GitHub project, and both of its words appear in a real paper
    called "llama-roofline: a portable memory-bandwidth roofline for llama.cpp".
    The relaxed rule accepted that and renamed the row to the wrong work.
    """
    from paper_daily.sources.openalex import same_paper

    assert not same_paper(
        "llama.cpp", "llama-roofline: a portable memory-bandwidth roofline for llama.cpp"
    )
    assert not same_paper("Unsloth", "Unsloth-based fine-tuning of large language models")


def test_same_paper_refuses_a_neighbouring_paper_in_the_same_field():
    from paper_daily.sources.openalex import same_paper

    assert not same_paper(
        "Deep learning for multi-class segmentation in cataract surgery videos",
        "Domain-agnostic weakly supervised surgical instrument segmentation",
    )
    assert not same_paper(
        "RP-SAM2: Refined prompt SAM2 for surgical segmentation",
        "Foam Segmentation in Wastewater Treatment Plants: A Federated Learning Approach",
    )
