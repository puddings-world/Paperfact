"""Immutable Drive transaction chain; local callers retain their applied anchor.

This is transport storage, not research conflict resolution or enrollment. A
transaction's validated bytes become visible only after conditional head update.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from paper_daily.drive_sync_files import (
    FORMAT as HEAD_FORMAT,
)
from paper_daily.drive_sync_files import (
    MAX_INLINE,
    DriveFiles,
    Head,
    decode,
    encode,
    head_body,
    identifier,
)
from paper_daily.sync_journal import SyncHistoryUnavailable, _identifier

FORMAT = "paperfact.drive-transaction.v1"
MAX_PAGE = 100
MAX_PAGE_BYTES = 8 * 1024**2


def reference(file_id, raw):
    return {"id": identifier(file_id), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def transaction(raw, workspace_id):
    value = decode(raw, MAX_INLINE)
    if (not isinstance(value, dict) or set(value) != {
            "format", "workspace_id", "generation", "previous", "payload"}
            or value["format"] != FORMAT or value["workspace_id"] != workspace_id
            or not isinstance(value["payload"], dict)):
        raise ValueError("Unsupported Drive transaction")
    # Reuse the closed, bounded reference and generation validation at the head.
    generation = value["generation"]
    if type(generation) is not int or generation < 1:
        raise ValueError("Invalid Drive transaction generation")
    head_body(dict(format=HEAD_FORMAT, workspace_id=workspace_id,
                   generation=generation - 1, commit=value["previous"]))
    if encode(value, MAX_INLINE) != raw:
        raise ValueError("Drive transaction must use canonical bytes")
    return value


@dataclass(frozen=True)
class Page:
    """Oldest-first transactions; commit the anchor with their local application."""

    transactions: tuple[bytes, ...]
    anchor: bytes
    caught_up: bool


class DriveLog:
    """One explicit private account/workspace/root; never automatic research upload."""

    def __init__(self, files: DriveFiles, folder, head_id, workspace_id):
        self.files = files
        self.folder, self.head_id = identifier(folder), identifier(head_id)
        _identifier(workspace_id)
        self.workspace_id = workspace_id

    def head(self):
        return self.files.read_head(self.head_id, self.folder, self.workspace_id)

    def append(self, observed: Head, object_id, payload):
        """Publish captured bytes; caller retains the same ID and intent for retry.

        A lost response is reconciled through read_since, not by treating absence
        of a local acknowledgment as proof that the cloud accepted nothing.
        """
        if (not isinstance(observed, Head) or observed.file_id != self.head_id
                or observed.workspace_id != self.workspace_id):
            raise ValueError("Read this workspace's Drive head before appending")
        if self.files.check_head(observed) != self.folder:
            raise ValueError("Drive head moved to another workspace folder")
        before = observed.value()
        raw = encode(dict(format=FORMAT, workspace_id=self.workspace_id,
                          generation=before["generation"] + 1,
                          previous=before["commit"], payload=payload), MAX_INLINE)
        transaction(raw, self.workspace_id)
        self.files.put_small(object_id, self.folder, self.workspace_id, "commit", raw)
        return self.files.publish_head(observed, reference(object_id, raw))

    def read_since(self, anchor: bytes, *, limit=MAX_PAGE, maximum=MAX_PAGE_BYTES):
        """Prove the captured prefix before returning any research for application.

        A changed, missing or rolled-back head is an error, never an empty list.
        The caller persists Page.anchor only in the research receive transaction.
        """
        if (type(limit) is not int or not 1 <= limit <= MAX_PAGE
                or type(maximum) is not int or not 1 <= maximum <= MAX_PAGE_BYTES):
            raise ValueError("Invalid Drive receive budget")
        prior = decode(anchor)
        if head_body(prior) != anchor or prior["workspace_id"] != self.workspace_id:
            raise ValueError("Invalid local Drive anchor")
        observed = self.head().value()
        if observed["generation"] < prior["generation"]:
            raise SyncHistoryUnavailable("Drive history moved behind locally retained work")
        # Walk immutable parent references, rather than a mutable change-feed cursor.
        current, generation = observed["commit"], observed["generation"]
        newest, used = [], 0
        while generation > prior["generation"]:
            self.files.check()
            if len(newest) >= limit:
                # Do not discard proof or advance an anchor over an unverified gap.
                raise SyncHistoryUnavailable("Drive catch-up exceeds this bounded history page")
            raw = self.files.read_small(current, self.folder, self.workspace_id)
            used += len(raw)
            if used > maximum:
                raise SyncHistoryUnavailable("Drive catch-up exceeds its byte budget")
            item = transaction(raw, self.workspace_id)
            if item["generation"] != generation:
                raise SyncHistoryUnavailable("Drive transaction ancestry has a generation gap")
            newest.append(raw)
            current, generation = item["previous"], generation - 1
        if current != prior["commit"]:
            raise SyncHistoryUnavailable("Drive history replaced a locally retained prefix")
        return Page(tuple(reversed(newest)), head_body(observed), True)
