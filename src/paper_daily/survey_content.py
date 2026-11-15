"""Closed list-survey evidence records; declarations are never source authority.

The producer must capture actual inputs and verify quotations against owned sealed
originals. Decoding this record grants no local paper mapping, file access, sync
publication or semantic support. Legacy prose is deliberately not migrated here.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from paper_daily import claim_content as content

FORMAT = "paperfact.survey-evidence.v1"
RECIPE = "list-survey-sources.v1"
MAX_BYTES = 1024 * 1024
MAX_BODY_BYTES = 200 * 1024
MAX_MEMBERS = 2000
MAX_STATEMENTS = 96
MAX_PASSAGES = 384
MAX_PAGES = 500
LIFETIME = re.compile(r"[0-9a-f]{32}")


def _encode(value):
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
        if len(result.encode('utf-8')) > MAX_BYTES:
            raise ValueError('Survey evidence exceeds its bounded inline budget')
        return result
    except (TypeError, UnicodeError, RecursionError):
        raise ValueError('Invalid bounded survey evidence') from None


def _items(value, maximum, *, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError('Survey evidence collection exceeds its declared bounds')


def _lifetime(value):
    if not isinstance(value, str) or not LIFETIME.fullmatch(value):
        raise ValueError('Survey evidence requires its actual input lifetime')


def source_id(paper_id, lifetime, document_hash):
    return content.hashed(['survey-source.v1', paper_id, lifetime, document_hash])


def statement_id(section, index, text):
    return content.hashed(['survey-statement.v1', section, index, content.normalize(text)])


def _render(report):
    return '\n\n'.join(
        '## ' + section['heading'] + '\n\n' + '\n\n'.join(
            item['text'] for item in section['statements'])
        for section in report['sections'])


def body_hash(body):
    if not isinstance(body, str):
        raise ValueError('Survey body must be text')
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def validate(report):
    """Check a bounded portable record, not the truth/ownership of its declarations."""
    _encode(report)
    content.closed(report, {'format', 'recipe', 'inputs', 'generation', 'sources',
                           'sections', 'source_check', 'semantic_validation', 'body_hash', 'id'})
    if (report['format'] != FORMAT or report['recipe'] != RECIPE
            or report['source_check'] != 'quote_location_only'
            or report['semantic_validation'] != 'not_performed'):
        raise ValueError('Unsupported survey evidence contract')
    inputs = report['inputs']
    content.closed(inputs, {'list_id', 'list_name', 'list_lifecycle', 'prompt_hash', 'members'})
    content.text(inputs['list_id'], 4096)
    content.text(inputs['list_name'], 2000)
    content.digest(inputs['prompt_hash'])
    _lifetime(inputs['list_lifecycle'])
    _items(inputs['members'], MAX_MEMBERS, minimum=1)
    members = {}
    for member in inputs['members']:
        content.closed(member, {'paper_id', 'paper_lifecycle', 'position', 'input_hash', 'title'})
        content.text(member['paper_id'], 4096)
        content.text(member['title'], 2000)
        _lifetime(member['paper_lifecycle'])
        content.digest(member['input_hash'])
        content.number(member['position'], 2**31 - 1, minimum=-(2**31))
        if member['paper_id'] in members:
            raise ValueError('Duplicate survey input paper')
        members[member['paper_id']] = member
    order = [(m['position'], m['paper_id']) for m in inputs['members']]
    if order != sorted(order):
        raise ValueError('Survey inputs must retain their captured member order')
    generation = report['generation']
    content.closed(generation, {'task', 'backend', 'requested_model', 'returned_model'})
    if (generation['task'] != 'survey' or not isinstance(generation['backend'], str)
            or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', generation['backend'])):
        raise ValueError('Invalid survey generation task or provider')
    for key in ('requested_model', 'returned_model'):
        content.text(generation[key], 512, nullable=True)
    _items(report['sources'], MAX_MEMBERS, minimum=1)
    if len(report['sources']) != len(members):
        raise ValueError('Every captured survey input needs an explicit source state')
    sources = {}
    for source, member in zip(report['sources'], inputs['members'], strict=True):
        content.closed(source, {'id', 'paper_id', 'paper_lifecycle', 'document_hash',
                               'page_count', 'state'})
        if (source['paper_id'] != member['paper_id']
                or source['paper_lifecycle'] != member['paper_lifecycle']):
            raise ValueError('Survey source differs from its captured paper lifetime')
        if source['document_hash'] is not None:
            content.digest(source['document_hash'])
        if source['state'] not in ('captured', 'unavailable', 'not_selected'):
            raise ValueError('Invalid survey source availability state')
        if source['state'] == 'captured':
            content.digest(source['document_hash'])
            content.number(source['page_count'], MAX_PAGES, minimum=1)
        elif source['page_count'] is not None:
            raise ValueError('Unavailable survey source has no inspected page count')
        expected = source_id(source['paper_id'], source['paper_lifecycle'], source['document_hash'])
        if source['id'] != expected or source['id'] in sources:
            raise ValueError('Survey source identity differs from its owner/version')
        sources[source['id']] = source
    _items(report['sections'], 16, minimum=1)
    statements = passages = 0
    identities = set()
    for section_index, section in enumerate(report['sections']):
        content.closed(section, {'heading', 'statements'})
        content.text(section['heading'], 200)
        if '\n' in section['heading'] or '\r' in section['heading']:
            raise ValueError('Survey headings must remain single-line labels')
        _items(section['statements'], MAX_STATEMENTS, minimum=1)
        for index, item in enumerate(section['statements']):
            statements += 1
            content.closed(item, {'id', 'text', 'interpretation', 'passages'})
            content.text(item['text'], 12000)
            if (item['id'] != statement_id(section_index, index, item['text'])
                    or item['id'] in identities):
                raise ValueError('Survey statement identity differs from its recorded text')
            identities.add(item['id'])
            if item['interpretation'] not in ('reported', 'synthesis', 'inference'):
                raise ValueError('Survey interpretation must not claim verified semantic support')
            _items(item['passages'], 16)
            seen = set()
            for passage in item['passages']:
                passages += 1
                content.closed(passage, {'source_id', 'quote', 'location'})
                content.text(passage['source_id'], 64)
                content.text(passage['quote'], 4000)
                source = sources.get(passage['source_id'])
                if source is None:
                    raise ValueError('Survey passage names an unselected source')
                if passage['location'] is not None:
                    if source['state'] != 'captured':
                        raise ValueError(
                            'Unavailable survey original cannot have a checked location')
                    content.location(passage['location'], source['page_count'])
                key = content.hashed(passage)
                if key in seen:
                    raise ValueError('Duplicate survey statement passage')
                seen.add(key)
    if statements > MAX_STATEMENTS or passages > MAX_PASSAGES:
        raise ValueError('Survey evidence exceeds its statement/passage budget')
    content.digest(report['body_hash'])
    body = _render(report)
    if len(body.encode('utf-8')) > MAX_BODY_BYTES:
        raise ValueError('Survey prose exceeds its existing storage budget')
    if report['body_hash'] != body_hash(body):
        raise ValueError('Survey evidence does not describe the recorded prose')
    content.digest(report['id'])
    if report['id'] != content.hashed({k: v for k, v in report.items() if k != 'id'}):
        raise ValueError('Survey evidence record digest differs')
    return report


def assemble(*, inputs, generation, sources, sections):
    """Copy explicit producer inputs; assign content IDs without inventing evidence."""
    report = deepcopy(dict(format=FORMAT, recipe=RECIPE, inputs=inputs, generation=generation,
                           sources=sources, sections=sections, source_check='quote_location_only',
                           semantic_validation='not_performed'))
    for section_index, section in enumerate(report['sections']):
        for index, item in enumerate(section['statements']):
            if 'id' in item:
                raise ValueError('Survey producer cannot reuse a prior statement identity')
            item['id'] = statement_id(section_index, index, item['text'])
    report['body_hash'] = body_hash(_render(report))
    report['id'] = content.hashed(report)
    return validate(report)


def encode(report):
    return _encode(validate(report))


def decode(encoded):
    if not isinstance(encoded, str) or len(encoded.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Survey evidence exceeds its bounded inline budget')

    def unique(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError('Duplicate survey evidence field')
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError('Nonfinite survey evidence value')

    try:
        return validate(json.loads(encoded, object_pairs_hook=unique, parse_constant=invalid))
    except (TypeError, UnicodeError, RecursionError):
        raise ValueError('Invalid bounded survey evidence') from None


def render(report):
    """Return only the recorded prose; link inspection remains a separate operation."""
    validate(report)
    return _render(report)


def validate_pair(report, body):
    """Reject changed manual prose; an old source ledger cannot follow a rewrite."""
    validate(report)
    if body_hash(body) != report['body_hash']:
        raise ValueError('Survey prose changed; its previous sources require review')
    return report
