from contextlib import closing
from uuid import uuid4

import pytest
from test_document_reader import LOCAL, prepared
from test_sync_document_research import document, pdf_bytes
from test_sync_reading_state_research import save

from paper_daily import research_chat as chat
from paper_daily import research_generation


def request(path, document=None, **kwargs):
    with closing(research_generation._connect(path)) as conn:
        return chat.begin_chat(
            conn,
            paper_id=LOCAL,
            question="Explain this evidence",
            request_id=str(uuid4()),
            document=document,
            **kwargs,
        )


def test_actual_verified_pdf_text_is_used_not_legacy_alias_or_cache(tmp_path):
    path, journal, store, reader, alias, _ = prepared(tmp_path)
    exact = reader.resolve(LOCAL)
    alias.write_bytes(pdf_bytes("UNRELATED LEGACY ALIAS"))
    value, prompt = chat.prepare_chat(request(path, exact))
    assert "UNRELATED LEGACY ALIAS" not in prompt
    assert value.data["document"]["path"] == str(exact.path)
    assert chat.publish_answer(value, "Answer").status == "accepted"
    with closing(research_generation._connect(path)) as conn:
        rows = chat.history(conn, LOCAL)
    assert [row["source_hash"] for row in rows] == [exact.sha256] * 2
    exact.path.unlink()
    assert chat.publish_answer(value, "Answer").status == "accepted"


def test_managed_missing_never_reads_legacy_alias(tmp_path):
    path, journal, store, reader, alias, data = prepared(tmp_path)
    save(journal, document(pdf_bytes("Replacement"), op_id="new"))
    # An explicit missing managed source must not silently become abstract/alias input.
    with pytest.raises(ValueError):
        chat.prepare_chat(request(path))
    with closing(research_generation._connect(path)) as conn:
        assert chat.history(conn, LOCAL) == []
    assert alias.read_bytes() == data


def test_document_change_while_answering_retains_candidate(tmp_path):
    path, journal, store, reader, alias, data = prepared(tmp_path)
    value, _ = chat.prepare_chat(request(path, reader.resolve(LOCAL)))
    save(journal, document(pdf_bytes("Replacement"), op_id="new"))
    assert chat.publish_answer(value, "Old version answer").status == "candidate"
    with closing(research_generation._connect(path)) as conn:
        assert len(chat.history(conn, LOCAL)) == 1


def test_intentionally_open_old_pdf_keeps_its_hash_and_never_reads_new_alias(tmp_path):
    path, journal, store, reader, alias, data = prepared(tmp_path)
    old = reader.resolve(LOCAL)
    save(journal, document(pdf_bytes("Replacement"), op_id="new"))
    value, prompt = chat.prepare_chat(request(path, old))
    assert value.data["document"]["sha256"] == old.sha256
    assert value.data["desired"] != old.target
    assert chat.publish_answer(value, "Explicit old-version answer").status == "accepted"


def test_wrong_anchor_hash_and_out_of_range_page_fail_before_question(tmp_path):
    path, _, _, reader, _, _ = prepared(tmp_path)
    exact = reader.resolve(LOCAL)
    with pytest.raises(ValueError):
        chat.prepare_chat(
            request(
                path, exact, anchor={"p0": 0, "o0": 0, "p1": 0, "o1": 2, "document_hash": "0" * 64}
            )
        )
    with pytest.raises(ValueError):
        chat.prepare_chat(request(path, exact, page=999))
