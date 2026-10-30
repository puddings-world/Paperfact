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

