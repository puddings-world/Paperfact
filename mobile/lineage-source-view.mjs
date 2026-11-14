/** Read-only exact-original dialog; closing revokes local presentation, not sent bytes. */
import {openLineageSource,lineageSourceForDelivery} from './lineage-originals.mjs';
export const SOURCE_COPY={
 en:{title:'Analysis original',scope:'This is the exact saved source version, separate from the current PDF.',
  open:'Open saved original',download:'Download original',close:'Close',working:'Checking saved original...',
  downloading:'Downloading and checking original...',missing:'Original is not stored on this device. Download it while connected.',
  ready:'Verified original ready. Quote location does not certify the research claim.',
  changed:'The research, account or selected paper changed. Close and reopen this original.',
  failed:'Could not verify this original. Check the connection and try again.',preview:'Preview PDF',link:'Open verified PDF',unavailable:'No original was captured.'},
 'zh-TW':{title:'分析使用的原文',scope:'這是分析保存的原文版本，與目前 PDF 分開顯示。',
  open:'開啟已保存原文',download:'下載原文',close:'關閉',working:'正在核對已保存原文…',
  downloading:'正在下載並核對原文…',missing:'此裝置尚未保存原文，請連線後下載。',
  ready:'原文版本已核對。引句定位不代表研究主張已經驗證。',
  changed:'研究內容、帳號或論文已變更，請關閉後重新開啟。',
  failed:'無法核對原文，請確認連線後再試。',preview:'展開 PDF 預覽',link:'開啟已核對 PDF',unavailable:'這份分析未保存原文。'}
};
export function lineageSourceDialog(el,{engine,paper,row,sourceId,page=null,language='en',
 current=()=>true,connected=()=>false,available=()=>true,onClose=()=>{},actions={open:openLineageSource,deliver:lineageSourceForDelivery},
 urls=URL}={}){
 const t=SOURCE_COPY[language]??SOURCE_COPY.en,abort=new AbortController();
 const source=row.body.report.sources.find(s=>s.id===sourceId);
 let disposed=false,pending=false,url=null,lease=null;
 const live=()=>!disposed&&current();
 const status=el('p',{class:'notice',role:'status','aria-live':'polite'}),output=el('div',{});
 const open=el('button',{type:'button',onclick:()=>void load(false)},t.open),
  download=el('button',{type:'button',onclick:()=>void load(true)},t.download),
  close=el('button',{type:'button',onclick:dispose,autofocus:''},t.close);
 const dialog=el('dialog',{class:'lineage-source-dialog','aria-label':t.title},el('h2',{},t.title),
  el('p',{class:'prose'},source?.identity.title??''),el('p',{class:'muted'},t.scope),
  el('code',{class:'lineage-version'},source?.document_hash??''),status,
  el('div',{class:'toolbar'},open,download,close),output);
 const opener=dialog.ownerDocument?.activeElement;
 const controls={open,download,close,status,output};
 function state(){open.disabled=pending||disposed||!available()||source?.availability!=='available';
  download.disabled=open.disabled||!connected();open.hidden=Boolean(lease);download.hidden=Boolean(lease);dialog.setAttribute('aria-busy',String(pending));}
 function clear(){if(url!==null){urls.revokeObjectURL(url);url=null;}output.replaceChildren();}
 async function load(fetch){
  if(pending||disposed||!available()||source?.availability!=='available'||fetch&&!connected())return;
  pending=true;state();status.replaceChildren(fetch?t.downloading:t.working);
  try{
   const selected=await actions.open(engine,paper,row,sourceId,{download:fetch,current:live,signal:abort.signal});
   if(!live())return;
   const bytes=await actions.deliver(engine,selected,{current:live,signal:abort.signal});
   if(!live())return;
   clear();lease=selected;url=urls.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
   const located=Number.isInteger(page)&&page>=1&&page<=selected.page_count?page:null;
   const href=url+(located?'#page='+located:'');
   output.append(el('a',{href,target:'_blank',rel:'noopener',class:'source-open-link'},t.link),
    el('details',{class:'source-preview'},el('summary',{},t.preview),
     el('object',{data:href,type:'application/pdf',class:'pdf-frame','aria-label':t.title},
      el('a',{href,target:'_blank',rel:'noopener'},t.link))));
   status.replaceChildren(t.ready);
  }catch(error){
   if(!live())return;
   clear();lease=null;
   status.replaceChildren(error.message==='artifact_unavailable'?t.missing:
    /stale|cancelled|lineage_source_unavailable/.test(error.message)?t.changed:t.failed);
  }finally{pending=false;if(!disposed&&!current())dispose();else if(!disposed)state();}
 }
 function dispose(){if(disposed)return;disposed=true;abort.abort();clear();dialog.close();dialog.remove();if(current()&&opener?.isConnected&&!opener.disabled)opener.focus({preventScroll:true});onClose();}
 async function refresh(){
  if(disposed)return;
  if(!current()){dispose();return;}
  if(lease){try{await actions.deliver(engine,lease,{current:live,signal:abort.signal});}
   catch{if(live()){clear();lease=null;status.replaceChildren(t.changed);}}}
  if(!current()){dispose();return;}
  state();
 }
 dialog.addEventListener('cancel',event=>{event.preventDefault();dispose();});
 dialog.addEventListener('close',dispose);state();
 if(source?.availability!=='available')status.replaceChildren(t.unavailable);
 return {dialog,controls,load,refresh,dispose,get pending(){return pending;},get disposed(){return disposed;}};
}
