"""Observed canonical manual slots, content only; never a producer/job receipt.

Exact JSON remains archive-only. Dormant figure metadata is retained without
following its device paths. Used figures require actual canonical saved assets.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import local_deck_proposals as local
from paper_daily import presentations
from paper_daily.proposal_recovery_primary import _parent
from paper_daily.slide_layout import used_figures
from paper_daily.sync_deck_files import validate_png
from paper_daily.sync_files import canonical_json, closed, digest, text
from paper_daily.sync_legacy_sources import validate_pdf
from paper_daily.sync_slide_recovery import _json, _represented_deck

TABLE = "research_observed_current_deck_recovery"
COLUMNS = "paper_id slot parent_token manifest_json"
MAX_JSON = 8 * 1024**2
MAX_IMAGES = 64 * 1024**2
MAX_ORIGINALS = 512 * 1024**2
MAX_SLOTS = 2000
MAX_TOTAL = 768 * 1024**2
_SEAL = object()


def _load(data):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate observed-current JSON field")
            value[key] = item
        return value

    return json.loads(
        data,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
    )


def _descriptor(data):
    return dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _desc(row, limit):
    closed(row, ("sha256", "size"))
    digest(row["sha256"])
    if type(row["size"]) is not int or not 0 < row["size"] <= limit:
        raise ValueError("Observed-current object exceeds its bound")


def validate(row):
    closed(row, COLUMNS.split())
    text(row["paper_id"], 1024)
    if row["slot"] not in presentations.MODES or not isinstance(row["parent_token"], str):
        raise ValueError("Invalid observed-current slot")
    if not re.fullmatch("[0-9a-f]{32}", row["parent_token"]):
        raise ValueError("Observed current requires original parent lifetime")
    text(row["manifest_json"], MAX_JSON)
    value = _load(row["manifest_json"])
    closed(value, ("version", "input_provenance", "body", "figures", "evidence", "originals"))
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unknown observed-current version")
    if value["input_provenance"] != "unknown":
        raise ValueError("Observed manual content cannot assert producer provenance")
    _desc(value["body"], MAX_JSON)
    if not isinstance(value["figures"], dict) or len(value["figures"]) > 128:
        raise ValueError("Invalid observed-current figure closure")
    for identity, descriptor in value["figures"].items():
        text(identity, 300)
        _desc(descriptor, 8_000_000)
    if sum(item["size"] for item in value["figures"].values()) > MAX_IMAGES:
        raise ValueError("Observed current figures exceed 64 MiB")
    if value["evidence"] is not None:
        _desc(value["evidence"], MAX_JSON)
    if not isinstance(value["originals"], list) or len(value["originals"]) > 16:
        raise ValueError("Observed current originals exceed 16 PDFs")
    for item in value["originals"]:
        _desc(item, 150 * 1024**2)
    if (
        len({item["sha256"] for item in value["originals"]}) != len(value["originals"])
        or sum(item["size"] for item in value["originals"]) > MAX_ORIGINALS
    ):
        raise ValueError("Observed current original closure is duplicate or oversized")
    return value


def references(row):
    value = validate(row)
    return [
        value["body"],
        *value["figures"].values(),
        *([value["evidence"]] if value["evidence"] else []),
        *value["originals"],
    ]


def _hashes(raw, evidence):
    rows = [*raw["sources"], *raw["figures"]]
    if evidence is not None:
        rows += [*evidence.get("sources", []), *evidence.get("figures", [])]
    result = {item.get("document_hash") for item in rows} - {None}
    for value in result:
        digest(value)
    if len(result) > 16:
        raise ValueError("Too many observed original references")
    return result


def read(row, read_blob):
    value = validate(row)

    def verified(descriptor):
        data = read_blob(descriptor)
        if not isinstance(data, bytes) or _descriptor(data) != descriptor:
            raise ValueError("Observed-current object bytes changed")
        return data

    raw = _load(verified(value["body"]))
    deck = presentations.deck_from_dict(raw)
    if (deck.paper_id, deck.mode) != (row["paper_id"], row["slot"]):
        raise ValueError("Observed-current saved content has wrong paper/slot")
    if not _represented_deck(raw, {_json(deck.to_dict())}):
        raise ValueError("Saved manual fields cannot be represented without loss")
    figures = {}
    catalog = {item["id"]: item for item in raw["figures"]}
    required = used_figures(deck)
    declared = {identity for identity, item in catalog.items() if item.get("asset")}
    if set(value["figures"]) != declared or not required <= declared:
        raise ValueError("Saved current has a missing/extra asset closure")
    for identity, descriptor in value["figures"].items():
        if catalog[identity]["asset"] != descriptor["sha256"] + ".png":
            raise ValueError("Saved current asset name/hash mismatch")
        data = verified(descriptor)
        validate_png(data)
        figures[identity] = data
    evidence = _load(verified(value["evidence"])) if value["evidence"] else None
    if evidence is not None and (
        not isinstance(evidence, dict)
        or evidence.get("source_hash") != deck.source_hash
        or not isinstance(evidence.get("sources"), list)
        or not isinstance(evidence.get("figures", []), list)
    ):
        raise ValueError("Saved evidence differs from observed manual deck")
    if evidence is not None:
        payload = {key: item for key, item in evidence.items() if key != "source_hash"}
        if hashlib.sha256(_json(payload)).hexdigest() != deck.source_hash:
            raise ValueError("Saved evidence input digest differs from its actual content")
    if _hashes(raw, evidence) != {item["sha256"] for item in value["originals"]}:
        raise ValueError("Observed-current originals differ from exact saved references")
    for descriptor in value["originals"]:
        validate_pdf(verified(descriptor))
    return dict(
        raw=raw,
        deck=deck,
        evidence=evidence,
        images=figures,
        input_provenance="unknown",
        publish=False,
    )


def _read(path, maximum, witnessed):
    path = local._path(path)
    before = local.file_change.version(path)
    if before[2] > maximum:
        raise ValueError("Observed-current file exceeds its bound")
    with path.open("rb") as stream:
        if local.file_change.version(path, stream=stream) != before:
            raise ValueError("Observed-current file changed before read")
        data = stream.read(maximum + 1)
        if local.file_change.version(path, stream=stream) != before:
            raise ValueError("Observed-current file changed during read")
    if len(data) != before[2] or local.file_change.version(path) != before:
        raise ValueError("Observed-current file changed after read")
    witnessed.append((path, before))
    return data


def _tree(database):
    root = database.parent / "presentations"
    local._no_link(root)
    if not root.exists():
        return ()
    paths = [local._path(root)]
    for item in root.rglob("*"):
        if len(paths) >= MAX_SLOTS * 256:
            raise ValueError("Observed-current native entry inventory exceeds its bound")
        paths.append(local._path(item))
    return tuple((str(path), local._native(path)) for path in sorted(paths))


def _roster(database):
    root = database.parent / "presentations"
    if not root.exists():
        local._no_link(root)
        return ()
    local._path(root)
    # Only canonical slots, never received paths/history or arbitrary nested files.
    return tuple(
        sorted(
            local._path(path) for path in root.glob("*/*.json") if path.stem in presentations.MODES
        )
    )


@dataclass(frozen=True)
class Observation:
    database: Path
    native: tuple
    _rows: tuple = field(repr=False)
    _objects: tuple = field(repr=False)
    _aliases: tuple = field(repr=False)
    _parents: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    _roster: tuple = field(repr=False)
    _tree: tuple = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def rows(self):
        return [_load(value) for value in self._rows]

    @property
    def objects(self):
        return dict(self._objects)

    @property
    def aliases(self):
        return dict(self._aliases)

    def check(self, *, current=lambda: True):
        if self._seal is not _SEAL:
            raise ValueError("Use sealed actual manual-content observation")
        local._check(current)
        if local._native(self.database) != self.native:
            raise ValueError("Observed-current original database changed")
        if _tree(self.database) != self._tree or _roster(self.database) != self._roster:
            raise ValueError("Observed-current slot roster changed")
        for identity, paper_json, token in self._parents:
            paper, now = _parent(self.database, self.native, identity)
            if canonical_json(paper).decode() != paper_json or now != token:
                raise ValueError("Observed-current parent changed")
        local._files_current(self._files)
        local._check(current)
        return True


def collect(
    database,
    snapshot,
    temporary,
    *,
    expected_native,
    represented=None,
    source_resolver=None,
    source_objects=None,
    current=lambda: True,
):
    database, native = local._path(database), local._expected(expected_native)
    local._check(current)
    if local._native(database) != native:
        raise ValueError("Original observed-current database was replaced before reading")
    tree = _tree(database)
    roster = _roster(database)
    rows, objects, aliases, parents, files, total = [], {}, {}, [], [], 0
    staging = local._path(temporary) / "observed-current-objects"
    local._no_link(staging)
    staging.mkdir(exist_ok=True)
    local._path(staging)

    def stage(data):
        nonlocal total
        descriptor = _descriptor(data)
        if descriptor["sha256"] not in objects:
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError("Observed-current content exceeds 768 MiB")
            path = staging / descriptor["sha256"]
            local._no_link(path)
            if path.exists():
                local._path(path)
                if path.read_bytes() != data:
                    raise ValueError("Observed-current temporary object changed")
            else:
                path.write_bytes(data)
            objects[descriptor["sha256"]] = path
        return descriptor

    for path in roster:
        if represented and path in represented:
            continue  # Existing typed revisions remain governed by their strict validator.
        if len(rows) >= MAX_SLOTS:
            raise ValueError("Observed-current roster exceeds 2000 slots")
        local._check(current)
        raw_bytes = _read(path, MAX_JSON, files)
        raw = _load(raw_bytes)
        deck = presentations.deck_from_dict(raw)
        paper, token = _parent(database, native, deck.paper_id)
        if (
            local._paper(snapshot, deck.paper_id) != paper
            or local.parent_lifecycle(snapshot, "paper", deck.paper_id) != token
        ):
            raise ValueError("Observed-current snapshot differs from source parent")
        expected = (
            database.parent
            / "presentations"
            / hashlib.sha256(deck.paper_id.encode()).hexdigest()[:24]
            / (deck.mode + ".json")
        )
        if path != expected:
            raise ValueError("Saved manual slot is outside its canonical paper scope")
        figures = {}
        for item in raw["figures"]:
            asset = item.get("asset")
            if asset:
                if not isinstance(asset, str) or not re.fullmatch("[0-9a-f]{64}\\.png", asset):
                    raise ValueError("Saved manual asset must be a canonical immutable PNG")
                figures[item["id"]] = stage(_read(path.parent / "assets" / asset, 8_000_000, files))
        evidence = None
        if re.fullmatch("[0-9a-f]{64}", deck.source_hash):
            evidence_path = path.parent / "evidence" / (deck.source_hash + ".json")
            local._no_link(evidence_path)
            if evidence_path.exists():
                evidence = stage(_read(evidence_path, MAX_JSON, files))
        evidence_data = _load(objects[evidence["sha256"]].read_bytes()) if evidence else None
        originals = []
        for sha in sorted(_hashes(raw, evidence_data)):
            location = (source_objects or {}).get(sha)
            if location is None and source_resolver is not None:
                descriptor = source_resolver.require(sha)
                location = source_resolver.objects[descriptor["sha256"]]
            if location is None:
                raise ValueError("Saved manual original PDF is unavailable")
            originals.append(stage(_read(location, 150 * 1024**2, files)))
        value = dict(
            version=1,
            input_provenance="unknown",
            body=stage(raw_bytes),
            figures=figures,
            evidence=evidence,
            originals=originals,
        )
        row = dict(
            paper_id=deck.paper_id,
            slot=deck.mode,
            parent_token=token,
            manifest_json=canonical_json(value).decode(),
        )
        read(row, lambda descriptor: objects[descriptor["sha256"]].read_bytes())
        for location, version in files:
            aliases[location] = _descriptor(location.read_bytes())["sha256"], version[2]
        lock = path.parent / ".deck-write.lock"
        local._no_link(lock)
        if lock.exists():
            data = _read(lock, MAX_JSON, files)
            aliases[lock] = _descriptor(data)["sha256"], len(data)
        jobs = path.parent / ".research-jobs"
        local._no_link(jobs)
        if jobs.exists():
            local._path(jobs)
            for job_lock in jobs.iterdir():
                if not re.fullmatch(r"[0-9a-f]{64}\.lock", job_lock.name):
                    raise ValueError("Unknown saved manual coordination entry")
                data = _read(job_lock, MAX_JSON, files)
                aliases[job_lock] = _descriptor(data)["sha256"], len(data)
        rows.append(canonical_json(row).decode())
        parents.append((deck.paper_id, canonical_json(paper).decode(), token))
    result = Observation(
        database,
        native,
        tuple(rows),
        tuple(objects.items()),
        tuple(aliases.items()),
        tuple(parents),
        tuple(files),
        roster,
        tree,
        _SEAL,
    )
    # An enrolled workspace with no selected manual rows must not be treated as local.
    result.check(current=current)
    return result


def restore(stage, rows):
    for row in rows.values():
        value = validate(row)
        read(row, lambda item: (stage / "objects" / item["sha256"]).read_bytes())
        folder = stage / "presentations" / hashlib.sha256(row["paper_id"].encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (row["slot"] + ".json")
        if target.exists():
            raise ValueError("Duplicate restored manual current slot")
        target.write_bytes((stage / "objects" / value["body"]["sha256"]).read_bytes())
        for item in value["figures"].values():
            assets = folder / "assets"
            assets.mkdir(exist_ok=True)
            (assets / (item["sha256"] + ".png")).write_bytes(
                (stage / "objects" / item["sha256"]).read_bytes()
            )
        if value["evidence"]:
            raw = _load(target.read_bytes())
            evidence = folder / "evidence"
            evidence.mkdir(exist_ok=True)
            (evidence / (raw["source_hash"] + ".json")).write_bytes(
                (stage / "objects" / value["evidence"]["sha256"]).read_bytes()
            )


def snapshot(row, read_blob):
    value = validate(row)
    result = read(row, read_blob)
    return result["deck"], result["evidence"], value["figures"], value["originals"]
