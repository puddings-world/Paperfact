"""Device-local offline intent and bounded verification of current managed assets.

No transport, AI, publication, projection creation or legacy-file adoption occurs.
Run plan/status on a worker. Readiness applies to selected current manifests only.
"""
from __future__ import annotations

import sqlite3
import time
from copy import deepcopy

from paper_daily.sync_artifacts import (
    applied_file,
    desired_file,
    paper_current,
    verify_closure,
)
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_documents import (
    _paper_current,
    applied_document,
    desired_document,
    verify_document,
)
from paper_daily.sync_files import file_id, referenced_blobs
from paper_daily.workspace_service import (
    SnapshotChanged,
    Ticket,
    WorkspaceChanged,
    WorkspaceService,
    _read,
    _ReadOnlyStore,
    _tables,
)
from paper_daily.workspace_sync import local_binding

PREFIX = 'ui.offline.paper.'
MAX_PAPERS = 100
MAX_PINS = 1000
MAX_BYTES = 64 * 1024**2
MAX_ASSETS = 256


def _selection(values):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_PAPERS:
        raise ValueError('Select at most 100 local paper IDs')
    if any(not isinstance(v, str) or not v or len(v) > 512 for v in values):
        raise ValueError('Expected nonempty local paper IDs')
    return list(dict.fromkeys(values))


