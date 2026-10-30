"""Explicit workspace workflow: publish highlights, then link current explanations.

Saved canonical content is reusable offline without consulting AI accounts. The
two phases report partial completion honestly and never follow a global DB path.
"""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from paper_daily import annotation_content, llm, reading_links, research_job_lock
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.highlight_jobs import HighlightJob
from paper_daily.reading_link_jobs import ReadingLinksJob


def _analysis(row):
    annotation_content.validate_row("highlight_analysis", row)
    return {
        **annotation_content.decode("highlight_analysis", row["body_json"]),
        "paper_id": row["paper_id"],
        "source_hash": row["source_hash"],
        "document_hash": row["document_hash"],
        "known": True,
    }


def _row_identity(row):
    if row is None:
        return None
    annotation_content.validate_row("highlight_analysis", row)
    return {**row, "body_json": annotation_content.decode("highlight_analysis", row["body_json"])}


def _same_owner(first, second):
    return all(
        first.data[name] == second.data[name]
        for name in ("db_path", "database_identity", "binding", "owner_id", "parent_lifecycle")
    )


def prepare(database, paper_id, *, legacy_root, force=False, connections=None,
            owner=None, expected_document_hash=None, cancelled=lambda: False):
    """Run explicitly requested work; return saved highlights even if linking fails."""
    database = Path(database).resolve(strict=True)
    if cancelled():
        return None, "Preparation stopped before analysis"
    if owner is not None and (owner.database != database or owner.paper_id != paper_id):
        raise ValueError("The loaded annotation owner belongs to another research target")
    with research_job_lock.claim(database, "prepare-reading", paper_id) as own:
        if not own:
            return None, "Research annotation preparation is already running for this paper"
        with closing(generation._connect(database)) as conn:
            if owner is not None:
                owner.check(conn)
            original = generation.begin_generation(
                conn,
                table="paper_highlight_analysis",
                owner_id=paper_id,
            )
        row = original.target
        # A cached row is evidence for its original PDF, never for a new caller's
        # displayed source. Verify the explicit source before every cache return.
        if expected_document_hash is not None:
            source = from_workspace(database, legacy_root=legacy_root).resolve(paper_id)
            if not source.available or source.sha256 != expected_document_hash:
                raise ValueError("The displayed PDF changed before highlight analysis")
            if row is not None and row["document_hash"] != source.sha256:
                force = True
        if row is None and original.inputs["known"] and not force:
            return {
                "analysis": {"items": [], "known": True},
                "marks": None,
                "explanation": None,
                "explanation_pending": False,
            }, "Saved highlights were deleted"
        if row is None or force:
            if cancelled():
                return None, "Preparation stopped before analysis"
            from paper_daily.work_progress import report

            report("Reading the original PDF and locating selected evidence", paper_id=paper_id)
            if connections is None:
                connections = llm.capture_connections()
            job = HighlightJob(original, connections, Path(legacy_root).resolve())
            publication = job.run()
            if publication.status != "accepted":
                return None, publication.reason + "; completed highlights retained for review"
            row = job.result
            mark_rows = job.context.data["highlight_plan"]["marks"]
        else:
            mark_rows = original.inputs["marks"]
        analysis = _analysis(row)
        selected = {
            hashlib.sha256(f"{item['page']}:{item['text']}".encode()).hexdigest(): item
            for item in analysis["items"]
        }
        mapped = {
            mark["source_key"]
            for mark in mark_rows
            if mark["document_hash"] == row["document_hash"]
            and mark["analysis_hash"] == row["source_hash"]
            and mark["source_key"] in selected
            and mark["quote"] == selected[mark["source_key"]]["text"]
        }
        result = {
            "analysis": analysis,
            "marks": {
                "mapped": len(mapped),
                "total": len(selected),
                "unmatched": [item for key, item in selected.items() if key not in mapped],
                "document_hash": row["document_hash"],
            },
            "explanation": None,
            "explanation_pending": False,
        }
        def stopped():
            result.update(explanation_reason="Highlight phase saved; explanation linking stopped",
                          explanation_pending=True, cancelled=True)
            return result, "Highlights saved; explanation linking stopped"

        if cancelled():
            return stopped()
        try:
            link_job = ReadingLinksJob.capture(
                database,
                paper_id,
                legacy_root=legacy_root,
                connections=connections if connections is not None else {},
            )
            if not _same_owner(original, link_job.context):
                raise ValueError("The original research workspace or paper changed")
            inputs = link_job.context.inputs
            if _row_identity(inputs["paper_highlight_analysis"]) != _row_identity(row):
                raise ValueError("Highlights changed before explanation linking")
            parts = reading_links.sections(
                (inputs["dives"] or {}).get("body"),
                (inputs["close_readings"] or {}).get("body"),
            )
            if not parts:
                result["explanation_reason"] = (
                    "Complete the explanation before linking its evidence"
                )
                return result, "ok"
            result["explanation_pending"] = True
            saved = link_job.context.target
            if saved:
                annotation_content.validate_row("reading_links", saved)
                body = annotation_content.decode("reading_links", saved["body_json"])
                if (
                    saved["source_hash"] == reading_links._key(parts, analysis)
                    and saved["document_hash"] == row["document_hash"]
                    and body["analysis_hash"] == row["source_hash"]
                ):
                    result.update(
                        explanation={**body, "key": saved["source_hash"]}, explanation_pending=False
                    )
                    return result, "cached"
            document = from_workspace(database, legacy_root=legacy_root).resolve(paper_id)
            if not document.available or document.sha256 != row["document_hash"]:
                raise ValueError("The exact highlight source PDF is unavailable for linking")
            if cancelled():
                return stopped()
            from paper_daily.work_progress import report

            report("Highlights saved; linking evidence to the explanation", paper_id=paper_id)
            if connections is None:
                connections = llm.capture_connections()
            link_job.connections = connections
            publication = link_job.run()
            if publication.status != "accepted":
                raise ValueError(publication.reason + "; completed links retained for review")
            body = annotation_content.decode("reading_links", link_job.result["body_json"])
            result.update(
                explanation={**body, "key": link_job.result["source_hash"]},
                explanation_pending=False,
            )
            return result, "ok"
        except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as exc:
            result.update(explanation_reason=str(exc), explanation_pending=True)
            return result, "Highlights saved; explanation linking remains incomplete"
