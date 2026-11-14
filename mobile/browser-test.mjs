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
  [...doc.querySelectorAll('header button')].find(button => ['Connection', '連線'].includes(button.textContent)).click();
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
await check('Linked QA persists across IndexedDB reopen and actual UI reload without mispairing or HTML execution', async()=> {
  const {contentId} = await import('./ids.mjs');
  const {chatExchanges} = await import('./content.mjs');
  const uid=n=>'20000000-0000-4000-8000-'+String(n).padStart(12,'0');
  const store=await IndexedStore.open('demo-workspace','demo-phone');
  const before=await store.read(), events=[];
  const turns=[[3,'assistant',101,1,'First answer <img src=x onerror=alert(1)>'],
    [2,'user',102,null,'Same question'],[4,'assistant',102,2,'Second answer'],
    [1,'user',101,null,'Same question'],[5,'assistant',103,6,'Orphan answer']];
  for(const [id,role,exchange,reply,body] of turns) {
    const payload={scope:{kind:'paper',id:PAPER},feature:'chat',key:uid(id),source_document_hash:null,
      data:{role,body,created_at:'2026-10-27T00:00:00Z',page:null,anchor:null,
        exchange_id:uid(exchange),reply_to:reply===null?null:uid(reply)}};
    const operation={version:2,operation_id:'browser-chat-'+id,workspace_id:'demo-workspace',device_id:'demo-desktop',
      entity_type:'research_content',entity_id:contentId(payload.scope,'chat',payload.key),action:'put',
      base_revision:0,depends_on:null,payload,incarnation:'browser-chat-'+id,
      parents:[{kind:'paper',id:PAPER,incarnation:PAPER+'-created'}],structure_revision:0};
    const sequence=before.cursor+events.length+1;
    events.push({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
  }
  await store.update(state=>receive(state,[events[0]]));
  store.close();
  const reopened=await IndexedStore.open('demo-workspace','demo-phone');
  assert(chatExchanges(projection(await reopened.read()).papers.find(p=>p.id===PAPER))[0].orphan,'answer incorrectly paired before question');
  await reopened.update(state=>receive(state,events.slice(1)));
  const after=await reopened.read();
  assert(JSON.stringify(after.outbox)===JSON.stringify(before.outbox),'receive created outbound work');
  const authority=await IndexedStore.open('demo-workspace','fixture-authority');
  await authority.update(state=>receive(state,events)); authority.close(); reopened.close();
  const frame=document.querySelector('#reader');
  const loaded=new Promise(resolve=>frame.addEventListener('load',resolve,{once:true}));
  frame.contentWindow.location.reload(); await loaded;
  await until(()=>frame.contentDocument.querySelector('.paper-card') || frame.contentDocument.querySelector('#tab-overview'));
  const doc=frame.contentDocument;doc.querySelector('.paper-card')?.click();doc.querySelector('#tab-overview').click();
  await until(()=>doc.querySelectorAll('.chat-exchange').length===3);
  const cards=[...doc.querySelectorAll('.chat-exchange')];
  assert(cards[0].querySelector('.chat-question').textContent==='Same question','question lost');
  assert(cards[0].querySelector('.chat-answer').textContent==='Second answer','interleaved answer mispaired');
  assert(cards[1].querySelector('.chat-answer').textContent===turns[0][4],'answer markup changed');
  assert(!cards[1].querySelector('img'),'model HTML executed');
  assert(!cards[2].querySelector('.chat-question') && cards[2].querySelector('.muted'),'orphan attached to another question');
  assert(!(doc.querySelector('.chat-exchange textarea') || doc.querySelector('.chat-exchange button')),'receive exposed AI action');
  const cached=await caches.match(new URL('./chat-view.mjs',location.href));
  assert(cached,'offline conversation module missing');
});
await check('Lineage exact IndexedDB reopen, real read-only cards and source-lifetime retirement',async()=>{
  const {lineageRow}=await import('./tests/fixtures/lineage-data.mjs');
  const {contentId}=await import('./ids.mjs');
  const {sourceFileId}=await import('./artifacts.mjs');
  const {operation}=await import('./fixture.mjs');
  let store=await IndexedStore.open('demo-workspace','demo-phone');
  const before=await store.read(),row=lineageRow();
  row.body.bindings[0].paper_id=PAPER;
  const parent={kind:'paper',id:PAPER,incarnation:before.graph['paper/'+PAPER].incarnation};
  const sha=row.document_hash,id=sourceFileId(PAPER,sha);
  const payload={paper_id:PAPER,feature:'original_source',slot:sha,format_version:1,
    source_document_hash:sha,input_versions:{schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null},
    body:{sha256:'b'.repeat(64),size:160,media_type:'application/json'},
    assets:[{id:'original',role:'original_pdf',sha256:sha,size:256,media_type:'application/pdf'}]};
  const source=operation('research_file',id,payload,{operationId:'browser-lineage-source',parents:[parent]});
  const body={scope:{kind:'paper',id:PAPER},feature:'lineage',key:row.body.corpus_id,source_document_hash:sha,
    data:{body_json:row.body,source_hash:row.source_hash,document_hash:sha,written_at:row.written_at}};
  const science={...operation('research_content',contentId(body.scope,'lineage',body.key),body,
    {operationId:'browser-lineage-report',parents:[parent]}),
    content_address:{feature:'lineage',key:body.key},source_dependencies:[{source_id:row.body.report.focal,
      paper_id:PAPER,file_id:id,incarnation:source.incarnation}]};
  const event=(op,sequence)=>({sequence,outcome:'accepted',operation:op,head:{revision:sequence,operation:op}});
  const events=[event(source,before.cursor+1),event(science,before.cursor+2)];
  const authority=await IndexedStore.open('demo-workspace','fixture-authority');
  await store.update(state=>receive(state,events));await authority.update(state=>receive(state,events));
  store.close();store=await IndexedStore.open('demo-workspace','demo-phone');
  const saved=await store.read(),paper=projection(saved).papers.find(p=>p.id===PAPER);
  assert(JSON.stringify(paper.lineage)==JSON.stringify([row]),'reopen lost scientific body');
  assert(JSON.stringify(saved.files)===JSON.stringify(before.files),'metadata changed PDF bytes');
  assert(JSON.stringify(saved.artifactFiles)===JSON.stringify(before.artifactFiles),'metadata created byte grants');
  assert(JSON.stringify(saved.drafts)===JSON.stringify(before.drafts),'receive lost drafts');
  const bad={...structuredClone(science),operation_id:'bad-browser-lineage'};
  bad.source_dependencies[0].incarnation='changed-original';
  let rejected=false;try{await store.update(state=>{state.drafts.lineage='must rollback';receive(state,[event(bad,state.cursor+1)]);});}catch{rejected=true;}
  assert(rejected,'stale original was accepted');
  assert(JSON.stringify(await store.read())===JSON.stringify(saved),'failed page changed durable state');
  const frame=document.querySelector('#reader');
  const live=frame.contentDocument;live.querySelector('#tab-overview').click();
  [...live.querySelectorAll('header button')][0].click();
  await until(()=>live.querySelector('.lineage-card'));
  assert(live.querySelector('.lineage-card').textContent.includes(row.body.report.statements[0].text),'foreground refresh omitted new science');
  async function overview(){
    const loaded=new Promise(resolve=>frame.addEventListener('load',resolve,{once:true}));
    frame.contentWindow.location.reload();await loaded;
    await until(()=>frame.contentDocument.querySelector('.paper-card')||frame.contentDocument.querySelector('#tab-overview'));
    const doc=frame.contentDocument;doc.querySelector('.paper-card')?.click();doc.querySelector('#tab-overview').click();return doc;
  }
  const doc=await overview();await until(()=>doc.querySelector('.lineage-card'));
  const card=doc.querySelector('.lineage-card'),summary=card.querySelector('.lineage-corpus>summary');
  assert(card.textContent.includes(row.body.report.statements[0].text),'actual overview omitted Lineage');
  assert(card.textContent.includes(row.body.report.statements[0].passages[0].quote),'actual overview omitted original quote');
  assert(!card.querySelector('button,a,textarea'),'read-only cards exposed an unchecked action');
  assert(card.scrollWidth<=card.clientWidth+1,'phone-width Lineage card overflowed');
  summary.focus();const open=summary.parentElement.open;summary.click();
  assert(summary.parentElement.open!==open,'native disclosure could not toggle');summary.click();
  assert(await caches.match(new URL('./lineage-ops.mjs',location.href)),'new receiver missing from offline shell');
  const retired={...source,operation_id:'browser-lineage-source-retired',action:'delete',payload:{}};
  const restored={...source,operation_id:'browser-lineage-source-restored',incarnation:'browser-lineage-source-restored'};
  const next=[event(retired,saved.cursor+1),event(restored,saved.cursor+2)];
  await store.update(state=>receive(state,next));await authority.update(state=>receive(state,next));
  const after=await store.read();assert(projection(after).papers.find(p=>p.id===PAPER).lineage.length===0,'same-hash restoration revived old source pin');
  assert(JSON.stringify(after.entities['research_content/'+science.entity_id].operation)===JSON.stringify(science),'retirement discarded scientific history');
  assert(JSON.stringify(after.entities['paper_document/'+PAPER])===JSON.stringify(before.entities['paper_document/'+PAPER]),'retirement changed primary document');
  [...doc.querySelectorAll('header button')][0].click();
  await until(()=>!doc.querySelector('.lineage-card'));
  assert(doc.querySelector('#tab-overview'),'source update moved away from the paper reader');
  const reloaded=await overview();await until(()=>!reloaded.querySelector('.lineage-card'));
  store.close();authority.close();
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
