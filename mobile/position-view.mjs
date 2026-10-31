/** Read-only labels and choices. Availability is proved separately from these records. */
import {active,keyOf,optimistic,stable,validateEvent,validateOperation} from './domain.mjs';
import {copy,own} from './store.mjs';
import {sourceFileId} from './artifacts.mjs';
import {contentId} from './ids.mjs';
import {positionReport} from './reading-position-report.mjs';
export const POSITION_COPY={
  en:{title:'Reading position',nav:'Reading position…',page:'Page',remember:'Remember',rememberAgain:'Remember again',
    current:'Current original',earlier:'Earlier version',selected:'Selected original',draft:'Page draft',savedPage:'Saved page',
    hint:'Choose the exact original and enter the page you want to remember.',
    viewerHelp:'The native PDF viewer does not report its viewport. Pages are entered manually; no page is tracked automatically.',
    jump:'Open this exact PDF and use its page controls. A native viewer may ignore page links; no automatic jump is made.',
    check:'Check selected PDF',checking:'Checking exact PDF bytes and page count…',checked:'Verified pages',
    open:'Open exact PDF',close:'Close',cancel:'Cancel',cancelled:'Cancelled; your page text is kept.',refresh:'Refresh',empty:'No saved page for this original.',
    versions:'Versions, retained pages and PDF help',identifier:'PDF identifier',recovery:'Recovery and retained archives',import:'Import page recovery',
    importHelp:'Import retains verified originals and proposals privately. It sends no old operations. Review a page explicitly with your current connection.',
    export:'Export retained work',viewArchive:'View retained archive text',archiveHelp:'Archived note, draft and outbox text is read-only. It remains viewable and exportable; no generic replay is performed.',
    archive:'Retained archive',notes:'Note drafts',operations:'Archived operations',conflicts:'Archived conflicts',review:'Review page',otherPages:'Other paper proposals remain in the retained archive.',
    reviewed:'Reviewed on this device',readonly:'Read-only snapshot. Receive current workspace history before editing.',
    working:'Working locally…',saved:'Page saved locally. Sync with your existing connection when ready.',
    retained:'Your entered page was retained as a conflict; the newer recorded page was kept.',
    failed:'Could not finish. Your page text is kept; check the selected original and retry.',
    changed:'Paper, connection or selected source changed. Your entered text is kept here; reopen the matching context to save it.',
    blocked:'Finish the active task or save your note draft first. Your note is unchanged.',
    bounds:'Enter a whole page within the verified PDF page count.',
    tooLarge:'This reader checks PDFs up to 32 MiB. No page was saved.',
    recoveryLimit:'Recovery exceeds this reader’s limits. Existing data is unchanged.',
    importFailed:'Could not finish page recovery. Keep the original file and retry.',
    unavailable:'The exact PDF could not be checked. Download it with your connection, then retry; no page was saved.',
    dirty:'Keep this page draft before leaving?',keep:'Keep draft',discard:'Discard changes',editing:'Keep editing',
    kept:'Page draft kept privately on this device.',imported:'Verified recovery retained privately. Choose a page to review; nothing was queued.',
    wrongWorkspace:'This recovery belongs to a different workspace. Nothing was imported.',
    noRecovery:'No retained page recovery.',restore:'This saved page was deleted. Remember it again as a new record?',confirm:'Confirm',
    newer:'A newer current original is available. Your selected original and page text are unchanged.',
    source:'Original',date:'Recorded',importLimit:'Page recovery accepts the closed v2 format, at most 64 MiB including 32 MiB of exact source bytes.'},
  'zh-TW':{title:'閱讀位置',nav:'閱讀位置…',page:'頁碼',remember:'記住頁碼',rememberAgain:'重新記住',
    current:'目前原文',earlier:'較早版本',selected:'已選原文',draft:'頁碼草稿',savedPage:'已存頁碼',
    hint:'請選擇相符原文，手動輸入要記住的頁碼。',viewerHelp:'原生 PDF 檢視器不會回報視窗位置；頁碼由你手動輸入，不會自動追蹤。',
    jump:'請開啟這份原文，使用檢視器的頁碼控制。原生檢視器可能忽略頁碼連結；此處不會自動跳頁。',
    check:'檢查所選 PDF',checking:'正在檢查原文位元組與實際頁數…',checked:'已驗證頁數',
    open:'開啟這份 PDF',close:'關閉',cancel:'取消',cancelled:'已取消；輸入的頁碼仍保留。',refresh:'重新讀取',empty:'這份原文尚無已存頁碼。',
    versions:'版本、保留頁碼與 PDF 說明',identifier:'PDF 識別碼',recovery:'復原與保留封存',import:'匯入頁碼復原檔',
    importHelp:'匯入只會私下保留已驗證的原文與提案，不會傳送舊操作。請使用目前連線明確檢閱頁碼。',
    export:'匯出保留工作',viewArchive:'檢視保留的封存文字',archiveHelp:'封存的筆記、草稿與待送文字為唯讀，仍可檢視及匯出；不會通用重播。',
    archive:'保留封存',notes:'筆記草稿',operations:'封存操作',conflicts:'封存衝突',review:'檢閱頁碼',otherPages:'其他論文的提案仍保留於封存中。',
    reviewed:'已在此裝置檢閱',readonly:'這是唯讀快照；請先接收目前工作區歷史再編輯。',
    working:'正在本機處理…',saved:'頁碼已存於本機；準備好時可使用現有連線同步。',
    retained:'輸入的頁碼已保留為衝突，較新的已存頁碼未被覆寫。',
    failed:'無法完成；輸入的頁碼仍保留，請檢查原文後重試。',
    changed:'論文、連線或所選原文已變更。輸入文字仍留在此處；請回到相符情境後儲存。',
    blocked:'請先完成目前工作或儲存筆記草稿；筆記內容未變更。',bounds:'請輸入實際驗證頁數範圍內的整數頁碼。',
    tooLarge:'此閱讀器可檢查最多 32 MiB 的 PDF；尚未儲存頁碼。',
    recoveryLimit:'復原資料超過此閱讀器的限制；既有資料未變更。',importFailed:'無法完成頁碼復原，請保留原始檔案後重試。',
    unavailable:'無法檢查這份原文；可使用現有連線下載後重試。尚未儲存頁碼。',
    dirty:'離開前要保留這份頁碼草稿嗎？',keep:'保留草稿',discard:'捨棄變更',editing:'繼續編輯',
    kept:'頁碼草稿已私下保留在此裝置。',imported:'已私下保留驗證過的復原資料；請選擇頁碼檢閱，沒有加入待送操作。',
    wrongWorkspace:'復原檔屬於另一個工作區，未匯入任何內容。',noRecovery:'尚無保留的頁碼復原資料。',
    restore:'這筆頁碼已刪除；要以新紀錄重新記住嗎？',confirm:'確認',
    newer:'已有較新的目前原文；所選原文與輸入頁碼均未變更。',source:'原文',date:'紀錄時間',
    importLimit:'頁碼復原僅接受封閉的 v2 格式；檔案最多 64 MiB，其中原文位元組最多 32 MiB。'}
};
export const positionLabel=language=>(POSITION_COPY[language]??POSITION_COPY.en).nav;
function acceptedPrimary(state,view,document,paper) {
  try {
    validateOperation(document,state.workspace);const receipt=own(state.receipts,document.operation_id);
    validateEvent(receipt,state.workspace);
    const graph=state.graph[keyOf('research_file',sourceFileId(paper,document.payload.sha256))];
    return document.entity_type==='paper_document' && document.action==='put' && document.entity_id===paper &&
      receipt.outcome==='accepted' && stable(receipt.operation)===stable(document) &&
      active(view,'paper',paper) && document.parents[0].incarnation===view.graph[keyOf('paper',paper)].incarnation &&
      (!graph || active(state,'research_file',sourceFileId(paper,document.payload.sha256)));
  }catch{return false;}
}
function knownDeletedPosition(state,operation,paper,hash) {
  try {
    const receipt=own(state.receipts,operation.incarnation),origin=receipt?.operation;
    validateEvent(receipt,state.workspace);validateOperation(origin,state.workspace);
    return receipt.outcome==='accepted'&&receipt.sequence<=state.cursor&&origin.entity_type==='research_content'&&
      origin.action==='put'&&origin.entity_id===operation.entity_id&&origin.incarnation===operation.incarnation&&
      origin.payload.feature==='reading_position'&&origin.payload.scope.id===paper&&origin.payload.key===hash&&
      stable(origin.parents)===stable(operation.parents);
  }catch{return false;}
}
export function positionChoices(state,paper,{selected=null}={}) {
  const view=optimistic(state),report=positionReport(state,paper),writable=active(view,'paper',paper),options=new Map();
  const primary=state.entities[keyOf('paper_document',paper)]?.operation;
  const add=(hash,value)=>{if(!options.has(hash))options.set(hash,{hash,current:false,read_only:false,...value});};
  if(acceptedPrimary(state,view,primary,paper))add(primary.payload.sha256,{current:true,kind:'primary',document:copy(primary)});
  for(const row of report.sources)add(row.document_hash,{kind:'original',source_id:row.id});
  for(const [id,entry] of Object.entries(state.positionRetentions??{}))if(entry.manifest.paper_id===paper &&
    acceptedPrimary(state,view,entry.document,paper))add(entry.manifest.slot,{kind:'original',source_id:id,private:true});
  if(selected?.document && acceptedPrimary(state,view,selected.document,paper))add(selected.hash,
    {kind:'primary',document:copy(selected.document),held:true});
  for(const row of report.positions)if(row.read_only)add(row.document_hash,{kind:'snapshot',read_only:true});
  for(const value of options.values()) {
    value.position=copy(report.positions.find(row=>row.document_hash===value.hash)??null);
    value.draft=copy(own(state.positionDrafts??{},paper+'/'+value.hash)??null);
    const position=view.entities[keyOf('research_content',contentId({kind:'paper',id:paper},'reading_position',value.hash))]?.operation;
    value.deleted=position?.action==='delete'&&knownDeletedPosition(state,position,paper,value.hash);
    if(position?.action==='delete'&&!value.deleted){value.history_unknown=true;value.read_only=true;}
  }
  const drafts=[...options.values()].filter(row=>row.draft),current=[...options.values()].find(row=>row.current);
  return {writable,options:[...options.values()],default_hash:drafts.length===1?drafts[0].hash:current?.hash??options.keys().next().value??null,
    retained:copy(report.retained),positions:copy(report.positions)};
}
export function choiceLabel(option,language='en') {
  const t=POSITION_COPY[language]??POSITION_COPY.en;
  return (option.current?t.current:t.earlier)+(option.position?` · ${t.savedPage} ${option.position.page}`:'')+
    (option.draft?` · ${t.draft}`:'');
}
