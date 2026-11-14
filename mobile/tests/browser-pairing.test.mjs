import test from 'node:test';
import assert from 'node:assert/strict';
import {browserPairingPanel,PAIRING_COPY} from '../browser-pairing.mjs';
class Node {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.value=attrs.value??'';}
 append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
 setAttribute(key,value){this.attrs[key]=value;}focus(){this.focused=true;}
 get text(){return this.children.map(x=>x instanceof Node?x.text:String(x)).join(' ');}
 set innerHTML(_value){assert.fail('unsafe pairing HTML');}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children);
const gate=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const identity={workspace_id:'research',device_id:'phone'};

test('empty, repeated pairing and real phase transitions produce one verified handoff',async()=>{
 const waiting=gate(),phases=[],handed=[],calls={prepare:0,complete:0};
 const service={preparePairing:async()=>{calls.prepare++;await waiting.promise;return identity;},
  completePairing:async()=>{calls.complete++;return identity;}};
 const view=browserPairingPanel(el,{transport:service,onConnected:(...args)=>handed.push(args),onPending:v=>phases.push(v)});
 view.controls.packet.attrs.onkeydown({key:'Enter',isComposing:true,preventDefault:()=>assert.fail('IME submission')});
 assert.equal(await view.run('pair'),false);assert.deepEqual(calls,{prepare:0,complete:0});
 view.controls.packet.value='synthetic-private-packet';const pending=view.run('pair');
 assert(view.pending&&view.controls.pair.disabled&&view.controls.resume.disabled);
 assert.equal(view.controls.status.text,PAIRING_COPY.en.preparing);assert.equal(view.controls.packet.value,'');
 assert.equal(await view.run('pair'),false);assert.equal(await view.run('resume'),false);
 waiting.resolve();assert.equal(await pending,true);
 assert.deepEqual(calls,{prepare:1,complete:1});assert.deepEqual(phases,[true,false]);
 assert.equal(handed.length,1);assert.deepEqual(handed[0],[identity,service]);
 assert.equal(view.controls.status.text,PAIRING_COPY.en.ready);
});

test('lost reply resumes without preparing a new device and errors never echo payloads',async()=>{
 let prepared=0,completed=0,opened=0;
 const service={preparePairing:async()=>{prepared++;return identity;},completePairing:async()=>{
  if(completed++===0)throw Error('private server diagnostics');return identity;}};
 const view=browserPairingPanel(el,{transport:service,onConnected:()=>opened++});
 view.controls.packet.value='synthetic-private-packet';assert.equal(await view.run('pair'),false);
 assert.equal(view.controls.status.text,PAIRING_COPY.en.failed);
 assert.equal(await view.run('resume'),true);assert.equal(prepared,1);assert.equal(completed,2);assert.equal(opened,1);
 assert(!view.element.text.includes('synthetic-private-packet'));
});

test('close, stop and changed workspace refuse late identity delivery',async()=>{
 for(const reason of ['close','stop','workspace']){
  const waiting=gate();let current=true,opened=0,signal;
  const view=browserPairingPanel(el,{current:()=>current,onConnected:()=>opened++,transport:{
   completePairing:async value=>{signal=value;await waiting.promise;return identity;}}});
  const pending=view.run('resume');
  if(reason==='close')view.dispose();else if(reason==='stop')view.cancel();else current=false;
  waiting.resolve();assert.equal(await pending,false);assert.equal(opened,0);
  if(reason!=='workspace')assert(signal.aborted);
  if(reason==='stop')assert.equal(view.controls.status.text,PAIRING_COPY.en.cancelled);
 }
});

test('forget is explicit, cancelable, single-flight and bilingual; a busy service stays retryable',async()=>{
 assert.deepEqual(Object.keys(PAIRING_COPY.en).sort(),Object.keys(PAIRING_COPY['zh-TW']).sort());
 for(const language of ['en','zh-TW']){
  let forgotten=0,cleared=0,active=false,response='unsupported_service';const waiting=gate();
  const view=browserPairingPanel(el,{language,current:()=>active,onForgotten:()=>cleared++,transport:{
   forgetSession:async()=>{forgotten++;await waiting.promise;return {forgotten:true};},
   completePairing:async()=>{throw Error(response);}}});
  assert(view.controls.pair.disabled);active=true;view.refresh();assert(!view.controls.pair.disabled);
  assert.equal(await view.run('forget'),false);assert(view.askForget());assert(view.controls.keep.focused);
  view.keepConnection();assert.equal(forgotten,0);assert(view.controls.question.hidden);
  assert.equal(await view.run('resume'),false);assert.equal(view.controls.status.text,PAIRING_COPY[language].unsupported);
  response='rate_limited';assert.equal(await view.run('resume'),false);
  assert.equal(view.controls.status.text,PAIRING_COPY[language].throttled);
  view.askForget();const pending=view.run('forget');assert.equal(await view.run('forget'),false);
  waiting.resolve();assert.equal(await pending,true);assert.equal(forgotten,1);assert.equal(cleared,1);
  assert.equal(view.controls.status.text,PAIRING_COPY[language].forgotten);
 }
});
