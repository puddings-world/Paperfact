"""Prepare selected-list intake with the existing offline package operations."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from paper_daily import runtime, store
from paper_daily.workspace_open import _environment
from paper_daily.workspace_service import _read, _tables


def package_command(root, arguments, ticket):
    environment = _environment(os.environ)
    environment["PAPERFACT_DATA"] = str(root)
    environment["OTEL_SDK_DISABLED"] = "true"
    if not runtime.FROZEN:
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    options = dict(
        env=environment,
        cwd=str(root),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        )
    process = subprocess.Popen(runtime.cli_command(*arguments), **options)
    try:
        while True:
            ticket.check()
            try:
                process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise ValueError(
                "Selected-list package preparation failed; source research is retained"
            )
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise


def prepare_selected(database, list_ids, destination, ticket, progress):
    ticket.check()
    ids = list(dict.fromkeys(list_ids))
    if (
        not ids
        or len(ids) > 100
        or any(not isinstance(value, str) or not value or len(value) > 128 for value in ids)
    ):
        raise ValueError("Choose between one and 100 research lists")
    ids.sort()  # Cached package indexes follow the same order as the selection receipt.
    database, destination = Path(database), Path(destination)
    if database.name != "papers.db":
        raise ValueError("Select a Paperfact papers.db workspace")
    with _read(database) as conn:
        selected = {row[0] for row in conn.execute("SELECT id FROM lists")}
        if not set(ids) <= selected:
            raise ValueError("A selected list is no longer available")
    destination.mkdir(parents=True, exist_ok=True)
    intake = destination / "papers.db"
    if not intake.exists():
        with closing(sqlite3.connect(intake)) as conn:
            conn.executescript(store.SCHEMA)
            store._migrate(conn)
            conn.commit()
    packages = destination.parent / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    for index, identity in enumerate(ids):
        ticket.check()
        progress(dict(stage="selected_lists", completed=index, total=len(ids)))
        archive = packages / ("selected-" + str(index) + ".zip")
        if not archive.exists():
            package_command(
                database.parent, ["list-export", "--out", str(archive), "--", identity], ticket
            )
        package_command(destination, ["list-import", "--no-pdfs", "--", str(archive)], ticket)
    # Peer packages deliberately omit personal queue/history. Keep those local
    # personal records for the selected papers before first-sync enrollment.
    with _read(database) as source, closing(sqlite3.connect(intake)) as target:
        if {row[0] for row in target.execute("SELECT id FROM lists")} != set(ids):
            raise ValueError("Staged lists differ from this selection; prepare a fresh copy")
        marks = ",".join("?" for _ in ids)
        members = source.execute(
            "SELECT state,delivered_at,read_at,list_id,paper_id FROM list_papers "
            f"WHERE list_id IN ({marks}) ORDER BY list_id,paper_id", ids
        ).fetchall()
        staged = target.execute(
            "SELECT list_id,paper_id FROM list_papers ORDER BY list_id,paper_id"
        ).fetchall()
        if staged != [row[3:] for row in members]:
            raise ValueError("Selected membership changed; prepare a fresh copy")
        ticket.check()
        target.executemany(
            "UPDATE list_papers SET state=?,delivered_at=?,read_at=? "
            "WHERE list_id=? AND paper_id=?",
            members,
        )
        papers = sorted({row[4] for row in members})
        for table in ("queue", "reading_log"):
            if table not in _tables(source):
                continue
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
            received = [row[1] for row in target.execute(f"PRAGMA table_info({table})")]
            if columns != received or "paper_id" not in columns:
                raise ValueError("Selected reading state needs a compatible workspace schema")
            if target.execute(
                f"SELECT 1 FROM {table} r WHERE NOT EXISTS (SELECT 1 FROM list_papers lp "
                "WHERE lp.paper_id=r.paper_id) LIMIT 1"
            ).fetchone():
                raise ValueError("Out-of-scope staged history; prepare a fresh copy")
            for offset in range(0, len(papers), 400):
                ticket.check()
                batch = papers[offset : offset + 400]
                slots = ",".join("?" for _ in batch)
                rows = source.execute(f"SELECT * FROM {table} WHERE paper_id IN ({slots})", batch)
                values = ",".join("?" for _ in columns)
                target.executemany(
                    f"INSERT OR IGNORE INTO {table} VALUES({values})", [tuple(row) for row in rows]
                )
        ticket.checkpoint(target.commit)
    progress(dict(stage="selected_lists", completed=len(ids), total=len(ids)))
    return intake
