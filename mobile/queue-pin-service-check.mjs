/** Real desktop writer -> authenticated loopback service -> offline mobile bytes. */
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {MemoryStore} from './store.mjs';
import {Engine} from './engine.mjs';
import {HttpTransport} from './transport.mjs';
import {projection,stable} from './domain.mjs';
const python=process.argv[2],root=process.argv[3]??fileURLToPath(new URL('../',import.meta.url));
if(!python)throw Error('Pass the project Python executable and optional core root.');
const child=spawn(python,[resolve(root,'mobile/queue-pin-service-fixture.py'),root],
  {stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='',exited=false;
child.stderr.on('data',chunk=>errors+=chunk);
const lines=[],waiting=[];
createInterface({input:child.stdout}).on('line',line=>{
  const waiter=waiting.shift();if(waiter)waiter.resolve(line);else lines.push(line);
});
child.once('exit',code=>{exited=true;for(const waiter of waiting.splice(0))waiter.reject(Error('Fixture exit '+code+': '+errors));});
async function message(command) {
  if(command)child.stdin.write(command+'\n');
  const line=lines.length?lines.shift():await new Promise((resolve,reject)=>{
    if(exited){reject(Error('Fixture exited: '+errors));return;}
    const timer=setTimeout(()=>reject(Error('Fixture timeout: '+errors)),20000);
    waiting.push({resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
  });return JSON.parse(line);
}
try {
  const ready=await message();
  const store=new MemoryStore(ready.workspace,'phone');
  const transport=new HttpTransport(ready.url);
  const engine=new Engine(store,{transport});
  await engine.connect(ready.token);await engine.sync();
  let state=await store.read(),data=projection(state);
  const paper=data.papers.find(item=>item.title==='Orphan pinned paper');
  assert(paper);assert.deepEqual(paper.queue_pin,{pinned_at:ready.stamp});
  assert.deepEqual(data.lists,[]);assert.deepEqual(state.outbox,[]);
  const first=state.cursor;
  await engine.sync();assert.equal((await store.read()).cursor,first);
  // Persist/reopen the same local state with a transport that cannot contact a service.
  const reopened=new MemoryStore(ready.workspace,'phone',JSON.parse(JSON.stringify(await store.read())));
  const offline=new Engine(reopened,{transport:{push(){throw Error('offline');},pull(){throw Error('offline');}}});
  assert.deepEqual(projection(await reopened.read()).papers.find(item=>item.id===paper.id).queue_pin,{pinned_at:ready.stamp});
  assert(offline);
  const initialPin=Object.values(state.entities).find(row=>row.operation.payload?.feature==='queue_pin').operation;
  let priorCursor=state.cursor,priorInc=initialPin.incarnation,previous=null;
  for(const command of ['rollback','off','off','on','on']) {
    const next=await message(command);await engine.sync();state=await store.read();data=projection(state);
    const current=data.papers.find(item=>item.id===paper.id),op=state.entities['research_content/'+initialPin.entity_id].operation;
    assert.equal(state.cursor,next.events);assert.deepEqual(state.outbox,[]);assert.deepEqual(data.lists,[]);
    if(command==='rollback'||command==='on')assert.deepEqual(current.queue_pin,{pinned_at:ready.stamp});
    else assert.equal(current.queue_pin,null);
    if(command==='rollback'||command===previous) {
      assert.equal(state.cursor,priorCursor);assert.equal(op.incarnation,priorInc);
    } else {
      assert(state.cursor>priorCursor);
      if(command==='on')assert.notEqual(op.incarnation,priorInc);
    }
    priorCursor=state.cursor;priorInc=op.incarnation;previous=command;
  }
  const pinReceipts=Object.values(state.receipts).filter(event=>event.operation.entity_id===initialPin.entity_id).length;
  for(const command of ['make-queue-list','remove-queue-member','remove-queue-list']) {
    const next=await message(command);await engine.sync();state=await store.read();data=projection(state);
    assert.equal(next.pinned,true);
    assert.deepEqual(data.papers.find(item=>item.id===paper.id).queue_pin,{pinned_at:ready.stamp});
    assert.equal(state.entities['research_content/'+initialPin.entity_id].operation.incarnation,priorInc);
    assert.equal(Object.values(state.receipts).filter(event=>event.operation.entity_id===initialPin.entity_id).length,pinReceipts);
    assert.deepEqual(state.outbox,[]);
    if(command==='make-queue-list')assert.equal(data.lists.find(list=>list.id==='queue').members.length,1);
    if(command==='remove-queue-member')assert.equal(data.lists.find(list=>list.id==='queue').members.length,0);
    if(command==='remove-queue-list')assert.deepEqual(data.lists,[]);
  }
  console.log('PASS actual queue-pin writer, authenticated HTTP, idempotence, rollback, tombstone/restore and offline read-only projection');
} finally {
  if(!exited)child.stdin.write('quit\n');
}
