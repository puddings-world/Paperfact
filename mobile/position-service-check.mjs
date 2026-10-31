/** Actual entered desktop record -> HTTP -> independent phone -> exact offline A/B. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {Engine} from './engine.mjs';
import {MemoryStore} from './store.mjs';
import {HttpTransport} from './transport.mjs';
import {positionReport} from './reading-position-report.mjs';
import * as old from './tests/fixtures/pre-position-domain.mjs';
if(!process.argv[2])throw Error('Pass project Python.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./position-service-fixture.py',import.meta.url)),
  ...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const lines=[],pending=[];createInterface({input:child.stdout}).on('line',line=>{const next=pending.shift();if(next)next(line);else lines.push(line);});
async function next(command) {
  if(command)child.stdin.write(command+'\n');
  return JSON.parse(await new Promise((resolve,reject)=>{
    if(lines.length){resolve(lines.shift());return;}
    const timer=setTimeout(()=>reject(Error('Position fixture timeout: '+errors)),30000);
    pending.push(line=>{clearTimeout(timer);resolve(line);});
    child.once('exit',code=>{clearTimeout(timer);reject(Error('Position fixture exit '+code+': '+errors));});
  }));
}
try {
  const ready=await next(),store=new MemoryStore(ready.workspace,'phone'),transport=new HttpTransport(ready.url);
  const engine=new Engine(store,{transport});await engine.importProjection(ready.projection);
  assert.equal(positionReport(await store.read(),ready.paper).positions[0].page,2);
  assert.deepEqual((await store.read()).artifactFiles,{});assert.equal((await store.read()).cursor,0);
  console.log('PASS actual source-preserving snapshot, three-capability union and no active graph/bytes from import');
  const previous=new MemoryStore(ready.workspace,'phone'),before=await previous.read();
  const wire=await transport.pull(ready.token,0);
  while(wire.length<ready.events) {
    const page=await transport.pull(ready.token,wire.at(-1).sequence);
    assert(page.length>0 && wire.length+page.length<=1000);wire.push(...page);
  }
  assert(wire.some(event=>event.operation.payload?.feature==='reading_position'));
  await assert.rejects(previous.update(state=>old.receive(state,wire)));
  assert.deepEqual(await previous.read(),before);
  console.log('PASS previous receiver rejects new live content before whole-page state/cursor persistence');
  await engine.connect(ready.token);await engine.sync();
  let report=positionReport(await store.read(),ready.paper);
  assert.equal(report.positions[0].page,2);assert.equal(report.positions[0].document_hash,ready.source_hash);
  assert.equal(report.sources[0].id,ready.id);assert.deepEqual((await store.read()).outbox,[]);
  await engine.download(ready.paper);const primary=await engine.pdf(ready.paper);
  assert.equal(primary.sha256,ready.current_hash);assert.notEqual(primary.sha256,ready.source_hash);
  await engine.downloadArtifact(ready.id);const original=await engine.originalSource(ready.id);
  assert.equal(original.body.document_hash,ready.source_hash);
  assert.equal(original.blobs.get(ready.source_hash).length,ready.source_size);
  assert.deepEqual(await engine.pdf(ready.paper),primary);
  console.log('PASS real position metadata plus authenticated exact original A download leaves primary B unchanged');
  const offlineState=await store.read(),offline=new Engine(new MemoryStore(ready.workspace,'phone',offlineState),
    {transport:new Proxy({},{get(){throw Error('Offline read attempted network');}})});
  assert.equal(positionReport(await offline.store.read(),ready.paper).positions[0].page,2);
  assert.equal((await offline.originalSource(ready.id)).body.document_hash,ready.source_hash);
  assert.deepEqual(await offline.pdf(ready.paper),primary);
  console.log('PASS independent offline restart retains exact A/B bytes and recorded page without invented viewport');
  await next('position');await engine.sync();
  report=positionReport(await store.read(),ready.paper);assert.equal(report.positions[0].page,1);
  assert.deepEqual((await store.read()).outbox,[]);
  await next('delete');await engine.sync();assert.deepEqual(positionReport(await store.read(),ready.paper).positions,[]);
  console.log('PASS actual received update and known deletion suppress stale snapshot without echo or new position');
  await next('retire');await engine.sync();await assert.rejects(engine.originalSource(ready.id),/artifact_unavailable/);
  assert.deepEqual(positionReport(await store.read(),ready.paper).sources,[]);
  assert.deepEqual(await engine.pdf(ready.paper),primary);
  const retired=new Engine(new MemoryStore(ready.workspace,'phone',await store.read()));
  await assert.rejects(retired.originalSource(ready.id),/artifact_unavailable/);
  console.log('PASS original retirement suppresses cached access across restart, keeps primary bytes');
  await next('revoke');const revoked=await store.read();await assert.rejects(engine.sync(),/session_denied/);
  assert.deepEqual(await store.read(),revoked);assert.deepEqual(await engine.pdf(ready.paper),primary);
  console.log('PASS revoked session cannot sync and does not alter verified offline primary or state');
} finally {
  child.stdin.end('quit\n');
  const code=await new Promise(resolve=>{if(child.exitCode!==null){resolve(child.exitCode);return;}child.once('exit',resolve);setTimeout(()=>{child.kill();resolve(null);},5000).unref();});
  assert.equal(code,0,'Fixture did not close cleanly: '+errors);
}
