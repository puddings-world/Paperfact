import test from 'node:test';
import assert from 'node:assert/strict';
import {BrowserStorageProtection,storageProtectionPanel} from '../storage-protection.mjs';
import {messages,translator} from '../i18n.mjs';
const gate=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
class Node {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.isConnected=true;}
 setAttribute(key,value){this.attrs[key]=value;}
 set innerHTML(_value){assert.fail('unsafe HTML');}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children);

test('inspection is read-only, single-flight and does not request permission',async()=>{
 const wait=gate();let queries=0,requests=0;
 const control=new BrowserStorageProtection({persisted:()=>{queries++;return wait.promise;},persist:()=>{requests++;return true;}});
 const first=control.inspect();assert.equal(control.inspect(),first);assert.equal(queries,1);assert.equal(requests,0);
 wait.resolve(false);assert.equal((await first).status,'best_effort');assert.equal(requests,0);
});

test('explicit requests are synchronous, single-flight and an older query cannot replace the grant',async()=>{
 const query=gate(),grant=gate();let requests=0;
 const control=new BrowserStorageProtection({persisted:()=>query.promise,persist:()=>{requests++;return grant.promise;}});
 const inspection=control.inspect(),first=control.request();assert.equal(requests,1);
 assert.equal(control.request(),first);assert.equal(control.inspect(),first);
 grant.resolve(true);assert.equal((await first).status,'persistent');
 query.resolve(false);assert.equal((await inspection).status,'persistent');
 assert.deepEqual(control.snapshot(),{status:'persistent',phase:null,supported:true});
});

test('denial and provider errors stay distinct, bounded and explicitly retryable',async()=>{
 let result=false;
 const control=new BrowserStorageProtection({persisted:()=>false,persist:()=>{
  if(result==='error')throw Error('private browser diagnostics');return result;}});
 assert.equal((await control.request()).status,'best_effort');result='error';
 const failure=await control.request();assert.equal(failure.status,'unknown');
 assert(!JSON.stringify(failure).includes('private'));result=true;
 assert.equal((await control.request()).status,'persistent');
});

test('unsupported APIs or invalid boolean values cannot become a protection claim',async()=>{
 for(const storage of [undefined,{}, {persisted:()=>true}]) {
  const control=new BrowserStorageProtection(storage);
  assert.equal((await control.inspect()).status,'unsupported');assert.equal((await control.request()).status,'unsupported');
 }
 const control=new BrowserStorageProtection({persisted:()=>({granted:true}),persist:()=>'true'});
 assert.equal((await control.inspect()).status,'unknown');assert.equal((await control.request()).status,'unknown');
});

test('inspection after a later revocation replaces a remembered grant with current truth',async()=>{
 let persisted=true;const control=new BrowserStorageProtection({persisted:()=>persisted,persist:()=>true});
 await control.request();persisted=false;assert.equal((await control.inspect()).status,'best_effort');
});

test('actual panel is bilingual, stays usable after denial and visibly disables repeated requests',async()=>{
 for(const language of ['en','zh-TW']) {
  const grant=gate();let requests=0;
  const control=new BrowserStorageProtection({persisted:()=>false,persist:()=>{requests++;return grant.promise;}});
  const t=translator(language),panel=storageProtectionPanel(el,{controller:control,t});
  await panel.refresh();assert.equal(requests,0);assert.equal(panel.status.textContent,t('storageTemporary'));
  const pending=panel.request();assert.equal(requests,1);assert(panel.button.disabled);
  assert.equal(panel.button.attrs['aria-busy'],'true');assert.equal(panel.status.textContent,t('storageRequesting'));
  const repeated=panel.request();assert.equal(requests,1);grant.resolve(false);await pending;await repeated;
  assert.equal(panel.status.textContent,t('storageTemporary'));assert(!panel.button.disabled);
  assert.equal(panel.element.attrs['data-storage-state'],'best_effort');
 }
});

for(const reason of ['closed','workspace','detached'])test('late storage result cannot update a '+reason+' panel',async()=>{
 const grant=gate();let current=true;
 const control=new BrowserStorageProtection({persisted:()=>false,persist:()=>grant.promise});
 const panel=storageProtectionPanel(el,{controller:control,t:translator('en'),current:()=>current});
 await panel.refresh();const pending=panel.request(),before=panel.status.textContent;
 if(reason==='closed')panel.dispose();if(reason==='workspace')current=false;if(reason==='detached')panel.element.isConnected=false;
 grant.resolve(true);assert.equal(await pending,false);assert.equal(panel.status.textContent,before);
 assert.equal(control.snapshot().status,'persistent');
 assert.equal(await panel.request(),false);
});


test('Chinese storage labels contain real Han characters rather than encoding replacement marks',()=>{
 const t=translator('zh-TW');assert.equal(t('storageTitle'),'\u700f\u89bd\u5668\u96e2\u7dda\u5132\u5b58');
 for(const key of Object.keys(messages.en).filter(key=>key.startsWith('storage'))) {
  assert(/\p{Script=Han}/u.test(t(key)),key);assert(!t(key).includes('?'),key);
 }
});

test('unavailable browser API getters never break offline reading initialization',async()=>{
 const control=new BrowserStorageProtection({get persisted(){throw Error('restricted storage');},persist:()=>true});
 assert.equal((await control.inspect()).status,'unsupported');
 assert.equal((await control.request()).status,'unsupported');
});
