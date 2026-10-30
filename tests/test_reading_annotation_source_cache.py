"""A cached highlight group can never stand in for another displayed PDF source."""
from contextlib import closing

import pytest
from test_highlight_generation import QUOTES, marks
from test_highlight_generation import ready as ready_fixture
from test_highlight_generation import workspace as workspace_fixture
from test_research_generation import pdf, rows

from paper_daily import llm, reading_annotation_jobs, sync_capture
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace

workspace = workspace_fixture
ready = ready_fixture


def run(ready, **kwargs):
    return reading_annotation_jobs.prepare(
        ready[0], 'paper', legacy_root=ready[2].path.parent, **kwargs)


def replace_source(ready):
    ready[2].path.unlink()
    pdf(ready[2].path, QUOTES[1])
    document = from_workspace(ready[0], legacy_root=ready[2].path.parent).resolve('paper')
    assert document.available and document.sha256 != ready[2].sha256
    return document


def test_cached_group_rejects_old_displayed_hash_before_return_or_provider_call(ready, monkeypatch):
    assert run(ready)[0]['marks']['mapped'] == 1
    before = rows(ready[0], 'SELECT * FROM paper_highlight_analysis'), marks(ready[0])
    replace_source(ready)
    monkeypatch.setattr(llm, 'capture_connections', lambda: pytest.fail('Wrong source called AI'))
    with pytest.raises(ValueError, match='displayed PDF'):
        run(ready, expected_document_hash=ready[2].sha256)
    assert (rows(ready[0], 'SELECT * FROM paper_highlight_analysis'), marks(ready[0])) == before
    assert len(ready[5]) == 1


def test_new_verified_expected_source_regenerates_cached_group_and_places_new_marks(ready):
    assert run(ready)[0]['marks']['mapped'] == 1
    document = replace_source(ready)
    result, reason = run(ready, expected_document_hash=document.sha256)
    assert reason == 'ok' and result['analysis']['document_hash'] == document.sha256
    assert result['marks']['document_hash'] == document.sha256
    assert result['marks']['mapped'] == 1 and len(ready[5]) == 2
    current = rows(ready[0], 'SELECT * FROM paper_highlight_analysis')[0]
    assert current['document_hash'] == document.sha256
    assert any(mark['document_hash'] == document.sha256 and mark['quote'] == QUOTES[1]
               and mark['analysis_hash'] == current['source_hash'] for mark in marks(ready[0]))


def test_new_expected_source_does_not_resurrect_known_deleted_group(ready, monkeypatch):
    assert run(ready)[0]['marks']['mapped'] == 1
    with closing(generation._connect(ready[0])) as conn:
        observed = sync_capture.observe_target(conn, 'paper', 'paper', 'highlight_analysis')
        with sync_capture.expecting(conn, [observed]):
            conn.execute("DELETE FROM paper_highlight_analysis WHERE paper_id='paper'")
            conn.commit()
    document = replace_source(ready)
    monkeypatch.setattr(llm, 'capture_connections', lambda: pytest.fail('Deletion called AI'))
    result, reason = run(ready, expected_document_hash=document.sha256)
    assert result['analysis'] == {'items': [], 'known': True}
    assert result['marks'] is None and 'deleted' in reason
    assert rows(ready[0], 'SELECT * FROM paper_highlight_analysis') == []
    assert len(ready[5]) == 1
