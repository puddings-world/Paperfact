"""Supplying original bytes does not implicitly authorize AI analysis."""

from types import SimpleNamespace

import pytest

from paper_daily.desktop import queue_view


@pytest.mark.parametrize("source", ["file", "url"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_pdf_supply_requests_only_the_explicit_file_action(monkeypatch, source, cancelled):
    selected = "" if cancelled else "/synthetic/known.pdf"
    url = "https://fixture.invalid/known.pdf"
    monkeypatch.setattr(
        queue_view.QFileDialog,
        "getOpenFileName",
        lambda *a: (selected, "PDF (*.pdf)"),
    )
    monkeypatch.setattr(
        queue_view.QInputDialog,
        "getText",
        lambda *a: (url, not cancelled),
    )
    calls = []
    page = SimpleNamespace(_start=lambda args, then=None: calls.append((args, then)))
    paper = SimpleNamespace(id="paper", title="Synthetic paper")
    queue_view.QueuePage._supply_pdf(page, paper, source)
    assert calls == (
        []
        if cancelled
        else [
            (
                [
                    "repdf",
                    "paper",
                    "--file" if source == "file" else "--url",
                    selected if source == "file" else url,
                ],
                None,
            )
        ]
    )
