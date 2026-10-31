/** Actual desktop Inbox operations -> authenticated HTTP -> independent offline phone. */
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {MemoryStore} from './store.mjs';
import {Engine} from './engine.mjs';
import {HttpTransport} from './transport.mjs';
import {captureInbox,draftInbox,saveInbox,resolveInbox,inboxReport,observeInbox} from './inbox-ops.mjs';
import {validateProjection,stable} from './domain.mjs';
if(!process.argv[2])throw Error('Pass the project Python executable.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./inbox-fixture.py',import.meta.url)),...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const lines=[],pending=[];createInterface({input:child.stdout}).on('line',line=>{const next=pending.shift();if(next)next(line);else lines.push(line);});
async function message(command) {
 if(command)child.stdin.write(JSON.stringify(command)+'\n');
 return JSON.parse(await new Promise((resolve,reject)=>{
  if(lines.length){resolve(lines.shift());return;}
  const timer=setTimeout(()=>reject(Error('Inbox fixture timeout: '+errors)),30000);
  pending.push(line=>{clearTimeout(timer);resolve(line);});
  child.once('exit',code=>{clearTimeout(timer);reject(Error('Inbox fixture exit '+code+': '+errors));});
 }));
}
try {
 const ready=await message(),store=new MemoryStore(ready.workspace,'phone'),native=new HttpTransport(ready.url),calls=[];
 const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{calls.push(key);return value.apply(target,args);}:value;}});
 let engine=new Engine(store,{transport});await engine.importProjection(ready.projection);
 assert.deepEqual(validateProjection(ready.projection,ready.workspace).inbox.items[0].payload,ready.items[0].payload);
 await engine.connect(ready.token);await engine.sync();
 assert.equal(inboxReport(await store.read()).items[0].payload.text,'  DOI:10.1234/Exact-Mixed  ');
 engine.disconnect();const offlineStore=new MemoryStore(ready.workspace,'phone',await store.read());engine=new Engine(offlineStore,{transport});
 const scope=await captureInbox(engine),requestId=crypto.randomUUID(),itemId=crypto.randomUUID();
 const payload={kind:'idea',text:'  Exact phone idea <script>literal</script>  ',state:'new',created_at:'2026-10-30T12:01:00Z',updated_at:'2026-10-30T12:01:00Z'};
 const before=calls.length;await draftInbox(engine,scope,{itemId,requestId,kind:'idea',text:payload.text,state:'new'});
 const saved=await saveInbox(engine,{scope,requestId,itemId,payload});assert.equal(calls.length,before);
 const restartedStore=new MemoryStore(ready.workspace,'phone',await offlineStore.read());engine=new Engine(restartedStore,{transport});
 let captured=await captureInbox(engine);assert.deepEqual(await saveInbox(engine,{scope:captured,requestId,itemId,payload}),saved);
 assert.equal((await restartedStore.read()).outbox.length,1);await restartedStore.update(state=>{state.drafts.reader='Keep unrelated reader draft';});
 await engine.connect(ready.token);await engine.sync();let desktop=await message({command:'sync'});
 assert.equal(desktop.items.find(row=>row.id===itemId).payload.text,payload.text);
 const observed=observeInbox(await restartedStore.read(),itemId);
 desktop=await message({command:'triage',item_id:itemId});
 assert.equal(desktop.items.find(row=>row.id===itemId).payload.state,'kept');
 engine.disconnect();captured=await captureInbox(engine);
 const changed={...payload,text:'Phone edit retained across conflict',state:'dismissed',updated_at:'2026-10-30T14:00:00Z'};
 await saveInbox(engine,{scope:captured,requestId:crypto.randomUUID(),itemId,payload:changed,observed});
 await engine.connect(ready.token);await engine.sync();desktop=await message({command:'sync'});
 let report=inboxReport(await restartedStore.read());assert.equal(report.items.find(row=>row.id===itemId).payload.state,'kept');
 const conflict=report.retained.find(row=>row.source==='server');assert.equal(conflict.payload.text,changed.text);
 assert.equal(desktop.retained[0].payload.text,changed.text);
 captured=await captureInbox(engine);const resolvedRequest=crypto.randomUUID();
 await resolveInbox(engine,conflict.id,{scope:captured,requestId:resolvedRequest,choice:'incoming'});
 await engine.sync();desktop=await message({command:'sync'});
 assert.equal(desktop.items.find(row=>row.id===itemId).payload.text,changed.text);
 assert.equal(inboxReport(await restartedStore.read()).retained.length,0);
 await message({command:'delete',item_id:itemId});await engine.sync();report=inboxReport(await restartedStore.read());
 const deleted=report.items.find(row=>row.id===itemId);assert.equal(deleted.active,false);assert.equal(deleted.payload.text,changed.text);
 captured=await captureInbox(engine);const deadBase=observeInbox(await restartedStore.read(),itemId);
 await assert.rejects(saveInbox(engine,{scope:captured,requestId:crypto.randomUUID(),itemId,payload:changed,observed:deadBase}));
 const oldIncarnation=deleted.incarnation;await saveInbox(engine,{scope:captured,requestId:crypto.randomUUID(),itemId,payload:changed,observed:deadBase,restore:true});
 await engine.sync();desktop=await message({command:'backup'});
 assert.equal(desktop.items.find(row=>row.id===itemId).payload.text,changed.text);
 assert.notEqual(desktop.items.find(row=>row.id===itemId).incarnation,oldIncarnation);
 assert.equal(desktop.restored.find(row=>row.id===itemId).payload.text,changed.text);
 assert(desktop.fresh_receiver);assert.equal(desktop.sender_receipts_live,0);assert.equal(desktop.active_binding,false);
 const final=await restartedStore.read();assert.equal(final.drafts.reader,'Keep unrelated reader draft');
 assert(!stable(final).includes(ready.token));assert(calls.every(key=>['session_info','push','pull'].includes(key)));
 console.log('PASS actual desktop Inbox -> private HTTP -> independent offline phone capture/restart/retry, explicit triage/conflict/delete/restore, exact text and fresh detached recovery; no implicit fetch/AI/account/file operations');
} finally {
 child.stdin.end(JSON.stringify({command:'quit'})+'\n');if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
