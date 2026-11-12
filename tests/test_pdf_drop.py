"""A PDF dragged onto the window joins the open reading list and is read from that file."""

import argparse

import pymupdf as fitz
import pytest
from PySide6.QtCore import QMimeData, QUrl
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import cli, lists, pdf_identity, repdf, runtime, store
from paper_daily.desktop import add_dialog
from paper_daily.desktop.main import MainWindow

workspace = _workspace
TITLE = "Sparse Attention Learns Its Own Receptive Field"


def _pdf(path, title=TITLE, meta_title="", stamp="arXiv:2401.01234v2 [cs.LG] 3 Jan 2024", body=""):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 120), title, fontsize=17)
    page.insert_text((60, 150), "Ada Lovelace, Alan Turing", fontsize=10)
    page.insert_text((60, 700), stamp + " " + body, fontsize=8)
    doc.set_metadata({"title": meta_title})
    doc.save(path)
    doc.close()
    return path


def test_the_first_page_names_the_paper():
    found = pdf_identity.from_parts(
        "Microsoft Word - final_v3.docx",
        "Published as doi:10.1145/3580305.3599256. arXiv:2401.01234v3",
        [
            (9.0, 0.02, "Workshop header"),
            (17.0, 0.1, "Sparse Attention Learns"),
            (17.0, 0.13, "Its Own Receptive Field"),
            (10.0, 0.16, "Ada Lovelace"),
            (24.0, 0.6, "Figure 1"),
        ],
    )
    assert found == {
        "doi": "10.1145/3580305.3599256",
        "arxiv": "2401.01234",
        "title": "Sparse Attention Learns Its Own Receptive Field",
    }
    # A real metadata title wins over guessing from type sizes.
    assert pdf_identity.from_parts("Graph Neural Networks Revisited", "", [])["title"] == (
        "Graph Neural Networks Revisited"
    )


def test_a_real_pdf_is_read_from_its_first_page(tmp_path):
    found = pdf_identity.guess(_pdf(tmp_path / "paper.pdf", meta_title="untitled"))
    assert found["title"] == TITLE and found["arxiv"] == "2401.01234" and found["doi"] is None


def _args(**kw):
    base = dict(list_id="x", citation=None, file=None, doi=None, create=None, pdf=None)
    return argparse.Namespace(**{**base, **kw})


def test_list_add_with_a_pdf_names_the_paper_and_reads_that_file(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "paper.pdf", stamp="", body="doi:10.5555/12345.678")
    asked, attached = [], []
    monkeypatch.setattr(
        lists,
        "add_paper",
        lambda list_id, citation, **kw: (
            asked.append((list_id, citation, kw["doi"]))
            or {"added": 1, "paper_ids": ["p1"], "already": [], "reason": "ok"}
        ),
    )
    monkeypatch.setattr(
        repdf,
        "replace",
        lambda pid, url, log=print, file=None: attached.append((pid, file)) or True,
    )
    from paper_daily import resources

    monkeypatch.setattr(resources, "refresh", lambda conn, ids, log=None: None)
    assert cli.cmd_list_add(_args(pdf=str(pdf))) == 0
    assert asked == [("x", TITLE, "10.5555/12345.678")]
    assert attached == [("p1", str(pdf))]


def test_a_paper_already_in_the_list_keeps_its_pdf(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "paper.pdf")
    monkeypatch.setattr(
        lists,
        "add_paper",
        lambda *a, **k: {
            "added": 0,
            "paper_ids": [],
            "already": ["p1"],
            "reason": "already in this list",
        },
    )
    monkeypatch.setattr(repdf, "PDF_DIR", tmp_path)
    (tmp_path / "p1.pdf").write_bytes(b"%PDF-1.7 existing")
    monkeypatch.setattr(repdf, "replace", lambda *a, **k: pytest.fail("replaced a kept PDF"))
    # Nothing was added, so the command still reports that, but the file is untouched.
    assert cli.cmd_list_add(_args(pdf=str(pdf))) == 1
    assert (tmp_path / "p1.pdf").read_bytes() == b"%PDF-1.7 existing"


