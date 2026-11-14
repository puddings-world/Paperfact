"""A legacy upgrade must not relax rich-note identity or anchored-source guards."""

import pytest
from test_sync_content import database, envelope, seed, snapshot

from paper_daily.sync_research import research_writer


def test_existing_rich_note_still_rejects_a_changed_creation_identity(tmp_path):
    path, local, journal = database(tmp_path, "rich-owner")
    seed(path, local)
    before = snapshot(path, tables={"notes"})
    identity, payload = next(iter(before.items()))
    journal.apply(envelope(identity, payload, op_id="rich-start"), research_writer)
    changed = dict(payload, created_at="2030-01-01T00:00:00+00:00", body="Invalid overwrite")
    with pytest.raises(ValueError, match="creation identity"):
        journal.apply(
            envelope(identity, changed, op_id="changed-creation", predecessor="rich-start"),
            research_writer,
        )
    assert snapshot(path, tables={"notes"}) == before
