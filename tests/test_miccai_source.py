"""MICCAI paper pages: the PDF hunt reads them, and the reader can ask for the hunt.

The page below keeps the structure of papers.miccai.org/miccai-2026/0467-Paper4826.html
as fetched on 2026-11-09 (sections, anchors, the author meta tag), with the prose
shortened. The title searches through Semantic Scholar, OpenAlex and arXiv found no
PDF for that paper; its page linked one.
"""

import json
import threading

import pytest
from PySide6.QtCore import Qt
from test_managed_reader_ui import wait_for, workspace  # noqa: F401 - fixture

from paper_daily import pdf_sources, resolve
from paper_daily.desktop.pdf_hunt import FIND_PDF, hunt_message, no_pdf_message
from paper_daily.http import FetchError
from paper_daily.pdf_downloads import DownloadQueue, State
from paper_daily.sources import miccai

PAGE_URL = "https://papers.miccai.org/miccai-2026/0467-Paper4826.html"
PDF_URL = "https://papers.miccai.org/miccai-2026/paper/4826_paper.pdf"
PAGE = """<!DOCTYPE html><html><head>
<title>Hi-FL | MICCAI 2026 - Open Access</title>
<meta name="author" content="Alekseenko, Julia AND Quero, Giuseppe AND Padoy, Nicolas" />
</head><body>
<h1><span><b>Hi-FL: Hierarchical Federated Learning</b></span></h1>
<h2>Author(s): </h2><a href="/miccai-2026/tags#Alekseenko, Julia">Alekseenko, Julia</a>
    <h1 id="abstract-id">Abstract</h1>
<p>Automated surgical phase recognition is &amp; hard.</p>

<p>We propose Hi-FL.
<br /><br /></p>

<h1 id="link-id">Links to Paper and Supplementary Materials</h1>
<p>Main Paper (Open Access Version): <a
href="https://papers.miccai.org/miccai-2026/paper/4826_paper.pdf" target="_blank">
https://papers.miccai.org/miccai-2026/paper/4826_paper.pdf</a></p>

<p>SharedIt Link: Not yet available</p>

<p>SpringerLink (DOI): Not yet available</p>

<h1 id="code-id">Link to the Code Repository</h1>
<p><a href="https://github.com/CAMMA-public/Hi-FL">https://github.com/CAMMA-public/Hi-FL</a>
<br /><br /></p>

<h1 id="dataset-id">Link to the Dataset(s)</h1>
<p>N/A</p>
<h1 id="review-id">Reviews</h1>
<p>See <a href="https://example.org/other.pdf">a reviewer's file</a>.</p>
</body></html>"""


def test_a_miccai_page_gives_its_pdf_abstract_authors_and_code():
    found = miccai.parse(PAGE, PAGE_URL)
    assert found["pdf_url"] == PDF_URL
    assert found["code_url"] == "https://github.com/CAMMA-public/Hi-FL"
    assert found["doi"] is None
    assert (
        found["abstract"] == "Automated surgical phase recognition is & hard.\n\nWe propose Hi-FL."
    )
    assert found["authors"] == ["Julia Alekseenko", "Giuseppe Quero", "Nicolas Padoy"]


def test_a_page_without_a_paper_link_gives_no_pdf_rather_than_another_link():
    bare = PAGE.split('<h1 id="link-id">')[0] + "</body></html>"
    assert miccai.parse(bare, PAGE_URL)["pdf_url"] is None


def test_only_miccai_paper_pages_are_recognised():
    assert miccai.is_page(PAGE_URL)
    assert not miccai.is_page("https://papers.miccai.org/miccai-2026/")
    assert not miccai.is_page("https://example.org/miccai-2026/0467-Paper4826.html")
    assert not miccai.is_page(None)


def test_discovery_reads_the_linked_miccai_page_before_any_title_search(monkeypatch):
    asked = []

    def fetch(url, **kwargs):
        asked.append((url, kwargs))
        return PAGE.encode()

    monkeypatch.setattr(pdf_sources, "fetch", fetch)
    found = pdf_sources.discover(dict(title="Hi-FL", page_url=PAGE_URL))
    assert next(found) == PDF_URL
    assert asked == [(PAGE_URL, dict(retries=1, timeout=12, max_age=86400))]


