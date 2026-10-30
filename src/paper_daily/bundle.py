"""A reading list and everything worked out about it, as one file to hand on.

A list's value is mostly not its titles: it is the hours of analysis behind them --
deep dives, close readings, what each reference is doing, what came after, the
survey of the whole field, slide decks checked against the originals, and the
questions already asked. Re-running that on a colleague's machine costs the same
hours and model calls again. A bundle carries it across:

- the rows (papers, the list, every analysis keyed by paper, and optionally the
  notes and Q&A) as JSON;
- the files the app keeps beside the database, keyed by paper: rendered figures,
  slide decks, verified highlights, reading links;
- every locally available PDF, plus file fingerprints. Export and import of the
  default package work offline. Optional smaller packages retain verified URLs;
  imports of those older/link-only packages still check the exact PDF version.

Importing never overwrites what the colleague already has unless asked: a paper,
an analysis or a file already present stays theirs. Reading state stays with the
person who did the reading, so imported papers arrive unread; the list's order and
its pinned papers are part of the list and travel with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from paper_daily import annotation_content, bundle_files
from paper_daily.config import DATA_DIR, PDF_DIR
from paper_daily.fetch import _safe_name, pdf_candidates
from paper_daily.http import FetchError, fetch
from paper_daily.store import connect, get_kv, init_db, set_kv

FORMAT = 1

# Tables holding one paper's analyses, keyed by paper_id.
PER_PAPER = (
    "dives", "close_readings", "cites", "followups", "paper_context", "resources",
    *annotation_content.FEATURES.values(), "paper_annotation_known",
)
KV_KEYS = ("citegraph.{pid}", "followups.checked.{pid}", "resources:{pid}")


def _required_capabilities(tables):
    capabilities = []
    if tables.get("paper_claim_sets") or any(
            row.get("feature") == "claims" for row in tables.get("paper_annotation_known", [])):
        capabilities.append("claim_evidence")
    if tables.get("list_reading_goals"):
        capabilities.append("reading_goal")
    if any(tables.get(table) for table in annotation_content.FEATURES.values()):
        capabilities.append("reading_annotations")
    if tables.get("paper_annotation_known"):
        capabilities.append("annotation_deletions")
    return sorted(capabilities)


def _claim_source_relative(paper_id, fingerprint):
    from paper_daily.claim_content import hashed

    owner = hashed(["claim-source-owner", paper_id])[:24]
    return Path("pdf") / ".claim-evidence" / owner / (fingerprint + ".pdf")


def _digest(paper_id: str) -> str:
    return hashlib.sha256(paper_id.encode()).hexdigest()


def _paper_files(paper_id: str, *, derivatives=True) -> list[Path]:
    """The app's files about a paper, relative to the data directory."""
    out: list[Path] = []
    figures = DATA_DIR / "figures" / _safe_name(paper_id)
    if derivatives and figures.is_dir():
        out += [p.relative_to(DATA_DIR) for p in figures.rglob("*") if p.is_file()]
    # Decks live under the first 24 hex digits; their history stays behind, it is
    # the sharer's undo, not the deck.
    decks = DATA_DIR / "presentations" / _digest(paper_id)[:24]
    if decks.is_dir():
        out += [
            p.relative_to(DATA_DIR)
            for p in decks.rglob("*")
            if p.is_file() and "history" not in p.relative_to(decks).parts
        ]
    # The text extracted from the PDF is what questions, translation and any rerun
    # read; nothing rebuilds it when a PDF arrives by import rather than by analyze.
    text = DATA_DIR / "text" / f"{_safe_name(paper_id)}.txt"
    if derivatives and text.exists():
        out.append(text.relative_to(DATA_DIR))
    for folder in ("paper-highlights", "reading-links", "material-positions", "research-questions"):
        path = DATA_DIR / folder / (_digest(paper_id) + ".json")
        if path.exists():
            out.append(path.relative_to(DATA_DIR))
    return out


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _document(paper_id):
    """Resolve against the selected research DB, never another paper's alias."""
    from paper_daily.document_reader import from_workspace

    with connect() as conn:
        database = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    resolver = from_workspace(Path(database), legacy_root=PDF_DIR)
    status = resolver.inspect(paper_id)
    if status.managed:
        return resolver.resolve(paper_id)
    return status if status.status == "ambiguous" else None


