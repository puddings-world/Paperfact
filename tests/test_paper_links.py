"""A paper's pages on the web, named for what they are, one click from the reader and list."""

from types import SimpleNamespace

from paper_daily.desktop import paper_links


def paper(**kw):
    base = dict(title="HoughSAM: Zero-Shot Segmentation", page_url=None, pdf_url=None,
                arxiv_id=None)
    return SimpleNamespace(**{**base, **kw})


def test_each_page_is_named_for_what_it_is_and_the_pdf_source_is_kept():
    found = paper_links.links(paper(
        page_url="https://doi.org/10.1007/978-3-032-38233-7_20",
        pdf_url="https://papers.miccai.org/miccai-2026/paper/2588_paper.pdf",
        arxiv_id="2401.01234",
    ))
    assert [label for label, _url in found] == [
        "出版頁面（DOI）", "arXiv 2401.01234", "原文 PDF 來源", "Google Scholar 搜尋"]
    assert found[1][1] == "https://arxiv.org/abs/2401.01234"
    assert found[3][1].startswith("https://scholar.google.com/scholar?q=HoughSAM%3A%20")
    assert paper_links.site_name("https://iclr.cc/virtual/2024/poster/1") == "會議頁面"
    assert paper_links.site_name("https://example.org/paper") == "論文網頁"


def test_only_web_addresses_are_linked_and_the_same_address_once():
    found = paper_links.links(paper(page_url="javascript:alert(1)",
                                    pdf_url="https://a.org/x.pdf"), search=False)
    assert found == [("原文 PDF 來源", "https://a.org/x.pdf")]
    same = paper_links.links(paper(page_url="https://a.org/x.pdf", pdf_url="https://a.org/x.pdf"),
                             search=False)
    assert len(same) == 1


def test_the_row_link_is_the_papers_own_page_never_a_search():
    assert paper_links.main_link(paper()) is None
    assert paper_links.main_link(paper(pdf_url="https://a.org/x.pdf")) == (
        "原文 PDF 來源", "https://a.org/x.pdf")
