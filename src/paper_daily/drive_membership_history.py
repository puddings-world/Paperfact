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
        from paper_daily.drive_list_records import ListReviewRequired

        _, changes = self.changes(None, revision=revision)
        retired = {op["entity_id"]: op for op in changes}
        if len(retired) != len(changes):
            raise ListReviewRequired("Duplicate membership retirement; review the history")
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
