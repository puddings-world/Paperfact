"""Real built-in CJK fonts retain exact quotes and real mixed-language separators."""

import pymupdf
from test_research_evidence import first, proposal
from test_research_evidence import source as _source

from paper_daily import research_evidence as evidence

source = _source
CHINESE = "\u81e8\u5e8a\u7814\u7a76\u986f\u793a\u6cbb\u7642\u6548\u679c\u6709\u9650\u3002"
MIXED = "\u7814\u7a76 AI + B = 3 \u7d50\u679c"


def cjk_source(source, *, repeat=False, visible_gap=False):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        if visible_gap:
            for index, char in enumerate(CHINESE):
                page.insert_text((40 + index * 26, 50), char, fontname="china-s", fontsize=12)
        else:
            page.insert_text((40, 50), CHINESE, fontname="china-s", fontsize=12)
        page.insert_text((40, 100), MIXED, fontname="china-s", fontsize=12)
        if repeat:
            pdf.new_page().insert_text((40, 50), CHINESE, fontname="china-s", fontsize=12)
        data = pdf.tobytes()
    source.path.write_bytes(data)
    return source._owner.resolve("paper")


def test_cjk_original_quote_is_located_from_actual_font_extraction(source):
    document = cjk_source(source)
    result = evidence.verify(document, proposal(document, CHINESE))
    assert first(result)["location"]["state"] == "located"
    assert first(result)["location"]["anchor"] == {"p0": 0, "o0": 0, "p1": 0, "o1": 0}


def test_mixed_cjk_latin_math_preserves_real_separators_and_lexical_boundaries(source):
    document = cjk_source(source)
    assert (
        first(evidence.verify(document, proposal(document, MIXED)))["location"]["state"]
        == "located"
    )
    compact = MIXED.replace(" ", "")
    assert (
        first(evidence.verify(document, proposal(document, compact)))["location"]["state"]
        == "missing"
    )
    assert (
        first(evidence.verify(document, proposal(document, "A + B = 3")))["location"]["state"]
        == "missing"
    )


def test_cjk_ambiguous_or_visibly_separated_glyphs_are_never_approximately_joined(source):
    document = cjk_source(source, repeat=True)
    location = first(evidence.verify(document, proposal(document, CHINESE)))["location"]
    assert location["state"] == "ambiguous" and location["anchor"] is None
    assert len(location["candidates"]) == 2
    document = cjk_source(document, visible_gap=True)
    assert (
        first(evidence.verify(document, proposal(document, CHINESE)))["location"]["state"]
        == "missing"
    )
