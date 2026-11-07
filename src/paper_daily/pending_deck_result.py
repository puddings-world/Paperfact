"""Actual unsaved results, owned by the app rather than a disposable view.

No model calls or sender observations can activate a result through this module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock

from paper_daily.sync_files import canonical_json, closed, validate_closure


def _capture(outcome):
    from paper_daily import raw_deck_receipts
    from paper_daily.sync_deck_publication import DraftRetention

    if not isinstance(outcome, DraftRetention):
        raise ValueError("Only an actual producer retention outcome can be held")
    if outcome._capture is None:
        raise ValueError("Complete captured bytes are unavailable; keep the actual result")
    header, objects = raw_deck_receipts.decode(outcome._capture)
    if (
        header["raw"]["candidate_id"] != outcome.candidate_id
        or json.loads(header["raw"]["deck"]) != outcome.deck.to_dict()
        or header["evidence"] != outcome.evidence
    ):
        raise ValueError("Actual result differs from its immutable captured bytes")
    return header, objects


def _research_snapshot(deck, evidence):
    """Keep all scientific fields; omit only declared local execution/cache data.

    Unsupported fields refuse export rather than silently settling a lossy copy.
    The receiver never follows a retained filename or imports writer authority.
    """
    from paper_daily.presentations import deck_from_dict
    from paper_daily.sync_deck_files import DECK_FIELDS, FIGURE_FIELDS, SOURCE_FIELDS, _source
    from paper_daily.sync_files import MAX_BODY

    def figures(rows):
        if not isinstance(rows, list) or len(rows) > 256:
            raise ValueError("Recovery figure catalog exceeds its bound")
        result = []
        for row in rows:
            if not isinstance(row, dict) or set(row) - FIGURE_FIELDS - {
                "file",
                "cache_key",
                "asset",
            }:
                raise ValueError("Unsupported figure metadata; keep the unsaved result")
            item = {key: deepcopy(value) for key, value in row.items() if key in FIGURE_FIELDS}
            item["asset_id"] = item["id"]
            _source(item, figure=True)
            result.append(item)
        return result

    def sources(rows):
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("Recovery sources exceed their bound")
        for row in rows:
            if not isinstance(row, dict) or set(row) - SOURCE_FIELDS:
                raise ValueError("Unsupported source metadata; keep the unsaved result")
            _source(row)
        return deepcopy(rows)

    value = deepcopy(deck)
    closed(value, DECK_FIELDS)
    generation = value["generation"]
    if not isinstance(generation, dict) or set(generation) - {
        "inputs",
        "backend",
        "model",
        "profile",
        "request_id",
    }:
        raise ValueError("Unsupported execution metadata; keep the unsaved result")
    value["generation"] = {
        key: item
        for key, item in generation.items()
        if key in {"inputs", "backend", "model"} and item is not None
    }
    value["figures"] = figures(value["figures"])
    value["sources"] = sources(value["sources"])
    deck_from_dict(value)
    evidence = deepcopy(evidence)
    if evidence is not None:
        if not isinstance(evidence, dict) or set(evidence) - {
            "paper",
            "sources",
            "figures",
            "coverage",
            "source_hash",
        }:
            raise ValueError("Unsupported evidence metadata; keep the unsaved result")
        evidence["sources"] = sources(evidence["sources"])
        if "figures" in evidence:
            evidence["figures"] = figures(evidence["figures"])
        if "paper" in evidence:
            paper = evidence["paper"]
            if not isinstance(paper, dict) or set(paper) - {
                "id",
                "title",
                "venue",
                "year",
                "authors_json",
            }:
                raise ValueError("Unsupported paper metadata; keep the unsaved result")
        if len(canonical_json(evidence)) > MAX_BODY:
            raise ValueError("Recovery evidence exceeds its bound")
    if len(canonical_json(value)) > MAX_BODY:
        raise ValueError("Recovery deck exceeds its bound")
    return {"deck": value, "evidence": evidence}


def _export_bytes(outcome):
    header, objects = _capture(outcome)
    value = {
        "format": "paperfact.pending-deck",
        "version": 1,
        "closure": header["closure"],
        "research": _research_snapshot(json.loads(header["raw"]["deck"]), header["evidence"]),
        "data": {
            sha: base64.b64encode(data).decode("ascii") for sha, data in sorted(objects.items())
        },
    }
    data = canonical_json(value)
    read_export(data)
    return data


def read_export(data):
    """Read only a bounded, pathless recovery snapshot; never restore a writer."""
    from paper_daily import raw_deck_receipts
    from paper_daily.raw_deck_closure import validate_row
    from paper_daily.sync_deck_files import validate_png

    value = raw_deck_receipts._load(data)
    closed(value, {"format", "version", "closure", "data", "research"})
    if (
        value["format"] != "paperfact.pending-deck"
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("Unsupported pending deck recovery format")
    payload, inventory = validate_row(value["closure"])
    if not isinstance(value["data"], dict):
        raise ValueError("Recovery bytes require a closed object map")
    expected = {}
    for row in [payload["body"], *payload["assets"], *inventory["images"]]:
        prior = expected.setdefault(row["sha256"], row["size"])
        if prior != row["size"]:
            raise ValueError("Conflicting recovery object sizes")
    if set(value["data"]) != set(expected):
        raise ValueError("Missing or undeclared recovery objects")
    objects = {}
    for sha, size in expected.items():
        encoded = value["data"][sha]
        if not isinstance(encoded, str) or len(encoded) > ((size + 2) // 3) * 4:
            raise ValueError("Invalid recovery object encoding")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Invalid recovery object encoding") from exc
        if len(decoded) != size or hashlib.sha256(decoded).hexdigest() != sha:
            raise ValueError("Recovery bytes differ from their manifest")
        objects[sha] = decoded
    body = validate_closure(payload, lambda row: objects[row["sha256"]])
    images = {}
    for row in inventory["images"]:
        image = objects[row["sha256"]]
        validate_png(image)
        images[row["id"]] = image
    portable_evidence = next(
        (
            json.loads(objects[row["sha256"]])
            for row in payload["assets"]
            if row["role"] == "evidence"
        ),
        None,
    )
    from paper_daily.raw_deck_closure import normalized_deck

    research = value["research"]
    closed(research, {"deck", "evidence"})
    if _research_snapshot(research["deck"], research["evidence"]) != research:
        raise ValueError("Recovery contains local execution/cache fields")
    if normalized_deck(research["deck"], payload["paper_id"]) != body["deck"]:
        raise ValueError("Recovery scientific content differs from its portable deck")
    if {row["id"] for row in research["deck"]["figures"]} != set(images):
        raise ValueError("Recovery figure catalog differs from its captured images")
    evidence = research["evidence"]
    expected_evidence = (
        None
        if evidence is None
        else {
            "version": 1,
            **{key: evidence[key] for key in ("sources", "coverage", "source_hash")},
        }
    )
    if expected_evidence != portable_evidence:
        raise ValueError("Recovery evidence differs from its portable snapshot")
    return {
        "deck": research["deck"],
        "evidence": evidence,
        "image_bytes": images,
        "publish": False,
        "sync": False,
        "requires_explicit_review": True,
    }


class PendingDeckResults:
    """Thread-safe lifetime owner. Explicit actions settle exactly one result."""

    def __init__(self):
        self._lock = RLock()
        self._items = {}
        self._contexts = {}
        self._working = set()

    @property
    def pending(self):
        with self._lock:
            return bool(self._items)

    def items(self):
        with self._lock:
            return list(self._items.items())

    def hold(self, outcome):
        from paper_daily.local_rescue_import import LocalRetention, context
        from paper_daily.sync_deck_publication import DraftRetention

        local = isinstance(outcome, LocalRetention)
        if not isinstance(outcome, (DraftRetention, LocalRetention)) or outcome.durable:
            raise ValueError("Only an actual unsaved result needs pending disposition")
        if local:
            owner = context(outcome)
            source = hashlib.sha256(canonical_json(owner)).hexdigest()
            label = f"{Path(owner['database']).name} · local · {source[:8]}"
            context = owner["database"] + "\nLocal-only workspace"
        elif outcome._capture is not None:
            header, _objects = _capture(outcome)
            owner = header["owner"]
            source = hashlib.sha256(canonical_json(owner)).hexdigest()
            label = (
                f"{Path(owner['database']).name} · "
                f"{owner['workspace_id']}/{owner['device_id']} · {source[:8]}"
            )
            context = (
                f"{owner['database']}\nWorkspace: {owner['workspace_id']}"
                f"\nDevice: {owner['device_id']}"
            )
        else:
            source = str(id(outcome))
            label = context = "Original workspace unavailable · " + outcome.candidate_id
        key = outcome.candidate_id + ":" + source
        with self._lock:
            prior = self._items.get(key)
            if (
                prior is not None
                and prior is not outcome
                and (
                    type(prior) is not type(outcome)
                    or (not local and prior._capture != outcome._capture)
                    or prior.deck.to_dict() != outcome.deck.to_dict()
                    or prior.evidence != outcome.evidence
                )
            ):
                raise ValueError("A different result cannot replace pending research")
            self._items[key] = outcome
            self._contexts[key] = (label, context)
        return key

    def label(self, key):
        with self._lock:
            return self._contexts.get(key, ("", ""))[0]

    def context(self, key):
        with self._lock:
            return self._contexts.get(key, ("", ""))[1]

    def _begin(self, key):
        with self._lock:
            if key in self._working:
                raise ValueError("This result already has an action in progress")
            outcome = self._items[key]
            self._working.add(key)
            return outcome

    def retry(self, key):
        from paper_daily.raw_deck_closure import retry_retention

        outcome = self._begin(key)
        try:
            from paper_daily import local_rescue_import

            result = (
                local_rescue_import.retry(outcome)
                if isinstance(outcome, local_rescue_import.LocalRetention)
                else retry_retention(outcome)
            )
            if result.candidate_id != outcome.candidate_id or result.deck is not outcome.deck:
                raise ValueError("Retry returned a different research result")
            with self._lock:
                if result.durable:
                    del self._items[key]
                    del self._contexts[key]
                else:
                    self._items[key] = result
            return result
        finally:
            with self._lock:
                self._working.discard(key)

    def export(self, key, destination):
        outcome = self._begin(key)
        target = Path(destination)
        try:
            from paper_daily import local_rescue_import

            if isinstance(outcome, local_rescue_import.LocalRetention):
                exported = local_rescue_import.export(outcome, target)
                with self._lock:
                    del self._items[key]
                    del self._contexts[key]
                return exported
            data = _export_bytes(outcome)
            # Exclusive creation: never truncate earlier user research or follow an
            # existing destination symlink. A failed write leaves the result held.
            with target.open("xb") as stream:
                native = os.fstat(stream.fileno())
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            before = target.lstat()
            if (before.st_dev, before.st_ino) != (
                native.st_dev,
                native.st_ino,
            ) or target.is_symlink():
                raise ValueError("Recovery destination changed before verification")
            restored = target.read_bytes()
            after = target.lstat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) or restored != data:
                raise ValueError("Recovery destination changed while verifying")
            read_export(restored)
            with self._lock:
                del self._items[key]
                del self._contexts[key]
            return target
        finally:
            with self._lock:
                self._working.discard(key)

    def discard(self, key, *, expected):
        with self._lock:
            if key in self._working or self._items.get(key) is not expected:
                raise ValueError("Pending result changed; review it again")
            del self._items[key]
            del self._contexts[key]
