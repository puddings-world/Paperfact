"""Parser tests against fixtures captured from the real sites.

These markup shapes are the project's main fragility: every one of them was wrong on
the first attempt against the live pages, so they are pinned here.
"""

from paper_daily.sources import neurips, pmlr, virtual_site

PMLR_VOLUME = """
<div class="paper">
  <p class="title">Revisiting Character-level Adversarial Attacks</p>
  <p class="details">
    <span class="authors">Elias Abad Rocamora,&nbsp;Yongtao Wu,&nbsp;Volkan Cevher</span>;
    <span class="info"><i>Proceedings of the 41st ICML</i>, PMLR 235:1-30</span>
  </p>
  <p class="links">
    [<a href="https://proceedings.mlr.press/v235/abad-rocamora24a.html">abs</a>]
    [<a href="https://raw.githubusercontent.com/mlresearch/v235/main/assets/x/x.pdf">Download PDF</a>]
  </p>
</div>
"""

PMLR_INDEX = """
<ul class="proceedings-list">
  <li><a href="v267"><b>Volume 267</b></a> Proceedings of ICML 2025</li>
  <li><a href="v251"><b>Volume 251</b></a> Proceedings of GRaM at ICML 2024</li>
  <li><a href="v235"><b>Volume 235</b></a> Proceedings of ICML 2024</li>
  <li><a href="v37"><b>Volume 37</b></a> ICML 2015 Proceedings</li>
</ul>
"""

NEURIPS_INDEX = """
<ul class="paper-list">
  <li class="" data-track="none">
    <div class="paper-content">
      <a title="paper title" href="/paper_files/paper/2023/hash/abc123-Abstract-Conference.html">MicroAdam</a>
      <span class="paper-authors">Ionut Modoranu, Mher Safaryan</span>
    </div>
  </li>
</ul>
"""

VIRTUAL_PAPERS = """
<a href="/virtual/2026/poster/10006831">Escaping Policy Contraction</a>
<a href="/virtual/2026/poster/10006831">View full details</a>
<a href="/virtual/2026/poster/10006832">Another Paper</a>
"""

VIRTUAL_ORAL = """
<span class="event-type-badge">Oral</span>
<h3 class="event-title"><a href="/virtual/2024/oral/35513">MorphGrower: A Growing Approach</a></h3>
<h3 class="event-title"><a href="/virtual/2024/oral/35513">View full details</a></h3>
"""

VIRTUAL_POSTER = """
<script type="application/ld+json">
{ "@type": "CreativeWork", "name": "Escaping Policy Contraction",
  "author": [{"@type":"Person","name":"Dun Yuan"},{"@type":"Person","name":"Di Wu"}] }
</script>
<meta name="keywords" content="Reinforcement Learning:Deep RL">
<div class="abstract-text collapsed">Reinforcement learning from human feedback with PPO is widely used but yields less diverse outputs.</div>
"""


def test_pmlr_volume_parsing(monkeypatch):
    monkeypatch.setattr(pmlr, "fetch_text", lambda *a, **k: PMLR_VOLUME)
    monkeypatch.setattr(pmlr, "volume_for_year", lambda y: "v235")
    rows = pmlr.crawl_year(2024)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "ICML:2024:abad-rocamora24a"
    assert row["title"].startswith("Revisiting Character-level")
    assert "Volkan Cevher" in row["authors_json"]
    assert row["pdf_url"].endswith(".pdf")
    assert row["page_url"].endswith("abad-rocamora24a.html")


def test_pmlr_discovery_excludes_workshops(monkeypatch):
    monkeypatch.setattr(pmlr, "fetch_text", lambda *a, **k: PMLR_INDEX)
    vols = pmlr.discover_volumes()
    assert vols[2025] == "v267"
    assert vols[2024] == "v235"  # not v251, the co-located GRaM workshop
    assert vols[2015] == "v37"


def test_neurips_pdf_url_follows_abstract_suffix(monkeypatch):
    monkeypatch.setattr(neurips, "fetch_text", lambda *a, **k: NEURIPS_INDEX)
    rows = neurips.crawl_year(2023)
    assert len(rows) == 1
    # The suffix changed in 2023; the PDF name must mirror the abstract name.
    assert rows[0]["pdf_url"].endswith("abc123-Paper-Conference.pdf")
    assert rows[0]["authors_json"].count('"') == 4


def test_virtual_roster_dedupes_and_drops_boilerplate(monkeypatch):
    monkeypatch.setattr(virtual_site, "fetch_text", lambda *a, **k: VIRTUAL_PAPERS)
    rows = virtual_site.fetch_roster("ICLR", 2026)
    titles = [r["title"] for r in rows]
    assert titles == ["Escaping Policy Contraction", "Another Paper"]
    assert "View full details" not in titles


def test_virtual_awards(monkeypatch):
    monkeypatch.setattr(virtual_site, "fetch_text", lambda *a, **k: VIRTUAL_ORAL)
    awards = virtual_site.fetch_awards("ICML", 2024)
    assert set(awards.values()) == {"oral"}
    assert len(awards) == 1


def test_virtual_paper_detail(monkeypatch):
    monkeypatch.setattr(virtual_site, "fetch_text", lambda *a, **k: VIRTUAL_POSTER)
    d = virtual_site.fetch_paper_detail("https://iclr.cc/virtual/2026/poster/1")
    assert d["authors"] == ["Dun Yuan", "Di Wu"]
    assert d["keywords"] == "Reinforcement Learning:Deep RL"
    assert d["abstract"].startswith("Reinforcement learning from human feedback")


