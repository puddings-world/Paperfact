"""Explicit personal Drive enrollment and new-device joining for desktop workers."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from uuid import uuid4, uuid5

from paper_daily import google_slides, sync_bootstrap
from paper_daily.connection_vault import ConnectionVault, native_backend
from paper_daily.device_list_selection import DeviceSelection
from paper_daily.drive_library_directory import DriveDirectory
from paper_daily.drive_sync_credentials import DriveVault
from paper_daily.drive_sync_factory import TransportFactory, origin
from paper_daily.drive_sync_files import FORMAT, DriveFiles, decode, head_body
from paper_daily.library_directory import Directory, ListEntry, checklist, inspect_lists
from paper_daily.presentations import _atomic_json
from paper_daily.runtime import user_cache_dir, user_data_dir
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import WorkspaceService
from paper_daily.workspace_sync import SyncSession, local_binding

PENDING = "io.github.puddings-world.paperfact.drive-pending"


class DriveSetup:
    def __init__(
        self,
        database,
        *,
        current_path=None,
        backend=native_backend,
        profiles=None,
        cache=None,
        startup_dir=None,
        authorize=google_slides.authorize,
    ):
        self.workspace = WorkspaceService(database, current_path=current_path)
        self.vault_options = {"backend": backend}
        if startup_dir is not None:
            self.vault_options["startup_dir"] = startup_dir
        self.binding = ConnectionVault(self.workspace, **self.vault_options)
        self.backend, self.authorize = backend, authorize
        self.profiles = Path(profiles or user_data_dir().with_name("Paperfact-workspaces"))
        self.cache = Path(cache or user_cache_dir() / "drive-setup")
        self.files = self.account = None
        self._library_view = None
        self._list_target = None
        self._consent = None
        self._pdf_versions = {}
        self._pdf_review_titles = {}
        self._membership_conflicts = {}

    def check(self, ticket):
        ticket.check()
        self.binding._check()

    def sign_in(self, ticket, progress):
        self.check(ticket)
        if self.library_startup_record():
            self.disable_library_startup(ticket)
        self.files = self.account = self._library_view = None
        self._pdf_review_titles.clear()
        self._membership_conflicts.clear()
        self._list_target = None
        progress({"stage": "google_login"})
        session = self.authorize(cancelled=lambda: ticket.cancelled)
        self.check(ticket)
        files = DriveFiles(session, cancelled=lambda: ticket.cancelled)
        account = files.account()
        self.check(ticket)
        self.files, self.account = files, account
        self._library_view = None
        try:
            return self.overview(ticket, progress)
        except Exception:
            self.files = self.account = self._library_view = None
            files.close()
            raise

    def remember_library(self, ticket, *, startup=False):
        """Save the reviewed ordinary library grant after explicit device opt-in."""
        self.check(ticket)
        if self._library_view is None or self.files is None:
            raise ValueError("Review the library before remembering Google authorization")
        files, store, selected, directory, *_ = self._library_view
        if (files is not self.files or directory is None or not selected.selected
                or store.owner_id != self.account["id"] or store.load() != selected):
            raise ValueError("Save the current list selection before remembering this library")
        vault = DriveVault(self.workspace, library=True, **self.vault_options)
        grant = vault.remember(files, directory.folder, directory.head, directory.key, ticket,
                               owner_id=store.owner_id)
        if startup:
            vault.library_startup(grant, ticket)

    def library_startup_record(self):
        import sqlite3

        try:
            vault = DriveVault(self.workspace, library=True, **self.vault_options)
            return vault.binding.startup_record()
        except (OSError, ValueError, sqlite3.Error):
            return None

    def disable_library_startup(self, ticket):
        self.check(ticket)
        vault = DriveVault(self.workspace, library=True, **self.vault_options)
        vault.binding.startup_path.unlink(missing_ok=True)

    def reconnect_library(self, ticket, progress, *, startup_record=None):
        """Restore a device grant without opening a browser or transferring research."""
        self.check(ticket)
        if local_binding(self.workspace.path) is not None:
            raise PermissionError("Open the original local library to reconnect its saved lists")
        if self.files is not None:
            raise ValueError("Close the active Google session before restoring a saved library")
        vault = DriveVault(self.workspace, library=True, **self.vault_options)
        if startup_record is not None and vault.binding.startup_record() != startup_record:
            raise PermissionError("Automatic library reconnect is disabled")
        grant = vault.load(ticket)
        if grant is None:
            raise PermissionError("Sign in and remember this library on this device first")
        if startup_record is not None and (
            hashlib.sha256(grant.encoded().encode()).hexdigest() != startup_record
            or vault.binding.startup_record() != startup_record
        ):
            raise PermissionError("The saved library startup authorization changed")
        if startup_record is not None:
            store = self._device_selection(grant.owner_id)
            selection = store.load()
            scopes = {key: (store, grant.folder_id, grant.head_id, key, selection.revision)
                      for key in store.position_lists() if key in selection.selected}
            self.check(ticket)
            if vault.binding.startup_record() != startup_record:
                raise PermissionError("Automatic library reconnect is disabled")
            progress({"stage": "local_page_scopes", "stamp": startup_record, "scopes": scopes})
        files = DriveFiles(grant.session(), cancelled=lambda: ticket.cancelled)
        try:
            owner = files.account()
            if owner["id"] != grant.owner_id:
                raise PermissionError("The saved Google account changed; sign in again")
            self.check(ticket)
            self._list_target = grant.folder_id, grant.head_id
            self.files, self.account = files, owner
            result = self.overview(ticket, progress)
            if startup_record is not None and vault.binding.startup_record() != startup_record:
                raise PermissionError("Automatic library reconnect is disabled")
            self.check(ticket)
            return result
        except Exception:
            self.files = self.account = self._library_view = self._list_target = None
            files.close()
            raise

    def forget_library(self, ticket):
        DriveVault(self.workspace, library=True, **self.vault_options).forget(ticket)

    def overview(self, ticket, progress):
        """Read settings for the current Drive session without requesting authorization."""
        self.check(ticket)
        if self.files is None or self.account is None:
            raise PermissionError("Sign in to Google Drive first")
        self.files.cancelled = lambda: ticket.cancelled
        rows = self.files.workspaces()
        if local_binding(self.workspace.path) is not None:
            return {"account": self.account, "workspaces": rows, "lists": [], "bound": True}
        library = self.read_library(ticket)
        return {
            "account": self.account,
            "workspaces": rows,
            "lists": library["local"],
            "library": library,
        }

    def _device_selection(self, owner_id):
        return DeviceSelection(
            self.workspace.path, owner_id=owner_id, library_id="personal",
            device_id=self.binding.account, current_path=self.workspace.current_path,
            root=self.profiles.parent / "Paperfact-settings" / "library-sync",
        )

    def read_library(self, ticket, *, expected_directory=None):
        """Discover names and device intent without creating or transferring research."""
        self.check(ticket)
        files = self.files
        files.cancelled = lambda: ticket.cancelled
        directories = files.workspaces(directories=True)
        if len(directories) > 1:
            raise ValueError("Multiple personal library directories found; review them first")
        expected_directory = expected_directory or self._list_target
        if expected_directory is not None and (
            not directories or files.account()["id"] != self.account["id"]
            or (directories[0]["folder_id"], directories[0]["head_id"]) != expected_directory
        ):
            raise ValueError("The selected Drive directory changed; reopen the list settings")
        library_id = "personal"
        store = self._device_selection(self.account["id"])
        local = inspect_lists(self.workspace.path, library_id, ticket=ticket)
        remote = observation = None
        if directories:
            spec = directories[0]
            args = files, spec["folder_id"], spec["head_id"], library_id
            remote = DriveDirectory(*args, membership_restores=True, positions=True)
            observation = remote.read()
            entries = observation.directory.lists
            has_positions = any(entry.positions_head for entry in entries)
            # Ordinary directories keep their inexpensive unchanged-bibliography path.
            # A concurrent upgrade will invalidate a legacy snapshot on its next read.
            remote = DriveDirectory(
                *args, positions=has_positions,
                membership_changes=any(entry.membership_changes_head for entry in entries),
                membership_restores=any(entry.restored_memberships for entry in entries),
            )
        base = observation.directory if observation else Directory(library_id, 0, ())
        merged = {item.id: item for item in local.lists}
        merged.update((item.id, item) for item in base.lists)
        visible = Directory(library_id, base.generation, tuple(merged[k] for k in sorted(merged)))
        selection = store.load()
        self.check(ticket)
        self._library_view = (files, store, selection, remote, observation, local, visible)
        if remote is not None:
            self._list_target = (remote.folder, remote.head)
        pdf_lists = store.pdf_lists()
        self._membership_conflicts = {
            key: value for key, value in self._membership_conflicts.items()
            if key[0] is files and key[1] == store.context and key[2] in selection.selected
        }
        return {
            "ordinary": local_binding(self.workspace.path) is None,
            "first_selection": selection.revision == 0,
            "membership_conflicts": {k[2]: v for k, v in self._membership_conflicts.items()},
            "reading_lists": store.reading_lists(),
            "position_lists": store.position_lists(),
            "note_lists": store.note_lists(),
            "pdf_lists": pdf_lists,
            "pdf_review_titles": {key: self._pdf_review_titles[key] for key in pdf_lists
                                  if key in selection.selected and key in self._pdf_review_titles},
            "dive_lists": store.dive_lists(),
            "items": checklist(
                visible, selection.selected, local_ids=[item.id for item in local.lists]
            ),
            "local": [{"id": item.id, "name": item.name} for item in local.lists],
        }

    def review_notes(self, list_id, ticket, progress, *, decision=None, feature="note"):
        if feature == "dive":
            from paper_daily.drive_reader_dives import review_dives as review
        elif feature == "list":
            from paper_daily.drive_list_records import review_list as review
        elif feature == "reading":
            from paper_daily.drive_reader_progress import review_reading as review
        elif feature == "note":
            from paper_daily.drive_note_review import review
        else:
            raise ValueError("Unknown review feature")

        self.check(ticket)
        if self._library_view is None:
            raise ValueError("Open your library directory first")
        files, store, saved, remote, *_ = self._library_view
        if files is not self.files or store.owner_id != self.account["id"] or remote is None:
            raise ValueError("The reviewed account or directory changed")
        files.cancelled = lambda: ticket.cancelled
        return review(remote, store, list_id, saved.revision, ticket, decision)

    def choose_position_sync(self, list_id, enabled, ticket, progress):
        return self._choose_list_content(list_id, enabled, ticket, kind="positions")

    def choose_reading_sync(self, list_id, enabled, ticket, progress):
        return self._choose_list_content(list_id, enabled, ticket, kind="reading")

    def choose_note_sync(self, list_id, enabled, ticket, progress):
        return self._choose_list_content(list_id, enabled, ticket, kind="notes")

    def choose_pdf_sync(self, list_id, enabled, ticket, progress):
        return self._choose_list_content(list_id, enabled, ticket, kind="pdfs")

    def choose_dive_sync(self, list_id, enabled, ticket, progress):
        return self._choose_list_content(list_id, enabled, ticket, kind="dives")

    def _choose_list_content(self, list_id, enabled, ticket, *, kind):
        self.check(ticket)
        if self._library_view is None or local_binding(self.workspace.path):
            raise ValueError("Review the ordinary library first")
        files, store, saved, *_ = self._library_view
        if files is not self.files or store.owner_id != self.account["id"]:
            raise ValueError("The reviewed account changed")
        save = {"reading": store.set_reading_sync, "notes": store.set_note_sync,
                "positions": store.set_position_sync, "pdfs": store.set_pdf_sync,
                "dives": store.set_dive_sync}[kind]
        save(list_id, enabled, revision=saved.revision, ticket=ticket)
        if kind == "pdfs" and not enabled:
            self._pdf_review_titles.pop(list_id, None)
        return self.read_library(ticket)

    def save_library(self, selected, ticket, progress, *, intermediate=False,
                     include_new_content=False, follow_new=False):
        """Publish the reviewed local names and persist this device's selection."""
        self.check(ticket)
        if self._library_view is None:
            raise ValueError("Sign in and review your list directory first")
        files, store, selection, remote, observed, local, visible = self._library_view
        if files is not self.files or not set(selected) <= {item.id for item in visible.lists}:
            raise ValueError("List selection or Google account changed; refresh first")
        files.cancelled = lambda: ticket.cancelled
        latest = inspect_lists(self.workspace.path, local.library_id, ticket=ticket)
        if latest != local:
            raise ValueError("Local lists changed; refresh before publishing their names")
        if remote is None:
            if files.workspaces(directories=True):
                raise ValueError("Another device created the directory; sign in again to refresh")
            path = self._receipt("personal-directory")
            if path.exists():
                ids = decode(path.read_bytes())
            else:
                folder, head = files.new_ids(2)
                ids = {"folder": folder, "head": head}
                self.cache.mkdir(parents=True, exist_ok=True)
                _atomic_json(path, ids)
            remote = DriveDirectory(files, ids["folder"], ids["head"], local.library_id)
            observed = remote.initialize("Paperfact library")
        self.check(ticket)
        existing = {item.id for item in observed.directory.lists}
        additions = [
            ListEntry(item.id, item.name, False) for item in local.lists if item.id not in existing
        ]
        if additions:
            updated = remote.upsert(observed, additions)
        else:
            updated = remote.read()
            before, after = observed.directory, updated.directory
            if after.generation < before.generation or (
                after.generation == before.generation and after.digest != before.digest
            ):
                raise ValueError("Directory history changed; review before syncing")
        self.check(ticket)
        store.save(updated.directory, selected, expected_revision=selection.revision, ticket=ticket,
                   intermediate=intermediate, include_new_content=include_new_content,
                   reviewed_ids=[item.id for item in visible.lists], follow_new=follow_new)
        return self.read_library(ticket, expected_directory=(remote.folder, remote.head))

    def apply_library(self, selected, ticket, progress, *, include_new_content=False):
        result = self.save_library(selected, ticket, progress, intermediate=True,
                                   include_new_content=include_new_content)
        return self._exchange_saved(result, ticket, progress)

    def follow_future_lists(self, ticket, progress):
        """Upgrade a previously saved selection after explicit startup sign-in."""
        self.check(ticket)
        if not self._library_view:
            raise ValueError("Review the directory before enabling automatic sync")
        selected = self._library_view[2].selected
        result = self.save_library(sorted(selected), ticket, progress,
                                   intermediate=True, follow_new=True)
        return self._exchange_saved(result, ticket, progress)

    def sync_saved_library(self, ticket, progress):
        """Exchange only previously saved subscriptions under the current sign-in."""
        self.check(ticket)
        if self.files is None or self.account is None:
            raise PermissionError("Sign in to Google Drive first")
        view = self._library_view
        if view is None or view[0] is not self.files or view[1].owner_id != self.account["id"]:
            raise ValueError("Review the list settings before syncing this Google account")
        remote = view[3]
        if remote is None:
            if view[2].selected:
                raise ValueError("Drive directory missing; reopen the list settings")
            return {**self.read_library(ticket), "reviews": {}}
        result = self.read_library(ticket)
        _, store, selection, _, observed, _, visible = self._library_view
        if local_binding(self.workspace.path):
            return {**result, "reviews": {}}
        if observed is not None:
            fresh = store.new_subscriptions((item.id for item in visible.lists), selection.revision)
            if fresh:
                return self.apply_library(sorted(selection.selected | fresh), ticket, progress,
                                          include_new_content=True)
        if not selection.selected:
            return {**result, "reviews": {}}
        if observed is None or not selection.selected.issubset(
            item.id for item in observed.directory.lists
        ):
            raise ValueError("The saved list directory changed; review your selection")
        # Validate the directory checkpoint using the same revision guard as manual setup.
        accepted = store.save(
            observed.directory, sorted(selection.selected), expected_revision=selection.revision,
            ticket=ticket, intermediate=True,
        )
        return self._exchange_saved(result, ticket, progress, selection=accepted)

    def accept_membership_removal(self, list_id, detail, ticket, progress, *, keep=False):
        from paper_daily.drive_membership_apply import (
            keep_reviewed_membership,
            receive_membership_changes,
        )
        from paper_daily.drive_membership_history import membership_history

        self.check(ticket)
        if not self._library_view:
            raise ValueError("Open the list settings and review again")
        files, store, saved, remote, *_ = self._library_view
        if (not remote or not remote.membership_changes or files is not self.files
                or store.owner_id != self.account["id"] or list_id not in saved.selected
                or not detail.get("observation")
                or self._membership_conflicts.get((files, store.context, list_id)) != detail):
            raise ValueError("The reviewed membership changed; sync again")
        files.cancelled = lambda: ticket.cancelled
        if keep:
            remote = DriveDirectory(files, remote.folder, remote.head, remote.library_id,
                                    membership_restores=True, positions=remote.positions)
        history = membership_history(remote, store, list_id, revision=saved.revision)
        if keep:
            keep_reviewed_membership(history, saved.revision, detail["observation"], ticket)
        else:
            receive_membership_changes(history, saved.revision, ticket,
                                       accept_removal=detail["observation"])
        return self.sync_saved_library(ticket, progress)

    def adopt_membership_sync(self, list_id, proposal, ticket, progress):
        """Upgrade this directory only for the reviewed, still-pending local removals."""
        from paper_daily.drive_membership_history import DriveMembershipChanges, removal_operation

        self.check(ticket)
        if self._library_view is None:
            raise ValueError("Review the list settings before upgrading")
        files, store, saved, remote, *_ = self._library_view
        if (remote is None or remote.membership_changes or files is not self.files
                or local_binding(self.workspace.path) or store.owner_id != self.account["id"]
                or list_id not in saved.selected or proposal["binding"] != (
                    store.context, remote.folder, remote.head, list_id, saved.revision)):
            raise ValueError("The reviewed library changed; sync again")
        files.cancelled = lambda: ticket.cancelled
        upgraded = DriveDirectory(files, remote.folder, remote.head, remote.library_id,
                                  membership_changes=True, positions=remote.positions)
        history = DriveMembershipChanges(upgraded, store, list_id, revision=saved.revision)
        operations = [removal_operation(history.creations[key], store.context)
                      for key in proposal["members"] if key in history.creations]
        if (not operations or [op["operation_id"] for op in operations] != proposal["ids"]
                or any(e.membership_changes_head for e in upgraded.read().directory.lists)):
            raise ValueError("The reviewed removals changed; sync again")
        ticket.check()
        history.append(None, operations[:history.max_operations], revision=saved.revision)
        return self.sync_saved_library(ticket, progress)

    def _exchange_saved(self, result, ticket, progress, *, selection=None):
        from paper_daily.drive_list_records import (
            ListDetailsConflict,
            ListReviewRequired,
            exchange_list,
        )
        from paper_daily.drive_membership_apply import MembershipConflict, arm_present_review
        from paper_daily.drive_membership_intent import MembershipRemovalReview

        _, store, saved, directory, *_ = self._library_view
        selection = saved if selection is None else selection
        if local_binding(self.workspace.path) or not selection.selected:
            return {**result, "reviews": {}}
        from paper_daily.drive_reader_notes import NoteEditConflict, exchange_reader_notes

        reviews = {}
        upgrades = {}
        membership_conflicts = {}
        list_conflicts = []
        reading_conflicts = set()
        note_conflicts = []
        dive_conflicts = set()
        pdf_conflicts = set()
        pdf_titles = {}
        position_suggestions = {}
        position_grants = {}
        selected = sorted(selection.selected)
        for index, list_id in enumerate(selected):
            ticket.check()
            progress({"stage": "selected_lists", "completed": index, "total": len(selected)})
            try:
                state = exchange_list(directory, store, list_id, selection.revision, ticket)
                if state in ("updated", "current"):
                    from paper_daily.drive_paper_receive import exchange_bibliography

                    exchange_bibliography(directory, store, list_id, selection.revision, ticket)
                    if list_id in result.get("pdf_lists", ()):
                        from paper_daily.drive_reader_originals import exchange_originals

                        differing = exchange_originals(
                            directory, self.cache, store, list_id, selection.revision, ticket,
                            self._pdf_versions,
                        )
                        if differing:
                            pdf_conflicts.add(list_id)
                            pdf_titles[list_id] = sorted(differing, key=str.casefold)
                            count = len(differing)
                            reviews[list_id] = f"The local PDF differs from Drive ({count})"
                    if list_id in result.get("dive_lists", ()):
                        from paper_daily.drive_reader_dives import exchange_dives

                        if exchange_dives(directory, store, list_id, selection.revision, ticket):
                            dive_conflicts.add(list_id)
                            reason = "Saved explanations differ; review both versions"
                            reasons = (reviews.get(list_id), reason)
                            reviews[list_id] = " · ".join(filter(None, reasons))
                    if list_id in result.get("reading_lists", ()):
                        from paper_daily.drive_reader_progress import exchange_reading

                        differing = exchange_reading(directory, store, list_id, selection.revision,
                                                     ticket)
                        if differing:
                            reading_conflicts.add(list_id)
                            reason = f"Reading progress differs on {len(differing)} papers"
                            reasons = (reviews.get(list_id), reason)
                            reviews[list_id] = " · ".join(filter(None, reasons))
                    if list_id in result.get("position_lists", ()):
                        from paper_daily.drive_list_history import DriveListPositions
                        from paper_daily.drive_position_cache import retain
                        from paper_daily.drive_position_publish import publish_recorded

                        if not directory.positions:
                            directory = DriveDirectory(
                                directory.files, directory.folder, directory.head,
                                directory.library_id, positions=True,
                                membership_changes=directory.membership_changes,
                                membership_restores=directory.membership_restores,
                            )
                        history = DriveListPositions(directory, store, list_id,
                                                     revision=selection.revision)
                        history.check_source = ticket.check
                        head, tips = history.suggestions(revision=selection.revision)
                        if publish_recorded(history, tips, selection.revision, ticket):
                            head, tips = history.suggestions(revision=selection.revision)
                        position_grants[list_id] = history.grant
                        position_suggestions[list_id] = retain(
                            history, head, tips, selection.revision, ticket
                        )
                    if list_id in result.get("note_lists", ()):
                        exchange_reader_notes(directory, store, list_id, selection.revision, ticket)
            except MembershipConflict as exc:
                if exc.detail["kind"] != "absent":
                    arm_present_review(store, list_id, exc.detail, ticket)
                reviews[list_id] = str(exc)
                membership_conflicts[list_id] = exc.detail
            except MembershipRemovalReview as exc:
                reviews[list_id] = str(exc)
                if not directory.membership_changes and exc.missing == len(exc.operations):
                    upgrades[list_id] = {
                        "binding": (store.context, directory.folder, directory.head,
                                    list_id, selection.revision),
                        "ids": [op["operation_id"] for op in exc.operations],
                        "members": [op["entity_id"] for op in exc.operations],
                    }
            except ListDetailsConflict as exc:
                reviews[list_id] = str(exc)
                list_conflicts.append(list_id)
            except NoteEditConflict as exc:
                reviews[list_id] = " · ".join(filter(None, (reviews.get(list_id), str(exc))))
                note_conflicts.append(list_id)
            except ListReviewRequired as exc:
                reading_conflicts.discard(list_id)
                pdf_conflicts.discard(list_id)
                dive_conflicts.discard(list_id)
                reviews[list_id] = str(exc)
        self.check(ticket)
        self._membership_conflicts = {(self.files, store.context, key): detail
                                      for key, detail in membership_conflicts.items()}
        self._pdf_review_titles = pdf_titles
        refreshed = self.read_library(ticket)
        for key in list(position_suggestions):
            if (key not in refreshed["position_lists"]
                    or store.position_grant(key, selection.revision) != position_grants[key]):
                del position_suggestions[key]
        return {**refreshed, "position_suggestions": position_suggestions,
                "reviews": reviews, "membership_upgrades": upgrades,
                "note_conflicts": note_conflicts,
                "list_conflicts": list_conflicts, "reading_conflicts": sorted(reading_conflicts),
                "dive_conflicts": sorted(dive_conflicts), "pdf_conflicts": sorted(pdf_conflicts)}

    def _receipt(self, kind, spec=None):
        if self.files is None:
            raise PermissionError("Sign in to Google Drive first")
        scope = self.binding.account + self.account["id"] + kind
        if spec is not None:
            scope += spec["folder_id"]
        path = self.cache / (hashlib.sha256(scope.encode()).hexdigest() + ".json")
        return path

    def _pending(self, receipt, device):
        key = self.binding.account + "." + receipt["request"]
        backend = self.backend()
        raw = backend.get_password(PENDING, key)
        if raw is None:
            raw = json.dumps({"device_id": device, "credential": secrets.token_urlsafe(32)})
            backend.set_password(PENDING, key, raw)
        value = decode(raw.encode())
        if set(value) != {"device_id", "credential"} or value["device_id"] != device:
            raise ValueError("Pending Drive enrollment belongs to another device")
        return value["credential"]

    def _factory(self, database, spec):
        workspace = WorkspaceService(database)
        return TransportFactory(
            workspace,
            files=self.files,
            descriptor=spec,
            owner_id=self.account["id"],
            backend=self.backend,
            cache_root=self.cache / "replicas",
        )

    def _activate(self, database, spec, device, credential, ticket, progress):
        self.check(ticket)
        factory = self._factory(database, spec)
        endpoint = origin(spec["folder_id"])
        # Browser permission alone never uploads research. This explicit action enrolls the device.
        with factory(endpoint) as transport:
            transport.authority.invoke(
                "enroll", spec["workspace_id"], device, credential=credential
            )
        session = SyncSession(database, transport_factory=factory)
        session.connect(endpoint, spec["workspace_id"], device, credential, ticket)
        self.check(ticket)
        DriveVault(session.workspace, backend=self.backend).remember(
            self.files, spec["folder_id"], spec["head_id"], spec["workspace_id"], ticket
        )
        self.check(ticket)
        vault = ConnectionVault(session.workspace, **self.vault_options)
        previous = vault.startup_record()
        vault.set_startup(session, True, ticket)
        self._consent = vault, vault.startup_record(), previous
        try:
            self.check(ticket)
        except BaseException:
            self.rollback_consent()
            raise
        progress({"stage": "connected"})
        return session

    def rollback_consent(self):
        if self._consent is None:
            return
        vault, stamp, previous = self._consent
        self._consent = None
        if vault.current() and stamp is not None and vault.startup_record() == stamp:
            if previous is None:
                vault.startup_path.unlink(missing_ok=True)
            else:
                _atomic_json(vault.startup_path, {"format": 1, "connection": previous})

    def create(self, name, ticket, progress, *, pdfs=None, list_ids=None):
        self.check(ticket)
        self.files.cancelled = lambda: ticket.cancelled
        bound = local_binding(self.workspace.path)
        if bound:
            saved = DriveVault(self.workspace, backend=self.backend).load(ticket)
            if saved is not None:
                if saved.owner_id != self.account["id"]:
                    raise PermissionError("Choose this workspace's original Google account")
                spec = dict(
                    folder_id=saved.folder_id,
                    head_id=saved.head_id,
                    workspace_id=saved.workspace_id,
                )
                connection = self.binding.load(ticket)
                if (
                    connection is None
                    or connection.workspace_id != bound["workspace_id"]
                    or connection.device_id != bound["device_id"]
                    or connection.endpoint != origin(saved.folder_id)
                ):
                    raise PermissionError("Saved device connection is missing; join separately")
                session = self._activate(
                    self.workspace.path,
                    spec,
                    bound["device_id"],
                    connection.token,
                    ticket,
                    progress,
                )
                return dict(
                    database=str(self.workspace.path),
                    session=session,
                    descriptor=spec,
                    copied=False,
                )
        kind = "create"
        if list_ids is not None:
            scope = json.dumps(sorted(set(list_ids)), separators=(",", ":"))
            kind += "-" + hashlib.sha256(scope.encode()).hexdigest()
        receipt_path = self._receipt(kind)
        self.profiles.mkdir(parents=True, exist_ok=True)
        if receipt_path.exists():
            receipt = decode(receipt_path.read_bytes())
        else:
            request = uuid4()
            bound = local_binding(self.workspace.path)
            workspace = bound["workspace_id"] if bound else str(uuid5(request, "workspace"))
            folder, head = self.files.new_ids(2)
            receipt = dict(
                request=str(request),
                destination=str(
                    self.workspace.path.parent
                    if bound
                    else self.profiles / ("workspace-" + request.hex[:12])
                ),
                spec=dict(folder_id=folder, head_id=head, workspace_id=workspace),
            )
            _atomic_json(receipt_path, receipt)
        target = Path(receipt["destination"])
        database = (
            self.workspace.path if target == self.workspace.path.parent else target / "papers.db"
        )
        spec = receipt["spec"]
        if not database.exists():
            progress({"stage": "preparing_copy"})
            backups = self.profiles / "backups"
            backups.mkdir(exist_ok=True)
            source = self.workspace.path
            if list_ids is not None:
                from paper_daily.desktop.enrollment_dialog import current_pdfs
                from paper_daily.drive_sync_scope import prepare_selected

                source = prepare_selected(
                    source, list_ids, self.cache / receipt["request"] / "selected", ticket, progress
                )
                pdfs = current_pdfs(source, ticket, progress)
            EnrollmentService(source).prepare(
                target,
                backup_output=backups / (receipt["request"] + ".zip"),
                request_id=receipt["request"],
                pdfs=pdfs,
                ticket=ticket,
                progress=progress,
            )
        identity = local_binding(database, require_capture=True)
        if identity["workspace_id"] != spec["workspace_id"]:
            raise PermissionError("Prepared workspace differs from its Drive enrollment")
        self.check(ticket)
        self.files.create_folder(spec["folder_id"], spec["workspace_id"], name)
        description = head_body(
            dict(format=FORMAT, workspace_id=spec["workspace_id"], generation=0, commit=None)
        ).decode()
        self.files.put_small(
            spec["head_id"],
            spec["folder_id"],
            spec["workspace_id"],
            "head",
            b"Paperfact personal workspace",
            description=description,
        )
        credential = self._pending(receipt, identity["device_id"])
        session = self._activate(
            database, spec, identity["device_id"], credential, ticket, progress
        )
        return dict(
            database=str(database),
            session=session,
            descriptor=spec,
            copied=database != self.workspace.path,
        )

    def join(self, spec, ticket, progress):
        self.check(ticket)
        self.files.cancelled = lambda: ticket.cancelled
        self.files.read_head(spec["head_id"], spec["folder_id"], spec["workspace_id"])
        receipt_path = self._receipt("join", spec)
        self.profiles.mkdir(parents=True, exist_ok=True)
        if receipt_path.exists():
            receipt = decode(receipt_path.read_bytes())
        else:
            request = uuid4()
            receipt = dict(
                request=str(request),
                device=str(uuid4()),
                destination=str(self.profiles / ("workspace-" + request.hex[:12])),
            )
            _atomic_json(receipt_path, receipt)
        device = receipt["device"]
        credential = self._pending(receipt, device)
        factory = self._factory(self.workspace.path, spec)
        endpoint = origin(spec["folder_id"])
        with factory(endpoint) as transport:
            transport.authority.invoke(
                "enroll", spec["workspace_id"], device, credential=credential
            )
        joining = SyncSession(self.workspace.path, transport_factory=factory)
        joining.connect(endpoint, spec["workspace_id"], device, credential, ticket)
        destination = Path(receipt["destination"])
        deadline = time.monotonic() + 300
        while True:
            self.check(ticket)
            result = sync_bootstrap.join(joining, destination, ticket, progress, seconds=20)
            if result["state"] == "metadata_ready":
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Join progress saved; continue joining to finish")
        database = destination / "papers.db"
        session = self._activate(database, spec, device, credential, ticket, progress)
        return dict(database=str(database), session=session, descriptor=spec, copied=True)
