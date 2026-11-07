"""A new database at the same path is a new reader authority, even with equal data."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_research_generation import workspace as _workspace

from paper_daily.document_reader import from_workspace

workspace = _workspace
pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.mark.parametrize("new_paper_identity", [False, True], ids=["same-data", "new-paper"])
def test_native_database_replacement_revokes_old_reader_and_resolves_new_identity(
    workspace, new_paper_identity
):
    database, _client, original = workspace
    reader = from_workspace(database, legacy_root=original.path.parent)
    first = reader.resolve("paper")
    assert first.available and first.paper_id == original.paper_id
    replacement = database.with_suffix(".replacement.sqlite")
    with closing(sqlite3.connect(database)) as old, closing(sqlite3.connect(replacement)) as new:
        old.backup(new)
        identity = str(uuid4()) if new_paper_identity else first.paper_id
        if new_paper_identity:
            new.execute(
                "UPDATE research_paper_identity SET sync_id=? WHERE local_id='paper'", (identity,)
            )
            new.commit()
    replacement.replace(database)
    assert not reader.intact(first)
    assert not reader.current(first)
    fresh = reader.resolve("paper")
    assert fresh.available and fresh.paper_id == identity
    assert fresh.path.read_bytes() == first.path.read_bytes()
    assert reader.intact(fresh) and reader.current(fresh)
