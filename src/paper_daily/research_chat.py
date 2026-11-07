"""Observed, append-only QA publication; explicit database and no provider credentials."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.store import now

FIELDS = {
    "request_id",
    "context_json",
    "question_json",
    "answer_json",
    "status",
    "candidate_id",
    "reason",
}
MAX_BYTES = 3 * 1024 * 1024


def _json(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("Question context exceeds its limit")
    return text


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid question identity")


def initialize(conn):
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_chat_links(local_id INTEGER "
            "PRIMARY KEY,message_id TEXT NOT NULL UNIQUE,exchange_id TEXT "
            "NOT NULL,reply_to TEXT,source_hash "
            "TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_chat_requests(request_id "
            "TEXT PRIMARY KEY,context_json TEXT NOT NULL,question_json TEXT "
            "NOT NULL,answer_json TEXT,status TEXT NOT NULL,candidate_id "
            "TEXT,reason TEXT NOT NULL)"
        )
    from paper_daily.research_lifecycle import ensure_lifecycle

    ensure_lifecycle(conn)


def _parent(conn, paper_id):
    row = conn.execute("SELECT rowid AS _rowid,* FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        raise ValueError("Original paper is no longer available")
    from paper_daily.research_lifecycle import parent_lifecycle

    epoch = parent_lifecycle(conn, "paper", paper_id)
    portable = None
    observation = None
    if sync_capture.enabled(conn):
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper_id,)
        ).fetchone()[0]
        observation = sync_capture.observe(conn, "paper", portable)
    return {
        "row": {key: row[key] for key in ("_rowid", "id", "title", "venue", "year", "abstract")},
        "epoch": epoch,
        "observation": observation,
        "portable": portable,
    }


def history(conn, paper_id):
    linked = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_chat_links'"
    ).fetchone()
    fields = (
        "c.*,l.message_id,l.exchange_id,l.reply_to,l.source_hash"
        if linked
        else "c.*,NULL AS message_id,NULL AS exchange_id,NULL AS reply_to,NULL AS source_hash"
    )
    join = "LEFT JOIN research_chat_links l ON l.local_id=c.id" if linked else ""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT {fields} FROM chat c {join} WHERE c.paper_id=? ORDER BY c.id", (paper_id,)
        )
    ]


def _inputs(conn, paper_id, exclude=None):
    rows = history(conn, paper_id)
    return [row for row in rows if exclude is None or row["message_id"] != exclude][-6:]


@dataclass(frozen=True)
class ChatRequest:
    encoded: str
    document: object = field(default=None, repr=False, compare=False)

    @property
    def data(self):
        return json.loads(self.encoded)

    @property
    def request_id(self):
        return self.data["request_id"]

    @property
    def db_path(self):
        return Path(self.data["db_path"])


def begin_chat(
    conn, *, paper_id, question, request_id, page=None, anchor=None, document=None, legacy_root=None
):
    """Short submit-time transaction. PDF parsing/history preparation runs later."""
    _uuid(request_id)
    if not isinstance(question, str) or not question.strip() or len(question.encode()) > 200 * 1024:
        raise ValueError("Enter a bounded question")
    from paper_daily.sync_content import validate_anchor

    anchor = json.loads(anchor) if isinstance(anchor, str) else anchor
    validate_anchor(anchor)
    if page is not None and (type(page) is not int or not 1 <= page <= 1000001):
        raise ValueError("Invalid question page")
    if anchor and page not in (None, anchor["p0"] + 1):
        raise ValueError("Question page differs from its selection")
    conn.execute("BEGIN IMMEDIATE")
    initialize(conn)
    user_key = str(uuid5(NAMESPACE_URL, "paperfact:qa:" + request_id + ":user"))
    answer_key = str(uuid5(NAMESPACE_URL, "paperfact:qa:" + request_id + ":assistant"))
    data = {
        "version": 1,
        "request_id": request_id,
        "db_path": generation._path(conn),
        "database_identity": generation._identity(generation._path(conn)),
        "binding": generation._binding(conn),
        "paper_id": paper_id,
        "parent": _parent(conn, paper_id),
        "question": question.strip(),
        "page": page,
        "anchor": anchor,
        "created_at": now(),
        "user_key": user_key,
        "answer_key": answer_key,
        "user_observation": sync_capture.observe_target(conn, "paper", paper_id, "chat", user_key),
        "answer_observation": sync_capture.observe_target(
            conn, "paper", paper_id, "chat", answer_key
        ),
        "history": None,
        "document": None,
        "desired": None,
        "legacy_root": str(Path(legacy_root).resolve()) if legacy_root is not None else None,
    }
    conn.commit()
    return ChatRequest(_json(data), document)


def _original(conn, data):
    if (
        generation._path(conn) != data["db_path"]
        or generation._identity(data["db_path"]) != data["database_identity"]
    ):
        return False
    return generation._binding(conn) == data["binding"]


def _document_intact(request):
    expected = request.data["document"]
    if expected is None:
        return True
    document = request.document
    if document is None or not document._owner.intact(document):
        return False
    before = generation._identity(expected["path"])
    with Path(expected["path"]).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest == expected["sha256"] and before == generation._identity(expected["path"])


def _stale(conn, request, *, question_row=None):
    data = request.data
    if not _original(conn, data):
        return "Original research workspace changed"
    if _parent(conn, data["paper_id"]) != data["parent"]:
        return "Original paper changed"
    if (
        data["history"] is not None
        and _inputs(conn, data["paper_id"], data["user_key"]) != data["history"]
    ):
        return "Conversation inputs changed"
    if question_row is not None:
        actual = next(
            (r for r in history(conn, data["paper_id"]) if r["message_id"] == data["user_key"]),
            None,
        )
        if actual != question_row:
            return "Original question changed or was deleted"
    if request.document is not None:
        if not request.document._owner.intact(request.document):
            return "Original PDF changed"
        if request.document._owner.inspect(data["paper_id"]).target != data["desired"]:
            return "Desired PDF changed during the question"
    return None


def _append(conn, data, *, role, body, source_hash):
    """Reserve portable identity before capture's AFTER INSERT trigger observes it."""
    from paper_daily.sync_content import content_id

    key = data["user_key"] if role == "user" else data["answer_key"]
    observation = data["user_observation"] if role == "user" else data["answer_observation"]
    local_id = (
        max(
            conn.execute("SELECT COALESCE(MAX(id),0) FROM chat").fetchone()[0],
            conn.execute(
                "SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='chat'),0)"
            ).fetchone()[0],
        )
        + 1
    )
    anchor = data["anchor"] if role == "user" else None
    page = data["page"] if role == "user" else None
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO research_chat_links VALUES(?,?,?,?,?)",
            (
                local_id,
                key,
                data["request_id"],
                None if role == "user" else data["user_key"],
                source_hash,
            ),
        )
        if sync_capture.enabled(conn):
            conn.execute(
                "INSERT INTO research_content_identity VALUES(?,?,?,?,?)",
                ("chat", key, local_id, data["paper_id"], data["created_at"]),
            )
    source = (
        {content_id({"kind": "paper", "id": data["parent"]["portable"]}, "chat", key): source_hash}
        if observation
        else {}
    )
    with sync_capture.expecting(conn, [observation], source_hashes=source):
        conn.execute(
            "INSERT INTO chat(id,paper_id,role,body,created_at,page,anchor) VALUES(?,?,?,?,?,?,?)",
            (
                local_id,
                data["paper_id"],
                role,
                body,
                data["created_at"],
                page,
                _json(anchor) if anchor else None,
            ),
        )
        # Capture's commit must remain inside the observation scope, but receipts
        # are written by the caller before that same commit.
        conn._chat_commit_observation = (observation, source)
    return next(r for r in history(conn, data["paper_id"]) if r["id"] == local_id)


