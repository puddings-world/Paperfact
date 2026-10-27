"""Desktop reader tests.

No QApplication is created: these cover the parts that decide what the reader shows
-- Markdown rendering, row mapping, and the queue filters -- which is where the bugs
have actually been. Widget construction is left to the app itself.
"""

import pytest

pytest.importorskip("PySide6", reason="the desktop reader is an optional extra")

from paper_daily.desktop import md  # noqa: E402
from paper_daily.desktop.ask import build_prompt  # noqa: E402

PALETTE = {
    "ink": "#000000", "muted": "#555555", "faint": "#888888",
    "sunk": "#eeeeee", "border": "#dddddd", "accent": "#2f5bd8",
}


def test_markdown_headings_and_emphasis():
    html = md.to_html("## 核心洞見\n\n這是 **重點** 與 `code`。", PALETTE)
    assert "核心洞見" in html
    assert "<b>重點</b>" in html
    assert "<code" in html


def test_markdown_renders_tables():
    """The deep dives compare baselines in tables; QTextBrowser needs real <table>."""
    src = "| Layer | LDA | PH |\n|---|---|---|\n| 1 | 0.995 | 1.000 |"
    html = md.to_html(src, PALETTE)
    assert html.count("<tr>") == 2
    assert "<th" in html and "0.995" in html


def test_markdown_escapes_html():
    html = md.to_html("a <script>alert(1)</script> b", PALETTE)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_keeps_unicode_maths_intact():
    """The whole formatting convention is Unicode maths, never LaTeX -- the renderer
    must not mangle the symbols on the way through."""
    html = md.to_html("σ = C:ε 且 ∇·σ(u) + f_ext,X ⊂ ℝ^D", PALETTE)
    for symbol in ("σ", "ε", "∇", "⊂", "ℝ"):
        assert symbol in html


def test_markdown_code_fence_is_not_reflowed():
    html = md.to_html("```\nline one\n  line two\n```", PALETTE)
    assert "<pre" in html
    assert "line one\n  line two" in html


def test_build_prompt_carries_paper_and_history():
    prompt = build_prompt(
        "A Title", "ICLR", 2026, "the abstract", "FULL TEXT HERE",
        [("user", "earlier question"), ("assistant", "earlier answer")],
        "what now?",
    )
    assert "A Title" in prompt
    assert "ICLR 2026" in prompt
    assert "FULL TEXT HERE" in prompt
    assert "earlier question" in prompt
    assert prompt.rstrip().endswith("what now?")
    assert "LaTeX" in prompt  # the formatting rule must reach the model


def test_build_prompt_truncates_full_text():
    prompt = build_prompt("T", "ICML", 2025, None, "x" * 200_000, [], "q",
                          text_budget=1000)
    assert len(prompt) < 5000


class _FakePaper:
    """Only the attributes the queue filter reads."""

    def __init__(self, **kw):
        self.title = kw.get("title", "Some Paper")
        self.reason = kw.get("reason")
        self.authors = kw.get("authors", ["Ada Lovelace"])
        self.award = kw.get("award")
        self.paper_type = kw.get("paper_type", "method")
        self.state = kw.get("state", "pending")
        self.has_pdf = kw.get("has_pdf", False)
        self.touched_at = kw.get("touched_at")
        self.read_at = kw.get("read_at")
        self.pinned = kw.get("pinned", False)
        self.arxiv_id = kw.get("arxiv_id")
        self.has_dive = kw.get("has_dive", False)
        self.has_cites = kw.get("has_cites", False)
        self.has_later = kw.get("has_later", False)
        self.has_pdf = kw.get("has_pdf", False)
        self.year = kw.get("year", 2024)
        self.citations = kw.get("citations")
        self.dependents = kw.get("dependents", 0)
        self.venue = kw.get("venue", "ICLR")

    @property
    def read(self):
        return self.state == "read"


class _Filters:
    """Stands in for the checkboxes, so the filter logic can be tested alone."""

    def __init__(self, **flags):
        self.flags = flags

    def __getattr__(self, name):
        checked = self.flags.get(name, False)
        return type("Box", (), {"isChecked": staticmethod(lambda: checked)})()


def _matches(paper, **flags):
    from paper_daily.desktop.queue_view import QueuePage

    stub = _Filters(**flags)
    stub.search = type("E", (), {"text": staticmethod(lambda: flags.get("q", ""))})()
    return QueuePage._matches(stub, paper)


