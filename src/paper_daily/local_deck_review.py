"""Explicit local proposal review with rollback of active deck files and SQL receipt."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sqlite3
import zipfile
from contextlib import closing, suppress
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from paper_daily import bundle_files, file_change, presentations, research_job_lock
from paper_daily.sync_blobs import _no_link
from paper_daily.sync_files import MAX_BODY, canonical_json


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _path(value):
    path = Path(value).absolute()
    for item in (path, *path.parents):
        _no_link(item)
    return path.resolve(strict=False)


def _native(path):
    info = _path(path).stat()
    if not info.st_ino:
        raise ValueError("Presentation storage has no reliable native identity")
    return [info.st_dev, info.st_ino]


def _slot(root, paper, mode):
    folder = _path(root) / _hash(paper.encode())[:24]
    return _path(folder / (mode + ".json"))


def _slot_data(path):
    if not path.exists():
        return {"version": None, "sha256": None, "deck": None}
    before = file_change.version(path)
    if before[2] > MAX_BODY:
        raise ValueError("Current presentation exceeds the bounded review size")
    data = path.read_bytes()
    if canonical_json(file_change.version(path)) != canonical_json(before):
        raise ValueError("Current presentation changed during review")
    value = json.loads(data)
    presentations.deck_from_dict(value)
    return {"version": before, "sha256": _hash(data), "deck": value}


def _witnesses(proposal):
    return [[str(path), version] for path, version in proposal.witnesses]


def prepare(service, record):
    from paper_daily import local_deck_proposals as catalog
    from paper_daily.research_lifecycle import parent_lifecycle

    read = catalog.read(
        service.path,
        record["proposal_id"],
        expected_native=service.identity,
        current=lambda: not service.closed,
    )
    if not read.current_parent:
        raise ValueError(
            "Original local paper lifecycle changed; keep/export the retained proposal"
        )
    if read.record != record:
        raise ValueError("Retained local proposal changed during explicit review")
    science = read.content
    paper = record["paper_id"]
    mode = science["deck"]["mode"]
    root = _path(service.presentation_root)
    slot = _slot(root, paper, mode)
    # Explicit verification may prepare its owned lock directory, never active data.
    root.mkdir(parents=True, exist_ok=True)
    _path(root)
    slot.parent.mkdir(parents=True, exist_ok=True)
    _path(slot.parent)
    current = _slot_data(slot)
    if current["deck"] is not None and (
        current["deck"]["paper_id"] != paper or current["deck"]["mode"] != mode
    ):
        raise ValueError("Current presentation belongs to another paper or slot")
    with closing(service._connect()) as conn:
        service._check(conn)
        catalog.assert_current_in(conn, read)
        parent = conn.execute("SELECT * FROM papers WHERE id=?", (paper,)).fetchone()
        if parent is None:
            raise ValueError("Original local paper was removed")
        title = parent["title"]
        token = parent_lifecycle(conn, "paper", paper)
        parent = dict(parent)
    source_hash = science["source_document_hash"]
    return {
        "apply": True,
        "editable": False,
        "original": None,
        "retained": science["deck"],
        "current": current["deck"],
        "source_hash": source_hash,
        "reason": "Verified local proposal; compare the current version before confirming Apply",
        "scope": {"kind": "paper", "id": paper},
        "parent_token": token,
        "parent_row": parent,
        "target": {"id": paper, "title": title, "slot": mode, "restoring": False},
        "requires_confirmation": True,
        "expected": {
            "local_proposal": record["proposal_id"],
            "files": _witnesses(read),
            "root": str(root),
            "root_native": _native(root),
            "folder_native": _native(slot.parent),
            "slot": str(slot),
            "current": current,
        },
    }


def _check(service, conn, data, proposal, rollback_key=None):
    from paper_daily import local_deck_proposals as catalog
    from paper_daily.research_lifecycle import parent_lifecycle

    service._check(conn)
    catalog.assert_current_in(conn, proposal)
    expected = data["expected"]
    paper = data["target"]["id"]
    root = _path(service.presentation_root)
    slot = _slot(root, paper, data["target"]["slot"])
    if (
        str(root) != expected["root"]
        or str(slot) != expected["slot"]
        or _native(root) != expected["root_native"]
        or _native(slot.parent) != expected["folder_native"]
    ):
        raise ValueError("Original presentation directory changed after review")
    if canonical_json(_witnesses(proposal)) != canonical_json(expected["files"]):
        raise ValueError("Original scientific proposal bytes changed after review")
    parent = conn.execute("SELECT * FROM papers WHERE id=?", (paper,)).fetchone()
    if (
        parent is None
        or dict(parent) != data["parent_row"]
        or parent_lifecycle(conn, "paper", paper) != data["parent_token"]
    ):
        raise ValueError("Displayed local paper changed; review again")
    actual = _slot_data(slot)
    if canonical_json(actual) != canonical_json(expected["current"]):
        restored = getattr(service, "_local_review_rollbacks", {}).get(rollback_key)
        if restored is None or canonical_json(actual) != canonical_json(restored):
            raise ValueError("Current presentation changed; review its latest version")
    return root, slot


def _remember_rollback(service, data, proposal, rollback_key):
    from paper_daily import local_deck_proposals as catalog

    with closing(service._connect()) as conn:
        service._check(conn)
        catalog.assert_current_in(conn, proposal)
        expected = data["expected"]
        root = _path(service.presentation_root)
        slot = _slot(root, data["target"]["id"], data["target"]["slot"])
        if (
            _native(root) != expected["root_native"]
            or _native(slot.parent) != expected["folder_native"]
        ):
            return
        actual, before = _slot_data(slot), expected["current"]
        if actual["sha256"] != before["sha256"] or actual["deck"] != before["deck"]:
            return
        if before["version"] is not None:
            if actual["version"] is None or tuple(actual["version"][:2]) != tuple(
                before["version"][:2]
            ):
                return
        elif actual["version"] is not None:
            return
        # Only our verified rollback may refresh native change metadata. Arbitrary
        # same-byte external writes and a replaced parent remain stale previews.
        values = getattr(service, "_local_review_rollbacks", {})
        values[rollback_key] = actual
        while len(values) > 16:
            del values[next(iter(values))]
        service._local_review_rollbacks = values


def apply(service, data, fingerprint, request_id, body, confirm_target):
    from paper_daily import local_deck_proposals as catalog
    from paper_daily.research_review import _setup

    if body is not None:
        raise ValueError("Edit the applied presentation in its canvas after source review")
    if not confirm_target:
        raise ValueError("Confirm the local target before applying retained slides")
    # An exact successful retry is a read, even after the current slot moved on.
    with closing(service._connect()) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "research_review_receipts" in tables:
            prior = conn.execute(
                "SELECT fingerprint,result FROM research_review_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise ValueError("Review retry changed its decision or draft")
                return json.loads(prior[1])
    proposal = catalog.read(
        service.path,
        data["id"],
        expected_native=service.identity,
        current=lambda: not service.closed,
    )
    from paper_daily.research_review import digest

    if digest(proposal.record) != data["record_hash"]:
        raise ValueError("Retained local proposal changed after the displayed review")
    science = proposal.content
    deck = presentations.deck_from_dict(copy.deepcopy(science["deck"]))
    deck.paper_id = data["target"]["id"]
    deck.deck_id = str(uuid5(NAMESPACE_URL, "paperfact.local.review:" + request_id))
    deck.edited = True
    root = _path(service.presentation_root)
    slot = _slot(root, deck.paper_id, deck.mode)
    additions = {}
    for key, image in science["image_bytes"].items():
        relative = slot.parent.relative_to(root) / "assets" / (_hash(image) + ".png")
        target = _path(root / relative)
        if target.exists() and target.read_bytes() != image:
            raise ValueError("Existing content-addressed slide image differs from its hash")
        additions[relative] = image
        for row in deck.figures:
            if row["id"] == key:
                row["asset"] = relative.name
    old = data["expected"]["current"]
    if old["deck"] is not None:
        history = (
            slot.parent.relative_to(root)
            / "history"
            / (deck.mode + "-review-" + old["sha256"] + ".json")
        )
        # History follows the maintained raw-deck JSON format, with a content key.
        history_bytes = slot.read_bytes()
        if _hash(history_bytes) != old["sha256"]:
            raise ValueError("Current presentation changed before history capture")
        target = _path(root / history)
        if target.exists() and target.read_bytes() != history_bytes:
            raise ValueError("Existing presentation history differs; preserve it before retry")
        additions[history] = history_bytes
    additions[slot.relative_to(root)] = canonical_json(deck.to_dict())
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_STORED) as archive:
        for path, value in additions.items():
            archive.writestr("files/" + path.as_posix(), value)
    archive_bytes.seek(0)
    lock = _path(slot.parent / ".deck-write.lock")
    with lock.open("ab"):
        pass
    rollback_key = (request_id, fingerprint)
    installation_started = False
    try:
        with research_job_lock.claim(lock, "deck-save", deck.mode) as acquired:
            if not acquired:
                raise ValueError(
                    "Another presentation save is running; keep the proposal and retry"
                )
            with (
                zipfile.ZipFile(archive_bytes) as archive,
                bundle_files.stage(root, archive, list(additions)) as staged,
                closing(service._connect()) as conn,
                conn,
            ):
                conn.execute("BEGIN IMMEDIATE")
                _check(service, conn, data, proposal, rollback_key)
                _setup(conn)
                prior = conn.execute(
                    "SELECT fingerprint,result FROM research_review_receipts WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if prior:
                    if prior[0] != fingerprint:
                        raise ValueError("Review retry changed its decision or draft")
                    return json.loads(prior[1])
                installation_started = True
                staged.install()
                if slot.read_bytes() != additions[slot.relative_to(root)]:
                    raise ValueError("Reviewed presentation changed during publication")
                catalog.assert_current_in(conn, proposal)
                service._check(conn)
                result = {"decision": "applied", "operation_id": None}
                service._receipt(conn, request_id, fingerprint, data, result)
                service._check(conn)
                getattr(service, "_local_review_rollbacks", {}).pop(rollback_key, None)
                return result
    except Exception:
        if installation_started:
            with suppress(ValueError, OSError, sqlite3.Error):
                _remember_rollback(service, data, proposal, rollback_key)
        raise