def _commit(conn):
    observation, sources = getattr(conn, "_chat_commit_observation", (None, {}))
    with sync_capture.expecting(conn, [observation], source_hashes=sources):
        conn.commit()


def _prompt_history(rows):
    """Project completed typed exchanges without changing captured CAS inputs.

    Unlinked legacy rows keep their existing prompt behavior. Their ordering is
    historical context, not proof of pairing or a completed portable exchange.
    """
    users = {}
    for index, row in enumerate(rows):
        if row["role"] == "user" and row.get("message_id") and row.get("exchange_id"):
            users.setdefault(row["message_id"], []).append((index, row))
    completed = set()
    for index, row in enumerate(rows):
        matches = users.get(row.get("reply_to"), [])
        if row["role"] != "assistant" or len(matches) != 1:
            continue
        parent_index, parent = matches[0]
        if (row.get("message_id") and row.get("exchange_id") == parent["exchange_id"]
                and row.get("paper_id") == parent.get("paper_id")
                and row.get("source_hash") == parent.get("source_hash")):
            completed.update((parent_index, index))
    return [
        (row["role"], row["body"]) for index, row in enumerate(rows)
        if index in completed or not any(
            row.get(key) is not None for key in ("message_id", "exchange_id", "reply_to")
        )
    ]