def test_filter_unread_hides_read_papers():
    assert _matches(_FakePaper(state="pending"), f_unread=True)
    assert not _matches(_FakePaper(state="read"), f_unread=True)


def test_filter_history_shows_only_what_was_marked_read():
    """Opening a paper is not reading it: only 已讀, pressed by hand, counts."""
    assert _matches(_FakePaper(state="read"), f_history=True)
    assert not _matches(_FakePaper(state="delivered"), f_history=True)
    assert not _matches(_FakePaper(state="pending"), f_history=True)


def test_filter_award_and_principle():
    oral = _FakePaper(award="oral", paper_type="principle")
    plain = _FakePaper(award=None, paper_type="method")
    assert _matches(oral, f_award=True) and not _matches(plain, f_award=True)
    assert _matches(oral, f_principle=True) and not _matches(plain, f_principle=True)


def test_search_matches_title_or_author():
    p = _FakePaper(title="Persistent Homology of Latent Spaces", authors=["Anthea Monod"])
    assert _matches(p, q="homology")
    assert _matches(p, q="monod")
    assert not _matches(p, q="diffusion")


def test_search_matches_where_it_was_published():
    miccai = _FakePaper(venue="International Conference on Medical Image Computing and "
                              "Computer-Assisted Intervention", year=2025)
    preprint = _FakePaper(venue="arXiv.org", year=2026)
    assert _matches(miccai, q="miccai 2025") and not _matches(preprint, q="miccai")
    assert _matches(preprint, q="預印本") and not _matches(miccai, q="預印本")


def _q(*states):
    """A queue of papers in order, given their states."""
    out = []
    for i, state in enumerate(states):
        paper = _FakePaper(state=state, title=f"paper {i}")
        paper.id = f"p{i}"
        out.append(paper)
    return out


def test_next_after_advances_past_the_open_paper():
    """The button is labelled 下一篇, so it must move.

    Opening a paper marks it delivered, not read, so "first not-read paper" kept
    selecting whatever was already on screen and the button looked dead.
    """
    from paper_daily.desktop.main import next_after

    papers = _q("read", "read", "delivered", "pending", "pending")
    assert next_after(papers, "p2").id == "p3"
    assert next_after(papers, "p3").id == "p4"


def test_next_after_with_nothing_open_takes_the_first_unread():
    from paper_daily.desktop.main import next_after

    papers = _q("read", "delivered", "pending")
    assert next_after(papers, None).id == "p1"


def test_next_after_wraps_when_past_the_end():
    """A promoted lineage paper sits above the current position, not below it."""
    from paper_daily.desktop.main import next_after

    papers = _q("pending", "read", "delivered")
    assert next_after(papers, "p2").id == "p0"


def test_next_after_returns_none_when_everything_is_read():
    from paper_daily.desktop.main import next_after

    papers = _q("read", "read")
    assert next_after(papers, "p0") is None
    assert next_after(papers, None) is None


class _FakeRow(dict):
    """sqlite3.Row-like access for the columns pdf_candidates reads."""

    def __getitem__(self, key):
        return self.get(key)


def test_pdf_candidates_prefers_proceedings_then_arxiv():
    from paper_daily.fetch import pdf_candidates

    both = _FakeRow(pdf_url="https://proceedings.mlr.press/x.pdf", arxiv_id="2009.14794")
    assert pdf_candidates(both) == [
        "https://proceedings.mlr.press/x.pdf",
        "https://arxiv.org/pdf/2009.14794",
    ]


def test_pdf_candidates_prefers_arxiv_to_a_publisher_copy():
    """A journal's link can be the watermarked accepted manuscript."""
    from paper_daily.fetch import pdf_candidates

    journal = _FakeRow(pdf_url="https://www.nature.com/articles/x_reference.pdf",
                       arxiv_id="2510.16371")
    assert pdf_candidates(journal) == [
        "https://arxiv.org/pdf/2510.16371",
        "https://www.nature.com/articles/x_reference.pdf",
    ]


def test_pdf_candidates_falls_back_to_arxiv_alone():
    """ICLR papers have no open proceedings PDF, so arXiv is the only route."""
    from paper_daily.fetch import pdf_candidates

    assert pdf_candidates(_FakeRow(pdf_url=None, arxiv_id="2009.14794")) == [
        "https://arxiv.org/pdf/2009.14794"
    ]


def test_pdf_candidates_empty_when_nothing_is_reachable():
    from paper_daily.fetch import pdf_candidates

    assert pdf_candidates(_FakeRow(pdf_url=None, arxiv_id=None)) == []


