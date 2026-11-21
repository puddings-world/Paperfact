"""Bounded library discovery records, independent of research replication or login."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from paper_daily.drive_sync_files import MAX_INLINE, decode, encode, identifier
from paper_daily.sync_journal import SyncFormatUnsupported, _identifier
from paper_daily.workspace_service import Ticket, _read

FORMAT = "paperfact.library-directory.v1"
MAX_LISTS = 10_000
MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ScopeHead:
    generation: int
    id: str
    sha256: str
    size: int

    def __post_init__(self):
        if type(self.generation) is not int or not 1 <= self.generation < 2**53:
            raise ValueError("Invalid list history generation")
        identifier(self.id)
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Invalid list history checksum")
        if type(self.size) is not int or not 1 <= self.size <= MAX_INLINE:
            raise ValueError("Invalid list history size")

    def reference(self):
        return {"id": self.id, "size": self.size, "sha256": self.sha256}

    def record(self):
        return {"generation": self.generation, **self.reference()}


@dataclass(frozen=True)
class ListEntry:
    id: str
    name: str
    published: bool
    head: ScopeHead | None = None
    papers_head: ScopeHead | None = None
    notes_head: ScopeHead | None = None
    originals_head: ScopeHead | None = None
    dives_head: ScopeHead | None = None
    reading_head: ScopeHead | None = None
    extended_papers: bool = False
    membership_changes_head: ScopeHead | None = None
    restored_memberships: bool = False
    positions_head: ScopeHead | None = None
    chat_head: ScopeHead | None = None
    unlinked_chat: bool = False


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
            if any(h is not None and not isinstance(h, ScopeHead)
                   for h in (item.head, item.papers_head, item.notes_head,
                             item.originals_head, item.dives_head, item.reading_head,
                             item.membership_changes_head, item.positions_head, item.chat_head)):
                raise ValueError("Invalid published list history")
            if type(item.unlinked_chat) is not bool or (item.unlinked_chat and not item.chat_head):
                raise ValueError("Historical messages require a conversation history")
            if item.chat_head and not item.papers_head:
                raise ValueError("Conversation history requires a bibliography")
            if item.positions_head and not item.papers_head:
                raise ValueError("PDF positions require a bibliography")
            if type(item.restored_memberships) is not bool or (
                item.restored_memberships and not item.membership_changes_head
            ):
                raise ValueError("Restored memberships require a membership change history")
            if item.membership_changes_head and not item.papers_head:
                raise ValueError("Membership changes require a bibliography")
            if type(item.extended_papers) is not bool or (
                item.extended_papers and not item.papers_head
            ):
                raise ValueError("Invalid extended bibliography marker")
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
                format="paperfact.library-directory.v13" if any(e.unlinked_chat for e in self.lists)
                else "paperfact.library-directory.v12" if any(e.chat_head for e in self.lists)
                else "paperfact.library-directory.v11" if any(
                    e.positions_head for e in self.lists)
                else "paperfact.library-directory.v10" if any(
                    e.restored_memberships for e in self.lists)
                else "paperfact.library-directory.v9"
                if any(e.membership_changes_head for e in self.lists)
                else "paperfact.library-directory.v8"
                if any(e.extended_papers for e in self.lists)
                else "paperfact.library-directory.v7" if any(e.reading_head for e in self.lists)
                else "paperfact.library-directory.v6" if any(e.dives_head for e in self.lists)
                else "paperfact.library-directory.v5" if any(e.originals_head for e in self.lists)
                else "paperfact.library-directory.v4" if any(e.notes_head for e in self.lists)
                else "paperfact.library-directory.v3" if any(e.papers_head for e in self.lists)
                else "paperfact.library-directory.v2"
                if any(e.head for e in self.lists)
                else FORMAT,
                library_id=self.library_id,
                generation=self.generation,
                lists=[
                    dict(id=item.id, name=item.name, published=item.published)
                    | ({"head": item.head.record()} if item.head is not None else {})
                    | ({"papers_head": item.papers_head.record()} if item.papers_head else {})
                    | ({"unlinked_chat": True} if item.unlinked_chat else {})
                    | ({"chat_head": item.chat_head.record()} if item.chat_head else {})
                    | ({"notes_head": item.notes_head.record()} if item.notes_head else {})
                    | ({"originals_head": item.originals_head.record()}
                       if item.originals_head else {})
                    | ({"dives_head": item.dives_head.record()} if item.dives_head else {})
                    | ({"extended_papers": True} if item.extended_papers else {})
                    | ({"reading_head": item.reading_head.record()} if item.reading_head else {})
                    | ({"membership_changes_head": item.membership_changes_head.record()}
                       if item.membership_changes_head else {})
                    | ({"positions_head": item.positions_head.record()}
                       if item.positions_head else {})
                    | ({"restored_memberships": True} if item.restored_memberships else {})
                    for item in self.lists
                ],
            ),
            MAX_BYTES,
        )

    @property
    def digest(self):
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(cls, raw, *, library_id, membership_changes=False, membership_restores=False,
                   positions=False, chat=False, unlinked_chat=False):
        value = decode(raw, MAX_BYTES)
        if (
            not isinstance(value, dict)
            or set(value) != {"format", "library_id", "generation", "lists"}
            or value["library_id"] != library_id
            or not isinstance(value["lists"], list)
            or len(value["lists"]) > MAX_LISTS
        ):
            raise ValueError("Directory belongs to another library or unsupported format")
        version = re.fullmatch(r"paperfact\.library-directory\.v([1-9][0-9]{0,8})",
                               value["format"]) if isinstance(value["format"], str) else None
        if not version:
            raise ValueError("Invalid library directory format")
        supported = (13 if chat and unlinked_chat else 12 if chat else 11 if positions
                     else 10 if membership_restores else 9 if membership_changes else 8)
        if int(version[1]) > supported:
            raise SyncFormatUnsupported()
        entries = []
        for item in value["lists"]:
            required = {"id", "name", "published"}
            heads = ("head", "papers_head", "notes_head", "originals_head", "dives_head",
                     "reading_head", "membership_changes_head", "positions_head", "chat_head")
            allowed = required.union(heads, {"extended_papers", "restored_memberships",
                                             "unlinked_chat"})
            if not isinstance(item, dict) or not required <= item.keys() <= allowed:
                raise ValueError("Directory entries contain unsupported fields")
            for key in heads:
                if key not in item:
                    continue
                head = item[key]
                if not isinstance(head, dict) or set(head) != {
                    "generation",
                    "id",
                    "size",
                    "sha256",
                }:
                    raise ValueError("Invalid directory list history")
                item = {**item, key: ScopeHead(**head)}
            entries.append(ListEntry(**item))
        if chat and (
            (not positions and any(e.positions_head for e in entries))
            or (not membership_restores and any(e.restored_memberships for e in entries))
            or (not (membership_changes or membership_restores)
                and any(e.membership_changes_head for e in entries))
        ):
            raise SyncFormatUnsupported()
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
                if item.id in chosen and not (item.published or item.head)
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
