"""Process-local explicit decisions over observed native Lineage import conflicts."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field

from paper_daily import (
    claim_content,
    lineage_package_native,
    lineage_projection,
    lineage_sets,
    lineage_wire,
    sync_capture,
)
from paper_daily.package_import import UnsupportedPackage
from paper_daily.sync_content import content_id

_KEY = secrets.token_bytes(32)
MAX_BYTES = 64 * 1024**2


def _encode(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Lineage comparison exceeds its bounded review budget")
    return encoded


def _seal(value):
    return hmac.new(_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class Decision:
    _json: str = field(repr=False)
    _seal: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Review:
    _json: str = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def archive_hash(self):
        return _checked(self, Review)["scope"]["archive"]

    @property
    def conflicts(self):
        value = _checked(self, Review)
        return [
            dict(
                id=item["id"],
                title=item["title"],
                can_replace=item["can_replace"],
                can_adopt=item["can_adopt"],
                current=lineage_sets.decode(item["current"]["body_json"])
                if item["current"] is not None
                else None,
                incoming=item["incoming"]["data"]["body_json"],
                current_at=item["current"]["written_at"] if item["current"] is not None else None,
                incoming_at=item["incoming"]["data"]["written_at"],
            )
            for item in value["items"]
        ]

    def decide(self, choices):
        value = _checked(self, Review)
        if not isinstance(choices, dict) or set(choices) != {i["id"] for i in value["items"]}:
            raise ValueError("Choose explicitly for every compared Lineage analysis")
        for item in value["items"]:
            choice = choices[item["id"]]
            if choice not in ("keep", "replace", "adopt") or (
                choice == "replace" and not item["can_replace"]
            ) or (choice == "adopt" and not item["can_adopt"]):
                raise ValueError("This Lineage version cannot be replaced by package import")
        encoded = _encode(dict(review=value, choices=choices))
        return Decision(encoded, _seal(encoded))


class ReviewRequired(UnsupportedPackage):
    def __init__(self, review):
        super().__init__("Lineage replacement requires reviewed adoption")
        self.review = review


def _checked(value, expected):
    if (
        type(value) is not expected
        or not isinstance(value._json, str)
        or not isinstance(value._seal, str)
    ):
        raise ValueError("Lineage import requires its actual observed review")
    if len(value._json.encode("utf-8")) > MAX_BYTES or not hmac.compare_digest(
        value._seal, _seal(value._json)
    ):
        raise ValueError("Lineage import review is not an actual native decision")
    return json.loads(value._json)


def fingerprint(decision):
    _checked(decision, Decision)
    return hashlib.sha256(decision._json.encode("utf-8")).hexdigest()


def admit_in(conn, importer, validated, identities, archive_hash, decision=None):
    """Observe all conflicts without publishing bytes, SQL, history or operations.

    Permission to replace a native report is bound to this exact archive, receiver,
    mapping, SQL row and native operation. Exact matching unowned content has a
    separate explicit adoption choice. It cannot restore retired science, repair
    missing native authority or change selected paper identities.
    """
    client = importer.client
    items = []
    for incoming in lineage_package_native.payloads(validated, identities):
        portable = incoming["scope"]["id"]
        # identity mapping is portable; the local receiver mapping is its SQL identity.
        mapped = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
            (portable,),
        ).fetchone()
        if mapped is None:
            continue  # A genuinely new focal paper has no report to replace.
        local = mapped[0]
        identity = content_id(incoming["scope"], "lineage", incoming["key"])
        current = lineage_package_native.saved_in(conn, local, incoming["key"])
        prior = sync_capture._current(conn, client, "research_content", identity)
        if current is None and prior is None:
            continue
        marker = marker_operation = None
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_projection.TABLE,)
        ).fetchone():
            marker, marker_operation = lineage_projection._marker(conn, identity)
        if prior is not None and prior.get("action") == "put":
            if current != lineage_wire.decode_row(conn, prior["payload"]):
                raise ValueError("Saved Lineage changed outside its native projection")
            owned = bool(
                marker
                and marker["active"]
                and marker_operation == prior
                and marker["fingerprint"] == claim_content.hashed(current)
            )
            if owned and prior["payload"] == incoming:
                continue
        else:
            owned = False
        can_replace = owned and (
            [(p["kind"], p["id"]) for p in prior["parents"]]
            == lineage_wire.parent_identities(incoming)
        )
        from paper_daily.lineage_matching_adoption import eligible_in, parents_in

        can_adopt = eligible_in(conn, client, identity, incoming, current)
        title = conn.execute("SELECT title FROM papers WHERE id=?", (local,)).fetchone()
        items.append(
            dict(
                id=identity,
                title=title[0] if title else local,
                current=current,
                operation=prior,
                marker=marker,
                incoming=incoming,
                can_replace=bool(can_replace),
                can_adopt=can_adopt,
                adoption_parents=parents_in(conn, client, incoming) if can_adopt else None,
            )
        )
    scope = dict(
        database=str(importer.database),
        identity=list(importer.identity),
        binding=importer.binding,
        archive=archive_hash,
        mapping=identities,
    )
    value = dict(scope=scope, items=items)
    if decision is not None:
        approved = _checked(decision, Decision)
        if _encode(approved["review"]) != _encode(value):
            raise ValueError("Lineage comparison changed; review the versions again")
        return dict(approved["choices"])
    if items:
        encoded = _encode(value)
        raise ReviewRequired(Review(encoded, _seal(encoded)))
    return {}