def _sorted(label, papers):
    """Apply one of the queue screen's sort options, as refresh() does."""
    from paper_daily.desktop.queue_view import SORTS

    _id, _name, key, reverse = next(s for s in SORTS if s[1] == label)
    rows = list(enumerate(papers, 1))
    rows.sort(key=lambda pair: key(pair[1]), reverse=reverse)
    return rows


def test_sort_by_citations_puts_the_most_cited_first():
    papers = [
        _FakePaper(title="few", citations=3),
        _FakePaper(title="many", citations=900),
        _FakePaper(title="none", citations=None),
    ]
    assert [p.title for _i, p in _sorted("引用數 多 → 少", papers)] == ["many", "few", "none"]


def test_a_kept_answer_is_headed_by_its_question():
    from paper_daily.desktop.main import note_headline

    body = "> 這兩種標註差在哪 關於這段原文: Frames were annotated\n\n## 1. 答案\n| a | b |"
    assert note_headline(body, "ask") == (
        "這兩種標註差在哪", "Frames were annotated", "## 1. 答案\n| a | b |"
    )
    assert note_headline("> a passage\n\n# 我的結論\n細節", "note")[:2] == ("我的結論", "a passage")


def test_questions_pair_with_their_answers():
    from paper_daily.desktop.main import _exchanges

    rows = [{"role": "user", "id": 1}, {"role": "assistant", "id": 2}, {"role": "user", "id": 3}]
    assert [(q and q["id"], a and a["id"]) for q, a in _exchanges(rows)] == [(1, 2), (3, None)]


def test_sort_by_year_runs_both_ways():
    papers = [_FakePaper(title=str(y), year=y) for y in (2019, 2026, 2004)]
    assert [p.title for _i, p in _sorted("時間 新 → 舊", papers)] == ["2026", "2019", "2004"]
    assert [p.title for _i, p in _sorted("時間 舊 → 新", papers)] == ["2004", "2019", "2026"]


def test_time_order_within_a_year_comes_from_the_arxiv_month():
    papers = [
        _FakePaper(title="march", year=2026, arxiv_id="2603.21566"),
        _FakePaper(title="august", year=2026, arxiv_id="2608.17522"),
        # A 2024 preprint published in 2026 says nothing about the 2026 month.
        _FakePaper(title="old-preprint", year=2026, arxiv_id="2411.15421"),
    ]
    order = [p.title for _i, p in _sorted("時間 新 → 舊", papers)]
    assert order == ["august", "march", "old-preprint"]


def test_grouping_by_venue_puts_miccai_first_and_preprints_last():
    papers = [
        _FakePaper(title="pre", venue="arXiv.org", year=2026),
        _FakePaper(title="tmi", venue="IEEE Transactions on Medical Imaging", year=2025),
        _FakePaper(title="miccai-old", venue="MICCAI 2023", year=2023),
        _FakePaper(title="miccai-new", venue="MICCAI 2026", year=2026),
    ]
    order = [p.title for _i, p in _sorted("依發表處分組", papers)]
    assert order == ["miccai-new", "miccai-old", "tmi", "pre"]


def test_unanalysed_papers_can_be_brought_forward():
    papers = [
        _FakePaper(title="done", has_dive=True, has_cites=True, has_later=True, has_pdf=True),
        _FakePaper(title="none"),
        _FakePaper(title="half", has_dive=True, has_pdf=True),
    ]
    assert [p.title for _i, p in _sorted("待分析的在前", papers)] == ["none", "half", "done"]


def test_sorting_keeps_each_paper_position():
    """The number on the row is where the paper sits in the queue or the list.

    Sorting is a way to look at that order, not to renumber it, so the positions must
    travel with the papers rather than being reassigned.
    """
    papers = [
        _FakePaper(title="first", citations=1),
        _FakePaper(title="second", citations=50),
    ]
    assert _sorted("引用數 多 → 少", papers) == [(2, papers[1]), (1, papers[0])]


def test_sort_by_recency_is_newest_first_and_never_read_last():
    papers = [
        _FakePaper(title="old", read_at="2026-01-01T00:00:00Z"),
        _FakePaper(title="never", read_at=None),
        # Opened yesterday but never marked read: not reading.
        _FakePaper(title="opened", touched_at="2026-10-07T00:00:00Z"),
        _FakePaper(title="recent", read_at="2026-09-20T00:00:00Z"),
    ]
    order = [p.title for _i, p in _sorted("最近標記已讀", papers)]
    assert order[:2] == ["recent", "old"]
    assert set(order[2:]) == {"never", "opened"}


