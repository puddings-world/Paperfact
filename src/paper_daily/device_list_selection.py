"""Device-local list subscription intent; no upload, deletion or sync permission."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from paper_daily.connection_vault import ConnectionVault
from paper_daily.library_directory import MAX_BYTES, MAX_LISTS, Directory
from paper_daily.runtime import user_data_dir
from paper_daily.sync_blobs import _no_link
from paper_daily.sync_journal import _identifier
from paper_daily.workspace_service import Ticket, WorkspaceChanged, WorkspaceService

MAX_FILE_BYTES = 8 * 1024 * 1024


class SelectionChanged(ValueError):
    """Refresh the device selection before applying a different observed intent."""


@dataclass(frozen=True)
class Selection:
    revision: int = 0
    selected: frozenset[str] = frozenset()
    directory_generation: int | None = None
    directory_digest: str | None = None


class DeviceSelection:
    def __init__(self, database, *, owner_id, library_id, device_id, current_path=None, root=None):
        for identity in (owner_id, library_id, device_id):
            _identifier(identity)
        self.workspace = WorkspaceService(database, current_path=current_path)
        # Captures local file lifetime and native binding without reading a vault.
        self.binding = ConnectionVault(self.workspace)
        self.context = hashlib.sha256(
            json.dumps(
                [self.binding.account, owner_id, library_id, device_id],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        self.owner_id = owner_id
        self.library_id = library_id
        base = Path(root or user_data_dir().with_name("Paperfact-settings") / "library-sync")
        self.path = base.absolute() / (self.context + ".sqlite")
        if self.path.is_relative_to(self.workspace.path.parent):
            raise ValueError("Keep device selection settings outside the research workspace")

    def _check(self):
        self.binding._check()
        for entry in (self.path, *self.path.parents):
            _no_link(entry)
        if self.path.exists() and (
            not self.path.is_file()
            or self.path.stat().st_nlink != 1
            or self.path.stat().st_size > MAX_FILE_BYTES
        ):
            raise ValueError("Device selection store exceeds its supported bounds")

    def _load(self, conn):
        row = conn.execute(
            "SELECT context,revision,selected,generation,digest FROM selection WHERE id=1"
        ).fetchone()
        if row is None:
            return Selection()
        context, revision, raw, generation, digest = row
        if (
            context != self.context
            or type(revision) is not int
            or revision < 1
            or not isinstance(raw, str)
            or len(raw.encode()) > MAX_BYTES
            or type(generation) is not int
            or not 0 <= generation < 2**53
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid device selection record")
        values = json.loads(raw)
        if not isinstance(values, list):
            raise ValueError("Invalid device list selection")
        for value in values:
            _identifier(value)
        if len(values) > MAX_LISTS or sorted(set(values)) != values:
            raise ValueError("Invalid device list selection")
        return Selection(revision, frozenset(values), generation, digest)

    def load(self):
        self._check()
        if not self.path.exists():
            return Selection()
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as conn:
            result = self._load(conn)
        self._check()
        return result

    def save(self, directory, selected, *, expected_revision, ticket=None, intermediate=False):
        """CAS-save intent. Deselect retains research; callers schedule transfer separately."""
        if not isinstance(directory, Directory) or directory.library_id != self.library_id:
            raise ValueError("Selection belongs to another library")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid observed selection revision")
        if not isinstance(selected, (list, tuple, set, frozenset)):
            raise ValueError("Select explicit library list identities")
        if len(selected) > MAX_LISTS:
            raise ValueError("Device selection exceeds its list budget")
        for identity in selected:
            _identifier(identity)
        chosen = frozenset(selected)
        if not chosen <= {item.id for item in directory.lists}:
            raise ValueError("Selected list is not in the observed directory")
        ticket = ticket or Ticket()
        ticket.check()
        self._check()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=0.2)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS selection("
                    "id INTEGER PRIMARY KEY CHECK(id=1),context TEXT NOT NULL,"
                    "revision INTEGER NOT NULL,selected TEXT NOT NULL,"
                    "generation INTEGER NOT NULL,digest TEXT NOT NULL)"
                )
                previous = self._load(conn)
                if previous.directory_generation is not None and (
                    directory.generation < previous.directory_generation
                    or (
                        directory.generation == previous.directory_generation
                        and directory.digest != previous.directory_digest
                    )
                ):
                    raise SelectionChanged(
                        "Library directory moved behind or changed its generation"
                    )
                identical = (
                    previous.selected == chosen and previous.directory_digest == directory.digest
                )
                if previous.revision != expected_revision and not identical:
                    raise SelectionChanged("Device selection changed; review it again")
                result = (
                    previous
                    if identical
                    else Selection(
                        previous.revision + 1, chosen, directory.generation, directory.digest
                    )
                )
                self._check()
                ticket.check()
                if not identical:
                    conn.execute(
                        "INSERT INTO selection VALUES(1,?,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET context=excluded.context,"
                        "revision=excluded.revision,selected=excluded.selected,"
                        "generation=excluded.generation,digest=excluded.digest",
                        (
                            self.context,
                            result.revision,
                            json.dumps(sorted(chosen), separators=(",", ":")),
                            directory.generation,
                            directory.digest,
                        ),
                    )

                removed = previous.selected - chosen
                for table in ("note_grants", "pdf_grants", "dive_grants", "reading_grants"):
                    if removed and self._has_grants(conn, table):
                        conn.executemany(f"DELETE FROM {table} WHERE list_id=?",
                                         ((identity,) for identity in removed))

                def commit():
                    self._check()
                    conn.commit()

                if intermediate:
                    ticket.checkpoint(commit)
                else:
                    ticket.publish(commit)
            except BaseException:
                conn.rollback()
                raise
        return result

    @staticmethod
    def _has_grants(conn, table):
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def note_lists(self):
        return self._grant_lists("note_grants")

    def dive_lists(self):
        return self._grant_lists("dive_grants")

    def pdf_lists(self):
        return self._grant_lists("pdf_grants")

    def _grant_lists(self, table):
        self._check()
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            selected = self._load(conn).selected
            if not self._has_grants(conn, table):
                return []
            return sorted(key for (key,) in conn.execute(f"SELECT list_id FROM {table}")
                          if key in selected)

    def note_grant(self, list_id, revision):
        return self._grant("note_grants", list_id, revision)

    def dive_grant(self, list_id, revision):
        return self._grant("dive_grants", list_id, revision)

    def reading_lists(self):
        return self._grant_lists("reading_grants")

    def reading_grant(self, list_id, revision):
        return self._grant("reading_grants", list_id, revision)

    def set_reading_sync(self, list_id, enabled, *, revision, ticket):
        self._set_grant("reading_grants", "reading-v1:", list_id, enabled, revision, ticket)

    def pdf_grant(self, list_id, revision):
        return self._grant("pdf_grants", list_id, revision)

    def _grant(self, table, list_id, revision):
        self._check()
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            saved = self._load(conn)
            if saved.revision != revision or list_id not in saved.selected:
                raise SelectionChanged("Device selection changed; review it again")
            if not self._has_grants(conn, table):
                return None
            row = conn.execute(f"SELECT grant_id FROM {table} WHERE list_id=?",
                               (list_id,)).fetchone()
        return row[0] if row else None

    def set_note_sync(self, list_id, enabled, *, revision, ticket):
        self._set_grant("note_grants", "edits-v1:", list_id, enabled, revision, ticket)

    def set_dive_sync(self, list_id, enabled, *, revision, ticket):
        self._set_grant("dive_grants", "dives-v1:", list_id, enabled, revision, ticket)

    def set_pdf_sync(self, list_id, enabled, *, revision, ticket):
        self._set_grant("pdf_grants", "pdf-v1:", list_id, enabled, revision, ticket)

    def _set_grant(self, table, prefix, list_id, enabled, revision, ticket):
        """Choices are local to one account, device, database, list and content type."""
        self._check()
        ticket.check()
        if type(enabled) is not bool:
            raise ValueError("Expected a yes/no sync choice")
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            saved = self._load(conn)
            if saved.revision != revision or list_id not in saved.selected:
                raise SelectionChanged("Device selection changed; review it again")
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table}("
                         "list_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL)")
            if enabled:
                conn.execute(f"INSERT OR IGNORE INTO {table} VALUES(?,?)",
                             (list_id, prefix + str(uuid4())))
            else:
                conn.execute(f"DELETE FROM {table} WHERE list_id=?", (list_id,))
            self._check()
            ticket.publish(conn.commit)

    def current(self):
        try:
            self._check()
        except (OSError, ValueError, sqlite3.Error, WorkspaceChanged):
            return False
        return True