def _drop(win, *paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def test_dropping_a_pdf_offers_it_to_the_open_list(workspace, monkeypatch, tmp_path):
    win = MainWindow()
    try:
        pdf = _pdf(tmp_path / "paper.pdf")
        seen = []
        import paper_daily.desktop.main as main

        monkeypatch.setattr(main, "run_add", lambda w, pdf=None: seen.append(pdf) or False)
        assert MainWindow.dropped_pdfs(_drop(win, pdf, tmp_path / "notes.txt")) == [pdf]

        class Event:
            def __init__(self, mime):
                self._mime, self.accepted = mime, False

            def mimeData(self):
                return self._mime

            def acceptProposedAction(self):
                self.accepted = True

        win.active_list = None
        event = Event(_drop(win, pdf))
        win.dropEvent(event)
        assert event.accepted and not seen
        assert "切到一個清單" in win.queue_page.analysis.text()

        win.active_list = "x"
        win.dropEvent(Event(_drop(win, pdf, pdf)))
        assert seen == [pdf, pdf]
    finally:
        win.close()
        win.deleteLater()


def test_the_dialog_shows_the_guess_and_passes_the_file_along(workspace, monkeypatch, tmp_path):
    owner = MainWindow()
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    pdf = _pdf(tmp_path / "paper.pdf", body="https://doi.org/10.5555/12345.678")
    commands = []
    missing = str(workspace[1] / "missing-python.exe")
    monkeypatch.setattr(runtime, "cli_command", lambda *a: commands.append(a) or [missing, *a])
    widget = add_dialog.AddToListDialog(owner.pal, "x", "Research", workspace[1], owner, pdf=pdf)
    try:
        # The arXiv id is exact, so it is what gets looked up; the title is shown when
        # there is no id.
        assert widget.body.toPlainText() == "2401.01234"
        assert any(
            "paper.pdf" in label.text() for label in widget.findChildren(type(widget.status))
        )
        assert "10.5555/12345.678" in widget.status.text()
        widget._start_ready()
        args = commands[-1]
        # The job is handed to the AI-job wrapper; the command it carries is what matters.
        at = args.index("list-add")
        assert args[at : at + 2] == ("list-add", "x")
        assert args[args.index("--pdf") + 1] == str(pdf)
        assert args[args.index("--doi") + 1] == "10.5555/12345.678"
    finally:
        widget.close()
        owner.close()
        owner.deleteLater()


def test_a_small_caps_title_keeps_its_capitals(tmp_path):
    # Each word's capital is set larger than the rest; read by spans, the title lost
    # its first letters ("ATEGORICAL EPARAMETERIZATION").
    doc = fitz.open()
    page = doc.new_page()
    x = 60
    for big, small in [("C", "ATEGORICAL "), ("R", "EPARAMETERIZATION")]:
        page.insert_text((x, 120), big, fontsize=17)
        x += 12
        page.insert_text((x, 120), small, fontsize=13)
        x += 8 * len(small)
    page.insert_text((60, 160), "Eric Jang, Shixiang Gu", fontsize=10)
    doc.save(tmp_path / "caps.pdf")
    doc.close()
    assert pdf_identity.guess(tmp_path / "caps.pdf")["title"] == "CATEGORICAL REPARAMETERIZATION"


def test_open_with_passes_the_pdf_to_the_running_window(workspace, monkeypatch, tmp_path):
    from PySide6.QtGui import QFileOpenEvent

    import paper_daily.desktop.main as main

    assert cli.build_parser().parse_args(["app", "paper.pdf"]).pdf == "paper.pdf"

    class Socket:
        def connectToServer(self, name):
            pass

        def waitForConnected(self, _ms):
            return True

        def write(self, data):
            sent.append(data)

        def __getattr__(self, _name):
            return lambda *a: None

    sent = []
    monkeypatch.setattr(main, "QLocalSocket", Socket)
    pdf = _pdf(tmp_path / "paper.pdf")
    assert main._hand_off_to_running_instance(False, pdf=str(pdf))
    assert sent == [b"pdf:" + str(pdf.resolve()).encode()]
    win = MainWindow()
    try:
        seen = []
        monkeypatch.setattr(win, "open_pdfs", lambda pdfs: seen.extend(pdfs))
        opens = main._FileOpens(win)
        assert opens.eventFilter(None, QFileOpenEvent(str(pdf)))
        assert not opens.eventFilter(None, QFileOpenEvent(str(tmp_path / "notes.txt")))
        assert seen == [pdf]
    finally:
        win.close()
        win.deleteLater()
