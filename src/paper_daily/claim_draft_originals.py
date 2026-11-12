"""Independent owned original reads for claim drafts; no publication."""

from paper_daily import review_draft_originals as _shared

ClaimReadProof = _shared.DraftReadProof


def prepare(service, preview, document_hash, *, reference=None, cancelled=lambda: False):
    return _shared.prepare(
        service,
        preview,
        document_hash,
        domain="claim_resume",
        reference=reference,
        cancelled=cancelled,
    )


def gui_status(proof):
    if getattr(proof, "domain", None) != "claim_resume":
        return "revoked"
    return _shared.gui_status(proof)


def revalidate(proof, *, cancelled=lambda: False):
    if getattr(proof, "domain", None) != "claim_resume":
        raise ValueError("Use an actual claim original read proof")
    return _shared.revalidate(proof, cancelled=cancelled)