def _document_path(paper_id, document):
    if document is not None:
        return document.path if document.available else None
    return PDF_DIR / f"{_safe_name(paper_id)}.pdf"


def pdf_record(row, log=lambda _m: None) -> dict | None:
    """The local PDF's fingerprint, and a URL that serves exactly it, if any.

    Downloading every candidate is slow, so the answer is kept in kv against the
    fingerprint and reused until the local file changes.
    """
    captured = _document(row["id"])
    path = _document_path(row["id"], captured)
    if path is None or not path.exists():
        return None
    blob = path.read_bytes()
    if captured is not None:
        if _sha256(blob) != captured.sha256:
            raise ValueError("The verified document changed during export")
        # A sync-owned PDF has no implicit publisher-fetch permission or stable public URL.
        return {"sha256": captured.sha256, "bytes": len(blob), "url": None}
    record = {"sha256": _sha256(blob), "bytes": len(blob), "url": None}
    key = f"pdf.verified.{row['id']}"
    with connect() as conn:
        known = get_kv(conn, key)
    if known and known.get("sha256") == record["sha256"]:
        return known
    urls = list(dict.fromkeys(pdf_candidates(row) + ([row["pdf_url"]] if row["pdf_url"] else [])))
    for url in urls:
        try:
            got = fetch(url, cache=False, retries=3)
        except FetchError:
            continue
        if _sha256(got) == record["sha256"]:
            record["url"] = url
            break
    arxiv = row["arxiv_id"]
    if not record["url"] and arxiv and "v" not in arxiv:
        # arXiv's bare URL serves the newest version, so a paper revised after it
        # was downloaded no longer matches; each version keeps its own fixed URL.
        for version in range(1, 10):
            url = f"https://arxiv.org/pdf/{arxiv}v{version}"
            try:
                got = fetch(url, cache=False, retries=3)
            except FetchError:
                break
            if _sha256(got) == record["sha256"]:
                record["url"] = url
                break
    log(f"  {'verified' if record['url'] else 'no URL serves it'}: {row['title'][:60]}")
    with connect() as conn:
        set_kv(conn, key, record)
        conn.commit()
    return record


