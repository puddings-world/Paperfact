"""Tools for the /paper-guide round: build a paper's 論文導讀 deck by hand-checked steps.

The app's own generator writes a deck in one model call. A guide that someone will
present to people who have not read the paper deserves more: the front matter read
against the original, the citation context (what the paper stands on, what is still
open after it) laid out on purpose, a review pass for gaps, and every point checked
against the original before it reaches a slide. That work is done by Claude
sessions following docs/guide-decks.md; this script is the part that touches the
app's data, so the edits go through the same validation as the 簡報 canvas.

    python scripts/guide_deck.py export <paper_id>             # write the work folder
    python scripts/guide_deck.py apply-guide <paper_id> [--dry-run]
    python scripts/guide_deck.py apply-review <paper_id> [--dry-run]
    python scripts/guide_deck.py apply-review <paper_id> --plan detail_plan.json

The work folder is data/guide-work/<paper>/ (gitignored, like all of data/).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper_daily import closeread, followups, presentations  # noqa: E402
from paper_daily.config import DATA_DIR, PDF_DIR  # noqa: E402
from paper_daily.fetch import _safe_name  # noqa: E402
from paper_daily.store import connect, now  # noqa: E402

WORK = DATA_DIR / "guide-work"


def folder(paper_id: str) -> Path:
    return WORK / _safe_name(paper_id)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def export(paper_id: str) -> Path:
    """Everything a session needs to read, as plain files it can open in parts."""
    import pymupdf

    out = folder(paper_id)
    pdf = PDF_DIR / (_safe_name(paper_id) + ".pdf")
    if not pdf.exists():
        raise SystemExit(f"no PDF for {paper_id}: the guide is built from the original")
    with pymupdf.open(pdf) as doc:
        pages = "".join(f"\n\n===== PAGE {i} =====\n{pg.get_text()}" for i, pg in enumerate(doc, 1))
    _write(out / "original.txt", pages)

    with connect() as conn:
        paper = conn.execute(
            "SELECT title, venue, year FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
        dive = conn.execute("SELECT body FROM dives WHERE paper_id=?", (paper_id,)).fetchone()
        close = closeread.get(conn, paper_id)
        refs = followups.references(conn, paper_id)
        later = followups.for_paper(conn, paper_id)
        story = followups.overview_for(conn, paper_id)
        chat = conn.execute(
            "SELECT role, body FROM chat WHERE paper_id=? ORDER BY id", (paper_id,)
        ).fetchall()

    # The citation context gets its own file: it is what the 承先 and 啟後 parts of
    # the deck are built from, and buried in the analysis it was under-used.
    lines = [f"# 承先啟後：{paper['title']} ({paper['venue']} {paper['year']})\n"]
    if story:
        lines.append("\n## 研究脈絡（AI 分析）\n" + story["summary"] + "\n")
        for x in story["reading"]:
            lines.append(f"- 必讀[{x.get('direction')}] {x['title']}：{x.get('why', '')}\n")
    lines.append("\n## 承先：參考文獻（依判定排序）\n")
    for r in refs:
        ctx = (r.get("contexts") or [""])[0]
        lines.append(
            f"- [{r.get('ref_key') or '-'}] {r.get('title')} ({r.get('year') or '?'}) "
            f"判定={r.get('verdict') or '-'} 依據={r.get('basis')}\n"
            f"  用途：{r.get('purpose') or ''}\n  判斷：{r.get('why') or ''}\n"
            + (f"  引用句：「{ctx[:300]}」\n" if ctx else "")
        )
    lines.append("\n## 啟後：引用這篇的後續研究\n")
    for r in later:
        ctx = (r.get("contexts") or [""])[0]
        lines.append(
            f"- {r['title']} ({r.get('year') or '?'}, {r.get('venue') or '?'}, "
            f"{r.get('citations') or 0} cites) 判定={r.get('verdict') or '-'}\n"
            f"  拿它做了什麼：{r.get('relation') or ''}\n  判斷：{r.get('why') or ''}\n"
            + (f"  引用句：「{ctx[:300]}」\n" if ctx else "")
        )
    _write(out / "citations.md", "".join(lines))

    _write(
        out / "analysis.md",
        "## 深度講解\n"
        + (dive["body"] if dive else "（沒有）")
        + "\n\n## 逐節精讀\n"
        + (close or "（沒有）")
        + "\n\n## 現有問答\n"
        + "".join(f"[{r['role']}] {r['body'][:600]}\n" for r in chat),
    )

    decks = {}
    sources = None
    for mode in presentations.MODES:
        deck = presentations.load_deck(paper_id, mode)
        if deck is None:
            continue
        decks[mode] = [
            {
                "slide": i,
                "title": s.title,
                "section": s.section,
                "takeaway": s.takeaway,
                "bullets": s.bullets,
                "speaker_notes": s.speaker_notes,
                "sources": s.sources,
                "figure": s.figure,
            }
            for i, s in enumerate(deck.slides, 1)
        ]
        if mode == "guide":
            sources = deck
    if sources is None:
        # The guide is replaced, not created: its source and figure list is built by
        # the app's evidence collection, which is what keeps every ID resolvable.
        raise SystemExit(
            "no 論文導讀 deck yet: generate one in the 簡報 tab first (any length), "
            "then export again"
        )
    _write(out / "decks.json", json.dumps(decks, ensure_ascii=False, indent=1))

    # Sentences the 簡報 tab's 素材 panel picked from the original and checked
    # word for word. Read from its cache file rather than its module, so this
    # works whether or not that feature is installed.
    cache = (
        DATA_DIR / "paper-highlights" / (hashlib.sha256(paper_id.encode()).hexdigest() + ".json")
    )
    if cache.exists():
        items = json.loads(cache.read_text(encoding="utf-8")).get("items") or []
        _write(out / "highlights.json", json.dumps(items, ensure_ascii=False, indent=1))
    _write(
        out / "sources.json",
        json.dumps(
            {
                "sources": [
                    {k: s.get(k) for k in ("id", "label", "kind", "page")} for s in sources.sources
                ],
                "figures": [
                    {
                        "id": f["id"],
                        "label": f.get("label"),
                        "page": f.get("page"),
                        "caption": (f.get("caption") or "")[:200],
                    }
                    for f in sources.figures
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
    )
    return out


def _archive(paper_id: str, mode: str, deck, tag: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d%H%M")
    presentations._atomic_json(
        presentations._folder(paper_id) / "history" / f"{mode}-{tag}-{stamp}.json",
        copy.deepcopy(deck.to_dict()),
    )


def apply_guide(paper_id: str, dry: bool) -> int:
    raw = json.loads((folder(paper_id) / "guide_deck.json").read_text(encoding="utf-8"))
    deck = presentations.load_deck(paper_id, "guide")
    source_ids = {s["id"] for s in deck.sources}
    figure_ids = {f["id"] for f in deck.figures}
    slides, problems = [], []
    for i, s in enumerate(raw["slides"], 1):
        try:
            slides.append(presentations.validate_slide(s, source_ids, figure_ids))
        except (ValueError, TypeError) as exc:
            problems.append(f"slide {i}: {exc}")
    if not 4 <= len(slides) <= presentations.MAX_SLIDES:
        problems.append(f"{len(raw['slides'])} slides")
    print(json.dumps({"slides": len(raw["slides"]), "problems": problems}, ensure_ascii=False))
    if problems or dry:
        return 1 if problems else 0
    _archive(paper_id, "guide", deck, "preguide")
    deck.title = presentations._text(raw["title"], "deck title", 200)
    deck.slides = slides
    deck.created_at = now()
    deck.deck_id = uuid4().hex
    deck.edited = True
    deck.generation = {**deck.generation, "rebuilt": "guide round (docs/guide-decks.md)"}
    presentations.save_deck(deck)
    return 0


def apply_review(paper_id: str, dry: bool, plan_name: str = "review_plan.json") -> int:
    plan = json.loads((folder(paper_id) / plan_name).read_text(encoding="utf-8"))
    report = {"applied": [], "rejected": [], "inserted": [], "notes": 0, "qa": 0}
    for mode in presentations.MODES:
        deck = presentations.load_deck(paper_id, mode)
        if deck is None:
            continue
        before = copy.deepcopy(deck)
        source_ids = {s["id"] for s in deck.sources}
        figure_ids = {f["id"] for f in deck.figures}
        changed = False
        for edit in [e for e in plan.get("slide_edits", []) if e["deck"] == mode]:
            i = edit["slide"] - 1
            s = deck.slides[i]
            raw = {
                "title": s.title,
                "section": s.section,
                "takeaway": s.takeaway,
                "bullets": s.bullets,
                "speaker_notes": s.speaker_notes,
                "sources": s.sources,
                "figure": s.figure,
            }
            raw[edit["field"]] = edit["new"]
            try:
                deck.slides[i] = presentations.validate_slide(raw, source_ids, figure_ids)
                changed = True
                report["applied"].append([mode, edit["slide"], edit["field"]])
            except (ValueError, TypeError) as exc:
                report["rejected"].append([mode, edit["slide"], edit["field"], str(exc)])
        # New slides go in after the edits, from the back, so every number in the
        # plan refers to the deck as it was read.
        inserts = [x for x in plan.get("insert_slides", []) if x["deck"] == mode]
        for ins in sorted(inserts, key=lambda x: x["after"], reverse=True):
            if len(deck.slides) >= presentations.MAX_SLIDES:
                report["rejected"].append([mode, ins["after"], "insert", "deck is full"])
                continue
            try:
                new = presentations.validate_slide(ins["slide"], source_ids, figure_ids)
            except (ValueError, TypeError) as exc:
                report["rejected"].append([mode, ins["after"], "insert", str(exc)])
                continue
            deck.slides.insert(ins["after"], new)
            changed = True
            report["inserted"].append([mode, ins["after"], new.title])
        shift = sorted(x[1] for x in report["inserted"] if x[0] == mode)
        for add in [a for a in plan.get("speaker_notes", []) if a["deck"] == mode]:
            # A note planned for slide N moves with it past slides inserted before it.
            at = add["slide"] + sum(1 for after in shift if after < add["slide"])
            s = deck.slides[at - 1]
            notes = (s.speaker_notes.rstrip() + "\n\n" + add["append"].strip()).strip()
            if len(notes) > 6000:
                report["rejected"].append([mode, add["slide"], "speaker_notes", "over 6000"])
                continue
            s.speaker_notes = notes
            changed = True
            report["notes"] += 1
        if changed and not dry:
            _archive(paper_id, mode, before, "prereview")
            deck.edited = True
            presentations.save_deck(deck)
    if not dry:
        with connect() as conn:
            for qa in plan.get("qa", []):
                for role, body in (("user", qa["question"]), ("assistant", qa["answer"])):
                    conn.execute(
                        "INSERT INTO chat(paper_id, role, body, created_at) VALUES (?,?,?,?)",
                        (paper_id, role, body.strip(), now()),
                    )
            conn.commit()
    report["qa"] = len(plan.get("qa", []))
    verdicts: dict[str, list] = {}
    for item in plan.get("items", []):
        verdicts.setdefault(item["verdict"], []).append(item["n"])
    print(json.dumps({"verdicts": verdicts, **report}, ensure_ascii=False, indent=1))
    return 1 if report["rejected"] else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("export", "apply-guide", "apply-review"):
        sp = sub.add_parser(name)
        sp.add_argument("paper_id")
        if name != "export":
            sp.add_argument("--dry-run", action="store_true")
        if name == "apply-review":
            sp.add_argument("--plan", default="review_plan.json")
    args = ap.parse_args()
    if args.cmd == "export":
        print(export(args.paper_id))
        return 0
    if args.cmd == "apply-guide":
        return apply_guide(args.paper_id, args.dry_run)
    return apply_review(args.paper_id, args.dry_run, args.plan)


if __name__ == "__main__":
    raise SystemExit(main())
