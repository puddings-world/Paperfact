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
import {digest} from './artifact-engine.mjs';
const python=process.argv[2],root=process.argv[3]??fileURLToPath(new URL('../',import.meta.url));
if(!python)throw Error('Pass the project Python executable and optional core root.');
const child=spawn(python,[resolve(root,'mobile/legacy-workflow-service-fixture.py'),root],
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
  const ready=await message(),store=new MemoryStore(ready.workspace,'phone'),native=new HttpTransport(ready.url),calls=[];
  let interrupt=true;
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?async(...args)=>{
    calls.push(key);
    if(key==='blob_read' && args[1]===ready.sha256 && interrupt){interrupt=false;throw Error('fixture_interruption');}
    return value.apply(target,args);
  }:value;}});
  const engine=new Engine(store,{transport});await engine.connect(ready.token);await engine.sync();
  const paperId=ready.event.payload.scope.id,eventId=ready.event.payload.key,fileId=ready.file.entity_id;
  let state=await store.read(),view=projection(state),paper=view.papers.find(p=>p.id===paperId);
  assert.equal(state.cursor,ready.events);assert.deepEqual(state.outbox,[]);assert.deepEqual(state.appliedArtifacts,{});
  assert.deepEqual(paper.legacy_queue,ready.queue.payload.data);
  assert.deepEqual(paper.reading_events[0].data,ready.event.payload.data);
  assert.equal(paper.reading_events[0].id,eventId);assert.deepEqual(view.lists,[]);
  assert.equal(view.legacy_briefs[0].id,fileId);
  await assert.rejects(engine.legacyBrief(fileId),/artifact_unavailable/);
  const pending=engine.downloadArtifact(fileId);assert.equal(pending,engine.downloadArtifact(fileId));
  await assert.rejects(pending,/fixture_interruption/);assert.deepEqual((await store.read()).appliedArtifacts,{});
  await engine.downloadArtifact(fileId);
  const result=await engine.legacyBrief(fileId),exact=new TextEncoder().encode(ready.markdown);
  assert.equal(result.text,ready.markdown);assert.equal(await digest(exact),ready.sha256);
  assert.deepEqual(result.blobs.get(ready.sha256),exact);assert(result.text.includes('<script>never execute</script>'));
  assert.equal(result.body.event_incarnation,ready.event.incarnation);
  engine.disconnect();
  const offline=new Engine(new MemoryStore(ready.workspace,'phone',await store.read()),
    {transport:new Proxy({}, {get(){throw Error('offline reader attempted network');}})});
  assert.equal((await offline.legacyBrief(fileId)).text,ready.markdown);
  await engine.connect(ready.token);
  for(const command of ['note','companion','rank','clear','delete']) {
    const next=await message(command);await engine.sync();state=await store.read();paper=projection(state).papers.find(p=>p.id===paperId);
    assert.equal(state.cursor,next.events);assert.deepEqual(state.outbox,[]);
    if(command==='note'){assert.equal(paper.reading_events[0].data.note,'Edited note');assert.equal((await engine.legacyBrief(fileId)).text,ready.markdown);}
    if(command==='companion'){
      assert.deepEqual(paper.legacy_queue,next.queue.payload.data);assert.equal(paper.legacy_queue.rank,0.1);
      assert.equal(paper.legacy_queue.role,'companion');assert.equal(next.queue.entity_id,ready.queue.entity_id);
      assert.deepEqual(next.queue.parents[0],ready.queue.parents[0]);
      assert.notEqual(next.queue.parents[1].id,ready.queue.parents[1].id);
      assert.notEqual(next.queue.incarnation,ready.queue.incarnation);assert.equal(next.queue.incarnation,next.queue.operation_id);
      assert.equal(state.entities['research_content/'+next.queue.entity_id].operation.incarnation,next.queue.incarnation);
      assert.equal((await engine.legacyBrief(fileId)).text,ready.markdown);assert.deepEqual(projection(state).lists,[]);
    }
    if(command==='rank')assert.equal(paper.legacy_queue.rank,1e21);
    if(command==='clear'){
      assert.equal(paper.reading_events[0].data.brief,null);assert.deepEqual(projection(state).legacy_briefs,[]);
      await assert.rejects(engine.legacyBrief(fileId),/artifact_unavailable/);
    }
    if(command==='delete'){assert.deepEqual(paper.reading_events,[]);await assert.rejects(engine.legacyBrief(fileId),/artifact_unavailable/);}
  }
  const before=stable(await store.read());await engine.sync();assert.equal(stable(await store.read()),before);
  engine.disconnect();const cleared=new Engine(new MemoryStore(ready.workspace,'phone',await store.read()));
  await assert.rejects(cleared.legacyBrief(fileId),/artifact_unavailable/);
  assert(!JSON.stringify(await store.read()).includes(ready.token));
  assert(calls.every(key=>['session_info','pull','blob_read'].includes(key)),JSON.stringify(calls));
  console.log('PASS actual desktop legacy queue/event/brief -> HTTP -> exact UTF8 Markdown offline; interrupted retry, duplicate download, note/companion-context/rank/clear/delete, no writes or jobs');
} finally {
  child.stdin.end('quit\n');
  if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
