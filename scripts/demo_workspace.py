"""A small workspace to photograph: one list, a paper with its PDF and a deep dive.

The build machines have no papers.db, and the screenshots taken there are how a
layout is checked on Windows, macOS and Linux side by side. Everything here is
written for the purpose; nothing is copied from a real paper.
"""

from __future__ import annotations

from datetime import datetime

LIST_ID = "demo"
PAPER_ID = "demo:paperfact"

DIVE = r"""## 一句話結論

這篇示範論文提出一個讀論文的工作流程：先讀講解，再對照原文，最後把筆記整理成簡報。

## 核心方法

閱讀進度以 $p_t = \frac{r_t}{n}$ 表示，其中 $r_t$ 是第 $t$ 天讀完的段落數。

```pseudocode
for each paper in list:
    read the deep dive
    check claims against the PDF
```

## 審稿人會問

- 這個流程和一般的筆記軟體差在哪？
- 自動標註的重點準確嗎？
"""

PDF_TEXT = (
    "Paperfact: A Reading Workflow for Research Papers",
    "Demo Author",
    "Abstract. This document exists so that screenshots taken on every platform show "
    "the same page. It describes no real result.",
    "1 Introduction",
    "Reading a paper well means moving between an explanation and the original text. "
    "This page stands in for the original text.",
)


