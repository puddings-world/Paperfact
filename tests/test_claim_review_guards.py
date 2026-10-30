"""Claim exports stay readable and source-aware review stays fail-closed."""
import json

import pytest

from paper_daily import annotation_content
from paper_daily.research_review import _claim_export, _source_aware_block, _source_aware_required


@pytest.mark.parametrize('origin', ['generation', 'sidecar'])
def test_claim_generation_requires_source_aware_review_even_with_generic_apply_flags(origin):
    view = {'origin': origin, 'scope': {'table': 'paper_claim_sets', 'owner_id': 'paper'},
            'retained': {}, 'apply': True, 'editable': True}
    assert _source_aware_required(view)
    blocked = _source_aware_block(view)
    assert blocked['apply'] is False and blocked['editable'] is False
    assert blocked['reason'] == 'Claim sets require source-aware review'


def test_remote_claim_requires_source_aware_review_but_unrelated_features_do_not():
    assert _source_aware_required({'origin': 'remote', 'retained': {'feature': 'claims'}})
    assert not _source_aware_required({'origin': 'remote', 'retained': {'feature': 'dive'}})
    assert not _source_aware_required({'origin': 'generation', 'scope': {'table': 'dives'}})


def test_claim_export_invokes_closed_validator_and_whitelists_readable_fields(monkeypatch):
    raw = '{"example": "bounded raw body"}'
    calls = []

    def decode(feature, text):
        calls.append((feature, text))
        return {'generation': {'private': 'secret account'}, 'inputs': {'path': 'private path'},
                'report': {'source': {'path': 'never export'}, 'claims': [
                    {'text': 'A proposed claim', 'judgment': {'status': 'supported',
                     'reason': 'A proposed judgment', 'authority': 'caller'}, 'passages': [
                        {'quote': 'Exact paper quote', 'location': {'state': 'exact',
                         'reason': 'private scanner details',
                         'anchor': {'path': 'never export'}}}]}]}}

    monkeypatch.setattr(annotation_content, 'decode', decode)
    exported = _claim_export({'body_json': raw})
    assert calls == [('claims', raw)]
    assert exported == {'claims': [{'text': 'A proposed claim',
                        'judgment': {'status': 'supported', 'reason': 'A proposed judgment'},
                        'passages': [{'quote': 'Exact paper quote', 'location': 'exact'}]}]}
    assert 'private' not in json.dumps(exported) and 'authority' not in json.dumps(exported)


def test_invalid_claim_export_never_falls_back_to_raw_provenance(monkeypatch):
    def reject(*_):
        raise ValueError('Unsupported or incomplete claim body')

    monkeypatch.setattr(annotation_content, 'decode', reject)
    value = _claim_export({'data': {'body_json': {'generation': {'account': 'private'}}}})
    assert value == {'unavailable': 'Claim content could not be validated for readable export'}
