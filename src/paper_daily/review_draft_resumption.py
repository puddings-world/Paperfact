"""Closed dispatch between independently observed text and note draft domains."""

ORIGINS = {"archived_resume", "archived_note_resume", "claim_resume", "highlight_resume"}


def adapter(origin):
    if origin == "archived_resume":
        from paper_daily import archived_draft_resume

        return archived_draft_resume
    if origin == "archived_note_resume":
        from paper_daily import archived_note_resume

        return archived_note_resume
    if origin == "claim_resume":
        from paper_daily import claim_draft_resume

        return claim_draft_resume
    if origin == "highlight_resume":
        from paper_daily import highlight_draft_resume

        return highlight_draft_resume
    raise ValueError("Select a typed resumed draft")


def archived(record):
    from paper_daily import enrollment_history as history

    value, _sources = history.validate(record)
    if record["protocol"] != "research_review_drafts":
        raise ValueError("Select a historical saved draft")
    if value["origin"] == "archived_note_resume":
        return adapter("archived_note_resume")
    if value["origin"] == "remote":
        snapshot = history._value(value["preview_json"])
        if snapshot["scope"]["kind"] == "note":
            return adapter("archived_note_resume")
    return adapter("archived_resume")


def source_intent(data):
    current = data["expected"]
    if data["origin"] == "archived_resume":
        from paper_daily.research_generation import GenerationContext

        current = GenerationContext(current)
    return adapter(data["origin"]).source_intent(current)
