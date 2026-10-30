"""Observed question generation; original PDF, analyses and account stay pinned.

This operation has no implicit workspace lookup or legacy-cache migration. Its
caller supplies the workspace; accepted SQL data is the portable authority.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import annotation_content, llm, research_job_lock, research_questions
from paper_daily import research_generation as generation
from paper_daily.document_reader import document_current, from_workspace


@dataclass
class QuestionJob:
    context: generation.GenerationContext
    connections: object = field(repr=False)
    legacy_root: Path
    result: dict | None = None
    publication: generation.Publication | None = None

    @classmethod
    def capture(cls, database, paper_id, *, legacy_root, connections=None):
        # Before PDF preparation or model work, pin the actual account and SQL base.
        if connections is None:
            connections = llm.capture_connections()
        with closing(generation._connect(Path(database).resolve(strict=True))) as conn:
            context = generation.begin_generation(
                conn, table="paper_research_questions", owner_id=paper_id
            )
        return cls(context, connections, Path(legacy_root).resolve())

    def run(self):
        if self.publication is not None:
            return self.publication
        with research_job_lock.claim(
            self.context.db_path, "research-questions", self.context.owner_id
        ) as acquired:
            if not acquired:
                raise ValueError("Question generation is already running for this paper")
            # A completed result is delivered again without resolving today's route.
            if self.result is not None:
                self.publication = generation.publish_generated(self.context, row=self.result)
                return self.publication
            inputs = self.context.inputs
            if not inputs["dives"] or not inputs["close_readings"]:
                raise ValueError("Complete the deep explanation and close reading first")
            # Do not pay for a new result after a captured target has already changed.
            with closing(generation._connect(self.context.db_path)) as conn:
                if generation._stale(conn, self.context):
                    raise ValueError("Research inputs changed before question generation")
            document = from_workspace(self.context.db_path, legacy_root=self.legacy_root).resolve(
                self.context.owner_id
            )
            if not document.available:
                raise ValueError("The original verified PDF is not available")
            self.context = generation.bind_inputs(self.context, document=document)
            pages = _pages(document)
            source = {
                "pages": pages,
                "explanation": inputs["dives"]["body"],
                "close_reading": inputs["close_readings"]["body"],
            }
            encoded = json.dumps(source, ensure_ascii=False, sort_keys=True)
            if len(encoded) > 240000:
                raise ValueError("Question input exceeds the supported budget")
            source_hash = hashlib.sha256(encoded.encode()).hexdigest()
            with llm.connection_scope(self.connections):
                response = research_questions.produce(source)
            if not response["items"]:
                raise ValueError(response.get("reason") or "Question generation failed")
            body = annotation_content.validate("research_questions", {"items": response["items"]})
            self.result = {
                "paper_id": self.context.owner_id,
                "body_json": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                "source_hash": source_hash,
                "document_hash": document.sha256,
                "written_at": self.context.started_at,
            }
            self.publication = generation.publish_generated(self.context, row=self.result)
            return self.publication


def _pages(document):
    """Read only the pinned PDF, then verify the exact source again before AI."""
    import pymupdf

    from paper_daily.paper_highlights import normalize

    pages = []
    size = 0
    with pymupdf.open(document.path) as pdf:
        if len(pdf) > 20000:
            raise ValueError("Question source exceeds the supported page count")
        for index, page in enumerate(pdf):
            text = normalize(page.get_text())
            size += len(text)
            if size > 240000:
                raise ValueError("Question source exceeds the supported budget")
            pages.append({"page": index + 1, "text": text})
    if not any(page["text"] for page in pages):
        raise ValueError("The PDF has no readable text")
    if not document_current(document):
        raise ValueError("Original PDF changed during question preparation")
    with document.path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != document.sha256:
            raise ValueError("Original PDF changed during question preparation")
    return pages


def ensure(database, paper_id, *, force=False, connections=None):
    """Application operation: saved peer content is read without regeneration."""
    from paper_daily import annotation_reader

    database = Path(database).resolve(strict=True)
    saved = annotation_reader.questions(
        database, paper_id, cache_root=database.parent / "research-questions"
    )
    if not force and (saved.get("items") or saved["known"]):
        return saved, (
            "舊版建議尚未核對來源；可核對後採用，或更新建議。"
            if saved.get("legacy_unverified")
            else "已載入工作區保存的本文建議。"
        )
    job = QuestionJob.capture(
        database, paper_id, legacy_root=database.parent / "pdf", connections=connections
    )
    publication = job.run()
    if publication.status != "accepted":
        return None, "原文或研究內容已變動；完成的建議已保留，請至保留內容審閱。"
    return annotation_reader.questions(
        database, paper_id, cache_root=database.parent / "research-questions"
    ), "本文建議已儲存於工作區。"