def prepare_chat(request, *, replacement=None):
    """Resolve exact PDF bytes and history off-thread, then durably append the question."""
    data = request.data
    with closing(generation._connect(request.db_path)) as conn:
        if not _original(conn, data) or _parent(conn, data["paper_id"]) != data["parent"]:
            raise ValueError("Original question target changed")
        prior = conn.execute(
            "SELECT * FROM research_chat_requests WHERE request_id=?", (request.request_id,)
        ).fetchone()
        if prior:
            prior = validate_request_record(dict(prior))
            stored = json.loads(prior["context_json"])
            for key in (
                "db_path",
                "database_identity",
                "binding",
                "paper_id",
                "question",
                "page",
                "anchor",
                "request_id",
            ):
                if stored[key] != data[key]:
                    raise ValueError("Question identity was reused")
            request = replace(request, encoded=prior["context_json"])
            data = request.data
            if reason := _stale(conn, request, question_row=json.loads(prior["question_json"])):
                raise ValueError(reason)
        else:
            data["history"] = _inputs(conn, data["paper_id"])
    from paper_daily.document_reader import from_workspace

    reader = (
        request.document._owner
        if request.document is not None
        else from_workspace(request.db_path, legacy_root=data["legacy_root"])
    )
    status = reader.inspect(data["paper_id"])
    document = request.document or reader.resolve(data["paper_id"])
    text = None
    if document.available:
        import pymupdf

        if not reader.intact(document):
            raise ValueError("Original PDF is no longer intact")
        data["document"] = {
            "sha256": document.sha256,
            "path": str(document.path),
            "target": document.target,
            "managed": document.managed,
        }
        data["desired"] = status.target
        request = replace(request, encoded=_json(data), document=document)
        if not _document_intact(request):
            raise ValueError("Original PDF failed verification")
        with pymupdf.open(document.path) as pdf:
            chunks, length = [], 0
            for item in pdf:
                chunk = item.get_text()[: 45000 - length]
                chunks.append(chunk)
                length += len(chunk)
                if length >= 45000:
                    break
            text = "\n".join(chunks)
            if data["page"] is not None:
                if data["page"] > len(pdf):
                    raise ValueError("Question page is outside the captured PDF")
                text = (
                    f"[Selected page {data['page']}]\n"
                    + pdf[data["page"] - 1].get_text()[:45000]
                    + "\n[Paper]\n"
                    + text
                )
        if data["anchor"] and data["anchor"].get("document_hash") != document.sha256:
            raise ValueError("Selection belongs to another PDF version")
    elif status.managed or data["anchor"] is not None or data["page"] is not None:
        raise ValueError("The selected original PDF is unavailable")
    # Missing legacy PDFs remain abstract-only. Never use an unverified alias text.
    request = replace(
        request, encoded=_json(data), document=document if document.available else None
    )
    with closing(generation._connect(request.db_path)) as conn, ExitStack() as scopes:
        conn.execute("BEGIN IMMEDIATE")
        if reason := _stale(conn, request):
            raise ValueError(reason)
        prior = conn.execute(
            "SELECT * FROM research_chat_requests WHERE request_id=?", (request.request_id,)
        ).fetchone()
        if prior is None:
            if replacement is not None:
                rows = replacement["rows"]
                if len(rows) != 1 or rows[0]["row"]["role"] != "user":
                    raise ValueError("Only an unanswered question can be retried")
                old = rows[0]["row"]
                current = history(conn, data["paper_id"])
                if any(row.get("reply_to") == old.get("message_id")
                       and row["role"] == "assistant" for row in current):
                    raise ValueError("The original question has already been answered")
                receipt = conn.execute(
                    "SELECT answer_json FROM research_chat_requests WHERE request_id=?",
                    (old.get("exchange_id"),),
                ).fetchone()
                if receipt and receipt[0] is not None:
                    raise ValueError("Review the retained answer before replacing its question")
                scopes.enter_context(
                    _delete_messages(conn, data["paper_id"], rows, expected=replacement)
                )
                data["history"] = _inputs(conn, data["paper_id"])
                request = replace(request, encoded=_json(data))
            question_row = _append(
                conn,
                data,
                role="user",
                body=data["question"],
                source_hash=data["document"]["sha256"] if data["document"] else None,
            )
            with sync_capture.suppress_capture(conn):
                conn.execute(
                    "INSERT INTO research_chat_requests VALUES(?,?,?,?,?,?,?)",
                    (
                        request.request_id,
                        request.encoded,
                        _json(question_row),
                        None,
                        "prepared",
                        None,
                        "ok",
                    ),
                )
            _commit(conn)
        elif prior["context_json"] != request.encoded:
            raise ValueError("Original question inputs changed; start a new question")
    request = seal_prepared(request)
    from paper_daily.desktop.ask import build_prompt

    paper = data["parent"]["row"]
    prompt = build_prompt(
        paper["title"],
        paper["venue"],
        paper["year"],
        paper["abstract"],
        text,
        _prompt_history(data["history"]),
        data["question"],
    )
    return request, prompt


