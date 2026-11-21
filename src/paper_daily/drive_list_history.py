"""Read and append a selected list's contiguous native operation history in Drive."""

import hashlib
from dataclasses import replace
from types import MappingProxyType

from paper_daily.drive_sync_files import MAX_INLINE, DriveChanged, decode, encode
from paper_daily.drive_sync_log import reference
from paper_daily.library_directory import ScopeHead
from paper_daily.sync_journal import SyncHistoryUnavailable, canonical_operation

FORMAT = "paperfact.list-history.v1"


class DriveListHistory:
    """One list, one local subscription store and one captured account directory."""

    format = FORMAT
    head_field = "head"

    def __init__(self, directory, store, list_id):
        if store.library_id != directory.library_id:
            raise ValueError("List subscription belongs to another library")
        self.directory = directory
        self.store = store
        self.list_id = list_id

    def _check(self, revision):
        selection = self.store.load()
        if selection.revision != revision or self.list_id not in selection.selected:
            raise ValueError("This device changed its list selection")

    def _entry(self, observation):
        return next((item for item in observation.directory.lists if item.id == self.list_id), None)

    def _operations(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError("Invalid scoped operation batch")
        seen = set()
        for op in records:
            canonical_operation(op)
            if op["workspace_id"] != self.directory.library_id or op["operation_id"] in seen:
                raise ValueError("Unexpected library or duplicate operation")
            seen.add(op["operation_id"])
        self._validate_scope(records)
        return records

    def _validate_scope(self, records):
        if any(op["entity_type"] != "list" or op["entity_id"] != self.list_id for op in records):
            raise ValueError("Operation is outside the selected list")

    def _advance(self, entry, head, records):
        return replace(entry, head=head, name=records[-1]["payload"].get("name", entry.name))

    def append(self, expected, records, *, revision):
        self._check(revision)
        records = self._operations(records)
        if expected is not None and not isinstance(expected, ScopeHead):
            raise ValueError("Invalid observed list history")
        directory = self.directory
        if directory.files.account()["id"] != self.store.owner_id:
            raise PermissionError("The selected Google account changed")
        observed = directory.read()
        entry = self._entry(observed)
        if entry is None:
            raise DriveChanged("Selected list is no longer in this directory")
        generation = 1 if expected is None else expected.generation + 1
        raw = encode(
            dict(
                format=self.format,
                library_id=directory.library_id,
                list_id=self.list_id,
                generation=generation,
                previous=expected.record() if expected else None,
                operations=records,
            ),
            MAX_INLINE,
        )
        current = getattr(entry, self.head_field)
        if current != expected:
            if (
                current
                and current.generation == generation
                and current.sha256 == hashlib.sha256(raw).hexdigest()
            ):
                return current
            raise DriveChanged("List history changed; reload before publishing")
        (identity,) = directory.files.new_ids()
        self._check(revision)
        directory.files.put_small(
            identity, directory.folder, directory.key, "commit", raw, folder_role="directory"
        )
        head = ScopeHead(generation, **reference(identity, raw))
        self._check(revision)
        directory.upsert(
            observed,
            [self._advance(entry, head, records)],
            check=lambda: self._check(revision),
        )
        return head

    def _read_entry(self, current):
        directory = self.directory
        raw = directory.files.read_small(current.reference(), directory.folder, directory.key)
        item = decode(raw, MAX_INLINE)
        if (
            not isinstance(item, dict)
            or set(item)
            != {"format", "library_id", "list_id", "generation", "previous", "operations"}
            or item["format"] != self.format
            or item["list_id"] != self.list_id
            or item["library_id"] != directory.library_id
            or item["generation"] != current.generation
            or encode(item, MAX_INLINE) != raw
        ):
            raise ValueError("Invalid selected list history")
        operations = self._operations(item["operations"])
        previous = item["previous"]
        if previous is not None and (
            not isinstance(previous, dict)
            or set(previous) != {"generation", "id", "size", "sha256"}
        ):
            raise ValueError("Invalid previous list history")
        parent = ScopeHead(**previous) if previous is not None else None
        if current.generation != (parent.generation if parent else 0) + 1:
            raise SyncHistoryUnavailable("List history has a generation gap")
        return parent, operations

    def applied_payload(self, anchor, *, revision):
        """Read the exact common version only when both copies have changed."""
        self._check(revision)
        if self.directory.files.account()["id"] != self.store.owner_id:
            raise PermissionError("The selected Google account changed")
        _, operations = self._read_entry(anchor)
        self._check(revision)
        return operations[-1]["payload"] if operations[-1]["action"] == "put" else None

    def changes(self, anchor, *, revision):
        self._check(revision)
        if anchor is not None and not isinstance(anchor, ScopeHead):
            raise ValueError("Invalid observed list history")
        head = self._current_head()
        return head, self._since(head, anchor, revision)

    def _current_head(self):
        directory = self.directory
        if directory.files.account()["id"] != self.store.owner_id:
            raise PermissionError("The selected Google account changed")
        entry = self._entry(directory.read())
        if entry is None:
            raise SyncHistoryUnavailable("Selected list is missing from this directory")
        return getattr(entry, self.head_field)

    def _since(self, head, anchor, revision):
        current = head
        result, used = [], 0
        while current != anchor:
            self._check(revision)
            if (
                current is None
                or (anchor and current.generation <= anchor.generation)
                or len(result) >= 100
                or used + current.size > 8 * 1024**2
            ):
                raise SyncHistoryUnavailable("Cannot prove the selected list history prefix")
            parent, operations = self._read_entry(current)
            used += current.size
            result.append(operations)
            current = parent
        self._check(revision)
        return [op for batch in reversed(result) for op in batch]


class DriveListPapers(DriveListHistory):
    """Transfer native paper metadata only alongside its selected-list membership."""

    format = "paperfact.list-paper-history.v1"
    head_field = "papers_head"

    def members(self, revision):
        """Reuse only a verified membership projection for the exact observed paper head."""
        self._check(revision)
        head = self._current_head()
        key = (self.store.context, self.directory.folder, self.directory.head, self.list_id)
        cache = self.directory.files.membership_cache
        with self.directory.files.membership_lock:
            previous = cache.get(key)
        if previous is not None and previous[0] == head:
            self._check(revision)
            return previous
        records = self._since(head, None, revision)
        members = MappingProxyType({op["entity_id"]: op["incarnation"] for op in records[::2]})
        snapshot = head, members
        with self.directory.files.membership_lock:
            cache.pop(key, None)
            if members and len(members) <= 10000:
                while (len(cache) >= 16
                       or sum(len(v[1]) for v in cache.values()) + len(members) > 10000):
                    del cache[next(iter(cache))]
                cache[key] = snapshot
        return snapshot

    def _validate_scope(self, records):
        if len(records) % 2:
            raise ValueError("Each paper requires a selected-list membership")
        seen = set()
        for paper, member in zip(records[::2], records[1::2], strict=True):
            if (
                paper["version"] != 2 or member["version"] != 2
                or paper["entity_type"] != "paper" or member["entity_type"] != "membership"
                or paper["action"] != "put" or member["action"] != "put"
                or member["payload"]["list_id"] != self.list_id
                or member["payload"]["paper_id"] != paper["entity_id"]
                or paper["entity_id"] in seen
            ):
                raise ValueError("Paper does not belong to this selected membership")
            parent = next(p for p in member["parents"] if p["kind"] == "paper")
            if parent["incarnation"] != paper["incarnation"]:
                raise ValueError("Membership refers to another paper incarnation")
            seen.add(paper["entity_id"])

    def _advance(self, entry, head, records):
        return replace(entry, papers_head=head)


class DriveListNotes(DriveListHistory):
    """A note stream tied to paper incarnations in a verified bibliography snapshot."""

    format = "paperfact.list-note-history.v1"
    head_field = "notes_head"

    def __init__(self, directory, store, list_id, *, revision):
        super().__init__(directory, store, list_id)
        self.revision = revision
        self.grant = store.note_grant(list_id, revision)
        if self.grant is None:
            raise PermissionError("Enable note sync on this device before transferring notes")
        papers = DriveListPapers(directory, store, list_id)
        _, self._members = papers.members(revision)

    def paper_parent(self, identity):
        if identity not in self._members:
            raise ValueError("Note parent is outside the selected bibliography")
        return {"kind": "paper", "id": identity, "incarnation": self._members[identity]}

    def _check(self, revision):
        if revision != self.revision:
            raise ValueError("Review the changed list selection before exchanging notes")
        if self.store.note_grant(self.list_id, revision) != self.grant:
            raise PermissionError("This device changed its note sync permission")

    def _validate_scope(self, records):
        for op in records:
            if op["version"] != 2 or op["entity_type"] != "note" or len(op["parents"]) != 1:
                raise ValueError("Expected a native paper note")
            parent = op["parents"][0]
            if parent != self.paper_parent(parent["id"]):
                raise ValueError("Note parent is outside the selected bibliography")

    def _advance(self, entry, head, records):
        return replace(entry, notes_head=head)
