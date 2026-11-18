"""Publish list discovery separately from research content in a private Drive folder."""

from dataclasses import dataclass

from paper_daily.drive_sync_files import FORMAT, DriveChanged, Head, head_body, identifier
from paper_daily.drive_sync_log import reference
from paper_daily.library_directory import MAX_BYTES, Directory
from paper_daily.sync_journal import _identifier

PREFIX = "directory."


@dataclass(frozen=True)
class Observation:
    head: Head
    directory: Directory


class DriveDirectory:
    """One dedicated directory head, shared by devices in the same library."""

    def __init__(self, files, folder_id, head_id, library_id):
        _identifier(library_id)
        self.key = PREFIX + library_id
        _identifier(self.key)
        self.library_id = library_id
        self.files = files
        self.folder = identifier(folder_id)
        self.head = identifier(head_id)

    def initialize(self, name):
        """Reuse caller-retained object IDs after interrupted explicit setup."""
        self.files.create_folder(self.folder, self.key, name, directory=True)
        initial = head_body(dict(format=FORMAT, workspace_id=self.key, generation=0, commit=None))
        self.files.put_small(
            self.head,
            self.folder,
            self.key,
            "head",
            b"Paperfact directory",
            description=initial.decode("utf-8"),
            folder_role="directory",
        )
        return self.read()

    def read(self):
        head = self.files.read_head(self.head, self.folder, self.key, folder_role="directory")
        pointer = head.value()
        generation = pointer["generation"]
        if not generation:
            directory = Directory(self.library_id, 0, ())
        else:
            ref = pointer["commit"]
            if ref["size"] > MAX_BYTES:
                raise ValueError("Drive directory exceeds its byte budget")
            raw = self.files.read_small(ref, self.folder, self.key)
            directory = Directory.from_bytes(raw, library_id=self.library_id)
            if directory.generation != generation:
                raise ValueError("Drive directory generation differs from its head")
        return Observation(head, directory)

    def upsert(self, observed, entries):
        """Publish explicit additions/renames only. Missing local lists stay visible."""
        if (
            observed.head.file_id != self.head
            or observed.head.workspace_id != self.key
            or self.files.check_head(observed.head) != self.folder
        ):
            raise ValueError("Read this library before updating its directory")
        before = observed.directory
        pointer = observed.head.value()
        if before.library_id != self.library_id or before.generation != pointer["generation"]:
            raise ValueError("Invalid directory observation")
        if before.generation:
            if before.digest != pointer["commit"]["sha256"]:
                raise ValueError("Directory observation bytes changed")
        elif before.lists:
            raise ValueError("Unexpected initial directory entries")
        updates = Directory(self.library_id, before.generation, tuple(entries))
        merged = {item.id: item for item in before.lists}
        merged.update((item.id, item) for item in updates.lists)
        rows = tuple(sorted(merged.values(), key=lambda item: item.id))
        if rows == before.lists:
            current = self.read()
            if current.directory != before:
                raise DriveChanged("Reload the library directory before updating")
            return current
        after = Directory(self.library_id, before.generation + 1, rows)
        raw = after.to_bytes()
        (object_id,) = self.files.new_ids()
        self.files.put_small(
            object_id, self.folder, self.key, "commit", raw, folder_role="directory"
        )
        accepted = self.files.publish_head(
            observed.head, reference(object_id, raw), folder_role="directory"
        )
        return Observation(accepted, after)
