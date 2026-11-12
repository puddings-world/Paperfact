/** Explicit local fake producer -> reference HTTP -> independent/offline mobile. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Engine} from './engine.mjs';
import {MemoryStore} from './store.mjs';
import {HttpTransport} from './transport.mjs';
import {projection} from './domain.mjs';
import {laterOutcomeText} from './later-outcomes.mjs';
import {SHELL} from './sw-policy.mjs';
import * as old from './tests/fixtures/pre-position-domain.mjs';
const root=process.argv[3]??fileURLToPath(new URL('../',import.meta.url));
const child=spawn(process.argv[2],[root+'/mobile/later-outcome-service-fixture.py',root],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let errors='',exited=false;const lines=[],pending=[];
child.stderr.on('data',b=>errors+=b);createInterface({input:child.stdout}).on('line',line=>{const next=pending.shift();if(next)next(line);else lines.push(line);});
const done=new Promise(resolve=>child.once('exit',code=>{exited=true;resolve(code);}));
async function ready(){if(lines.length)return JSON.parse(lines.shift());return JSON.parse(await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Fixture timeout: '+errors)),30000);pending.push(line=>{clearTimeout(timer);resolve(line);});done.then(code=>{clearTimeout(timer);reject(Error('Fixture exit '+code+': '+errors));});}));}
const shell=createServer(async(req,res)=>{const name=req.url;const path='.'+name;if(req.method!=='GET'||!SHELL.includes(path)){res.writeHead(404);res.end();return;}try{const data=await readFile(new URL('./'+name.slice(1),import.meta.url));res.writeHead(200,{'Content-Type':'text/javascript','Cache-Control':'no-store'});res.end(data);}catch{res.writeHead(404);res.end();}});
try{
 const info=await ready(),store=new MemoryStore(info.workspace,'phone'),engine=new Engine(store,{transport:new HttpTransport(info.url)});
 await engine.importProjection(info.projection);assert.equal((await store.read()).cursor,0);assert.deepEqual((await store.read()).outbox,[]);
 await engine.connect(info.token);await engine.sync();const state=await store.read(),view=projection(state);
 const available=view.papers.find(p=>p.id===info.paper),missing=view.papers.find(p=>p.title==='Unavailable original');
 assert.equal(available.later_outcome.body.source.document_hash,info.source_hash);assert.equal(missing.later_outcome.body.source.availability,'unavailable');
 assert.deepEqual(state.outbox,[]);assert(state.cursor>0);
 await engine.download(info.paper);const primary=await engine.pdf(info.paper);assert.equal(primary.sha256,info.current_hash);assert.notEqual(primary.sha256,info.source_hash);
 await engine.downloadArtifact(info.source_id);const original=await engine.originalSource(info.source_id);assert.equal(original.body.document_hash,info.source_hash);assert.equal(original.blobs.get(info.source_hash).length,info.source_size);
 assert.equal((await engine.pdf(info.paper)).sha256,info.current_hash);
 assert.match(laterOutcomeText(available.later_outcome,'en',info.current_hash),/another original version/);
 const offline=new Engine(new MemoryStore(info.workspace,'phone',await store.read()),{transport:new Proxy({},{get(){throw Error('Offline read touched transport');}})});
 assert.equal(projection(await offline.store.read()).papers.find(p=>p.id===info.paper).later_outcome.body.source.document_hash,info.source_hash);
 assert.equal((await offline.originalSource(info.source_id)).blobs.get(info.source_hash).length,info.source_size);assert.equal((await offline.pdf(info.paper)).sha256,info.current_hash);
 const legacy=new MemoryStore(info.workspace,'old-phone'),before=await legacy.read(),wire=await new HttpTransport(info.url).pull(info.token,0);
 await assert.rejects(legacy.update(s=>old.receive(s,wire)));assert.deepEqual(await legacy.read(),before);
 await new Promise(resolve=>shell.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+shell.address().port;
 const response=await fetch(base+'/later-outcomes.mjs');assert.equal(response.status,200);assert.equal(await response.text(),await readFile(new URL('./later-outcomes.mjs',import.meta.url),'utf8'));
 assert.equal((await fetch(base+'/later-outcomes.mjs?private=1')).status,404);assert.equal((await fetch(base+'/../src/paper_daily/store.py')).status,404);
 console.log('PASS 8 checkpoints: actual accepted available/missing queries, read-only projection, authenticated typed sync, exact original A, current B preserved, offline restart, old receiver atomic refusal, bounded shell HTTP bytes');
}finally{await new Promise(resolve=>shell.listening?shell.close(resolve):resolve());if(!exited)child.stdin.write('quit\n');const code=await done;assert.equal(code,0,errors);}