def validate_request_record(record):
    """Closed archive schema; local paths are provenance, never active configuration."""
    from pathlib import PurePosixPath, PureWindowsPath

    from paper_daily.sync_content import _stamp, validate_anchor
    from paper_daily.sync_journal import ID

    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("Invalid QA receipt fields")
    _uuid(record["request_id"])
    if record["status"] not in ("prepared", "accepted", "candidate"):
        raise ValueError("Invalid QA receipt status")
    if not isinstance(record["reason"], str) or not 0 < len(record["reason"]) <= 1024:
        raise ValueError("Invalid QA result reason")
    for name in ("context_json", "question_json"):
        if not isinstance(record[name], str) or len(record[name].encode()) > MAX_BYTES:
            raise ValueError("Invalid bounded QA receipt")
    data = json.loads(record["context_json"])
    expected = {
        "version",
        "request_id",
        "db_path",
        "database_identity",
        "binding",
        "paper_id",
        "parent",
        "question",
        "page",
        "anchor",
        "created_at",
        "user_key",
        "answer_key",
        "user_observation",
        "answer_observation",
        "history",
        "document",
        "desired",
        "legacy_root",
    }
    if (
        not isinstance(data, dict)
        or set(data) != expected
        or type(data["version"]) is not int
        or data["version"] != 1
        or data["request_id"] != record["request_id"]
    ):
        raise ValueError("Invalid QA context")
    for key in ("db_path", "legacy_root"):
        value = data[key]
        if key == "legacy_root" and value is None:
            continue
        if (
            not isinstance(value, str)
            or not 0 < len(value) <= 32768
            or not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute())
        ):
            raise ValueError("Invalid archived QA path")
    identity = data["database_identity"]
    if (
        not isinstance(identity, list)
        or len(identity) != 2
        or any(type(v) is not int or v < 0 for v in identity)
    ):
        raise ValueError("Invalid original database identity")
    if not isinstance(data["paper_id"], str) or not 0 < len(data["paper_id"]) <= 1024:
        raise ValueError("Invalid original paper identity")
    binding = data["binding"]
    if binding is not None and (
        not isinstance(binding, dict)
        or set(binding) != {"workspace_id", "device_id"}
        or any(not isinstance(v, str) or not ID.fullmatch(v) for v in binding.values())
    ):
        raise ValueError("Invalid QA workspace binding")
    for key, role in (("user_key", "user"), ("answer_key", "assistant")):
        _uuid(data[key])
        if data[key] != str(
            uuid5(NAMESPACE_URL, "paperfact:qa:" + record["request_id"] + ":" + role)
        ):
            raise ValueError("QA turn identity differs from its request")
    _stamp(data["created_at"])
    validate_anchor(data["anchor"])
    if data["page"] is not None and (
        type(data["page"]) is not int or not 1 <= data["page"] <= 1000001
    ):
        raise ValueError("Invalid QA page")
    parent = data["parent"]
    if not isinstance(parent, dict) or set(parent) != {"row", "epoch", "observation", "portable"}:
        raise ValueError("Invalid QA parent snapshot")
    if (
        not isinstance(parent["epoch"], str)
        or len(parent["epoch"]) != 32
        or any(c not in "0123456789abcdef" for c in parent["epoch"])
    ):
        raise ValueError("Invalid original paper lifecycle")
    paper = parent["row"]
    if (
        not isinstance(paper, dict)
        or set(paper) != {"_rowid", "id", "title", "venue", "year", "abstract"}
        or paper["id"] != data["paper_id"]
    ):
        raise ValueError("Invalid captured paper metadata")
    if parent["portable"] is not None:
        _uuid(parent["portable"])
    question = json.loads(record["question_json"])
    if not isinstance(question, dict) or type(question.get("id")) is not int or question["id"] < 1:
        raise ValueError("Invalid original question row")
    validate_shared_turn({key: value for key, value in question.items() if key != "id"})
    if (
        question["paper_id"] != data["paper_id"]
        or question["message_id"] != data["user_key"]
        or question["exchange_id"] != data["request_id"]
        or question["role"] != "user"
        or question["body"] != data["question"]
        or question["created_at"] != data["created_at"]
    ):
        raise ValueError("QA question differs from its captured target")
    history_rows = data["history"]
    if not isinstance(history_rows, list) or len(history_rows) > 6:
        raise ValueError("Invalid bounded QA history")
    for row in history_rows:
        if (
            not isinstance(row, dict)
            or set(row) != set(question)
            or row["paper_id"] != data["paper_id"]
            or row["role"] not in ("user", "assistant", "system")
            or not isinstance(row["body"], str)
            or len(row["body"].encode()) > 200 * 1024
        ):
            raise ValueError("Invalid captured QA turn")
        if row["message_id"] is not None:
            validate_shared_turn({key: value for key, value in row.items() if key != "id"})
    document = data["document"]
    if document is not None:
        if (
            not isinstance(document, dict)
            or set(document) != {"sha256", "path", "target", "managed"}
            or type(document["managed"]) is not bool
        ):
            raise ValueError("Invalid QA document provenance")
        digest = document["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid QA document hash")
        path = document["path"]
        if not isinstance(path, str) or not (
            PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()
        ):
            raise ValueError("Invalid QA document path")
    if record["answer_json"] is not None:
        if (
            not isinstance(record["answer_json"], str)
            or len(record["answer_json"].encode()) > MAX_BYTES
        ):
            raise ValueError("Invalid bounded QA answer")
        answer = json.loads(record["answer_json"])
        if (
            not isinstance(answer, dict)
            or set(answer) != {"body"}
            or not isinstance(answer["body"], str)
            or not answer["body"].strip()
            or len(answer["body"].encode()) > 200 * 1024
        ):
            raise ValueError("Invalid QA answer")
    if (record["status"] == "prepared") != (record["answer_json"] is None):
        raise ValueError("QA receipt status differs from output")
    expected_candidate = (
        hashlib.sha256((record["context_json"] + record["answer_json"]).encode()).hexdigest()
        if record["status"] == "candidate"
        else None
    )
    if record["candidate_id"] != expected_candidate:
        raise ValueError("Invalid QA candidate identity")
    _json(record)
    return record


