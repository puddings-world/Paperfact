"""Explicit private sync sessions; credentials remain in this process only."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from paper_daily.sync_capture import RESEARCH, trusted_connection
from paper_daily.sync_client import SyncClient
from paper_daily.sync_http import HttpTransport
from paper_daily.sync_journal import Journal, SyncHistoryUnavailable, _identifier
from paper_daily.sync_research import (
    research_order_writer,
    research_projection_writer,
    research_writer,
)
from paper_daily.workspace_service import Cancelled, WorkspaceService, _binding, _read, _tables


class SyncStopped(RuntimeError):
    """The original session was cancelled, disconnected or replaced."""


class EnrollmentRequired(ValueError):
    """Existing local research needs explicit complete enrollment, not a login."""


def local_binding(path, *, require_capture=False):
    with _read(path) as conn:
        tables = _tables(conn)
        rows = dict(_binding(conn, tables))
        identity = rows.get("paperfact_sync_identity")
        if identity is None:
            if require_capture:
                raise EnrollmentRequired("Existing research has not been enrolled")
            return None
        expected = {"paperfact_sync_identity", "research_sync_binding", "research_capture_binding"}
        if require_capture and (set(rows) != expected or len(set(rows.values())) != 1):
            raise EnrollmentRequired("Journal, research and writer capture must agree")
        if require_capture:
            required = {
                "paperfact_sync_cursor",
                "paperfact_sync_inbox",
                "paperfact_sync_heads",
                "paperfact_sync_conflicts",
                "paperfact_sync_graph",
                "paperfact_sync_graph_receipts",
                "paperfact_sync_graph_projection",
                "paperfact_sync_operations",
            }
            if not required <= tables:
                raise EnrollmentRequired("Sync schema is incomplete")
            triggers = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            }
            for table in RESEARCH & tables:
                if (
                    not {f"capture_{table}_{action}" for action in ("insert", "update", "delete")}
                    <= triggers
                ):
                    raise EnrollmentRequired("Research writer capture is incomplete")
        return {"workspace_id": identity[0], "device_id": identity[1]}


class _Connection(sqlite3.Connection):
    def commit(self):
        self.live()
        self.check_binding(self)
        return super().commit()


class GuardedJournal(Journal):
    """A late callback can neither create a missing DB nor write its replacement."""

    def _connect(self):
        self.live()
        conn = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=2, factory=_Connection
        )
        conn.row_factory = sqlite3.Row
        conn.live = self.live
        conn.check_binding = self._check_all_bindings
        try:
            self.live()
            self._check_all_bindings(conn)
            trusted_connection(conn)
            return conn
        except BaseException:
            conn.close()
            raise

    def _check_all_bindings(self, conn):
        expected = (self.workspace_id, self.device_id)
        rows = dict(_binding(conn, _tables(conn)))
        if set(rows) != {
            "paperfact_sync_identity",
            "research_sync_binding",
            "research_capture_binding",
        } or any(value != expected for value in rows.values()):
            raise SyncStopped("The original workspace binding changed")


class GuardedTransport:
    def __init__(self, transport, live, *, history=None):
        self.transport, self.live, self.history = transport, live, history
        self.base_url = transport.base_url

    def control_checkpoint(self):
        self.live()
        reader = getattr(type(self.transport), "control_checkpoint", None)
        point = reader(self.transport) if reader is not None else None
        self.live()
        return point

    def check_control_checkpoint(self, token, point):
        self.live()
        checker = getattr(type(self.transport), "check_control_checkpoint", None)
        if checker is None:
            raise SyncHistoryUnavailable("Transport removed authority control continuity")
        result = checker(self.transport, token, point)
        self.live()
        return result

    def __getattr__(self, name):
        if name not in {
            "session_info",
            "device_catalog",
            "rename_device",
            "revoke_peer",
            "create_pairing",
            "push",
            "pull",
            "history_page",
            "push_verified",
            "blob_begin",
            "blob_append",
            "blob_commit",
            "blob_cancel",
            "blob_read",
        }:
            raise AttributeError(name)

        def invoke(*args, **kwargs):
            self.live()
            if self.history is not None and name in {
                "blob_begin", "blob_append", "blob_commit", "blob_cancel",
            }:
                kwargs["checkpoint"] = self.history()
                self.live()
            result = getattr(self.transport, name)(*args, **kwargs)
            self.live()
            return result

        return invoke


class _Live:
    def __init__(self, owner, generation, ticket):
        self.owner, self.generation, self.ticket = owner, generation, ticket

    def __call__(self):
        self.owner._live(self.generation, self.ticket)


class SyncSession:
    """One source DB, one verified endpoint/device and one explicit job at a time.

    No token, endpoint setting or login is read from disk. Connecting only asks
    session_info; private research requests require an additional explicit action.
    """

    def __init__(self, database, *, current_path=None, transport_factory=HttpTransport):
        self.workspace = WorkspaceService(database, current_path=current_path)
        self._factory = transport_factory
        self._state = threading.Lock()
        self._running = threading.Lock()
        self._generation = 0
        self._token = None
        self._source_binding = None
        self.endpoint = None
        self.identity = None
        self.state = "disconnected"
        self.last_success = None
        self._history_review = None

    @property
    def busy(self):
        """Whether this session already owns a metadata or attachment job."""
        return self._running.locked()

    @property
    def generation(self):
        """Opaque process-local consent epoch; contains no credential."""
        with self._state:
            return self._generation

    def summary(self):
        with self._state:
            return {
                "state": self.state,
                "authenticated": self._token is not None,
                "endpoint": self.endpoint,
                "identity": dict(self.identity) if self.identity else None,
                "last_success": self.last_success,
            }

    def disconnect(self):
        with self._state:
            self._generation += 1
            self._history_review = None
            self._token = None
            self.state = "disconnected"

    def cancel(self):
        with self._state:
            self._generation += 1
            self._history_review = None
            self.state = "connected" if self._token else "disconnected"

    def _live(self, generation, ticket=None):
        if ticket is not None:
            ticket.check()
        with self._state:
            if generation != self._generation:
                raise SyncStopped("The connection session changed")
        info = self.workspace.path.stat()
        if (info.st_dev, info.st_ino) != self.workspace.identity or self.workspace.path != Path(
            self.workspace.current_path()
        ).resolve():
            raise SyncStopped("The active workspace changed")
        if self._source_binding is not None:
            with _read(self.workspace.path) as conn:
                if _binding(conn, _tables(conn)) != self._source_binding:
                    raise SyncStopped("The original local binding changed")

    @contextmanager
    def _job(self):
        if not self._running.acquire(blocking=False):
            raise SyncStopped("Another sync action is active")
        try:
            yield
        except BaseException as error:
            with self._state:
                if self._token is not None and self.state != "reconnect":
                    self.state = (
                        "offline"
                        if isinstance(error, (TimeoutError, ConnectionError))
                        else "connected"
                        if isinstance(error, (SyncStopped, Cancelled, EnrollmentRequired))
                        else "failed"
                    )
            raise
        finally:
            self._running.release()

    def connect(self, endpoint, workspace_id, device_id, token, ticket):
        with self._job():
            self.disconnect()
            _identifier(workspace_id)
            _identifier(device_id)
            if not isinstance(token, str) or not token or len(token) > 4096:
                raise ValueError("An explicit device credential is required")
            with _read(self.workspace.path) as conn:
                self._source_binding = _binding(conn, _tables(conn))
            with self._state:
                generation = self._generation
                self.state = "checking"
            expected = {"workspace_id": workspace_id, "device_id": device_id}
            try:
                self._live(generation, ticket)
                # Construction validates HTTPS/literal-loopback URL policy without I/O.
                with self._factory(endpoint) as transport:
                    from paper_daily.workspace_control import bind_control

                    bind_control(transport, self.workspace.path, expected,
                                 _Live(self, generation, ticket))
                    identity = transport.session_info(token)
                    self._live(generation, ticket)
                    if identity != expected:
                        raise PermissionError("Credential belongs to a different workspace/device")
                    origin = transport.base_url
                with self._state:
                    if generation != self._generation:
                        raise SyncStopped("The connection session changed")
                    self.endpoint, self.identity, self._token = origin, expected, token
                    self.state = "connected"
                    self.last_success = None
                return self.summary()
            except BaseException:
                with self._state:
                    if generation == self._generation:
                        self._token = None
                        self.state = "disconnected"
                raise

    @contextmanager
    def authorized(self, ticket):
        with self._state:
            generation, token, endpoint = self._generation, self._token, self.endpoint
            expected = dict(self.identity) if self.identity else None
        if token is None or expected is None:
            raise PermissionError("Connect this device before syncing")
        live = _Live(self, generation, ticket)
        live()
        try:
            with self._factory(endpoint) as transport:
                from paper_daily.workspace_control import bind_control

                bind_control(transport, self.workspace.path, expected, live)
                guarded = GuardedTransport(transport, live)
                if guarded.session_info(token) != expected:
                    raise PermissionError("The authenticated device binding changed")
                yield guarded, token, expected, live
        except PermissionError:
            with self._state:
                if generation == self._generation:
                    self._token = None
                    self._generation += 1
                    self.state = "reconnect"
            raise

    def _client(self, identity, live):
        if local_binding(self.workspace.path, require_capture=True) != identity:
            raise EnrollmentRequired("This local workspace does not match the connection")
        journal = GuardedJournal.attach_existing(self.workspace.path, **identity)
        journal.live = live
        return SyncClient.attach_existing(
            journal,
            research_writer,
            order_writer=research_order_writer,
            projection_writer=research_projection_writer,
        )

    def history_review_summary(self):
        with self._state:
            saved = self._history_review
            return saved[1].summary() if saved and saved[0] == self._generation else None

    def review_history(self, ticket, progress=lambda _value: None, *, max_pages=25):
        """Explicit read-only comparison; subsequent calls continue its bounded scan."""
        with self._job(), self.authorized(ticket) as (transport, token, identity, live):
            client = self._client(identity, live)
            with self._state:
                generation, saved = self._generation, self._history_review
            previous = saved[1] if saved and saved[0] == generation else None
            try:
                review = client.review_legacy_history(
                    transport, token, previous, max_pages=max_pages, check=live,
                    progress=lambda value: progress(dict(stage="history_review", **value)))
            except SyncHistoryUnavailable:
                with self._state:
                    self._history_review = None
                raise
            live()
            with self._state:
                if generation != self._generation:
                    raise SyncStopped('The history review connection changed')
                self._history_review = generation, review
            summary = review.summary()
            progress(dict(stage='history_review', **summary))
            return summary

    def adopt_history_review(self, ticket):
        """User-confirmed proof adoption; no upload, projection or cursor reset."""
        from paper_daily.sync_client import validate_history_page

        with self._job(), self.authorized(ticket) as (transport, token, identity, live):
            with self._state:
                saved = self._history_review
                if not saved or saved[0] != self._generation or not saved[1].complete:
                    raise SyncHistoryUnavailable('Complete a current history review first')
                review = saved[1]
            point = dict(sequence=review.point[0], sha256=review.point[1])
            page = transport.history_page(token, after=point['sequence'], limit=1,
                                          checkpoint=point)
            _events, start, _end, _points = validate_history_page(page, identity['workspace_id'])
            if start != point:
                raise SyncHistoryUnavailable('Reviewed service history changed')
            live()
            result = self._client(identity, live).adopt_legacy_history(review)
            live()
            with self._state:
                self._history_review = None
            return result

    def sync(self, ticket, progress=lambda _value: None, *, max_pages=100, seconds=20):
        if type(max_pages) is not int or not 1 <= max_pages <= 100 or not 0 < seconds <= 60:
            raise ValueError("Invalid sync work budget")
        # Do not even read private remote research for an unrelated/non-enrolled DB.
        bound = local_binding(self.workspace.path, require_capture=True)
        with self._job(), self.authorized(ticket) as (transport, token, identity, live):
            if bound != identity:
                raise EnrollmentRequired("Use a new directory to join this workspace")
            client = self._client(identity, live)
            client.prepare_history_checkpoint()
            transport = GuardedTransport(
                transport, live, history=lambda: client.history_checkpoint(acknowledged=True),
            )
            with self._state:
                self.state = "syncing"
            deadline = time.monotonic() + seconds
            from paper_daily.workspace_sync_files import AttachmentSteps

            files = AttachmentSteps(client, transport, token, live, progress, deadline=deadline)
            try:
                totals = {"pushed": 0, "received": 0, "caught_up": False}
                result = client.status()
                for _ in range(max_pages):
                    live()
                    result = client.sync_verified_once(
                        transport,
                        token,
                        limit=100,
                        prepare_push=files.prepare,
                    )
                    totals["pushed"] += result["pushed"]
                    totals["received"] += result["received"]
                    progress({**totals, "cursor": result["cursor"],
                              "history_preparing": bool(result.get("history_preparing")),
                              "history_remaining": result.get("history_remaining", 0)})
                    # HTTP byte/page caps can produce short pages. Only an empty
                    # response proves this observed prefix was exhausted.
                    if result.get("history_preparing"):
                        if time.monotonic() >= deadline:
                            break
                        continue
                    if result["received"] == 0:
                        totals["caught_up"] = True
                        break
                    if time.monotonic() >= deadline:
                        break
                from paper_daily.lineage_history_repair import HistoryRepair

                history = HistoryRepair(
                    client, current_path=self.workspace.current_path,
                    expected_identity=self.workspace.identity,
                )
                remaining = deadline - time.monotonic()
                history_status = (
                    history.drain(ticket, progress, max_steps=16, seconds=min(3, remaining))
                    if remaining > 0 and not result.get("history_preparing") else history.status()
                )
                if not result.get("history_preparing"):
                    files.download_pending()
                live()
                file_status = files.status()
                with self._state:
                    if self._generation != live.generation:
                        raise SyncStopped("The connection session changed")
                    if not result.get("history_preparing"):
                        self.last_success = datetime.now(UTC).isoformat()
                    self.state = "connected"
                return {
                    **result,
                    **totals,
                    "last_success": self.last_success,
                    "attachments": file_status,
                    "local_binding": identity,
                    "lineage_history": history_status,
                }
            finally:
                files.close()


    def prepare_offline(self, local_paper_ids, ticket, progress=lambda _value: None, *,
                        steps=64, seconds=20):
        """Download selected current attachments only; never push/pull research or pin.

        Metadata must already be present locally. Existing transfer receipts/offsets
        provide retry/resume. Byte/source verification status remains a separate action.
        """
        if (type(steps) is not int or not 1 <= steps <= 256
                or isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not 0 < seconds <= 60):
            raise ValueError("Invalid selected-download work budget")
        from paper_daily.workspace_offline import OfflineService
        from paper_daily.workspace_sync_files import AttachmentSteps

        with self._job():
            offline = OfflineService(self.workspace.path,
                                     current_path=self.workspace.current_path)
            plan = offline.plan(local_paper_ids, ticket)
            selected = [row["paper_id"] for row in plan["papers"]]
            portable = [row["portable_id"] for row in plan["papers"]]
            if not selected:
                return {"state": "empty", "paper_ids": [], "portable_ids": [],
                        "partial": False, "verification_required": True, "attachments": None}

            def signature(value):
                return [(row["paper_id"], row["portable_id"], row["pdf"]["target"],
                         [(item["entity_id"], item["operation"], item.get("source_pins", ()))
                          for item in row["artifacts"]],
                         row["artifact_inventory_available"]) for row in value["papers"]]

            expected = signature(plan)
            artifact_ids = list(dict.fromkeys(
                item["entity_id"] for row in plan["papers"] for item in row["artifacts"]
            ))
            with self.authorized(ticket) as (transport, token, identity, live):
                if offline.identity != identity:
                    raise EnrollmentRequired("The selected workspace does not match the connection")

                def selected_live():
                    live()
                    try:
                        current = offline.plan(selected, ticket)
                    except (sqlite3.Error, OSError, ValueError) as error:
                        raise SyncStopped(
                            "Selected research changed; retry from the current view"
                        ) from error
                    if signature(current) != expected:
                        raise SyncStopped("Selected attachment targets changed")

                selected_live()
                guarded = GuardedTransport(transport, selected_live)
                client = self._client(identity, selected_live)
                deadline = time.monotonic() + seconds
                with self._state:
                    self.state = "syncing"
                files = AttachmentSteps(client, guarded, token, selected_live, progress,
                                        budget=steps, deadline=deadline)
                try:
                    progress({"stage": "offline_download", "selected": len(selected),
                              "steps": 0})
                    download = files.download_selected(portable, artifact_ids=artifact_ids)
                    selected_live()
                    status = {**files.status(paper_ids=portable, artifact_ids=artifact_ids),
                              **download}
                    missing = sum(row["pdf"]["target"] is None for row in plan["papers"])
                    missing_artifacts = sum(item["operation"] is None
                                            for row in plan["papers"] for item in row["artifacts"])
                    current = offline.plan(selected, ticket)
                    stale = any(item["state"] == "stale"
                                for row in current["papers"] for item in row["artifacts"])
                    inventory = all(row["artifact_inventory_available"] for row in plan["papers"])
                    partial = bool(status["pending"] or status["failed"]
                                   or status["remaining_targets"] or missing or missing_artifacts
                                   or stale
                                   or not inventory or not status["storage_registered"])
                    selected_live()
                    with self._state:
                        if self._generation != live.generation:
                            raise SyncStopped("The connection session changed")
                        self.state = "connected"
                    # Do not advance last_success: no metadata sync took place.
                    return {"state": "partial" if partial else "downloaded",
                            "paper_ids": selected, "portable_ids": portable,
                            "attachments": status, "missing_pdf_manifests": missing,
                            "missing_artifact_manifests": missing_artifacts,
                            "partial": partial, "verification_required": True}
                finally:
                    files.close()
