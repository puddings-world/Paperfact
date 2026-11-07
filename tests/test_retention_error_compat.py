"""Legacy stale-save callers retain compatibility without mistaking raw metadata for bytes."""

import copy
import json
import sqlite3
from contextlib import closing

import pytest
from test_raw_deck_receipts import no_external as _no_external
from test_sync_files import LOCAL, save_current
from test_sync_files import codec as _codec
from test_sync_files import pair as _pair

from paper_daily import presentations, store
from paper_daily.pending_deck_result import PendingDeckResults
from paper_daily.sync_deck_publication import (
    IncompleteDraftRetention,
    StaleDeckError,
    observe_deck,
)

codec, pair, no_external = _codec, _pair, _no_external


@pytest.mark.parametrize('destination', ['enrolled', 'unbound'])
def test_incomplete_workspace_refusal_is_compatible_but_remains_visibly_unsaved(
    pair, codec, monkeypatch, tmp_path, destination
):
    _server, a, b, _fa, _fb, _ta, _tb = pair
    value = copy.deepcopy(codec[0])
    value.paper_id, value.title = LOCAL, 'Actual output lacking captured image ownership'
    save_current(pair, codec[0])
    before_deck = presentations.load_deck(LOCAL, 'guide').to_dict()
    observation = observe_deck(LOCAL, 'guide')
    before_a, before_b = a.journal.pending(), b.journal.pending()
    path = b.journal.path if destination == 'enrolled' else tmp_path / 'unbound.sqlite'
    if destination == 'unbound':
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(store.SCHEMA)
    with monkeypatch.context() as m:
        m.setattr(store, 'DB_PATH', path)
        with pytest.raises(IncompleteDraftRetention) as caught:
            presentations.save_deck(value, observation=observation)
    error = caught.value
    assert isinstance(error, StaleDeckError)
    context = ('Deck belongs to another workspace/device'
               if destination == 'enrolled' else 'Workspace changed')
    assert str(error) == context + (
        '; Draft retention is incomplete; preserve the actual unsaved result'
    )
    assert 'incomplete' in str(error) and 'original draft retained' not in str(error)
    outcome = error.retention
    assert outcome.candidate_id == error.candidate_id
    assert outcome.deck is value and not outcome.durable and outcome.state == 'incomplete'
    assert outcome._capture is None
    assert 'captured original roots or producer bytes' in outcome.reason
    assert a.journal.pending() == before_a and b.journal.pending() == before_b
    assert presentations.load_deck(LOCAL, 'guide').to_dict() == before_deck
    with closing(sqlite3.connect(a.journal.path)) as conn:
        row = conn.execute(
            'SELECT deck FROM research_file_drafts WHERE candidate_id=?', (error.candidate_id,)
        ).fetchone()
        assert json.loads(row[0]) == value.to_dict()
    pending = PendingDeckResults()
    key = pending.hold(outcome)
    assert pending.items() == [(key, outcome)]
    with pytest.raises(ValueError, match='captured byte'):
        pending.retry(key)
    export = tmp_path / 'incomplete.paperfact-draft.json'
    with pytest.raises(ValueError, match='captured bytes'):
        pending.export(key, export)
    assert not export.exists() and pending.items() == [(key, outcome)]
