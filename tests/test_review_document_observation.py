"""Compare resolved reader states, while retaining actual new-file/owner checks."""

import pymupdf
import pytest

from paper_daily.document_reader import DocumentReader
from paper_daily.review_draft_sources import check_document


@pytest.mark.parametrize("configured", [False, True])
def test_unchanged_absent_original_does_not_invalidate_a_review(tmp_path, configured):
    reader = DocumentReader.from_workspace(
        tmp_path / "missing.db", legacy_root=tmp_path if configured else None
    )
    original = reader.resolve("paper")
    assert original.status == ("missing" if configured else "unconfigured")
    check_document(original)
    assert not (tmp_path / "missing.db").exists()
    reader.close()
    with pytest.raises(ValueError, match="PDF changed"):
        check_document(original)


def test_newly_available_pdf_cannot_reuse_a_missing_document_observation(tmp_path):
    reader = DocumentReader.from_workspace(tmp_path / "missing.db", legacy_root=tmp_path)
    original = reader.resolve("paper")
    assert original.status == "missing"
    check_document(original)
    with pymupdf.open() as document:
        document.new_page().insert_text((50, 50), "New actual original after review")
        document.save(tmp_path / "paper.pdf")
    with pytest.raises(ValueError, match="PDF changed"):
        check_document(original)
    reader.close()
