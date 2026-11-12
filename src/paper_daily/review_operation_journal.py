"""Owner-bound local review journal shared by typed note and claim transports."""

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from uuid import UUID

_MAX = 2_000_000
_OP = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def _fail(code, message):
    from paper_daily.local_operations import OperationError

    raise OperationError(code, message)


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        _fail("invalid_input", "Use a canonical draft or target UUID")


def _revision(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        _fail("invalid_input", "Use the current positive draft revision")


def _operation(value):
    if not isinstance(value, str) or not _OP.fullmatch(value):
        _fail("invalid_input", "operation_id must contain 1-128 letters, numbers, . _ : -")


def _output(value):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > _MAX:
        _fail("result_too_large", "Request a smaller result page")
    return value


@contextmanager
def _review():
    from paper_daily import store
    from paper_daily.local_operations import OperationError
    from paper_daily.research_review import ResearchReview
    from paper_daily.research_review_drafts import DraftConflict

    service = None
    try:
        service = ResearchReview(store.DB_PATH)
        yield service
    except OperationError:
        raise
    except sqlite3.Error:
        _fail(
            "storage_unavailable", "Workspace storage is unavailable; retry the same operation_id"
        )
    except DraftConflict:
        _fail("conflict", "Draft changed in another window; read it again and retain your text")
    except (ValueError, OSError):
        _fail(
            "review_unavailable",
            "Review is unavailable or changed; retain drafts and review the current workspace",
        )
    finally:
        if service is not None:
            service.close()


def _schema(conn):
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE name='integration_operations'").fetchone()
    if row is None:
        from paper_daily import sync_capture

        with sync_capture.suppress_capture(conn):
            conn.execute(
                "CREATE TABLE integration_operations (id TEXT PRIMARY KEY,"
                "fingerprint TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL)"
            )
    if [r[1] for r in conn.execute("PRAGMA table_info(integration_operations)")] != [
        "id",
        "fingerprint",
        "result",
        "created_at",
    ]:
        _fail("review_unavailable", "Local operation receipts require migration")


def _fingerprint(service, operation, arguments):
    from paper_daily.research_review import digest

    return digest(
        dict(
            operation=operation,
            arguments=arguments,
            owner=dict(path=str(service.path), identity=service.identity, binding=service.binding),
        )
    )


def _prior(service, conn, operation_id, fingerprint):
    service._check(conn)
    if (
        conn.execute("SELECT 1 FROM sqlite_master WHERE name='integration_operations'").fetchone()
        is None
    ):
        return None
    row = conn.execute(
        "SELECT fingerprint,CASE WHEN length(CAST(result AS BLOB))<=? "
        "THEN result END FROM integration_operations WHERE id=?",
        (_MAX, operation_id),
    ).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        _fail("conflict", "operation_id already used for a different request or workspace owner")
    if row[1] is None:
        _fail("review_unavailable", "Saved operation result exceeds its supported limit")
    return _output(json.loads(row[1]))


def _receipt(service, conn, operation_id, fingerprint, result):
    from paper_daily.research_review import encode
    from paper_daily.store import now

    _schema(conn)
    service._check(conn)
    conn.execute(
        "INSERT INTO integration_operations VALUES(?,?,?,?)",
        (operation_id, fingerprint, encode(_output(result)), now()),
    )


def _check_revision(service, conn, draft_id, revision):
    service._check(conn)
    row = conn.execute(
        "SELECT revision FROM research_review_drafts WHERE draft_id=?", (draft_id,)
    ).fetchone()
    if row is None or row[0] != revision:
        _fail("conflict", "Draft changed while this request was running")


def private(operation, arguments, prepare, *, _review_factory=_review, _receipt_fn=_receipt):
    from paper_daily.research_review_drafts import DraftStore

    operation_id = arguments["operation_id"]
    _operation(operation_id)
    with _review_factory() as service:
        if service.recovery or service.binding is None:
            _fail("review_unavailable", "Create an editable managed copy before resuming drafts")
        fingerprint = _fingerprint(service, operation, arguments)
        with closing(service._connect()) as conn:
            prior = _prior(service, conn, operation_id, fingerprint)
        if prior is not None:
            return prior
        try:
            preview, body, draft_id, revision = prepare(service, fingerprint)
        except (ValueError, OSError):
            # A concurrent identical request can commit while preparation observes
            # a newer private revision. Its native receipt resolves this retry.
            with closing(service._connect()) as conn:
                prior = _prior(service, conn, operation_id, fingerprint)
            if prior is not None:
                return prior
            raise
        with closing(service._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = _prior(service, conn, operation_id, fingerprint)
            if prior is not None:
                return prior
            if revision is not None:
                _check_revision(service, conn, draft_id, revision)
            saved = DraftStore(service).save_in(
                conn, preview, body, draft_id, draft_id=draft_id, revision=revision
            )
            result = dict(operation_id=operation_id, status="draft_saved", **saved)
            _receipt_fn(service, conn, operation_id, fingerprint, result)
            conn.commit()
            return result


@contextmanager
def source_guard(service):
    """Bounded worker-only exclusion for local source inspections and Apply.

    Use the existing OS lock, released on process exit. This is neither a source
    capability nor a DB transaction; all native/base checks still run afterward.
    Waiting duplicates reuse their committed receipt instead of staging the same
    source in parallel and invalidating each other's immutable-read fence.
    """
    from time import monotonic, sleep

    from paper_daily.research_job_lock import claim

    deadline = monotonic() + 5
    while True:
        with claim(service.path, "local-claim-review", "sources") as acquired:
            if acquired:
                with closing(service._connect()) as conn:
                    service._check(conn)
                yield
                return
        if monotonic() >= deadline:
            _fail("in_progress", "Claim source work is active; retry the same operation_id")
        sleep(0.02)
