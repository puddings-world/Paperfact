/** Actual producer → authenticated Python HTTP → offline JavaScript reader. */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';
import assert from 'node:assert/strict';
import { HttpTransport } from './transport.mjs';
import { MemoryStore } from './store.mjs';
import { Engine } from './engine.mjs';
import { projection } from './domain.mjs';
import { chatExchanges } from './content.mjs';
if(!process.argv[2]) throw new Error('Pass the project Python executable.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./chat-service-fixture.py',import.meta.url)),...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
try {
  const ready=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('QA fixture did not start: '+errors)),15000);
    createInterface({input:child.stdout}).once('line',line=>{clearTimeout(timer);try {resolve(JSON.parse(line));}catch(error){reject(error);}});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error('QA fixture exited '+code+': '+errors));});
  });
  const store=new MemoryStore('qa-workspace','phone'), calls=[];
  const native=new HttpTransport(ready.url);
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{calls.push(key);return value.apply(target,args);}:value;}});
  const engine=new Engine(store,{transport});await engine.connect(ready.token);await engine.sync();
  const initial=await store.read();assert.equal(initial.cursor,ready.events);assert.deepEqual(initial.outbox,[]);
  const paper=projection(initial).papers[0], exchanges=chatExchanges(paper);
  assert.deepEqual(exchanges.map(e=>[e.question.data.body,e.answer.data.body]),[['Same question','First answer'],['Same question','Second answer']]);
  const actual=paper.research_content.filter(r=>r.feature==='chat').map(r=>({message_id:r.key,exchange_id:r.data.exchange_id,reply_to:r.data.reply_to,body:r.data.body})).sort((a,b)=>a.message_id.localeCompare(b.message_id));
  const shared=ready.shared.map(r=>({message_id:r.message_id,exchange_id:r.exchange_id,reply_to:r.reply_to,body:r.body})).sort((a,b)=>a.message_id.localeCompare(b.message_id));
  assert.deepEqual(actual,shared,'Bundle and synchronized mobile turn identities diverged');
  await engine.sync();assert.equal((await store.read()).cursor,initial.cursor);
  engine.disconnect();
  const reopened=new MemoryStore('qa-workspace','phone',JSON.parse(JSON.stringify(await store.read())));
  const offline=new Engine(reopened,{transport:new Proxy({}, {get(){throw new Error('Offline render attempted network');}})});
  assert.deepEqual(chatExchanges(projection(await offline.store.read()).papers[0]),exchanges);
  assert.deepEqual((await reopened.read()).outbox,[]);
  assert(calls.every(key=>['session_info','pull'].includes(key)),JSON.stringify(calls));
  console.log('PASS desktop QA producer → HTTP → mobile pairing, shared bundle IDs, offline restart, retry without AI/upload');
} finally {
  child.stdin.end('\n');
  if(child.exitCode===null) await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
