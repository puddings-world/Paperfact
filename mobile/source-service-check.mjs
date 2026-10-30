/** Real Python publication -> authenticated ranges -> byte-bound offline source. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {Engine} from './engine.mjs';
import {MemoryStore} from './store.mjs';
import {projection} from './domain.mjs';
import {HttpTransport,CHUNK} from './transport.mjs';
if(!process.argv[2])throw Error('Pass project Python.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./source-service-fixture.py',import.meta.url)),
  ...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const lines=[],pending=[];
createInterface({input:child.stdout}).on('line',line=>{const resolve=pending.shift();if(resolve)resolve(line);else lines.push(line);});
const next=async()=>JSON.parse(await new Promise((resolve,reject)=>{
  if(lines.length){resolve(lines.shift());return;}
  const timer=setTimeout(()=>reject(Error('Source fixture did not respond: '+errors)),45000);
  pending.push(line=>{clearTimeout(timer);resolve(line);});
  child.once('exit',code=>{clearTimeout(timer);reject(Error('Source fixture exited '+code+': '+errors));});
}));
try {
  const ready=await next(),native=new HttpTransport(ready.url),calls=[];
  let interrupt=true;
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{
    calls.push([key,...(key==='blob_read'?[args[1],args[3]]:[])]);
    if(key==='blob_read' && args[1]===ready.source_hash && args[3]>0 && interrupt){interrupt=false;throw Error('fixture_connection_failed');}
    return value.apply(target,args);
  }:value;}});
  const store=new MemoryStore('source-workspace','phone'),engine=new Engine(store,{transport});
  await engine.connect(ready.token);await engine.sync();
  const metadata=await store.read(),view=projection(metadata);
  assert.equal(metadata.cursor,ready.events);assert.deepEqual(view.decks,[]);
  assert.equal(view.original_sources[0].id,ready.id);assert.equal(view.original_sources[0].document_hash,ready.source_hash);
  assert.deepEqual(metadata.artifactFiles,{});assert.deepEqual(metadata.outbox,[]);
  await assert.rejects(engine.originalSource(ready.id),/artifact_unavailable/);
  assert(!JSON.stringify(metadata).includes(ready.token));
  console.log('PASS actual Python source publisher -> authenticated metadata, separate from decks/current document');
  await engine.download(ready.paper);const primary=await engine.pdf(ready.paper);
  assert.equal(primary.sha256,ready.current_hash);assert.notEqual(primary.sha256,ready.source_hash);
  await assert.rejects(engine.downloadArtifact(ready.id),/fixture_connection_failed/);
  const partial=(await store.read()).artifactFiles[ready.source_hash];
  assert.equal(partial.verified,false);assert.equal(partial.chunks.length,1);
  await assert.rejects(engine.originalSource(ready.id),/artifact_unavailable/);
  calls.length=0;await engine.downloadArtifact(ready.id);
  assert.equal(calls.find(row=>row[0]==='blob_read' && row[1]===ready.source_hash)[2],CHUNK);
  const original=await engine.originalSource(ready.id);
  assert.equal(original.body.document_hash,ready.source_hash);assert.equal(original.verification_scope,'exact_bytes');
  assert.equal(original.blobs.get(ready.source_hash).length,ready.source_size);
  assert.deepEqual(await engine.pdf(ready.paper),primary);
  const snapshot=await store.read();engine.disconnect();
  const offline=new Engine(new MemoryStore('source-workspace','phone',snapshot),
    {transport:new Proxy({}, {get(){throw Error('Offline original attempted network');}})});
  assert.equal((await offline.originalSource(ready.id)).body.document_hash,ready.source_hash);
  assert.deepEqual(await offline.pdf(ready.paper),primary);
  console.log('PASS actual interrupted/resumed range closure, verified exact bytes and offline restart leave primary B unchanged');
  child.stdin.write('retire\n');const retired=await next();assert(retired.retired);
  await engine.connect(ready.token);await engine.sync();
  assert.equal((await store.read()).cursor,retired.events);
  assert.deepEqual(projection(await store.read()).original_sources,[]);
  await assert.rejects(engine.originalSource(ready.id),/artifact_unavailable/);
  assert.deepEqual(await engine.pdf(ready.paper),primary);
  const deleted=new Engine(new MemoryStore('source-workspace','phone',await store.read()));
  await assert.rejects(deleted.originalSource(ready.id),/artifact_unavailable/);
  assert(calls.every(row=>['session_info','pull','blob_read'].includes(row[0])));
  assert.deepEqual((await store.read()).outbox,[]);
  console.log('PASS canonical source retirement suppresses cached access offline without current PDF changes, AI or mobile uploads');
} finally {
  child.stdin.end('\n');
  if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
