/** One saved-first text Inbox. No URL activation or background research work. */
import {captureInbox,draftInbox,inboxReport,observeInbox,saveInbox,resolveInbox} from './inbox-ops.mjs';
import {INBOX_KINDS,INBOX_STATES,validateInbox} from './inbox-schema.mjs';
export const INBOX_COPY={
 en:{title:'Research Inbox',nav:'Inbox',hint:'Save a DOI, URL or short idea for desktop triage. Saving never searches, downloads, opens links or calls AI.',
 new:'New capture',save:'Save',close:'Close',refresh:'Refresh',edit:'Edit',remove:'Delete',restore:'Restore',
 idea:'Idea',doi:'DOI',url:'URL',state_new:'New',state_kept:'Keep',state_dismissed:'Dismissed',
 empty:'No saved captures.',draft:'Continue draft',draft_saved:'Draft saved on this device.',deleted:'Deleted capture',
 working:'Working locally...',saved:'Saved locally; synchronize explicitly with your existing connection.',
 conflict:'Your proposal is retained; newer research was kept.',resolved:'Decision saved locally.',failed:'Storage or validation failed. Your text is kept; retry.',
 changed:'Workspace or connection changed. Reopen Inbox; retained drafts stay in their original workspace.',
 cancel:'Cancel',confirm:'Confirm',confirm_delete:'Delete this capture? Saved history is retained.',confirm_restore:'Restore this capture as a new incarnation?',
 discard:'Discard this unsaved draft?',readonly:'Read-only snapshot; receive its full history before editing.',
 kept:'Keep current',incoming:'Use proposal',retained:'Retained proposals',sync_local:'Local',sync_pending:'Pending upload',sync_awaiting:'Awaiting receipt',sync_deferred:'Apply pending',sync_synced:'Synced',sync_conflict:'Retained conflict',
 page:'Showing at most 256 captures.',previous:'Previous',next:'Next'},
 'zh-TW':{resolved:'\u6c7a\u5b9a\u5df2\u5132\u5b58\u65bc\u672c\u6a5f\u3002',title:'\u7814\u7a76\u6536\u4ef6\u5323',nav:'\u6536\u4ef6\u5323',hint:'\u5132\u5b58 DOI\u3001\u7db2\u5740\u6216\u77ed\u69cb\u60f3\uff0c\u7a0d\u5f8c\u5728\u684c\u9762\u6574\u7406\u3002\u4e0d\u6703\u641c\u5c0b\u3001\u4e0b\u8f09\u3001\u958b\u555f\u9023\u7d50\u6216\u547c\u53eb AI\u3002',
 new:'\u65b0\u6536\u96c6',save:'\u5132\u5b58',close:'\u95dc\u9589',refresh:'\u91cd\u65b0\u8b80\u53d6',edit:'\u7de8\u8f2f',remove:'\u522a\u9664',restore:'\u9084\u539f',
 idea:'\u69cb\u60f3',doi:'DOI',url:'\u7db2\u5740',state_new:'\u5f85\u6574\u7406',state_kept:'\u4fdd\u7559',state_dismissed:'\u7565\u904e',
 empty:'\u5c1a\u7121\u5df2\u5132\u5b58\u7684\u6536\u96c6\u3002',draft:'\u7e7c\u7e8c\u8349\u7a3f',draft_saved:'\u8349\u7a3f\u5df2\u5132\u5b58\u65bc\u6b64\u88dd\u7f6e\u3002',deleted:'\u5df2\u522a\u9664\u7684\u6536\u96c6',
 working:'\u6b63\u5728\u672c\u6a5f\u8655\u7406...',saved:'\u5df2\u5132\u5b58\u65bc\u672c\u6a5f\uff1b\u53ef\u660e\u78ba\u9078\u64c7\u4f7f\u7528\u73fe\u6709\u9023\u7dda\u540c\u6b65\u3002',
 conflict:'\u63d0\u6848\u5df2\u4fdd\u7559\uff0c\u4e0d\u6703\u8986\u5beb\u8f03\u65b0\u7814\u7a76\u3002',failed:'\u5132\u5b58\u6216\u9a57\u8b49\u5931\u6557\u3002\u6587\u5b57\u4ecd\u4fdd\u7559\uff0c\u53ef\u91cd\u8a66\u3002',changed:'\u5de5\u4f5c\u5340\u6216\u9023\u7dda\u5df2\u8b8a\u66f4\u3002\u8acb\u91cd\u958b\u6536\u4ef6\u5323\uff1b\u8349\u7a3f\u4ecd\u4fdd\u7559\u5728\u539f\u5de5\u4f5c\u5340\u3002',
 cancel:'\u53d6\u6d88',confirm:'\u78ba\u8a8d',confirm_delete:'\u8981\u522a\u9664\u9019\u7b46\u6536\u96c6\u55ce\uff1f\u5df2\u5132\u5b58\u7684\u6b77\u53f2\u6703\u4fdd\u7559\u3002',confirm_restore:'\u8981\u4ee5\u65b0\u751f\u547d\u9031\u671f\u9084\u539f\u9019\u7b46\u6536\u96c6\u55ce\uff1f',
 discard:'\u8981\u6368\u68c4\u9019\u4efd\u5c1a\u672a\u5132\u5b58\u7684\u8349\u7a3f\u55ce\uff1f',readonly:'\u9019\u662f\u552f\u8b80\u5feb\u7167\uff1b\u8acb\u5148\u63a5\u6536\u5b8c\u6574\u6b77\u53f2\u518d\u7de8\u8f2f\u3002',
 kept:'\u4fdd\u7559\u76ee\u524d\u7248\u672c',incoming:'\u4f7f\u7528\u63d0\u6848',retained:'\u4fdd\u7559\u7684\u63d0\u6848',sync_local:'\u672c\u6a5f',sync_pending:'\u5f85\u4e0a\u50b3',sync_awaiting:'\u7b49\u5f85\u6536\u64da',sync_deferred:'\u5f85\u5957\u7528',sync_synced:'\u5df2\u540c\u6b65',sync_conflict:'\u4fdd\u7559\u885d\u7a81',
 page:'\u6bcf\u9801\u6700\u591a\u986f\u793a 256 \u7b46\u3002',previous:'\u4e0a\u4e00\u9801',next:'\u4e0b\u4e00\u9801'}
};
export const inboxLabel=language=>(INBOX_COPY[language]??INBOX_COPY.en).nav;
export function researchInboxDialog(el,{engine,language='en',current=()=>true,blocked=()=>false,onClose=()=>{},onSaved=()=>{}}) {
 const t=INBOX_COPY[language]??INBOX_COPY.en,dialog=el('dialog',{'aria-label':t.title}),body=el('div'),status=el('p',{role:'status'}),question=el('div');
 const kind=el('select',{'aria-label':t.title}),state=el('select',{'aria-label':t.state_new}),text=el('textarea',{'aria-label':t.title,rows:'5'});
 INBOX_KINDS.forEach(value=>kind.append(el('option',{value},t[value])));
 INBOX_STATES.forEach(value=>state.append(el('option',{value},t['state_'+value])));
 let disposed=false,pending=false,wantClose=false,scope=null,snapshot=null,report=null,form=null,dirty=false,durable=true,epoch=0,page=0,askResolve=null;
 let draftQueue=Promise.resolve(),activeWork=Promise.resolve();const controls=[];
 const valid=()=>!disposed&&!wantClose&&current();
 const say=key=>{if(!disposed)status.replaceChildren(t[key]??t.failed);};
 const newForm=()=>({itemId:crypto.randomUUID(),requestId:crypto.randomUUID(),kind:'idea',text:'',state:'new',createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),observed:{operation_id:null,incarnation:null,action:null},active:true,action:'put'});
 function fill(value) {form=structuredClone(value);kind.value=form.kind;state.value=form.state;text.value=form.text;dirty=!!form.text;durable=true;epoch++;enable();}
 const values=()=>({...form,kind:kind.value,text:text.value,state:state.value});
 function enable() {
  for(const control of [fresh,refresh,...controls])control.disabled=pending||!valid()||blocked()||!!askResolve;
  for(const input of [kind,state,text])input.disabled=pending||!valid()||!!askResolve;
  save.disabled=pending||!valid()||blocked()||!scope||!dirty||!!askResolve;save.replaceChildren(t[form?.action==='delete'?'remove':'save']);
  previous.disabled=pending||!valid()||page===0;
  next.disabled=pending||!valid()||!report||report.items.length<=(page+1)*256;
 }
 async function ask(key) {
  if(askResolve)return false;
  return new Promise(resolve=>{
   askResolve=value=>{askResolve=null;question.replaceChildren();enable();resolve(value);};
   const cancel=el('button',{type:'button',autofocus:'',onclick:()=>askResolve?.(false)},t.cancel);
   const yes=el('button',{type:'button',onclick:()=>askResolve?.(true)},t.confirm);
   question.replaceChildren(el('p',{},t[key]),cancel,yes);enable();cancel.focus?.();
  });
 }
 async function persist() {
  if(!form||!scope||!current()||disposed)return;
  const value=values(),version=epoch;durable=false;
  draftQueue=draftQueue.catch(()=>{}).then(()=>draftInbox(engine,scope,value,{slot:value.itemId,current:()=>!disposed&&current()}));
  try {await draftQueue;if(version===epoch){durable=true;say('draft_saved');}}
  catch {if(version===epoch){durable=false;say('failed');}}
 }
 function edited() {if(!form)return;dirty=true;epoch++;form.requestId=crypto.randomUUID();form.updatedAt=new Date().toISOString();void persist();enable();}
 for(const input of [kind,state,text])input.addEventListener('input',edited);
 async function load() {
  if(pending||!valid())return;pending=true;enable();say('working');
  try {
   scope??=await captureInbox(engine,current);const data=await engine.store.read();if(!valid())return;
   snapshot=data;report=inboxReport(data);render();
   if(!form) {const drafts=Object.values(report.drafts);fill(drafts.at(-1)??newForm());}
   say(report.items.length?'saved':'empty');
  } catch {say(current()?'failed':'changed');}finally{pending=false;enable();}
 }
 function render() {
  body.replaceChildren();controls.length=0;
  const drafts=Object.values(report.drafts);
  for(const draft of drafts) {const button=el('button',{type:'button',onclick:()=>void chooseDraft(draft)},t.draft);body.append(el('article',{class:'card'},el('p',{},draft.text),button));controls.push(button);}
  if(!report.items.length)body.append(el('p',{},t.empty));
  for(const row of report.items.slice(page*256,(page+1)*256)) {
   const card=el('article',{class:'card'},el('p',{},row.payload?.text??t.deleted),el('p',{},t[row.active?'state_'+row.payload.state:'deleted']),el('p',{},t['sync_'+row.status]??row.status));
   if(row.editable) {
    const edit=el('button',{type:'button',onclick:()=>void choose(row)},t[row.active?'edit':'restore']);card.append(edit);controls.push(edit);
    if(row.active){const remove=el('button',{type:'button',onclick:()=>void removeRow(row)},t.remove);card.append(remove);controls.push(remove);}
   } else card.append(el('p',{},t.readonly));
   body.append(card);
  }
  if(report.retained.length)body.append(el('h2',{},t.retained));
  for(const record of report.retained) {
   const card=el('article',{class:'card'},el('p',{},record.payload?.text??t.remove));
   if(record.source==='server')for(const [choice,label]of [['canonical','kept'],['incoming','incoming']]){const button=el('button',{type:'button',onclick:()=>void decide(record,choice)},t[label]);card.append(button);controls.push(button);}
   else {const keep=el('button',{type:'button',onclick:()=>void decide(record,'canonical')},t.kept),use=el('button',{type:'button',onclick:()=>void chooseProposal(record)},t.incoming);card.append(keep,use);controls.push(keep,use);}
   body.append(card);
  }
  enable();
 }
 async function mayLeave() {await draftQueue.catch(()=>{});return !dirty||durable||await ask('discard');}
 async function chooseDraft(draft) {if(pending||!valid()||!await mayLeave())return;fill(draft);say('draft_saved');}
 async function choose(row) {
  if(pending||!valid()||!await mayLeave())return;
  if(!row.active&&!await ask('confirm_restore'))return;
  const draft=report.drafts[row.id];
  fill(draft??{...newForm(),itemId:row.id,kind:row.payload?.kind??'idea',text:row.payload?.text??'',state:row.payload?.state??'new',createdAt:row.payload?.created_at??new Date().toISOString(),observed:observeInbox(snapshot,row.id),active:row.active});
  form.restore=!row.active;dirty=!!draft||!!form.restore;enable();
 }
 async function chooseProposal(record) {
  if(pending||!valid()||!await mayLeave())return;
  const currentRow=report.items.find(row=>row.id===record.itemId);
  if(!currentRow?.editable){say('changed');return;}
  if(!currentRow.active&&!await ask('confirm_restore'))return;
  const data=record.payload??currentRow.payload;if(!data){say('failed');return;}
  fill({...newForm(),itemId:record.itemId,kind:data.kind,text:data.text,state:data.state,createdAt:currentRow.payload?.created_at??data.created_at,observed:observeInbox(snapshot,record.itemId),active:currentRow.active,candidateId:record.id,restore:!currentRow.active,action:record.action});
  dirty=true;void persist();enable();
 }
 async function run(work,{clearForm=false}={}) {
  if(pending||!valid()||blocked())return false;pending=true;const version=epoch;enable();say('working');
  activeWork=(async()=>{
   let outcome='failed';
   try {await draftQueue.catch(()=>{});const result=await work();if(!valid())return result;outcome=result.status==='conflict'?'conflict':result.status==='resolved'?'resolved':'saved';try{onSaved(result);}catch{}
    if(clearForm&&['saved','resolved'].includes(result.status)&&version===epoch){fill(newForm());dirty=false;durable=true;}
    else if(result.status==='conflict')durable=true;
    say(result.status==='conflict'?'conflict':'saved');return result;
   } catch {outcome=current()?'failed':'changed';say(outcome);return null;}
   finally {pending=false;if(valid()){await load();say(outcome);}enable();}
  })();return activeWork;
 }
 async function saveForm() {
  if(!form||!dirty)return false;
  const value=values(),data={kind:value.kind,text:value.text,state:value.state,created_at:value.createdAt,updated_at:value.updatedAt};
  if(value.action!=='delete')try{validateInbox(data);}catch{say('failed');return false;}
  return run(()=>saveInbox(engine,{scope,current:valid,requestId:value.requestId,itemId:value.itemId,action:value.action??'put',payload:value.action==='delete'?null:data,
    observed:value.observed,restore:!!value.restore,candidateId:value.candidateId??null,draftSlot:value.itemId,notify:false}),{clearForm:true});
 }
 async function removeRow(row) {
  if(pending||!valid()||!await ask('confirm_delete'))return;
  const requestId=crypto.randomUUID(),observed=observeInbox(snapshot,row.id);
  return run(()=>saveInbox(engine,{scope,current:valid,requestId,itemId:row.id,action:'delete',observed,notify:false}));
 }
 async function decide(record,choice) {
  if(pending||!valid()||!await mayLeave())return;
  const currentRow=report.items.find(row=>row.id===record.itemId);let restore=false;
  if(choice==='incoming'&&record.action==='put'&&!currentRow?.active){restore=await ask('confirm_restore');if(!restore)return;}
  const requestId=crypto.randomUUID();return run(()=>resolveInbox(engine,record.id,{scope,current:valid,requestId,choice,restore,notify:false,observed:observeInbox(snapshot,record.itemId)}));
 }
 async function close() {
  if(disposed)return;askResolve?.(false);wantClose=true;enable();
  await Promise.allSettled([draftQueue,activeWork]);
  if(dirty&&!durable){wantClose=false;if(!await ask('discard')){enable();return;}wantClose=true;}
  disposed=true;dialog.close();
 }
 const fresh=el('button',{type:'button',onclick:()=>void(async()=>{if(pending||!valid()||!await mayLeave())return;fill(newForm());dirty=false;enable();})()},t.new);
 const save=el('button',{type:'button',onclick:()=>void saveForm()},t.save),refresh=el('button',{type:'button',onclick:()=>void load()},t.refresh),closeButton=el('button',{type:'button',onclick:()=>void close()},t.close);
 const previous=el('button',{type:'button',onclick:()=>{if(!pending&&page>0){page--;render();}}},t.previous),next=el('button',{type:'button',onclick:()=>{if(!pending){page++;render();}}},t.next);
 dialog.append(el('h1',{},t.title),el('p',{},t.hint),el('div',{class:'toolbar'},fresh,refresh,closeButton),body,
  el('div',{class:'toolbar'},kind,state),text,save,el('div',{class:'toolbar'},previous,next),status,question);
 dialog.addEventListener('cancel',event=>{event.preventDefault();if(askResolve){askResolve(false);return;}void close();});
 dialog.addEventListener('close',()=>{disposed=true;onClose();dialog.remove();});
 const check=()=>{if(!current()){body.replaceChildren();say('changed');}enable();};
 return {dialog,refresh:load,check,dispose:close,get pending(){return pending;},controls:{kind,state,text,save,fresh,refresh,close:closeButton,previous,next},get form(){return form?structuredClone(values()):null;}};
}
