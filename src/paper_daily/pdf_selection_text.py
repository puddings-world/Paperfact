"""Pure indexed PDF word stream shared by selection and observed annotations."""

def level_words(page) -> list[tuple[int, tuple]]:
    """PyMuPDF's words with their index, without any set at an angle.

    A preprint stamped "ARTICLE IN PRESS" diagonally across every page gives three
    words whose boxes are a hundred points square, in the middle of the text and
    first in reading order. A drag starting anywhere over them started at the top of
    the page. Rotated axis labels in figures do the same on a smaller scale.
    """
    tp = page.get_textpage()
    slanted = {
        (b["number"], n)
        for b in page.get_text("dict", textpage=tp)["blocks"]
        for n, line in enumerate(b.get("lines", ()))
        if abs(line["dir"][1]) > 0.05
    }
    words = page.get_text("words", textpage=tp)
    return [(i, w) for i, w in enumerate(words) if (w[5], w[6]) not in slanted]


def validate_range(document, anchor):
    """Validate actual selectable word endpoints, never character offsets.

    This establishes location only, not semantic support for a note or claim.
    At most the two endpoint pages are extracted, even for a long selection.
    """
    from paper_daily.sync_content import validate_anchor

    validate_anchor(anchor)
    if anchor is None:
        raise ValueError("A source selection anchor is required")
    if anchor["p1"] >= len(document):
        raise ValueError("Selection page range is outside its original PDF")
    pages = {}
    for page, order in ((anchor["p0"], anchor["o0"]), (anchor["p1"], anchor["o1"])):
        if page not in pages:
            pages[page] = {index for index, _word in level_words(document[page])}
        if order not in pages[page]:
            raise ValueError("Selection word anchor is outside its original PDF")
