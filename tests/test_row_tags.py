"""The tag strip under each paper: the sorted-by tag first, the reader's note last,
and a bibliography line that only repeats the title not shown at all."""

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from test_queue_keys import page as _page

from paper_daily.desktop.queue_view import SORT_IDS, note_parts, opened_label

page = _page


def _labels(view, paper):
    return [text for text, _fg, _bg in view.view.itemDelegate()._tags(paper)]


def test_a_citation_line_that_repeats_the_title_is_not_a_note(page):
    _view, win = page
    paper = win.papers[0]
    paper.title = "SASVi - Segment Any Surgical Video"
    paper.reason = "SASVi: Segment Any Surgical Video. Sivakumar SKR, et al. IJCARS 2025."
    assert note_parts(paper) == ([], "")
    paper.reason = "Rare-phase TTA incl. Cataract-101 #dataset-gap"
    assert note_parts(paper) == (["dataset-gap"], "Rare-phase TTA incl. Cataract-101")


def test_the_sorted_by_tag_comes_first_after_the_pin(page):
    view, win = page
    paper = win.papers[0]
    paper.citations, paper.paper_type, paper.pinned = 28, "benchmark", True
    view.sort.setCurrentIndex(SORT_IDS.index("citations"))
    assert _labels(view, paper)[:3] == ["置頂", "28 cites", "MICCAI 2026"]
    view.sort.setCurrentIndex(SORT_IDS.index("type"))
    assert _labels(view, paper)[:3] == ["置頂", "benchmark", "MICCAI 2026"]
    view.sort.setCurrentIndex(SORT_IDS.index("venue"))
    assert _labels(view, paper)[:3] == ["置頂", "MICCAI 2026", "benchmark"]


def test_the_note_goes_last_marked_and_whole_in_the_tooltip(page):
    view, win = page
    paper = win.papers[1]
    paper.reason = "Federated multi-institution learning, relevant to a regional dataset"
    labels = _labels(view, paper)
    assert labels[-1].startswith("理由：Federated") and labels[-1].endswith("…")
    view.refresh()
    row = next(
        r
        for r in range(view.model.rowCount())
        if view.model.index(r).data(Qt.ItemDataRole.UserRole + 1).id == paper.id
    )
    assert paper.reason in view.model.index(row).data(Qt.ItemDataRole.ToolTipRole)


def test_the_recent_sort_says_when_each_paper_was_opened(page):
    view, win = page
    paper = win.papers[2]
    paper.state = "delivered"
    paper.opened_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    view.sort.setCurrentIndex(SORT_IDS.index("recent"))
    labels = _labels(view, paper)
    assert labels[0] == "剛剛開過" and "開過" not in labels[1:]
    view.sort.setCurrentIndex(SORT_IDS.index("venue"))
    assert "剛剛開過" not in _labels(view, paper)


def test_opened_labels_read_naturally_and_ignore_bad_stamps():
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    assert opened_label("2026-10-27T11:30:00+00:00", now) == "30 分鐘前開過"
    assert opened_label("2026-10-27T09:00:00+00:00", now) == "3 小時前開過"
    assert opened_label("2026-10-20T12:00:00+00:00", now) == "7 天前開過"
    assert opened_label("2026-06-01T12:00:00+00:00", now) == "6/1 開過"
    assert opened_label("2026-10-28T12:00:00+00:00", now) is None
    assert opened_label("not a date", now) is None
    assert opened_label("2026-10-27T11:00:00", now) is None
    assert opened_label(None, now) is None
