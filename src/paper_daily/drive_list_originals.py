"""Discover verified originals inside a selected list without exposing paper data in its catalog."""

from dataclasses import replace
from pathlib import Path

from paper_daily.drive_list_history import DriveListPapers
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import MAX_INLINE, decode, encode
from paper_daily.drive_sync_log import reference
from paper_daily.drive_sync_objects import DriveObjects, checked_manifest
from paper_daily.library_directory import ScopeHead
from paper_daily.sync_blobs import BlobManifest

FORMAT = "paperfact.list-originals.v1"


class DriveListOriginals:
    def __init__(self, directory, cache, store, list_id, revision, ticket, *, check_local=None):
        self.directory, self.store, self.list_id = directory, store, list_id
        self.revision, self.ticket = revision, ticket
        self.check_local = check_local
        self.grant = store.pdf_grant(list_id, revision)
        if not self.grant:
            raise PermissionError("Enable PDF sync for this list on this device")
        self.check()
        papers = DriveListPapers(directory, store, list_id)
        self.paper_head, self.members = papers.members(revision)
        self.check()
        self.objects = DriveObjects(directory.files, directory.folder, directory.key,
                                    Path(cache) / directory.folder, folder_role="directory",
                                    check=self.check)

    def check(self):
        self.ticket.check()
        if self.check_local:
            self.check_local()
        if self.store.pdf_grant(self.list_id, self.revision) != self.grant:
            raise PermissionError("This device changed its PDF sync permission")

    def member(self, paper, incarnation):
        self.check()
        if paper not in self.members or self.members[paper] != incarnation:
            raise ValueError("Original is outside this selected bibliography")

    def _record(self, generation, originals):
        return dict(format=FORMAT, library_id=self.store.library_id, list_id=self.list_id,
                    generation=generation, originals=originals)

    def _read(self):
        self.check()
        directory = self.directory
        observation = directory.read()
        entry = next((e for e in observation.directory.lists if e.id == self.list_id), None)
        if entry is None:
            raise ListReviewRequired("The selected list disappeared")
        if entry.papers_head != self.paper_head:
            raise ListReviewRequired("The bibliography changed; refresh before exchanging PDFs")
        head = entry.originals_head
        if head is None:
            self.check()
            return observation, entry, {}
        raw = directory.files.read_small(head.reference(), directory.folder, directory.key)
        value = decode(raw, MAX_INLINE)
        originals = value.get("originals") if isinstance(value, dict) else None
        if (not isinstance(originals, dict) or len(originals) > len(self.members)
                or raw != encode(self._record(head.generation, originals), MAX_INLINE)):
            raise ValueError("Invalid original index for this list")
        for paper, item in originals.items():
            if (not isinstance(item, dict) or set(item) != {"incarnation", "manifest"}
                    or paper not in self.members or self.members[paper] != item["incarnation"]):
                raise ValueError("Indexed original is outside this selected bibliography")
            checked_manifest(item["manifest"])
        self.check()
        return observation, entry, originals

    def publish(self, paper, incarnation, path, expected: BlobManifest):
        """Publish a first original. A different digest requires explicit review."""
        self.member(paper, incarnation)
        observation, entry, originals = self._read()
        if not isinstance(expected, BlobManifest):
            raise ValueError("Select an exact original before publishing")
        prior = originals.get(paper)
        if prior is not None:
            if checked_manifest(prior["manifest"])[0] != expected:
                raise ListReviewRequired("This paper already has a different original on Drive")
            return prior["manifest"]
        manifest = self.objects.put(path, expected=expected)
        generation = entry.originals_head.generation + 1 if entry.originals_head else 1
        originals[paper] = dict(incarnation=incarnation, manifest=manifest)
        raw = encode(self._record(generation, originals), MAX_INLINE)
        directory = self.directory
        self.check()
        (identity,) = directory.files.new_ids()
        directory.files.put_small(identity, directory.folder, directory.key, "commit", raw,
                                  folder_role="directory")
        head = ScopeHead(generation, **reference(identity, raw))
        self.check()
        directory.upsert(observation, [replace(entry, originals_head=head)], check=self.check)
        return manifest

    def download(self, paper, incarnation, blobs):
        self.member(paper, incarnation)
        _, _, originals = self._read()
        if paper not in originals:
            return None
        manifest = originals[paper]["manifest"]
        return self.objects.get(manifest, blobs, expected=checked_manifest(manifest)[0])
