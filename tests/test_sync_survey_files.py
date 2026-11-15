"""List survey bytes travel independently of bounded journal metadata and PDF grants."""

from copy import deepcopy

import pytest
from test_survey import source_aware_survey as source_aware_survey
from test_sync_files import PAPER, drain
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import survey_content, sync_source_files, sync_survey_files
from paper_daily.sync_artifacts import (
    activate,
    applied_file,
    desired_file,
    materialize,
    stage_bytes,
)
from paper_daily.sync_files import canonical_json, list_file_id, validate_closure, validate_payload
from paper_daily.sync_journal import canonical_operation


def report_for(source_aware_survey, source_hash, *, large=False):
    report = deepcopy(source_aware_survey)
    report['sources'][0]['document_hash'] = source_hash
    report['sources'][0]['id'] = survey_content.source_id('a', 'a' * 32, source_hash)
    report['sections'][0]['statements'][0]['passages'][0]['source_id'] = report['sources'][0]['id']
    if large:
        for index in range(650):
            identity = 'missing-' + str(index)
            report['inputs']['members'].append(dict(paper_id=identity, paper_lifecycle='d' * 32,
                position=index + 1, input_hash='4' * 64, title='Unretrieved input ' + 'x' * 100))
            report['sources'].append(dict(id=survey_content.source_id(identity, 'd' * 32, None),
                paper_id=identity, paper_lifecycle='d' * 32, document_hash=None, page_count=None,
                state='unavailable'))
    for section in report['sections']:
        for item in section['statements']:
            del item['id']
    return survey_content.assemble(inputs=report['inputs'], generation=report['generation'],
        sources=report['sources'], sections=report['sections'])


def setup_survey(pair, source_aware_survey, *, large=False):
    import pymupdf

    server, a, _, fa, _, ta, _ = pair
    listing = a.new_graph_operation('list', 'cat', dict(name='Selected field', note=''))
    a.save(listing)
    a.sync_once(server, ta)
    with pymupdf.open() as document:
        document.new_page().insert_text((30, 30), 'A selected method')
        source_payload, source_blobs = sync_source_files.encode(PAPER, document.tobytes())
    source = a.new_graph_operation('research_file',
        sync_survey_files.file_id(PAPER, 'original_source', source_payload['slot']), source_payload)
    a.save(source)
    stage_bytes(fa.store, source_blobs)
    report = report_for(source_aware_survey, source_payload['slot'], large=large)
    binding = dict(source_id=report['sources'][0]['id'], paper_id=PAPER,
        paper_incarnation=source['parents'][0]['incarnation'], document_hash=source_payload['slot'],
        file_id=source['entity_id'], incarnation=source['incarnation'])
    versions = dict(schema_version=2, complete=False, workspace_id='workspace', documents=[],
        inputs_sha256=report['inputs']['prompt_hash'], entities=[
            dict(kind=kind, id=identity, incarnation=incarnation, revision=0, depends_on=None)
            for kind, identity, incarnation in (
                ('list', 'cat', listing['incarnation']),
                ('paper', PAPER, binding['paper_incarnation']),
                ('research_file', source['entity_id'], source['incarnation']))])
    payload, blobs = sync_survey_files.encode(report, 'cat', [binding], input_versions=versions)
    operation = a.new_graph_operation('research_file', list_file_id('cat'), payload)
    a.save(operation)
    stage_bytes(fa.store, blobs)
    return report, source, operation, blobs


def test_large_survey_receives_exact_prose_sources_and_separate_originals(
    pair, source_aware_survey,
):
    server, a, b, fa, fb, ta, tb = pair
    report, source, operation, blobs = setup_survey(pair, source_aware_survey, large=True)
    assert len(next(iter(blobs.values()))) > 256 * 1024
    assert len(canonical_operation(operation).encode()) < 16 * 1024
    assert operation['parents'][0]['kind'] == 'list' and 'paper_id' not in operation['payload']
    assert not fa.ready_to_push(operation)
    drain(lambda: fa.upload(source), 'uploaded')
    # Upload is not a received service outcome.
    assert not fa.ready_to_push(operation)
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    drain(lambda: fa.upload(operation), 'uploaded')
    assert fa.ready_to_push(operation)
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    b.sync_once(server, tb)
    with b.journal.transaction() as conn:
        assert desired_file(conn, operation['entity_id']) == operation
        assert applied_file(conn, operation['entity_id']) is None
    drain(lambda: fb.download(operation['entity_id']), 'bound')
    directory = materialize(fb.store, fb.root, operation)
    assert (directory / 'survey.json').read_bytes() == next(iter(blobs.values()))
    received = validate_closure(operation['payload'], lambda row: blobs[row['sha256']])
    assert received['report'] == report
    assert not (directory / 'source.pdf').exists()
    with b.journal.transaction() as conn:
        assert applied_file(conn, operation['entity_id']) == operation
        assert applied_file(conn, source['entity_id']) is None


