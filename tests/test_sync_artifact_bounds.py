"""Corrupt or racing local artifact bytes cannot exceed declared read limits."""

from pathlib import Path

import pytest
from test_sync_files import PAPER, codec  # noqa: F401
from test_sync_reading_state_service import op, ref

from paper_daily.sync_artifacts import stage_bytes, verify_closure
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_files import file_id


@pytest.fixture
def prepared(request, tmp_path):
    _deck, payload, blobs = request.getfixturevalue("codec")
    store = BlobStore(tmp_path / "owned")
    stage_bytes(store, blobs)
    operation = op(
        "deck",
        "research_file",
        file_id(PAPER, "deck", "guide"),
        payload,
        parents=[ref("paper", PAPER, "paper-create")],
    )
    row = payload["body"]
    path = store._path(BlobManifest(row["sha256"], row["size"]))
    return store, operation, row, path


class Reader:
    def __init__(self, stream, read):
        self.stream, self._read = stream, read

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def read(self, amount=-1):
        return self._read(self.stream, amount)


@pytest.mark.parametrize("difference", [-1, 1, 1024])
def test_wrong_size_is_rejected_before_read_or_allocation(prepared, monkeypatch, difference):
    store, operation, row, path = prepared
    path.write_bytes(b"x" * (row["size"] + difference))
    original = Path.open

    def guarded(self, *args, **kwargs):
        if self == path:
            pytest.fail("Wrong-size artifact was opened for allocation")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError, match="size"):
        verify_closure(store, operation)


def test_append_after_initial_size_check_still_uses_a_bounded_read(prepared, monkeypatch):
    store, operation, row, path = prepared
    original, amounts = Path.open, []

    def read(stream, amount):
        assert amount == row["size"] + 1
        amounts.append(amount)
        with original(path, "ab") as writer:
            writer.write(b"x" * 4096)
        return stream.read(amount)

    def guarded(self, *args, **kwargs):
        stream = original(self, *args, **kwargs)
        return Reader(stream, read) if self == path else stream

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError, match="changed|size"):
        verify_closure(store, operation)
    assert amounts == [row["size"] + 1]


def test_open_handle_must_match_verified_path_before_read(prepared, tmp_path, monkeypatch):
    store, operation, row, path = prepared
    other = tmp_path / "different-file"
    other.write_bytes(b"x" * row["size"])
    original = Path.open

    def read(_stream, _amount):
        pytest.fail("Read a different file handle before checking identity")

    def redirected(self, *args, **kwargs):
        if self == path:
            return Reader(original(other, "rb"), read)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", redirected)
    with pytest.raises(ValueError, match="changed|identity"):
        verify_closure(store, operation)


def test_valid_closure_still_verifies_and_returns_all_exact_bytes(prepared):
    store, operation, row, _path = prepared
    verified, body, blobs = verify_closure(store, operation)
    assert verified.matches(operation)
    assert body["deck"]["slides"][0]["speaker_notes"] == "Speaker explanation"
    assert len(blobs[row["sha256"]]) == row["size"]
