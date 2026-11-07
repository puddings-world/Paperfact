"""Pathless, bounded rescue archives over the shared scientific proposal codec."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change
from paper_daily import portable_deck_proposal as codec
from paper_daily.sync_blobs import _no_link
from paper_daily.sync_files import canonical_json, read_json
from paper_daily.workspace_service import Ticket

MAX_FILES = codec.MAX_IMAGES + codec.MAX_ORIGINALS + 2
MAX_EXPANDED = codec.MAX_ORIGINAL_BYTES + codec.MAX_IMAGE_BYTES + 2 * codec.MAX_METADATA_BYTES
_SEAL = object()


def _path(value, *, existing=True):
    path = Path(value).absolute()
    for entry in (path, *path.parents):
        _no_link(entry)
    return path.resolve(strict=existing)


def _check(current):
    if not current():
        raise ValueError("Rescue archive action was cancelled or its original scope changed")


def _items(manifest):
    codec.fingerprint(manifest)
    result = {}
    for item in [manifest["research"], *manifest["images"], *manifest["originals"]]:
        description = {key: item[key] for key in ("sha256", "size", "media_type")}
        prior = result.setdefault(item["sha256"], description)
        if prior != description:
            raise ValueError("Rescue archive object descriptors disagree")
    return result


@dataclass(frozen=True)
class RescueArchive:
    source_path: Path
    file_version: tuple
    _manifest: str = field(repr=False)
    _objects: tuple = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def manifest(self):
        return json.loads(self._manifest)

    @property
    def content(self):
        if self._seal is not _SEAL:
            raise ValueError("Use a verified rescue archive")
        values = dict(self._objects)
        return codec.decode(self.manifest, lambda item: values[item["sha256"]])

    def read_blob(self, item):
        if self._seal is not _SEAL:
            raise ValueError("Use a verified rescue archive")
        values = dict(self._objects)
        return values[item["sha256"]]

    def current(self):
        if self._seal is not _SEAL:
            return False
        try:
            return canonical_json(file_change.version(_path(self.source_path))) == canonical_json(
                self.file_version
            )
        except (ValueError, OSError):
            return False


def inspect_file(path, *, current=lambda: True):
    _check(current)
    path = _path(path)
    before = file_change.version(path)
    if not path.is_file() or before[2] > MAX_EXPANDED:
        raise ValueError("Rescue archive exceeds its bounded file budget")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if (
                len(infos) > MAX_FILES
                or len(names) != len({n.casefold() for n in names})
                or sum(item.file_size for item in infos) > MAX_EXPANDED
            ):
                raise ValueError("Rescue archive exceeds its object budget or repeats a name")
            if any(
                item.flag_bits & 1
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                for item in infos
            ):
                raise ValueError("Unsupported rescue archive member")
            if archive.getinfo("manifest.json").file_size > codec.MAX_METADATA_BYTES:
                raise ValueError("Rescue archive metadata exceeds its budget")
            manifest = read_json(archive.read("manifest.json"))
            expected = _items(manifest)
            if set(names) != {"manifest.json", *("objects/" + sha for sha in expected)}:
                raise ValueError("Rescue archive contains missing, unsafe or undeclared members")
            objects = {}
            for sha, item in expected.items():
                _check(current)
                name = "objects/" + sha
                if archive.getinfo(name).file_size != item["size"]:
                    raise ValueError("Rescue archive member size differs from its descriptor")
                objects[sha] = archive.read(name)
            codec.decode(manifest, lambda item: objects[item["sha256"]])
    except (zipfile.BadZipFile, KeyError) as error:
        raise ValueError("Invalid or incomplete Paperfact rescue archive") from error
    _check(current)
    if canonical_json(file_change.version(path)) != canonical_json(before):
        raise ValueError("Rescue archive changed during verification")
    return RescueArchive(
        path,
        tuple(before),
        canonical_json(manifest).decode(),
        tuple(sorted(objects.items())),
        _SEAL,
    )


def export(destination, manifest, read_blob, *, overwrite=False, current=lambda: True, ticket=None):
    """Verify complete scientific closure and publish one independently readable file."""
    if type(overwrite) is not bool:
        raise ValueError("Rescue overwrite must be explicit")
    _check(current)
    destination = _path(destination, existing=False)
    before = file_change.version(destination) if destination.exists() else None
    if before is not None and not overwrite:
        raise FileExistsError("The rescue destination already exists")
    anchor = destination.parent
    while not anchor.exists():
        anchor = anchor.parent
    anchor = _path(anchor)
    if not anchor.is_dir():
        raise ValueError("Rescue destination requires an actual directory")
    info = anchor.stat()
    anchor_native = (info.st_dev, info.st_ino)
    expected = _items(manifest)
    objects = {}

    def read(item):
        _check(current)
        sha = item["sha256"]
        if sha not in objects:
            objects[sha] = read_blob(item)
        return objects[sha]

    codec.decode(manifest, read)
    info = _path(anchor).stat()
    if (info.st_dev, info.st_ino) != anchor_native:
        raise ValueError("Rescue destination ancestor changed during capture")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _path(destination.parent)
    info = destination.parent.stat()
    parent_native = (info.st_dev, info.st_ino)
    handle, stage = tempfile.mkstemp(
        prefix=".paperfact-rescue-", suffix=".zip", dir=destination.parent
    )
    os.close(handle)
    stage = Path(stage)
    try:
        with zipfile.ZipFile(stage, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical_json(manifest))
            for sha in sorted(expected):
                _check(current)
                archive.writestr("objects/" + sha, objects[sha])
        with stage.open("r+b") as stream:
            os.fsync(stream.fileno())
        verified = inspect_file(stage, current=current)
        if verified.manifest != manifest or dict(verified._objects) != objects:
            raise ValueError("Published rescue archive differs from captured scientific content")
        _check(current)
        _path(destination, existing=False)
        after = file_change.version(destination) if destination.exists() else None
        if canonical_json(after) != canonical_json(before):
            raise ValueError("Rescue destination changed during export")

        def publish():
            _check(current)
            _path(destination, existing=False)
            info = destination.parent.stat()
            if (info.st_dev, info.st_ino) != parent_native:
                raise ValueError("Rescue destination directory changed before publication")
            now = file_change.version(destination) if destination.exists() else None
            if canonical_json(now) != canonical_json(before):
                raise ValueError("Rescue destination changed before publication")
            os.replace(stage, destination)

        (ticket or Ticket()).publish(publish)
        return destination
    finally:
        with suppress(FileNotFoundError):
            stage.unlink()
