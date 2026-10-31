/** Entered pages only. Native PDF viewport and page jumps are never inferred. */
import {copy,own} from './store.mjs';
import {keyOf,stable} from './domain.mjs';
import {POSITION_COPY,choiceLabel,positionChoices} from './position-view.mjs';
import {openPrimaryPositionSource,openPositionSource,saveEnteredPosition,draftPosition,
  prepareRecoveryReview,saveRecoveryReview} from './reading-position-ops.mjs';
import {preparePositionRecovery,importPositionRecovery,recoveryReport,recoveryRow,MAX_RECOVERY_BYTES} from './position-recovery.mjs';

async function openChoice(engine,paper,choice,options,canDownload) {
  if(choice.kind==='primary') {
    const state=await engine.store.read(),file=state.files[choice.hash]??state.artifactFiles?.[choice.hash];
    if(!file?.verified && canDownload() &&
      stable(state.entities[keyOf('paper_document',paper)]?.operation)===stable(choice.document))await engine.download(paper);
    return openPrimaryPositionSource(engine,paper,{...options,document:choice.document});
  }
  return openPositionSource(engine,paper,choice.hash,{...options,download:canDownload()});
}
const defaults={choices:positionChoices,open:openChoice,save:saveEnteredPosition,draft:draftPosition,
  prepareImport:preparePositionRecovery,commitImport:importPositionRecovery,review:prepareRecoveryReview,
  saveReview:saveRecoveryReview};

