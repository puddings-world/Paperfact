"""Boolean passage navigation for the new claims/audit consumers only.

The legacy ReaderPage source action is unchanged. Its final document guard is
retained here, and only actual native passage focus counts as success.
"""

from __future__ import annotations

from paper_daily.desktop import document_flow


def focus(reader, source, *, document, current):
    """Keep failed navigation visible; never report a page-only fallback as focus."""
    try:
        if not isinstance(source, dict) or source.get("kind") not in {"claims", "audit"}:
            return False
        digest, anchor = source.get("document_hash"), source.get("anchor")
        pdf = reader.pdf
        selection = getattr(pdf, "selection", None)

        def same():
            return bool(
                current()
                and document is not None
                and getattr(reader, "_active_document", None) is document
                and document.sha256 == digest
                and getattr(reader, "_pdf_fingerprint", None) == digest
                and reader.pdf is pdf
                and pdf.isVisible()
                and selection is not None
                and getattr(pdf, "selection", None) is selection
            )

        if not isinstance(anchor, dict) or not same():
            return False
        if not document_flow.anchor_allowed(reader, source) or not same():
            return False
        return bool(selection.focus(anchor))
    except (OSError, ValueError, RuntimeError):
        return False
