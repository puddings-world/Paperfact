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
    max_operations = 100
    max_pages = 100
    max_bytes = 8 * 1024**2

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
        if not isinstance(records, list) or not 1 <= len(records) <= self.max_operations:
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

    def _check_publication(self, revision, records):
        self._check(revision)

    def append(self, expected, records, *, revision):
        return self._append(expected, records, revision,
                            lambda: self._check_publication(revision, records))

    def _append(self, expected, records, revision, check, *, remaining_bytes=None):
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
        if remaining_bytes is not None and len(raw) > remaining_bytes:
            raise ValueError("New page exceeds the readable history budget")
        (identity,) = directory.files.new_ids()
        check()
        directory.files.put_small(
            identity, directory.folder, directory.key, "commit", raw, folder_role="directory"
        )
        head = ScopeHead(generation, **reference(identity, raw))
        self._check(revision)
        directory.upsert(
            observed,
            [self._advance(entry, head, records)],
            check=check,
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
        return [op for _, batch in self._pages_since(head, anchor, revision) for op in batch]

    def _pages_since(self, head, anchor, revision):
        current = head
        result, used = [], 0
        while current != anchor:
            self._check(revision)
            if (
                current is None
                or (anchor and current.generation <= anchor.generation)
                or len(result) >= self.max_pages
                or used + current.size > self.max_bytes
            ):
                raise SyncHistoryUnavailable("Cannot prove the selected list history prefix")
            parent, operations = self._read_entry(current)
            used += current.size
            result.append((current, operations))
            current = parent
        self._check(revision)
        return reversed(result)


class DriveListPapers(DriveListHistory):
    """Transfer native paper metadata only alongside its selected-list membership."""

    format = "paperfact.list-paper-history.v1"
    head_field = "papers_head"
    max_operations = 500
    max_pages = 256
    max_bytes = 64 * 1024**2
    extended = False

    def bibliography(self, revision):
        """Return ordered records and the verified record boundary at each immutable head."""
        self._check(revision)
        head = self._current_head()
        records, boundaries = [], {}
        for page, operations in self._pages_since(head, None, revision):
            records.extend(operations)
            boundaries[encode(page.record())] = len(records)
        return head, records, boundaries

    def members(self, revision):
        head, members, _ = self.membership_snapshot(revision)
        return head, members

    def membership_snapshot(self, revision):
        """Verified paper and membership lifetimes for the exact observed paper head."""
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
        lifetimes = {}
        for member in records[1::2]:
            identity = member["entity_id"]
            if identity in lifetimes:
                lifetimes = None
                break
            parents = {p["kind"]: p for p in member["parents"]}
            paper = parents["paper"]
            lifetimes[identity] = (paper["id"], paper["incarnation"],
                                   parents["list"]["incarnation"], member["incarnation"])
        snapshot = head, members, MappingProxyType(lifetimes) if lifetimes is not None else None
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
        return replace(entry, papers_head=head,
                       extended_papers=entry.extended_papers or self.extended)


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


class _MembershipHistory(DriveListHistory):
    def __init__(self, directory, store, list_id, *, revision):
        super().__init__(directory, store, list_id)
        self.check_source = None
        self.revision = revision
        self.grant = self._grant(revision)
        self._check(revision)
        papers = DriveListPapers(directory, store, list_id)
        self.paper_head, _, self.memberships = papers.membership_snapshot(revision)
        self._check(revision)
        if self.memberships is None:
            raise ValueError("Ambiguous membership history for reading progress")

        self.retired = {}
        self.restored = {}
        self.prior_lifetimes = set()
        self.removal_head = None
        if directory.membership_changes:
            from paper_daily.drive_membership_history import (
                membership_history,
                membership_versions,
            )

            changes = membership_history(directory, store, list_id, revision=revision)
            if changes.paper_head != self.paper_head:
                raise DriveChanged("Bibliography changed before reading progress")
            self.removal_head, removals = changes.changes(None, revision=revision)
            latest, retired = membership_versions(changes.creations, removals)
            self.restored = {m: op for m, op in latest.items() if op != changes.creations[m]}
            if self.restored:
                self.memberships = dict(self.memberships)
                for m, op in self.restored.items():
                    self.memberships[m] = (*self.memberships[m][:3], op["incarnation"])
                self.prior_lifetimes = {(op["entity_id"], op["incarnation"]) for op in removals
                                        if op["action"] == "delete"}
            self.retired = {member: op["operation_id"] for member, op in retired.items()}

    def _entry(self, observation):
        entry = super()._entry(observation)
        if self.directory.membership_changes and (
            not entry or entry.papers_head != self.paper_head
            or entry.membership_changes_head != self.removal_head
        ):
            raise DriveChanged("List membership changed; retry reading progress")
        return entry

    def parents_for(self, identity):
        paper, paper_inc, list_inc, member_inc = self.memberships[identity]
        return {
            "list": dict(kind="list", id=self.list_id, incarnation=list_inc),
            "paper": dict(kind="paper", id=paper, incarnation=paper_inc),
            "membership": dict(kind="membership", id=identity, incarnation=member_inc),
        }

    def _check(self, revision):
        if self.check_source:
            self.check_source()
        if (not self.grant or revision != self.revision
                or self._grant(revision) != self.grant):
            raise PermissionError("Enable this content type for the selected list on this device")



class DriveListReading(_MembershipHistory):
    """Reading progress belongs to the observed membership, including its lifetime."""

    format = "paperfact.list-reading-history.v1"
    head_field = "reading_head"

    def _grant(self, revision):
        return self.store.reading_grant(self.list_id, revision)

    def _check_publication(self, revision, records):
        super()._check_publication(revision, records)
        if any(op["incarnation"] != self.memberships[op["entity_id"]][3] for op in records):
            raise ValueError("Cannot publish reading progress for an earlier membership lifetime")
        if any(op["entity_id"] in self.retired for op in records):
            raise ValueError("Cannot publish reading progress for a retired membership")

    def _validate_scope(self, records):
        for op in records:
            if (op["version"] != 2 or op["entity_type"] != "reading_state"
                    or op["action"] != "put" or op["entity_id"] not in self.memberships
            ):
                raise ValueError("Reading progress requires the selected membership parents")
            identity = op["entity_id"]
            expected = self.parents_for(identity)
            if (identity, op["incarnation"]) in self.prior_lifetimes:
                expected["membership"]["incarnation"] = op["incarnation"]
            if (expected["membership"]["incarnation"] != op["incarnation"]
                    or expected != {p["kind"]: p for p in op["parents"]}):
                raise ValueError("Reading progress requires the selected membership parents")

    def _advance(self, entry, head, records):
        return replace(entry, reading_head=head)

class DriveListPositions(_MembershipHistory):
    """Source-bound page suggestions from devices sharing this list."""

    format = "paperfact.list-position-history.v1"
    head_field = "positions_head"

    def _grant(self, revision):
        if not self.directory.positions:
            raise PermissionError("Enable directory support for PDF positions")
        return self.store.position_grant(self.list_id, revision)

    def _latest(self, records):
        tips, seen = {}, set()
        for op in records:
            key = (op["device_id"], op["entity_id"], op["incarnation"])
            previous = tips.get(key)
            predecessor = previous["operation_id"] if previous else None
            version = previous["base_revision"] + 1 if previous else 0
            if (op["operation_id"] in seen or op["depends_on"] != predecessor
                    or op["base_revision"] != version):
                raise SyncHistoryUnavailable("PDF position does not follow its device history")
            seen.add(op["operation_id"])
            tips[key] = op
        return tips.values()

    def suggestions(self, *, revision):
        """Read current membership suggestions in verified history order, independent of clocks."""
        head, records = self.changes(None, revision=revision)
        result = []
        for op in self._latest(records):
            member = self._member(op)
            if member not in self.retired and op["incarnation"] == self.memberships[member][3]:
                result.append(op)
        self._check(revision)
        return head, result

    def append(self, expected, records, *, revision):
        # Bound each page so a complete history always fits the reader's byte limit.
        if isinstance(expected, ScopeHead) and expected.generation >= self.max_pages:
            raise ValueError("PDF position history reached its page limit")
        self._check(revision)
        if expected is not None and not isinstance(expected, ScopeHead):
            raise ValueError("Invalid observed position history")
        self._operations(records)
        self._check_publication(revision, records)
        if self.directory.files.account()["id"] != self.store.owner_id:
            raise PermissionError("The selected Google account changed")
        self._latest(self._since(expected, None, revision) + records)
        return self._append(expected, records, revision,
                            lambda: self._check_publication(revision, records),
                            remaining_bytes=self.max_bytes // self.max_pages)

    def _member(self, op):
        from paper_daily.sync_schema_v2 import membership_id

        return membership_id(self.list_id, op["payload"]["scope"]["id"])

    def _validate_scope(self, records):
        for op in records:
            if (op["version"] != 2 or op["entity_type"] != "research_content"
                    or op["action"] != "put" or op["payload"]["feature"] != "reading_position"):
                raise ValueError("Expected a source-bound PDF position")
            member = self._member(op)
            if member not in self.memberships:
                raise ValueError("Position paper is outside the selected list")
            refs = self.parents_for(member)
            if (op["parents"] != [refs["paper"]]
                    or (op["incarnation"] != refs["membership"]["incarnation"]
                        and (member, op["incarnation"]) not in self.prior_lifetimes)):
                raise ValueError("Position belongs to another paper or membership lifetime")

    def _check_publication(self, revision, records):
        self._check(revision)
        for op in records:
            member = self._member(op)
            if (op["device_id"] != self.store.context or member in self.retired
                    or op["incarnation"] != self.memberships[member][3]):
                raise ValueError("Publish a local position for an active membership")

    def _advance(self, entry, head, records):
        return replace(entry, positions_head=head)
