"""Exercise real local TLS sockets without touching a user's Drive or home network."""

import hashlib
import ipaddress
import time
from contextlib import ExitStack
from types import SimpleNamespace

from paper_daily import lan_pdf
from paper_daily.drive_sync_objects import DriveObjects
from paper_daily.file_change import version
from paper_daily.sync_blobs import BlobStore


def test_verified_chunks_switch_from_authenticated_peer_to_drive(tmp_path, monkeypatch):
    # Use loopback for the synthetic home network only.
    local = ipaddress.ip_interface("127.0.0.1/8")
    monkeypatch.setattr(lan_pdf, "PRIVATE", (local.network,))
    registry = {}

    class Registry:
        def owned(self, *args):
            return {}

        def request(self, method, url, *, params, json=None):
            if json:
                registry.update(json["properties"])
            return dict(ownedByMe=True, shared=False, trashed=False, properties=dict(registry))

        def json(self, value):
            return value

    directory = SimpleNamespace(folder="library", key="library", files=Registry())
    data = b"first chunk"
    digest = hashlib.sha256(data).hexdigest()
    path = tmp_path / "original.pdf"
    path.write_bytes(data)
    ref = dict(sha256=digest, size=len(data), id="part")
    manifest = dict(format="paperfact.drive-bytes.v1", sha256=digest, size=len(data), chunks=[ref])
    with ExitStack() as stack:
        source, laptop = lan_pdf.LanPdf(local), lan_pdf.LanPdf(local)
        for peer, label in ((source, "source"), (laptop, "laptop")):
            stack.callback(peer.close)
            peer.scope = ("library", label, local)
            peer.refresh(directory, SimpleNamespace(context=label))
        source.updated = 0
        source.refresh(directory, SimpleNamespace(context="source"))
        permit = [True]
        source.offers[digest] = path, version(path), lambda: permit[0]
        drive_reads = []

        def read(*args):
            drive_reads.append(args[0]["id"])
            return data

        files = SimpleNamespace(check=lambda: None, owned=lambda *args: None,
                                read_small=read, lan_pdf=laptop)
        objects = DriveObjects(files, "library", "library", tmp_path / "receipts",
                               folder_role="directory")
        received = objects.get(manifest, BlobStore(tmp_path / "peer-copy"))
        assert received.read_bytes() == data and not drive_reads
        # Lose the peer after one committed chunk of the very same download.
        chunks = [b"x" * lan_pdf.MAX_INLINE, b"last"]
        larger = b"".join(chunks)
        full_hash = hashlib.sha256(larger).hexdigest()
        original = tmp_path / "large.pdf"
        original.write_bytes(larger)
        source.offers[full_hash] = original, version(original), lambda: True
        refs = [dict(id=f"chunk-{i}", sha256=hashlib.sha256(chunk).hexdigest(), size=len(chunk))
                for i, chunk in enumerate(chunks)]
        multi = dict(format=manifest["format"], sha256=full_hash, size=len(larger), chunks=refs)
        blobs = BlobStore(tmp_path / "interrupted")
        fetch = laptop.fetch

        def disconnect(digest, offset, reference):
            if offset:
                raise ConnectionError("test interruption")
            return fetch(digest, offset, reference)

        import pytest

        monkeypatch.setattr(laptop, "fetch", disconnect)
        with pytest.raises(ConnectionError, match="test interruption"):
            objects.get(multi, blobs)
        monkeypatch.setattr(laptop, "fetch", lambda *args: None)

        def last_chunk(ref, *args):
            drive_reads.append(ref["id"])
            return chunks[1]

        files.read_small = last_chunk
        assert objects.get(multi, blobs).read_bytes() == larger
        assert drive_reads == ["chunk-1"]
        drive_reads.clear()
        files.read_small = read
        monkeypatch.setattr(laptop, "fetch", fetch)
        permit[0] = False
        assert laptop.fetch(digest, 0, ref) is None
        permit[0] = True
        source.peers = {}
        assert laptop.fetch(digest, 0, ref) is None
        source.close()
        received = objects.get(manifest, BlobStore(tmp_path / "drive-copy"))
        assert received.read_bytes() == data and drive_reads == ["part"]
        laptop.lease = time.monotonic() - 1
        assert laptop.fetch(digest, 0, ref) is None