def _retained_path(request):
    data = request.data
    group = hashlib.sha256(
        _json([data["db_path"], data["database_identity"], data["binding"]]).encode()
    ).hexdigest()
    return request.db_path.parent / ".paperfact-chat" / group / (request.request_id + ".json")


def _completed_sidecar(request, original):
    """Only the expected owned record may replace this exact prepared receipt."""
    path = _retained_path(request)
    for entry in (path, *path.parents):
        if generation._is_link(entry):
            raise ValueError("QA recovery cannot traverse links")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid bounded QA recovery receipt")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("QA recovery receipt exceeds limits")
    record = validate_request_record(json.loads(raw))
    if record["status"] != "candidate" or any(
        record[key] != original[key] for key in ("request_id", "context_json", "question_json")
    ):
        raise ValueError("Retained answer differs from the original question")
    return record


def retain_failed_answer(request, answer):
    """Durable fallback after an unexpected publication error; no raw error text."""
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode()) > 200 * 1024:
        raise ValueError("Invalid bounded QA answer")
    sealed = getattr(request, "_receipt", None)
    if sealed is None or sealed["context_json"] != request.encoded:
        raise ValueError("Original prepared question is required")
    validate_request_record(sealed)
    encoded = _json({"body": answer})
    # Probe failures never authorize writes to a rebound or damaged database.
    # The sealed original output can still be retained outside it. A valid
    # conflicting completed receipt remains an explicit identity-reuse error.
    prior = None
    try:
        if generation._identity(request.db_path) == request.data["database_identity"]:
            with closing(generation._connect(request.db_path)) as conn:
                if _original(conn, request.data):
                    row = conn.execute(
                        "SELECT * FROM research_chat_requests WHERE request_id=?",
                        (request.request_id,),
                    ).fetchone()
                    if row is not None and row["answer_json"] is not None:
                        prior = validate_request_record(dict(row))
    except (OSError, sqlite3.DatabaseError, ValueError):
        prior = None
    if prior is not None:
        if (
            any(
                prior[key] != sealed[key] for key in ("request_id", "context_json", "question_json")
            )
            or prior["answer_json"] != encoded
        ):
            raise ValueError("QA delivery identity was reused for another result")
        return generation.Publication(
            prior["status"], request.request_id, prior["candidate_id"], prior["reason"]
        )
    return _retain(
        request, {**sealed, "answer_json": encoded}, "Answer retained after publication failed"
    )


