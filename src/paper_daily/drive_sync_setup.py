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
        self._consent = None

    def check(self, ticket):
        ticket.check()
        self.binding._check()

    def sign_in(self, ticket, progress):
        self.check(ticket)
        self.files = self.account = self._library_view = None
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

    def overview(self, ticket, progress):
        """Read settings for the current Drive session without requesting authorization."""
        self.check(ticket)
        if self.files is None or self.account is None:
            raise PermissionError("Sign in to Google Drive first")
        self.files.cancelled = lambda: ticket.cancelled
        rows = self.files.workspaces()
        library = self.read_library(ticket)
        return {
            "account": self.account,
            "workspaces": rows,
            "lists": library["local"],
            "library": library,
        }

    def read_library(self, ticket):
        """Discover names and device intent without creating or transferring research."""
        self.check(ticket)
        files = self.files
        files.cancelled = lambda: ticket.cancelled
        directories = files.workspaces(directories=True)
        if len(directories) > 1:
            raise ValueError("Multiple personal library directories found; review them first")
        library_id = "personal"
        store = DeviceSelection(
            self.workspace.path,
            owner_id=self.account["id"],
            library_id=library_id,
            device_id=self.binding.account,
            current_path=self.workspace.current_path,
            root=self.profiles.parent / "Paperfact-settings" / "library-sync",
        )
        local = inspect_lists(self.workspace.path, library_id, ticket=ticket)
        remote = observation = None
        if directories:
            spec = directories[0]
            remote = DriveDirectory(files, spec["folder_id"], spec["head_id"], library_id)
            observation = remote.read()
        base = observation.directory if observation else Directory(library_id, 0, ())
        merged = {item.id: item for item in local.lists}
        merged.update((item.id, item) for item in base.lists)
        visible = Directory(library_id, base.generation, tuple(merged[k] for k in sorted(merged)))
        selection = store.load()
        self.check(ticket)
        self._library_view = (files, store, selection, remote, observation, local, visible)
        return {
            "ordinary": local_binding(self.workspace.path) is None,
            "note_lists": store.note_lists(),
            "items": checklist(
                visible, selection.selected, local_ids=[item.id for item in local.lists]
            ),
            "local": [{"id": item.id, "name": item.name} for item in local.lists],
        }

    def review_notes(self, list_id, ticket, progress, *, decision=None):
        from paper_daily.drive_note_review import review

        self.check(ticket)
        if self._library_view is None:
            raise ValueError("Open your library directory first")
        files, store, saved, remote, *_ = self._library_view
        if files is not self.files or store.owner_id != self.account["id"] or remote is None:
            raise ValueError("The reviewed account or directory changed")
        files.cancelled = lambda: ticket.cancelled
        return review(remote, store, list_id, saved.revision, ticket, decision)

    def choose_note_sync(self, list_id, enabled, ticket, progress):
        self.check(ticket)
        if self._library_view is None or local_binding(self.workspace.path):
            raise ValueError("Review the ordinary library first")
        files, store, saved, *_ = self._library_view
        if files is not self.files or store.owner_id != self.account["id"]:
            raise ValueError("The reviewed account changed")
        store.set_note_sync(list_id, enabled, revision=saved.revision, ticket=ticket)
        return self.read_library(ticket)

    def save_library(self, selected, ticket, progress, *, intermediate=False):
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
                   intermediate=intermediate)
        return self.read_library(ticket)

    def apply_library(self, selected, ticket, progress):
        result = self.save_library(selected, ticket, progress, intermediate=True)
        return self._exchange_saved(result, ticket, progress)

    def sync_saved_library(self, ticket, progress):
        """Exchange only previously saved subscriptions under the current sign-in."""
        self.check(ticket)
        if self.files is None or self.account is None:
            raise PermissionError("Sign in to Google Drive first")
        result = self.read_library(ticket)
        _, store, selection, _, observed, *_ = self._library_view
        if not selection.selected or local_binding(self.workspace.path):
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

    def _exchange_saved(self, result, ticket, progress, *, selection=None):
        from paper_daily.drive_list_records import ListReviewRequired, exchange_list

        _, store, saved, directory, *_ = self._library_view
        selection = saved if selection is None else selection
        if local_binding(self.workspace.path) or not selection.selected:
            return {**result, "reviews": {}}
        from paper_daily.drive_reader_notes import NoteEditConflict, exchange_reader_notes

        reviews = {}
        note_conflicts = []
        selected = sorted(selection.selected)
        for index, list_id in enumerate(selected):
            ticket.check()
            progress({"stage": "selected_lists", "completed": index, "total": len(selected)})
            try:
                state = exchange_list(directory, store, list_id, selection.revision, ticket)
                if state in ("updated", "current"):
                    from paper_daily.drive_paper_receive import exchange_bibliography

                    exchange_bibliography(directory, store, list_id, selection.revision, ticket)
                    if list_id in result.get("note_lists", ()):
                        exchange_reader_notes(directory, store, list_id, selection.revision, ticket)
            except NoteEditConflict as exc:
                reviews[list_id] = str(exc)
                note_conflicts.append(list_id)
            except ListReviewRequired as exc:
                reviews[list_id] = str(exc)
        return {**self.read_library(ticket), "reviews": reviews, "note_conflicts": note_conflicts}

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
