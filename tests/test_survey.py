"""A reading list read as one field: what goes in, what is kept, what a hand edit protects."""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import store, survey

DIVE = """## 一句話結論
第一個千支影片的白內障資料集。

## 前導導讀
### 研究當下的狀態
CaDIS [20] 只有 25 支影片。

## 核心洞見
規模與多任務。

## 證據
Table 6 的 phase F1。

## 限制與反駁
只有 56 支有 phase 標註。
"""


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    store._migrate(c)
    store.upsert_papers(
        c,
        [
            {
                "id": "a",
                "title": "Cataract-1K Dataset",
                "venue": "Sci Data",
                "year": 2024,
                "source": "test",
                "abstract": "A dataset.",
            },
            {
                "id": "b",
                "title": "CaDIS: Cataract dataset",
                "venue": "MedIA",
                "year": 2021,
                "source": "test",
                "abstract": "Segmentation data.",
            },
        ],
    )
    c.execute("INSERT INTO lists(id, name, created_at) VALUES ('cat', 'Cataract', 'now')")
    for pos, pid in enumerate(("a", "b")):
        c.execute(
            "INSERT INTO list_papers(list_id, paper_id, position, added_at) VALUES "
            "('cat', ?, ?, 'now')",
            (pid, pos),
        )
    c.execute("INSERT INTO dives(paper_id, body, written_at) VALUES ('a', ?, 'now')", (DIVE,))
    c.commit()
    monkeypatch.setattr(survey, "init_db", lambda: None)
    return c


def test_each_paper_brings_its_account_of_the_field(conn):
    text, count = survey.build_input(conn, "cat")
    assert count == 2
    # Oldest first, so the history reads in order.
    assert text.index("CaDIS") < text.index("Cataract-1K")
    assert "【前導導讀】### 研究當下的狀態" in text
    assert "【限制與反駁】只有 56 支" in text
    assert "摘要:Segmentation data." in text  # no dive: the abstract stands in


def test_a_paper_card_keeps_to_its_share(conn):
    row = conn.execute("SELECT * FROM papers WHERE id='a'").fetchone()
    card = survey.digest(row, DIVE * 40, None, 3, 900)
    assert len(card) <= 900
    assert "後續研究 3 篇" in card


def test_a_survey_is_stored_and_a_hand_edit_is_kept(conn, monkeypatch):
    calls = []

    def complete(prompt, system=None, timeout=0, task=""):
        calls.append(task)
        return "## 這個領域在解決什麼\n" + "白內障手術影片分析。" * 300, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    assert survey.write("cat") == (True, "ok")
    assert calls == ["survey"]
    stored = survey.get(conn, "cat")
    assert stored["papers"] == 2 and not stored["edited"]

    survey.edit("cat", "我改過的綜覽")
    written, reason = survey.write("cat")
    assert not written and "edited by hand" in reason
    assert survey.get(conn, "cat")["body"] == "我改過的綜覽"
    assert survey.write("cat", force=True) == (True, "ok")


def test_a_short_reply_is_not_kept_as_a_survey(conn, monkeypatch):
    monkeypatch.setattr(survey.llm, "complete", lambda *a, **k: ("I cannot help.", "ok"))
    written, reason = survey.write("cat")
    assert not written and "too short" in reason
    assert survey.get(conn, "cat") is None


def _long_reply(*_args, **_kwargs):
    return "## 這個領域在解決什麼\n" + "白內障手術影片分析。" * 300, "ok"


def test_a_topic_roadmap_is_not_replaced_unless_forced(conn, monkeypatch):
    conn.execute(
        "INSERT INTO list_surveys(list_id, body, papers, spec, written_at, edited) "
        "VALUES ('cat', '# 研究路線', 2, ?, 'now', 0)",
        (survey.ROADMAP_SPEC,),
    )
    conn.commit()
    monkeypatch.setattr(survey.llm, "complete", _long_reply)
    written, reason = survey.write("cat")
    assert not written and "roadmap" in reason
    assert survey.get(conn, "cat")["body"] == "# 研究路線"
    assert survey.write("cat", force=True) == (True, "ok")
    assert survey.get(conn, "cat")["spec"] == survey.SURVEY_SPEC


def test_an_edit_saved_while_the_survey_is_written_wins(conn, monkeypatch):
    monkeypatch.setattr(survey.llm, "complete", _long_reply)
    assert survey.write("cat") == (True, "ok")

    def edited_meanwhile(*args, **kwargs):
        survey.edit("cat", "撰寫期間我改過的綜覽")
        return _long_reply()

    monkeypatch.setattr(survey.llm, "complete", edited_meanwhile)
    written, reason = survey.write("cat")
    assert not written and "edited while" in reason
    stored = survey.get(conn, "cat")
    assert stored["body"] == "撰寫期間我改過的綜覽" and stored["edited"]


