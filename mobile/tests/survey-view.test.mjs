import test from 'node:test';
import assert from 'node:assert/strict';
import {renderSurveys,SURVEY_COPY} from '../survey-view.mjs';
class Node{
  constructor(tag,attrs,children){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.events={};}
  append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
  addEventListener(name,fn){this.events[name]=fn;}set innerHTML(_){throw Error('executable HTML');}
  get text(){return this.children.map(child=>child instanceof Node?child.text:String(child)).join('\n');}
  find(tag){return this.tag===tag?this:this.children.filter(child=>child instanceof Node).map(child=>child.find(tag)).find(Boolean);}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children),tick=()=>new Promise(resolve=>setImmediate(resolve));
const collection={id:'list'},rows=[{id:'report',list_id:'list'}];
const result={body:{report:{inputs:{members:[{paper_id:'p',title:'Source title'}]},
  sources:[{paper_id:'p',state:'unavailable'}],sections:[{heading:'Research context',statements:[
    {text:'<script>literal research</script>',passages:[{quote:'<img src=x>',location:null}]}]}]}}};
test('empty selection stays empty; cached report and source records render as localized literal text',async()=>{
  const empty=el('div');renderSurveys(empty,null,rows,el);assert.equal(empty.children.length,0);
  for(const language of ['en','zh-TW']){
    const panel=el('div');renderSurveys(panel,collection,rows,el,{language,read:async()=>result});await tick();
    assert(panel.text.includes(SURVEY_COPY[language].title));assert(panel.text.includes('<script>literal research</script>'));
    assert(panel.text.includes('<img src=x>'));assert.equal(panel.find('button').hidden,true);
    assert.equal(panel.find('button').disabled,true);
  }
});
test('duplicate download is one job; failure permits retry, download status is visible and PDFs stay separate',async()=>{
  let resolve,calls=0,ready=false;const gate=new Promise(done=>resolve=done),panel=el('div');
  renderSurveys(panel,collection,rows,el,{canDownload:true,read:async()=>{if(!ready)throw Error('missing');return result;},
    download:async()=>{calls++;await gate;if(calls===1)throw Error('failed');ready=true;}});
  await tick();const button=panel.find('button'),job=button.events.click();await button.events.click();
  assert.equal(calls,1);assert.equal(button.disabled,true);assert(panel.text.includes(SURVEY_COPY.en.working));
  resolve();await job;assert(panel.text.includes(SURVEY_COPY.en.retry));assert.equal(button.disabled,false);
  await button.events.click();assert.equal(calls,2);assert.equal(button.hidden,true);
  assert(panel.text.includes(SURVEY_COPY.en.sourceNote));
});
test('navigation, account switching or close suppresses stale reads and late downloads',async()=>{
  for(const action of ['switch-list','switch-account','close']){
    let current=true,resolve;const pending=new Promise(done=>resolve=done),panel=el('div');
    renderSurveys(panel,collection,rows,el,{current:()=>current,canDownload:true,read:()=>pending,download:()=>pending});
    const button=panel.find('button'),job=button.events.click();current=false;const before=panel.text;
    resolve(result);await job;await tick();assert.equal(panel.text,before,action);
    assert(!panel.text.includes('literal research'));
  }
});
