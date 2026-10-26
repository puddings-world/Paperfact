import { artifactFixture } from './artifact-fixture.mjs';
import { fileId } from './artifacts.mjs';
import { receive } from './domain.mjs';
import {
  IndexedStore
} from './store.mjs';
import {
  Engine
} from './engine.mjs';
import {
  demoTransport,
  PAPER
} from './fixture.mjs';
import {
  projection
} from './domain.mjs';
const results =[], result = document.querySelector('#result');
const assert =(value, message) => {
  if(! value) throw new Error(message);
};
async function check(name, run) {
  try {
    await run();
    results.push('PASS ' + name);
  } catch(error) {
    results.push('FAIL ' + name + ': ' + error.message);
  }
  result.textContent = results.join('\n');
}
async function until(predicate) {
  for(let i = 0; i < 100; i++) {
    if(predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('Timed out');
}
await check(
'IndexedDB atomic mutation rollback and reopened durable outbox',
async() => {
  const workspace = 'browser-fixture-' + crypto.randomUUID(),
  store = await IndexedStore.open(workspace, 'phone');
  try {
    await store.update(state => {
      state.drafts.note = 'must rollback';
      state.outbox.push({
        fixture: true
      });
      throw new Error('injected failure');
    });
  } catch {} assert(!(await store.read()).drafts.note, 'failed write leaked');
  assert((await store.read()).outbox.length === 0, 'outbox leaked');
  await store.update(state => {
    state.drafts.note = 'durable';
  });
  store.close();
  const reopened = await IndexedStore.open(workspace, 'phone');
  assert((await reopened.read()).drafts.note === 'durable', 'reload lost draft');
  reopened.close();
}
);
await check(
'IndexedDB note+outbox commit, scope isolation and response retry',
async() => {
  const device = 'browser-' + crypto.randomUUID(),
  transport = await demoTransport();
  transport.device = device;
  const store = await IndexedStore.open('demo-workspace', device),
  engine = new Engine(store, {
    transport
  });
  await engine.connect('fixture-token');
  await engine.sync();
  await saveCurrent(engine, 'browser-note', PAPER, 'Browser durable note');
  transport.loseResponse = true;
  try {
    await engine.sync();
  } catch {} assert((await store.read()).outbox.length === 1, 'lost response cleared outbox');
  await engine.sync();
  assert((await store.read()).outbox.length === 0, 'retry did not finish');
  const peer = await IndexedStore.open('other-workspace', device);
  assert((await peer.read()).cursor === 0, 'cross-workspace data');
  peer.close();
  engine.disconnect();
  store.close();
}
);
await check(
'Reader UI: select paper, save note, refresh without losing draft/focus',
async() => {
  const frame = document.querySelector('#reader');
  await until(() => frame.contentDocument.querySelector('.paper-card'));
  const doc = frame.contentDocument;
  doc.querySelector('.paper-card').click();
  doc.querySelector('#tab-notes').click();
  let editor = doc.querySelector('#note-editor');
  assert(editor, 'note editor missing');
  editor.focus();
  editor.value = 'Browser UI saved note';
  editor.dispatchEvent(new Event('input', {
    bubbles: true
  }));
  const save =[...doc.querySelectorAll('button')].find(button => button.textContent === 'Save note' || button.textContent === '儲存筆記');
  save.click();
  await until(() => doc.querySelector('#save-state')?.textContent.includes('Pending') || doc.querySelector('#save-state')?.textContent.includes('等待'));
  editor = doc.querySelector('#note-editor');
  editor.focus();
  editor.value = 'Keep this unsaved UI draft';
  editor.setSelectionRange(5, 9);
  editor.dispatchEvent(new Event('input', {
    bubbles: true
  }));
  const sync =[...doc.querySelectorAll('header button')][0];
  sync.click();
  await new Promise(resolve => setTimeout(resolve, 250));
  assert(doc.querySelector('#note-editor').value === 'Keep this unsaved UI draft', 'refresh overwrote draft');
  assert(doc.activeElement.id === 'note-editor', 'refresh stole focus');
  assert(doc.querySelector('#note-editor').selectionStart === 5, 'cursor position changed');
  const store = await IndexedStore.open('demo-workspace', 'demo-phone');
  assert(projection(await store.read()).notes.some(note => note.body === 'Browser UI saved note'), 'saved text missing');
  const lastEditor = doc.querySelector('#note-editor');
  lastEditor.value = 'Immediate switch draft';
  lastEditor.dispatchEvent(new Event('input', {
    bubbles: true
  }));
  [...doc.querySelectorAll('header button')][1].click();
  const demoButton =[...doc.querySelectorAll('dialog button')].find(button =>['Open demo workspace', '開啟示範工作區'].includes(button.textContent));
  demoButton.click();
  await until(() => ! doc.querySelector('dialog'));
  await until(() => ! doc.querySelector('header button')?.disabled);
  await until(() => doc.querySelector('#tab-notes'));
  doc.querySelector('#tab-notes').click();
  await until(() => doc.querySelector('#note-editor')?.value === 'Immediate switch draft');
  const switched = await store.read();
  assert(switched.drafts['demo-note'] === 'Immediate switch draft', 'switch lost debounced draft');
  assert(switched.draftBases['demo-note'], 'switch lost original observation');
  store.close();
}
);
await check(
'Service worker static shell cached without research/token requests',
async() => {
  const registration = await navigator.serviceWorker.ready;
  assert(registration.scope.endsWith('/'), 'scope unavailable');
  const cached = await caches.match(new URL('./index.html', location.href));
  assert(cached, 'offline shell missing');
  assert(!(await caches.match(new URL('./v1/pull', location.href))), 'research cached');
}
);
await check('Verified offline deck renders slide image, speaker notes and source on actual mobile UI', async()=> {
  const fixture = await artifactFixture(), id = fileId(PAPER,'guide');
  const store = await IndexedStore.open('demo-workspace','demo-phone');
  const transport = await demoTransport();
  for(const [hash,bytes] of fixture.blobs) transport.blobs.set(hash,bytes);
  let artifactEvent;
  await store.update(state=> {
    const op={version:2,operation_id:'browser-deck',workspace_id:state.workspace,device_id:'demo-desktop',
      entity_type:'research_file',entity_id:id,action:'put',base_revision:0,depends_on:null,payload:fixture.payload,
      incarnation:'browser-deck',parents:[{kind:'paper',id:PAPER,incarnation:PAPER+'-created'}],structure_revision:0};
    const sequence=state.cursor+1;
    artifactEvent={sequence,outcome:'accepted',operation:op,head:{revision:sequence,operation:op}};
    receive(state,[artifactEvent]);
  });
  const authority=await IndexedStore.open('demo-workspace','fixture-authority');
  await authority.update(next=>receive(next,[artifactEvent]));
  authority.close();
  const engine = new Engine(store,{transport}); await engine.connect('fixture-token');
  await engine.downloadArtifact(id); engine.disconnect();
  assert((await engine.deck(id)).body.deck.title===fixture.body.deck.title,'offline deck missing');
  const frame=document.querySelector('#reader');
  const loaded=new Promise(resolve=>frame.addEventListener('load',resolve,{once:true}));
  frame.contentWindow.location.reload(); await loaded;
  await until(()=>frame.contentDocument.querySelector('.paper-card') || frame.contentDocument.querySelector('#tab-slides'));
  const doc=frame.contentDocument; doc.querySelector('.paper-card')?.click(); doc.querySelector('#tab-slides').click();
  await until(()=>doc.querySelector('.slide-surface img')?.complete && doc.querySelector('.slide-surface img')?.naturalWidth>0);
  assert(doc.querySelector('.slide-surface').textContent.includes('Why this result matters'),'slide content missing');
  const boxes=doc.querySelectorAll('.slide-object');
  assert(boxes[1].getBoundingClientRect().top > boxes[0].getBoundingClientRect().top,'CSP blocked slide geometry');
  doc.querySelector('.slide-page details').open=true;
  assert(doc.querySelector('.slide-notes').textContent.includes('synthetic slide'),'speaker notes missing');
  assert(doc.querySelector('.slide-page details').textContent.includes('Figure 1'),'source missing');
  assert(!doc.querySelector('.slide-page textarea'),'read-only viewer unexpectedly editable');
  store.close();
});
document.body.dataset.result = results.some(line => line.startsWith('FAIL')) ? 'fail': 'pass';
result.textContent = results.join('\n') + '\n' + document.body.dataset.result.toUpperCase();
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
