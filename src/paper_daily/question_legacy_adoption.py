"""Explicitly attach a bounded historical question preview to verified current inputs.

Preparation never calls AI and does not adopt data. Acceptance uses the exact
captured workspace, source and target; it does not assert historical ownership.
"""

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from paper_daily import annotation_reader, research_questions
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.research_question_jobs import _pages


@dataclass(frozen=True)
class LegacyQuestions:
    context: generation.GenerationContext
    _row_json: str

    @property
    def row(self):
        return json.loads(self._row_json)

    @property
    def items(self):
        return json.loads(self.row["body_json"])["items"]

    def adopt(self):
        """Call only after the user chooses to adopt the displayed preview."""
        return generation.publish_generated(self.context, row=self.row)


def prepare(database, paper_id, *, cache_root, legacy_root):
    database = Path(database).resolve(strict=True)
    old = annotation_reader.questions(database, paper_id, cache_root=cache_root)
    if old.get("known") or not old.get("legacy_unverified"):
        raise ValueError("No unadopted legacy questions are available")
    with closing(generation._connect(database)) as conn:
        context = generation.begin_generation(
            conn, table="paper_research_questions", owner_id=paper_id
        )
    if context.target is not None or context.inputs["question_known"]:
        raise ValueError("Canonical questions or a deletion already exist")
    inputs = context.inputs
    if not inputs["dives"] or not inputs["close_readings"]:
        raise ValueError("The original analysis inputs are unavailable")
    document = from_workspace(database, legacy_root=legacy_root).resolve(paper_id)
    if not document.available:
        raise ValueError("A verified original PDF is required for adoption")
    context = generation.bind_inputs(context, document=document)
    pages = _pages(document)
    source = {
        "pages": pages,
        "explanation": inputs["dives"]["body"],
        "close_reading": inputs["close_readings"]["body"],
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True)
    if len(encoded) > 240000:
        raise ValueError("Legacy question inputs exceed the supported budget")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    if digest != old["source_hash"]:
        raise ValueError("Legacy questions do not match the current PDF and analyses")
    items = research_questions.validate(old["items"], pages)
    if items != old["items"]:
        raise ValueError("Legacy question page or source text could not be confirmed exactly")
    row = {
        "paper_id": paper_id,
        "body_json": json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":")),
        "source_hash": digest,
        "document_hash": document.sha256,
        "written_at": context.started_at,
    }
    return LegacyQuestions(context, json.dumps(row, ensure_ascii=False, sort_keys=True))