def test_closed_list_manifest_rejects_owner_workspace_and_source_substitution(
    pair, source_aware_survey,
):
    _, _, _, _, _, _, _ = pair
    _, _, operation, blobs = setup_survey(pair, source_aware_survey)
    for mutate in (
        lambda p: p.update(paper_id=PAPER),
        lambda p: p['source_bindings'][0].update(paper_id='22222222-2222-4222-8222-222222222222'),
        lambda p: p['source_bindings'][0].update(incarnation='another-lifetime'),
        lambda p: p['input_versions'].update(schema_version=1),
    ):
        bad = deepcopy(operation['payload'])
        mutate(bad)
        with pytest.raises(ValueError):
            validate_payload(bad)
    bad = deepcopy(operation)
    bad['payload']['input_versions']['workspace_id'] = 'another-workspace'
    with pytest.raises(ValueError, match='workspace'):
        canonical_operation(bad)
    bad = deepcopy(operation['payload'])
    bad['source_bindings'] = []
    with pytest.raises(ValueError, match='bindings'):
        validate_closure(bad, lambda row: blobs[row['sha256']])
    bad = deepcopy(operation)
    bad['parents'] = [dict(kind='paper', id=PAPER, incarnation='wrong')]
    with pytest.raises(ValueError):
        canonical_operation(bad)


def test_service_retains_conflict_for_retired_original_and_local_rejects_stale_pin(
    pair, source_aware_survey,
):
    server, a, _, fa, _, ta, _ = pair
    _, source, operation, _ = setup_survey(pair, source_aware_survey)
    drain(lambda: fa.upload(source), 'uploaded')
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    drain(lambda: fa.upload(operation), 'uploaded')
    retirement = a.new_graph_operation('research_file', source['entity_id'], {}, action='delete')
    a.save(retirement)
    a.sync_once(server, ta, prepare_push=lambda op: (
        op['entity_id'] != operation['entity_id'] and fa.ready_to_push(op)))
    with pytest.raises(ValueError, match='original-source'):
        a.new_graph_operation('research_file', operation['entity_id'], operation['payload'])
    event = server.push(ta, operation)
    assert event['outcome'] == 'conflict'
    assert event['operation'] == operation


def test_list_artifact_retirement_requires_same_identity_and_owner(pair, source_aware_survey):
    _, a, _, _, _, _, _ = pair
    _, _, operation, _ = setup_survey(pair, source_aware_survey)
    retirement = a.new_graph_operation('research_file', operation['entity_id'], {}, action='delete')
    canonical_operation(retirement)
    assert retirement['parents'] == operation['parents']
    assert retirement['entity_id'] != sync_survey_files.file_id(PAPER, 'deck', 'guide')
    bad = deepcopy(retirement)
    bad['entity_id'] = sync_survey_files.file_id(PAPER, 'deck', 'guide')
    with pytest.raises(ValueError, match='identity'):
        canonical_operation(bad)
    # Tampered report bytes never pass the reusable closure verifier.
    with pytest.raises(ValueError, match='bytes'):
        validate_closure(operation['payload'], lambda _: canonical_json({}))


def test_late_materialization_cannot_activate_after_owning_list_retires(pair, source_aware_survey):
    server, a, b, fa, fb, ta, tb = pair
    _, source, operation, _ = setup_survey(pair, source_aware_survey)
    drain(lambda: fa.upload(source), 'uploaded')
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    drain(lambda: fa.upload(operation), 'uploaded')
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    b.sync_once(server, tb)
    drain(lambda: fb.download(operation['entity_id']), 'bound')
    directory = materialize(fb.store, fb.root, operation)
    retirement = a.new_graph_operation('list', 'cat', {}, action='delete')
    a.save(retirement)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    with b.journal.transaction() as conn:
        assert activate(conn, operation, directory) is False
    assert (directory / 'survey.json').is_file()  # Retained historical bytes stay inspectable.
