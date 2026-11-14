"""The fixture client must be quiescent before native version leases are taken."""

import gc
import hashlib

from test_sync_client import client

from paper_daily import file_change


def test_fixture_initialization_connection_is_closed_before_observation(tmp_path):
    gc.collect()
    database = client(tmp_path / "device.sqlite", "a").journal.path
    before = file_change.version(database)
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    gc.collect()
    after = file_change.version(database)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    assert after == before, (before, after)