def _rows(conn, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


def export(
    list_id: str, out: Path, notes: bool = True, with_pdfs: bool = True, log=lambda _m: None
) -> dict:
    """Write the bundle for one list. Returns what went in.

    `with_pdfs` packs every locally available PDF without requiring the network.
    """
    with connect() as conn:
        database_root = Path(next(row[2] for row in conn.execute("PRAGMA database_list")
                                  if row[1] == "main")).parent
        listing = conn.execute("SELECT * FROM lists WHERE id=?", (list_id,)).fetchone()
        if listing is None:
            raise ValueError(f"no list {list_id}")
        members = _rows(
            conn,
            "SELECT paper_id, position, citation, added_at FROM list_papers "
            "WHERE list_id=? ORDER BY position",
            (list_id,),
        )
        ids = [m["paper_id"] for m in members]
        marks_sql = ",".join("?" * len(ids))
        tables = {
            "papers": _rows(conn, f"SELECT * FROM papers WHERE id IN ({marks_sql})", ids),
            # Every graph edge touching the list, with the papers at the far end:
            # the reference tab and the citation map draw them, and without their
            # rows the receiver would see fewer references than the sharer.
            "refs": _rows(
                conn,
                f"SELECT * FROM refs WHERE paper_id IN ({marks_sql}) "
                f"OR ref_paper_id IN ({marks_sql})",
                (*ids, *ids),
            ),
            "list_surveys": _rows(conn, "SELECT * FROM list_surveys WHERE list_id=?", (list_id,)),
        }
        goals = _rows(conn, "SELECT * FROM list_reading_goals WHERE list_id=?", (list_id,))
        if goals:
            tables["list_reading_goals"] = goals
        far = sorted(
            {e for r in tables["refs"] for e in (r["paper_id"], r["ref_paper_id"])} - set(ids)
        )
        tables["cited_papers"] = _rows(
            conn, f"SELECT * FROM papers WHERE id IN ({','.join('?' * len(far))})", far
        )
        for table in PER_PAPER:
            if table in annotation_content.FEATURES.values() and not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (table,)
            ).fetchone():
                tables[table] = []
                continue
            tables[table] = _rows(
                conn, f"SELECT * FROM {table} WHERE paper_id IN ({marks_sql})", ids
            )
        # Marks on the PDF are tied to its fingerprint, which the receiver's copy now
        # shares, so they carry over as they are. The verified-quote marks are part
        # of the analysis (without them the step reads as not done and would be
        # paid for again); the reader's own highlighter marks go with the notes.
        for table in ["pdf_ai_highlights"] + (["pdf_highlights"] if notes else []):
            rows = _rows(conn, f"SELECT * FROM {table} WHERE paper_id IN ({marks_sql})", ids)
            tables[table] = [{k: v for k, v in r.items() if k != "id"} for r in rows]
        tables["pins"] = _rows(
            conn, "SELECT paper_id, pinned_at FROM pins WHERE scope=?", (list_id,)
        )
        if notes:
            for table in ("notes", "chat"):
                rows = _rows(conn, f"SELECT * FROM {table} WHERE paper_id IN ({marks_sql})", ids)
                tables[table] = [{k: v for k, v in r.items() if k != "id"} for r in rows]
                if table == "chat":
                    from paper_daily.research_chat import history

                    by_id = {row["id"]: row for pid in ids for row in history(conn, pid)}
                    for source, exported in zip(rows, tables[table], strict=True):
                        linked = by_id[source["id"]]
                        if linked.get("message_id"):
                            exported.update(
                                {
                                    key: linked[key]
                                    for key in (
                                        "message_id",
                                        "exchange_id",
                                        "reply_to",
                                        "source_hash",
                                    )
                                }
                            )
        keys = [k.format(pid=pid) for pid in ids for k in KV_KEYS]
        kv = _rows(conn, f"SELECT * FROM kv WHERE key IN ({','.join('?' * len(keys))})", keys)

    pdfs, captured, paths = {}, {}, {}
    for row in tables["papers"]:
        pid = row["id"]
        captured[pid] = _document(pid)
        path = _document_path(pid, captured[pid])
        paths[pid] = path
        if with_pdfs:
            blob = path.read_bytes() if path is not None and path.exists() else None
            pdfs[pid] = (
                dict(sha256=_sha256(blob), bytes=len(blob), url=None) if blob is not None else None
            )
            if (
                captured[pid] is not None
                and blob is not None
                and pdfs[pid]["sha256"] != captured[pid].sha256
            ):
                raise ValueError("The verified document changed during export")
        else:
            pdfs[pid] = pdf_record(row, log)
    # Legacy aliases may contain another revision. Reproducible derivatives can be
    # regenerated locally from the exported PDF; curated decks retain their own assets.
    files = {
        relative: DATA_DIR / relative
        for pid in ids
        for relative in _paper_files(pid, derivatives=captured[pid] is None)
    }
    if with_pdfs:
        files.update(
            {Path("pdf") / f"{_safe_name(pid)}.pdf": paths[pid] for pid, rec in pdfs.items() if rec}
        )
    claim_sources = {}
    for claim in tables.get("paper_claim_sets", []):
        annotation_content.validate_row("claims", claim)
        pid, digest = claim["paper_id"], claim["document_hash"]
        relative = _claim_source_relative(pid, digest)
        included = None
        if with_pdfs:
            candidate = database_root / relative
            current = paths.get(pid)
            if candidate.exists() and _sha256(candidate.read_bytes()) == digest:
                selected = candidate
            elif (current is not None and current.exists()
                  and _sha256(current.read_bytes()) == digest):
                selected = current
            else:
                raise ValueError("The exact original claim-source PDF is unavailable for sharing")
            files[relative] = selected
            included = relative.as_posix()
        claim_sources[pid] = {"sha256": digest, "path": included}
    capabilities = _required_capabilities(tables)
    manifest = {
        "format": 2 if capabilities else FORMAT,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "list": dict(listing),
        "members": members,
        "pdfs": pdfs,
        "notes_included": notes,
        "pdfs_included": with_pdfs,
        "file_hashes": {f.as_posix(): _sha256(source.read_bytes()) for f, source in files.items()},
        "counts": {t: len(rows) for t, rows in tables.items()} | {"files": len(files)},
    }
    if "claim_evidence" in capabilities:
        manifest["claim_sources"] = claim_sources
    if capabilities:
        manifest["capabilities"] = capabilities
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=out.parent, prefix=".paperfact-export-", delete=False
    ) as f:
        staged = Path(f.name)
    try:
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            z.writestr("tables.json", json.dumps({**tables, "kv": kv}, ensure_ascii=False))
            for rel, source in files.items():
                z.write(source, "files/" + rel.as_posix())
        # Detect research files changed during packing before replacing a prior export.
        with zipfile.ZipFile(staged) as z:
            _validated(z)
        from paper_daily.document_reader import document_current

        if any(
            item.managed and not document_current(item)
            for item in captured.values()
            if item is not None and item.available
        ):
            raise ValueError("The selected document version changed during export; retry")
        os.replace(staged, out)
    finally:
        staged.unlink(missing_ok=True)
    return {
        "out": out,
        "papers": len(ids),
        "bytes": out.stat().st_size,
        "pdf_verified": sum(1 for r in pdfs.values() if r and r["url"]),
        "pdf_unverified": [pid for pid, r in pdfs.items() if r and not r["url"]],
        "pdf_missing": [pid for pid, r in pdfs.items() if r is None],
        "pdf_packed": sum(1 for r in pdfs.values() if r) if with_pdfs else 0,
        **manifest["counts"],
    }


