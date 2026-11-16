"""A paper too new for Crossref still prints its own reference list."""

import json

from test_citation_coverage import answers
from test_research_compound import driver as driver
from test_research_compound import workspace as workspace
from test_research_generation import rows

from paper_daily import cites, llm
from paper_daily.sources import crossref

NATURE = """Steps are key surgical activities11. Cataract-1K has 1,000 videos13.

References
\t 1.\t Pesudovs, K. et al. Global estimates on the number of people blind by cataract: a
meta-analysis from 2000 to 2020. Eye 38, 2156–2172 (2024).
\t 2.\t Assi, L. et al. A Global Assessment of Eye Health and Quality of Life. JAMA
Ophthalmol 139, 526–541 (2021).
\t 3.\t Ghamsarian, N. et al. Cataract-1K Dataset for Deep-Learning-Assisted Analysis of
Cataract Surgery Videos. Sci Data 11, 373 (2024). https://doi.org/10.1038/s41597-024-03193-4.
\t 4.\t Ma, X., Nie, L. & Chu, H. Statistical methods for multivariate meta-analysis of
diagnostic tests. Stat Methods Med Res 25, 1596–1619 (2016).

Acknowledgements
This work was supported by a grant awarded in 2025 to the last author.
"""


def test_a_numbered_list_is_read_with_year_doi_and_the_whole_citation():
    listed = cites.listed_references(NATURE)
    assert list(listed) == ["1", "2", "3", "4"]
    third = listed["3"]
    assert third["title"].startswith("Cataract-1K Dataset for Deep-Learning-Assisted")
    assert third["year"] == 2024
    assert third["doi"] == "10.1038/s41597-024-03193-4"
    assert third["citation"].startswith("Ghamsarian, N. et al. Cataract-1K")
    # No marked author block: the whole string is kept, as for a publisher's entry.
    assert listed["4"]["title"].startswith("Ma, X., Nie, L. & Chu, H. Statistical")
    assert "Acknowledgements" not in listed["4"]["citation"]
    assert "supported" not in listed["4"]["citation"]


def test_bracketed_numbers_are_read_too():
    text = (
        "Body [1].\n\nReferences\n"
        "[1] A. Author. First paper title here. In NeurIPS, 2019.\n"
        "[2] B. Author and C. Other. Second paper title here. In ICML, 2020.\n"
        "[3] D. Author. Third paper title here. arXiv preprint, 2021.\n"
    )
    listed = cites.listed_references(text)
    assert [listed[k]["year"] for k in ("1", "2", "3")] == [2019, 2020, 2021]


def test_numbered_steps_after_an_author_year_bibliography_are_not_a_list():
    text = (
        "Body (Smith et al., 2020).\n\nReferences\n"
        + "Smith, J. and Jones, K. A paper. In ICLR, 2020.\n" * 12
        + "\nA Appendix\n"
        "1. For cases where one of i and j is affected in 2020 runs, see below.\n"
        "2. For cases where both are affected in 2021 runs, see below.\n"
        "3. Otherwise the 2022 bound holds as stated above.\n"
    )
    assert cites.listed_references(text) == {}


def test_a_number_out_of_turn_or_a_text_without_a_list_pairs_nothing():
    assert cites.listed_references("No list here at all.") == {}
    assert cites.listed_references("") == {}
    skipped = (
        "Body.\n\nReferences\n"
        "1. A. Author. First paper title here. In NeurIPS, 2019.\n"
        "7. B. Author. A page number, not a reference, 2020.\n"
    )
    assert cites.listed_references(skipped) == {}


def test_an_undated_or_page_long_entry_is_left_out_rather_than_paired():
    text = (
        "Body.\n\nReferences\n"
        "1. A. Author. First paper title here. In NeurIPS, 2019.\n"
        "2. B. Author. Second paper title here. In ICML, 2020.\n"
        "3. Personal communication with the dataset maintainers.\n"
        "4. C. Author. Fourth paper title here. In ICLR, 2021.\n"
    )
    assert list(cites.listed_references(text)) == ["1", "2", "4"]


def test_the_models_title_replaces_a_citation_string_only_when_printed_in_it():
    known = cites.listed_references(NATURE)["3"]
    exact = "Cataract-1K Dataset for Deep-Learning-Assisted Analysis of Cataract Surgery Videos"
    assert cites.listed_title(known, exact) == exact
    # A description, or a title of some other paper, never displaces the list's entry.
    assert cites.listed_title(known, "從引用句看不出標題") == known["title"]
    assert (
        cites.listed_title(known, "CaDIS: Cataract dataset for image segmentation")
        == (known["title"])
    )
    # A publisher's entry has no citation string and keeps its own title.
    assert cites.listed_title({"title": "Reference 1"}, "Some other title entirely") == (
        "Reference 1"
    )
    assert cites.listed_title({}, "Only the model knows") == "Only the model knows"


def test_analysis_falls_back_to_the_papers_own_list(driver, monkeypatch):
    path, _client, _document, _calls, install, _invoke = driver
    install("citations")
    monkeypatch.setattr(crossref, "reference_list", lambda _: {})
    listed = {
        "1": {
            "title": "A real title of the cited work. Journal 1, 2 (2024).",
            "year": 2024,
            "doi": None,
            "citation": "Doe, J. et al. A real title of the cited work. Journal 1, 2 (2024).",
        }
    }
    monkeypatch.setattr(cites, "listed_references", lambda _text: listed)
    prompts = []

    def complete(prompt, **kwargs):
        prompts.append(prompt)
        answer = answers([1])
        answer[0]["title"] = "A real title of the cited work"
        return json.dumps(answer), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    count, _reason = cites.analyse_result("paper", database=path)
    assert count == 1
    assert "[1] A real title of the cited work. Journal 1, 2 (2024)." in prompts[0]
    saved = rows(path, "SELECT ref_key, title, year FROM cites")
    assert [(r["ref_key"], r["title"], r["year"]) for r in saved] == [
        ("1", "A real title of the cited work", 2024)
    ]