def _retain(request, record, reason):
    record = {**record, "status": "candidate", "reason": reason}
    record["candidate_id"] = hashlib.sha256(
        (record["context_json"] + record["answer_json"]).encode()
    ).hexdigest()
    validate_request_record(record)
    path = _retained_path(request)
    for entry in (path, *path.parents):
        if generation._is_link(entry):
            raise ValueError("QA recovery cannot traverse links")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(_json(record).encode())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            old = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
            if (old["context_json"], old["answer_json"]) != (
                record["context_json"],
                record["answer_json"],
            ):
                raise ValueError("QA recovery identity was reused") from None
    finally:
        temporary.unlink(missing_ok=True)
    return generation.Publication("candidate", request.request_id, record["candidate_id"], reason)


def publish_answer(request, answer):
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode()) > 200 * 1024:
        raise ValueError("Invalid bounded QA answer")
    data = request.data
    answer_json = _json({"body": answer})
    # Preserve the original question row in memory with the request so that a
    # replaced database never supplies a forged receipt. Loaded from the original
    # database during preparation and sealed in a separate field below.
    record = getattr(request, "_receipt", None)
    if record is None:
        raise ValueError("Prepare the question before publishing an answer")
    record = {**record, "answer_json": answer_json}
    try:
        if generation._identity(request.db_path) != data["database_identity"]:
            return _retain(request, record, "Original research database was replaced")
        with closing(generation._connect(request.db_path)) as read:
            if _original(read, data):
                prior = read.execute(
                    "SELECT * FROM research_chat_requests WHERE request_id=?", (request.request_id,)
                ).fetchone()
                if prior is not None and prior["answer_json"] is not None:
                    if (
                        prior["context_json"] != request.encoded
                        or prior["answer_json"] != answer_json
                    ):
                        raise ValueError("QA delivery identity was reused")
                    return generation.Publication(
                        prior["status"], request.request_id, prior["candidate_id"], prior["reason"]
                    )
        intact = _document_intact(request)
        with closing(generation._connect(request.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not _original(conn, data):
                conn.rollback()
                return _retain(request, record, "Original workspace binding changed")
            prior = conn.execute(
                "SELECT * FROM research_chat_requests WHERE request_id=?", (request.request_id,)
            ).fetchone()
            if prior is None or prior["context_json"] != request.encoded:
                raise ValueError("Original QA receipt is unavailable")
            if prior["answer_json"] is not None:
                if prior["answer_json"] != answer_json:
                    raise ValueError("QA delivery identity was reused for a different answer")
                return generation.Publication(
                    prior["status"], request.request_id, prior["candidate_id"], prior["reason"]
                )
            try:
                reason = _stale(conn, request, question_row=json.loads(prior["question_json"]))
            except ValueError:
                reason = "Original paper is unavailable"
            if not intact:
                reason = "Original PDF changed"
            status = "candidate" if reason else "accepted"
            candidate = (
                hashlib.sha256((request.encoded + answer_json).encode()).hexdigest()
                if reason
                else None
            )
            if not reason:
                _append(
                    conn,
                    data,
                    role="assistant",
                    body=answer,
                    source_hash=data["document"]["sha256"] if data["document"] else None,
                )
            with sync_capture.suppress_capture(conn):
                conn.execute(
                    (
                        "UPDATE research_chat_requests SET "
                        "answer_json=?,status=?,candidate_id=?,reason=? WHERE "
                        "request_id=?"
                    ),
                    (answer_json, status, candidate, reason or "ok", request.request_id),
                )
            _commit(conn)
            return generation.Publication(status, request.request_id, candidate, reason or "ok")
    except (OSError, sqlite3.DatabaseError):
        return _retain(request, record, "Original research database is unavailable")


def seal_prepared(request):
    with closing(generation._connect(request.db_path)) as conn:
        if not _original(conn, request.data):
            raise ValueError("Original workspace changed")
        record = conn.execute(
            "SELECT * FROM research_chat_requests WHERE request_id=?", (request.request_id,)
        ).fetchone()
        record = validate_request_record(dict(record))
    object.__setattr__(request, "_receipt", record)
    return request


def answer_record(request):
    record = getattr(request, "_receipt", None)
    return json.loads(record["answer_json"])["body"] if record and record["answer_json"] else None


def delete_messages(conn, paper_id, snapshots, *, expected):
    conn.execute("BEGIN IMMEDIATE")
    with _delete_messages(conn, paper_id, snapshots, expected=expected):
        conn.commit()


@contextmanager
def _delete_messages(conn, paper_id, snapshots, *, expected):
    from paper_daily.research_lifecycle import parent_lifecycle

    if (
        not _original(conn, expected)
        or not expected["parent_lifecycle"]
        or parent_lifecycle(conn, "paper", paper_id) != expected["parent_lifecycle"]
    ):
        raise ValueError("Original conversation parent changed")
    current = {r["id"]: r for r in history(conn, paper_id)}
    observations = []
    for item in snapshots:
        row = item["row"]
        if current.get(row["id"]) != row or row["paper_id"] != paper_id:
            raise ValueError("Conversation changed; reload before deleting")
        observations.append(item["observation"])
    with sync_capture.expecting(conn, observations):
        conn.executemany(
            "DELETE FROM chat WHERE id=? AND paper_id=?",
            [(s["row"]["id"], paper_id) for s in snapshots],
        )
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_chat_links(local_id INTEGER "
                "PRIMARY KEY,message_id TEXT NOT NULL UNIQUE,exchange_id TEXT "
                "NOT NULL,reply_to TEXT,source_hash "
                "TEXT)"
            )
            conn.executemany(
                "DELETE FROM research_chat_links WHERE local_id=?",
                [(s["row"]["id"],) for s in snapshots],
            )
        yield


def validate_link(record):
    if not isinstance(record, dict) or set(record) != {
        "local_id",
        "message_id",
        "exchange_id",
        "reply_to",
        "source_hash",
    }:
        raise ValueError("Invalid conversation link")
    if type(record["local_id"]) is not int or record["local_id"] < 1:
        raise ValueError("Invalid local conversation identity")
    for key in ("message_id", "exchange_id"):
        _uuid(record[key])
    if record["reply_to"] is not None:
        _uuid(record["reply_to"])
        if record["reply_to"] == record["message_id"]:
            raise ValueError("A message cannot answer itself")
    digest = record["source_hash"]
    if digest is not None and (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("Invalid conversation document hash")
    return record


def validate_shared_turn(row):
    """Optional portable linkage has a closed shape; legacy bundles stay valid."""
    linked = {"message_id", "exchange_id", "reply_to", "source_hash"}
    if not linked & set(row):
        return False
    required = {"paper_id", "role", "body", "created_at", "page", "anchor"}
    if set(row) != required | linked:
        raise ValueError("Invalid shared conversation fields")
    validate_link({"local_id": 1, **{key: row[key] for key in linked}})
    from paper_daily.sync_content import validate_payload

    payload = {
        "scope": {"kind": "paper", "id": "11111111-1111-4111-8111-111111111111"},
        "feature": "chat",
        "key": row["message_id"],
        "source_document_hash": row["source_hash"],
        "data": {key: row[key] for key in required - {"paper_id"}}
        | {"exchange_id": row["exchange_id"], "reply_to": row["reply_to"]},
    }
    payload["data"]["anchor"] = json.loads(row["anchor"]) if row["anchor"] is not None else None
    validate_payload(payload)
    return True


def import_shared_turn(conn, row):
    validate_shared_turn(row)
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_chat_links(local_id INTEGER "
            "PRIMARY KEY,message_id TEXT NOT NULL UNIQUE,exchange_id TEXT "
            "NOT NULL,reply_to TEXT,source_hash "
            "TEXT)"
        )
    prior = conn.execute(
        "SELECT local_id FROM research_chat_links WHERE message_id=?", (row["message_id"],)
    ).fetchone()
    if prior:
        actual = next((r for r in history(conn, row["paper_id"]) if r["id"] == prior[0]), None)
        if actual is None or {key: actual[key] for key in row} != row:
            raise ValueError("Shared conversation identity has conflicting content")
        return 0
    local_id = (
        max(
            conn.execute("SELECT COALESCE(MAX(id),0) FROM chat").fetchone()[0],
            conn.execute(
                "SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='chat'),0)"
            ).fetchone()[0],
        )
        + 1
    )
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO research_chat_links VALUES(?,?,?,?,?)",
            (local_id, row["message_id"], row["exchange_id"], row["reply_to"], row["source_hash"]),
        )
        if sync_capture.enabled(conn):
            conn.execute(
                "INSERT INTO research_content_identity VALUES(?,?,?,?,?)",
                ("chat", row["message_id"], local_id, row["paper_id"], row["created_at"]),
            )
    columns = ["paper_id", "role", "body", "created_at", "page", "anchor"]
    conn.execute(
        "INSERT INTO chat(id,"
        + ",".join(columns)
        + ") VALUES("
        + ",".join("?" for _ in range(7))
        + ")",
        [local_id, *[row[key] for key in columns]],
    )
    return 1


def list_recovery_requests(database_path):
    """Bounded original-workspace sidecars; paths never become restored bindings."""
    import re

    database = Path(database_path).resolve()
    root = database.parent / ".paperfact-chat"
    if not root.exists():
        return []
    for entry in (root, *root.parents):
        if generation._is_link(entry):
            raise ValueError("QA recovery cannot traverse links")
    records = []
    total = 0
    count = 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_capture_binding'"
        ).fetchone()
        row = (
            conn.execute(
                "SELECT workspace,device FROM research_capture_binding WHERE id=1"
            ).fetchone()
            if table
            else None
        )
        binding = {"workspace_id": row[0], "device_id": row[1]} if row else None
    for folder in root.iterdir():
        if (
            generation._is_link(folder)
            or not folder.is_dir()
            or not re.fullmatch("[0-9a-f]{64}", folder.name)
        ):
            raise ValueError("Invalid QA recovery namespace")
        for path in folder.iterdir():
            if generation._is_link(path) or not path.is_file() or path.suffix != ".json":
                raise ValueError("Incomplete QA recovery artifact")
            count += 1
            size = path.stat().st_size
            total += size
            if count > 10000 or size > MAX_BYTES or total > 64 * 1024 * 1024:
                raise ValueError("QA recovery inventory exceeds limits")
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("QA recovery receipt exceeds limits")
            record = validate_request_record(json.loads(raw))
            data = json.loads(record["context_json"])
            group = hashlib.sha256(
                _json([data["db_path"], data["database_identity"], data["binding"]]).encode()
            ).hexdigest()
            if path.name != record["request_id"] + ".json" or folder.name != group:
                raise ValueError("QA recovery identity differs from its location")
            if data["db_path"] == str(database) and data["binding"] == binding:
                records.append(record)
    return records


def load_request(database_path, request_id, *, resolve_document=True):
    """Explicit restart seam; detached/archive paths cannot activate old requests."""
    _uuid(request_id)
    with closing(generation._connect(Path(database_path).resolve())) as conn:
        row = conn.execute(
            "SELECT * FROM research_chat_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown original question")
        record = validate_request_record(dict(row))
        request = ChatRequest(record["context_json"])
        if not _original(conn, request.data):
            raise ValueError("Question belongs to another original workspace")
        if record["answer_json"] is None:
            completed = _completed_sidecar(request, record)
            if completed is not None:
                record = completed
        if record["answer_json"] is None:
            reason = _stale(conn, request, question_row=json.loads(record["question_json"]))
            if reason:
                raise ValueError(reason)
    expected = request.data["document"]
    if resolve_document and expected is not None and record["answer_json"] is None:
        from paper_daily.document_reader import from_workspace

        reader = from_workspace(request.db_path, legacy_root=request.data["legacy_root"])
        document = reader.resolve(request.data["paper_id"])
        if (
            not document.available
            or document.sha256 != expected["sha256"]
            or document.target != expected["target"]
        ):
            raise ValueError("Original question PDF is no longer available")
        request = replace(request, document=document)
    object.__setattr__(request, "_receipt", record)
    return request


def pending_requests(conn, paper_id, *, limit=100):
    """Read-only bounded summaries; opening a paper never resumes an agent."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid pending question limit")
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_chat_requests'"
    ).fetchone():
        return []
    rows = conn.execute(
        "SELECT request_id,status,substr(reason,1,300) AS reason,"
        "json_extract(context_json,'$.user_key') AS user_key,"
        "substr(json_extract(context_json,'$.question'),1,300) AS question "
        "FROM research_chat_requests WHERE status IN ('prepared','candidate') "
        "AND json_valid(context_json) AND json_extract(context_json,'$.paper_id')=? "
        "ORDER BY rowid DESC LIMIT ?",
        (paper_id, limit),
    )
    return [dict(row) for row in rows]
