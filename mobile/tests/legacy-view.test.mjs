import test from 'node:test';
import assert from 'node:assert/strict';
import {renderLegacyWorkflow} from '../legacy-view.mjs';
import {translator} from '../i18n.mjs';
class Node {
  constructor(tag,attrs,children){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.events={};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  addEventListener(name,fn){this.events[name]=fn;}
  set innerHTML(_){throw Error('executable HTML');}
  get text(){return this.children.map(c=>c instanceof Node?c.text:String(c)).join('\n');}
  find(tag){return this.tag===tag?this:this.children.filter(c=>c instanceof Node).map(c=>c.find(tag)).find(Boolean);}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children);
const paper={id:'p',legacy_queue:{state:'deferred',role:'manual',reason:'Exact reason'},reading_events:[
  {id:'e',data:{delivered_at:'2026-10-30T12:34:56+08:00',role:null,note:'Original note',brief:{}}}]};
const briefs=[{id:'f',paper_id:'p',event_id:'e'}],tick=()=>new Promise(r=>setImmediate(r));
test('history display has localized state, original prose and verified Markdown as literal text',async()=>{
  for(const lang of ['en','zh-TW']) {
    const panel=el('div');renderLegacyWorkflow(panel,paper,el,translator(lang),{briefs,read:async()=>({text:'<script>x</script>\r\n中文😀'})});
    await tick();assert(panel.text.includes('<script>x</script>\r\n中文😀'));assert(panel.text.includes('Original note'));
    assert(panel.text.includes('Exact reason'));assert(panel.text.includes(translator(lang)('legacyState_deferred')));
    assert.equal(panel.find('button').disabled,true);
  }
});
test('empty selection renders nothing and absent brief has no download action',()=>{
  const panel=el('div');renderLegacyWorkflow(panel,{id:'p'},el,translator('en'));assert.equal(panel.children.length,0);
  renderLegacyWorkflow(panel,paper,el,translator('en'));assert.equal(panel.find('button'),undefined);
});
for(const change of ['switch-paper','disconnect','close'])test('late read does not change retired display after '+change,async()=>{
  let resolve,current=true;const pending=new Promise(r=>resolve=r),panel=el('div');
  renderLegacyWorkflow(panel,paper,el,translator('en'),{briefs,read:()=>pending,current:()=>current});
  const before=panel.text;current=false;resolve({text:'late confidential answer'});await tick();assert.equal(panel.text,before);
});
test('duplicate download clicks share one action; failure permits retry and late close suppresses content',async()=>{
  let resolve,calls=0,current=true,ready=false;const panel=el('div'),pending=new Promise(r=>resolve=r);
  renderLegacyWorkflow(panel,paper,el,translator('en'),{briefs,canDownload:true,current:()=>current,
    read:async()=>{if(!ready)throw Error('unavailable');return {text:'verified'};},
    download:async()=>{calls++;await pending;if(calls===1)throw Error('interrupted');ready=true;}});
  const button=panel.find('button');const first=button.events.click();await button.events.click();assert.equal(calls,1);
  assert.equal(button.disabled,true);resolve();await first;assert.equal(button.disabled,false);
  await button.events.click();assert.equal(calls,2);assert(panel.text.includes('verified'));
  current=false;await button.events.click();assert.equal(calls,2);
});
for(const change of ['close','switch-connection'])test('active download cannot fill retired view after '+change,async()=>{
  let current=true,resolve,ready=false;const panel=el('div'),pending=new Promise(r=>resolve=r);
  renderLegacyWorkflow(panel,paper,el,translator('en'),{briefs,canDownload:true,current:()=>current,
    read:async()=>{if(!ready)throw Error('unavailable');return {text:'late downloaded content'};},
    download:async()=>{await pending;ready=true;}});
  await tick();const before=panel.text,button=panel.find('button'),job=button.events.click();
  current=false;resolve();await job;assert.equal(panel.text,before);assert(!panel.text.includes('late downloaded content'));
});
