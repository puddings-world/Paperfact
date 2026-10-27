"""Typed, explicit QA review. Retained answers never invoke a provider.

The original receipt remains immutable. A sealed preview carries the displayed
target and observations, and application records its own atomic local receipt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import NAMESPACE_URL, uuid4, uuid5

from paper_daily import research_chat as chat
from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.research_lifecycle import ensure_lifecycle

FIELDS = {"request_id", "fingerprint", "record_json", "target_json", "answer_json", "result_json"}


MAX_DETAIL = 8 * 1024 * 1024


def encode(value):
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if len(text.encode()) > MAX_DETAIL:
        raise ValueError("QA review exceeds the bounded detail budget")
    return text


def _hash(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _setup(conn):
    if not conn.in_transaction:
        raise ValueError("QA review requires a caller-owned transaction")
    chat.initialize(conn)
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_chat_review_receipts("
            "request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,record_json TEXT NOT NULL,"
            "target_json TEXT NOT NULL,answer_json TEXT NOT NULL,result_json TEXT NOT NULL)"
        )


def _desired(conn, portable, local=None):
    if portable is None and local is not None and "research_paper_identity" in _tables(conn):
        row = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local,)
        ).fetchone()
        portable = row[0] if row else None
    if portable is None or "research_document_desired" not in _tables(conn):
        return None
    row = conn.execute(
        "SELECT target,active FROM research_document_desired WHERE paper_id=?", (portable,)
    ).fetchone()
    return list(row) if row else None


def _validate_observation(value, binding):
    from paper_daily.sync_journal import ID

    if value is None:
        if binding is not None:
            raise ValueError("Enrolled target requires an observation")
        return
    if (
        binding is None
        or not isinstance(value, dict)
        or set(value)
        != {
            "workspace_id",
            "kind",
            "entity_id",
            "revision",
            "predecessor",
            "incarnation",
            "active",
            "parents",
        }
    ):
        raise ValueError("Invalid displayed observation")
    if (
        value["workspace_id"] != binding["workspace_id"]
        or value["kind"] not in ("paper", "research_content")
        or type(value["revision"]) is not int
        or value["revision"] < 0
        or type(value["active"]) is not bool
    ):
        raise ValueError("Invalid observed target state")
    for name in ("entity_id", "predecessor", "incarnation"):
        item = value[name]
        if item is None and name != "entity_id":
            continue
        if not isinstance(item, str) or not ID.fullmatch(item):
            raise ValueError("Invalid observed identity")
    if not isinstance(value["parents"], list) or len(value["parents"]) > 1:
        raise ValueError("Invalid observed parents")
    for parent in value["parents"]:
        if (
            not isinstance(parent, dict)
            or set(parent) != {"kind", "id", "incarnation", "active"}
            or parent["kind"] != "paper"
            or type(parent["active"]) is not bool
            or not isinstance(parent["id"], str)
            or not ID.fullmatch(parent["id"])
        ):
            raise ValueError("Invalid observed parent")
        if parent["incarnation"] is not None and (
            not isinstance(parent["incarnation"], str) or not ID.fullmatch(parent["incarnation"])
        ):
            raise ValueError("Invalid observed parent incarnation")


def validate_preview_snapshot(value):
    """Closed private snapshot for a future shared durable-draft adapter."""
    if (
        not isinstance(value, dict)
        or set(value)
        != {"version", "database", "identity", "binding", "record", "target", "confirmation"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["confirmation"]) is not bool
    ):
        raise ValueError("Invalid QA review snapshot")
    chat.validate_request_record(value["record"])
    if value["record"]["status"] != "candidate":
        raise ValueError("Only retained QA answers can be applied")
    if (
        not isinstance(value["database"], str)
        or not isinstance(value["identity"], list)
        or len(value["identity"]) != 2
        or any(type(item) is not int or item < 0 for item in value["identity"])
        or not (
            PurePosixPath(value["database"]).is_absolute()
            or PureWindowsPath(value["database"]).is_absolute()
        )
    ):
        raise ValueError("Invalid QA review workspace")
    if value["binding"] is not None and (
        not isinstance(value["binding"], dict)
        or set(value["binding"]) != {"workspace_id", "device_id"}
    ):
        raise ValueError("Invalid QA review binding")
    from paper_daily.sync_content import _stamp
    from paper_daily.sync_journal import ID

    if value["binding"] is not None and any(
        not isinstance(item, str) or not ID.fullmatch(item) for item in value["binding"].values()
    ):
        raise ValueError("Invalid target binding identity")
    target = value["target"]
    if target is not None:
        if (
            not isinstance(target, dict)
            or set(target)
            != {
                "paper_id",
                "parent",
                "history",
                "question",
                "answer",
                "desired",
                "created_at",
                "exchange_id",
                "user_key",
                "answer_key",
                "user_observation",
                "answer_observation",
                "reuse",
            }
            or type(target["reuse"]) is not bool
        ):
            raise ValueError("Invalid QA displayed target")
        for key in ("exchange_id", "user_key", "answer_key"):
            chat._uuid(target[key])
        if not isinstance(target["paper_id"], str) or not target["paper_id"]:
            raise ValueError("Invalid target paper")
        if not isinstance(target["parent"], dict) or set(target["parent"]) != {
            "row",
            "epoch",
            "observation",
            "portable",
        }:
            raise ValueError("Invalid target lifecycle")
        epoch = target["parent"]["epoch"]
        if (
            not isinstance(epoch, str)
            or len(epoch) != 32
            or any(c not in "0123456789abcdef" for c in epoch)
        ):
            raise ValueError("Unknown target lifecycle")
        if not isinstance(target["history"], list) or len(target["history"]) > 6:
            raise ValueError("Invalid displayed conversation history")
        parent = target["parent"]
        if (
            not isinstance(parent["row"], dict)
            or set(parent["row"]) != {"_rowid", "id", "title", "venue", "year", "abstract"}
            or parent["row"]["id"] != target["paper_id"]
        ):
            raise ValueError("Invalid displayed paper metadata")
        if parent["portable"] is not None:
            chat._uuid(parent["portable"])
        _stamp(target["created_at"])
        for key, role in (("user_key", "user"), ("answer_key", "assistant")):
            if target[key] != str(
                uuid5(NAMESPACE_URL, "paperfact:qa:" + target["exchange_id"] + ":" + role)
            ):
                raise ValueError("Target turn identity differs from its exchange")
        original = json.loads(value["record"]["context_json"])
        if target["answer"] is not None:
            raise ValueError("Review may only append an absent answer")
        if target["reuse"]:
            if (
                target["question"] != json.loads(value["record"]["question_json"])
                or target["paper_id"] != original["paper_id"]
                or target["exchange_id"] != original["request_id"]
            ):
                raise ValueError("Reused question differs from the retained source")
        elif target["question"] is not None or not value["confirmation"]:
            raise ValueError("A new exchange requires explicit target confirmation")
        rows = [*target["history"], *([target["question"]] if target["question"] else [])]
        fields = {
            "id",
            "paper_id",
            "role",
            "body",
            "created_at",
            "page",
            "anchor",
            "message_id",
            "exchange_id",
            "reply_to",
            "source_hash",
        }
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != fields
                or row["paper_id"] != target["paper_id"]
                or type(row["id"]) is not int
                or row["id"] < 1
            ):
                raise ValueError("Invalid displayed conversation row")
            if row["message_id"] is not None:
                chat.validate_shared_turn({key: item for key, item in row.items() if key != "id"})
            else:
                if (
                    row["role"] not in ("user", "assistant", "system")
                    or not isinstance(row["body"], str)
                    or len(row["body"].encode()) > 200 * 1024
                    or any(
                        row[key] is not None for key in ("exchange_id", "reply_to", "source_hash")
                    )
                ):
                    raise ValueError("Invalid displayed legacy turn")
                _stamp(row["created_at"])
        for observation in (
            parent["observation"],
            target["user_observation"],
            target["answer_observation"],
        ):
            _validate_observation(observation, value["binding"])
        if target["desired"] is not None:
            from paper_daily.sync_documents import _validate_target

            if (
                not isinstance(target["desired"], list)
                or len(target["desired"]) != 2
                or type(target["desired"][1]) is not int
                or target["desired"][1] not in (0, 1)
            ):
                raise ValueError("Invalid displayed document")
            document = json.loads(target["desired"][0])
            _validate_target(document)
            if parent["portable"] is not None and document["paper_id"] != parent["portable"]:
                raise ValueError("Displayed document belongs to another paper")
    encode(value)
    return value


def validate_receipt(row):
    if not isinstance(row, dict) or set(row) != FIELDS:
        raise ValueError("Invalid QA application receipt")
    chat._uuid(row["request_id"])
    if (
        not isinstance(row["fingerprint"], str)
        or len(row["fingerprint"]) != 64
        or any(c not in "0123456789abcdef" for c in row["fingerprint"])
    ):
        raise ValueError("Invalid QA application fingerprint")
    record = chat.validate_request_record(json.loads(row["record_json"]))
    target = validate_preview_snapshot(json.loads(row["target_json"]))
    if target["record"] != record:
        raise ValueError("QA receipt source differs from displayed source")
    answer = json.loads(row["answer_json"])
    if (
        not isinstance(answer, dict)
        or set(answer) != {"body"}
        or not isinstance(answer["body"], str)
        or not answer["body"].strip()
        or len(answer["body"].encode()) > 200 * 1024
    ):
        raise ValueError("Invalid reviewed answer")
    result = json.loads(row["result_json"])
    if not isinstance(result, dict) or set(result) != {"exchange_id", "user_key", "answer_key"}:
        raise ValueError("Invalid QA application result")
    for key, value in result.items():
        chat._uuid(value)
        if target["target"] is None or value != target["target"][key]:
            raise ValueError("QA result differs from selected target")
    if row["fingerprint"] != _hash({"preview": target, "body": answer["body"]}):
        raise ValueError("QA application fingerprint differs from retained choice")
    encode(row)
    return row


def check_target(conn, snapshot):
    """Validate the displayed base in the write transaction; never recapture it."""
    data = validate_preview_snapshot(snapshot)
    if (
        generation._path(conn) != data["database"]
        or generation._identity(data["database"]) != data["identity"]
        or generation._binding(conn) != data["binding"]
    ):
        raise ValueError("Displayed workspace changed")
    target = data["target"]
    if target is None:
        raise ValueError("Select a target paper explicitly")
    if chat._parent(conn, target["paper_id"]) != target["parent"]:
        raise ValueError("Displayed target paper changed")
    if chat._inputs(conn, target["paper_id"]) != target["history"]:
        raise ValueError("Displayed conversation changed")
    turns = chat.history(conn, target["paper_id"])
    for key in ("question", "answer"):
        identity = target["user_key" if key == "question" else "answer_key"]
        current = next((row for row in turns if row["message_id"] == identity), None)
        if current != target[key]:
            raise ValueError("Displayed conversation turn changed")
    if _desired(conn, target["parent"]["portable"], target["paper_id"]) != target["desired"]:
        raise ValueError("Displayed document version changed")


@dataclass(frozen=True)
class ChatPreview:
    serialized: str
    seal: str

    @property
    def data(self):
        return json.loads(self.serialized)


class ChatReview:
    def __init__(self, database):
        self.path = Path(database).resolve(strict=True)
        self.identity = generation._identity(self.path)
        with closing(generation._connect(self.path)) as conn:
            self.binding = generation._binding(conn)
        self.key = secrets.token_bytes(32)
        self.closed = False

    def close(self):
        self.closed = True

    def _connect(self):
        if self.closed or generation._identity(self.path) != self.identity:
            raise ValueError("Original review workspace closed or was replaced")
        conn = generation._connect(self.path)
        if generation._binding(conn) != self.binding:
            conn.close()
            raise ValueError("Original review workspace binding changed")
        return conn

    def records(self, paper_id=None, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid QA review limit")
        records = []
        with closing(self._connect()) as conn:
            if "research_chat_requests" in _tables(conn):
                for row in conn.execute(
                    "SELECT * FROM research_chat_requests WHERE status IN ('prepared','candidate') "
                    "AND length(CAST(context_json AS BLOB))+length(CAST(question_json AS BLOB))"
                    "+coalesce(length(CAST(answer_json AS BLOB)),0)<? "
                    "AND json_valid(context_json) AND "
                    "(? IS NULL OR json_extract(context_json,'$.paper_id')=?) "
                    "ORDER BY rowid DESC LIMIT ?",
                    (chat.MAX_BYTES, paper_id, paper_id, limit),
                ):
                    record = chat.validate_request_record(dict(row))
                    if (
                        paper_id is None
                        or json.loads(record["context_json"])["paper_id"] == paper_id
                    ):
                        records.append(record)
            if "recovery_records" in _tables(conn):
                for row in conn.execute(
                    "SELECT data FROM recovery_records WHERE table_name IN "
                    "('research_chat_requests','research_chat_recovery') "
                    "AND length(CAST(data AS BLOB))<? "
                    "ORDER BY rowid DESC LIMIT ?",
                    (chat.MAX_BYTES, limit),
                ):
                    record = chat.validate_request_record(json.loads(row[0]))
                    if record["status"] == "candidate":
                        records.append(record)
        # Explicit review only: sidecars are bounded and stay source provenance.
        for record in chat.list_recovery_requests(self.path):
            records.append(record)
        unique = {}
        for record in records:
            prior = unique.get(record["request_id"])
            if prior is None or (prior["status"] == "prepared" and record["status"] == "candidate"):
                unique[record["request_id"]] = record
        result = []
        with closing(self._connect()) as conn:
            tables = _tables(conn)
            for record in unique.values():
                accepted = []
                if "research_chat_requests" in tables:
                    row = conn.execute(
                        "SELECT * FROM research_chat_requests WHERE request_id=? "
                        "AND status='accepted'",
                        (record["request_id"],),
                    ).fetchone()
                    if row is not None:
                        accepted.append(chat.validate_request_record(dict(row)))
                if "recovery_records" in tables:
                    for row in conn.execute(
                        "SELECT data FROM recovery_records "
                        "WHERE table_name='research_chat_requests' AND json_valid(data) "
                        "AND json_extract(data,'$.request_id')=? "
                        "AND json_extract(data,'$.status')='accepted' "
                        "AND length(CAST(data AS BLOB))<? LIMIT 2",
                        (record["request_id"], chat.MAX_BYTES),
                    ):
                        accepted.append(chat.validate_request_record(json.loads(row[0])))
                if any(
                    all(
                        row[key] == record[key]
                        for key in ("request_id", "context_json", "question_json", "answer_json")
                    )
                    for row in accepted
                ):
                    continue
                result.append(record)
        return result[:limit]

    def applied_result(self, record):
        record = chat.validate_request_record(dict(record))
        with closing(self._connect()) as conn:
            if "research_chat_review_receipts" not in _tables(conn):
                return None
            row = conn.execute(
                "SELECT * FROM research_chat_review_receipts WHERE record_json=? "
                "ORDER BY rowid DESC LIMIT 1",
                (chat._json(record),),
            ).fetchone()
            return json.loads(validate_receipt(dict(row))["result_json"]) if row else None

    def targets(self):
        with closing(self._connect()) as conn:
            return [
                dict(row)
                for row in conn.execute("SELECT id,title FROM papers ORDER BY title,id LIMIT 1000")
            ]

    def _seal(self, data):
        validate_preview_snapshot(data)
        serialized = encode(data)
        return ChatPreview(
            serialized, hmac.new(self.key, serialized.encode(), "sha256").hexdigest()
        )

    def verify(self, preview):
        if not isinstance(preview, ChatPreview) or not hmac.compare_digest(
            preview.seal, hmac.new(self.key, preview.serialized.encode(), "sha256").hexdigest()
        ):
            raise ValueError("QA preview is modified or belongs to another session")
        return validate_preview_snapshot(preview.data)

    def preview(self, record, *, target_paper_id=None):
        record = chat.validate_request_record(dict(record))
        if record["status"] != "candidate":
            raise ValueError("This question has no retained answer to review")
        old = json.loads(record["context_json"])
        data = {
            "version": 1,
            "database": str(self.path),
            "identity": self.identity,
            "binding": self.binding,
            "record": record,
            "target": None,
            "confirmation": False,
        }
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _setup(conn)
            ensure_lifecycle(conn)
            conn.commit()
            conn.execute("BEGIN")
            original = False
            if chat._original(conn, old):
                with suppress(ValueError):
                    original = (
                        chat._parent(conn, old["paper_id"])["epoch"] == old["parent"]["epoch"]
                    )
            if target_paper_id is None and not original:
                return self._seal(data)
            paper = target_paper_id if target_paper_id is not None else old["paper_id"]
            parent = chat._parent(conn, paper)
            rows = chat.history(conn, paper)
            question = next((r for r in rows if r["message_id"] == old["user_key"]), None)
            answer = next((r for r in rows if r["message_id"] == old["answer_key"]), None)
            reuse = (
                original
                and paper == old["paper_id"]
                and question == json.loads(record["question_json"])
                and answer is None
            )
            exchange = old["request_id"] if reuse else str(uuid4())
            user = (
                old["user_key"]
                if reuse
                else str(uuid5(NAMESPACE_URL, "paperfact:qa:" + exchange + ":user"))
            )
            assistant = (
                old["answer_key"]
                if reuse
                else str(uuid5(NAMESPACE_URL, "paperfact:qa:" + exchange + ":assistant"))
            )
            data["confirmation"] = target_paper_id is not None or not reuse
            data["target"] = {
                "paper_id": paper,
                "parent": parent,
                "history": chat._inputs(conn, paper),
                "question": question if reuse else None,
                "answer": None,
                "desired": _desired(conn, parent["portable"], paper),
                "created_at": chat.now(),
                "exchange_id": exchange,
                "user_key": user,
                "answer_key": assistant,
                "reuse": reuse,
                "user_observation": sync_capture.observe_target(conn, "paper", paper, "chat", user),
                "answer_observation": sync_capture.observe_target(
                    conn, "paper", paper, "chat", assistant
                ),
            }
            return self._seal(data)

    def target_preview(self, preview, target_id):
        return self.preview(self.verify(preview)["record"], target_paper_id=target_id)

    def apply(self, preview, *, body=None, request_id, confirm_target=False):
        data = self.verify(preview)
        chat._uuid(request_id)
        if data["confirmation"] and confirm_target is not True:
            raise ValueError("Confirm the explicitly selected target")
        body = json.loads(data["record"]["answer_json"])["body"] if body is None else body
        if not isinstance(body, str) or not body.strip() or len(body.encode()) > 200 * 1024:
            raise ValueError("Invalid reviewed answer")
        fingerprint = _hash({"preview": data, "body": body})
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _setup(conn)
            prior = conn.execute(
                "SELECT * FROM research_chat_review_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
            if prior:
                row = validate_receipt(dict(prior))
                if row["fingerprint"] != fingerprint:
                    raise ValueError("Review request was reused for another choice")
                return json.loads(row["result_json"])
            context = json.loads(data["record"]["context_json"])
            if chat._original(conn, context):
                source = conn.execute(
                    "SELECT * FROM research_chat_requests WHERE request_id=?",
                    (data["record"]["request_id"],),
                ).fetchone()
                if (
                    source is not None
                    and source["status"] == "candidate"
                    and dict(source) != data["record"]
                ):
                    raise ValueError("Retained source changed after display")
            check_target(conn, data)
            target = data["target"]
            old = json.loads(data["record"]["context_json"])
            source = old["document"]["sha256"] if old["document"] else None
            output = {
                **old,
                **target,
                "request_id": target["exchange_id"],
                "question": old["question"],
                "page": old["page"],
                "anchor": old["anchor"],
            }
            observations = [target["user_observation"], target["answer_observation"]]
            sources = {obs["entity_id"]: source for obs in observations if obs is not None}
            with sync_capture.expecting(conn, observations, source_hashes=sources):
                if not target["reuse"]:
                    chat._append(
                        conn, output, role="user", body=old["question"], source_hash=source
                    )
                chat._append(conn, output, role="assistant", body=body, source_hash=source)
                result = {key: target[key] for key in ("exchange_id", "user_key", "answer_key")}
                row = dict(
                    request_id=request_id,
                    fingerprint=fingerprint,
                    record_json=chat._json(data["record"]),
                    target_json=encode(data),
                    answer_json=chat._json({"body": body}),
                    result_json=chat._json(result),
                )
                validate_receipt(row)
                with sync_capture.suppress_capture(conn):
                    conn.execute(
                        "INSERT INTO research_chat_review_receipts VALUES(?,?,?,?,?,?)",
                        tuple(
                            row[k]
                            for k in (
                                "request_id",
                                "fingerprint",
                                "record_json",
                                "target_json",
                                "answer_json",
                                "result_json",
                            )
                        ),
                    )
                conn.commit()
            return result


def load_record(path):
    """Explicitly selected recovery JSON; embedded paths never become destinations."""
    path = Path(path).absolute()
    if (
        any(generation._is_link(p) for p in (path, *path.parents))
        or path.stat().st_size > chat.MAX_BYTES
    ):
        raise ValueError("Invalid retained QA file")
    with path.open("rb") as stream:
        raw = stream.read(chat.MAX_BYTES + 1)
    if len(raw) > chat.MAX_BYTES:
        raise ValueError("Retained QA file is too large")
    return chat.validate_request_record(json.loads(raw))


def source_hashes(receipt):
    """All retained source versions, including historical displayed conversations."""
    validate_receipt(receipt)
    record = json.loads(receipt["record_json"])
    context = json.loads(record["context_json"])
    target = json.loads(receipt["target_json"])["target"]
    rows = [json.loads(record["question_json"]), *context["history"], *target["history"]]
    if target["question"] is not None:
        rows.append(target["question"])
    hashes = {row["source_hash"] for row in rows if row.get("source_hash") is not None}
    if context["document"] is not None:
        hashes.add(context["document"]["sha256"])
    return hashes
