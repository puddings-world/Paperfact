/** Actual ClaimJob -> authenticated HTTP -> read-only/offline/deletion browser projection. */
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import assert from 'node:assert/strict';
import {HttpTransport} from './transport.mjs';
import {MemoryStore} from './store.mjs';
import {Engine} from './engine.mjs';
import {projection} from './domain.mjs';
import {renderAnnotations} from './annotations.mjs';
import {translator} from './i18n.mjs';
import {validateClaims} from './claims.mjs';
if(!process.argv[2]) throw Error('Pass the project Python executable.');
const child=spawn(process.argv[2],[fileURLToPath(new URL('./claim-service-fixture.py',import.meta.url)),...(process.argv[3]?[process.argv[3]]:[])],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='';child.stderr.on('data',chunk=>errors+=chunk);
const lines=[], pending=[];
createInterface({input:child.stdout}).on('line',line=>{const resolve=pending.shift();if(resolve) resolve(line);else lines.push(line);});
const next=async()=>JSON.parse(await new Promise((resolve,reject)=>{
  if(lines.length) {resolve(lines.shift());return;}
  const timer=setTimeout(()=>reject(Error('Claim fixture did not respond: '+errors)),45000);
  pending.push(line=>{clearTimeout(timer);resolve(line);});
  child.once('exit',code=>{clearTimeout(timer);reject(Error('Claim fixture exited '+code+': '+errors));});
}));
const node=(tag,attrs={},...children)=>({tag,attrs,children,append(...items){this.children.push(...items);}});
try {
  const ready=await next(), calls=[], native=new HttpTransport(ready.url);
  const transport=new Proxy(native,{get(target,key){const value=target[key];return typeof value==='function'?(...args)=>{calls.push(key);return value.apply(target,args);}:value;}});
  for(const example of ready.variants) assert.equal(validateClaims(example.body),example.body,example.name);
  const store=new MemoryStore('qa-workspace','phone'), engine=new Engine(store,{transport});
  await engine.connect(ready.token);await engine.sync();
  const first=await store.read(), paper=projection(first).papers[0];
  const row=paper.research_content.find(item=>item.feature==='claims');
  assert.deepEqual(row.data,ready.claims.data);assert.equal(row.source_document_hash,ready.claims.source_document_hash);
  assert.equal(first.cursor,ready.events);assert.deepEqual(first.outbox,[]);
  assert(!JSON.stringify(first).includes(ready.token));
  const panel=node('main');renderAnnotations(panel,paper,node,translator('en'));
  const rendered=JSON.stringify(panel);
  assert(rendered.includes('Proposed judgment: supported'));
  assert(rendered.includes('Semantic support has not been verified'));
  await engine.sync();assert.equal((await store.read()).cursor,first.cursor);
  engine.disconnect();
  const reopened=new MemoryStore('qa-workspace','phone',JSON.parse(JSON.stringify(first)));
  const offline=new Engine(reopened,{transport:new Proxy({}, {get(){throw Error('Offline claim rendering attempted network');}})});
  assert.deepEqual(projection(await offline.store.read()).papers[0].research_content.find(item=>item.feature==='claims'),row);
  const offlinePanel=node('main');renderAnnotations(offlinePanel,projection(await offline.store.read()).papers[0],node,translator('en'));
  assert.equal(JSON.stringify(offlinePanel),rendered);
  child.stdin.write('delete\n');const removed=await next();assert(removed.deleted);
  await engine.connect(ready.token);await engine.sync();
  const after=await store.read();assert.equal(after.cursor,removed.events);
  assert(!projection(after).papers[0].research_content.some(item=>item.feature==='claims'));
  assert.deepEqual(after.outbox,[]);assert(calls.every(key=>['session_info','pull'].includes(key)));
  const deletedOffline=new MemoryStore('qa-workspace','phone',JSON.parse(JSON.stringify(after)));
  assert(!projection(await deletedOffline.read()).papers[0].research_content.some(item=>item.feature==='claims'));
  console.log('PASS actual claim producer -> authenticated HTTP -> source-bound read-only cards, offline restart, retry and canonical deletion without AI/upload');
} finally {
  child.stdin.end('\n');
  if(child.exitCode===null) await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{child.kill();resolve();},5000).unref();});
}