export function readingPositionDialog(el,{engine,paper,language='en',current=()=>true,blocked=()=>false,
  connected=()=>false,onClose=()=>{},onSaved=()=>{},onExport=()=>{},actions={},urls=globalThis.URL}={}) {
  const service={...defaults,...actions},t=POSITION_COPY[language]??POSITION_COPY.en,generation=engine.generation;
  const dialog=el('dialog',{class:'position-dialog','aria-label':t.title}),status=el('p',{role:'status','aria-live':'polite'}),
    sourceName=el('p',{class:'position-source'}),sourceHash=el('small',{class:'muted position-hash'}),
    pageInfo=el('p',{id:'position-page-info',class:'muted'}),question=el('div',{class:'position-question'}),
    oldBody=el('div'),recoveryBody=el('div'),archiveText=el('textarea',{readonly:'',rows:'9',class:'editor position-archive','aria-label':t.archive});
  const select=el('select',{'aria-label':t.source}),page=el('input',{id:'position-page',type:'number',inputmode:'numeric',
    min:'1',step:'1','aria-label':t.page,'aria-describedby':'position-page-info',autocomplete:'off'});
  let disposed=false,pending=false,mode=null,controller=null,serial=0,state=null,report=null,choice=null,opened=null,
    form=null,dirty=false,baselineText='',expired=false,questionAction=null,pdfURL=null,review=null,wantClose=false,abortWrite=false,checkRun=0,sourceEpoch=0;
  let questionButtons=[],initialCountRequested=false;
  const dynamic=[],bound=()=>!disposed&&current()&&engine.generation===generation,valid=()=>bound()&&!expired;
  const controls={select,page};
  const say=key=>{if(!disposed)status.replaceChildren(key===''?'':t[key]??t.failed);};
  const button=(name,action,attributes={})=>el('button',{type:'button',onclick:()=>void action(),...attributes},t[name]);
  const checkButton=button('check',()=>leave(()=>prepare(choice))),save=button('remember',()=>remember()),
    cancel=button('cancel',()=>cancelWork()),close=button('close',()=>requestClose()),
    open=el('a',{target:'_blank',rel:'noopener',class:'position-open hidden'},t.open),
    importFile=el('input',{type:'file',accept:'application/json,.json','aria-label':t.import}),
    exportButton=button('export',()=>leave(()=>run('export',async()=>onExport(await engine.exportLocal())))),
    archiveButton=button('viewArchive',()=>showArchive());
  Object.assign(controls,{check:checkButton,save,cancel,close,open,importFile,export:exportButton,archive:archiveButton});
  function revoke() {if(pdfURL)urls.revokeObjectURL(pdfURL);pdfURL=null;open.removeAttribute?.('href');open.className='position-open hidden';}
  function pageNumber() {const value=Number(page.value);return page.value.trim()!==''&&Number.isSafeInteger(value)&&value>=1&&value<=opened?.pageCount?value:null;}
  function enable() {
    const ready=valid()&&!!opened&&!choice?.read_only;
    select.disabled=pending||!valid()||report?.writable===false;page.disabled=pending||!ready;
    checkButton.disabled=pending||!valid()||!choice||choice.read_only;
    save.disabled=pending||!ready||pageNumber()===null||blocked();
    importFile.disabled=pending||!valid();exportButton.disabled=pending||!bound();
    archiveButton.disabled=pending||!state||!bound();cancel.disabled=!pending;cancel.hidden=!pending;
    open.setAttribute?.('aria-disabled',String(pending||!ready||blocked()));
    for(const [node,extra] of dynamic)node.disabled=pending||!valid()||extra();
    for(const [node,extra] of questionButtons)node.disabled=pending||extra();
    save.replaceChildren(t[form?.restore?'rememberAgain':'remember']);
  }
  function classify(error) {
    if(error.message==='cancelled')return 'cancelled';
    if(error.message==='page_out_of_bounds')return 'bounds';
    if(['file_too_large','pdf_count_size_limit'].includes(error.message))return 'tooLarge';
    if(['position_recovery_size_limit','position_recovery_source_limit','position_recovery_limit'].includes(error.message))return 'recoveryLimit';
    if(error.message==='wrong_recovery_workspace')return 'wrongWorkspace';
    if(['not_connected','session_denied'].includes(error.message)){expired=true;return 'changed';}
    if(['stale_position_scope','stale_position_source','primary_parent_changed','position_original_retired',
      'position_source_unavailable'].includes(error.message)){expired=true;return 'changed';}
    if(['artifact_unavailable','file_unavailable','corrupt_file','pdf_worker_required',
      'pdf_parse_failed','invalid_pdf_page_count'].includes(error.message))return 'unavailable';
    if(mode==='import')return 'importFailed';
    return 'failed';
  }
  async function run(kind,work) {
    if(pending||!(kind==='export'?bound():valid()))return;
    pending=true;mode=kind;abortWrite=false;controller=new AbortController();const epoch=++serial;say(kind==='check'?'checking':'working');enable();
    try {return await work(controller.signal,()=>(kind==='export'?bound():valid())&&!abortWrite&&epoch===serial);}
    catch(error){if(!disposed&&epoch===serial)say(classify(error));}
    finally {if(epoch===serial){pending=false;mode=null;controller=null;enable();
      if(wantClose){wantClose=false;abortWrite=false;requestClose();}}}
  }
  function cancelWork() {
    if(!pending)return;
    if(mode==='save'||mode==='draft'){wantClose=true;abortWrite=true;return;}
    abortWrite=true;if(mode==='check')sourceEpoch++;controller?.abort();say('cancelled');
  }
  function closeNow() {
    if(disposed)return;disposed=true;controller?.abort();serial++;revoke();
    dialog.close();dialog.remove();onClose();
  }
  function prompt(next,restore=false) {
    questionAction=next;questionButtons=[];question.replaceChildren(el('p',{},t[restore?'restore':'dirty']));
    const editing=button(restore?'cancel':'editing',()=>{questionAction=null;questionButtons=[];question.replaceChildren();enable();page.focus();},{autofocus:''});
    questionButtons.push([editing,()=>false]);
    question.append(editing);
    if(restore){const confirm=button('confirm',()=>{const action=questionAction;questionAction=null;questionButtons=[];question.replaceChildren();void action?.();});
      questionButtons.push([confirm,()=>!valid()||blocked()]);question.append(confirm);}
    else {
      const keep=button('keep',()=>keepDraft()),discard=button('discard',()=>{dirty=false;page.value=baselineText;const action=questionAction;
        questionAction=null;questionButtons=[];question.replaceChildren();void action?.();});
      questionButtons.push([keep,()=>!valid()||!opened],[discard,()=>false]);question.append(keep,discard);
    }
    enable();editing.focus();
  }
  function leave(next) {if(pending)return;if(dirty){prompt(next);return;}void next();}
  function requestClose() {
    if(disposed)return;
    if(pending){wantClose=true;abortWrite=true;controller?.abort();return;}
    if(dirty){prompt(closeNow);return;}closeNow();
  }
  async function keepDraft() {
    if(!valid()||!opened||pending)return;
    const next=questionAction;
    const success=await run('draft',async(_signal,scope)=>{
      await service.draft(engine,opened.captured,{pageText:page.value,requestId:form.requestId,
        recordedAt:form.recordedAt,observed:form.observed},{current:scope});
      if(!scope())return false;dirty=false;baselineText=page.value;say('kept');return true;
    });
    if(success){questionAction=null;questionButtons=[];question.replaceChildren();await next?.();}
  }
  async function prepare(selected,{proposal=null,recovery=null}={}) {
    if(!selected||selected.read_only)return;
    const selectedEpoch=++sourceEpoch;
    choice=selected;opened=null;review=null;revoke();
    await run('check',async(signal,scope)=>{
      // A review remains tied to this selected source after its count job ends.
      // The later Save still supplies a separate current action scope.
      const selectedCurrent=()=>valid()&&selectedEpoch===sourceEpoch;
      const checked=recovery?await service.review(engine,recovery.archive_id,recovery.row_id,{signal,current:selectedCurrent}):
        await service.open(engine,paper,selected,{signal,current:scope},()=>connected()&&!blocked());
      if(!scope())return;
      opened=checked;review=recovery?checked.token:null;
      const savedDraft=selected.draft;
      form={requestId:savedDraft?.requestId??crypto.randomUUID(),recordedAt:savedDraft?.recordedAt??new Date().toISOString(),
        observed:copy(savedDraft?.observed??JSON.parse(checked.captured?.json??'{}').observed??null),
        restore:selected.deleted??false,candidateId:proposal?.source==='local'?proposal.id:null,
        resolutionOf:proposal?.source==='remote'?proposal.id:null};
      page.value=recovery?(checked.row.page_text??String(checked.row.data?.page??'')):
        proposal?String(proposal.data.page):savedDraft?.pageText??(selected.position?String(selected.position.page):'');
      baselineText=page.value;
      dirty=!!proposal||!!recovery;sourceName.replaceChildren(t.selected+' · '+choiceLabel(choice??selected,language));
      sourceHash.replaceChildren(`${t.identifier} · ${selected.hash.slice(0,12)}`);sourceHash.setAttribute?.('title',selected.hash);
      page.setAttribute?.('max',String(checked.pageCount));pageInfo.replaceChildren(`${t.checked}: ${checked.pageCount}.`);
      pdfURL=urls.createObjectURL(new Blob([checked.bytes],{type:'application/pdf'}));open.setAttribute?.('href',pdfURL);
      open.className='position-open';say(blocked()?'blocked':'');page.focus();
    });
    enable();
  }
  async function remember(confirmed=false) {
    if(pending||!valid()||!opened)return;
    if(blocked()){say('blocked');return;}
    const number=pageNumber();if(number===null){say('bounds');return;}
    if(form.restore&&!confirmed){prompt(()=>remember(true),true);return;}
    const result=await run('save',async(_signal,scope)=>{
      const request={page:number,recordedAt:form.recordedAt,requestId:form.requestId,restore:form.restore,current:scope};
      return review?service.saveReview(engine,review,request):service.save(engine,opened.captured,
        {...request,observed:form.observed,candidateId:form.candidateId,resolutionOf:form.resolutionOf,notify:false});
    });
    if(!result||!valid())return;
    dirty=false;onSaved(result);
    if(result.status==='retained'){say('retained');await refresh(false);return;}
    say('saved');closeNow();
  }
  page.addEventListener('input',()=>{
    if(!valid()||pending)return;dirty=true;form??={};form.requestId=crypto.randomUUID();form.recordedAt=new Date().toISOString();enable();
  });
  select.addEventListener('change',()=>{
    const selected=report?.options.find(row=>row.hash===select.value);select.value=choice?.hash??'';if(!selected)return;
    leave(async()=>{select.value=selected.hash;await prepare(selected);});
  });
  open.addEventListener('click',event=>{if(pending||!valid()||blocked()||!opened)event.preventDefault();});
  importFile.addEventListener('change',()=>{
    const file=importFile.files?.[0];if(!file)return;
    leave(()=>run('import',async(signal,scope)=>{
      if(!Number.isSafeInteger(file.size)||file.size>MAX_RECOVERY_BYTES)throw Error('position_recovery_size_limit');
      const text=await file.text();if(!scope())return;
      const prepared=await service.prepareImport(engine,text,{signal,current:scope});if(!scope())return;
      await service.commitImport(engine,prepared);if(!scope())return;say('imported');await refresh(false);
    }));
    importFile.value='';
  });
  async function selectProposal(row,recovery=null) {
    if(blocked()){say('blocked');return;}
    const selected=report.options.find(item=>item.hash===row.document_hash);
    // A recovery primary may not yet have a live original-source declaration.
    const source=recovery?recoveryRow(state,recovery.archive_id,recovery.row_id).source:null;
    const fallback={hash:row.document_hash,current:false,kind:'recovery',read_only:false,
      document:copy(source?.primary_receipt?.operation??null)};
    leave(()=>prepare(selected??fallback,{proposal:recovery?null:row,recovery}));
  }
  function renderRecords() {
    oldBody.replaceChildren();recoveryBody.replaceChildren();dynamic.length=0;
    for(const row of report.positions)oldBody.append(el('p',{},`${t.savedPage} ${row.page} · ${row.recorded_at}`,
      el('small',{class:'muted position-hash',title:row.document_hash},row.document_hash.slice(0,12)),row.read_only?el('span',{},t.readonly):''));
    for(const row of report.retained) {
      const action=button('review',()=>selectProposal(row));dynamic.push([action,()=>blocked()]);
      oldBody.append(el('article',{class:'position-row'},el('p',{},`${t.savedPage} ${row.data.page}`),action));
    }
    const allRecoveries=recoveryReport(state),recoveries=allRecoveries.filter(row=>row.paper_id===paper);
    if(allRecoveries.length>recoveries.length)recoveryBody.append(el('p',{class:'muted'},t.otherPages));
    if(!recoveries.length)recoveryBody.append(el('p',{},t.noRecovery));
    for(const row of recoveries) {
      const action=button('review',()=>selectProposal(row,row));dynamic.push([action,()=>blocked()||!connected()||!report.writable||!!row.reviewed_by]);
      recoveryBody.append(el('article',{class:'position-row'},el('p',{},`${t.savedPage} ${row.data?.page??row.page_text??''}`),
        el('small',{class:'muted position-hash',title:row.document_hash},row.document_hash.slice(0,12)),
        row.reviewed_by?el('p',{},t.reviewed):action));
    }
    for(const [id,entry] of Object.entries(state.positionRecoveries??{})) {
      const archive=entry.archive;
      recoveryBody.append(el('p',{class:'muted',title:id},`${t.archive}: ${t.notes} ${Object.keys(archive.drafts).length}, `+
        `${t.operations} ${archive.outbox.length}, ${t.conflicts} ${Object.keys(archive.conflicts).length}`));
    }
  }
  function showArchive() {
    if(!state)return;
    const archives=Object.values(state.positionRecoveries??{}).map(({archive})=>({workspace:archive.workspace,device:archive.device,
      cursor:archive.cursor,drafts:archive.drafts,draftBases:archive.draftBases,outbox:archive.outbox,conflicts:archive.conflicts,
      positions:archive.positions,sources:archive.sources}));
    archiveText.value=JSON.stringify(archives,null,2);archiveText.hidden=false;archiveText.focus();
  }
  async function refresh(auto=true) {
    if(auto&&!choice&&!opened)initialCountRequested=true;
    const run=++checkRun,value=await engine.store.read();if(disposed||run!==checkRun)return;
    state=value;
    if(!current()||engine.generation!==generation){expired=true;abortWrite=true;controller?.abort();say('changed');enable();return;}
    report=service.choices(state,paper,{selected:choice});
    const oldCurrent=choice?.current,currentHash=report.options.find(row=>row.current)?.hash;
    const selected=report.options.find(row=>row.hash===choice?.hash);
    if(choice&&!selected){expired=true;abortWrite=true;controller?.abort();say('changed');enable();return;}
    if(selected)choice=selected;
    if(!choice)choice=report.options.find(row=>row.hash===report.default_hash)??null;
    if(choice&&opened)sourceName.replaceChildren(t.selected+' · '+choiceLabel(choice,language));
    select.replaceChildren(...report.options.map(row=>el('option',{value:row.hash,title:row.hash},choiceLabel(row,language))));
    select.value=choice?.hash??report.default_hash??'';renderRecords();
    if(oldCurrent&&choice?.hash!==currentHash)say('newer');
    if(!report.writable){initialCountRequested=false;say('readonly');enable();return;}
    if(blocked())say('blocked');
    if(initialCountRequested&&!opened&&!pending&&choice&&!choice.read_only){initialCountRequested=false;await prepare(choice);}
    if(choice?.read_only){initialCountRequested=false;say('readonly');}
    enable();
  }
  dialog.addEventListener('cancel',event=>{event.preventDefault();requestClose();});
  dialog.addEventListener('close',()=>{
    if(disposed)return;
    if(dirty){prompt(closeNow);dialog.showModal?.();return;}
    closeNow();
  });
  archiveText.hidden=true;
  dialog.append(el('h2',{},t.title),el('p',{class:'muted'},t.hint),
    el('div',{class:'fields'},el('label',{},t.source,select)),sourceName,sourceHash,
    el('div',{class:'toolbar'},checkButton,open),pageInfo,
    el('div',{class:'position-entry'},el('label',{},t.page,page),save),
    el('div',{class:'toolbar'},cancel,close),status,question,
    el('details',{},el('summary',{},t.versions),oldBody,el('p',{class:'muted'},t.viewerHelp),el('p',{class:'muted'},t.jump)),
    el('details',{},el('summary',{},t.recovery),el('p',{class:'muted'},t.importHelp),el('p',{class:'muted'},t.importLimit),
      el('label',{class:'position-import'},t.import,importFile),recoveryBody,el('p',{class:'muted'},t.archiveHelp),
      el('div',{class:'toolbar'},exportButton,archiveButton),archiveText));
  enable();
  return {dialog,controls,refresh,check:()=>void refresh(false),dispose:requestClose,
    get pending(){return pending;},get dirty(){return dirty;},get disposed(){return disposed;}};
}
