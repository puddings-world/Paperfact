"""The reading views' Markdown: formulas left for KaTeX, algorithms numbered,
diagrams handed to Mermaid, code labelled by language, and older box diagrams kept
in their columns."""

import pytest

pytest.importorskip("markdown_it")

from paper_daily.desktop import rich_html  # noqa: E402
from paper_daily.desktop.main import DARK, LIGHT  # noqa: E402


def test_formulas_become_katex_spans_and_prices_stay_prose():
    out = rich_html.markdown("Loss $L_t = a_t^2$ costs $5 and $10.\n\n$$\n\\sum_t x_t\n$$")
    assert '<span class="math inline">L_t = a_t^2</span>' in out
    assert "$5 and $10" in out
    assert '<div class="math block">' in out and "\\sum_t x_t" in out
    # The underscores were not read as emphasis.
    assert "<em>" not in out


def test_a_pseudocode_block_is_a_titled_numbered_algorithm():
    out = rich_html.markdown(
        "```pseudocode Algorithm 1 · CIP-MPC\n"
        "for t in 1..T do\n  u ← argmax C  // plan\nend for\n```"
    )
    assert '<figure class="algo"><figcaption>Algorithm 1 · CIP-MPC</figcaption>' in out
    assert out.count('<span class="ln">') == 3
    assert '<b class="kw">for</b>' in out and '<span class="cm">// plan</span>' in out


def test_mermaid_and_code_blocks_are_marked_for_their_renderers():
    out = rich_html.markdown("```mermaid\nflowchart LR\nA-->B\n```\n\n```python\nx = 1 < 2\n```")
    assert '<pre class="mermaid">flowchart LR\nA--&gt;B</pre>' in out
    assert '<code class="language-python">x = 1 &lt; 2</code>' in out


def test_an_unlabelled_block_pins_wide_characters_to_two_columns():
    out = rich_html.markdown("```\n│ 係數 │\n```")
    assert out.count('class="c2"') == 2 and out.count('class="c1"') == 2


def test_model_html_is_escaped_not_run():
    assert "<script>" not in rich_html.markdown("<script>alert(1)</script>")


def test_the_page_follows_the_theme_and_loads_only_local_assets():
    light = rich_html.page("<p>x</p>", LIGHT)
    dark = rich_html.page("<p>x</p>", DARK)
    assert "hljs-light.css" in light and "hljs-dark.css" in dark
    assert "color-scheme: dark" in dark
    assert "http://" not in light and "https://" not in light


def test_a_display_formula_written_under_a_sentence_is_still_displayed():
    out = rich_html.markdown("所以\n$$\np^* = q\n$$\n接著")
    assert '<div class="math block">' in out and "<p>接著</p>" in out
