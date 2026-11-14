"""Resumable new-device metadata replay into a new, never merged workspace."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from paper_daily import store
from paper_daily.document_reader import register_document_paths
from paper_daily.sync_artifacts import register_paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_recovery_fs import publish_directory
from paper_daily.sync_research import (
    prepare,
    research_order_writer,
    research_projection_writer,
    research_writer,
)
from paper_daily.workspace_service import _safe_path
from paper_daily.workspace_sync import GuardedJournal, local_binding

FIELDS = {"version", "stage_id", "endpoint", "workspace_id", "device_id", "destination"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _spec(endpoint, identity, destination):
    return {"version": 1, "endpoint": endpoint, **identity, "destination": str(destination)}


def _load(path, expected):
    path = _safe_path(path)
    before = path.stat()
    if before.st_size > 16384:
        raise ValueError("Invalid bootstrap ownership receipt")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(16385)
    after = path.stat()
    if (
        len(raw) > 16384
        or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ValueError("Bootstrap ownership receipt changed")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != FIELDS or type(value["version"]) is not int:
        raise ValueError("Invalid bootstrap ownership receipt")
    if any(value[key] != item for key, item in expected.items()):
        raise ValueError("This bootstrap stage belongs to another request")
    if (
        not isinstance(value["stage_id"], str)
        or re.fullmatch("[0-9a-f]{32}", value["stage_id"]) is None
    ):
        raise ValueError("Invalid bootstrap stage identity")
    return value


def _stage(parent, spec):
    digest = hashlib.sha256(_json(spec).encode()).hexdigest()
    path = _safe_path(parent / (".paperfact-join-" + digest))
    receipt = path / "request.json"
    if path.exists():
        return path, _load(receipt, spec)
    path.mkdir()
    value = {**spec, "stage_id": uuid4().hex}
    # The stage never contains a credential. A missing/incomplete receipt after
    # disk failure is rejected, not adopted as an unrelated writable directory.
    with receipt.open("x", encoding="utf-8") as stream:
        stream.write(_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    return path, value


def _receipt(path, spec):
    path = _safe_path(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT request,cursor,ready FROM local_sync_bootstrap WHERE id=1"
        ).fetchone()
        if (
            row is None
            or json.loads(row[0]) != spec
            or type(row[1]) is not int
            or row[1] < 0
            or row[2] not in (0, 1)
        ):
            raise ValueError("Bootstrap database ownership differs")
        if local_binding(path, require_capture=True) != {
            key: spec[key] for key in ("workspace_id", "device_id")
        }:
            raise ValueError("Bootstrap device identity differs")
        return {"cursor": row[1], "ready": bool(row[2])}
    finally:
        conn.close()


def _initialize(folder, spec):
    folder.mkdir()
    path = folder / "papers.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    finally:
        conn.close()
    identity = {key: spec[key] for key in ("workspace_id", "device_id")}
    prepare(path, **identity)
    journal = Journal(path, **identity)
    SyncClient(
        journal,
        research_writer,
        order_writer=research_order_writer,
        projection_writer=research_projection_writer,
    )
    conn = sqlite3.connect(path, factory=CaptureConnection)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TABLE local_sync_bootstrap (id INTEGER PRIMARY KEY CHECK(id=1),"
            "request TEXT NOT NULL,cursor INTEGER NOT NULL,ready INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO local_sync_bootstrap VALUES(1,?,0,0)", (_json(spec),))
        install(conn, **identity)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _register_final_paths(client, staged, destination):
    blobs = BlobStore(staged / "blobs")
    with client.journal.transaction() as conn:
        document = (
            conn.execute(
                "SELECT blob_root,projection_root,legacy_root FROM document_reader_paths WHERE id=1"
            ).fetchone()
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='document_reader_paths'"
            ).fetchone()
            else None
        )
        artifact = conn.execute(
            "SELECT blob_root,version_root FROM research_file_paths WHERE id=1"
        ).fetchone()
        expected_document = tuple(str(destination / name) for name in ("blobs", "reader", "pdf"))
        expected_artifact = tuple(str(destination / name) for name in ("blobs", "versions"))
        if document is not None and artifact is not None:
            if tuple(document) == expected_document and tuple(artifact) == expected_artifact:
                return
            raise ValueError("Bootstrap paths differ from the selected destination")
        register_document_paths(
            conn,
            workspace_id=client.journal.workspace_id,
            blob_root=blobs.root,
            projection_root=staged / "reader",
            legacy_root=staged / "pdf",
        )
        register_paths(conn, client.journal.workspace_id, blobs, staged / "versions")
        # These are device-local paths, not research envelopes. Rewrite only the
        # new owned stage before its atomic directory publication.
        conn.execute(
            "UPDATE document_reader_paths SET blob_root=?,projection_root=?,legacy_root=? "
            "WHERE id=1",
            (str(destination / "blobs"), str(destination / "reader"), str(destination / "pdf")),
        )
        conn.execute(
            "UPDATE research_file_paths SET blob_root=?,version_root=? WHERE id=1",
            (str(destination / "blobs"), str(destination / "versions")),
        )


def join(session, destination, ticket, progress=lambda _value: None, *, max_pages=100, seconds=20):
    """Replay an observed prefix; only an empty pull permits publication.

    Cancel/failure keeps the owned stage and durable cursor for a later explicit
    retry with the same endpoint/device/destination. It never changes active data.
    """
    if (
        not isinstance(destination, (str, Path))
        or not str(destination).strip()
        or type(max_pages) is not int
        or not 1 <= max_pages <= 100
        or not 0 < seconds <= 60
    ):
        raise ValueError("Invalid bootstrap destination or budget")
    destination = _safe_path(destination)
    if not destination.parent.is_dir() or destination.is_relative_to(session.workspace.path.parent):
        raise ValueError("Choose a new directory outside the active workspace")
    with session._job(), session.authorized(ticket) as (transport, token, identity, source_live):
        if local_binding(session.workspace.path) == identity:
            raise ValueError("Joining needs a newly issued device identity")
        expected = _spec(transport.base_url, identity, destination)
        digest = hashlib.sha256(_json(expected).encode()).hexdigest()
        stage = _safe_path(destination.parent / (".paperfact-join-" + digest))
        # An existing unrelated destination is rejected before creating a stage.
        if destination.exists() and not stage.is_dir():
            raise FileExistsError("The destination already exists")
        stage, spec = _stage(destination.parent, expected)
        work = stage / "workspace"
        if destination.exists():
            if work.exists() or not _receipt(destination / "papers.db", spec)["ready"]:
                raise FileExistsError("The destination is not this completed bootstrap")
            return {
                "state": "metadata_ready",
                "path": str(destination),
                **_receipt(destination / "papers.db", spec),
                "attachments": "unavailable",
            }
        if not work.exists():
            with tempfile.TemporaryDirectory(prefix=".initialize-", dir=stage) as temporary:
                initializing = Path(temporary) / "workspace"
                _initialize(initializing, spec)
                source_live()
                publish_directory(initializing, work)
        else:
            _receipt(work / "papers.db", spec)
        path = work / "papers.db"
        info = path.stat()
        file_identity = info.st_dev, info.st_ino

        def live():
            source_live()
            current = _safe_path(path).stat()
            if (current.st_dev, current.st_ino) != file_identity:
                raise ValueError("The bootstrap database was replaced")

        journal = GuardedJournal.attach_existing(path, **identity)
        journal.live = live
        client = SyncClient.attach_existing(
            journal,
            research_writer,
            order_writer=research_order_writer,
            projection_writer=research_projection_writer,
        )
        deadline, received = time.monotonic() + seconds, 0
        ready = False
        for _ in range(max_pages):
            live()
            events = transport.pull(token, after=client.status()["cursor"], limit=100)
            if any(
                event.get("operation", {}).get("device_id") == identity["device_id"]
                for event in events
            ):
                raise ValueError("Joining needs an unused device identity")
            result = client.receive(events)
            received += result["received"]
            with journal.transaction() as conn:
                conn.execute(
                    "UPDATE local_sync_bootstrap SET cursor=?,ready=? WHERE id=1",
                    (result["cursor"], int(not events)),
                )
            progress({"received": received, "cursor": result["cursor"], "stage": "joining"})
            if not events:
                ready = True
                break
            if time.monotonic() >= deadline:
                break
        live()
        cursor = client.status()["cursor"]
        if not ready:
            return {
                "state": "catching_up",
                "cursor": cursor,
                "path": str(destination),
                "received": received,
                "stage": str(stage),
                "attachments": "unavailable",
            }
        _register_final_paths(client, work, destination)
        source_live()
        ticket.publish(lambda: publish_directory(work, destination))
        return {
            "state": "metadata_ready",
            "cursor": cursor,
            "path": str(destination),
            "received": received,
            "attachments": "unavailable",
            "active_unchanged": True,
        }