def test_a_forced_rewrite_still_keeps_an_edit_made_during_the_call(conn, monkeypatch):
    monkeypatch.setattr(survey.llm, "complete", _long_reply)
    survey.write("cat")
    survey.edit("cat", "第一次修改")

    def edited_meanwhile(*args, **kwargs):
        survey.edit("cat", "第二次修改")
        return _long_reply()

    monkeypatch.setattr(survey.llm, "complete", edited_meanwhile)
    written, _reason = survey.write("cat", force=True)
    assert not written and survey.get(conn, "cat")["body"] == "第二次修改"


@pytest.fixture
def source_aware_survey():
    from paper_daily import survey_content as content

    inputs = dict(list_id='cat', list_name='Selected field', list_lifecycle='c' * 32,
                  prompt_hash='3' * 64, members=[
        dict(paper_id='a', paper_lifecycle='a' * 32, position=0,
             input_hash='1' * 64, title='First selected paper'),
        dict(paper_id='b', paper_lifecycle='b' * 32, position=0,
             input_hash='2' * 64, title='Second selected paper'),
    ])
    sources = [dict(id=content.source_id('a', 'a' * 32, 'f' * 64), paper_id='a',
                    paper_lifecycle='a' * 32, document_hash='f' * 64, page_count=1,
                    state='captured'),
               dict(id=content.source_id('b', 'b' * 32, None), paper_id='b',
                    paper_lifecycle='b' * 32, document_hash=None, page_count=None,
                    state='unavailable')]
    sections = [dict(heading='Evidence and gaps', statements=[
        dict(text='The first study reports a selected method.', interpretation='reported',
             passages=[dict(source_id=sources[0]['id'], quote='A selected method',
                            location=dict(state='located', reason=None,
                                          anchor=dict(p0=0, o0=0, p1=0, o1=3),
                                          page=1, candidates=[], truncated=False))]),
        dict(text='The cross-paper relationship remains an inference.',
             interpretation='inference', passages=[]),
    ])]
    return content.assemble(inputs=inputs,
                            generation=dict(task='survey', backend='codex',
                                            requested_model='configured-model',
                                            returned_model=None),
                            sources=sources, sections=sections)


def test_source_aware_survey_roundtrip_preserves_exact_prose_and_missing_sources(
    source_aware_survey,
):
    from paper_daily import survey_content as content

    report = content.decode(content.encode(source_aware_survey))
    assert report == source_aware_survey
    prose = content.render(report)
    assert prose == ('## Evidence and gaps\n\n'
                     'The first study reports a selected method.\n\n'
                     'The cross-paper relationship remains an inference.')
    assert content.validate_pair(report, prose) == report
    assert report['sources'][1]['document_hash'] is None
    assert report['sections'][0]['statements'][1]['passages'] == []
    assert report['semantic_validation'] == 'not_performed'
    with pytest.raises(ValueError, match='prose changed'):
        content.validate_pair(report, prose.replace('method', 'new conclusion'))


@pytest.mark.parametrize('change', ['owner', 'lifetime', 'version', 'foreign_source',
                                   'unavailable_location', 'page', 'semantic_claim',
                                   'private_field'])
def test_source_aware_survey_rejects_inconsistent_or_unselected_provenance(
    source_aware_survey, change,
):
    from copy import deepcopy

    from paper_daily import survey_content as content

    report = deepcopy(source_aware_survey)
    passage = report['sections'][0]['statements'][0]['passages'][0]
    if change == 'owner':
        report['sources'][0]['paper_id'] = 'b'
    elif change == 'lifetime':
        report['sources'][0]['paper_lifecycle'] = '0' * 32
    elif change == 'version':
        report['sources'][0]['document_hash'] = '0' * 64
    elif change == 'foreign_source':
        passage['source_id'] = content.source_id('foreign', 'a' * 32, 'f' * 64)
    elif change == 'unavailable_location':
        passage['source_id'] = report['sources'][1]['id']
    elif change == 'page':
        passage['location']['page'] = 2
    elif change == 'semantic_claim':
        report['semantic_validation'] = 'scientifically_verified'
    else:
        report['generation']['account_email'] = 'private@example.invalid'
    with pytest.raises(ValueError):
        content.validate(report)


def test_source_aware_survey_decoding_is_bounded_and_rejects_duplicate_fields(source_aware_survey):
    from paper_daily import survey_content as content

    raw = content.encode(source_aware_survey)
    with pytest.raises(ValueError, match='Duplicate'):
        content.decode(raw.replace('"format":', '"format":"ambiguous","format":', 1))
    with pytest.raises(ValueError, match='Nonfinite'):
        content.decode(raw.replace('"page_count":1', '"page_count":NaN', 1))
    with pytest.raises(ValueError, match='budget'):
        content.decode(' ' * (content.MAX_BYTES + 1))
    changed = dict(source_aware_survey, sections=[])
    with pytest.raises(ValueError):
        content.validate(changed)
