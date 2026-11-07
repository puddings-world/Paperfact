/** Desktop Data writer -> authenticated Python HTTP -> actual mobile engine -> desktop. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {Engine} from './engine.mjs';
import {HttpTransport} from './transport.mjs';
import {MemoryStore} from './store.mjs';
import {projection} from './domain.mjs';

const child=spawn(process.argv[2],[fileURLToPath(new URL('./plain-note-service-fixture.py',import.meta.url)),...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const lines=[],waiters=[];
createInterface({input:child.stdout}).on('line',line=>{const next=waiters.shift();if(next)next(line);else lines.push(line);});
function message(command){
  if(command)child.stdin.write(JSON.stringify(command)+'\n');
  return new Promise((resolve,reject)=>{
    if(lines.length){resolve(JSON.parse(lines.shift()));return;}
    const timer=setTimeout(()=>reject(Error('Plain-note service timed out: '+errors)),30000);
    waiters.push(line=>{clearTimeout(timer);resolve(JSON.parse(line));});
    child.once('exit',code=>{clearTimeout(timer);reject(Error('Plain-note service exited '+code+': '+errors));});
  });
}
try{
  const ready=await message(),transport=new HttpTransport(ready.url);
  let store=new MemoryStore(ready.workspace,ready.device),engine=new Engine(store,{transport});
  await engine.connect(ready.token);await engine.sync();
  let note=projection(await store.read()).notes.find(n=>n.id===ready.note);
  assert.equal(note.editable,true,'Desktop unanchored text must remain editable on phone');
  const created=note.created_at;
  const observed=await engine.observeNote(ready.note,ready.paper);
  await engine.draft(ready.note,'Phone offline text',observed);
  engine.disconnect();
  store=new MemoryStore(ready.workspace,ready.device,await store.read());
  engine=new Engine(store,{transport});
  assert.equal((await store.read()).drafts[ready.note],'Phone offline text');
  const saved=await engine.saveNote(ready.note,ready.paper,'Phone offline text');
  assert.equal((await engine.saveNote(ready.note,ready.paper,'Phone offline text')).operation_id,saved.operation_id);
  assert.equal((await store.read()).outbox.length,1);
  assert.deepEqual(saved.payload,{paper_id:ready.paper,body:'Phone offline text',kind:'note',created_at:created,page:null,anchor:null});
  await engine.connect(ready.token);await engine.sync();
  let desktop=await message({command:'inspect'});
  assert.equal(desktop.note.body,'Phone offline text');assert.equal(desktop.note.created_at,created);
  assert.equal(desktop.pending,0);
  await message({command:'edit',body:'Desktop continued text'});await engine.sync();
  note=projection(await store.read()).notes.find(n=>n.id===ready.note);
  assert.equal(note.body,'Desktop continued text');assert.equal(note.editable,true);
  const old=await engine.observeNote(ready.note,ready.paper);
  await engine.draft(ready.note,'Unsent human draft',old);
  await message({command:'edit',body:'Newer desktop text'});await engine.sync();
  await assert.rejects(engine.saveNote(ready.note,ready.paper,'Unsent human draft',{observed:old}),/stale_draft/);
  assert.equal((await store.read()).drafts[ready.note],'Unsent human draft');
  assert.equal((await store.read()).outbox.length,0);
  desktop=await message({command:'edit-stale',body:'Stale desktop draft'});
  assert.equal(desktop.conflict,true);assert.equal(desktop.note.body,'Newer desktop text');
  assert.equal(desktop.candidates.length,1);
  assert(JSON.stringify(desktop.candidates).includes('Stale desktop draft'));
  assert.equal(desktop.note.created_at,created);
  const fresh=await engine.observeNote(ready.note,ready.paper);
  await engine.saveNote(ready.note,ready.paper,'Final phone revision',{observed:fresh});
  await engine.sync();desktop=await message({command:'inspect'});
  assert.equal(desktop.note.body,'Final phone revision');assert.equal(desktop.note.created_at,created);
  assert.equal(desktop.note.anchor,null);assert.equal(desktop.note.page,null);
  const finalObservation=await engine.observeNote(ready.note,ready.paper);
  await engine.deleteNote(ready.note,{observed:finalObservation});
  assert.equal((await store.read()).outbox.length,1);
  await engine.sync();desktop=await message({command:'inspect'});
  assert.equal(desktop.note,null);
  assert.equal((await store.read()).outbox.length,0);
  console.log('PASS desktop/mobile unanchored text: offline draft/reopen, single save, authenticated roundtrip, metadata preservation, both stale edits retained, fresh retry and synchronized deletion');
}finally{
  child.stdin.end(JSON.stringify({command:'quit'})+'\n');
  const code=await new Promise(resolve=>{if(child.exitCode!==null){resolve(child.exitCode);return;}child.once('exit',resolve);setTimeout(()=>{child.kill();resolve(null);},5000).unref();});
  if(code!==0)throw Error('Plain-note service cleanup failed: '+errors);
}