class OfflineService:
    """One explicit database; only set_pins writes (device-local ui.* keys)."""

    def __init__(self, database, *, current_path=None):
        self.workspace = WorkspaceService(database, current_path=current_path)
        self.workspace._baseline = self.workspace._context()
        self.identity = local_binding(self.workspace.path, require_capture=True)

    def _check(self, ticket):
        ticket.check()
        self.workspace.check()
        if local_binding(self.workspace.path, require_capture=True) != self.identity:
            raise WorkspaceChanged('The enrolled workspace identity changed')

    def _snapshot(self, selection, ticket):
        self._check(ticket)
        rows = []
        with _read(self.workspace.path) as conn:
            tables = _tables(conn)
            inventory = {'research_file_desired', 'research_file_applied'} <= tables
            for local in selection:
                ticket.check()
                found = conn.execute(
                    'SELECT m.sync_id,substr(p.title,1,2000),g.incarnation '
                    'FROM research_paper_identity m JOIN papers p ON p.id=m.local_id '
                    'LEFT JOIN research_paper_projection g '
                    'ON g.sync_id=m.sync_id WHERE m.local_id=? LIMIT 2', (local,),
                ).fetchall()
                if len(found) != 1 or not found[0][2]:
                    raise ValueError('Selected paper has no current portable identity')
                portable, title, _incarnation = found[0]
                # file_id validates the canonical portable UUID; no caller-built SQL/path.
                artifact_ids = [(slot, file_id(portable, 'deck', slot))
                                for slot in ('notes', 'guide')]
                pdf = desired_document(conn, portable)
                applied = applied_document(conn, portable)
                state = ('missing_manifest' if pdf is None else 'unbound'
                         if applied != pdf else 'stale' if not _paper_current(conn, pdf)
                         else 'unchecked')
                artifacts = []
                if inventory:
                    for slot, entity in artifact_ids:
                        # Do not parse an unbounded stored operation.
                        for table in ('research_file_desired', 'research_file_applied'):
                            size = conn.execute(
                                f'SELECT length(operation) FROM {table} WHERE entity_id=?',
                                (entity,),
                            ).fetchone()
                            if size and size[0] > 128 * 1024:
                                raise ValueError('Stored artifact operation exceeds bounds')
                        operation = desired_file(conn, entity)
                        if operation is None:
                            continue
                        bound = applied_file(conn, entity)
                        source = operation['payload']['source_document_hash']
                        source_state = ('unknown' if source is None else 'current'
                                        if pdf and source == pdf['sha256'] else 'mismatch')
                        artifacts.append({
                            'entity_id': entity, 'slot': slot, 'operation': operation,
                            'state': ('unbound' if bound != operation else 'stale'
                                      if not paper_current(conn, operation) else 'unchecked'),
                            'source_state': source_state,
                        })
                pinned = conn.execute(
                    'SELECT CASE WHEN length(value)<=5 THEN value ELSE NULL END '
                    'FROM kv WHERE key=?', (PREFIX + portable,),
                ).fetchone()
                if pinned and pinned[0] not in ('true', 'false'):
                    raise ValueError('Invalid local offline intent')
                rows.append({
                    'paper_id': local, 'portable_id': portable, 'title': title,
                    'pinned': bool(pinned and pinned[0] == 'true'),
                    'pdf': {'state': state, 'target': pdf, 'applied': applied},
                    'artifacts': artifacts, 'artifact_inventory_available': inventory,
                })
        self._check(ticket)
        return rows

    def pins(self, ticket=None):
        """Return active local IDs, resolving persisted portable pin identities."""
        ticket = ticket or Ticket()
        self._check(ticket)
        with _read(self.workspace.path) as conn:
            rows = conn.execute(
                'SELECT m.local_id,m.sync_id,length(k.value),CASE WHEN length(k.value)<=5 '
                'THEN k.value ELSE NULL END FROM kv k '
                'JOIN research_paper_identity m ON k.key=?||m.sync_id '
                'JOIN papers p ON p.id=m.local_id ORDER BY m.local_id LIMIT ?',
                (PREFIX, MAX_PINS + 1),
            ).fetchall()
        if len(rows) > MAX_PINS or any(row[2] > 5 or row[3] not in ('true', 'false')
                                      for row in rows):
            raise ValueError('Invalid or excessive local offline intents')
        self._check(ticket)
        return [{'paper_id': row[0], 'portable_id': row[1]} for row in rows if row[3] == 'true']

    def _pin_targets(self, selection, ticket):
        self._check(ticket)
        result = []
        with _read(self.workspace.path) as conn:
            for local in selection:
                ticket.check()
                rows = conn.execute(
                    'SELECT m.sync_id,g.incarnation FROM research_paper_identity m '
                    'JOIN papers p ON p.id=m.local_id JOIN research_paper_projection g '
                    'ON g.sync_id=m.sync_id WHERE m.local_id=? LIMIT 2', (local,),
                ).fetchall()
                if len(rows) != 1:
                    raise ValueError('Selected paper has no current portable identity')
                file_id(rows[0][0], 'deck', 'notes')  # Validate portable UUID.
                result.append({'paper_id': local, 'portable_id': rows[0][0],
                               'incarnation': rows[0][1]})
        return result

    def set_pins(self, paper_ids, enabled=True, ticket=None):
        """Persist intent only; never download, evict bytes or create sync operations."""
        if type(enabled) is not bool:
            raise ValueError('Offline intent must be a boolean')
        ticket = ticket or Ticket()
        selection = _selection(paper_ids)
        snapshot = self._pin_targets(selection, ticket)
        conn = sqlite3.connect(self.workspace.path.as_uri() + '?mode=rw', uri=True,
                               factory=CaptureConnection, timeout=0.2)
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._check(ticket)
            if snapshot != self._pin_targets(selection, ticket):
                raise SnapshotChanged('Selected research changed before saving offline intent')
            count = conn.execute(
                'SELECT COUNT(*) FROM kv WHERE key>=? AND key<?',
                (PREFIX, PREFIX + '\U0010ffff'),
            ).fetchone()[0]
            for row in snapshot:
                key = PREFIX + row['portable_id']
                if enabled:
                    exists = conn.execute('SELECT 1 FROM kv WHERE key=?', (key,)).fetchone()
                    count += not bool(exists)
                    if count > MAX_PINS:
                        raise ValueError('Offline pin limit reached')
                    conn.execute('INSERT INTO kv(key,value) VALUES(?,?) '
                                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                 (key, 'true'))
                else:
                    conn.execute('DELETE FROM kv WHERE key=?', (key,))
            self._check(ticket)
            ticket.publish(conn.commit)
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {'paper_ids': selection, 'pinned': enabled}

    def plan(self, paper_ids, ticket=None):
        """Bounded metadata-only preflight; this is never an offline-ready claim."""
        ticket = ticket or Ticket()
        papers = self._snapshot(_selection(paper_ids), ticket)
        manifests = {}
        for paper in papers:
            target = paper['pdf']['target']
            if target:
                manifests[target['sha256']] = target['size']
            for artifact in paper['artifacts']:
                for row in referenced_blobs(artifact['operation']):
                    old = manifests.setdefault(row['sha256'], row['size'])
                    if old != row['size']:
                        raise ValueError('Inconsistent manifest sizes')
        return {'scope': 'selected_current_manifests', 'papers': papers,
                'required_bytes': sum(manifests.values()), 'required_assets': len(manifests),
                'ready': False, 'whole_workspace_offline_verified': False}

    def _store(self):
        context = self.workspace._context()
        root = context[2]
        if root is None:
            return None
        store = _ReadOnlyStore(root)
        with _read(root / 'index.sqlite') as conn:
            if 'transfer_binding' not in _tables(conn):
                raise WorkspaceChanged('Registered blob store has no ownership binding')
            rows = conn.execute(
                'SELECT workspace,device,research_path FROM transfer_binding LIMIT 2'
            ).fetchall()
        expected = (self.identity['workspace_id'], self.identity['device_id'],
                    str(self.workspace.path))
        if len(rows) != 1 or tuple(rows[0]) != expected:
            raise WorkspaceChanged('Blob store ownership differs from the active workspace')
        return store

    def status(self, paper_ids, ticket=None, *, max_bytes=MAX_BYTES,
               max_assets=MAX_ASSETS, seconds=10):
        """Verify current managed bytes within explicit per-pass resource limits.

        Cancellation/deadline checks occur between existing bounded verifications;
        a single PDF/closure verification is not forcibly interrupted mid-parser.
        """
        if (type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES
                or type(max_assets) is not int or not 0 < max_assets <= MAX_ASSETS
                or isinstance(seconds, bool) or not isinstance(seconds, (float, int))
                or not 0 < seconds <= 30):
            raise ValueError('Invalid offline verification budget')
        ticket = ticket or Ticket()
        selection = _selection(paper_ids)
        report = self.plan(selection, ticket)
        before = deepcopy(report['papers'])
        store = self._store()
        deadline, spent, checked = time.monotonic() + seconds, 0, 0
        proofs = []
        for paper in report['papers']:
            entries = [(paper['pdf'], True), *[(row, False) for row in paper['artifacts']]]
            for item, is_pdf in entries:
                self._check(ticket)
                if item['state'] != 'unchecked':
                    continue
                if store is None:
                    item['state'] = 'unconfigured'
                    continue
                rows = ([item['target']] if is_pdf else referenced_blobs(item['operation']))
                size, count = sum(row['size'] for row in rows), len(rows)
                if (spent + size > max_bytes or checked + count > max_assets
                        or time.monotonic() >= deadline):
                    item['state'] = 'budget_exceeded'
                    continue
                spent, checked = spent + size, checked + count
                try:
                    if is_pdf:
                        proof = verify_document(store, item['target'])
                        target = item['target']
                    else:
                        proof, _body, _blobs = verify_closure(store, item['operation'])
                        target = item['operation']
                    self._check(ticket)
                    if time.monotonic() >= deadline:
                        item['state'] = 'budget_exceeded'
                    elif not proof.matches(target):
                        item['state'] = 'invalid'
                    else:
                        item['state'] = 'verified'
                        proofs.append((item, proof, target, rows))
                except (OSError, ValueError):
                    item['state'] = 'unavailable'
        self._check(ticket)
        if before != self._snapshot(selection, ticket):
            raise SnapshotChanged('Selected research changed during offline verification')
        self._store()  # Recheck ownership after worker-side file verification.
        for item, proof, target, _rows in proofs:
            if not proof.matches(target):
                item['state'] = 'invalid'
        for paper in report['papers']:
            paper['ready'] = (paper['pdf']['state'] == 'verified'
                              and paper['artifact_inventory_available']
                              and all(row['state'] == 'verified'
                                      and row['source_state'] == 'current'
                                      for row in paper['artifacts']))
        verified = {row['sha256']: row['size']
                    for item, _proof, _target, rows in proofs if item['state'] == 'verified'
                    for row in rows}
        report.update(ready=bool(report['papers']) and all(p['ready'] for p in report['papers']),
                      partial=any(row['state'] == 'budget_exceeded' for p in report['papers']
                                  for row in [p['pdf'], *p['artifacts']]),
                      verified_bytes=sum(verified.values()), verification_bytes=spent,
                      verified_assets=len(verified), checked_assets=checked)
        return report
