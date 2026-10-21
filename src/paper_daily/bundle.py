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

from paper_daily import bundle_files
from paper_daily.config import DATA_DIR, PDF_DIR
from paper_daily.fetch import _safe_name, pdf_candidates
from paper_daily.http import FetchError, fetch
from paper_daily.store import connect, get_kv, init_db, set_kv

FORMAT = 1

# Tables holding one paper's analyses, keyed by paper_id.
PER_PAPER = ("dives", "close_readings", "cites", "followups", "paper_context", "resources")
KV_KEYS = ("citegraph.{pid}", "followups.checked.{pid}", "resources:{pid}")


def _digest(paper_id: str) -> str:
    return hashlib.sha256(paper_id.encode()).hexdigest()


def _paper_files(paper_id: str) -> list[Path]:
    """The app's files about a paper, relative to the data directory."""
    out: list[Path] = []
    figures = DATA_DIR / "figures" / _safe_name(paper_id)
    if figures.is_dir():
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
    if text.exists():
        out.append(text.relative_to(DATA_DIR))
    for folder in ("paper-highlights", "reading-links", "material-positions", "research-questions"):
        path = DATA_DIR / folder / (_digest(paper_id) + ".json")
        if path.exists():
            out.append(path.relative_to(DATA_DIR))
    return out


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def pdf_record(row, log=lambda _m: None) -> dict | None:
    """The local PDF's fingerprint, and a URL that serves exactly it, if any.

    Downloading every candidate is slow, so the answer is kept in kv against the
    fingerprint and reused until the local file changes.
    """
    path = PDF_DIR / f"{_safe_name(row['id'])}.pdf"
    if not path.exists():
        return None
    blob = path.read_bytes()
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
        far = sorted(
            {e for r in tables["refs"] for e in (r["paper_id"], r["ref_paper_id"])} - set(ids)
        )
        tables["cited_papers"] = _rows(
            conn, f"SELECT * FROM papers WHERE id IN ({','.join('?' * len(far))})", far
        )
        for table in PER_PAPER:
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
        keys = [k.format(pid=pid) for pid in ids for k in KV_KEYS]
        kv = _rows(conn, f"SELECT * FROM kv WHERE key IN ({','.join('?' * len(keys))})", keys)

    pdfs = {}
    for row in tables["papers"]:
        path = PDF_DIR / f"{_safe_name(row['id'])}.pdf"
        if with_pdfs:
            pdfs[row["id"]] = (
                dict(sha256=_sha256(path.read_bytes()), bytes=path.stat().st_size, url=None)
                if path.exists()
                else None
            )
        else:
            pdfs[row["id"]] = pdf_record(row, log)
    files = [f for pid in ids for f in _paper_files(pid)]
    if with_pdfs:
        files += [
            (PDF_DIR / f"{_safe_name(pid)}.pdf").relative_to(DATA_DIR)
            for pid, rec in pdfs.items()
            if rec
        ]
    manifest = {
        "format": FORMAT,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "list": dict(listing),
        "members": members,
        "pdfs": pdfs,
        "notes_included": notes,
        "pdfs_included": with_pdfs,
        "file_hashes": {f.as_posix(): _sha256((DATA_DIR / f).read_bytes()) for f in files},
        "counts": {t: len(rows) for t, rows in tables.items()} | {"files": len(files)},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=out.parent, prefix=".paperfact-export-", delete=False
    ) as f:
        staged = Path(f.name)
    try:
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            z.writestr("tables.json", json.dumps({**tables, "kv": kv}, ensure_ascii=False))
            for rel in files:
                z.write(DATA_DIR / rel, "files/" + rel.as_posix())
        # Detect research files changed during packing before replacing a prior export.
        with zipfile.ZipFile(staged) as z:
            _validated(z)
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
    if len(names) != len(set(names)):
        raise ValueError("資料包包含重複檔名")
    try:
        manifest = json.loads(z.read("manifest.json"))
        tables = json.loads(z.read("tables.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError("不支援的研究資料包格式")
        listing = manifest["list"]
        if not all(
            isinstance(listing.get(k), str) and listing[k] for k in ("id", "name", "created_at")
        ):
            raise ValueError("資料包缺少清單資訊")
        ids = {p["id"] for p in tables["papers"]}
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
        owner = next((pid for pid in ids if _owns_file(pid, rel)), None)
        if owner is None:
            raise ValueError(f"資料包包含不屬於論文的檔案：{relative}")
        blob = z.read(name)  # also validates CRC, including legacy bundles
        expected = manifest.get("file_hashes", {}).get(relative)
        if expected and _sha256(blob) != expected:
            raise ValueError(f"資料包檔案核對失敗：{relative}")
        if rel.parts[0] == "pdf":
            record = manifest.get("pdfs", {}).get(owner)
            if not record or _sha256(blob) != record.get("sha256"):
                raise ValueError(f"PDF 版本核對失敗：{relative}")
        owners[relative] = owner
    return manifest, tables, owners


def _owns_file(pid, rel):
    parts = rel.parts
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


def import_(path: Path, replace: bool = False, pdfs: bool = True, log=lambda _m: None) -> dict:
    """Bring a bundle into this workspace. Returns what was added.

    With `pdfs`, each paper's PDF is then fetched from its verified URL and kept
    only if it is byte for byte the file the analyses were made from."""
    init_db()
    with zipfile.ZipFile(path) as z:
        manifest, tables, owners = _validated(z)
        listing = manifest["list"]
        report: dict = {"list": listing["id"], "name": listing["name"]}
        conflicts = set()
        for pid, rec in manifest.get("pdfs", {}).items():
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
            if owners[relative.as_posix()] in conflicts:
                continue
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
            for table in ("refs", "list_surveys", *PER_PAPER):
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
            fresh = [r for r in tables.get("chat", []) if r["paper_id"] not in talked]
            report["chat"] = _insert(conn, "chat", fresh, replace=False)
            report["files"] = staged.install()
    if pdfs:
        titles = {r["id"]: r["title"] for r in tables["papers"]}
        report |= fetch_pdfs(manifest.get("pdfs") or {}, titles, log, replace=replace)
    report["pdf_conflicts"] = sorted(conflicts)
    return report