def _insert(conn, table: str, rows: list[dict], replace: bool) -> int:
    """Add rows the local database lacks (or all of them, replacing). Only the
    columns both sides know are written, so a bundle from an older or newer app
    still imports."""
    if not rows:
        return 0
    local = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    added = 0
    for row in rows:
        cols = [c for c in row if c in local]
        verb = "INSERT" if replace else "INSERT OR IGNORE"
        conflict = (
            " ON CONFLICT DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in cols)
            if replace
            else ""
        )
        cur = conn.execute(
            f"{verb} INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))}){conflict}",
            [row[c] for c in cols],
        )
        added += cur.rowcount > 0
    return added


def fetch_pdfs(pdfs: dict, titles: dict, log=lambda _m: None, *, replace=False) -> dict:
    """Download each PDF from its verified URL, keeping it only if it is the same
    file. Returns which papers are now right, and which still need the file."""
    got, need = [], []
    for pid, rec in pdfs.items():
        if not rec:
            continue
        captured = _document(pid)
        if captured is not None:
            (got if captured.available and captured.sha256 == rec["sha256"] else need).append(pid)
            continue
        dest = PDF_DIR / f"{_safe_name(pid)}.pdf"
        if dest.exists() and _sha256(dest.read_bytes()) == rec["sha256"]:
            got.append(pid)
            continue
        if dest.exists() and not replace:
            need.append(pid)
            continue
        blob = None
        if rec["url"]:
            try:
                blob = fetch(rec["url"], cache=False, retries=4)
            except FetchError:
                blob = None
        if blob is not None and _sha256(blob) == rec["sha256"]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            got.append(pid)
            log(f"  PDF ok: {titles.get(pid, pid)[:60]}")
            continue
        need.append(pid)
        # Keep `analyze` from downloading some other version of this paper: the
        # analyses' page numbers and figures refer to the sharer's file.
        with connect() as conn:
            set_kv(
                conn,
                f"analyze.failed.pdf.{pid}",
                f"needs the shared version (sha256 {rec['sha256'][:12]}); ask the sharer for "
                "the file and add it with repdf --file",
            )
            conn.commit()
        log(f"  PDF needed from the sharer: {titles.get(pid, pid)[:60]}")
    return {"pdf_ok": got, "pdf_needed": need}


