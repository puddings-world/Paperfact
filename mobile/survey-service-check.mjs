/** Real native publisher -> authenticated ranges -> independent offline survey. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {Engine} from './engine.mjs';
import {MemoryStore} from './store.mjs';
import {projection} from './domain.mjs';
import {HttpTransport,CHUNK} from './transport.mjs';
if(!process.argv[2])throw Error('Pass project Python.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./survey-service-fixture.py',import.meta.url)),
  ...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',data=>errors+=data);
const lines=[],pending=[];
createInterface({input:child.stdout}).on('line',line=>{const next=pending.shift();if(next)next(line);else lines.push(line);});
const next=()=>new Promise((resolve,reject)=>{
  if(lines.length){resolve(JSON.parse(lines.shift()));return;}
  const timer=setTimeout(()=>reject(Error('Survey fixture timeout: '+errors)),45000);
  pending.push(line=>{clearTimeout(timer);resolve(JSON.parse(line));});
  child.once('exit',code=>{clearTimeout(timer);reject(Error('Survey fixture exited '+code+': '+errors));});
});
try{
  const ready=await next();assert(ready.body_size>CHUNK);
  const native=new HttpTransport(ready.url),calls=[];let interrupt=true;
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{
    calls.push([key,...(key==='blob_read'?[args[1],args[3]]:[])]);
    if(key==='blob_read'&&args[1]===ready.body_hash&&args[3]>0&&interrupt){interrupt=false;throw Error('fixture_interruption');}
    return value.apply(target,args);
  }:value;}});
  const store=new MemoryStore('survey-workspace','phone'),engine=new Engine(store,{transport});
  await engine.connect(ready.token);await engine.sync();
  const received=await store.read();assert.equal(received.cursor,ready.events);
  assert.equal(projection(received).surveys[0].id,ready.id);
  assert.deepEqual(received.artifactFiles,{});assert.deepEqual(received.outbox,[]);
  await assert.rejects(engine.survey(ready.id),/artifact_unavailable/);
  await assert.rejects(engine.downloadArtifact(ready.id),/fixture_interruption/);
  assert.equal((await store.read()).artifactFiles[ready.body_hash].chunks.length,1);
  assert.deepEqual((await store.read()).appliedArtifacts,{});
  calls.length=0;await engine.downloadArtifact(ready.id);
  assert.equal(calls.find(row=>row[0]==='blob_read')[2],CHUNK);
  const report=await engine.survey(ready.id);assert.equal(report.body.report.id,ready.report_id);
  assert.equal(report.semantic_validation,'not_performed');
  assert.equal(report.verification_scope,'report_bytes_and_record');
  assert.equal(report.body.report.sections[0].statements[0].passages.at(-1).location.state,'located');
  assert.equal(report.body.report.sections[0].statements[0].passages[0].location.state,'missing');
  await assert.rejects(engine.originalSource(ready.source_id),/artifact_unavailable/);
  const snapshot=await store.read();engine.disconnect();
  const offline=new Engine(new MemoryStore('survey-workspace','phone',snapshot),
    {transport:new Proxy({}, {get(){throw Error('Offline report tried network');}})});
  assert.equal((await offline.survey(ready.id)).body.report.id,ready.report_id);
  assert.deepEqual((await store.read()).files,{});
  console.log('PASS trusted native report >256KiB, exact resumed ranges, full source ledger and offline restart without PDF activation');
  await engine.connect(ready.token);child.stdin.write('retire\n');const retired=await next();
  await engine.sync();assert.equal((await store.read()).cursor,retired.events);
  assert.deepEqual(projection(await store.read()).surveys,[]);
  await assert.rejects(engine.survey(ready.id),/artifact_unavailable/);
  assert.deepEqual((await store.read()).outbox,[]);
  assert(calls.every(row=>['session_info','begin_session','pull','history_page','blob_read'].includes(row[0])),JSON.stringify([...new Set(calls.map(row=>row[0]))]));
  console.log('PASS owning list retirement prevents cached report access, without model calls or mobile writes');
}finally{
  child.stdin.end('\n');
  if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);
    setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
