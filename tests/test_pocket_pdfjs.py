"""A real pocket export reaches the same protected display/text parser boundary."""

import os
import shutil
import subprocess
from pathlib import Path

import pymupdf
from test_pocket import workspace as pocket_workspace

from paper_daily import pocket

workspace = pocket_workspace


def test_exported_reader_disables_eval_for_display_and_text(workspace, monkeypatch):
    monkeypatch.setattr(pocket, "POCKET_PDF_DIR", workspace / "compressed")
    original = pocket.PDF_DIR / "ref_a.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 40), "Fixture original; never opened by a real browser.")
        document.save(original)
    before = original.read_bytes()
    built = pocket.write(["ref:a"], workspace / "export" / "index.html")
    assert original.read_bytes() == before
    assert (built["out"].parent / "pdf/ref_a.pdf").is_file()
    node = shutil.which("node")
    assert node, "Node.js is required to exercise the exported reader parser calls"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "--test-reporter=tap", str(root / "tests/test_pocket_pdfjs.mjs")],
        cwd=root,
        env={**os.environ, "PAPERFACT_POCKET_TEST_HTML": str(built["out"])},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# pass 6" in result.stdout
