"""Closed private QA history and explicit live message identities during enrollment.

No context path is opened, no question/answer pairing is inferred, and archived
request ownership is never installed in the new workspace.
"""

from __future__ import annotations

from paper_daily import research_chat
from paper_daily.sync_content import _stamp, content_id, validate_anchor, validate_payload
from paper_daily.sync_documents import _validate_target
from paper_daily.sync_files import canonical_json, closed, digest
from paper_daily.sync_journal import _identifier

FORMATS = {
    "research_chat_requests": (
        "request_id context_json question_json answer_json status candidate_id reason"
    ),
    "research_chat_recovery": (
        "request_id context_json question_json answer_json status candidate_id reason"
    ),
    "research_chat_links": "local_id message_id exchange_id reply_to source_hash",
    "research_chat_review_receipts": (
        "request_id fingerprint record_json target_json answer_json result_json"
    ),
}
SQL_TURN = {"id", "paper_id", "role", "body", "created_at", "page", "anchor"}
LINK = {"message_id", "exchange_id", "reply_to", "source_hash"}
MAX_RECORDS = 10000
MAX_TOTAL = 64 * 1024**2
_DUMMY = "11111111-1111-4111-8111-111111111111"


def _value(raw):
    from paper_daily.enrollment_history import _value as checked_json

    return checked_json(raw)