def seed() -> None:
    """Fill an empty data directory; config must already point at it."""
    import pymupdf as fitz

    from paper_daily import store
    from paper_daily.config import PDF_DIR, ensure_dirs

    ensure_dirs()
    store.init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id=PAPER_ID,
                    title=PDF_TEXT[0],
                    venue="Demo",
                    year=2026,
                    source="demo",
                    abstract=PDF_TEXT[2],
                )
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO lists (id, name, note, created_at) VALUES (?, ?, ?, ?)",
            (LIST_ID, "示範清單", None, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO list_papers (list_id, paper_id, position, state, added_at)"
            " VALUES (?, ?, 0, 'pending', ?)",
            (LIST_ID, PAPER_ID, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO dives (paper_id, body, written_at) VALUES (?, ?, ?)",
            (PAPER_ID, DIVE, now),
        )
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for i, line in enumerate(PDF_TEXT):
        size = 16 if i == 0 else 11
        page.insert_textbox(fitz.Rect(72, y, 540, y + 80), line, fontsize=size)
        y += 40 if i < 2 else 70
    doc.save(str(PDF_DIR / "demo_paperfact.pdf"))


CORPUS_ID = "3390faaf-42c5-4953-8391-024cf4fe7dce"
PRIOR_ID = "demo:prior"
LATER_ID = "demo:later"
PRIOR = "Synthetic prior work evaluated one local collection."
CITING = "The synthetic prior study did not test an independent collection."
CHANGE = "This synthetic study adds a second independent collection."
LATER = "Following the synthetic focal study, this follow-up evaluates three collections."
OWN_LATER = "This synthetic follow-up examines transfer across collections."


def acceptance_package(destination):
    """Create synthetic three-original reading material in an explicit empty workspace.

    This fixture creates portable data, not sender-native ownership receipts.
    Production validation and observed receiver publication remain mandatory.
    No provider hooks, credentials, downloads or research directory defaults.
    """
    import hashlib
    import io
    import json
    import os
    import zipfile
    from pathlib import Path

    import pymupdf

    from paper_daily import bundle, config, lineage_packages, lineage_sets, research_lineage, store
    from paper_daily.research_lifecycle import ensure_lifecycle

    selected = os.environ.get("PAPERFACT_DATA")
    if not selected or not Path(selected).is_absolute():
        raise ValueError("Set PAPERFACT_DATA to an explicit empty absolute fixture directory")
    root = Path(selected).resolve()
    destination = Path(destination)
    if root != config.DATA_DIR.resolve() or root.exists() and any(root.iterdir()):
        raise ValueError("Acceptance fixture requires the bound empty workspace")
    if not destination.is_absolute() or destination.exists():
        raise ValueError("Choose a new absolute output package path")
    seed()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id=PRIOR_ID,
                    title="Synthetic Prior Study",
                    venue="Fixture",
                    year=2024,
                    source="synthetic",
                ),
                dict(
                    id=LATER_ID,
                    title="Synthetic Follow-up Study",
                    venue="Fixture",
                    year=2027,
                    source="synthetic",
                ),
            ],
        )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
        papers = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM papers")}

    for paper_id, lines in (
        (PAPER_ID, [CITING, CHANGE]),
        (PRIOR_ID, [PRIOR]),
        (LATER_ID, [LATER, OWN_LATER]),
    ):
        path = config.PDF_DIR / (paper_id.replace(":", "_") + ".pdf")
        existing = path.exists()
        with pymupdf.open(path) if existing else pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_textbox(
                pymupdf.Rect(72, 72, 540, 700),
                "Synthetic acceptance material; no real research results.\n\n" + "\n\n".join(lines),
                fontsize=11,
            )
            if existing:
                pdf.saveIncr()
            else:
                pdf.save(path)

    captured = research_lineage.capture(
        store.DB_PATH,
        PAPER_ID,
        [PRIOR_ID, LATER_ID],
        legacy_root=config.PDF_DIR,
    )
    focal, prior, later = [source["id"] for source in captured.sources]

    def passage(source, role, quote, page=1, cites=None):
        return dict(source_id=source, role=role, cites=cites, quote=quote, page=page, anchor=None)

    def statement(stage, subject, text, passages):
        return dict(
            stage=stage,
            subject=subject,
            text=text,
            function="extends",
            passages=passages,
            judgment=dict(status="inferred", reason="Synthetic authored fixture, not AI."),
        )

    proposals = dict(
        format=research_lineage.PROPOSALS,
        focal=focal,
        statements=[
            statement(
                "prior_gap",
                prior,
                "Synthetic prior scope was one collection.",
                [
                    passage(prior, "own_characterization", PRIOR),
                    passage(focal, "citing_context", CITING, page=2, cites=prior),
                ],
            ),
            statement(
                "current_change",
                focal,
                "Synthetic focal scope adds an independent collection.",
                [
                    passage(focal, "change_evidence", CHANGE, page=2),
                ],
            ),
            statement(
                "later_development",
                later,
                "Synthetic follow-up examines transfer.",
                [
                    passage(later, "own_characterization", OWN_LATER),
                    passage(later, "citing_context", LATER, cites=focal),
                ],
            ),
        ],
    )
    report = research_lineage.verify_snapshot(captured, proposals)
    body = dict(
        format=lineage_sets.FORMAT,
        corpus_id=CORPUS_ID,
        inputs=dict(dive=None, close_reading=None),
        generation=dict(
            task="lineage", backend="synthetic-fixture", requested_model=None, returned_model=None
        ),
        report=report,
        bindings=[
            dict(source_id=source["id"], paper_id=pid)
            for source, pid in zip(captured.sources, (PAPER_ID, PRIOR_ID, LATER_ID), strict=True)
        ],
    )
    row = dict(
        paper_id=PAPER_ID,
        corpus_key=CORPUS_ID,
        body_json=lineage_sets.canonical(body),
        source_hash=lineage_sets.source_hash(body),
        document_hash=captured.sources[0]["document_hash"],
        written_at="2026-11-15T00:00:00+00:00",
    )
    lineage_sets.validate_row(row)
    baseline = root / "baseline.zip"
    bundle.export(LIST_ID, baseline)
    with zipfile.ZipFile(baseline) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        files = {
            name.removeprefix("files/"): archive.read(name)
            for name in archive.namelist()
            if name.startswith("files/")
        }
    tables["cited_papers"] = [papers[PRIOR_ID], papers[LATER_ID]]
    tables[lineage_sets.TABLE] = [row]
    records = []
    for binding, source, document in zip(
        body["bindings"], captured.sources, captured._documents, strict=True
    ):
        digest, pid = source["document_hash"], binding["paper_id"]
        relative = lineage_packages.relative(PAPER_ID, pid, digest).as_posix()
        data = document.path.read_bytes()
        files[relative] = data
        records.append(
            dict(
                focal_paper_id=PAPER_ID,
                corpus_key=CORPUS_ID,
                source_id=source["id"],
                paper_id=pid,
                sha256=digest,
                size=len(data),
                path=relative,
            )
        )
    manifest.update(
        format=2,
        capabilities=sorted(set(manifest.get("capabilities", [])) | {"lineage"}),
        lineage_sources=records,
        file_hashes={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        counts={table: len(rows) for table, rows in tables.items()} | {"files": len(files)},
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("tables.json", json.dumps(tables, ensure_ascii=False))
        for name, data in files.items():
            archive.writestr("files/" + name, data)
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        bundle._validated(archive)
    with destination.open("xb") as stream:
        stream.write(output.getvalue())
        stream.flush()
        os.fsync(stream.fileno())
    return manifest
