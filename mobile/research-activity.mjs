/** Existing received records only; no last-opened/page tracking or network. */
import {active,keyOf,projection,stable,validateEvent,optimistic} from './domain.mjs';
const WINDOW=200,MAX_BYTES=8*1024**2,HASH=/^[0-9a-f]{64}$/;
const copy=structuredClone,expect=value=>{if(!value)throw Error('activity_unavailable');};
export const ACTIVITY_COPY={
  en:{title:'Research activity',nav:'Activity',continue:'Continue reading',recent:'Recent changes',
    coverage:'Recorded reading and note updates, in received order. This is not your last opened paper or PDF page.',
    echo:'Your accepted echoes are hidden in Recent changes; retained conflicts stay visible. File metadata is not a download.',
    native:'The mobile PDF viewer does not report its viewport. A saved note can be opened only with its matching PDF already open.',
    open:'Open paper',note:'Open saved note',close:'Close',refresh:'Refresh',empty:'No recorded activity in this window.',
    unavailable:'Activity is unavailable. Refresh to try again.',changed:'Workspace or record changed. Reopen activity.',
    drafts:'Finish the active task or save your draft first. Your draft is kept.',source:'Open the matching current PDF first.',
    applied:'Applied locally',accepted_history:'Accepted history',accepted_pending:'Accepted; local apply pending',
    conflict_retained:'Retained conflict',resolved:'Resolution recorded',manifest_waiting:'Metadata applied; verified files pending',
    binding_recorded:'File binding recorded; open to check availability',hidden:'Unavailable in this context',
    working:'Reading local records…',opened:'Paper opened.',note_opened:'Saved note opened; the PDF page was not moved.'},
  'zh-TW':{title:'研究動態',nav:'動態',continue:'繼續閱讀',recent:'最近變更',
    coverage:'依接收順序顯示已記錄的閱讀與筆記更新，不代表最後開啟的論文或 PDF 頁碼。',
    echo:'最近變更會隱藏此裝置已接受的回傳紀錄，但仍顯示保留的衝突。檔案資訊不代表已下載。',
    native:'手機 PDF 閱讀器無法回報目前顯示位置。開啟已儲存的筆記需要先開啟相符的 PDF。',
    open:'開啟論文',note:'開啟已儲存的筆記',close:'關閉',refresh:'重新整理',empty:'目前範圍沒有已記錄的動態。',
    unavailable:'無法讀取動態，請重新整理後再試。',changed:'工作區或紀錄已變更，請重新開啟動態。',
    drafts:'請先完成目前工作或儲存草稿，草稿仍保留。',source:'請先開啟相符的目前 PDF。',
    applied:'已套用至本機',accepted_history:'已接受的歷史紀錄',accepted_pending:'已接受，等待本機套用',
    conflict_retained:'已保留的衝突',resolved:'已記錄解決方式',manifest_waiting:'已套用檔案資訊，等待驗證檔案',
    binding_recorded:'已記錄檔案綁定，開啟時仍會檢查可用性',hidden:'目前內容已不可用',
    working:'讀取本機紀錄中…',opened:'已開啟論文。',note_opened:'已開啟儲存的筆記，尚未移動 PDF 頁碼。'}
};
export const activityLabel=language=>(ACTIVITY_COPY[language]??ACTIVITY_COPY.en).nav;
function recentWindow(receipts) {
  // Min-heap bounds extra memory even when the existing journal is long.
  const heap=[];let count=0;
  const swap=(a,b)=>{[heap[a],heap[b]]=[heap[b],heap[a]];};
  for(const key in receipts) {
    if(!Object.hasOwn(receipts,key))continue;
    const event=receipts[key];expect(Number.isSafeInteger(event.sequence)&&event.sequence>0);count++;
    if(heap.length<WINDOW){heap.push(event);let i=heap.length-1;while(i>0){const p=(i-1)>>1;if(heap[p].sequence<=heap[i].sequence)break;swap(p,i);i=p;}}
    else if(event.sequence>heap[0].sequence){heap[0]=event;let i=0;while(true){let j=i,l=i*2+1,r=l+1;if(l<heap.length&&heap[l].sequence<heap[j].sequence)j=l;if(r<heap.length&&heap[r].sequence<heap[j].sequence)j=r;if(j===i)break;swap(i,j);i=j;}}
  }
  return {events:heap.sort((a,b)=>b.sequence-a.sequence),has_more:count>WINDOW};
}
export function activityReport(state) {
  const {events,has_more}=recentWindow(state.receipts),data=projection(state),effective=optimistic(state),seen=new Set(),seenPapers=new Set();
  const recent=[],continuation=[],pending=new Set(state.outbox.map(row=>keyOf(row.operation.entity_type,row.operation.entity_id)));
  let bytes=0;
  for(const event of events) {
    bytes+=new TextEncoder().encode(JSON.stringify(event)).length;expect(bytes<=MAX_BYTES);
    validateEvent(event,state.workspace);expect(event.sequence<=state.cursor&&!seen.has(event.sequence));seen.add(event.sequence);
    const op=event.operation,key=keyOf(op.entity_type,op.entity_id),head=state.entities[key],live=active(effective,op.entity_type,op.entity_id);
    const current=head?.revision===event.sequence,applied=current&&!pending.has(key),conflict=event.outcome==='conflict';
    const owner=op.entity_type==='paper'?op.entity_id:op.payload.paper_id??(op.payload.scope?.kind==='paper'?op.payload.scope.id:null)??op.parents?.find(p=>p.kind==='paper')?.id;
    const parent=op.parents?.find(p=>p.kind==='paper'&&p.id===owner),incarnation=op.entity_type==='paper'?op.incarnation:parent?.incarnation;
    const paper=data.papers.find(p=>p.id===owner),visible=paper&&active(effective,'paper',owner)&&effective.graph[keyOf('paper',owner)].incarnation===incarnation;
    let status;
    if(conflict)status='conflict_retained';
    else if(!current||(!live&&op.action==='put'))status='accepted_history';
    else if(!applied)status='accepted_pending';
    else if(['paper_document','research_file'].includes(op.entity_type)&&op.action==='put') {
      const bound=op.entity_type==='research_file'?stable(state.appliedArtifacts?.[op.entity_id]?.operation)===stable(op):
        state.files[op.payload.sha256]?.verified===true&&state.files[op.payload.sha256].size===op.payload.size;
      status=bound?'binding_recorded':'manifest_waiting';
    } else status=live||op.action==='delete'?'applied':'accepted_history';
    const row={sequence:event.sequence,operation_id:op.operation_id,entity_type:op.entity_type,entity_id:op.entity_id,
      incarnation:op.incarnation??null,action:op.action,paper_id:visible?owner:null,paper_incarnation:visible?incarnation:null,
      title:visible?Array.from(String(paper.title??'')).slice(0,160).join(''):'',origin:op.device_id===state.device?'this_device':'other_device',
      status,resolved:!!state.conflicts[op.operation_id]?.resolvedBy,resume:null};
    if(recent.length<50&&(conflict||row.origin==='other_device'))recent.push(row);
    if(!conflict&&current&&live&&applied&&visible&&op.action==='put'&&['note','reading_state'].includes(op.entity_type)&&
       !seenPapers.has(owner)&&continuation.length<20) {
      const suggestion=copy(row),anchor=op.payload.anchor;
      if(op.entity_type==='note'&&anchor&&typeof anchor.document_hash==='string'&&HASH.test(anchor.document_hash))
        suggestion.resume={note_id:op.entity_id,source_hash:anchor.document_hash,anchor:copy(anchor)};
      continuation.push(suggestion);seenPapers.add(owner);
    }
  }
  return {workspace_id:state.workspace,device_id:state.device,cursor:state.cursor,recent,continue:continuation,
    window:events.length,has_more,coverage:'received_note_reading_updates',available:true};
}
export function canOpenSavedNote(state,row,loaded) {
  const target=state.entities[keyOf('paper_document',row.paper_id)]?.operation;
  return !!(row.resume&&loaded?.paper_id===row.paper_id&&typeof loaded.hash==='string'&&HASH.test(loaded.hash)&&
    row.resume.source_hash===loaded.hash&&target?.action==='put'&&active(state,'paper_document',row.paper_id)&&
    target.payload.sha256===loaded.hash);
}
export async function activateActivity({store,row,locate=false,current=()=>true,blocked=()=>false,loaded=()=>null,open,openNote}) {
  if(!current())return 'changed';if(blocked())return 'drafts';
  await store.read();if(!current())return 'changed';if(blocked())return 'drafts';
  const state=await store.read();if(!current())return 'changed';if(blocked())return 'drafts';
  const report=activityReport(state),fresh=[...report.continue,...report.recent].find(item=>item.operation_id===row.operation_id&&item.sequence===row.sequence);
  if(!fresh?.paper_id||fresh.paper_id!==row.paper_id||fresh.paper_incarnation!==row.paper_incarnation)return 'changed';
  if(locate) {
    if(Object.hasOwn(state.drafts,row.resume?.note_id??''))return 'drafts';
    if(!fresh.resume||stable(fresh.resume)!==stable(row.resume)||!canOpenSavedNote(state,fresh,loaded()))return 'source';
    if(!current()||blocked())return 'changed';openNote(fresh.paper_id,fresh.resume.note_id);return 'note_opened';
  }
  if(!current()||blocked())return 'changed';open(fresh.paper_id);return 'opened';
}
export function researchActivityDialog(el,{language='en',read,current=()=>true,blocked=()=>false,canNote=()=>false,activate,onClose=()=>{}}) {
  const t=ACTIVITY_COPY[language]??ACTIVITY_COPY.en,dialog=el('dialog',{'aria-label':t.title}),body=el('div'),status=el('p',{role:'status'});
  let disposed=false,pending=false;
  const valid=()=>!disposed&&current(),say=key=>{if(valid())status.replaceChildren(t[key]??t.unavailable);};
  const refresh=el('button',{type:'button',onclick:()=>void load()},t.refresh),close=el('button',{type:'button',onclick:()=>dialog.close()},t.close);
  const controls=[];
  const enable=()=>{refresh.disabled=pending||!valid();for(const [button,row,note]of controls)button.disabled=pending||!valid()||blocked()||!row.paper_id||(note&&!canNote(row));};
  async function action(row,note) {
    if(pending||!valid())return;if(blocked()){say('drafts');return;}pending=true;enable();
    try {const result=await activate(row,note);if(disposed)return;if(['opened','note_opened'].includes(result))dialog.close();else if(valid())say(result);}
    catch{say('unavailable');}finally{pending=false;enable();}
  }
  async function load() {
    if(pending||!valid())return;pending=true;say('working');enable();
    try {
      const report=await read();if(!valid())return;body.replaceChildren();controls.length=0;
      for(const key of ['continue','recent']) {
        const section=el('section',{},el('h2',{},t[key]));body.append(section);
        if(!report[key].length)section.append(el('p',{},t.empty));
        for(const row of report[key]) {
          const card=el('article',{class:'card'},el('h3',{},row.title||t.hidden),el('p',{},`#${row.sequence} · ${t[row.status]}`));
          if(row.resolved)card.append(el('p',{},t.resolved));
          const open=el('button',{type:'button',onclick:()=>void action(row,false)},t.open);card.append(open);controls.push([open,row,false]);
          if(key==='continue'&&row.resume){const note=el('button',{type:'button',onclick:()=>void action(row,true)},t.note);card.append(note);controls.push([note,row,true]);}
          section.append(card);
        }
      }
      status.replaceChildren('');
    }catch{say('unavailable');}finally{pending=false;enable();}
  }
  dialog.append(el('h1',{},t.title),el('p',{},t.coverage),el('p',{},t.echo),el('p',{},t.native),
    el('div',{class:'toolbar'},refresh,close),status,body);
  dialog.addEventListener('close',()=>{disposed=true;onClose();dialog.remove();});
  const check=()=>{if(!disposed&&!current()){body.replaceChildren();controls.length=0;status.replaceChildren(t.changed);}enable();};
  return {dialog,refresh:load,check,dispose:()=>{disposed=true;dialog.close();},get pending(){return pending;}};
}
