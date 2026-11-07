"""Open explanation reports on human-reviewed scenarios, with full inventory available."""

import runpy
from html.parser import HTMLParser
from pathlib import Path

import pytest
from test_test_report import sample as sample

REPORT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/test_report.py"))


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_report_starts_with_readable_scenarios_and_keeps_unexplained_inventory_available(
    sample, language
):
    root, _source, catalog, inventory = sample
    result = REPORT["render"](REPORT["build_model"](root, catalog, inventory), language)

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.toggle, self.articles = None, []

        def handle_starttag(self, tag, attributes):
            fields = dict(attributes)
            if tag == "input" and fields.get("id") == "reviewed":
                self.toggle = fields
            if tag == "article":
                self.articles.append(fields)

    page = Elements()
    page.feed(result)
    assert page.toggle is not None and page.toggle["type"] == "checkbox"
    assert "checked" in page.toggle
    assert [item["data-reviewed"] for item in page.articles] == ["yes", "no"]
    assert "test_undocumented" in page.articles[1]["data-search"]
    assert "Repeated checks keep the newest request" in result
    assert "Only the newest scope applies." in result
    assert "No real model requests or scientific quality are tested." in result
