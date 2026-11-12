"""Normal read/export access to detached decks, without reviving publication authority."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from copy import deepcopy

from paper_daily.sync_slide_recovery import (
    _check_descriptor,
    _descriptor,
    _json,
    _load,
    _path,
    _read_object,
    _represented_deck,
)

TABLE = "research_legacy_deck_recovery"
COLUMNS = "paper_id slot request_id parent_token deck"
MAX_JSON = 8 * 1024**2


def validate_slot(row):
    from uuid import UUID

    from paper_daily.presentations import MODES

    if not isinstance(row, dict) or set(row) != set(COLUMNS.split()):
        raise ValueError("Invalid recovered current deck slot")
    if not isinstance(row["paper_id"], str) or not 0 < len(row["paper_id"]) <= 1024:
        raise ValueError("Invalid recovered paper identity")
    if row["slot"] not in MODES or str(UUID(row["request_id"])) != row["request_id"]:
        raise ValueError("Invalid recovered deck slot identity")
    if not isinstance(row["parent_token"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", row["parent_token"]
    ):
        raise ValueError("Invalid recovered parent lifecycle")
    value = _load(row["deck"])
    _check_descriptor(value, MAX_JSON)
    return value


def legacy_snapshot(row, receipts, read):
    """A separately captured current slot selects content; receipt status never does."""
    from paper_daily import presentations, sync_slide_recovery

    descriptor = validate_slot(row)
    receipt = receipts.get(row["request_id"])
    if receipt is None:
        raise ValueError("Recovered current deck lacks its retained closure")
    record = sync_slide_recovery.read_retained(receipt, read)
    if record["parent_token"] != row["parent_token"]:
        raise ValueError("Recovered slot differs from its captured parent lifecycle")
    if record["binding"] is not None or (record["paper_id"], record["mode"]) != (
        row["paper_id"],
        row["slot"],
    ):
        raise ValueError("Recovered current deck belongs to another owner")
    data = read(descriptor)
    if _descriptor(data) != descriptor:
        raise ValueError("Recovered current deck hash differs")
    raw = _load(data)
    choices = {_json(item) for item in (record["original"], record["result"]) if item is not None}
    if not _represented_deck(raw, choices):
        raise ValueError("Recovered current deck differs from its captured content")
    deck = presentations.deck_from_dict(raw)
    manifest = sync_slide_recovery.validate_manifest(receipt)
    return deck, record["evidence"], manifest["figures"], manifest["sources"]


def restore_legacy(stage, slots, receipts):
    """Project exactly captured saved slots, not late results or old job capabilities."""
    from paper_daily.slide_layout import used_figures

    for row in slots.values():
        deck, evidence, figures, _sources = legacy_snapshot(
            row, receipts, lambda item: _read_object(stage / "objects", item)
        )
        folder = stage / "presentations" / hashlib.sha256(deck.paper_id.encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (deck.mode + ".json")
        if target.exists():
            raise ValueError("Duplicate restored current deck slot")
        for figure in deck.figures:
            if figure["id"] not in used_figures(deck):
                continue
            descriptor = figures.get(figure["id"])
            if descriptor is None:
                raise ValueError("Current deck figure lacks captured bytes")
            assets = folder / "assets"
            assets.mkdir(exist_ok=True)
            name = descriptor["sha256"] + ".png"
            (assets / name).write_bytes(_read_object(stage / "objects", descriptor))
            figure["asset"] = name
        # Logical evidence identity is preserved even when unknown.
        evidence_dir = folder / "recovered-evidence"
        evidence_dir.mkdir(exist_ok=True)
        evidence_data = _json(evidence)
        (evidence_dir / (_descriptor(evidence_data)["sha256"] + ".json")).write_bytes(evidence_data)
        target.write_bytes(_json(deck.to_dict()))


def _records(database):
    database = _path(database)
    if not database.exists():
        return None
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='recovery_identity'"
        ).fetchone():
            return None
        identity = conn.execute("SELECT backup_id FROM recovery_identity WHERE id=1").fetchone()
        if not identity:
            raise ValueError("Detached workspace identity is unavailable")
        rows = conn.execute(
            "SELECT table_name,data FROM recovery_records WHERE table_name IN "
            "('research_paper_identity','research_file_applied',"
            "'research_slide_revision_recovery','research_legacy_deck_recovery','research_observed_current_deck_recovery',"
            "'research_parent_lifecycle') LIMIT 10001"
        ).fetchall()
    if len(rows) > 10000 or sum(len(raw.encode()) for _, raw in rows) > 256 * 1024**2:
        raise ValueError("Detached deck metadata exceeds its bound")
    return identity[0], [(name, _load(raw)) for name, raw in rows]


def _fingerprint(path):
    value = _path(path).stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _verified(root, descriptor):
    data = _read_object(root, descriptor)
    if _descriptor(data) != {key: descriptor[key] for key in ("sha256", "size")}:
        raise ValueError("Restored research asset hash differs")
    return data


def _snapshot(database, paper_id, slot, rows):
    from paper_daily import presentations, sync_slide_recovery
    from paper_daily.sync_files import validate_closure
    from paper_daily.sync_schema_v2 import canonical_operation

    roots = database.parent / "objects"
    portable = {
        row["sync_id"]
        for name, row in rows
        if name == "research_paper_identity" and row["local_id"] == paper_id
    }
    applied = []
    for name, row in rows:
        if name != "research_file_applied":
            continue
        operation = _load(row["operation"])
        canonical_operation(operation)
        payload = operation["payload"]
        if payload["paper_id"] in portable and payload["slot"] == slot:
            applied.append(payload)
    legacy = [
        row
        for name, row in rows
        if name == TABLE and (row["paper_id"], row["slot"]) == (paper_id, slot)
    ]
    observed = [
        row
        for name, row in rows
        if name == "research_observed_current_deck_recovery"
        and (row["paper_id"], row["slot"]) == (paper_id, slot)
    ]
    if len(applied) + len(legacy) + len(observed) != 1:
        raise ValueError("Restored deck has no unique retained owner")
    if observed:
        from paper_daily.proposal_recovery_current import snapshot

        parents = {
            row["entity_id"]: row
            for name, row in rows
            if name == "research_parent_lifecycle" and row["kind"] == "paper"
        }
        parent = parents.get(paper_id)
        if not parent or not parent["active"] or parent["token"] != observed[0]["parent_token"]:
            raise ValueError("Observed manual deck belongs to a retired paper")
        return snapshot(observed[0], lambda item: _verified(roots, item))
    if legacy:
        parents = {
            row["entity_id"]: row
            for name, row in rows
            if name == "research_parent_lifecycle" and row["kind"] == "paper"
        }
        parent = parents.get(paper_id)
        if parent is None or not parent["active"] or parent["token"] != legacy[0]["parent_token"]:
            raise ValueError("Recovered legacy slot belongs to a different paper lifecycle")
        receipts = {
            row["request_id"]: row for name, row in rows if name == sync_slide_recovery.TABLE
        }
        deck, evidence, figures, sources = legacy_snapshot(
            legacy[0], receipts, lambda item: _verified(roots, item)
        )
        from paper_daily.slide_layout import used_figures

        figures = {key: row for key, row in figures.items() if key in used_figures(deck)}
        for figure in deck.figures:
            if figure["id"] in figures:
                figure["asset"] = figures[figure["id"]]["sha256"] + ".png"
        return deck, evidence, figures, sources
    payload = applied[0]
    body = validate_closure(payload, lambda item: _verified(roots, item))
    raw = deepcopy(body["deck"])
    raw["paper_id"] = paper_id
    assets = {row["id"]: row for row in payload["assets"]}
    figures = {}
    for figure in raw["figures"]:
        descriptor = assets[figure.pop("asset_id")]
        figures[figure["id"]] = {key: descriptor[key] for key in ("sha256", "size")}
        figure["asset"] = descriptor["sha256"] + ".png"
    evidence = (
        _load(_verified(roots, assets[body["evidence_asset"]])) if body["evidence_asset"] else None
    )
    hashes = {item.get("document_hash") for item in raw["sources"] + raw["figures"]}
    hashes.add(payload["source_document_hash"])
    hashes.update(item["sha256"] for item in payload["input_versions"]["documents"])
    sources = [{"sha256": digest} for digest in sorted(hashes - {None})]
    return presentations.deck_from_dict(raw), evidence, figures, sources


def load(database, paper_id, slot):
    """Return (detached workspace, exact saved deck), without opening a live client."""
    from paper_daily import presentations

    if slot not in presentations.MODES:
        raise ValueError("Invalid recovered deck slot")
    database = _path(database)
    original_identity = _fingerprint(database)[:2] if database.exists() else None
    metadata = _records(database)
    if metadata is None:
        return False, None
    folder = database.parent / "presentations" / hashlib.sha256(paper_id.encode()).hexdigest()[:24]
    location = _path(folder / (slot + ".json"))
    if not location.exists():
        return True, None
    if location.stat().st_size > MAX_JSON:
        raise ValueError("Restored deck exceeds its size bound")
    saved_stat = _fingerprint(location)
    actual = presentations.deck_from_dict(_load(location.read_bytes()))
    expected, evidence, figures, sources = _snapshot(database, paper_id, slot, metadata[1])
    if actual.to_dict() != expected.to_dict():
        raise ValueError("Restored saved deck differs from its retained provenance")
    if _fingerprint(location) != saved_stat:
        raise ValueError("Restored saved deck changed while opening")
    stat = database.stat()
    if (stat.st_dev, stat.st_ino) != original_identity:
        raise ValueError("Recovered workspace changed while opening")
    actual._recovery_deck = {
        "saved_stat": saved_stat,
        "database": database,
        "identity": (stat.st_dev, stat.st_ino),
        "backup": metadata[0],
        "folder": folder,
        "saved": actual.to_dict(),
        "evidence": evidence,
        "figures": figures,
        "sources": sources,
    }
    actual._file_observation = {
        "recovery_readonly": True,
        "database": str(database),
        "backup_id": metadata[0],
    }
    actual._recovery_capabilities = {"read": True, "export": True, "publish": False, "retry": False}
    for identity in figures:
        figure_bytes(actual, identity)
    return True, actual


def _binding(deck):
    binding = getattr(deck, "_recovery_deck", None)
    if binding is None:
        raise ValueError("No recovered deck binding")
    database = _path(binding["database"])
    stat = database.stat()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        identity = conn.execute("SELECT backup_id FROM recovery_identity WHERE id=1").fetchone()
    if (
        (stat.st_dev, stat.st_ino) != binding["identity"]
        or not identity
        or identity[0] != binding["backup"]
    ):
        raise ValueError("Recovered deck workspace changed; reopen the deck")
    location = _path(binding["folder"] / (deck.mode + ".json"))
    if _fingerprint(location) != binding["saved_stat"]:
        raise ValueError("Recovered saved deck changed; reopen the deck")
    if (deck.paper_id, deck.mode, deck.deck_id, deck.source_hash) != tuple(
        binding["saved"][key] for key in ("paper_id", "mode", "deck_id", "source_hash")
    ):
        raise ValueError("Recovered deck identity differs")
    return binding


def figure_bytes(deck, identity):
    from paper_daily.sync_deck_files import validate_png

    binding = _binding(deck)
    descriptor = binding["figures"].get(identity)
    if descriptor is None:
        raise ValueError("Figure is outside the recovered deck closure")
    path = _path(binding["folder"] / "assets" / (descriptor["sha256"] + ".png"))
    if path.stat().st_size != descriptor["size"]:
        raise ValueError("Recovered PNG size differs")
    data = path.read_bytes()
    if _descriptor(data) != descriptor:
        raise ValueError("Recovered PNG hash differs")
    validate_png(data)
    return data


def evidence(deck):
    binding = _binding(deck)
    if binding["evidence"] is None:
        raise ValueError(
            "Restored deck has no retained evidence; current research was not substituted"
        )
    return deepcopy(binding["evidence"])


def document_status(deck):
    """Historical bytes and current reader alias are separate, explicit states."""
    binding = _binding(deck)
    result = []
    current = (
        binding["database"].parent
        / "pdf"
        / (re.sub(r"[^A-Za-z0-9._-]", "_", deck.paper_id) + ".pdf")
    )
    current_digest = None
    if current.exists():
        _path(current)
        if current.stat().st_size <= 150 * 1024**2:
            current_digest = hashlib.sha256(current.read_bytes()).hexdigest()
    for row in binding["sources"]:
        source = _path(binding["database"].parent / "objects" / row["sha256"])
        status = "missing"
        if source.exists():
            status = "corrupt"
            if (
                source.stat().st_size <= 150 * 1024**2
                and hashlib.sha256(source.read_bytes()).hexdigest() == row["sha256"]
            ):
                status = "available"
        result.append(
            {
                "sha256": row["sha256"],
                "historical": status,
                "current_matches": current_digest == row["sha256"] if current_digest else None,
            }
        )
    return {
        "input_digest_known": bool(re.fullmatch(r"[0-9a-f]{64}", deck.source_hash)),
        "documents": result,
    }


def assert_writable(database, paper_id, slot):
    metadata = _records(database)
    if metadata is not None:
        raise ValueError(
            "This recovered deck is read-only; an explicit editable copy is required "
            "before saving or using AI"
        )


def export_snapshot(deck):
    """Keep verified pixels in the export job; later file changes cannot blank pages."""
    binding = _binding(deck)
    images = {identity: figure_bytes(deck, identity) for identity in binding["figures"]}
    frozen = deepcopy(deck)
    frozen._revision_figures = images
    # The export snapshot contains pixels, not a live filesystem reader. Its
    # read-only observation remains, so it still cannot acquire write authority.
    del frozen._recovery_deck
    return frozen
