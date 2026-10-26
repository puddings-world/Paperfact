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
