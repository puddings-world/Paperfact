"""List metadata remains lossless across enrolled package intake and peer export."""

import json
import zipfile

import pytest
from test_package_import import importer as importer
from test_package_import import package as package
from test_package_import import rewrite_package
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import bundle, store


def listing_package(source, destination, value, *, include_note=True):
    def listing_only(manifest, tables, files):
        if include_note:
            manifest["list"]["note"] = value
        else:
            manifest["list"].pop("note", None)
        manifest["members"] = []
        manifest["pdfs"] = {}
        for table in tables:
            tables[table] = []
        for name in list(files):
            if name.startswith("files/"):
                del files[name]

    return rewrite_package(source, destination, transform=listing_only)


@pytest.mark.parametrize("value", [None, "", "  ", "Background research"])
def test_import_retry_peer_and_reexport_preserve_exact_list_note(
    package, importer, pair, tmp_path, monkeypatch, value
):
    service, client = importer
    archive = listing_package(package[0], tmp_path / "list.zip", value)
    report = service.apply(service.prepare(archive, request_id="list-metadata"))
    identity = report["list"]
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT note FROM lists WHERE id=?", (identity,)).fetchone()[0] == value
    before = client.journal.pending(1000)
    assert next(op for op in before if op["entity_type"] == "list")["payload"]["note"] == value
    assert {op["entity_type"] for op in before} <= {"list", "list_order"}
    assert service.apply(service.prepare(archive, request_id="list-metadata"))["replayed"]
    assert client.journal.pending(1000) == before
    server, _sender, receiver, _fa, _fb, ta, tb = pair
    client.sync_once(server, ta)
    receiver.sync_once(server, tb)
    with receiver.journal.transaction() as conn:
        assert conn.execute("SELECT note FROM lists WHERE id=?", (identity,)).fetchone()[0] == value
    monkeypatch.setattr(store, "DB_PATH", receiver.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", receiver.journal.path.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", tmp_path / "receiver-pdf")
    exported = tmp_path / "peer-list.zip"
    bundle.export(identity, exported)
    with zipfile.ZipFile(exported) as z:
        assert json.loads(z.read("manifest.json"))["list"]["note"] == value


def test_legacy_missing_optional_note_keeps_existing_import_default(package, importer, tmp_path):
    service, client = importer
    archive = listing_package(package[0], tmp_path / "legacy.zip", None, include_note=False)
    report = service.apply(service.prepare(archive))
    with client.journal.transaction() as conn:
        assert (
            conn.execute("SELECT note FROM lists WHERE id=?", (report["list"],)).fetchone()[0] == ""
        )


def test_existing_receiver_note_changes_only_with_reviewed_replacement(package, importer, tmp_path):
    from uuid import uuid4

    service, client = importer
    identity = str(uuid4())
    client.save(
        client.new_graph_operation(
            "list", identity, {"name": "Existing list", "note": "Receiver context"}
        )
    )
    archive = listing_package(package[0], tmp_path / "incoming.zip", None)
    choices = dict(target_list_id=identity, confirmed_mapping=True)
    service.apply(service.prepare(archive, request_id="keep-note", **choices))
    with client.journal.transaction() as conn:
        assert (
            conn.execute("SELECT note FROM lists WHERE id=?", (identity,)).fetchone()[0]
            == "Receiver context"
        )
    service.apply(service.prepare(archive, replace=True, request_id="replace-note", **choices))
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT note FROM lists WHERE id=?", (identity,)).fetchone()[0] is None
    pending = client.journal.pending(1000)
    assert service.apply(
        service.prepare(archive, replace=True, request_id="replace-note", **choices)
    )["replayed"]
    assert client.journal.pending(1000) == pending
