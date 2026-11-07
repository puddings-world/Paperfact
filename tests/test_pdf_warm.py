"""Pointing at a paper reads its PDF ahead of the click: from a cold disk, opening
it otherwise waited two thirds of a second on the window's thread."""

import threading

from paper_daily.desktop import pdf_warm


def test_a_pointed_at_pdf_is_read_once(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF" * 1000)
    opened = []
    real_open = open

    def tracking_open(path, mode="r", *a, **k):
        opened.append(path)
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", tracking_open)
    monkeypatch.setattr(pdf_warm, "_done", type(pdf_warm._done)())
    pdf_warm.warm(pdf)
    assert pdf_warm.idle()
    pdf_warm.warm(pdf)
    assert pdf_warm.idle()
    assert opened == [pdf]


def test_sweeping_past_rows_reads_only_the_last_one_waiting(tmp_path, monkeypatch):
    gate, opened = threading.Event(), []
    real_open = open

    def slow_open(path, mode="r", *a, **k):
        opened.append(path.name)
        gate.wait(5)
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", slow_open)
    monkeypatch.setattr(pdf_warm, "_done", type(pdf_warm._done)())
    paths = []
    for name in "abcd":
        paths.append(tmp_path / f"{name}.pdf")
        paths[-1].write_bytes(b"%PDF")
    pdf_warm.warm(paths[0])
    while not opened:
        threading.Event().wait(0.005)
    for path in paths[1:]:
        pdf_warm.warm(path)
    gate.set()
    assert pdf_warm.idle()
    assert opened == ["a.pdf", "d.pdf"]


def test_a_missing_file_is_not_an_error(tmp_path):
    pdf_warm.warm(tmp_path / "gone.pdf")
    assert pdf_warm.idle()
