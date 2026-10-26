import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MemoryStore,
  emptyState,
  scopeKey
} from '../store.mjs';
import {
  Engine
} from '../engine.mjs';
import {
  active,
  buildOperation,
  enqueue,
  keyOf,
  projection,
  receive,
  stable,
  statusFor,
  validateOperation
} from '../domain.mjs';
import {
  demoTransport,
  demoProjection,
  FixtureTransport,
  PAPER,
  MEMBER,
  operation,
  ref
} from '../fixture.mjs';
import {
  ReaderView,
  safeLink
} from '../view.mjs';
async function setup() {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'demo-phone'),
  engine = new Engine(store, {
    transport
  });
  await engine.connect('fixture-token');
  await engine.sync();
  return {
    transport,
    store,
    engine
  };
}
test(
'closed v2 note writes, stable retry ID and causal offline chains',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup();
  const first = await saveCurrent(engine, 'mine', PAPER, 'First', {
    operationId: 'edit-1'
  });
  const second = await saveCurrent(engine, 'mine', PAPER, 'Second', {
    operationId: 'edit-2'
  });
  assert.equal(second.depends_on, first.operation_id);
  assert.equal(second.incarnation, first.incarnation);
  assert.deepEqual(second.parents, [ref('paper', PAPER)]);
  await engine.sync();
  const state = await store.read();
  assert.equal(state.outbox.length, 0);
  assert.equal(projection(state).notes.find(n => n.id === 'mine').body, 'Second');
  assert.equal(transport.events.length, 8);
}
);
test(
'lost push response retries identical operation, without duplicate note or event',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup();
  await saveCurrent(engine, 'mine', PAPER, 'Retain me', {
    operationId: 'lost'
  });
  transport.loseResponse = true;
  await assert.rejects(engine.sync(), /connection_failed/);
  assert.equal((await store.read()).outbox.length, 1);
  await engine.sync();
  assert.equal(transport.events.length, 7);
  assert.equal((await store.read()).outbox.length, 0);
  assert.equal(transport.calls.filter(c => c[0] === 'push' && c[1] === 'lost').length, 2);
}
);
test(
'same content repeated save creates only one pending operation',
async() => {
  const {
    engine,
    store
  } = await setup();
  await Promise.all([saveCurrent(engine, 'mine', PAPER, 'Same'), saveCurrent(engine, 'mine', PAPER, 'Same')]);
  assert.equal((await store.read()).outbox.length, 1);
}
);
test(
'delete after an offline ordinary edit retains lifecycle marker, not metadata revision',
async() => {
  const {
    engine,
    store
  } = await setup();
  const before =(await store.read()).graph['note/demo-note'].structure_revision;
  await saveCurrent(engine, 'demo-note', PAPER, 'Editing before delete');
  const op = await deleteCurrent(engine, 'demo-note');
  assert.equal(op.structure_revision, before);
  assert.equal(Object.hasOwn(op, 'structure_depends_on'), false);
  await engine.sync();
  assert.equal((await store.read()).entities['note/demo-note'].operation.action, 'delete');
}
);
test(
'delete after offline creation depends on its lifecycle receipt',
async() => {
  const {
    engine,
    store
  } = await setup();
  const create = await saveCurrent(engine, 'new-note', PAPER, 'New');
  const remove = await deleteCurrent(engine, 'new-note');
  assert.equal(remove.structure_depends_on, create.operation_id);
  await engine.sync();
  assert.equal((await store.read()).entities['note/new-note'].operation.action, 'delete');
}
);
test(
'local note plus outbox rollback on quota failure and survive store reload',
async() => {
  const {
    engine,
    store
  } = await setup();
  store.failure = 'storage_write_failed';
  const before = await store.read();
  await assert.rejects(saveCurrent(engine, 'mine', PAPER, 'Unsaved'), /storage/);
  assert.deepEqual(await store.read(), before);
  store.failure = null;
  await engine.draft('mine', 'Draft');
  await saveCurrent(engine, 'mine', PAPER, 'Durable');
  const loaded = new MemoryStore('demo-workspace', 'demo-phone', await store.read());
  assert.equal(projection(await loaded.read()).notes.find(n => n.id === 'mine').body, 'Durable');
  assert.equal((await loaded.read()).outbox.length, 1);
  assert.equal((await loaded.read()).drafts.mine, undefined);
}
);
test(
'wrong retry content and unknown envelope versions rejected',
async() => {
  const {
    store
  } = await setup();
  await store.update(state => {
    const op = buildOperation(
    state,
    'note',
    'mine',
    {
      paper_id: PAPER,
      body: 'A'
    },
    {
      operationId: 'same'
    }
    );
    enqueue(state, op);
    assert.throws(
    () => enqueue(state, {
      ...op,
      payload: {
        ...op.payload,
        body: 'B'
      }
    }),
    /changed_retry/
    );
    assert.throws(() => validateOperation({
      ...op,
      version: 3
    }, state.workspace), /unsupported_version/);
    assert.throws(() => validateOperation({
      ...op,
      token: 'secret'
    }, state.workspace));
  });
}
);
test(
'contiguous receipt cursor atomicity, duplicate delivery, changed and reordered events',
async() => {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'phone');
  await assert.rejects(store.update(state => receive(state, [transport.events[1]])), /event_gap/);
  assert.equal((await store.read()).cursor, 0);
  await store.update(state => receive(state, transport.events));
  const before = await store.read();
  await store.update(state => receive(state, transport.events));
  assert.deepEqual(await store.read(), before);
  const changed = structuredClone(transport.events[0]);
  changed.operation.payload.name = 'Changed';
  changed.head.operation = changed.operation;
  await assert.rejects(store.update(state => receive(state, [changed])), /changed_retry/);
  assert.deepEqual(await store.read(), before);
}
);
test(
'wrong workspace delivery rolls back entire batch',
async() => {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'phone');
  const events = structuredClone(transport.events);
  events[1].operation.workspace_id = 'elsewhere';
  await assert.rejects(store.update(state => receive(state, events)), /wrong_workspace/);
  assert.equal((await store.read()).cursor, 0);
  assert.deepEqual((await store.read()).entities, {});
}
);
test(
'future entity kinds stop before advancing or discarding canonical history',
async() => {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'phone');
  const event = structuredClone(transport.events[0]);
  event.operation.entity_type = 'future_research_format';
  event.head.operation = event.operation;
  await assert.rejects(store.update(state => receive(state, [event])), /unsupported_operation/);
  assert.equal((await store.read()).cursor, 0);
  assert.deepEqual((await store.read()).receipts, {});
}
);
test(
'valid identifier strings cannot mutate record prototypes',
async() => {
  const {
    store
  } = await setup();
  await store.update(state => {
    const op = buildOperation(
    state,
    'note',
    '__proto__',
    {
      paper_id: PAPER,
      body: 'Literal identity'
    },
    {
      operationId: '__proto__'
    }
    );
    enqueue(state, op);
    const event = {
      sequence: 7,
      outcome: 'accepted',
      operation: op,
      head: {
        revision: 7,
        operation: op
      }
    };
    receive(state, [event]);
    assert.equal(Object.getPrototypeOf(state.receipts), Object.prototype);
    assert.equal(state.receipts.__proto__.operation.operation_id, '__proto__');
  });
}
);
test(
'pending and acknowledged-but-unreceived notes protect local content',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup();
  await saveCurrent(engine, 'demo-note', PAPER, 'Local edit', {
    operationId: 'ack'
  });
  const originalPull = transport.pull.bind(transport);
  transport.pull = async() =>[];
  await engine.sync();
  let state = await store.read();
  assert.equal(statusFor(state, 'note', 'demo-note'), 'awaiting');
  assert.equal(projection(state).notes.find(n => n.id === 'demo-note').body, 'Local edit');
  const next = await saveCurrent(engine, 'demo-note', PAPER, 'Another edit', {
    operationId: 'after-ack'
  });
  assert.equal(next.depends_on, 'ack');
  transport.pull = originalPull;
  await engine.sync();
  state = await store.read();
  assert.equal(statusFor(state, 'note', 'demo-note'), 'synced');
  assert.equal(projection(state).notes.find(n => n.id === 'demo-note').body, 'Another edit');
}
);
test(
'edit/edit conflicts keep both versions; only explicit accepted resolution closes them',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup();
  await saveCurrent(engine, 'demo-note', PAPER, 'Local branch', {
    operationId: 'local'
  });
  const peer = structuredClone((await store.read()).entities['note/demo-note'].operation);
  peer.operation_id = 'peer';
  peer.device_id = 'demo-phone';
  peer.base_revision = 5;
  peer.payload.body = 'Other device';
  await transport.push('fixture-token', peer);
  await engine.sync();
  let state = await store.read();
  assert.equal(state.conflicts.local.event.operation.payload.body, 'Local branch');
  assert.equal(state.conflicts.local.event.head.operation.payload.body, 'Other device');
  assert.equal(statusFor(state, 'note', 'demo-note'), 'conflict');
  await engine.resolve('local', {
    body: 'Reconciled'
  });
  assert.equal((await store.read()).conflicts.local.resolvedBy, null);
  await engine.sync();
  state = await store.read();
  assert.ok(state.conflicts.local.resolvedBy);
  assert.equal(projection(state).notes.find(n => n.id === 'demo-note').body, 'Reconciled');
}
);
test(
'edit/delete conflict requires explicit restore and retains original tombstone',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup();
  await saveCurrent(engine, 'demo-note', PAPER, 'Keep history', {
    operationId: 'offline'
  });
  const base = await store.read(),
  deleted = buildOperation(
  {
    ...base,
    outbox: []
  },
  'note',
  'demo-note',
  {},
  {
    action: 'delete',
    operationId: 'deleted'
  }
  );
  await transport.push('fixture-token', deleted);
  await engine.sync();
  await assert.rejects(engine.resolve('offline'), /explicit_restore/);
  await engine.resolve('offline', {
    restore: true
  });
  await engine.sync();
  const state = await store.read();
  assert.equal(state.receipts.deleted.operation.action, 'delete');
  assert.equal(projection(state).notes.find(n => n.id === 'demo-note').body, 'Keep history');
  assert.ok(state.conflicts.offline.resolvedBy);
}
);
test(
'late root rename and membership lifecycle do not resurrect obsolete children',
async() => {
  const {
    store
  } = await setup();
  await store.update(state => {
    const root = state.entities['list/demo-list'].operation;
    const removed = {
      ...root,
      action: 'delete',
      payload: {},
      operation_id: 'remove',
      base_revision: 1,
      structure_revision: state.graph['list/demo-list'].structure_revision
    };
    receive(
    state,
    [{
      sequence: 7,
      outcome: 'accepted',
      operation: removed,
      head: {
        revision: 7,
        operation: removed
      }
    }]
    );
    assert.equal(active(state, 'membership', MEMBER), false);
    const restored = {
      ...root,
      operation_id: 'restore',
      incarnation: 'restore',
      base_revision: 7
    };
    receive(
    state,
    [{
      sequence: 8,
      outcome: 'accepted',
      operation: restored,
      head: {
        revision: 8,
        operation: restored
      }
    }]
    );
    assert.equal(projection(state).lists[0].members.length, 0);
  });
}
);
test(
'reading state uses exact membership closure and records per-list state',
async() => {
  const {
    engine,
    store
  } = await setup();
  await engine.reading(MEMBER, 'demo-list', PAPER, 'read');
  const state = await store.read(),
  op = state.outbox[0].operation;
  assert.equal(op.entity_type, 'reading_state');
  assert.equal(op.parents.length, 3);
  assert.ok(op.payload.read_at);
  assert.equal(projection(state).lists[0].members[0].state, 'read');
  await assert.rejects(engine.reading(MEMBER, 'wrong-list', PAPER, 'pending'), /wrong_parent/);
}
);
test(
'DTO2 and DTO1 imports stay read-only and never grant cursor/bootstrap authority',
async() => {
  const store = new MemoryStore('demo-workspace', 'phone'),
  engine = new Engine(store);
  await engine.importProjection(demoProjection);
  assert.equal((await store.read()).cursor, 0);
  await assert.rejects(saveCurrent(engine, 'mine', PAPER, 'No parent'), /parent_unavailable/);
  await engine.importProjection({
    ...demoProjection,
    schema_version: 1
  });
  assert.equal((await store.read()).cursor, 0);
  await assert.rejects(engine.importProjection({
    ...demoProjection,
    schema_version: 3
  }), /unsupported_version/);
  await assert.rejects(
  engine.importProjection({
    ...demoProjection,
    capabilities: {
      sync_bootstrap: true
    }
  }),
  /unsupported_bootstrap/
  );
}
);
test(
'imported content cannot revive a deleted canonical note or list',
async() => {
  const {
    engine,
    store
  } = await setup();
  await engine.importProjection({
    ...demoProjection,
    lists: [{
      id: 'demo-list',
      name: 'Old copy',
      members: []
    }],
    notes: [{
      id: 'demo-note',
      paper_id: PAPER,
      body: 'Old note'
    }]
  });
  await deleteCurrent(engine, 'demo-note');
  assert.equal(projection(await store.read()).notes.length, 0);
}
);
test(
'reader selection, drafts and scroll remain stable during incoming refresh',
() => {
  const view = new ReaderView();
  view.select('chosen', 'paper');
  view.note = 'note';
  view.edit('note', 'Unsaved');
  view.scroll.paper = 420;
  view.refresh({
    selection: {
      list: 'other',
      paper: 'other'
    },
    drafts: {
      note: 'Older disk'
    }
  });
  assert.equal(view.paper, 'paper');
  assert.equal(view.note, 'note');
  assert.equal(view.drafts.note, 'Unsaved');
  assert.equal(view.scroll.paper, 420);
  view.saved('note', 'Older disk');
  assert.ok(view.dirty.has('note'));
}
);
test(
'scope keys cannot collide and external metadata cannot become unsafe hyperlinks',
() => {
  assert.notEqual(scopeKey('a:b', 'c'), scopeKey('a', 'b:c'));
  assert.equal(safeLink('javascript:alert(1)'), null);
  assert.equal(safeLink('https://user:secret@example.org'), null);
  assert.equal(safeLink('https://example.org/paper'), 'https://example.org/paper');
}
);
async function saveCurrent(engine, id, paperId, body, options = {}) {
  return engine.saveNote(id, paperId, body, {
    observed: await engine.observeNote(id, paperId),
    ...options
  });
}
async function deleteCurrent(engine, id, options = {}) {
  const state = await engine.store.read();
  const row = state.entities['note/' + id]?.operation;
  const pending =[...state.outbox].reverse().find(item => item.operation.entity_type === 'note' && item.operation.entity_id === id)?.operation;
  const source = pending ?? row;
  const paper = source?.payload.paper_id ?? source?.parents.find(parent => parent.kind === 'paper')?.id;
  return engine.deleteNote(id, {
    observed: await engine.observeNote(id, paper),
    ...options
  });
}
