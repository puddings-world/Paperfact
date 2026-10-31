/** Actual nullable-list enrollment -> HTTP/offline/retry. */
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import assert from 'node:assert/strict';
import {HttpTransport} from './transport.mjs';
import {MemoryStore} from './store.mjs';
import {Engine} from './engine.mjs';
import {projection} from './domain.mjs';
if(!process.argv[2]) throw Error('Pass the project Python executable.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./nullable-list-service-fixture.py',import.meta.url)),...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const ready=new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(Error('Nullable list fixture timed out: '+errors)),45000);
  createInterface({input:child.stdout}).once('line',line=>{clearTimeout(timer);resolve(JSON.parse(line));});
  child.once('exit',code=>{clearTimeout(timer);reject(Error('Nullable list fixture exited '+code+': '+errors));});
});
try {
  const fixture=await ready,native=new HttpTransport(fixture.url),calls=[];
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{calls.push(key);return value.apply(target,args);}:value;}});
  const store=new MemoryStore(fixture.workspace,fixture.device),engine=new Engine(store,{transport});
  await engine.connect(fixture.token);await engine.sync();
  const state=await store.read(),view=projection(state);
  assert.equal(state.cursor,fixture.events);
  assert.equal(view.lists.length,3);
  const observed=Object.fromEntries(view.lists.map(row=>[row.id,row.note]));
  assert.deepEqual(observed,fixture.expected);
  assert.deepEqual(state.outbox,[]);
  assert(!JSON.stringify(state).includes(fixture.token));
  await engine.sync();assert.equal((await store.read()).cursor,fixture.events);
  engine.disconnect();
  const offline=new MemoryStore(fixture.workspace,fixture.device,JSON.parse(JSON.stringify(state)));
  assert.deepEqual(projection(await offline.read()),view);
  assert(calls.every(key=>['session_info','pull'].includes(key)));
  console.log('PASS actual SQL NULL/empty/whitespace list enrollment -> authenticated HTTP/PWA/offline/retry without coercion, AI or upload');
} finally {
  child.stdin.end('\n');
  if(child.exitCode===null) await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
