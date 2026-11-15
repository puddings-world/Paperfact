"""List-owned survey report blobs with explicit native original-file lifetimes.

Wire validation is not a publication grant. The trusted publisher must derive
bindings from its captured owners, stage originals and retain the checked report.
"""

from __future__ import annotations

from copy import deepcopy

from paper_daily import survey_content
from paper_daily.sync_files import (
    canonical_json,
    closed,
    descriptor,
    digest,
    file_id,
    identifier,
    read_json,
    uuid,
)

FEATURE = 'survey'
SLOT = 'overview'
FORMAT = 'paperfact.survey-artifact.v1'
MAX_SOURCES = 64
MAX_BODY_BYTES = survey_content.MAX_BYTES + 1024
BINDING_FIELDS = {'source_id', 'paper_id', 'paper_incarnation', 'document_hash',
                  'file_id', 'incarnation'}


def selected(operation):
    return (isinstance(operation, dict) and operation.get('entity_type') == 'research_file'
            and isinstance(operation.get('payload'), dict)
            and operation['payload'].get('feature') == FEATURE)


def validate_manifest(payload, *, parents=None):
    from paper_daily.sync_files import validate_input_versions

    identifier(payload['list_id'])
    if (payload['feature'] != FEATURE or payload['slot'] != SLOT
            or payload['source_document_hash'] is not None or payload['assets'] != []):
        raise ValueError('Survey artifacts have a list owner, one report and separate originals')
    body = payload['body']
    if (type(body['size']) is not int or not 0 < body['size'] <= MAX_BODY_BYTES
            or body['media_type'] != 'application/json'):
        raise ValueError('Invalid bounded survey report descriptor')
    digest(body['sha256'])
    versions = payload['input_versions']
    validate_input_versions(versions)
    if versions['schema_version'] != 2:
        raise ValueError('Survey artifacts require workspace-bound native input versions')
    digest(versions['inputs_sha256'])
    observed = {(row['kind'], row['id']): row for row in versions['entities']}
    owner = observed.get(('list', payload['list_id']))
    if owner is None:
        raise ValueError('Survey artifact omits its actual list lifetime observation')
    if parents is not None and owner['incarnation'] != parents[0]['incarnation']:
        raise ValueError('Survey artifact belongs to a different list lifetime')
    bindings = payload['source_bindings']
    if not isinstance(bindings, list) or len(bindings) > MAX_SOURCES:
        raise ValueError('Survey artifact exceeds its bounded original-source bindings')
    seen = set()
    papers = set()
    for binding in bindings:
        closed(binding, BINDING_FIELDS)
        digest(binding['source_id'])
        digest(binding['document_hash'])
        uuid(binding['paper_id'])
        identifier(binding['paper_incarnation'])
        identifier(binding['incarnation'])
        if (binding['source_id'] in seen or binding['paper_id'] in papers
                or binding['file_id'] != file_id(binding['paper_id'], 'original_source',
                                                  binding['document_hash'])):
            raise ValueError('Survey source binding duplicates or substitutes its owner/version')
        seen.add(binding['source_id'])
        papers.add(binding['paper_id'])
        for kind, identity, incarnation in (
            ('paper', binding['paper_id'], binding['paper_incarnation']),
            ('research_file', binding['file_id'], binding['incarnation']),
        ):
            observation = observed.get((kind, identity))
            if observation is None or observation['incarnation'] != incarnation:
                raise ValueError('Survey source binding differs from its native input observation')
    return payload


def validate_report_body(payload, body):
    closed(body, {'format', 'list_id', 'report'})
    if body['format'] != FORMAT or body['list_id'] != payload['list_id']:
        raise ValueError('Survey report body belongs to another list')
    report = survey_content.validate(body['report'])
    expected = [source for source in report['sources'] if source['state'] == 'captured']
    actual = payload['source_bindings']
    if len(expected) != len(actual) or any(
        (source['id'], source['document_hash']) != (binding['source_id'], binding['document_hash'])
        for source, binding in zip(expected, actual, strict=True)
    ):
        raise ValueError('Survey original bindings omit or replace captured report sources')
    if report['inputs']['prompt_hash'] != payload['input_versions']['inputs_sha256']:
        raise ValueError('Survey native input block differs from the actual retained prompt')
    return body


def encode(report, list_id, bindings, *, input_versions):
    """Encode explicit data only; caller retains native mapping/publication authority."""
    from paper_daily.sync_files import validate_payload

    survey_content.validate(report)
    body = canonical_json(dict(format=FORMAT, list_id=list_id, report=report))
    payload = dict(list_id=list_id, feature=FEATURE, slot=SLOT, format_version=1,
                   source_document_hash=None, input_versions=deepcopy(input_versions),
                   source_bindings=deepcopy(bindings), body=descriptor(body, 'application/json'),
                   assets=[])
    validate_payload(payload)
    validate_report_body(payload, read_json(body))
    return payload, {payload['body']['sha256']: body}


def validate_closure(payload, blobs):
    return validate_report_body(payload, read_json(blobs[payload['body']['sha256']]))


def active(get_entity, operation):
    """Caller transaction checks actual workspace-scoped paper/file lifetimes."""
    if operation['action'] == 'delete':
        return True
    validate_manifest(operation['payload'], parents=operation['parents'])
    for binding in operation['payload']['source_bindings']:
        parent = dict(kind='paper', id=binding['paper_id'],
                      incarnation=binding['paper_incarnation'])
        paper = get_entity('paper', binding['paper_id'])
        original = get_entity('research_file', binding['file_id'])
        if (not isinstance(paper, dict) or paper.get('active') is not True
                or paper.get('incarnation') != binding['paper_incarnation']
                or not isinstance(original, dict) or original.get('active') is not True
                or original.get('incarnation') != binding['incarnation']
                or original.get('parents') != [parent]):
            return False
    return True


def ready_to_push_in(conn, client, operation):
    """Wait for actual source outcomes; an upload/push acknowledgement is insufficient."""
    from paper_daily.lineage_dependencies import _source_outcomes_in
    from paper_daily.sync_journal import canonical_operation

    canonical_operation(operation)
    if not selected(operation) or operation['action'] != 'put':
        raise ValueError('Survey readiness requires its actual report operation')

    def check_source(source, pin):
        canonical_operation(source)
        if (source['version'] != 2 or source['workspace_id'] != operation['workspace_id']
                or source['entity_type'] != 'research_file' or source['action'] != 'put'
                or source['operation_id'] != pin['incarnation']
                or source['incarnation'] != pin['incarnation']
                or source['entity_id'] != pin['file_id']
                or source['parents'] != [dict(kind='paper', id=pin['paper_id'],
                                              incarnation=pin['paper_incarnation'])]
                or source['payload'].get('feature') != 'original_source'
                or source['payload'].get('paper_id') != pin['paper_id']
                or source['payload'].get('source_document_hash') != pin['document_hash']):
            raise ValueError('Survey dependency differs from its exact owned original publication')

    return _source_outcomes_in(conn, client, operation, operation['payload']['source_bindings'],
                               check_source)