def _text(value, limit, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or len(value.encode()) > limit:
        raise ValueError("Invalid bounded archived QA text")


def _turn(row):
    closed(row, SQL_TURN | LINK)
    if type(row["id"]) is not int or row["id"] < 1:
        raise ValueError("Invalid archived QA local turn identity")
    _text(row["paper_id"], 4096)
    if not row["paper_id"] or row["role"] not in {"user", "assistant", "system"}:
        raise ValueError("Invalid archived QA owner or role")
    _text(row["body"], 200 * 1024)
    _stamp(row["created_at"])
    if row["page"] is not None and (
        type(row["page"]) is not int or not 1 <= row["page"] <= 1000001
    ):
        raise ValueError("Invalid archived QA page")
    anchor = None if row["anchor"] is None else _value(row["anchor"])
    validate_anchor(anchor)
    linked = row["message_id"] is not None
    if linked:
        research_chat.validate_shared_turn(
            {key: value for key, value in row.items() if key != "id"}
        )
    elif any(row[key] is not None for key in LINK):
        raise ValueError("Partially linked QA history cannot acquire inferred identities")
    source = row["source_hash"] if linked else (anchor or {}).get("document_hash")
    payload = dict(
        scope={"kind": "paper", "id": _DUMMY},
        feature="chat",
        key=row["message_id"] if linked else _DUMMY,
        source_document_hash=source,
        data={key: row[key] for key in ("role", "body", "created_at", "page")} | {"anchor": anchor},
    )
    if linked:
        payload["data"].update(exchange_id=row["exchange_id"], reply_to=row["reply_to"])
    validate_payload(payload)
    return {value for value in (source, (anchor or {}).get("document_hash")) if value is not None}


def _observation(value, *, binding, kind, identity, parent=None):
    if binding is None:
        if value is not None:
            raise ValueError("Unbound QA history cannot contain invented graph observations")
        return
    closed(
        value,
        {
            "workspace_id",
            "kind",
            "entity_id",
            "revision",
            "predecessor",
            "incarnation",
            "active",
            "parents",
        },
    )
    if (
        value["workspace_id"] != binding["workspace_id"]
        or value["kind"] != kind
        or value["entity_id"] != identity
    ):
        raise ValueError("Archived QA observation belongs to another target")
    if (
        type(value["revision"]) is not int
        or value["revision"] < 0
        or type(value["active"]) is not bool
    ):
        raise ValueError("Invalid archived QA observation state")
    for key in ("predecessor", "incarnation"):
        if value[key] is not None:
            _identifier(value[key])
    expected = [] if parent is None else [parent]
    if not isinstance(value["parents"], list) or len(value["parents"]) != len(expected):
        raise ValueError("Invalid archived QA observation parents")
    for actual, wanted in zip(value["parents"], expected, strict=True):
        closed(actual, {"kind", "id", "incarnation", "active"})
        if actual != wanted or type(actual["active"]) is not bool:
            raise ValueError("Archived QA observation parent changed")


def validate_record(protocol, record):
    """Validate original scalar/JSON/source declarations without accessing files."""
    if protocol not in FORMATS:
        raise ValueError("Unknown QA enrollment history protocol")
    closed(record, FORMATS[protocol].split())
    if protocol == "research_chat_links":
        research_chat.validate_link(record)
        return {record["source_hash"]} if record["source_hash"] is not None else set()
    if protocol == "research_chat_review_receipts":
        from paper_daily.enrollment_chat_reviews import source_hashes

        return source_hashes(record)
    data = _value(record["context_json"])
    question = _value(record["question_json"])
    if record["answer_json"] is not None:
        _value(record["answer_json"])
    research_chat.validate_request_record(record)
    paper = data["parent"]["row"]
    if type(paper["_rowid"]) is not int or paper["_rowid"] < 1:
        raise ValueError("Invalid archived QA paper row identity")
    _text(paper["title"], 2000)
    _text(paper["venue"], 120, nullable=True)
    _text(paper["abstract"], 128 * 1024, nullable=True)
    if paper["year"] is not None and (
        type(paper["year"]) is not int or not 0 <= paper["year"] <= 2200
    ):
        raise ValueError("Invalid archived QA paper year")
    binding, portable = data["binding"], data["parent"]["portable"]
    if (binding is None) != (portable is None):
        raise ValueError("Archived QA portable parent differs from its binding")
    _observation(data["parent"]["observation"], binding=binding, kind="paper", identity=portable)
    parent = None
    if binding is not None:
        root = data["parent"]["observation"]
        parent = {
            "kind": "paper",
            "id": portable,
            "incarnation": root["incarnation"],
            "active": root["active"],
        }
    for name, key in (("user_observation", "user_key"), ("answer_observation", "answer_key")):
        identity = (
            content_id({"kind": "paper", "id": portable}, "chat", data[key]) if portable else None
        )
        _observation(
            data[name], binding=binding, kind="research_content", identity=identity, parent=parent
        )
    sources = _turn(question)
    for row in data["history"]:
        sources.update(_turn(row))
    document = data["document"]
    if document is not None:
        _text(document["path"], 32768)
        digest(document["sha256"])
        sources.add(document["sha256"])
        target = document["target"]
        if document["managed"] != (target is not None):
            raise ValueError("Archived QA document ownership differs from its target")
        if target is not None:
            _validate_target(target)
            if (
                binding is None
                or target["workspace_id"] != binding["workspace_id"]
                or target["paper_id"] != portable
                or target["sha256"] != document["sha256"]
            ):
                raise ValueError("Archived QA original target differs from its consumed source")
    if data["desired"] is not None:
        _validate_target(data["desired"])
        sources.add(data["desired"]["sha256"])
        if (
            binding is None
            or data["desired"]["workspace_id"] != binding["workspace_id"]
            or data["desired"]["paper_id"] != portable
        ):
            raise ValueError("Archived QA desired state belongs to another paper/workspace")
    anchor = None if question["anchor"] is None else _value(question["anchor"])
    if (
        anchor != data["anchor"]
        or question["page"] != data["page"]
        or question["source_hash"] != (document["sha256"] if document else None)
    ):
        raise ValueError("Archived QA question differs from its declared original source")
    return sources


def live_inventory(conn, ticket):
    """Retain explicit links; absent reply targets stay unresolved, never guessed."""
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    links = []
    if "research_chat_links" in existing:
        if [row[1] for row in conn.execute("PRAGMA table_info(research_chat_links)")] != FORMATS[
            "research_chat_links"
        ].split():
            raise ValueError("Unknown live QA linkage columns")
        for raw in conn.execute(
            "SELECT * FROM research_chat_links ORDER BY local_id LIMIT ?", (MAX_RECORDS + 1,)
        ):
            ticket.check()
            value = dict(zip(FORMATS["research_chat_links"].split(), raw, strict=True))
            validate_record("research_chat_links", value)
            links.append(value)
            if len(links) > MAX_RECORDS:
                raise ValueError("Live QA linkage exceeds its record budget")
    by_local = {row["local_id"]: row for row in links}
    turns = {}
    total = 0
    sources = set()
    live = []
    legacy = 0
    papers = {row[0] for row in conn.execute("SELECT id FROM papers")}
    for count, raw in enumerate(
        conn.execute("SELECT * FROM chat ORDER BY id LIMIT ?", (MAX_RECORDS + 1,)), 1
    ):
        ticket.check()
        value = dict(
            zip((column[1] for column in conn.execute("PRAGMA table_info(chat)")), raw, strict=True)
        )
        if set(value) != SQL_TURN or value["paper_id"] not in papers:
            raise ValueError("Live QA turn requires its exact known paper/schema")
        link = by_local.get(value["id"])
        turn = value | ({key: link[key] for key in LINK} if link else dict.fromkeys(LINK))
        hashes = _turn(turn)
        total += len(canonical_json(turn))
        sources.update((value["paper_id"], digest) for digest in hashes)
        if count > MAX_RECORDS or total > MAX_TOTAL:
            raise ValueError("Live QA turns exceed their inventory budget")
        if link:
            if link["message_id"] in turns:
                raise ValueError("Duplicate live QA message identity")
            turns[link["message_id"]] = turn
            live.append(link)
        else:
            legacy += 1
    unresolved = 0
    for turn in turns.values():
        if turn["role"] != "assistant":
            continue
        target = turns.get(turn["reply_to"])
        if target is None:
            unresolved += 1
        elif (
            target["role"] != "user"
            or target["paper_id"] != turn["paper_id"]
            or target["exchange_id"] != turn["exchange_id"]
        ):
            raise ValueError("Explicit QA reply target differs from its paper/exchange/user")
    return dict(
        links=live,
        sources=[{"paper_id": paper, "sha256": digest} for paper, digest in sorted(sources)],
        unresolved_replies=unresolved,
        legacy_unpaired=legacy,
        archived_orphan_links=len(links) - len(live),
    )


def sidecars(database, ticket):
    """Reuse the existing strict owned namespace; never open archived context paths."""
    from pathlib import Path

    result = []
    root = Path(database).resolve().parent
    for record in research_chat.list_recovery_requests(database):
        ticket.check()
        validate_record("research_chat_recovery", record)
        request = research_chat.ChatRequest(record["context_json"])
        location = research_chat._retained_path(request)
        if not location.is_relative_to(root):
            raise ValueError("QA history sidecar is outside its selected workspace")
        # The maintained locator checks ownership; strict decoding also rejects
        # duplicate outer keys rather than accepting json.loads' last value.
        with location.open("rb") as stream:
            raw = stream.read(research_chat.MAX_BYTES + 1)
        if len(raw) > research_chat.MAX_BYTES:
            raise ValueError("QA history sidecar exceeds its byte bound")
        original = _value(raw.decode("utf-8"))
        validate_record("research_chat_recovery", original)
        if canonical_json(original) != canonical_json(record):
            raise ValueError("QA history sidecar changed during validation")
        result.append((record, str(location)))
    return result


def install_live_in(conn, links):
    """Caller-owned staging/capture transaction; only semantic live link fields."""
    if not conn.in_transaction:
        raise ValueError("Live QA identity migration requires a caller transaction")
    if not links:
        return
    for link in links:
        validate_record("research_chat_links", link)
        row = conn.execute("SELECT * FROM chat WHERE id=?", (link["local_id"],)).fetchone()
        if row is None:
            raise ValueError("Live QA turn disappeared before identity migration")
        names = [column[1] for column in conn.execute("PRAGMA table_info(chat)")]
        _turn(dict(zip(names, row, strict=True)) | {key: link[key] for key in LINK})
        old = conn.execute(
            "SELECT * FROM research_chat_links WHERE local_id=?", (link["local_id"],)
        ).fetchone()
        if old is not None:
            if dict(zip(FORMATS["research_chat_links"].split(), old, strict=True)) != link:
                raise ValueError("Live QA identity is already bound to another message")
            continue
        conn.execute(
            "INSERT INTO research_chat_links VALUES(?,?,?,?,?)",
            tuple(link[key] for key in FORMATS["research_chat_links"].split()),
        )


def verify_live_in(conn, expected, ticket):
    actual = live_inventory(conn, ticket)
    if canonical_json(actual["links"]) != canonical_json(expected):
        raise ValueError("Live QA identities changed during staged projection")


def add_live_sources(inventory, live, manifests, owned_sources, papers):
    """Only consumed live declarations become current shared source artifacts."""
    for item in live["sources"]:
        paper, digest = item["paper_id"], item["sha256"]
        if paper not in papers:
            raise ValueError("Live QA original has no current paper")
        primary = manifests.get(paper)
        candidates = ([primary] if primary and primary["sha256"] == digest else []) + [
            row for row in owned_sources
            if row["sha256"] == digest and not row.get("archive_only", False)
        ]
        if not candidates:
            raise ValueError("Live QA requires its exact original source PDF")
        inventory[(paper, digest)] = dict(candidates[0])
