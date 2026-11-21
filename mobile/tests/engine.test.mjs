import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MemoryStore
} from '../store.mjs';
import {
  Engine,
  documentTarget, hasLocalPdf,
  sha256,historySeed,historyStep
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
test('a saved original cannot mark its replacement as available offline', async () => {
  const {engine, store} = await setup();
  await engine.download(PAPER);
  const state = await store.read();
  assert.equal(hasLocalPdf(state, PAPER), true);
  const previous = documentTarget(state, PAPER);
  const replacement = {...previous, operation_id:'new-original',
    payload:{...previous.payload, sha256:'a'.repeat(64)}};
  receive(state, [{sequence:7, outcome:'accepted', operation:replacement,
    head:{revision:7, operation:replacement}}]);
  assert.equal(state.files[previous.payload.sha256].verified, true);
  assert.equal(hasLocalPdf(state, PAPER), false);
});
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
  assert.equal(result.version,3);
  assert.equal(result.archives[0].drafts.unsaved, 'Need to retain');
  assert.equal(result.archives[0].outbox.length, 1);
  assert.deepEqual(result.archives[0].history,(await store.read()).history);
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

test('retained history is verified before mobile upload and preserves offline work on failure',async()=>{
  for(const checkpoint of ['received','acknowledged']) for(const mode of ['missing','different','matching']) {
    const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
    const engine=new Engine(store,{transport});
    await engine.connect('fixture-token');await engine.sync();
    if(checkpoint==='acknowledged') {
      await saveCurrent(engine,'acknowledged-note',PAPER,'Accepted before disconnection');
      const cursor=(await store.read()).cursor,pull=transport.pull.bind(transport);
      transport.pull=async(...args)=>{
        if(args[1]===cursor && (await store.read()).outbox.some(item=>item.acknowledged))
          throw new Error('Disconnected after acknowledgment');
        return pull(...args);
      };
      await assert.rejects(engine.sync(),/Disconnected after acknowledgment/);
      transport.pull=pull;
      assert.equal((await store.read()).cursor,cursor);
      assert((await store.read()).outbox.some(item=>item.acknowledged));
    }
    await engine.saveNote('offline-note',PAPER,'Keep my offline research',{
      observed:await engine.observeNote('offline-note',PAPER),
    });
    const before=await store.read(),pull=transport.pull.bind(transport),checks=[];
    const sequence=Math.max(before.cursor,...before.outbox.map(item=>item.acknowledged?.sequence??0));
    const probes=before.cursor?[[before.cursor-1,1]]:[];
    if(sequence>before.cursor)probes.push([sequence-1,1]);
    transport.calls.length=0;
    transport.pull=async(...args)=>{
      checks.push([args[1],args[2]]);
      const events=await pull(...args);
      if(mode==='missing')return [];
      if(mode==='different' && args[1]===sequence-1){
        events[0].operation.device_id='different-author';
        if(events[0].outcome==='accepted')events[0].head.operation=structuredClone(events[0].operation);
      }
      return events;
    };
    if(mode==='matching') {
      await engine.sync();
      assert.equal((await store.read()).outbox.length,0);
      assert.deepEqual(checks.slice(0,probes.length),probes);
      assert.equal(transport.calls[0][0],'pull');
    } else {
      for(let repeat=0;repeat<2;repeat++) {
        await assert.rejects(engine.sync(),/sync_history_unavailable/);
        assert.deepEqual(await store.read(),before);
      }
      assert(!transport.calls.some(call=>call[0]==='push'));
      const expected=mode==='missing'?probes.slice(0,1):probes;
      assert.deepEqual(checks,[...expected,...expected]);
    }
  }
});


test('verified mobile history rejects a different prefix with an identical final event before upload',async()=>{
  const {engine,store,transport}=await setup();
  await saveCurrent(engine,'private-pending',PAPER,'Keep offline research');
  const before=await store.read(),original=structuredClone(transport.events[0]);
  const last=structuredClone(transport.events.at(-1));
  transport.events[0].operation.payload.name='A different retained past';
  transport.events[0].head.operation=structuredClone(transport.events[0].operation);
  assert.deepEqual(transport.events.at(-1),last);
  transport.calls.length=0;
  for(let repeat=0;repeat<2;repeat++) {
    await assert.rejects(engine.sync(),/sync_history_unavailable/);
    assert.deepEqual(await store.read(),before);
  }
  assert(!transport.calls.some(call=>call[0]==='push'));
  transport.events[0]=original;
  await engine.sync();
  const state=await store.read();
  assert.equal(state.outbox.length,0);
  assert.equal(state.history.received.sequence,state.cursor);
  assert.equal(state.entities['note/private-pending'].operation.payload.body,'Keep offline research');
});

test('forged push proof never acknowledges locally; restart repairs a lost reply without reupload',async()=>{
  const {engine,store,transport}=await setup();
  await saveCurrent(engine,'proof-note',PAPER,'Retain accepted content',{operationId:'proof-write'});
  const push=transport.push_verified.bind(transport),before=await store.read();
  transport.push_verified=async(...args)=>{
    const reply=await push(...args);reply.checkpoint.sha256='0'.repeat(64);return reply;
  };
  await assert.rejects(engine.sync(),/sync_history_unavailable/);
  assert.deepEqual(await store.read(),before);
  transport.push_verified=push;
  const restarted=new Engine(new MemoryStore(before.workspace,before.device,await store.read()),{transport});
  await restarted.connect('fixture-token');await restarted.sync();
  const final=await restarted.store.read();
  assert.equal(final.outbox.length,0);
  assert.equal(final.entities['note/proof-note'].operation.payload.body,'Retain accepted content');
  assert.equal(transport.calls.filter(call=>call[0]==='push' && call[1]==='proof-write').length,1);
  assert.deepEqual(final.history.received,(await transport.historySnapshot()).points.at(-1));
});

test('verified receive commits content cursor and proof together and refuses stale delivery',async()=>{
  const {engine,store,transport}=await setup();
  await saveCurrent(engine,'atomic-note',PAPER,'Do not lose accepted content',{operationId:'atomic-write'});
  const update=store.update.bind(store),before=await store.read();
  store.update=change=>update(state=>{
    const result=change(state);
    if(state.history.acknowledged.sequence>before.history.acknowledged.sequence)
      throw Error('synthetic_proof_storage_failure');
    return result;
  });
  await assert.rejects(engine.sync(),/synthetic_proof_storage_failure/);
  assert.deepEqual(await store.read(),before);
  store.update=change=>update(state=>{
    const result=change(state);
    if(state.cursor>before.cursor)throw Error('synthetic_receive_storage_failure');
    return result;
  });
  await assert.rejects(engine.sync(),/synthetic_receive_storage_failure/);
  assert.deepEqual(await store.read(),before);
  store.update=update;
  const history=transport.history_page.bind(transport),gate=deferred(),entered=deferred();
  transport.history_page=async(...args)=>{const page=await history(...args);entered.resolve();await gate.promise;return page;};
  const pending=engine.sync();await entered.promise;engine.disconnect();gate.resolve();
  await assert.rejects(pending,/cancelled/);assert.deepEqual(await store.read(),before);
  transport.history_page=history;
  await engine.connect('fixture-token');await engine.sync();
  const final=await store.read();
  assert.equal(final.outbox.length,0);assert.equal(final.cursor,final.history.received.sequence);
  assert.equal(final.entities['note/atomic-note'].operation.payload.body,'Do not lose accepted content');
});

test('legacy mobile inbox proves actual retained records and an old service cannot downgrade writes',async()=>{
  const {engine,store,transport}=await setup(),expected=(await store.read()).history.received;
  await store.update(state=>{delete state.history;});
  await engine.sync();assert.deepEqual((await store.read()).history.received,expected);
  await store.update(state=>{delete state.history;});
  const legacy=await store.read(),first=structuredClone(transport.events[0]);
  transport.events[0].operation.payload.name='Changed old history';
  transport.events[0].head.operation=structuredClone(transport.events[0].operation);
  await assert.rejects(engine.sync(),/sync_history_unavailable/);
  assert.deepEqual(await store.read(),legacy);
  transport.events[0]=first;await engine.sync();
  await saveCurrent(engine,'unsupported-note',PAPER,'Keep pending');
  const before=await store.read();transport.history_page=null;
  await assert.rejects(engine.sync(),/sync_history_unavailable/);
  assert.deepEqual(await store.read(),before);
  assert(!transport.calls.some(call=>call[0]==='push' && call[1]===before.outbox[0].operation.operation_id));
});


test('disconnect during a local read cannot send a later request with another session',async()=>{
  const {engine,store,transport}=await setup();
  await saveCurrent(engine,'held-local',PAPER,'Retain local intent');
  const before=await store.read(),read=store.read.bind(store),gate=deferred(),entered=deferred();
  let count=0;
  store.read=async()=>{const value=await read();if(++count===2){entered.resolve();await gate.promise;}return value;};
  transport.calls.length=0;
  const pending=engine.sync();await entered.promise;engine.disconnect();gate.resolve();
  await assert.rejects(pending,/cancelled/);
  assert.equal(transport.calls.length,0);assert.deepEqual(await read(),before);
});


test('mobile history matches native exact UTF-8 float and Unicode commitments',async()=>{
  const seed=await historySeed('history-vector');
  assert.equal(seed,'50e81e1dfc4adc065f8b1cd406567d157d1eb7fc9bc821db67331fcb324df643');
  const record='{"float":200.0,"negative":-0.0,"unicode":"\u{1f600}"}';
  assert.equal(await historyStep(seed,record),'164404784c52470482a1760d499915c6ce3d92b3799269fb1232868220205406');
  assert.notEqual(await historyStep(seed,JSON.stringify(JSON.parse(record))),await historyStep(seed,record));
});


for(const future of ['envelope','entity','content']) for(const damaged of [false,'checkpoint','sequence']) {
  test(`unreadable ${future} history preserves offline work; damaged proof=${damaged}`,async()=>{
    const {engine,store,transport}=await setup();
    await saveCurrent(engine,'local-format-note',PAPER,'Private offline reading note');
    const before=await store.read(),last=structuredClone(transport.events.find(e=>e.operation.entity_type==='note'));
    const operation=last.operation;
    operation.operation_id='unreadable-remote';operation.entity_id='unreadable-note';
    operation.base_revision=0;operation.depends_on=null;operation.incarnation='unreadable-epoch';
    if(future==='envelope')operation.version=3;
    if(future==='entity')operation.entity_type='future_research';
    if(future==='content') {
      operation.entity_type='research_content';operation.entity_id='00000000-0000-4000-8000-000000000001';
      operation.payload={scope:{kind:'paper',id:PAPER},feature:'future_annotation',key:'main',
        data:{private:'Do not display research in errors'},source_document_hash:null};
    }
    last.sequence=transport.events.length+1;
    if(damaged==='sequence')last.sequence+=2;
    last.head={revision:last.sequence,operation:structuredClone(operation)};
    transport.events.push(last);
    const original=transport.history_page.bind(transport);
    if(damaged==='checkpoint')transport.history_page=async(...args)=>{
      const page=await original(...args);
      if(page.events.some(raw=>JSON.parse(raw).operation.operation_id==='unreadable-remote'))
        page.checkpoint.sha256='0'.repeat(64);
      return page;
    };
    transport.calls.length=0;
    await assert.rejects(engine.sync(),new RegExp(damaged?'sync_history_unavailable':'sync_format_unsupported'));
    assert.deepEqual(await store.read(),before);
    assert(!transport.calls.some(call=>call[0]==='push'));
    const {translator}=await import('../i18n.mjs');
    assert.match(translator('en')('sync_format_unsupported'),/unsupported research format/);
    assert.match(translator('zh-TW')('sync_format_unsupported'),/\u683c\u5f0f/);
    assert(!translator('en')('sync_format_unsupported').includes('Private offline'));
    transport.events.pop();transport.history_page=original;
    await engine.sync();
    const after=await store.read();
    assert.equal(after.outbox.length,0);
    assert.equal(after.entities['note/local-format-note'].operation.payload.body,'Private offline reading note');
  });
}
