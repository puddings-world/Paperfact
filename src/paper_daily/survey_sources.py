"""Sealed, workspace-owned original snapshots for source-aware survey proposals.

No AI call, SQL mutation, current-PDF activation, file publication or enrollment.
The later publisher must retain originals and recheck this capture's currentness.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily import survey, survey_content
from paper_daily.document_reader import DocumentReader, ResolvedDocument, from_workspace

MAX_ORIGINAL_BYTES = 64 * 1024**2
_KEY = secrets.token_bytes(32)


def _seal(value):
    return hmac.new(_KEY, survey_content._encode(value).encode('utf-8'), hashlib.sha256).hexdigest()


def _cancel(cancelled):
    if cancelled():
        raise ValueError('Survey source work was cancelled')


def _context_current(context):
    try:
        with closing(generation._connect(context.db_path)) as conn:
            conn.execute('BEGIN')
            return generation._stale(conn, context) is None
    except (OSError, ValueError, sqlite3.DatabaseError):
        return False


@dataclass(frozen=True, slots=True)
class SurveySources:
    _context: generation.GenerationContext = field(repr=False)
    _json: str = field(repr=False)
    _snapshots: tuple = field(repr=False)
    _documents: tuple = field(repr=False)
    _reader: object = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def sources(self):
        return json.loads(self._json)['sources']

    @property
    def inputs(self):
        return json.loads(self._json)['inputs']


def _capture_seal(context, encoded, snapshots, documents, reader):
    return _seal([hashlib.sha256(context._json.encode()).hexdigest(),
                  hashlib.sha256(encoded.encode()).hexdigest(),
                  [s._seal if s else None for s in snapshots],
                  [id(d) if d else None for d in documents], id(reader)])


def _checked(capture):
    if (not isinstance(capture, SurveySources)
            or not isinstance(capture._context, generation.GenerationContext)
            or not isinstance(capture._json, str) or not isinstance(capture._seal, str)
            or not isinstance(capture._snapshots, tuple)
            or not isinstance(capture._documents, tuple)
            or not isinstance(capture._reader, DocumentReader)
            or any(s is not None and not isinstance(s, evidence.EvidenceSnapshot)
                   for s in capture._snapshots)
            or any(d is not None and not isinstance(d, ResolvedDocument)
                   for d in capture._documents)):
        raise ValueError('Survey sources require their sealed capture')
    expected = _capture_seal(capture._context, capture._json, capture._snapshots,
                             capture._documents, capture._reader)
    if not hmac.compare_digest(capture._seal, expected):
        raise ValueError('Survey source capture changed')
    value = json.loads(capture._json)
    if (len(value['sources']) != len(capture._snapshots)
            or len(capture._snapshots) != len(capture._documents)):
        raise ValueError('Survey source capture closure differs')
    for source, snapshot, document in zip(value['sources'], capture._snapshots,
                                          capture._documents, strict=True):
        if snapshot is None:
            if source['state'] == 'captured':
                raise ValueError('Survey source lacks its original snapshot')
            continue
        original, _data = evidence._checked_snapshot(snapshot)
        if (snapshot._origin is not document or document._owner is not capture._reader
                or document.local_id != source['paper_id']
                or original['paper_id'] != (document.paper_id or document.local_id)
                or original['document_hash'] != source['document_hash']):
            raise ValueError('Survey original belongs to another input owner/version')
    return value


def current(capture):
    _checked(capture)
    if not _context_current(capture._context):
        return False
    try:
        for document in capture._documents:
            if document is None:
                continue
            if document.available:
                if not capture._reader.current(document):
                    return False
            elif capture._reader.resolve(document.local_id).available:
                return False
    except (OSError, ValueError, sqlite3.DatabaseError):
        return False
    return True


def capture(context, *, legacy_root=None, selected_ids=None, cancelled=lambda: False):
    """Worker operation: capture exactly selected existing originals, without download."""
    _cancel(cancelled)
    inputs = survey.evidence_inputs(context)
    if not _context_current(context):
        raise ValueError('Survey inputs changed before source capture')
    papers = [member['paper_id'] for member in inputs['members']]
    if selected_ids is None:
        selected = set(papers)
    else:
        if (not isinstance(selected_ids, (list, tuple))
                or any(not isinstance(item, str) for item in selected_ids)
                or len(set(selected_ids)) != len(selected_ids)
                or not set(selected_ids).issubset(papers)):
            raise ValueError('Survey sources must select actual distinct input papers')
        selected = set(selected_ids)
    reader = from_workspace(context.db_path, legacy_root=legacy_root)
    sources, snapshots, documents = [], [], []
    used = 0
    for member in inputs['members']:
        _cancel(cancelled)
        paper = member['paper_id']
        document = snapshot = None
        digest = pages = None
        state = 'not_selected'
        if paper in selected:
            document = reader.resolve(paper)
            state = 'unavailable'
            digest = document.sha256
            if document.available:
                snapshot = evidence.capture(document)
                original, raw = evidence._checked_snapshot(snapshot)
                used += len(raw)
                if used > MAX_ORIGINAL_BYTES:
                    raise ValueError('Selected survey originals exceed the capture budget')
                digest = original['document_hash']
                pages = len(evidence.snapshot_pages(snapshot, cancelled=cancelled))
                state = 'captured'
        sources.append(dict(id=survey_content.source_id(paper, member['paper_lifecycle'], digest),
                            paper_id=paper, paper_lifecycle=member['paper_lifecycle'],
                            document_hash=digest, page_count=pages, state=state))
        snapshots.append(snapshot)
        documents.append(document)
    from paper_daily.survey_publication import observe

    native = observe(context, sources)
    encoded = survey_content._encode(dict(inputs=inputs, sources=sources, native=native))
    snapshots, documents = tuple(snapshots), tuple(documents)
    result = SurveySources(context, encoded, snapshots, documents, reader,
                           _capture_seal(context, encoded, snapshots, documents, reader))
    _cancel(cancelled)
    if not current(result):
        raise ValueError('Survey inputs or originals changed during capture')
    return result


@dataclass(frozen=True, slots=True)
class SurveyProposal:
    _capture: SurveySources = field(repr=False)
    _json: str = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def report(self):
        return checked_proposal(self)


def checked_proposal(proposal):
    if (not isinstance(proposal, SurveyProposal) or not isinstance(proposal._json, str)
            or not isinstance(proposal._seal, str)):
        raise ValueError('Survey publication requires its checked proposal')
    data = _checked(proposal._capture)
    expected = _seal([proposal._capture._seal,
                      hashlib.sha256(proposal._json.encode()).hexdigest()])
    if not hmac.compare_digest(proposal._seal, expected):
        raise ValueError('Survey proposal changed after original checks')
    report = survey_content.decode(proposal._json)
    if report['inputs'] != data['inputs'] or report['sources'] != data['sources']:
        raise ValueError('Survey proposal differs from its captured corpus')
    return report


def verify(corpus, sections, *, provenance, cancelled=lambda: False):
    """Locate proposed quotations in owned snapshots; never accept model locations."""
    data = _checked(corpus)
    _cancel(cancelled)
    sections = json.loads(survey_content._encode(sections))
    survey_content._items(sections, 16, minimum=1)
    sources = {source['id']: (source, snapshot) for source, snapshot
               in zip(data['sources'], corpus._snapshots, strict=True)}
    groups = {}
    statements = passages = 0
    for section in sections:
        survey_content.content.closed(section, {'heading', 'statements'})
        survey_content.content.text(section['heading'], 200)
        if '\n' in section['heading'] or '\r' in section['heading']:
            raise ValueError('Survey headings must remain single-line labels')
        survey_content._items(section['statements'], survey_content.MAX_STATEMENTS, minimum=1)
        for item in section['statements']:
            statements += 1
            survey_content.content.closed(item, {'text', 'interpretation', 'passages'})
            survey_content.content.text(item['text'], 12000)
            if item['interpretation'] not in ('reported', 'synthesis', 'inference'):
                raise ValueError('Survey interpretation is not a semantic verification')
            survey_content._items(item['passages'], 16)
            for passage in item['passages']:
                passages += 1
                survey_content.content.closed(passage, {'source_id', 'quote', 'page', 'anchor'})
                survey_content.content.text(passage['source_id'], 64)
                survey_content.content.text(passage['quote'], 4000)
                if passage['page'] is not None:
                    survey_content.content.number(passage['page'], 1000000, minimum=1)
                if passage['anchor'] is not None:
                    survey_content.content.anchor(passage['anchor'], survey_content.MAX_PAGES)
                source = sources.get(passage['source_id'])
                if source is None or source[0]['state'] == 'not_selected':
                    raise ValueError('Survey passage names an unselected original')
                groups.setdefault(passage['source_id'], []).append(passage)
    if statements > survey_content.MAX_STATEMENTS or passages > survey_content.MAX_PASSAGES:
        raise ValueError('Survey evidence exceeds its statement/passage budget')
    for source_id, proposed in groups.items():
        _cancel(cancelled)
        source, snapshot = sources[source_id]
        if snapshot is None:
            for passage in proposed:
                passage.pop('page')
                passage.pop('anchor')
                passage['location'] = None
            continue
        original, _raw = evidence._checked_snapshot(snapshot)
        # The evidence engine checks quotes only. Internal request IDs do not
        # impersonate a semantic appraisal of the survey's paragraph text.
        for offset in range(0, len(proposed), evidence.MAX_CLAIMS):
            part = proposed[offset:offset + evidence.MAX_CLAIMS]
            payload = dict(format=evidence.FORMAT, source=original, claims=[
                dict(text='Survey quotation ' + str(offset + index),
                     judgment=dict(status='unresolved', reason='Quote location only'),
                     passages=[dict(quote=p['quote'], page=p['page'], anchor=p['anchor'])])
                for index, p in enumerate(part)])
            checked = evidence.verify_snapshot(snapshot, payload, cancelled=cancelled)
            for passage, claim in zip(part, checked['claims'], strict=True):
                passage.pop('page')
                passage.pop('anchor')
                passage['location'] = claim['passages'][0]['location']
    report = survey_content.assemble(inputs=data['inputs'], generation=provenance,
                                     sources=data['sources'], sections=sections)
    encoded = survey_content.encode(report)
    _cancel(cancelled)
    seal = _seal([corpus._seal, hashlib.sha256(encoded.encode()).hexdigest()])
    return SurveyProposal(corpus, encoded, seal)


def pages(corpus, *, max_bytes=240 * 1024, cancelled=lambda: False):
    """Return bounded exact-original prompt pages, without silent truncation or I/O fallback."""
    data = _checked(corpus)
    if type(max_bytes) is not int or not 1 <= max_bytes <= survey_content.MAX_BYTES:
        raise ValueError('Invalid survey source prompt budget')
    result = []
    for source, snapshot in zip(data['sources'], corpus._snapshots, strict=True):
        _cancel(cancelled)
        if snapshot is not None:
            result.append(dict(source_id=source['id'],
                               pages=evidence.snapshot_pages(snapshot, cancelled=cancelled)))
            if len(survey_content._encode(result).encode('utf-8')) > max_bytes:
                raise ValueError('Selected survey original text exceeds the prompt budget')
    _cancel(cancelled)
    return result


def _original_rows(proposal):
    from paper_daily import source_snapshots

    checked_proposal(proposal)
    corpus = proposal._capture
    data = _checked(corpus)
    context = corpus._context.data
    result = []
    for source, snapshot in zip(data['sources'], corpus._snapshots, strict=True):
        if snapshot is None:
            continue
        original, raw = evidence._checked_snapshot(snapshot)
        owner = dict(format=source_snapshots.SURVEY_FORMAT,
                     database_identity=context['database_identity'], binding=context['binding'],
                     paper_id=source['paper_id'], parent_lifecycle=source['paper_lifecycle'],
                     source_owner_id=original['paper_id'], list_id=corpus._context.owner_id,
                     list_lifecycle=context['parent_lifecycle'],
                     generation_request_id=corpus._context.request_id, source_id=source['id'])
        row = dict(request_id='survey-original:' + survey_content.content.hashed(owner),
                   owner_json=generation._json(owner), sha256=source['document_hash'],
                   size=len(raw), media_type='application/pdf')
        source_snapshots.validate(row)
        result.append((row, raw))
    return result


def retain_originals(proposal, *, cancelled=lambda: False):
    """Durably archive complete original/receipt pairs before any canonical SQL write.

    A cancelled group may leave complete private pairs; retry reuses their exact
    bytes. No active original, survey row, outbox operation or ownership mapping
    is created. A later accepted publication must associate every returned row.
    """
    from paper_daily import position_source_snapshots as atomic_sources

    _cancel(cancelled)
    rows = _original_rows(proposal)
    for row, raw in rows:
        _cancel(cancelled)
        atomic_sources.publish(proposal._capture._context.db_path, row, data=raw)
    _cancel(cancelled)
    return [row for row, _raw in rows]


def retained_originals(proposal, receipts, *, cancelled=lambda: False):
    """Read/check the complete exact archive; no re-download or replacement on failure."""
    from paper_daily import position_source_snapshots as atomic_sources

    _cancel(cancelled)
    expected = [row for row, _raw in _original_rows(proposal)]
    if (not isinstance(receipts, list)
            or generation._json(receipts) != generation._json(expected)):
        raise ValueError('Survey original association differs from its checked proposal')
    files = []
    for row in expected:
        _cancel(cancelled)
        path, version = atomic_sources.verify(proposal._capture._context.db_path, row)
        files.append((path, version))
    _cancel(cancelled)
    return tuple(files)
