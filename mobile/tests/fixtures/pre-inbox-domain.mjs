import { contentId, uuid5Name, asciiJSON } from '../../ids.mjs';
import { validateArtifact } from '../../artifacts.mjs';
import { queueClosure, queueParents, requireLegacy } from '../../legacy-workflow.mjs';
import {
  copy,
  own,
  put
} from '../../store.mjs';
import {
  validateContent,
  validateRichNote,
  projectContent,
  suppressSnapshotContent
} from '../../content.mjs';
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const HASH = /^[0-9a-f]{64}$/;
export const states =['pending', 'delivered', 'read', 'skipped', 'deferred'];
const kinds =['list', 'paper', 'membership', 'note', 'reading_state', 'list_order', 'workspace_list_order',
'paper_document', 'research_content', 'research_file'];
export function requireThat(test, code = 'invalid_data') {
  if(! test) throw new Error(code);
}
export function identifier(value) {
  requireThat(typeof value === 'string' && ID.test(value));
  return value;
}
export function integer(value) {
  requireThat(Number.isSafeInteger(value) && value >= 0);
  return value;
}
export function closed(value, required, optional =[]) {
  requireThat(value && typeof value === 'object' && ! Array.isArray(value));
  requireThat(required.every(key => Object.hasOwn(value, key)) && Object.keys(value).every(key =>[...required,
  ...optional].includes(key)));
}
export function stable(value) {
  if(Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if(value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + stable(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
export const keyOf =(kind, id) => `${kind}/${id}`;
const utf8 = value => new TextEncoder().encode(value).length;
function boundedText(value, limit, nullable = false) {
  requireThat((nullable && value === null) ||(typeof value === 'string' &&[...value].length <= limit));
}
function parentShape(op) {
  if(queueClosure(op)) { queueParents(op); return; }
  const pin = op.entity_type === 'research_content' &&
    ((op.action === 'put' && op.payload?.feature === 'list_pin') ||
    (op.action === 'delete' && op.parents.length === 3));
  if(pin) {
    requireThat(op.parents.length === 3 && stable(op.parents.map(p=>p.kind)) === stable(['list','paper','membership']));
    for(const p of op.parents) { closed(p,['kind','id','incarnation']); identifier(p.id); identifier(p.incarnation); }
    const [list,paper,member]=op.parents;
    requireThat(list.id !== 'queue' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(paper.id));
    requireThat(member.id === uuid5Name('paperfact:membership:' + asciiJSON([list.id,paper.id])));
    requireThat(op.entity_id === contentId({kind:'list',id:list.id},'list_pin',paper.id));
    return;
  }
  const edge = op.entity_type === 'research_content' &&
    ((op.action === 'put' && op.payload?.feature === 'reference_edge') ||
    (op.action === 'delete' && op.parents.length === 2));
  if(edge) {
    requireThat(op.parents.length >= 1 && op.parents.length <= 2);
    const seen = new Set();
    for(const p of op.parents) {
      closed(p,['kind','id','incarnation']);
      requireThat(p.kind === 'paper' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(p.id));
      identifier(p.incarnation);
      requireThat(!seen.has(p.id)); seen.add(p.id);
    }
    requireThat(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(op.entity_id));
    if(op.action === 'delete') requireThat(op.entity_id === contentId(
      {kind:'paper',id:op.parents[0].id},'reference_edge',op.parents[1].id));
    return;
  }
  if(['research_content','research_file'].includes(op.entity_type)) {
    requireThat(op.parents.length === 1 && (op.entity_type === 'research_file' ? ['paper'] : ['paper','list']).includes(op.parents[0].kind));
    closed(op.parents[0], ['kind', 'id', 'incarnation']);
    identifier(op.parents[0].id);
    identifier(op.parents[0].incarnation);
    if(op.entity_type === 'research_file') requireThat(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(op.parents[0].id));
    requireThat(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(op.entity_id));
    return;
  }
  const expected = {
    list: [],
    paper: [],
    workspace_list_order: [],
    membership: ['list', 'paper'],
    note: ['paper'],
    paper_document: ['paper'],
    research_file: ['paper'],
    reading_state: ['membership', 'list', 'paper'],
    list_order: ['list']
  }
  [op.entity_type];
  requireThat(stable(op.parents.map(p => p.kind).sort()) === stable(expected.sort()));
  for(const p of op.parents) {
    closed(p, ['kind', 'id', 'incarnation']);
    identifier(p.id);
    identifier(p.incarnation);
  }
  if(op.action === 'put') {
    for(const p of op.parents) {
      if(p.kind === 'paper') requireThat(p.id === op.payload.paper_id);
      if(p.kind === 'list') requireThat(p.id === op.payload.list_id);
      if(p.kind === 'membership') requireThat(p.id === op.entity_id);
    }
  }
}
export function validateOperation(op, workspace) {
  const base =['version', 'operation_id', 'workspace_id', 'device_id', 'entity_type', 'entity_id', 'action',
  'base_revision', 'depends_on', 'payload'];
  requireThat(op?.version === 1 || op?.version === 2, 'unsupported_version');
  closed(
  op,
  op.version === 2 ?[...base, 'incarnation', 'parents', 'structure_revision']: base,
  ['resolution_of', ...(op.version === 2 ?['structure_depends_on']: [])]
  );
  requireThat(op.workspace_id === workspace, 'wrong_workspace');
  for(const name of['operation_id', 'workspace_id', 'device_id', 'entity_id']) identifier(op[name]);
  requireThat(
  op.version === 2 ? kinds.includes(op.entity_type): ['list', 'note'].includes(op.entity_type),
  'unsupported_operation'
  );
  requireThat(['put', 'delete'].includes(op.action));
  integer(op.base_revision);
  if(op.depends_on !== null) identifier(op.depends_on);
  for(const field of['resolution_of', 'structure_depends_on']) if(Object.hasOwn(op, field)) identifier(op[field]);
  for(const field of['depends_on', 'resolution_of', 'structure_depends_on']) requireThat(op[field] !== op.operation_id,
  'self_dependency');
  requireThat(utf8(stable(op)) <= 256 * 1024, 'operation_too_large');
  if(op.version === 2) {
    identifier(op.incarnation);
    integer(op.structure_revision);
    requireThat(Array.isArray(op.parents));
    parentShape(op);
  }
  if(op.action === 'delete') {
    closed(op.payload, []);
    requireThat(op.entity_type !== 'paper');
    return op;
  }
  if(op.entity_type === 'note') {
    if(Object.keys(op.payload).length === 2) {
      closed(op.payload, ['paper_id', 'body']);
      identifier(op.payload.paper_id);
      boundedText(op.payload.body, 200 * 1024);
    } else {
      requireThat(op.version === 2);
      validateRichNote(op.payload);
    }
  } else if(op.entity_type === 'research_file') {
    validateArtifact(op.payload, op.entity_id, op.parents);
  } else if(op.entity_type === 'research_content') {
    validateContent(op.payload, op.entity_id, op.parents);
  } else if(op.entity_type === 'list') {
    closed(op.payload, ['name', 'note']);
    boundedText(op.payload.name, 200);
    requireThat(op.payload.name.trim());
    boundedText(op.payload.note, 128 * 1024, op.version === 2);
  } else if(op.entity_type === 'reading_state') {
    closed(op.payload, ['list_id', 'paper_id', 'state', 'delivered_at', 'read_at']);
    requireThat(states.includes(op.payload.state));
    for(const field of['delivered_at', 'read_at']) {
      const v = op.payload[field];
      requireThat(v === null ||(typeof v === 'string' && v.length <= 64 && /(Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v))));
    }
  } else if(op.entity_type === 'paper_document') {
    closed(op.payload, ['paper_id', 'sha256', 'size', 'media_type']);
    requireThat(HASH.test(op.payload.sha256));
    integer(op.payload.size);
    requireThat(op.payload.size > 0 && op.payload.size <= 150 * 1024 * 1024 && op.payload.media_type === 'application/pdf' && op.entity_id === op.payload.paper_id);
  } else if(op.entity_type === 'membership') {
    closed(op.payload, ['list_id', 'paper_id', 'citation', 'added_at']);
    boundedText(op.payload.citation, 4000, true);
    boundedText(op.payload.added_at, 64);
  } else if(op.entity_type === 'paper') {
    closed(
    op.payload,
    ['title', 'authors', 'year', 'venue', 'abstract', 'doi', 'arxiv_id', 's2_id', 'page_url', 'pdf_url',
    'source']
    );
    boundedText(op.payload.title, 2000);
    requireThat(Array.isArray(op.payload.authors) && op.payload.authors.length <= 200);
    op.payload.authors.forEach(a => boundedText(a, 300));
  } else {
    closed(op.payload, op.entity_type === 'list_order' ?['list_id', 'items', 'observed_set']: ['items',
    'observed_set']);
    requireThat(Array.isArray(op.payload.items) && op.payload.items.length <= 2000 && HASH.test(op.payload.observed_set));
    const ids = new Set();
    for(const item of op.payload.items) {
      closed(item, ['id', 'incarnation']);
      identifier(item.id);
      identifier(item.incarnation);
      requireThat(! ids.has(item.id));
      ids.add(item.id);
    }
  }
  return op;
}
export function validateEvent(event, workspace) {
  closed(event, ['sequence', 'outcome', 'operation', 'head']);
  integer(event.sequence);
  requireThat(event.sequence > 0 &&['accepted', 'conflict'].includes(event.outcome));
  validateOperation(event.operation, workspace);
  closed(event.head, ['revision', 'operation']);
  integer(event.head.revision);
  requireThat(event.head.revision <= event.sequence);
  if(event.head.operation !== null) {
    validateOperation(event.head.operation, workspace);
    requireThat(event.head.revision > 0);
    requireThat(keyOf(event.head.operation.entity_type, event.head.operation.entity_id) === keyOf(event.operation.entity_type,
    event.operation.entity_id));
  } else requireThat(event.head.revision === 0);
  if(event.outcome === 'accepted') requireThat(event.head.revision === event.sequence && stable(event.head.operation) === stable(event.operation));
  return event;
}
export function active(state, kind, id, trail = new Set()) {
  const key = keyOf(kind, id),
  graph = state.graph[key];
  if(! graph?.active || trail.has(key)) return false;
  trail = new Set([...trail, key]);
  return graph.parents.every(p => state.graph[keyOf(p.kind, p.id)]?.incarnation === p.incarnation && active(state,
  p.kind, p.id, trail));
}
function applyGraph(state, op, sequence) {
  if(op.version !== 2) return;
  const key = keyOf(op.entity_type, op.entity_id),
  old = state.graph[key];
  state.graph[key] = {
    incarnation: op.incarnation,
    parents: copy(op.parents),
    active: op.action === 'put',
    structure_revision: (! old || old.incarnation !== op.incarnation || op.action === 'delete') ? sequence: old.structure_revision
  };
  for(const p of op.parents) {
    const parent = state.graph[keyOf(p.kind, p.id)];
    if(parent?.active && parent.incarnation === p.incarnation) parent.structure_revision = sequence;
  }
}
function queueContextTransition(state,op,previous) {
  if(op.entity_type!=='research_content' || op.action!=='put' || op.payload.feature!=='queue_entry' ||
      previous.action!=='put' || previous.payload.feature!=='queue_entry' ||
      !active(state,op.entity_type,op.entity_id) || op.incarnation!==op.operation_id ||
      op.incarnation===previous.incarnation || stable(op.parents[0])!==stable(previous.parents[0]))return false;
  const roots=parents=>parents.map(({kind,id})=>({kind,id}));
  if(stable(roots(op.parents))===stable(roots(previous.parents)))return false;
  const origin=own(state.receipts,previous.incarnation),source=origin?.operation;
  if(origin?.outcome!=='accepted' || source?.version!==2 || source.action!=='put' ||
      source.entity_type!==op.entity_type || source.entity_id!==op.entity_id ||
      source.incarnation!==previous.incarnation || source.operation_id!==previous.incarnation ||
      source.payload.feature!=='queue_entry' || source.payload.key!=='main' ||
      source.payload.scope.kind!=='paper' || source.payload.scope.id!==op.payload.scope.id)return false;
  for(const parent of previous.parents)if(!active(state,parent.kind,parent.id) ||
      state.graph[keyOf(parent.kind,parent.id)].incarnation!==parent.incarnation)return false;
  const head=own(state.entities,keyOf(op.entity_type,op.entity_id)),graph=own(state.graph,keyOf(op.entity_type,op.entity_id));
  const dependency=op.depends_on===null?null:own(state.receipts,op.depends_on);
  if(dependency) {
    const before=dependency.operation;
    if(dependency.outcome!=='accepted' || dependency.sequence!==head.revision ||
        before.workspace_id!==op.workspace_id || before.device_id!==op.device_id ||
        before.entity_type!==op.entity_type || before.entity_id!==op.entity_id)return false;
  } else if(op.depends_on!==null || op.base_revision!==head.revision)return false;
  if(!op.structure_depends_on)return op.structure_revision===graph.structure_revision;
  const receipt=own(state.receipts,op.structure_depends_on),before=receipt?.operation;
  if(receipt?.outcome!=='accepted' || receipt.sequence!==graph.structure_revision ||
      before.version!==2 || before.workspace_id!==op.workspace_id || before.device_id!==op.device_id)return false;
  return before.entity_type===op.entity_type && before.entity_id===op.entity_id ?
    before.incarnation===previous.incarnation && (before.action==='delete' || before.incarnation===before.operation_id) :
    before.parents.some(parent=>parent.kind===op.entity_type && parent.id===op.entity_id && parent.incarnation===previous.incarnation);
}
function legacyReceived(state,op) {
  const key=keyOf(op.entity_type,op.entity_id), previous=own(state.entities,key)?.operation;
  const priorPut=op.action==='delete' && previous?.action==='delete' ?
    Object.values(state.receipts).filter(event=>event.outcome==='accepted' &&
      event.operation.entity_type===op.entity_type && event.operation.entity_id===op.entity_id &&
      event.operation.action==='put').sort((a,b)=>b.sequence-a.sequence)[0]?.operation : previous;
  const feature=op.action==='put' ? op.payload?.feature : priorPut?.payload?.feature;
  const content=op.entity_type==='research_content' && ['queue_entry','reading_event'].includes(feature);
  const file=op.entity_type==='research_file' && feature==='legacy_brief';
  if(!content && !file && !queueClosure(op)) return;
  if(op.action==='put') {
    for(const parent of op.parents) requireLegacy(active(state,parent.kind,parent.id) &&
      state.graph[keyOf(parent.kind,parent.id)].incarnation===parent.incarnation,'legacy_parent_unavailable');
  }
  if(!previous) {
    if(op.action==='put') requireLegacy(op.incarnation===op.operation_id,'invalid_legacy_lifecycle');
    return;
  }
  if(queueContextTransition(state,op,previous))return;
  if(op.action==='delete' || op.incarnation===previous.incarnation) {
    requireLegacy(op.incarnation===previous.incarnation && stable(op.parents)===stable(previous.parents),
      'invalid_legacy_lifecycle');
    if(feature==='reading_event' && op.action==='put' && previous.action==='put')
      requireLegacy(op.payload.data.delivered_at===previous.payload.data.delivered_at,'changed_event_identity');
  }
  if(op.action==='put') {
    const live=active(state,op.entity_type,op.entity_id);
    requireLegacy(stable(op.parents.map(({kind,id})=>({kind,id})))===
      stable(previous.parents.map(({kind,id})=>({kind,id}))),'invalid_legacy_lifecycle');
    requireLegacy(live ? op.incarnation===previous.incarnation :
      op.incarnation===op.operation_id && op.incarnation!==previous.incarnation,'invalid_legacy_lifecycle');
  }
}
export function receive(state, events) {
  requireThat(Array.isArray(events) && events.length <= 1000);
  for(const event of events) {
    validateEvent(event, state.workspace);
    const prior = own(state.receipts, event.operation.operation_id);
    if(event.sequence <= state.cursor) {
      requireThat(prior && stable(prior) === stable(event), 'changed_retry');
      continue;
    }
    requireThat(event.sequence === state.cursor + 1, 'event_gap');
    requireThat(! prior || stable(prior) === stable(event), 'changed_retry');
    const op = event.operation,
    local = state.outbox.find(item => item.operation.operation_id === op.operation_id);
    if(local) requireThat(stable(local.operation) === stable(op), 'changed_retry');
    if(event.outcome==='accepted') legacyReceived(state,op);
    put(state.receipts, op.operation_id, copy(event));
    state.outbox = state.outbox.filter(item => item.operation.operation_id !== op.operation_id);
    if(event.outcome === 'accepted') {
      const key = keyOf(op.entity_type, op.entity_id),
      old = state.entities[key];
      state.entities[key] = {
        operation: copy(op),
        revision: event.sequence,
        created: old?.operation.incarnation === op.incarnation ? old.created: event.sequence
      };
      applyGraph(state, op, event.sequence);
      if(op.resolution_of && own(state.conflicts, op.resolution_of)) state.conflicts[op.resolution_of].resolvedBy = op.operation_id;
    } else put(state.conflicts, op.operation_id, {
      event: copy(event),
      resolvedBy: null
    });
    state.cursor = event.sequence;
  }
}
export function optimistic(state) {
  const result = copy(state);
  for(const {
    operation: op
  }
  of state.outbox) {
    const key = keyOf(op.entity_type, op.entity_id);
    result.entities[key] = {
      operation: copy(op),
      revision: state.entities[key]?.revision ?? 0,
      created: state.entities[key]?.created ?? Number.MAX_SAFE_INTEGER
    };
    applyGraph(result, op, 0);
  }
  return result;
}
export function observeNote(state, id, paperId) {
  const view = optimistic(state),
  key = keyOf('note', id),
  row = view.entities[key];
  const pending =[...state.outbox].reverse().find(item => item.operation.entity_type === 'note' && item.operation.entity_id === id);
  return {
    paper_id: paperId,
    paper_incarnation: view.graph[keyOf('paper', paperId)]?.incarnation ?? null,
    note_operation_id: row?.operation.operation_id ?? null,
    note_incarnation: row?.operation.incarnation ?? null,
    action: row?.operation.action ?? null,
    base_revision: state.entities[key]?.revision ?? 0,
    depends_on: pending?.operation.operation_id ?? null
  };
}
export function assertObserved(state, id, paperId, observation) {
  requireThat(observation, 'observation_required');
  const current = observeNote(state, id, paperId);
  // Own acknowledgement changes revision/depends_on, not the content the editor saw.
  for(const key of['paper_id', 'paper_incarnation', 'note_operation_id', 'note_incarnation', 'action']) requireThat(current[key] === observation[key],
  'stale_draft');
}
export function buildOperation(state, kind, id, payload, {
  action = 'put',
  operationId = crypto.randomUUID(),
  resolutionOf = null,
  restore = false
} = {}) {
  requireThat(['note', 'reading_state'].includes(kind), 'unsupported_write');
  identifier(id);
  identifier(operationId);
  const view = optimistic(state),
  key = keyOf(kind, id),
  canonical = state.entities[key],
  prior = view.entities[key],
  graph = view.graph[key];
  if(kind === 'note' && prior?.operation.action === 'put') requireThat(Object.keys(prior.operation.payload).length === 2,
  'rich_note_read_only');
  const conflict = resolutionOf ? own(state.conflicts, resolutionOf): null;
  if(resolutionOf) requireThat(
  conflict && ! conflict.resolvedBy && keyOf(conflict.event.operation.entity_type, conflict.event.operation.entity_id) === key,
  'unknown_conflict'
  );
  let parents;
  if(action === 'delete') {
    requireThat(graph || conflict, 'missing_entity');
    parents = copy(graph?.parents ?? conflict.event.operation.parents);
  } else if(kind === 'note') {
    requireThat(active(view, 'paper', payload.paper_id), 'parent_unavailable');
    parents =[{
      kind: 'paper',
      id: payload.paper_id,
      incarnation: view.graph[keyOf('paper', payload.paper_id)].incarnation
    }];
  } else {
    requireThat(active(view, 'membership', id), 'parent_unavailable');
    const member = view.graph[keyOf('membership', id)];
    parents =[{
      kind: 'membership',
      id,
      incarnation: member.incarnation
    }, ...copy(member.parents)];
    requireThat(
    parents.find(p => p.kind === 'list')?.id === payload.list_id && parents.find(p => p.kind === 'paper')?.id === payload.paper_id,
    'wrong_parent'
    );
  }
  const old = prior?.operation ?? conflict?.event.operation;
  if(old) requireThat(
  stable(old.parents.map(p =>[p.kind, p.id]).sort()) === stable(parents.map(p =>[p.kind, p.id]).sort()),
  'cannot_reparent'
  );
  const live = active(view, kind, id),
  retiring = action === 'delete' && conflict;
  if(prior && ! live && action === 'put') requireThat(restore, 'explicit_restore_required');
  if(action === 'delete' && ! retiring) requireThat(live, 'parent_unavailable');
  const pending =[...state.outbox].reverse().find(item => keyOf(item.operation.entity_type, item.operation.entity_id) === key);
  const op = {
    version: 2,
    operation_id: operationId,
    workspace_id: state.workspace,
    device_id: state.device,
    entity_type: kind,
    entity_id: id,
    action,
    base_revision: canonical?.revision ?? 0,
    depends_on: pending?.operation.operation_id ?? null,
    payload: action === 'delete' ? {}: copy(payload),
    incarnation: (restore || ! old) ? operationId: old.incarnation,
    parents,
    structure_revision: graph?.structure_revision ?? 0
  };
  if(resolutionOf) op.resolution_of = resolutionOf;
  if(action === 'delete') {
    const predecessor =[...state.outbox].reverse().find(item => item.operation.entity_type === kind && item.operation.entity_id === id &&(item.operation.operation_id === op.incarnation || item.operation.action === 'delete'));
    if(predecessor) op.structure_depends_on = predecessor.operation.operation_id;
  }
  validateOperation(op, state.workspace);
  return op;
}
export function enqueue(state, op) {
  validateOperation(op, state.workspace);
  requireThat(op.device_id === state.device, 'wrong_device');
  const existing = state.outbox.find(item => item.operation.operation_id === op.operation_id)?.operation ?? own(state.receipts,
  op.operation_id)?.operation;
  if(existing) {
    requireThat(stable(existing) === stable(op), 'changed_retry');
    return op;
  }
  state.outbox.push({
    operation: copy(op),
    acknowledged: null
  });
  return op;
}
export function statusFor(state, kind, id) {
  const matches = op => op.entity_type === kind && op.entity_id === id;
  if(Object.values(state.conflicts).some(c => ! c.resolvedBy && matches(c.event.operation))) return 'conflict';
  const queued = state.outbox.filter(item => matches(item.operation));
  return queued.length ?(queued.every(item => item.acknowledged) ? 'awaiting': 'pending'): 'synced';
}
export function validateProjection(value, workspace) {
  requireThat(value?.schema_version === 1 || value?.schema_version === 2, 'unsupported_version');
  requireThat(value.workspace_id === workspace, 'wrong_workspace');
  integer(value.cursor);
  for(const name of['lists', 'papers', 'notes', 'highlights', 'decks', 'assets']) requireThat(Array.isArray(value[name]) && value[name].length <= 10000);
  requireThat(utf8(JSON.stringify(value)) <= 8 * 1024 * 1024, 'projection_too_large');
  requireThat(value.capabilities?.sync_bootstrap === false, 'unsupported_bootstrap');
  closed(
  value,
  ['schema_version', 'workspace_id', 'cursor', 'capabilities', 'local_state', 'lists', 'papers', 'notes',
  'highlights', 'decks', 'assets'],
  ['list_order']
  );
  // Copy only read-contract fields. Imported credentials/config/path fields never persist.
  const pick =(row, fields) => Object.fromEntries(fields.filter(field => Object.hasOwn(row, field)).map(field =>[field,
  copy(row[field])]));
  const sections = rows =>(rows ??[]).map(row => pick(row, ['kind', 'body', 'written_at']));
  const result = {
    schema_version: value.schema_version,
    workspace_id: workspace,
    cursor: value.cursor,
    capabilities: {
      sync_bootstrap: false
    },
    local_state: {},
    lists: [],
    papers: [],
    notes: [],
    highlights: [],
    decks: [],
    assets: []
  };
  result.lists = value.lists.map(row =>({
    ...pick(row, ['id', 'name', 'note']),
    members: (row.members ??[]).map(member => {
      if(Object.hasOwn(member,'pinned')) {
        requireThat(typeof member.pinned === 'boolean');
        if(member.pinned) {
          boundedText(member.pinned_at,64);
          requireThat(/(Z|[+-]\d\d:\d\d)$/.test(member.pinned_at) && Number.isFinite(Date.parse(member.pinned_at)));
        } else requireThat(member.pinned_at === null || member.pinned_at === undefined);
      }
      if(Object.hasOwn(member,'pinned_at')) requireThat(Object.hasOwn(member,'pinned'));
      return pick(member, ['id', 'paper_id', 'position', 'state','pinned','pinned_at']);
    }),
    analysis_sections: sections(row.analysis_sections)
  }));
  result.papers = value.papers.map(row =>({
    ...pick(row, ['id', 'title', 'authors', 'year', 'doi', 'url', 'pdf_asset_id']),
    analysis_sections: sections(row.analysis_sections),
    citations: (row.citations ??[]).map(c => pick(c, ['ref_key', 'title', 'doi', 'purpose', 'gist', 'verdict',
    'why', 'basis', 'year']))
  }));
  result.notes = value.notes.map(row =>({
    ...pick(row, ['id', 'paper_id', 'body', 'kind', 'page', 'revision', 'anchor', 'pdf_hash', 'anchor_status']),
    editable: false
  }));
  result.highlights = value.highlights.map(row => pick(row, ['id', 'paper_id', 'origin', 'quote', 'reason',
  'hidden', 'pdf_hash', 'anchor', 'anchor_status']));
  for(const rows of[result.notes, result.highlights]) for(const row of rows) {
    if(row.anchor !== null && row.anchor !== undefined) {
      const a = row.anchor;
      closed(a, ['schema_version', 'kind', 'p0', 'o0', 'p1', 'o1']);
      requireThat(a.schema_version === 1 && a.kind === 'word_range');
      for(const n of['p0', 'o0', 'p1', 'o1']) integer(a[n]);
    }
  }
  return result;
}
export function projection(state) {
  const view = optimistic(state),
  rows = kind => Object.values(view.entities).filter(row => row.operation.entity_type === kind && row.operation.action === 'put' &&(row.operation.version === 1 || active(view,
  kind, row.operation.entity_id))).sort((a, b) => a.created - b.created || a.operation.entity_id.localeCompare(b.operation.entity_id));
  const supplementary = state.readProjection;
  const papers = rows('paper').map(({
    operation: op,
    revision
  }) =>({
    ...(supplementary?.papers.find(p => p.id === op.entity_id) ?? {}),
    ...op.payload,
    id: op.entity_id,
    revision
  }));
  const lists = rows('list').map(({
    operation: op
  }) =>({
    ...op.payload,
    id: op.entity_id,
    members: rows('membership').filter(row => row.operation.payload.list_id === op.entity_id).map(row => {
      const p = row.operation,
      reading = view.entities[keyOf('reading_state', p.entity_id)];
      return {
        id: p.entity_id,
        paper_id: p.payload.paper_id,
        state: active(view, 'reading_state', p.entity_id) ? reading.operation.payload.state: 'pending'
      };
    })
  }));
  const reorder =(items, kind, id) => {
    const order = view.entities[keyOf(kind, id)];
    if(! order || ! active(view, kind, id)) return items;
    const requested = order.operation.payload.items;
    const rank = item => requested.findIndex(ref => ref.id === item.id && view.graph[keyOf(kind === 'list_order' ? 'membership': 'list',
    item.id)]?.incarnation === ref.incarnation);
    return [...items].sort((a, b) =>(rank(a) < 0 ? Infinity: rank(a)) -(rank(b) < 0 ? Infinity: rank(b)));
  };
  lists.forEach(list => {
    list.members = reorder(list.members, 'list_order', list.id);
  });
  const notes = rows('note').map(({
    operation: op
  }) =>({
    ...op.payload,
    id: op.entity_id,
    editable: op.version === 2 && Object.keys(op.payload).length === 2,
    pdf_hash: op.payload.anchor?.document_hash ?? null,
    status: statusFor(state, 'note', op.entity_id)
  }));
  const hasKind = kind => Object.values(view.entities).some(row => row.operation.entity_type === kind);
  const snapshotHighlights = suppressSnapshotContent(
  papers,
  lists,
  Object.values(view.entities),
  Object.values(state.receipts),
  supplementary?.highlights ??[]
  );
  const contentHighlights = projectContent(papers, lists, rows('research_content'));
  return {
    lists: hasKind('list') ? reorder(lists, 'workspace_list_order', 'workspace-lists'): (supplementary?.lists ??[]),
    papers: hasKind('paper') ? papers: (supplementary?.papers ??[]),
    notes: [...notes, ...(supplementary?.notes ??[]).filter(n => ! view.entities[keyOf('note', n.id)]).map(n =>({
      ...n,
      editable: false,
      status: 'local'
    }))],
    highlights: [...contentHighlights, ...snapshotHighlights.live],
    imported_highlights: snapshotHighlights.archived,
    original_sources: rows('research_file').filter(({operation: op}) => op.payload.feature === 'original_source')
      .map(({operation: op}) => ({id:op.entity_id,paper_id:op.payload.paper_id,
        document_hash:op.payload.slot,operation_id:op.operation_id,editable:false})),
    legacy_briefs: rows('research_file').filter(({operation: op}) => op.payload.feature === 'legacy_brief')
      .map(({operation:op})=>({id:op.entity_id,paper_id:op.payload.paper_id,event_id:op.payload.slot,
        operation_id:op.operation_id,editable:false})),
    decks: rows('research_file').filter(({operation: op}) => op.payload.feature === 'deck').map(({operation: op}) => ({id: op.entity_id, paper_id: op.payload.paper_id,
      slot: op.payload.slot, operation_id: op.operation_id, editable: false}))
  };
}
