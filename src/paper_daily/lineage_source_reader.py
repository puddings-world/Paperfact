"""Choose the actual saved Lineage origin before verifying any original bytes.

Reader selection is not a source grant. Each maintained reader still validates
its own current ownership and delivery proof. Never try another reader on failure.
"""

from paper_daily import (
    lineage_bound_originals,
    lineage_import_originals,
    lineage_originals,
    lineage_package_publish,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker


def reader_in(conn, owner, row):
    """Worker-only, caller read transaction, current owner/row before provenance."""
    _worker()
    if not conn.in_transaction or generation._path(conn) != str(owner.database):
        raise ValueError("Lineage reader selection requires its owner transaction")
    owner.check(conn)
    if lineage_originals._row(conn, owner.paper_id, row["corpus_key"]) != row:
        raise ValueError("Displayed Lineage row changed before reader selection")
    if generation._binding(conn) is not None:
        return lineage_bound_originals
    if lineage_package_publish.current_in(conn, row) is not None:
        return lineage_import_originals
    # Absence of an import match is not evidence of a generated publication.
    # Require the exact local receipt before selecting that separate verifier.
    lineage_originals._latest(conn, row)
    return lineage_originals
