"""Bounded library discovery records, independent of research replication or login."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from paper_daily.drive_sync_files import decode, encode
from paper_daily.sync_journal import _identifier
from paper_daily.workspace_service import Ticket, _read

FORMAT = "paperfact.library-directory.v1"
MAX_LISTS = 10_000
MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ListEntry:
    id: str
    name: str
    published: bool


@dataclass(frozen=True)
class Directory:
    library_id: str
    generation: int
    lists: tuple[ListEntry, ...]

    def __post_init__(self):
        _identifier(self.library_id)
        if type(self.generation) is not int or not 0 <= self.generation < 2**53:
            raise ValueError("Invalid library directory generation")
        if not isinstance(self.lists, tuple) or len(self.lists) > MAX_LISTS:
            raise ValueError("Library directory exceeds its list budget")
        seen = set()
        for item in self.lists:
            if not isinstance(item, ListEntry):
                raise ValueError("Invalid library directory entry")
            _identifier(item.id)
            if item.id in seen:
                raise ValueError("Duplicate library list identity")
            seen.add(item.id)
            if (
                not isinstance(item.name, str)
                or not item.name.strip()
                or len(item.name) > 200
                or any(ord(c) < 32 or ord(c) == 127 for c in item.name)
                or type(item.published) is not bool
            ):
                raise ValueError("Invalid library list label or availability")
        if tuple(sorted(self.lists, key=lambda item: item.id)) != self.lists:
            raise ValueError("Library directory must use stable identity order")
        self.to_bytes()

    def to_bytes(self):
        return encode(
            dict(
                format=FORMAT,
                library_id=self.library_id,
                generation=self.generation,
                lists=[
                    dict(id=item.id, name=item.name, published=item.published)
                    for item in self.lists
                ],
            ),
            MAX_BYTES,
        )

    @property
    def digest(self):
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(cls, raw, *, library_id):
        value = decode(raw, MAX_BYTES)
        if (
            not isinstance(value, dict)
            or set(value) != {"format", "library_id", "generation", "lists"}
            or value["format"] != FORMAT
            or value["library_id"] != library_id
            or not isinstance(value["lists"], list)
            or len(value["lists"]) > MAX_LISTS
        ):
            raise ValueError("Directory belongs to another library or unsupported format")
        entries = []
        for item in value["lists"]:
            if not isinstance(item, dict) or set(item) != {"id", "name", "published"}:
                raise ValueError("Directory entries contain unsupported fields")
            entries.append(ListEntry(**item))
        directory = cls(library_id, value["generation"], tuple(entries))
        if directory.to_bytes() != raw:
            raise ValueError("Library directory bytes must be canonical")
        return directory


def inspect_lists(database, library_id, *, generation=0, published=(), ticket=None):
    """Read all list names, without opening papers, PDFs, notes or credentials.

    The returned record is a local observation, not cloud publication or proof of
    content availability. Only the transport may supply verified published IDs.
    """
    ticket = ticket or Ticket()
    ticket.check()
    available = set(published)
    for identity in available:
        _identifier(identity)
    entries = []
    with _read(Path(database).resolve()) as conn:
        rows = conn.execute("SELECT id,name FROM lists ORDER BY id LIMIT ?", (MAX_LISTS + 1,))
        for identity, name in rows:
            ticket.check()
            if len(entries) == MAX_LISTS:
                raise ValueError("Library directory exceeds its list budget")
            entries.append(ListEntry(identity, name, identity in available))
    if not available <= {item.id for item in entries}:
        raise ValueError("Published selection is not in this library directory")
    ticket.check()
    return Directory(library_id, generation, tuple(entries))


def checklist(directory, selected, *, local_ids=()):
    """Render selection intent and availability, never a claim of completed sync."""
    chosen, local = set(selected), set(local_ids)
    return [
        dict(
            id=item.id,
            name=item.name,
            selected=item.id in chosen,
            state=(
                "waiting_source"
                if item.id in chosen and not item.published
                else "selected_local"
                if item.id in chosen and item.id in local
                else "pending_download"
                if item.id in chosen
                else "retained_local"
                if item.id in local
                else "not_selected"
            ),
        )
        for item in directory.lists
    ]