def test_pinned_papers_stay_on_top_in_the_chosen_order():
    from paper_daily.desktop.queue_view import QueuePage

    papers = [
        _FakePaper(title="a", citations=5),
        _FakePaper(title="b", citations=50, pinned=True),
        _FakePaper(title="c", citations=500),
        _FakePaper(title="d", citations=1, pinned=True),
    ]
    rows = QueuePage._pinned_first(_sorted("引用數 多 → 少", papers))
    assert [p.title for _i, p in rows] == ["b", "d", "c", "a"]


def test_note_quote_is_split_from_what_you_wrote():
    """A note written against a passage keeps the passage on leading "> " lines."""
    from paper_daily.desktop.main import _split_quote

    quote, body = _split_quote("> The dataset contains 1000 videos\n\n要確認 56 支都在裡面")
    assert quote == "The dataset contains 1000 videos"
    assert body == "要確認 56 支都在裡面"

    assert _split_quote("just a thought") == ("", "just a thought")
    assert _split_quote("> a\n> b\n\nnote") == ("a b", "note")


def test_selected_words_join_across_lines_and_repair_hyphens():
    """A passage dragged across a line break is one sentence, not two fragments."""
    from paper_daily.desktop.pdfselect import SelectionOverlay, Word

    overlay = SelectionOverlay.__new__(SelectionOverlay)
    overlay._selected = [
        Word(0, 0, 100, 10, 110, "the", 0),
        Word(0, 12, 100, 30, 110, "visu-", 1),
        Word(0, 0, 120, 20, 130, "ally", 2),
        Word(0, 22, 120, 40, 130, "distinct", 3),
    ]
    assert overlay.selected_text() == "the visually distinct"


def test_a_drag_starts_on_the_word_under_the_pointer():
    """Grabbing the first letter of a long word must not start on the short word before it."""
    from paper_daily.desktop.pdfselect import SelectionOverlay, Word

    overlay = SelectionOverlay.__new__(SelectionOverlay)
    line = [
        Word(0, 0, 100, 10, 110, "a", 0),
        Word(0, 14, 100, 90, 110, "segmentation", 1),
        Word(0, 94, 100, 120, 110, "mask", 2),
    ]
    # Second column, above the end of the first in page coordinates.
    right = [Word(0, 300, 50, 340, 60, "later", 3)]
    overlay._words = {0: line + right}

    assert overlay._nearest(0, 15, 105).text == "segmentation"
    # Dragged backwards, or ending higher on the page in the next column: still in
    # reading order, from the first word found to the last.
    assert [w.text for w in overlay._between((0, 100, 105), (0, 15, 105))] == [
        "segmentation", "mask",
    ]
    assert [w.text for w in overlay._between((0, 15, 105), (0, 310, 55))] == [
        "segmentation", "mask", "later",
    ]


def test_find_in_the_paper_spans_lines_and_matches_inside_words():
    from paper_daily.desktop.pdfselect import SelectionOverlay, Word

    class Doc:
        page_count = 2

    overlay = SelectionOverlay.__new__(SelectionOverlay)
    overlay._doc = Doc()
    overlay._words = {
        0: [Word(0, 0, 0, 1, 1, "instrument", 0), Word(0, 0, 2, 1, 3, "segmentation", 1),
            Word(0, 0, 4, 1, 5, "and", 2)],
        1: [Word(1, 0, 0, 1, 1, "Phase", 0), Word(1, 0, 2, 1, 3, "segmentation.", 1)],
    }
    assert overlay.search("instrument  Segmentation") == [
        {"p0": 0, "o0": 0, "p1": 0, "o1": 1},
    ]
    assert [h["p0"] for h in overlay.search("segment")] == [0, 1]
    assert overlay.search("nowhere") == []


def test_a_watermark_set_at_an_angle_is_not_selectable_text():
    """A preprint's diagonal "ARTICLE IN PRESS" sat over the text and first in order."""
    pymupdf = pytest.importorskip("pymupdf")
    from paper_daily.desktop.pdfselect import _level_words

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((200, 400), "ARTICLE IN PRESS", fontsize=40, rotate=90)
    page.insert_text((72, 100), "phase recognition works")
    kept = _level_words(page)
    assert [w[4] for _i, w in kept] == ["phase", "recognition", "works"]
    # Indices count the words skipped, so anchors written before stay valid.
    assert [i for i, _w in kept] == [3, 4, 5]
