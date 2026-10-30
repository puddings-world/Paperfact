"""Typed review of an original-PDF highlight analysis and its located mark group.

The caller owns the sealed preview and one transaction covering analysis, marks,
outbox and review receipt. No model calls, raw SQL replay or partial row adoption.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from paper_daily import (
    annotation_content,
    highlight_publication,
    paper_highlights,
    pdf_highlights,
    sync_capture,
    sync_content,
)
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import parent_lifecycle

TABLE = highlight_publication.TABLE


def handles(record):
    return json.loads(record["context_json"]).get("table") == TABLE


def _same_owner(conn, original, owner):
    data = original.data
    return (
        original.owner_id == owner
        and generation._path(conn) == data["db_path"]
        and generation._identity(data["db_path"]) == data["database_identity"]
        and generation._binding(conn) == data["binding"]
        and parent_lifecycle(conn, "paper", owner) == data.get("parent_lifecycle")
    )


def _snapshot(conn, record, owner):
    generation.validate_request_record(record)
    if record["status"] != "candidate":
        raise ValueError("The highlight request has no retained candidate")
    original = generation.GenerationContext(record["context_json"])
    row = json.loads(record["row_json"])
    row["paper_id"] = owner
    expected = generation.begin_generation(conn, table=TABLE, owner_id=owner)
    # A retained context's path is only an IO hint for its original owned workspace.
    source = original.data["document"]
    owned = (
        generation._path(conn) == original.data["db_path"]
        and generation._identity(original.db_path) == original.data["database_identity"]
        and generation._binding(conn) == original.data["binding"]
    )
    from paper_daily.document_reader import from_workspace
    from paper_daily.research_question_jobs import _pages

    resolver = from_workspace(
        generation._path(conn), legacy_root=Path(source["path"]).parent if owned else None
    )
    document = resolver.resolve(owner)
    if not document.available or document.sha256 != source["sha256"]:
        raise ValueError("The exact original verified PDF is required for grouped highlight review")
    pages = _pages(document)
    if paper_highlights._hash(pages) != row["source_hash"]:
        raise ValueError("The retained highlight source text differs from the verified PDF")
    body = annotation_content.decode("highlight_analysis", row["body_json"])
    fingerprint, located, unmatched = pdf_highlights.locate(document.path, body)
    if fingerprint != document.sha256:
        raise ValueError("The PDF changed while verifying retained highlight locations")
    expected = generation.bind_inputs(expected, document=document)
    expected = highlight_publication.seal(expected, row, located, unmatched)
    generation._validate_row(expected, row)
    if not generation._document_current(expected):
        raise ValueError("The PDF changed while preparing the displayed highlight group")
    parent = dict(conn.execute("SELECT * FROM papers WHERE id=?", (owner,)).fetchone())
    state = expected.data
    # Observation time/request identity do not form write authority. All saved
    # source, parent, graph and SQL observations remain in the displayed CAS.
    state.pop("request_id")
    state.pop("started_at")
    from paper_daily.research_compound_review import _documents

    snapshot = {"context": state, "parent": parent, "documents": _documents(conn, owner)}
    generation._context_json(snapshot)
    return original, expected, row, snapshot


def _observations(context):
    return [context.data["observation"], *highlight_publication.expectations(context)]


def _restore_needed(context, original):
    old = {(mark["document_hash"], mark["source_key"]) for mark in original.data["inputs"]["marks"]}
    current = {
        (mark["document_hash"], mark["source_key"]) for mark in context.data["inputs"]["marks"]
    }
    planned = {
        (mark["document_hash"], mark["source_key"])
        for mark in context.data["highlight_plan"]["marks"]
    }
    missing = bool((old & planned) - current)
    missing_analysis = context.target is None and (
        original.target is not None or context.data["inputs"]["known"]
    )
    return (
        missing
        or missing_analysis
        or any(
            item and item["incarnation"] is not None and not item["active"]
            for item in _observations(context)
        )
    )


def preview(conn, record, *, owner=None, confirmed=False):
    original = generation.GenerationContext(record["context_json"])
    owner = owner or original.owner_id
    retained_row = json.loads(record["row_json"])
    view = {
        "original": {"analysis": original.target, "marks": original.data["inputs"]["marks"]},
        "retained": {
            "analysis": retained_row,
            "marks": original.data["highlight_plan"]["marks"],
            "unmatched": original.data["highlight_plan"]["unmatched"],
        },
        "scope": {"table": TABLE, "owner_id": owner},
        "source_hash": original.data["document"]["sha256"],
        "editable": False,
        "apply": False,
        "reason": "The exact original PDF and a current paper are required for this complete group",
    }
    try:
        _original, expected, row, snapshot = _snapshot(conn, record, owner)
    except (ValueError, OSError, RuntimeError, sqlite3.DatabaseError):
        return view
    restore = _restore_needed(expected, original)
    same = _same_owner(conn, original, owner)
    capable = (same and not restore) or confirmed
    view.update(
        current={"analysis": expected.target, "marks": expected.inputs["marks"]},
        retained={
            "analysis": row,
            "marks": expected.data["highlight_plan"]["marks"],
            "unmatched": expected.data["highlight_plan"]["unmatched"],
        },
        expected=snapshot,
        parent_token=expected.data["parent_lifecycle"],
        parent_row=snapshot["parent"],
        target={"id": owner, "title": snapshot["parent"]["title"]},
        requires_confirmation=confirmed,
        apply=capable,
        reason=(
            "Confirm the explicitly selected paper and restoration of the complete group"
            if confirmed
            else "Choose the target explicitly to restore deleted highlights"
            if restore
            else "Review the complete analysis and its verified located marks"
            if capable
            else "Choose the target explicitly; original parent ownership changed"
        ),
    )
    return view


def _upsert_analysis(conn, row):
    fields = list(row)
    updates = ",".join(f'"{name}"=excluded."{name}"' for name in fields if name != "paper_id")
    quoted = ",".join(f'"{name}"' for name in fields)
    conn.execute(
        f'INSERT INTO "{TABLE}"({quoted}) VALUES('
        + ",".join("?" for _ in fields)
        + f") ON CONFLICT(paper_id) DO UPDATE SET {updates}",
        tuple(row.values()),
    )


def _restore(conn, context, row=None):
    """Explicit restoration uses graph operations, retaining tombstone history."""
    client = conn._capture_client
    graph = client._optimistic_graph(conn)
    records = ([(TABLE, row)] if row is not None else []) + [
        ("pdf_ai_highlights", mark) for mark in context.data["highlight_plan"]["marks"]
    ]
    with sync_capture.suppress_capture(conn):
        for table, value in records:
            payload = sync_content.content_payload(conn, table, value)
            payload["source_document_hash"] = context.data["document"]["sha256"]
            identity = sync_content.content_id(payload["scope"], payload["feature"], payload["key"])
            prior = graph[0].get(("research_content", identity))
            parent = context.data["observation"]["parents"][0]
            restoring = bool(prior) and (
                not prior["active"]
                or any(ref["incarnation"] != parent["incarnation"] for ref in prior["parents"])
            )
            operation = client.new_graph_operation_in(
                conn, "research_content", identity, payload, restore=restoring
            )
            result = client.journal.apply_in(conn, operation, client.writer)
            if not result["applied"]:
                raise ValueError("Grouped highlight restoration was not applied atomically")
            client._overlay_optimistic(graph, operation)
            conn._capture_graph_cache = graph
    conn._capture_graph_cache = None


def apply_in(conn, record, data, receipt):
    """Apply only the exact displayed typed group; caller records/retries decisions."""
    if not conn.in_transaction:
        raise ValueError("Highlight review requires a caller-owned transaction")
    original, expected, row, snapshot = _snapshot(conn, record, data["scope"]["owner_id"])
    if snapshot != data["expected"]:
        raise ValueError("Displayed highlight group changed; retained work is unchanged")
    retained = {
        "analysis": row,
        "marks": expected.data["highlight_plan"]["marks"],
        "unmatched": expected.data["highlight_plan"]["unmatched"],
    }
    if retained != data["retained"]:
        raise ValueError("Retained highlight group differs from the displayed typed source")
    restore = _restore_needed(expected, original)
    if restore and not data["requires_confirmation"]:
        raise ValueError("Deleted highlights require explicit target confirmation")
    observations = _observations(expected)
    sources = {item["entity_id"]: data["source_hash"] for item in observations if item}
    with sync_capture.expecting(conn, observations, source_hashes=sources):
        if restore and sync_capture.enabled(conn):
            _restore(conn, expected, row)
        else:
            _upsert_analysis(conn, row)
            highlight_publication.apply(conn, expected)
        receipt()
        if not generation._document_current(expected):
            raise ValueError("The source PDF changed during grouped application")
        conn.commit()


class RemoteGroupUnavailable(ValueError):
    """A bounded explanation for retained remote data without complete source authority."""


def remote_group(data):
    return (data.get('origin') == 'remote'
            and (data.get('scope') or {}).get('table') == TABLE
            and isinstance(data.get('expected'), dict)
            and set(data['expected']) == {'remote', 'group'})


def _manual(conn, owner):
    rows = [dict(row) for row in conn.execute(
        'SELECT * FROM pdf_highlights WHERE paper_id=? ORDER BY id LIMIT ?',
        (owner, generation.MAX_ROWS + 1))]
    if len(rows) > generation.MAX_ROWS:
        raise RemoteGroupUnavailable('Manual highlight history exceeds the review budget')
    return rows


def _parent_keys(parents):
    return {(p['kind'], p['id'], p['incarnation']) for p in parents}


def _remote_snapshot(conn, state, owner=None):
    from paper_daily.document_reader import from_workspace
    from paper_daily.research_compound_review import _documents
    from paper_daily.research_question_jobs import _pages
    from paper_daily.sync_journal import canonical_operation

    incoming = json.loads(canonical_operation(state['event']['operation']))
    payload = incoming['payload']
    if (incoming['version'] != 2 or incoming['entity_type'] != 'research_content'
            or incoming['action'] != 'put' or payload.get('feature') != 'highlight_analysis'):
        raise RemoteGroupUnavailable('A lone mark is not complete analysis authority')
    sync_content.validate_payload(payload, entity_id=incoming['entity_id'],
                                  parents=incoming['parents'])
    local = sync_content._local_scope(conn, payload['scope'])
    if owner is not None and owner != local:
        raise RemoteGroupUnavailable('A remote analysis cannot move to another paper')
    owner = local
    if state['resolved_by'] is not None or state['outstanding']:
        raise RemoteGroupUnavailable('Synchronize outstanding edits before grouped source review')
    source_hash = payload['source_document_hash']
    if source_hash is None:
        raise RemoteGroupUnavailable('The original PDF source hash is unknown')
    row = {'paper_id': owner, **payload['data']}
    row['body_json'] = generation._json(row['body_json'])
    annotation_content.validate_row('highlight_analysis', row)
    body = annotation_content.decode('highlight_analysis', row['body_json'])
    if not body['items']:
        raise RemoteGroupUnavailable('The retained analysis has no complete source quotes')
    expected = generation.begin_generation(conn, table=TABLE, owner_id=owner)
    refs = expected.data['observation']['parents']
    if not refs or not all(ref['active'] for ref in refs):
        raise RemoteGroupUnavailable('The original paper parent is not currently active')
    # Use only this owned database's registered paths. A remote payload cannot
    # nominate local paths, and mutable global settings never select its source.
    document = from_workspace(generation._path(conn)).resolve(owner)
    if not document.available or document.sha256 != source_hash:
        raise RemoteGroupUnavailable('The exact original verified PDF is unavailable')
    if paper_highlights._hash(_pages(document)) != row['source_hash']:
        raise RemoteGroupUnavailable('The retained source text differs from the verified PDF')
    fingerprint, located, unmatched = pdf_highlights.locate(document.path, body)
    if fingerprint != document.sha256 or unmatched:
        raise RemoteGroupUnavailable(
            'Every retained full quote must be located in the original PDF')
    expected = generation.bind_inputs(expected, document=document)
    expected = highlight_publication.seal(expected, row, located, unmatched)
    generation._validate_row(expected, row)
    if not generation._document_current(expected):
        raise RemoteGroupUnavailable('The source PDF changed during grouped source review')
    parent = dict(conn.execute('SELECT * FROM papers WHERE id=?', (owner,)).fetchone())
    context = expected.data
    context.pop('request_id')
    context.pop('started_at')
    snapshot = {'context': context, 'parent': parent, 'documents': _documents(conn, owner),
                'manual': _manual(conn, owner)}
    generation._context_json(snapshot)
    active = state['state'] or {}
    restore_analysis = bool(active) and (
        not active['active'] or _parent_keys(active['parents']) != _parent_keys(refs))
    restore = (restore_analysis or _restore_needed(expected, expected)
               or _parent_keys(incoming['parents']) != _parent_keys(refs))
    return expected, row, snapshot, restore_analysis, restore


def remote_preview(conn, state, *, owner=None, confirmed=False):
    """Rebuild an incoming analysis into a complete exact-source local mark group."""
    blocked = {'apply': False, 'editable': False,
               'reason': 'Highlight conflicts require complete grouped source review'}
    try:
        expected, row, snapshot, _restore_analysis, restore = _remote_snapshot(conn, state, owner)
    except RemoteGroupUnavailable as error:
        blocked['reason'] += ': ' + str(error)
        return blocked
    except (ValueError, OSError, RuntimeError, sqlite3.DatabaseError):
        blocked['reason'] += ': retained data or its registered source could not be verified'
        return blocked
    return {
        'current': {'analysis': expected.target, 'marks': expected.inputs['marks']},
        'retained': {'analysis': row, 'marks': expected.data['highlight_plan']['marks'],
                     'unmatched': expected.data['highlight_plan']['unmatched']},
        'scope': {'table': TABLE, 'owner_id': expected.owner_id},
        'source_hash': row['document_hash'],
        'expected': {'remote': state, 'group': snapshot},
        'parent_token': expected.data['parent_lifecycle'], 'parent_row': snapshot['parent'],
        'target': {'id': expected.owner_id, 'title': snapshot['parent']['title']},
        'editable': False, 'apply': not restore or confirmed,
        'requires_confirmation': confirmed,
        'reason': ('Confirm this paper and restoration of the complete source group'
                   if confirmed else 'Choose this paper explicitly to restore the source group'
                   if restore else 'Review the complete analysis and its verified located marks'),
    }


def _row_identity(row):
    annotation_content.validate_row('highlight_analysis', row)
    return {**row, 'body_json': annotation_content.decode('highlight_analysis', row['body_json'])}


def _mark_map(marks):
    return {(mark['document_hash'], mark['source_key']):
            {**mark, 'anchor': json.loads(mark['anchor'])} for mark in marks}


def _after_remote_analysis(conn, context, row, snapshot):
    """Revalidate source, parent and all curated layers after conflict resolution callbacks."""
    from paper_daily.research_compound_review import _documents

    parent = conn.execute('SELECT * FROM papers WHERE id=?', (context.owner_id,)).fetchone()
    state = context.data
    if (parent is None or dict(parent) != snapshot['parent']
            or parent_lifecycle(conn, 'paper', context.owner_id) != state['parent_lifecycle']
            or generation._identity(context.db_path) != state['database_identity']
            or generation._binding(conn) != state['binding']
            or _documents(conn, context.owner_id) != snapshot['documents']
            or _manual(conn, context.owner_id) != snapshot['manual']
            or not generation._document_current(context)):
        raise ValueError('Source or parent changed during grouped remote application')
    current = conn.execute('SELECT * FROM paper_highlight_analysis WHERE paper_id=?',
                           (context.owner_id,)).fetchone()
    if current is None or _row_identity(dict(current)) != _row_identity(row):
        raise ValueError('Analysis changed during grouped remote application')
    observed = sync_capture.observe_target(conn, 'paper', context.owner_id, 'highlight_analysis')
    if observed['parents'] != state['observation']['parents']:
        raise ValueError('Paper graph changed during grouped remote application')


def apply_remote_in(conn, data, request_id, receipt):
    """Resolve only the displayed remote analysis; atomically publish all rebuilt marks."""
    if not conn.in_transaction or not remote_group(data):
        raise ValueError('Grouped remote review requires its displayed transaction')
    client = conn._capture_client
    state = client.conflict_observation_in(conn, int(data['id']))
    expected, row, snapshot, restore_analysis, restore = _remote_snapshot(
        conn, state, data['scope']['owner_id'])
    if {'remote': state, 'group': snapshot} != data['expected']:
        raise ValueError('Displayed remote highlight group changed; retained work is unchanged')
    retained = {'analysis': row, 'marks': expected.data['highlight_plan']['marks'],
                'unmatched': expected.data['highlight_plan']['unmatched']}
    if retained != data['retained']:
        raise ValueError('Retained remote highlight group differs from the displayed source')
    if restore and not data['requires_confirmation']:
        raise ValueError('Restoring this group requires explicit target confirmation')
    before = expected.inputs['marks']
    with sync_capture.suppress_capture(conn):
        result = client.resolve_conflict_in(
            conn, int(data['id']), expected=state,
            payload=state['event']['operation']['payload'], operation_id=request_id,
            restore=restore_analysis)
    _after_remote_analysis(conn, expected, row, snapshot)
    if highlight_publication.inputs(conn, expected.owner_id)['marks'] != before:
        raise ValueError('Highlight choices changed during remote conflict resolution')
    _restore(conn, expected)
    final = _mark_map(before)
    final.update(_mark_map(expected.data['highlight_plan']['marks']))
    receipt(result['operation_id'])
    _after_remote_analysis(conn, expected, row, snapshot)
    current = highlight_publication.inputs(conn, expected.owner_id)['marks']
    if _mark_map(current) != final:
        raise ValueError('Highlight group changed during remote application')
    conn.commit()
