"""Version-gated Drive history for retirement of exact native list memberships."""

import hashlib
from dataclasses import replace

from paper_daily.drive_list_history import DriveListHistory, DriveListPapers
from paper_daily.drive_sync_files import DriveChanged, encode
from paper_daily.sync_journal import canonical_operation


def removal_operation(member, device):
    """Build the same deletion on retry from its verified membership creation."""
    canonical_operation(member)
    if member["entity_type"] != "membership" or member["action"] != "put":
        raise ValueError("A removal needs a verified membership creation")
    op = dict(member, device_id=device, action="delete", depends_on=member["operation_id"],
              base_revision=member["base_revision"] + 1, payload={})
    del op["operation_id"]
    op["operation_id"] = hashlib.sha256(encode(op)).hexdigest()
    canonical_operation(op)
    return op


def restoration_operation(creation, retirement, device, *, citation, added_at):
    """Restore only the observed retired lifetime, keeping its list and paper parents."""
    if retirement != removal_operation(creation, retirement["device_id"]):
        raise ValueError("Restoration requires the matching membership removal")
    payload = dict(creation["payload"], citation=citation, added_at=added_at)
    op = dict(creation, device_id=device, payload=payload, depends_on=retirement["operation_id"],
              base_revision=retirement["base_revision"] + 1)
    del op["operation_id"], op["incarnation"]
    # A retry has the same incarnation. A later retirement has a different predecessor.
    identity = hashlib.sha256(encode(op)).hexdigest()
    op.update(incarnation=identity, operation_id=identity)
    canonical_operation(op)
    return op


def membership_versions(creations, changes):
    """Fold a verified bibliography and ordered changes into the latest put and open removal."""
    active_versions = dict(creations)
    retired = {}
    for op in changes:
        member = op["entity_id"]
        previous = active_versions.get(member)
        if not previous:
            raise ValueError("Unknown membership in change history")
        if op["action"] == "delete":
            if member in retired or op != removal_operation(previous, op["device_id"]):
                raise ValueError("Removal does not match the current membership lifetime")
            retired[member] = op
        else:
            removal = retired.get(member)
            if not removal or op != restoration_operation(
                previous, removal, op["device_id"], citation=op["payload"].get("citation"),
                added_at=op["payload"].get("added_at"),
            ):
                raise ValueError("Restoration does not follow the current membership removal")
            active_versions[member] = op
            del retired[member]
    return active_versions, retired


class DriveMembershipChanges(DriveListHistory):
    format = "paperfact.membership-changes.v1"
    head_field = "membership_changes_head"

    def __init__(self, directory, store, list_id, *, revision):
        super().__init__(directory, store, list_id)
        if not directory.membership_changes:
            raise ValueError("Enable membership change support before reading this history")
        papers = DriveListPapers(directory, store, list_id)
        self.paper_head, records, self.boundaries = papers.bibliography(
            revision)
        self.creations = {op["entity_id"]: op for op in records[1::2]}
        if len(self.creations) * 2 != len(records):
            raise ValueError("Ambiguous membership creation history")

    def _entry(self, observation):
        entry = super()._entry(observation)
        if not entry or entry.papers_head != self.paper_head:
            raise DriveChanged("Bibliography changed; refresh before exchanging removals")
        return entry

    def _validate_scope(self, records):
        for op in records:
            member = self.creations.get(op["entity_id"])
            if not member or op != removal_operation(member, op["device_id"]):
                raise ValueError("Removal does not match the observed membership creation")

    def retirements(self, revision):
        _, changes = self.changes(None, revision=revision)
        _, retired = membership_versions(self.creations, changes)
        return retired

    def append(self, expected, records, *, revision):
        records = self._operations(records)
        if any(op["device_id"] != self.store.context for op in records):
            raise ValueError("A device can only publish its own membership removal")
        head, prior = self.changes(None, revision=revision)
        if head == expected:
            retired = {op["entity_id"] for op in prior}
            if any(op["entity_id"] in retired for op in records):
                raise ValueError("Membership already retired")
            if (len(prior) + len(records) > self.max_pages * self.max_operations
                    or (head and head.generation >= self.max_pages)):
                raise ValueError("Membership change history exceeds its readable budget")
        return super().append(expected, records, revision=revision)

    def _check_publication(self, revision, records):
        from paper_daily.drive_list_records import ListReviewRequired
        from paper_daily.drive_membership_intent import observed_removals

        super()._check_publication(revision, records)
        members = {op["entity_id"] for op in records}
        candidates = {member["payload"]["paper_id"]: (index * 2 + 1, member)
                      for index, member in enumerate(self.creations.values())
                      if member["entity_id"] in members}
        pending = observed_removals(self.store, self.list_id, self.boundaries, candidates)
        if {op["operation_id"] for op in pending} != {op["operation_id"] for op in records}:
            raise ListReviewRequired("Local removal changed; refresh before publishing")

    def _advance(self, entry, head, records):
        return replace(entry, membership_changes_head=head)


class DriveMembershipRestores(DriveMembershipChanges):
    """Explicit restoration writer and full-chain reader for capable devices."""

    def __init__(self, directory, store, list_id, *, revision):
        if not directory.membership_restores:
            raise ValueError("Enable membership restoration before using this history")
        super().__init__(directory, store, list_id, revision=revision)

    def _validate_scope(self, records):
        for op in records:
            original = self.creations.get(op["entity_id"])
            if (not original or op["entity_type"] != "membership"
                    or op["parents"] != original["parents"]):
                raise ValueError("Membership change belongs to a different list or paper")

    def versions(self, revision):
        head, records = self.changes(None, revision=revision)
        latest, retired = membership_versions(self.creations, records)
        return head, latest, retired

    def append(self, expected, records, *, revision):
        raise ValueError("Restoration requires a reviewed local membership")

    def restore(self, expected, operation, *, revision, check_review):
        records = self._operations([operation])
        if operation["action"] != "put" or operation["device_id"] != self.store.context:
            raise ValueError("Restore only an entry reviewed by this device")
        self._check(revision)
        head = self._current_head()
        pages = list(self._pages_since(head, None, revision))
        prior = [op for _, batch in pages for op in batch]
        remaining = self.max_bytes - sum(page.size for page, _ in pages)
        membership_versions(self.creations, prior)
        if head == expected:
            membership_versions(self.creations, [*prior, operation])
            if head is None or head.generation >= self.max_pages:
                raise ValueError("Restoration exceeds the readable history budget")

        def check():
            self._check(revision)
            check_review()

        return self._append(expected, records, revision, check, remaining_bytes=remaining)

    def _advance(self, entry, head, records):
        return replace(entry, membership_changes_head=head, restored_memberships=True)