def test_an_unreachable_miccai_page_still_lets_the_title_searches_run(monkeypatch):
    asked = []

    def fetch(url, **kwargs):
        asked.append(url)
        if url == PAGE_URL:
            raise FetchError("busy")
        return (
            b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
            if "arxiv" in url
            else (json.dumps(dict(data=[], results=[])).encode())
        )

    monkeypatch.setattr(pdf_sources, "fetch", fetch)
    with pytest.raises(FetchError):
        list(pdf_sources.discover(dict(title="Hi-FL", page_url=PAGE_URL)))
    assert asked[0] == PAGE_URL and len(asked) == 4


def test_filling_gaps_takes_the_miccai_pdf_and_keeps_what_the_row_already_has(monkeypatch):
    monkeypatch.setattr(resolve, "fetch_text", lambda url, **_: PAGE)
    for module, name in (
        (resolve.cvf, "pdf_url"),
        (resolve.arxiv, "match_title"),
        (resolve.openalex, "match_title"),
    ):
        monkeypatch.setattr(
            module,
            name,
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("the publisher's page already answered")
            ),
        )
    row, found = resolve.fill_gaps(
        dict(
            title="Hi-FL",
            venue="MICCAI 2026",
            year=2026,
            page_url=PAGE_URL,
            abstract="Curated abstract",
            authors_json="[]",
        )
    )
    assert found == ["miccai"]
    assert row["pdf_url"] == PDF_URL
    assert row["abstract"] == "Curated abstract"
    assert json.loads(row["authors_json"]) == [
        "Julia Alekseenko",
        "Giuseppe Quero",
        "Nicolas Padoy",
    ]


def test_reader_messages_offer_the_lookup_and_a_retry_after_failure():
    assert f'href="{FIND_PDF}"' in no_pdf_message("#123")
    failed = hunt_message(State("error", message="<b>none</b>"), "#123")
    assert f'href="{FIND_PDF}"' in failed and "&lt;b&gt;" in failed
    assert FIND_PDF not in hunt_message(State("resolving"), "#123")


def test_reader_title_can_be_selected_and_the_lookup_runs_from_the_reader(workspace):  # noqa: F811
    w = workspace
    selectable = Qt.TextInteractionFlag.TextSelectableByMouse
    assert w.widget.title.textInteractionFlags() & selectable
    assert w.widget.byline.textInteractionFlags() & selectable
    assert w.widget.facts.textInteractionFlags() & selectable

    release = threading.Event()
    downloads = []

    def worker(paper_id, progress, cancel):
        downloads.append(paper_id)
        progress("resolving", 0, None, "")
        release.wait(5)
        return "fixture.pdf"

    w.widget.win.pdf_downloads = DownloadQueue(worker=worker)
    arrived = []
    w.widget._pdf_arrived = lambda paper_id, ok: arrived.append((paper_id, ok))
    w.widget._pdf_missing_link(FIND_PDF)
    wait_for(w.app, lambda: "尋找原文來源" in w.widget.pdf_missing.text())
    assert w.widget.pdf_note.text() == "查找中"
    release.set()
    wait_for(w.app, lambda: arrived)
    assert arrived == [(w.widget.paper.id, True)] and downloads == [w.widget.paper.id]
    assert not w.widget._pdf_hunt_poll.isActive()


def test_a_failed_lookup_in_the_reader_offers_to_look_again(workspace):  # noqa: F811
    w = workspace

    def worker(paper_id, progress, cancel):
        raise FetchError("尚未找到可下載的開放 PDF")

    w.widget.win.pdf_downloads = DownloadQueue(worker=worker)
    w.widget._find_pdf()
    wait_for(w.app, lambda: not w.widget._pdf_hunt_poll.isActive())
    assert "尚未找到可下載的開放 PDF" in w.widget.pdf_missing.text()
    assert FIND_PDF in w.widget.pdf_missing.text()
    assert w.widget.pdf_note.text() == "尚無 PDF"