def test_caption_pattern_accepts_the_nature_style_and_refuses_prose():
    """Nature writes "Fig. 1  Caption" with no colon at all.

    Requiring the colon kept only the tables out of a Nature paper. Accepting the
    bare form needs a case-sensitive lookahead: under re.I, "Fig. 2 sample frames
    are drawn from" reads as a caption too.
    """
    from paper_daily.figures import CAPTION_RE

    assert CAPTION_RE.match("Figure 1: An overview of the construction process")
    assert CAPTION_RE.match("Fig. 1  Total duration of the annotated phases")
    assert CAPTION_RE.match("Table 1 Results of models on MMMU-Pro")
    assert not CAPTION_RE.match("Figure 1 shows the ratio diverging around layer 12")
    assert not CAPTION_RE.match("Fig. 2 sample frames are drawn from")
    assert not CAPTION_RE.match("Table 3 of the appendix lists every run")


def test_citation_contexts_handle_the_three_styles():
    from paper_daily.cites import contexts

    text = (
        "Introduction\n"
        "Context-aware systems advance pre-operative surgical planning1-3 and automate "
        "skill assessment4,5 across the operating room.\n"
        "The segmentation baseline we compare against is DeepLab [12], while the data "
        "split follows [15, 16].\n"
        "The phase taxonomy is taken from (Ghamsarian et al., 2023), which we extend.\n"
    )
    got = contexts(text)
    assert set(["1", "2", "3", "4", "5"]).issubset(got)
    assert "12" in got and "15" in got and "16" in got
    assert "Ghamsarian et al., 2023" in got
    assert "surgical planning" in got["1"][0]
    assert "DeepLab" in got["12"][0]


def test_citation_contexts_ignore_author_affiliations_and_page_furniture():
    """Affiliation markers are superscript digits on names, and the running header
    carries the volume number -- both looked exactly like references."""
    from paper_daily.cites import contexts

    text = (
        "Cataract-1K Dataset for Deep-Learning-Assisted Analysis\n"
        "Negin Ghamsarian1, Yosuf El-Shabrawi2, Sahar Nasirihaghighi3\n"
        "Scientific Data | (2024) 11:373 | https://doi.org/10.1038/s41597-024-03193-4\n"
        "Introduction\n"
        "Deep learning reshaped surgical video analysis in recent years7, and the "
        "field has grown quickly since then.\n"
    )
    got = contexts(text)
    assert "7" in got
    assert "1" not in got and "2" not in got and "373" not in got


def test_citation_contexts_ignore_model_names_that_end_in_digits():
    """"ResNet50" and "Slow R50" end in digits exactly like a superscript citation."""
    from paper_daily.cites import contexts

    text = (
        "Introduction\n"
        "We evaluate Slow R50 and ResNet50 against the published numbers, and both "
        "reach the accuracy reported for this task.\n"
        "The taxonomy itself is taken from earlier work7, which we follow closely.\n"
    )
    got = contexts(text)
    assert "7" in got
    assert "50" not in got


def test_citation_numbers_above_the_reference_count_are_dropped():
    from paper_daily.cites import contexts

    text = (
        "Introduction\n"
        "The reported accuracy of the earlier system12 was never reproduced, and the "
        "follow-up study98 is unrelated extraction noise.\n"
    )
    got = contexts(text, highest=40)
    assert "12" in got and "98" not in got


def test_citations_at_the_end_of_a_sentence_are_not_lost():
    """The position a citation most often sits in. The lookahead that kept decimals
    out was also keeping out the full stop, so every sentence-final reference was
    dropped and every sentence-final range truncated to its first number."""
    from paper_daily.cites import contexts

    text = (
        "Introduction\n"
        "We evaluate cross-dataset instrument segmentation under domain shifts32.\n"
        "Context-aware systems already automate skill assessment4-8.\n"
        "Accuracy improves from 3.5 to 4.1 points, a gain of 12% over the baseline.\n"
    )
    got = contexts(text)
    assert "32" in got
    assert {"4", "5", "6", "7", "8"}.issubset(got)
    assert "5" in got and "1" not in got  # "3.5" and "4.1" are numbers, not references
    assert "12" not in got


def test_citation_numbers_are_normalised_and_zero_is_not_a_reference():
    """A page that prints "001" and one that prints "1" mean the same reference."""
    from paper_daily.cites import contexts

    text = (
        "Introduction\n"
        "The earliest treatment of the problem001 set the framing used ever since.\n"
        "A later survey1 revisited it with a much larger corpus of recordings.\n"
    )
    got = contexts(text)
    assert "1" in got and "001" not in got and "0" not in got
    assert len(got["1"]) == 2


def test_references_without_a_citing_sentence_still_reach_the_model():
    """The whole point of the two tiers: a reference the text never resolved is
    exactly the one you cannot otherwise judge."""
    from paper_daily.cites import _pack

    row = {"title": "A Paper", "venue": "Scientific Data", "year": 2024, "abstract": "x"}
    numbered = {
        "1": {"title": "Cited With A Sentence", "year": 2021, "doi": "10.1/a"},
        "2": {"title": "Listed But Never Resolved", "year": 2019, "doi": "10.1/b"},
    }
    packed = _pack(row, [], {"1": ["We build on the earlier system1."]}, numbered)
    assert "A 區" in packed and "B 區" in packed
    assert "[1] Cited With A Sentence" in packed
    assert "[2] Listed But Never Resolved (2019)" in packed
    # With the publisher's numbering there is nothing for the model to guess.
    assert "Semantic Scholar" not in packed
