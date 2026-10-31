/** Actual generated history enrollment -> absent tombstones -> HTTP/offline/retry. */
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import assert from 'node:assert/strict';
import {HttpTransport} from './transport.mjs';
import {MemoryStore} from './store.mjs';
import {Engine} from './engine.mjs';
import {projection} from './domain.mjs';
if(!process.argv[2]) throw Error('Pass the project Python executable.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./initial-deletion-service-fixture.py',import.meta.url)),...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const ready=new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(Error('Initial deletion fixture timed out: '+errors)),45000);
  createInterface({input:child.stdout}).once('line',line=>{clearTimeout(timer);resolve(JSON.parse(line));});
  child.once('exit',code=>{clearTimeout(timer);reject(Error('Initial deletion fixture exited '+code+': '+errors));});
});
try {
  const fixture=await ready,native=new HttpTransport(fixture.url),calls=[];
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{calls.push(key);return value.apply(target,args);}:value;}});
  const store=new MemoryStore(fixture.workspace,fixture.device),engine=new Engine(store,{transport});
  await engine.connect(fixture.token);await engine.sync();
  const state=await store.read(),view=projection(state);
  assert.equal(state.cursor,fixture.events);assert.equal(view.papers.length,1);
  assert.equal(view.papers[0].highlight_analysis_known,true);
  const content=view.papers[0].research_content ?? [];
  assert.equal(content.filter(row=>['claims','highlight_analysis','reading_links','research_questions'].includes(row.feature)).length,0);
  assert.deepEqual(content.map(row=>row.feature).sort(),['close_reading','dive']);
  assert(content.every(row=>row.data.body==='Original interpretation'));
  for(const id of fixture.tombstones) {
    assert.equal(state.graph['research_content/'+id].active,false);
    assert.equal(state.entities['research_content/'+id].operation.action,'delete');
    assert.deepEqual(state.entities['research_content/'+id].operation.payload,{});
  }
  assert.equal(fixture.tombstones.length,4);assert.deepEqual(state.outbox,[]);
  assert(!JSON.stringify(state).includes(fixture.token));
  await engine.sync();assert.equal((await store.read()).cursor,fixture.events);
  engine.disconnect();
  const offline=new MemoryStore(fixture.workspace,fixture.device,JSON.parse(JSON.stringify(state)));
  assert.deepEqual(projection(await offline.read()),view);
  assert(calls.every(key=>['session_info','pull'].includes(key)));
  console.log('PASS actual ClaimJob history enrollment -> four absent tombstones -> authenticated HTTP/offline/retry without fabricated content, AI or upload');
} finally {
  child.stdin.end('\n');
  if(child.exitCode===null) await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
