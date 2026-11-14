/** Real app, real IndexedDB and actual HttpOnly cookie through the isolated proxy. */
import {IndexedStore} from './store.mjs';
import {readWorkspaceHint,forgetWorkspaceHint} from './workspace-startup.mjs';
import {PAIRING_COPY} from './browser-pairing.mjs';
import {translator} from './i18n.mjs';
const results=[],errors=[],output=document.querySelector('#result'),assert=(value,message)=>{if(!value)throw Error(message);};
const until=async(check,label='UI')=>{const end=performance.now()+8000;while(!await check()){
 assert(performance.now()<end,'Timed out '+label);await new Promise(resolve=>setTimeout(resolve,20));}};
const fixture=await (await fetch('/__position_fixture')).json();
const inspect=async()=>(await fetch('/__position_command',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({command:'inspect'})})).json();
let frame,doc,identity;
const named=(root,label)=>[...root.querySelectorAll('button')].find(node=>node.textContent===label);
async function check(name,run){try{await run();results.push('PASS '+name);}catch(error){
 results.push('FAIL '+name+': '+error.message+' '+JSON.stringify({
  status:doc?.querySelector('.pairing-status')?.textContent,
  active:{tag:doc?.activeElement?.tagName,action:doc?.activeElement?.getAttribute('data-pairing')},
  busy:doc?.querySelector('#connection-trigger')?.disabled,
  buttons:[...(doc?.querySelectorAll('button')??[])].map(node=>node.textContent).slice(-22)}));}
 output.textContent=results.join('\n');}
async function openApp(){
 frame?.remove();frame=document.createElement('iframe');frame.title='Actual paired reader';document.body.append(frame);
 frame.src='./index.html';await until(()=>frame.contentDocument?.querySelector('#connection-trigger') &&
  !frame.contentDocument.querySelector('#connection-trigger').disabled,'app startup');doc=frame.contentDocument;
 frame.contentWindow.addEventListener('error',event=>errors.push(event.message));
 frame.contentWindow.addEventListener('unhandledrejection',event=>errors.push(String(event.reason)));
 return doc;
}
function connection(){doc.querySelector('#connection-trigger').click();return doc.querySelector('dialog.connection-dialog[open]');}
async function scoped(){const hint=readWorkspaceHint();assert(hint.status==='ready','missing local scope');
 const store=await IndexedStore.openExisting(hint.hint.workspace,hint.hint.device);assert(store,'missing cached research');
 try{return await store.read();}finally{store.close();}}
async function viewport(name){document.body.dataset.metrics=name;await until(()=>document.body.dataset.metricsReady===name,'viewport');}
async function capture(name){document.body.dataset.capture=name;await until(()=>document.body.dataset.captureReady===name,'screenshot');}
function fits(dialog){assert(dialog.getBoundingClientRect().width<=doc.documentElement.clientWidth,'dialog too wide');
 assert(dialog.scrollWidth<=dialog.clientWidth+1,'horizontal overflow');
 for(const button of dialog.querySelectorAll('.browser-pairing button'))if(button.getClientRects().length)
  assert(button.getBoundingClientRect().height>=40,'small touch target');}
