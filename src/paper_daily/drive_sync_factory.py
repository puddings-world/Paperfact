"""Lazy per-workspace transport routing; no native-vault access at construction."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from paper_daily.connection_vault import ConnectionVault
from paper_daily.drive_sync_authority import DriveAuthority
from paper_daily.drive_sync_credentials import DriveVault
from paper_daily.drive_sync_files import DriveFiles, origin
from paper_daily.drive_sync_transport import DriveTransport
from paper_daily.runtime import user_cache_dir
from paper_daily.sync_http import HttpTransport


class TransportFactory:
    def __init__(
        self,
        workspace,
        *,
        files=None,
        descriptor=None,
        owner_id=None,
        backend=None,
        cache_root=None,
        files_factory=DriveFiles,
        client_reader=None,
    ):
        self.workspace = workspace
        self.files, self.descriptor, self.owner_id = files, descriptor, owner_id
        self.options = {} if backend is None else {"backend": backend}
        self.cache_root = cache_root or user_cache_dir() / "drive-replicas"
        self.authority = None
        self.files_factory, self.client_reader = files_factory, client_reader

    def __call__(self, endpoint):
        ordinary = HttpTransport(endpoint)
        if not (urlsplit(endpoint).hostname or "").endswith(".paperfact-drive.invalid"):
            return ordinary
        ordinary.close()
        binding = ConnectionVault(self.workspace, **self.options)
        binding._check()
        if self.authority is None:
            if self.files is None:
                grant = DriveVault(self.workspace, **self.options).load()
                if grant is None:
                    raise PermissionError("Sign in to Google Drive on this device")
                options = (
                    {} if self.client_reader is None else {"client_reader": self.client_reader}
                )
                self.files = self.files_factory(grant.session(**options))
                self.owner_id = grant.owner_id
                self.descriptor = dict(
                    folder_id=grant.folder_id,
                    head_id=grant.head_id,
                    workspace_id=grant.workspace_id,
                )
            spec = self.descriptor
            if endpoint != origin(spec["folder_id"]):
                raise PermissionError("Saved Drive connection belongs to another workspace")
            key = hashlib.sha256((binding.account + self.owner_id + spec["folder_id"]).encode())
            self.authority = DriveAuthority(
                self.files,
                spec["folder_id"],
                spec["head_id"],
                spec["workspace_id"],
                self.owner_id,
                self.cache_root / key.hexdigest(),
            )
        if endpoint != origin(self.authority.log.folder):
            raise PermissionError("Drive connection changed during this session")
        return DriveTransport(self.authority)