def inspect(path: Path) -> dict:
    """Validate all contents before touching the workspace; return a reviewable summary."""
    with zipfile.ZipFile(path) as z:
        manifest, tables, _owners = _validated(z)
    with connect() as conn:
        _check_workspace_aliases(conn, _owners)
        existing = {r[0] for r in conn.execute("SELECT id FROM papers")}
        list_exists = bool(
            conn.execute("SELECT 1 FROM lists WHERE id=?", (manifest["list"]["id"],)).fetchone()
        )
    return dict(
        name=manifest["list"]["name"],
        list_id=manifest["list"]["id"],
        papers=len(manifest["members"]),
        pdfs=sum(name.startswith("pdf/") for name in _owners),
        missing_pdfs=sum(not record for record in manifest.get("pdfs", {}).values()),
        analyses=sum(len(tables.get(t, [])) for t in PER_PAPER),
        notes=len(tables.get("notes", [])),
        chats=len(tables.get("chat", [])),
        conflicts=sum(p["id"] in existing for p in tables["papers"]),
        list_exists=list_exists,
    )


def _validated(z):
    names = z.namelist()
    if len(names) != len({name.casefold() for name in names}):
        raise ValueError("資料包包含重複檔名")
    try:
        manifest = json.loads(z.read("manifest.json"))
        tables = json.loads(z.read("tables.json"))
        if type(manifest.get("format")) is not int or manifest["format"] not in (FORMAT, 2):
            raise ValueError("不支援的研究資料包格式")
        listing = manifest["list"]
        if not all(
            isinstance(listing.get(k), str) and listing[k] for k in ("id", "name", "created_at")
        ):
            raise ValueError("資料包缺少清單資訊")
        required = _required_capabilities(tables)
        capabilities = manifest.get("capabilities", [])
        if manifest["format"] == 2:
            if not required or capabilities != required:
                raise ValueError("Package capabilities do not match its research content")
        elif required or capabilities:
            raise ValueError("Extended research requires the version-2 package format")
        goals = tables.get("list_reading_goals", [])
        if not isinstance(goals, list) or len(goals) > 1:
            raise ValueError("Reading-goal package requires at most one goal row")
        from paper_daily.sync_content import validate_payload

        for goal in goals:
            if (not isinstance(goal, dict) or set(goal) != {"list_id", "body", "written_at"}
                    or goal["list_id"] != listing["id"]):
                raise ValueError("Reading goal does not belong to this list")
            validate_payload({
                "scope": {"kind": "list", "id": listing["id"]},
                "feature": "reading_goal", "key": "main", "source_document_hash": None,
                "data": {key: goal[key] for key in ("body", "written_at")},
            })
        ids = {p["id"] for p in tables["papers"]}
        from paper_daily.research_chat import validate_shared_turn

        for feature, table in annotation_content.FEATURES.items():
            for row in tables.get(table, []):
                annotation_content.validate_row(feature, row)
        for row in tables.get("paper_annotation_known", []):
            if (set(row) != {"feature", "paper_id"}
                    or row["feature"] not in annotation_content.FEATURES
                    or not isinstance(row["paper_id"], str) or not row["paper_id"]):
                raise ValueError("Invalid reading annotation authority marker")
        claim_rows = {row["paper_id"]: row["document_hash"]
                      for row in tables.get("paper_claim_sets", [])}
        claim_sources = manifest.get("claim_sources", {})
        if not isinstance(claim_sources, dict) or set(claim_sources) != set(claim_rows):
            raise ValueError("Claim package source ownership differs from its research")
        for pid, digest in claim_rows.items():
            record = claim_sources[pid]
            if not isinstance(record, dict) or set(record) != {"sha256", "path"}:
                raise ValueError("Invalid claim-source package manifest")
            expected = _claim_source_relative(pid, digest).as_posix()
            if record["sha256"] != digest or record["path"] not in (None, expected):
                raise ValueError("Claim-source package identity differs")
            if record["path"] is None:
                if manifest.get("pdfs_included"):
                    raise ValueError("Complete claim packages require original source bytes")
            elif (manifest.get("file_hashes", {}).get(expected) != digest
                  or "files/" + expected not in names):
                raise ValueError("Claim-source package bytes are missing or changed")
        linked_ids = set()
        for turn in tables.get("chat", []):
            if validate_shared_turn(turn):
                if turn["message_id"] in linked_ids:
                    raise ValueError("Duplicate shared conversation identity")
                linked_ids.add(turn["message_id"])
        if any(m["paper_id"] not in ids for m in manifest["members"]):
            raise ValueError("清單內有缺少資料的論文")
        for table in (*PER_PAPER, "pdf_ai_highlights", "pdf_highlights", "notes", "chat"):
            if any(row["paper_id"] not in ids for row in tables.get(table, [])):
                raise ValueError("資料包包含清單以外的分析")
        allowed_keys = {key.format(pid=pid) for pid in ids for key in KV_KEYS}
        if any(row["key"] not in allowed_keys for row in tables.get("kv", [])):
            raise ValueError("資料包包含非研究設定")
        if any(row["list_id"] != listing["id"] for row in tables.get("list_surveys", [])):
            raise ValueError("清單綜覽不屬於此資料包")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("請選擇 Paperfact 匯出的研究資料包，非軟體原始碼 ZIP") from exc
    for relative in manifest.get("file_hashes", {}):
        if "files/" + relative not in names:
            raise ValueError(f"資料包缺少檔案：{relative}")
    if manifest.get("pdfs_included"):
        for pid, record in manifest.get("pdfs", {}).items():
            if record and f"files/pdf/{_safe_name(pid)}.pdf" not in names:
                raise ValueError(f"資料包缺少 PDF：{pid}")
    owners = {}
    for name in names:
        if not name.startswith("files/") or name.endswith("/"):
            continue
        relative = name.removeprefix("files/")
        rel = Path(relative)
        if (
            "\\" in relative
            or ":" in relative
            or ".." in rel.parts
            or rel.is_absolute()
            or not (DATA_DIR / rel).resolve().is_relative_to(DATA_DIR.resolve())
        ):
            raise ValueError(f"bundle path escapes the data directory: {name}")
        matches = [pid for pid in ids if _owns_file(pid, rel)]
        if len(matches) != 1:
            raise ValueError(f"資料包檔案缺少唯一論文歸屬：{relative}")
        owner = matches[0]
        if rel.parts[0] in ("pdf", "text", "figures") and any(
            pid != owner and _safe_name(pid).casefold() == _safe_name(owner).casefold()
            for pid in ids
        ):
            raise ValueError("Bundle filenames alias multiple papers")
        blob = z.read(name)  # also validates CRC, including legacy bundles
        expected = manifest.get("file_hashes", {}).get(relative)
        if expected and _sha256(blob) != expected:
            raise ValueError(f"資料包檔案核對失敗：{relative}")
        if rel.parts[0] == "pdf":
            claim_source = len(rel.parts) == 4 and rel.parts[1] == ".claim-evidence"
            record = manifest.get("claim_sources" if claim_source else "pdfs", {}).get(owner)
            if not record or _sha256(blob) != record.get("sha256"):
                raise ValueError("Package PDF source version differs")
            if claim_source and record["path"] != relative:
                raise ValueError("Undeclared claim-source package file")
        owners[relative] = owner
    return manifest, tables, owners


