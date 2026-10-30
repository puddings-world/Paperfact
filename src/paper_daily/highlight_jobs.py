"""Original-PDF selection and exact mark placement share one durable publication."""

from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import (
    annotation_content,
    highlight_publication,
    llm,
    paper_highlights,
    pdf_highlights,
    research_job_lock,
)
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.research_question_jobs import _pages


@dataclass
class HighlightJob:
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
                conn,
                table=highlight_publication.TABLE,
                owner_id=paper_id,
            )
        return cls(context, connections, Path(legacy_root).resolve())

    def run(self):
        if self.publication is not None:
            return self.publication
        with research_job_lock.claim(
            self.context.db_path, "highlights", self.context.owner_id
        ) as own:
            if not own:
                raise ValueError("Highlight analysis is already running for this paper")
            if self.result is not None:
                self.publication = generation.publish_generated(self.context, row=self.result)
                return self.publication
            with closing(generation._connect(self.context.db_path)) as conn:
                if generation._stale(conn, self.context):
                    raise ValueError("Highlight inputs changed before analysis")
            document = from_workspace(self.context.db_path, legacy_root=self.legacy_root).resolve(
                self.context.owner_id,
            )
            if not document.available:
                raise ValueError("The original verified PDF is not available")
            self.context = generation.bind_inputs(self.context, document=document)
            pages = _pages(document)
            with llm.connection_scope(self.connections):
                response, reason = paper_highlights.produce(pages)
            if response is None:
                raise ValueError(reason or "Highlight selection failed")
            body = annotation_content.validate(
                "highlight_analysis",
                {key: response[key] for key in ("items", "coverage")},
            )
            row = {
                "paper_id": self.context.owner_id,
                "body_json": generation._json(body),
                "source_hash": response["source_hash"],
                "document_hash": document.sha256,
                "written_at": self.context.started_at,
            }
            # Completion must survive a source change between AI and anchor lookup.
            # Retain every selected quote as explicitly unmatched in that case.
            located, unmatched = [], body["items"]
            if generation._document_current(self.context):
                try:
                    fingerprint, located, unmatched = pdf_highlights.locate(document.path, response)
                    if fingerprint != document.sha256:
                        located, unmatched = [], body["items"]
                except (OSError, ValueError, RuntimeError):
                    located, unmatched = [], body["items"]
            self.context = highlight_publication.seal(self.context, row, located, unmatched)
            self.result = row
            self.publication = generation.publish_generated(self.context, row=row)
            return self.publication

    @property
    def placement(self):
        plan = self.context.data.get("highlight_plan", {"marks": [], "unmatched": []})
        return {
            "mapped": len(plan["marks"]),
            "unmatched": len(plan["unmatched"]),
            "total": len(plan["marks"]) + len(plan["unmatched"]),
        }
