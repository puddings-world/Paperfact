"""Actual portable rescue files include every scientific image and original, no writer."""

import hashlib
import json
import os
import zipfile

import pytest
from test_portable_deck_proposal import encoded
from test_portable_deck_proposal import scientific as _scientific

from paper_daily import portable_deck_archive as archive
from paper_daily.workspace_service import Cancelled, Ticket

scientific = _scientific


def test_real_rescue_archive_roundtrip_is_defensive_and_keeps_original_a(scientific, tmp_path):
    manifest, blobs = encoded(scientific)
    path = tmp_path / "copy.paperfact-draft.zip"
    assert archive.export(path, manifest, lambda item: blobs[item["sha256"]]) == path
    saved = archive.inspect_file(path)
    value = saved.content
    assert value["image_bytes"] == scientific[2]
    assert value["original_bytes"] == scientific[3]
    assert saved.current() and saved.manifest == manifest
    value["deck"]["title"] = "Caller edit"
    assert saved.content["deck"]["title"] != value["deck"]["title"]
    raw = b"".join(blobs.values()) + json.dumps(manifest).encode()
    with zipfile.ZipFile(path) as zipped:
        assert set(zipped.namelist()) == {"manifest.json", *("objects/" + key for key in blobs)}
        assert b"private-account" not in raw and b"local-writer-secret" not in raw
    path.write_bytes(path.read_bytes() + b"\n")
    assert not saved.current()


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "duplicate", "changed-pdf", "unsafe", "symlink"]
)
def test_untrusted_zip_objects_are_closed_and_verified(scientific, tmp_path, fault):
    manifest, blobs = encoded(scientific)
    values = {
        "manifest.json": json.dumps(manifest).encode(),
        **{"objects/" + key: data for key, data in blobs.items()},
    }
    original = manifest["originals"][0]["sha256"]
    key = "objects/" + original
    if fault == "missing":
        del values[key]
    elif fault == "extra":
        values["objects/" + hashlib.sha256(b"extra").hexdigest()] = b"extra"
    elif fault == "changed-pdf":
        values[key] = b"A different PDF must not substitute the original"
    elif fault == "unsafe":
        values["../outside"] = b"not extracted"
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        for name, data in values.items():
            zipped.writestr(name, data)
        if fault == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                zipped.writestr("manifest.json", values["manifest.json"])
        elif fault == "symlink":
            item = zipfile.ZipInfo("symbolic-link")
            item.external_attr = 0o120777 << 16
            zipped.writestr(item, b"outside")
    with pytest.raises(ValueError):
        archive.inspect_file(path)
    assert not (tmp_path.parent / "outside").exists()


@pytest.mark.parametrize("fault", ["existing", "cancel", "bad-content", "destination-changed"])
def test_failed_export_preserves_existing_destination_and_leaves_no_parts(
    scientific, tmp_path, fault, monkeypatch
):
    manifest, blobs = encoded(scientific)
    path = tmp_path / "existing.zip"
    path.write_bytes(b"Existing user file")
    ticket = Ticket()
    if fault == "cancel":
        ticket.cancel()

    def read(item):
        if fault == "destination-changed":
            path.write_bytes(b"External newer file")
        return b"corrupt" if fault == "bad-content" else blobs[item["sha256"]]

    with pytest.raises((ValueError, FileExistsError, Cancelled)):
        archive.export(path, manifest, read, overwrite=fault != "existing", ticket=ticket)
    assert path.read_bytes() == (
        b"External newer file" if fault == "destination-changed" else b"Existing user file"
    )
    assert not list(tmp_path.glob(".paperfact-rescue-*"))


def test_explicit_overwrite_keeps_complete_rescue_file(scientific, tmp_path):
    manifest, blobs = encoded(scientific)
    path = tmp_path / "old.zip"
    path.write_bytes(b"old")
    archive.export(path, manifest, lambda item: blobs[item["sha256"]], overwrite=True)
    assert archive.inspect_file(path).content["original_bytes"] == scientific[3]


def test_cancelled_capture_creates_no_destination(scientific, tmp_path):
    manifest, blobs = encoded(scientific)
    alive = [True]

    def read(item):
        alive[0] = False
        return blobs[item["sha256"]]

    path = tmp_path / "cancelled.zip"
    with pytest.raises(ValueError, match="cancelled"):
        archive.export(path, manifest, read, current=lambda: alive[0])
    assert not path.exists() and not list(tmp_path.glob(".paperfact-rescue-*"))


def test_parent_native_replacement_during_capture_refuses_new_directory(scientific, tmp_path):
    manifest, blobs = encoded(scientific)
    parent = tmp_path / "chosen"
    parent.mkdir()
    moved = tmp_path / "old-chosen"
    acted = []

    def read(item):
        if not acted:
            acted.append(True)
            os.replace(parent, moved)
            parent.mkdir()
        return blobs[item["sha256"]]

    with pytest.raises(ValueError, match="ancestor"):
        archive.export(parent / "copy.zip", manifest, read)
    assert not list(parent.iterdir())


def test_limits_refuse_before_reading_untrusted_members(scientific, tmp_path, monkeypatch):
    manifest, blobs = encoded(scientific)
    path = tmp_path / "large.zip"
    archive.export(path, manifest, lambda item: blobs[item["sha256"]])
    monkeypatch.setattr(archive, "MAX_EXPANDED", path.stat().st_size - 1)
    with pytest.raises(ValueError, match="budget"):
        archive.inspect_file(path)
