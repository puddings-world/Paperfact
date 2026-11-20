"""Read and append a selected list's contiguous native operation history in Drive."""

import hashlib
from dataclasses import replace

from paper_daily.drive_sync_files import MAX_INLINE, DriveChanged, decode, encode
from paper_daily.drive_sync_log import reference
from paper_daily.library_directory import ScopeHead
from paper_daily.sync_journal import SyncHistoryUnavailable, canonical_operation

FORMAT = "paperfact.list-history.v1"


class DriveListHistory:
    """One list, one local subscription store and one captured account directory."""

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
            # Publishing more entity kinds requires a verified membership/source closure.
            if op["entity_type"] != "list" or op["entity_id"] != self.list_id:
                raise ValueError("Operation is outside the selected list")
        return records

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
                format=FORMAT,
                library_id=directory.library_id,
                list_id=self.list_id,
                generation=generation,
                previous=expected.record() if expected else None,
                operations=records,
            ),
            MAX_INLINE,
        )
        if entry.head != expected:
            if (
                entry.head
                and entry.head.generation == generation
                and (entry.head.sha256 == hashlib.sha256(raw).hexdigest())
            ):
                return entry.head
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
            [replace(entry, head=head, name=records[-1]["payload"].get("name", entry.name))],
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
            or item["format"] != FORMAT
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
        directory = self.directory
        if directory.files.account()["id"] != self.store.owner_id:
            raise PermissionError("The selected Google account changed")
        observed = directory.read()
        entry = self._entry(observed)
        if entry is None:
            raise SyncHistoryUnavailable("Selected list is missing from this directory")
        current = entry.head
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
        return entry.head, [op for batch in reversed(result) for op in batch]
