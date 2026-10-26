import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MemoryStore
} from '../store.mjs';
import {
  Engine,
  documentTarget,
  sha256
} from '../engine.mjs';
import {
  demoTransport,
  PAPER
} from '../fixture.mjs';
import {
  receive
} from '../domain.mjs';
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
const deferred =() => {
  let resolve;
  const promise = new Promise(r => resolve = r);
  return {
    promise,
    resolve
  };
};
test(
'repeated sync activation shares a single job',
async() => {
  const {
    engine,
    transport
  } = await setup(),
  gate = deferred(),
  original = transport.session_info.bind(transport);
  let calls = 0;
  transport.session_info = async(...args) => {
    calls++;
    await gate.promise;
    return original(...args);
  };
  const a = engine.sync(),
  b = engine.sync();
  assert.equal(a, b);
  gate.resolve();
  await a;
  assert.equal(calls, 1);
}
);
test(
'session identity mismatch prevents push, pull and blob requests',
async() => {
  const {
    engine,
    transport
  } = await setup();
  transport.device = 'other-device';
  await assert.rejects(engine.connect('fixture-token'), /wrong_session/);
  const before = transport.calls.length;
  await assert.rejects(engine.sync(), /not_connected/);
  await assert.rejects(engine.download(PAPER), /not_connected/);
  assert.equal(transport.calls.length, before);
}
);
test(
'revoked sessions fail even after a successful prior handshake',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  await saveCurrent(engine, 'mine', PAPER, 'Private');
  transport.revoked = true;
  await assert.rejects(engine.sync(), /session_denied/);
  assert.equal((await store.read()).outbox.length, 1);
  await assert.rejects(engine.download(PAPER), /session_denied/);
}
);
test(
'sign-out during a request discards late response, preserving local outbox',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  await saveCurrent(engine, 'mine', PAPER, 'Private', {
    operationId: 'late'
  });
  const gate = deferred(),
  original = transport.push.bind(transport);
  transport.push = async(...args) => {
    const result = await original(...args);
    await gate.promise;
    return result;
  };
  const pending = engine.sync();
  while(! transport.state.receipts.late) await new Promise(r => setTimeout(r, 0));
  engine.disconnect();
  gate.resolve();
  await assert.rejects(pending, /cancelled/);
  const state = await store.read();
  assert.equal(state.cursor, 6);
  assert.equal(state.outbox.length, 1);
  assert.equal(state.outbox[0].acknowledged, null);
  await engine.connect('fixture-token');
  await engine.sync();
  assert.equal((await store.read()).cursor, 7);
}
);
test(
'download deduplication, full verification, reopen verification and no automatic download',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  assert.equal(transport.calls.filter(c => c[0] === 'blob').length, 0);
  const first = engine.download(PAPER),
  second = engine.download(PAPER);
  assert.equal(first, second);
  const hash = await first;
  const file = await engine.pdf(PAPER);
  assert.equal(await sha256(file.bytes), hash);
  assert.equal((await store.read()).files[hash].verified, true);
  await store.update(state => {
    state.files[hash].chunks[0][0] = 0;
  });
  await assert.rejects(engine.pdf(PAPER), /corrupt_file/);
}
);
test(
'corrupt bytes never become available or anchor-eligible; explicit retry repairs them',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  const original = transport.blob_read.bind(transport);
  transport.blob_read = async(...args) => {
    const bytes = await original(...args);
    bytes[10] ^= 1;
    return bytes;
  };
  await assert.rejects(engine.download(PAPER), /corrupt_file/);
  const state = await store.read(),
  hash = documentTarget(state, PAPER).payload.sha256;
  assert.equal(state.files[hash].verified, false);
  await assert.rejects(engine.pdf(PAPER), /file_unavailable/);
  transport.blob_read = original;
  await engine.download(PAPER);
  assert.equal((await engine.pdf(PAPER)).sha256, hash);
}
);
test(
'metadata cursor and notes advance while PDF bytes are absent',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  transport.blobs.clear();
  await assert.rejects(engine.download(PAPER), /file_unavailable/);
  await saveCurrent(engine, 'mine', PAPER, 'Readable without a PDF');
  await engine.sync();
  assert.equal((await store.read()).cursor, 7);
  assert.deepEqual((await store.read()).files, {});
}
);
test(
'document replacement during download prevents stale publication',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  const original = transport.blob_read.bind(transport);
  transport.blob_read = async(...args) => {
    const bytes = await original(...args);
    await store.update(state => {
      const previous = documentTarget(state, PAPER);
      const op = {
        ...previous,
        operation_id: 'replacement',
        payload: {
          ...previous.payload,
          sha256: 'a'.repeat(64)
        }
      };
      receive(
      state,
      [{
        sequence: 7,
        outcome: 'accepted',
        operation: op,
        head: {
          revision: 7,
          operation: op
        }
      }]
      );
    });
    return bytes;
  };
  await assert.rejects(engine.download(PAPER), /stale_document/);
  assert.deepEqual((await store.read()).files, {});
}
);
test(
'sign-out during PDF transfer cannot publish bytes under another session',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup(),
  gate = deferred(),
  entered = deferred(),
  original = transport.blob_read.bind(transport);
  transport.blob_read = async(...args) => {
    const bytes = await original(...args);
    entered.resolve();
    await gate.promise;
    return bytes;
  };
  const pending = engine.download(PAPER);
  await entered.promise;
  engine.disconnect();
  gate.resolve();
  await assert.rejects(pending, /cancelled/);
  assert.deepEqual((await store.read()).files, {});
}
);
test(
'persisted transfer state resumes from complete verified-length chunks',
async() => {
  const {
    engine,
    transport,
    store
  } = await setup();
  const target = documentTarget(await store.read(), PAPER),
  bytes = transport.blobs.get(target.payload.sha256);
  await store.update(state => {
    state.files[target.payload.sha256] = {
      size: bytes.length,
      chunks: [bytes.slice(0, 100)],
      verified: false
    };
  });
  await engine.download(PAPER);
  assert.equal(transport.calls.find(c => c[0] === 'blob')[2], 100);
  assert.equal((await engine.pdf(PAPER)).bytes.length, bytes.length);
}
);
test(
'local export has no credential or file bytes and retains conflict/draft/outbox work',
async() => {
  const {
    engine,
    store
  } = await setup();
  await engine.draft('unsaved', 'Need to retain');
  await saveCurrent(engine, 'mine', PAPER, 'Pending');
  await engine.download(PAPER);
  const result = await engine.exportLocal();
  assert.equal(result.drafts.unsaved, 'Need to retain');
  assert.equal(result.outbox.length, 1);
  assert.equal(JSON.stringify(result).includes('fixture-token'), false);
  assert.equal(Object.hasOwn(result, 'files'), false);
  assert.ok((await store.read()).files);
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