def _owns_file(pid, rel):
    parts = rel.parts
    if len(parts) == 4 and parts[:2] == ("pdf", ".claim-evidence"):
        fingerprint = rel.stem
        return (len(fingerprint) == 64 and all(char in "0123456789abcdef" for char in fingerprint)
                and rel == _claim_source_relative(pid, fingerprint))
    if len(parts) == 2:
        folder, name = parts
        if folder in ("pdf", "text"):
            return name == _safe_name(pid) + (".pdf" if folder == "pdf" else ".txt")
        if folder in (
            "paper-highlights",
            "reading-links",
            "material-positions",
            "research-questions",
        ):
            return name == _digest(pid) + ".json"
    return len(parts) >= 3 and (
        (parts[0] == "figures" and parts[1] == _safe_name(pid))
        or (parts[0] == "presentations" and parts[1] == _digest(pid)[:24])
    )


def _check_workspace_aliases(conn, owners):
    """A bundle may not claim another local paper's sanitized filename."""
    aliases = {}
    for (paper_id,) in conn.execute("SELECT id FROM papers"):
        aliases.setdefault(_safe_name(paper_id).casefold(), set()).add(paper_id)
    for relative, owner in owners.items():
        if Path(relative).parts[0] not in ("pdf", "text", "figures"):
            continue
        if aliases.get(_safe_name(owner).casefold(), set()) - {owner}:
            raise ValueError("Bundle file aliases another local paper; reconcile identities first")


