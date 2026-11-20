"""A question about a paper, answered by an agent host with its own account.

The same request, prompt and publication the reader's own 論文問答 uses: the question
is stored before anything is answered, and the answer passes the same checks. Only
the model call happens elsewhere. Paperfact makes none here.
"""

from __future__ import annotations

from contextlib import closing
from uuid import uuid4

from paper_daily import answer_content, research_chat, store
from paper_daily import research_generation as generation
from paper_daily.research_job_lock import claim

INSTRUCTIONS = (
    "Answer the reader's question at the end of material, following the rules at its "
    "top. Put only the answer for the reader between <answer> and </answer>."
)
BUSY = "This paper's question answering is running in Paperfact; try again shortly"


def _open(database, request_id):
    request = research_chat.load_request(database, request_id)
    if research_chat.answer_record(request) is not None:
        raise ValueError("This question already has an answer")
    return request


def task(paper_id=None, question=None, *, request_id=None, database=None) -> dict:
    """Store a new question, or reopen an unanswered one, and return what answers it."""
    from paper_daily.config import PDF_DIR

    database = (database or store.DB_PATH).resolve()
    if request_id is not None:
        request = _open(database, request_id)
    else:
        with closing(generation._connect(database)) as conn:
            request = research_chat.begin_chat(
                conn,
                paper_id=paper_id,
                question=question,
                request_id=str(uuid4()),
                legacy_root=PDF_DIR,
            )
    data = request.data
    with claim(database, "ask", data["paper_id"]) as accepted:
        if not accepted:
            raise ValueError(BUSY)
        request, prompt = research_chat.prepare_chat(request)
    return {
        "request_id": request.request_id,
        "paper_id": data["paper_id"],
        "title": data["parent"]["row"]["title"],
        "question": data["question"],
        "instructions": INSTRUCTIONS,
        "material": prompt,
        "full_text": request.document is not None,
    }


def save(request_id, answer, *, database=None) -> dict:
    """Publish the host's answer to task() as the reply to that question."""
    database = (database or store.DB_PATH).resolve()
    body = answer_content.tagged_answer(answer) if isinstance(answer, str) else None
    if not body:
        raise ValueError("The answer is empty")
    request = _open(database, request_id)
    with claim(database, "ask", request.data["paper_id"]) as accepted:
        if not accepted:
            raise ValueError(BUSY)
        result = research_chat.publish_answer(request, body)
    return {"status": result.status, "reason": result.reason, "chars": len(body)}
