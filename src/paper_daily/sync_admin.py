"""Explicit local administration for the loopback reference sync service."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import sys
from contextlib import closing
from pathlib import Path

from paper_daily.connection_vault import MAX_BYTES, Connection
from paper_daily.sync_http import _decode, make_server
from paper_daily.sync_journal import SyncHistoryUnavailable
from paper_daily.sync_service import AuthorityInUseError, ReferenceService

MARKER = ".paperfact-sync-service.json"
FORMAT = {"format": "paperfact-reference-service-v3"}
LEGACY_PINNED_FORMAT = {"format": "paperfact-reference-service-v2"}
LEGACY_FORMAT = {"format": "paperfact-reference-service-v1"}
DATABASE = "authority.sqlite"


def _root(value):
    path = Path(value).absolute()
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Use a dedicated directory, not a link")
    return path.resolve()


def require_mount(state, mount):
    """Refuse startup without the explicitly selected mounted data volume.

    This is a startup guard, not a runtime mount lock or an identity check on the
    underlying disk. The supervisor must also order the service after its mount.
    """
    selected = Path(mount)
    if not selected.is_absolute():
        raise ValueError("The required data mount must be absolute")
    volume = _root(selected)
    root = _root(state)
    if volume == root or not root.is_relative_to(volume) or not os.path.ismount(volume):
        raise ValueError("Service state must be below the required mounted data volume")
    return root


class AuthorityMarkerError(ValueError):
    """An official authority cannot establish its persisted local file lifetime."""


def file_marker(database, *, expected_identity=None):
    info = database.lstat()
    identity = (info.st_dev, info.st_ino)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_ino <= 0
            or expected_identity is not None and identity != tuple(expected_identity)):
        raise AuthorityMarkerError("Authority database identity changed; review recovery")
    return {**FORMAT, "database_identity": list(identity)}


def marker_for(database, *, expected_identity=None):
    from paper_daily.sync_authority_control import fingerprint

    before = file_marker(database, expected_identity=expected_identity)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        digest = fingerprint(conn)
    if file_marker(database, expected_identity=expected_identity) != before:
        raise AuthorityMarkerError("Authority identity changed during control capture")
    return {**before, "control_sha256": digest}


def marker_record(marker, database, *, allow_legacy_backup=False):
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256:
        raise AuthorityMarkerError("Invalid authority lifetime marker")
    with marker.open("rb") as stream:
        raw = stream.read(257)
    if len(raw) > 256:
        raise AuthorityMarkerError("Invalid authority lifetime marker")
    record = _decode(raw)
    expected = file_marker(database)
    old_pin = {**expected, **LEGACY_PINNED_FORMAT}
    pin = record.get("database_identity") if isinstance(record, dict) else None
    valid_pin = (isinstance(pin, list) and len(pin) == 2
                 and all(type(value) is int for value in pin))
    if record in (LEGACY_FORMAT, old_pin) and (record == LEGACY_FORMAT or valid_pin):
        if allow_legacy_backup:
            return record, tuple(expected["database_identity"])
        raise AuthorityMarkerError(
            "Legacy authority has no control checkpoint. Stop serving, create a verified "
            "backup and restore-backup into a fresh service/workspace; re-enroll devices.")
    digest = record.get("control_sha256") if isinstance(record, dict) else None
    if (not isinstance(pin, list) or len(pin) != 2
            or any(type(value) is not int for value in pin)
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or record != {**expected, "control_sha256": digest}):
        raise AuthorityMarkerError(
            "Authority identity/control marker differs. Preserve state and review recovery; "
            "do not recreate the marker or reuse old credentials.")
    return record, tuple(pin)


def marker_identity(marker, database, *, allow_legacy_backup=False):
    return marker_record(marker, database, allow_legacy_backup=allow_legacy_backup)[1]


def authority(state):
    root = _root(state)
    marker, database = root / MARKER, root / DATABASE
    if not marker.exists() or not database.exists():
        raise ValueError("Initialize a dedicated sync service directory first")
    identity = marker_identity(marker, database)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    if "papers" in tables or not {"sync_devices", "sync_events", "sync_heads"} <= tables:
        raise ValueError("This is not a reference sync authority")
    return ReferenceService(database, blob_root=root / "blobs",
                            expected_database_identity=identity, authority_marker=marker)


def initialize(state):
    root = _root(state)
    if (root / MARKER).exists():
        authority(root)
        return {"state": "initialized"}
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("Choose an empty service directory, separate from research")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    service = ReferenceService(root / DATABASE, blob_root=root / "blobs")
    record = marker_for(service.path, expected_identity=service._database_identity)
    fd = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"state": "initialized"}


def issue(state, endpoint, workspace, device, output):
    root = _root(state)
    candidate = Path(output).absolute()
    if candidate.is_symlink():
        raise ValueError("Connection output must not be a link")
    output = candidate.resolve()
    if output.is_relative_to(root):
        raise ValueError("Keep device credentials outside the service state directory")
    expected = Connection.decoded(Connection(endpoint, workspace, device, "pending").encoded())
    service = authority(root)
    if output.exists():
        if not output.is_file() or output.stat().st_size > MAX_BYTES:
            raise ValueError("Output already exists and is not this connection")
        record = Connection.decoded(output.read_text(encoding="utf-8"))
        if (record.endpoint, record.workspace_id, record.device_id) != (
            expected.endpoint, workspace, device
        ) or service.session_info(record.token) != {"workspace_id": workspace, "device_id": device}:
            raise ValueError("Existing output does not match this device")
        return {"state": "already_enrolled", "connection_file": str(output)}
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    observed = os.fstat(fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            def save(token):
                stream.write(Connection(expected.endpoint, workspace, device, token).encoded())
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()

            service.enroll(workspace, device, before_commit=save)
    except BaseException:
        # Never remove a different file that replaced our exclusive output.
        try:
            current = output.stat()
            if (current.st_dev, current.st_ino) == (observed.st_dev, observed.st_ino):
                output.unlink()
        except OSError:
            pass
        raise
    return {"state": "enrolled", "connection_file": str(output)}


def configure(parser):
    sub = parser.add_subparsers(dest="admin_action", required=True)
    for action in ("init", "issue", "serve", "backup", "verify-backup", "restore-backup",
                   "upload-backup", "download-backup", "review-device-backup",
                   "create-browser-key"):
        command = sub.add_parser(action)
        if action not in {"verify-backup", "upload-backup", "download-backup",
                          "review-device-backup", "create-browser-key"}:
            command.add_argument("--state", type=Path, required=True,
                                 help="Dedicated service directory, never a research workspace")
        if action == "create-browser-key":
            command.add_argument("--output", type=Path, required=True,
                                 help="New private signing-key file outside service/research state")
        if action in {"backup", "verify-backup"}:
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--seconds", type=float, default=30,
                                 help="Bounded local operation time budget (0, 300] seconds")
        if action == "review-device-backup":
            command.add_argument("--database", type=Path, required=True)
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--workspace", required=True)
            command.add_argument("--seconds", type=float, default=30)
        if action == "download-backup":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--bucket", required=True)
            command.add_argument("--snapshot", required=True, help="Exact manifest SHA-256")
            command.add_argument("--prefix", default="paperfact/authority-backups")
            command.add_argument("--seconds", type=float, default=300)
            command.add_argument("--max-bytes", type=int, default=16 * 1024**3)
        if action == "upload-backup":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--bucket", required=True)
            command.add_argument("--prefix", default="paperfact/authority-backups")
            command.add_argument("--quiet", action="store_true",
                                 help="Suppress bounded progress records on stderr")
            command.add_argument("--seconds", type=float, default=300)
        if action == "restore-backup":
            command.add_argument("--input", type=Path, required=True,
                                 help="Verified private authority backup directory")
            command.add_argument("--workspace", required=True,
                                 help="One source workspace from the backup")
            command.add_argument("--as-workspace", required=True,
                                 help="Fresh workspace ID, never the old identity")
            command.add_argument("--seconds", type=float, default=30)
        if action == "issue":
            command.add_argument("--endpoint", required=True)
            command.add_argument("--workspace", required=True)
            command.add_argument("--device", required=True)
            command.add_argument("--output", type=Path, required=True)
        elif action == "serve":
            command.add_argument("--port", type=int, default=8765)
            command.add_argument(
                "--browser-origin", help="Exact PWA HTTPS origin; requires --browser-key-file")
            command.add_argument("--browser-key-file", type=Path,
                                 help="Existing private signing key outside authority state")
            command.add_argument("--require-mount", type=Path,
                                 help="Refuse startup unless this data volume is mounted")
    parser.set_defaults(func=run)


def run(args):
    try:
        if args.admin_action == "create-browser-key":
            from paper_daily.sync_browser_key import create_key

            result = create_key(args.output)
        elif args.admin_action == "review-device-backup":
            from paper_daily.sync_device_recovery import review

            result = review(args.database, args.input, args.workspace, seconds=args.seconds)
        elif args.admin_action == "download-backup":
            from paper_daily.sync_gcs_fetch import fetch

            result = fetch(args.bucket, args.snapshot, args.output, prefix=args.prefix,
                           seconds=args.seconds, max_bytes=args.max_bytes)
        elif args.admin_action == "upload-backup":
            import time

            from paper_daily.sync_gcs_backup import publish

            last_progress = [float("-inf")]

            def progress(value):
                now = time.monotonic()
                terminal = value.get("completed") == value.get("total")
                if not args.quiet and (value["stage"] != "verified_remote" or terminal
                                       or now - last_progress[0] >= 1):
                    print(json.dumps(value), file=sys.stderr, flush=True)
                    last_progress[0] = now

            result = publish(args.input, args.bucket, prefix=args.prefix, seconds=args.seconds,
                             progress=progress)
        elif args.admin_action == "restore-backup":
            from paper_daily.sync_authority_restore import restore

            result = restore(args.input, args.state, args.workspace, args.as_workspace,
                             seconds=args.seconds)
        elif args.admin_action in {"backup", "verify-backup"}:
            from paper_daily import sync_authority_backup

            if args.admin_action == "backup":
                result = sync_authority_backup.export(
                    args.state, args.output, seconds=args.seconds)
            else:
                result = sync_authority_backup.verify(args.output, seconds=args.seconds)
        elif args.admin_action == "init":
            result = initialize(args.state)
        elif args.admin_action == "issue":
            result = issue(args.state, args.endpoint, args.workspace, args.device, args.output)
        else:
            if args.require_mount is not None:
                require_mount(args.state, args.require_mount)
            browser = None
            if args.browser_origin is not None or args.browser_key_file is not None:
                from paper_daily.sync_browser import BrowserSessions, validate_origin
                from paper_daily.sync_browser_key import load_key
                from paper_daily.workspace_service import _safe_path

                if args.browser_origin is None or args.browser_key_file is None:
                    raise ValueError("Use both browser origin and private signing key")
                origin = validate_origin(args.browser_origin)
                key_path = _safe_path(args.browser_key_file)
                if key_path.is_relative_to(_root(args.state)):
                    raise ValueError("Keep the browser signing key outside authority state")
                key = load_key(key_path)
                service = authority(args.state)
                browser = BrowserSessions(service, origin, key)
            else:
                service = authority(args.state)
            server = make_server(
                service, port=args.port, allow_unverified_mutations=False,
                **({"browser": browser} if browser else {}))
            try:
                receipt = {"state": "serving", "url": f"http://127.0.0.1:{server.server_port}"}
                if browser is not None:
                    receipt["browser_origin"] = browser.origin
                print(json.dumps(receipt), flush=True)
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        print(json.dumps(result), flush=True)
        return 0
    except AuthorityMarkerError as error:
        print(str(error), file=sys.stderr)
        return 2
    except SyncHistoryUnavailable:
        print("Authority control/history checkpoint cannot be verified. Stop serving, "
              "preserve state and review recovery into a fresh service/workspace. "
              "Do not repair the marker or silently reuse old credentials.", file=sys.stderr)
        return 2
    except AuthorityInUseError:
        print("Sync service already active for this authority. Stop the existing listener "
              "and let its current requests finish before starting another. "
              "Do not delete lock files or replace the database.", file=sys.stderr)
        return 2
    except (ValueError, OSError, sqlite3.Error):
        if args.admin_action == "download-backup":
            print("GCS backup retrieval failed. Check the exact snapshot digest, private bucket, "
                  "operator dependencies/ADC, access, time/byte budgets and new output path. "
                  "Incomplete output is retained; retry into a new directory. No service was "
                  "restored.", file=sys.stderr)
            return 2
        if args.admin_action == "upload-backup":
            print("GCS backup publication failed. Verify the local snapshot, private bucket, "
                  "operator dependencies/ADC, access and time budget. Retry the same unchanged "
                  "snapshot to verify any already-published objects; existing objects were not "
                  "overwritten.", file=sys.stderr)
            return 2
        if args.admin_action == "create-browser-key":
            print("Browser-key creation failed. Check the private output directory "
                  "and existing file. "
                  "Existing files were not overwritten; an interrupted write may need review.",
                  file=sys.stderr)
            return 2
        print("Sync administration failed. Check the dedicated state directory, device IDs "
              "and unused output path; for serve, also check the required data mount, "
              "paired browser "
              "origin/key options and private key-file permissions. "
              "Existing files were not overwritten.", file=sys.stderr)
        return 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog="paperfact sync-admin", description=__doc__)
    configure(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
