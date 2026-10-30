"""Publish explanation links against the exact observed analyses and verified PDF."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import annotation_content, llm, reading_links, research_job_lock
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace


@dataclass
class ReadingLinksJob:
    context: generation.GenerationContext
    connections: object = field(repr=False)
    legacy_root: Path
    result: dict | None = None
    publication: generation.Publication | None = None

    @classmethod
    def capture(cls, database, paper_id, *, legacy_root, connections=None):
        if connections is None:
            connections = llm.capture_connections()
        with closing(generation._connect(Path(database).resolve(strict=True))) as conn:
            context = generation.begin_generation(
                conn, table="paper_reading_links", owner_id=paper_id
            )
        return cls(context, connections, Path(legacy_root).resolve())

    def run(self):
        if self.publication is not None:
            return self.publication
        with research_job_lock.claim(
            self.context.db_path, "reading-links", self.context.owner_id
        ) as acquired:
            if not acquired:
                raise ValueError("Explanation linking is already running for this paper")
            if self.result is not None:
                self.publication = generation.publish_generated(self.context, row=self.result)
                return self.publication
            inputs = self.context.inputs
            row = inputs["paper_highlight_analysis"]
            if row is None:
                raise ValueError("Verified highlight analysis is required before linking")
            annotation_content.validate_row("highlight_analysis", row)
            if row["document_hash"] is None:
                raise ValueError("Highlight source PDF version has not been verified")
            analysis = {
                **annotation_content.decode("highlight_analysis", row["body_json"]),
                "source_hash": row["source_hash"],
            }
            parts = reading_links.sections(
                (inputs["dives"] or {}).get("body"), (inputs["close_readings"] or {}).get("body")
            )
            if not parts or not analysis["items"]:
                raise ValueError("Explanation sections and verified highlight quotes are required")
            if len(json.dumps([parts, analysis], ensure_ascii=False)) > 240000:
                raise ValueError("Explanation link inputs exceed the supported budget")
            with closing(generation._connect(self.context.db_path)) as conn:
                if generation._stale(conn, self.context):
                    raise ValueError("Explanation inputs changed before linking")
            document = from_workspace(self.context.db_path, legacy_root=self.legacy_root).resolve(
                self.context.owner_id
            )
            if not document.available or document.sha256 != row["document_hash"]:
                raise ValueError("The highlight analysis belongs to another or unavailable PDF")
            self.context = generation.bind_inputs(self.context, document=document)
            with llm.connection_scope(self.connections):
                response, reason = reading_links.produce(parts, analysis)
            if response is None:
                raise ValueError(reason or "Explanation linking failed")
            body = annotation_content.validate(
                "reading_links", {"links": response["links"], "analysis_hash": row["source_hash"]}
            )
            self.result = {
                "paper_id": self.context.owner_id,
                "body_json": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                "source_hash": response["key"],
                "document_hash": document.sha256,
                "written_at": self.context.started_at,
            }
            self.publication = generation.publish_generated(self.context, row=self.result)
            return self.publication