forgetWorkspaceHint();
await check('actual mobile connection is singleton, keyboard-ready and concise at phone width',async()=>{
 await openApp();let dialog=connection();const select=dialog.querySelector('select');select.value='en';
 select.dispatchEvent(new frame.contentWindow.Event('change',{bubbles:true}));
 await until(()=>!dialog.isConnected,'old language dialog close');dialog=connection();
 for(let i=0;i<10;i++)doc.querySelector('#connection-trigger').click();
 assert(doc.querySelectorAll('dialog.connection-dialog').length===1,'duplicate connection windows');
 assert(doc.activeElement===dialog.querySelector('[data-pairing=packet]'),'pairing input not focused');
 assert(!dialog.querySelector('details').open,'manual setup is not collapsed');
 await viewport('phone-en');fits(dialog);await capture('phone-en');
});
await check('real cookie pairs once, opens research and never exposes credentials to JavaScript storage',async()=>{
 const input=doc.querySelector('[data-pairing=packet]');input.value=fixture.invitation;
 input.focus();document.body.dataset.keyboard='pair-en';
 await until(()=>!doc.querySelector('dialog.connection-dialog')&&!doc.querySelector('#connection-trigger')?.disabled&&
  doc.body.textContent.includes('Synthetic paired research'),'paired workspace');
 const report=await inspect();assert(report.devices===2,'duplicate device enrollment');
 const state=await scoped();identity={workspace:state.workspace,device:state.device};
 assert(state.workspace===fixture.workspace&&Object.keys(state.entities).length>=3,'wrong research scope');
 assert(!doc.cookie.includes('paperfact-device'),'HttpOnly cookie exposed to script');
 assert(!JSON.stringify(state).includes(JSON.parse(fixture.invitation).code),'invitation in research storage');
});
await check('saved note survives page reload without auto-auth and reconnect uses the same device',async()=>{
 doc.querySelector('.paper-card').click();doc.querySelector('#tab-notes').click();
 const t=translator(doc.documentElement.lang);named(doc,'+ '+t('newNote')).click();
 const editor=doc.querySelector('#note-editor');editor.value='A durable browser pairing note';
 editor.dispatchEvent(new frame.contentWindow.Event('input',{bubbles:true}));named(doc,t('save')).click();
 await until(async()=>(await scoped()).outbox.some(row=>row.operation?.payload?.body==='A durable browser pairing note'),'saved note');
 const saved=await scoped();assert(saved.outbox.length===1,'local save was not queued exactly once');
 const before=await inspect(),requests=await (await fetch('/__position_requests')).json();
 await navigator.serviceWorker.ready;
 document.body.dataset.offlineReady='true';await until(()=>document.body.dataset.offlineActive==='true','offline mode');
 await openApp();
 const offline=await scoped();assert(offline.outbox.length===1&&
  offline.outbox[0].operation.payload.body==='A durable browser pairing note','offline reload lost saved work');
 document.body.dataset.onlineReady='true';await until(()=>document.body.dataset.onlineActive==='true','online mode');
 assert((await inspect()).events===before.events,'reload uploaded private work automatically');
 assert((await (await fetch('/__position_requests')).json()).length===requests.length,'offline reopen authenticated automatically');
 connection();doc.querySelector('[data-pairing=resume]').click();
 await until(async()=>!doc.querySelector('dialog.connection-dialog')&&!doc.querySelector('#connection-trigger')?.disabled&&
  (await scoped()).outbox.length===0,'reconnect sync');
 const after=await scoped();assert(after.workspace===identity.workspace&&after.device===identity.device,'reconnect changed device');
 assert(Object.values(after.entities).some(row=>row.operation?.payload?.body==='A durable browser pairing note'),'accepted note missing from received research');
 const report=await inspect();assert(report.devices===2&&report.notes.includes('A durable browser pairing note'),'reconnect lost note or minted device');
});
await check('Traditional Chinese forget confirmation preserves cached research and reconnect reports missing session',async()=>{
 let dialog=connection();const select=dialog.querySelector('select');select.value='zh-TW';
 select.dispatchEvent(new frame.contentWindow.Event('change',{bubbles:true}));
 await until(()=>!dialog.isConnected,'old language dialog close');dialog=connection();
 await viewport('phone-zh');fits(dialog);await capture('phone-zh');
 const before=JSON.stringify(await scoped());
 dialog.querySelector('[data-pairing=forget]').click();assert(doc.activeElement===dialog.querySelector('[data-pairing=keep]'),'forget does not default to keep');
 dialog.querySelector('[data-pairing=keep]').click();assert(JSON.stringify(await scoped())===before,'cancel changed research');
 dialog.querySelector('[data-pairing=forget]').click();dialog.querySelector('[data-pairing=confirm]').click();
 await until(()=>dialog.querySelector('.pairing-status').textContent===PAIRING_COPY['zh-TW'].forgotten,'forget completion');
 assert(JSON.stringify(await scoped())===before,'forget changed research');
 assert(!dialog.querySelector('[data-pairing=pair]').disabled,'cannot pair after forgetting');
 dialog.querySelector('[data-pairing=resume]').click();
 await until(()=>dialog.querySelector('.pairing-status').textContent===PAIRING_COPY['zh-TW'].denied,'missing cookie notice');
 assert((await inspect()).devices===2&&JSON.stringify(await scoped())===before,'missing cookie changed local state');
 assert(errors.length===0,'browser errors: '+errors.join(';'));
});
output.textContent=results.join('\n');document.body.dataset.result=results.some(line=>line.startsWith('FAIL'))?'fail':'pass';
