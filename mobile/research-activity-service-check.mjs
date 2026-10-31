/** Real typed HTTP journal -> independently equal Python/mobile activity views. */
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {Engine} from './engine.mjs';
import {MemoryStore} from './store.mjs';
import {HttpTransport} from './transport.mjs';
import {activityReport,canOpenSavedNote,activateActivity} from './research-activity.mjs';
import {stable} from './domain.mjs';
if(!process.argv[2])throw Error('Pass the project Python executable.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./research-activity-fixture.py',import.meta.url)),
  ...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const lines=[],pending=[];
createInterface({input:child.stdout}).on('line',line=>{const next=pending.shift();if(next)next(line);else lines.push(line);});
async function message(command) {
  if(command)child.stdin.write(command+'\n');
  return JSON.parse(await new Promise((resolve,reject)=>{
    if(lines.length){resolve(lines.shift());return;}
    const timer=setTimeout(()=>reject(Error('Activity fixture timeout: '+errors)),20000);
    pending.push(line=>{clearTimeout(timer);resolve(line);});
    child.once('exit',code=>{clearTimeout(timer);reject(Error('Activity fixture exit '+code+': '+errors));});
  }));
}
try {
  const ready=await message(),store=new MemoryStore(ready.workspace,'phone'),native=new HttpTransport(ready.url),calls=[];
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{calls.push(key);return value.apply(target,args);}:value;}});
  const engine=new Engine(store,{transport});await engine.connect(ready.token);await engine.sync();
  assert.deepEqual(activityReport(await store.read()),ready.report);
  assert.equal(ready.report.recent[0].status,'manifest_waiting');
  assert(ready.report.continue[0].resume);assert.equal(ready.report.continue[0].resume.source_hash,ready.source_hash);
  for(const command of ['own','conflict']) {
    const result=await message(command);await engine.sync();assert.deepEqual(activityReport(await store.read()),result.report);
    if(command==='own')assert(!result.report.recent.some(r=>r.operation_id==='own-note'));
    else assert.equal(result.report.recent[0].status,'conflict_retained');
  }
  await engine.download(ready.paper_id);const loaded=await engine.pdf(ready.paper_id),row=activityReport(await store.read()).continue[0];
  assert.equal(loaded.sha256,ready.source_hash);
  assert(canOpenSavedNote(await store.read(),row,{paper_id:ready.paper_id,hash:loaded.sha256}));
  const beforeCalls=calls.length,before=stable(await store.read()),opened=[];
  assert.equal(await activateActivity({store,row,locate:true,loaded:()=>({paper_id:ready.paper_id,hash:loaded.sha256}),
    openNote:(paper,note)=>opened.push([paper,note])}),'note_opened');
  assert.deepEqual(opened,[[ready.paper_id,ready.note_id]]);assert.equal(calls.length,beforeCalls);
  assert.equal(stable(await store.read()),before);
  const changed=await message('source');await engine.sync();assert.deepEqual(activityReport(await store.read()),changed.report);
  assert(!canOpenSavedNote(await store.read(),activityReport(await store.read()).continue[0],{paper_id:ready.paper_id,hash:loaded.sha256}));
  const deleted=await message('delete');await engine.sync();assert.deepEqual(activityReport(await store.read()),deleted.report);
  assert.equal(deleted.report.continue[0].entity_type,'reading_state');assert.equal(deleted.report.continue[0].resume,null);
  engine.disconnect();const offline=new MemoryStore(ready.workspace,'phone',await store.read());
  assert.deepEqual(activityReport(await offline.read()),deleted.report);assert.deepEqual((await offline.read()).outbox,[]);
  assert(!JSON.stringify(await store.read()).includes(ready.token));
  assert(calls.every(key=>['session_info','pull','blob_read'].includes(key)));
  console.log('PASS actual typed journal/HTTP -> identical Python/mobile recorded-activity views, own echo/conflict, explicit source-pinned note, changed PDF/deleted note/offline/drafts preserved; no activity network/research write/AI');
} finally {
  child.stdin.end('quit\n');if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
