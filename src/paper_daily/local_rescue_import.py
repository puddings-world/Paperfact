"""Receiver-local rescue import: immutable science, actual NULL binding, no active writes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, replace

from paper_daily import local_deck_proposals as catalog
from paper_daily import portable_deck_archive as archive
from paper_daily import presentations
from paper_daily.sync_files import canonical_json

_SEAL = object()


@dataclass(frozen=True)
class LocalImport:
    prepared: object = field(repr=False)
    source: archive.RescueArchive = field(repr=False)
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class LocalRetention:
    candidate_id: str
    deck: object = field(repr=False, compare=False)
    evidence: object = field(repr=False, compare=False)
    durable: bool
    reason: str | None
    _job: LocalImport = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)


def _job(value):
    if not isinstance(value, LocalImport) or value._seal is not _SEAL:
        raise ValueError("Use an actual local rescue preparation")
    data = catalog._prepared(value.prepared)
    if data["manifest"] != value.source.manifest:
        raise ValueError("Prepared local rescue differs from its complete scientific copy")
    return data


def prepare(database, paper_id, source, *, expected_native, request_id, current=lambda: True):
    if not isinstance(source, archive.RescueArchive):
        raise ValueError("Choose a complete Paperfact rescue archive")

    def admitted():
        return current() and source.current()

    if not admitted():
        raise ValueError("Displayed rescue archive or original workspace changed")
    prepared = catalog.prepare(
        database, paper_id, source.manifest, source.read_blob,
        expected_native=expected_native, request_id=request_id, current=admitted,
    )
    if not admitted():
        raise ValueError("Displayed rescue archive changed during preparation")
    return LocalImport(prepared, source, _SEAL)


def run(job, *, current=lambda: True):
    data = _job(job)
    science = job.source.content
    outcome = LocalRetention(
        data["proposal_id"], presentations.deck_from_dict(science["deck"]),
        science["evidence"], False, None, job, _SEAL,
    )
    return retry(outcome, current=current)


def validate(outcome):
    if not isinstance(outcome, LocalRetention) or outcome._seal is not _SEAL:
        raise ValueError("Only an actual local rescue result can be retained")
    data = _job(outcome._job)
    science = outcome._job.source.content
    if (
        outcome.candidate_id != data["proposal_id"]
        # The UI Deck adds maintained text-style defaults on decoding. Compare
        # its projection to the same decoder, while the immutable rescue source
        # and catalog/export keep the unmodified full scientific JSON.
        or canonical_json(outcome.deck.to_dict()) != canonical_json(
            presentations.deck_from_dict(science["deck"]).to_dict()
        )
        or canonical_json(outcome.evidence) != canonical_json(science["evidence"])
    ):
        raise ValueError("Actual local result differs from its complete captured copy")
    return data


def retry(outcome, *, current=lambda: True):
    validate(outcome)
    try:
        identity = catalog.retain(outcome._job.prepared, current=current)
        if identity != outcome.candidate_id:
            raise ValueError("Local rescue returned a different retained result")
        return replace(outcome, durable=True, reason=None)
    except (ValueError, OSError, sqlite3.Error) as error:
        return replace(outcome, durable=False, reason=str(error))


def export(outcome, destination):
    validate(outcome)
    # Export the already captured memory copy even if the original file/database
    # disappeared. Export carries science, never authority to adopt another DB.
    source = outcome._job.source
    return archive.export(destination, source.manifest, source.read_blob)


def context(outcome):
    owner = validate(outcome)["captured"]
    return json.loads(canonical_json(owner))