def import_(path: Path, replace: bool = False, pdfs: bool = True, log=lambda _m: None) -> dict:
    """Bring a bundle into this workspace. Returns what was added.

    With `pdfs`, each paper's PDF is then fetched from its verified URL and kept
    only if it is byte for byte the file the analyses were made from."""
    from contextlib import closing

    from paper_daily import store

    captured = False
    database = Path(store.DB_PATH).resolve()
    if database.is_file():
        import sqlite3

        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            markers = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','trigger')"
            )}
            captured = any(name.startswith(("research_capture_", "capture_")) for name in markers)
    if captured:
        # A damaged capture binding must fail here; it cannot opt back into the
        # legacy writer. Reader-only historical adapters retain their old path.
        from paper_daily.package_import import import_package

        return import_package(
            database, DATA_DIR, path, replace=replace,
            current_path=lambda: store.DB_PATH,
        )
    init_db()
    with zipfile.ZipFile(path) as z:
        manifest, tables, owners = _validated(z)
        listing = manifest["list"]
        with connect() as conn:
            _check_workspace_aliases(conn, owners)
        report: dict = {"list": listing["id"], "name": listing["name"]}
        conflicts = set()
        managed = {}
        for row in tables["papers"]:
            pid = row["id"]
            captured = _document(pid)
            if captured is not None:
                managed[pid] = captured
                rec = manifest.get("pdfs", {}).get(pid)
                if not rec or not captured.available or captured.sha256 != rec["sha256"]:
                    conflicts.add(pid)
        for pid, rec in manifest.get("pdfs", {}).items():
            if pid in managed:
                continue
            local = PDF_DIR / f"{_safe_name(pid)}.pdf"
            if (
                rec
                and local.exists()
                and not replace
                and _sha256(local.read_bytes()) != rec["sha256"]
            ):
                conflicts.add(pid)
        # Imported page numbers must never be attached to a different local PDF.
        for table in (*PER_PAPER, "pdf_ai_highlights", "pdf_highlights", "notes", "chat"):
            tables[table] = [r for r in tables.get(table, []) if r["paper_id"] not in conflicts]
        tables["kv"] = [
            r
            for r in tables.get("kv", [])
            if not any(
                r["key"] == template.format(pid=pid) for pid in conflicts for template in KV_KEYS
            )
        ]
        relatives = []
        for name in z.namelist():
            if not name.startswith("files/") or name.endswith("/"):
                continue
            relative = Path(name.removeprefix("files/"))
            owner = owners[relative.as_posix()]
            if owner in conflicts:
                continue
            if relative.parts[0] == "pdf" and len(relative.parts) == 2 and owner in managed:
                continue  # Existing managed bytes remain owned by the document binding.
            target = (DATA_DIR / relative).resolve()
            if not target.is_relative_to(DATA_DIR.resolve()):
                raise ValueError("Bundle file escapes the workspace")
            if target.exists() and not replace:
                continue
            relatives.append(relative)
        # Stage bytes before taking a database write lock. A failed file write or
        # database commit restores installed files as the connection rolls back.
        with bundle_files.stage(DATA_DIR, z, relatives) as staged, connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _check_workspace_aliases(conn, owners)
            report["papers"] = _insert(conn, "papers", tables["papers"], replace)
            # Context only: never let the bundle overwrite a paper the receiver keeps.
            report["cited_papers"] = _insert(
                conn, "papers", tables.get("cited_papers", []), replace=False
            )
            conn.execute(
                "INSERT OR IGNORE INTO lists(id, name, note, created_at) VALUES (?,?,?,?)",
                (listing["id"], listing["name"], listing.get("note"), listing["created_at"]),
            )
            have = {
                r[0]
                for r in conn.execute(
                    "SELECT paper_id FROM list_papers WHERE list_id=?", (listing["id"],)
                )
            }
            last = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM list_papers WHERE list_id=?",
                (listing["id"],),
            ).fetchone()[0]
            joined = 0
            for m in manifest["members"]:
                if m["paper_id"] in have:
                    continue
                last += 1
                conn.execute(
                    "INSERT INTO list_papers(list_id, paper_id, position, state, citation, "
                    "added_at) VALUES (?,?,?,'pending',?,?)",
                    (listing["id"], m["paper_id"], last, m.get("citation"), m["added_at"]),
                )
                joined += 1
            report["joined_list"] = joined
            pins = [{"scope": listing["id"], **pin} for pin in tables.get("pins", [])]
            report["pins"] = _insert(conn, "pins", pins, replace=False)
            for table in ("refs", "list_surveys", "list_reading_goals", *PER_PAPER):
                report[table] = _insert(conn, table, tables.get(table, []), replace)
            report["kv"] = _insert(conn, "kv", tables.get("kv", []), replace)
            for table in ("pdf_ai_highlights", "pdf_highlights"):
                report[table] = _insert(conn, table, tables.get(table, []), replace)
            seen = {(r[0], r[1]) for r in conn.execute("SELECT paper_id, body FROM notes")}
            fresh = [r for r in tables.get("notes", []) if (r["paper_id"], r["body"]) not in seen]
            report["notes"] = _insert(conn, "notes", fresh, replace=False)
            # A conversation is a sequence of turns: skipping one duplicate turn in
            # the middle would pair a question with the wrong answer, so only a
            # paper with no conversation here yet receives one.
            talked = {r[0] for r in conn.execute("SELECT DISTINCT paper_id FROM chat")}
            from paper_daily.research_chat import import_shared_turn

            fresh = [
                r
                for r in tables.get("chat", [])
                if not r.get("message_id") and r["paper_id"] not in talked
            ]
            report["chat"] = _insert(conn, "chat", fresh, replace=False)
            for turn in tables.get("chat", []):
                if turn.get("message_id"):
                    report["chat"] += import_shared_turn(conn, turn)
            from paper_daily.document_reader import document_current

            if any(
                not document_current(item) for pid, item in managed.items() if pid not in conflicts
            ):
                raise ValueError("The document version changed during import; retry")
            report["files"] = staged.install()
    if pdfs:
        titles = {r["id"]: r["title"] for r in tables["papers"]}
        report |= fetch_pdfs(manifest.get("pdfs") or {}, titles, log, replace=replace)
    report["pdf_conflicts"] = sorted(conflicts)
    return report
