import test from 'node:test';
import assert from 'node:assert/strict';
import {
  Engine
} from '../engine.mjs';
import {
  MemoryStore
} from '../store.mjs';
import {
  demoTransport,
  PAPER
} from '../fixture.mjs';
import {
  observeNote,
  projection
} from '../domain.mjs';
import {
  ReaderView,
  flushDrafts
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
    engine,
    store,
    transport
  };
}
test(
'workspace switch flushes immediate draft and observation only to old scope',
async() => {
  const {
    store
  } = await setup(),
  view = new ReaderView(),
  other = new MemoryStore('other-workspace', 'other-device');
  view.observed['demo-note'] = observeNote(await store.read(), 'demo-note', PAPER);
  view.edit('demo-note', 'Typed just before switching');
  await flushDrafts(store, view);
  const saved = await store.read();
  assert.equal(saved.drafts['demo-note'], 'Typed just before switching');
  assert.deepEqual(saved.draftBases['demo-note'], view.observed['demo-note']);
  assert.deepEqual((await other.read()).drafts, {});
}
);
test(
'failed workspace-switch flush keeps dirty editor and does not claim persistence',
async() => {
  const {
    store
  } = await setup(),
  view = new ReaderView();
  view.edit('demo-note', 'Do not lose');
  view.observed['demo-note'] = observeNote(await store.read(), 'demo-note', PAPER);
  store.failure = 'storage_write_failed';
  const before = await store.read();
  await assert.rejects(flushDrafts(store, view), /storage_write_failed/);
  assert.equal(view.drafts['demo-note'], 'Do not lose');
  assert.ok(view.dirty.has('demo-note'));
  assert.deepEqual(await store.read(), before);
}
);
async function remoteChange(transport, store) {
  const source =(await store.read()).entities['note/demo-note'];
  const op = {
    ...source.operation,
    operation_id: 'remote-update',
    device_id: 'demo-phone',
    base_revision: source.revision,
    payload: {
      paper_id: PAPER,
      body: 'New remote text'
    }
  };
  await transport.push('fixture-token', op);
}
test(
'remote update during editing never silently rebases stale draft on save or delete',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup(),
  observed = await engine.observeNote('demo-note', PAPER);
  await engine.draft('demo-note', 'My old-base draft', observed);
  await remoteChange(transport, store);
  await engine.sync();
  await assert.rejects(engine.saveNote('demo-note', PAPER, 'My old-base draft', {
    observed
  }), /stale_draft/);
  await assert.rejects(engine.deleteNote('demo-note', {
    observed
  }), /stale_draft/);
  const state = await store.read();
  assert.equal(state.drafts['demo-note'], 'My old-base draft');
  assert.equal(state.outbox.length, 0);
  assert.equal(projection(state).notes.find(n => n.id === 'demo-note').body, 'New remote text');
  assert.deepEqual(state.draftBases['demo-note'], observed);
}
);
test(
'draft observation survives reload and remains stale after remote update',
async() => {
  const {
    engine,
    store,
    transport
  } = await setup(),
  observed = await engine.observeNote('demo-note', PAPER);
  await engine.draft('demo-note', 'Retain after reload', observed);
  await remoteChange(transport, store);
  await engine.sync();
  const reopened = new MemoryStore('demo-workspace', 'demo-phone', await store.read()),
  reader = new Engine(reopened, {
    transport
  });
  await assert.rejects(reader.saveNote('demo-note', PAPER, 'Retain after reload'), /stale_draft/);
  assert.equal((await reader.exportLocal()).draftBases['demo-note'].note_operation_id, observed.note_operation_id);
}
);
test(
'existing-note edits require explicit observation; acknowledgement alone does not stale it',
async() => {
  const {
    engine,
    store
  } = await setup();
  await assert.rejects(engine.saveNote('demo-note', PAPER, 'Blind update'), /observation_required/);
  await assert.rejects(engine.deleteNote('demo-note'), /observation_required/);
  const first = await engine.observeNote('demo-note', PAPER);
  await engine.saveNote('demo-note', PAPER, 'First local change', {
    observed: first
  });
  const next = await engine.observeNote('demo-note', PAPER);
  await engine.draft('demo-note', 'Second local change', next);
  await engine.sync();
  await engine.saveNote('demo-note', PAPER, 'Second local change', {
    observed: next
  });
  assert.equal((await store.read()).outbox.length, 1);
}
);
test(
'bounded foreground push and pull passes report remaining work rather than synced',
async() => {
  const {
    engine,
    store
  } = await setup(),
  announcements =[];
  engine.onChange = message => announcements.push(message);
  for(let i = 0; i < 101; i++) await engine.saveNote('bulk-' + i, PAPER, 'Fixture ' + i);
  await engine.sync();
  assert.equal(announcements.at(- 1), 'more_pending');
  assert.ok((await store.read()).outbox.length > 0);
  await engine.sync();
  assert.equal(announcements.at(- 1), 'synced');
  assert.equal((await store.read()).outbox.length, 0);
}
);
