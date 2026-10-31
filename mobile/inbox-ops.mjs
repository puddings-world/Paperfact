/** Offline Inbox writes share the ordinary atomic store/outbox boundary. No transport calls. */
import {copy,own,put} from './store.mjs';
import {buildOperation,enqueue,keyOf,optimistic,projection,requireThat,stable,statusFor} from './domain.mjs';
import {sha256} from './engine.mjs';
import {inboxUUID,validateInbox,INBOX_KINDS,INBOX_STATES} from './inbox-schema.mjs';

export function observeInbox(state,id) {
  const row=optimistic(state).entities[keyOf('inbox_item',id)]?.operation;
  return {operation_id:row?.operation_id??null,incarnation:row?.incarnation??null,action:row?.action??null};
}
function scope(engine,state,captured,current) {
  engine.check(captured.generation);
  requireThat(current() && state.workspace===captured.workspace && state.device===captured.device,'stale_inbox_scope');
}
export async function captureInbox(engine,current=()=>true) {
  const generation=engine.generation,state=await engine.store.read();
  engine.check(generation); requireThat(current(),'stale_inbox_scope');
  return {generation,workspace:state.workspace,device:state.device};
}
export async function saveInbox(engine,{scope:captured,current=()=>true,requestId,itemId,payload=null,
  observed=null,action='put',restore=false,resolutionOf=null,candidateId=null,draftSlot='capture',notify=true}) {
  inboxUUID(requestId); inboxUUID(itemId);
  requireThat(['put','delete'].includes(action) && typeof restore==='boolean' && typeof notify==='boolean','invalid_inbox');
  payload=copy(payload);
  if(action==='put')validateInbox(payload); else requireThat(payload===null,'invalid_inbox');
  const expected=copy(observed??{operation_id:null,incarnation:null,action:null});
  requireThat(expected && Object.keys(expected).length===3 && ['operation_id','incarnation','action'].every(key=>Object.hasOwn(expected,key)),'invalid_inbox_observation');
  const request={itemId,payload,observed:expected,action,restore,resolutionOf,candidateId};
  const fingerprint=await sha256(new TextEncoder().encode(stable(request)));
  engine.check(captured.generation); requireThat(current(),'stale_inbox_scope');
  const result=await engine.store.update(state=>{
    scope(engine,state,captured,current);
    state.inboxRequests??={}; state.inboxCandidates??={};
    const receipt=own(state.inboxRequests,requestId);
    if(receipt) {requireThat(receipt.fingerprint===fingerprint,'changed_inbox_retry');return receipt.result;}
    requireThat(Object.keys(state.inboxRequests).length<100000,'inbox_limit');
    const view=optimistic(state),known=view.entities[keyOf('inbox_item',itemId)]?.operation;
    const snapshot=state.readProjection?.inbox?.items?.some(row=>row.id===itemId);
    requireThat(!snapshot || known,'read_only_inbox_snapshot');
    let result;
    if(stable(observeInbox(state,itemId))!==stable(expected)) {
      put(state.inboxCandidates,requestId,{itemId,payload:copy(payload),observed:copy(expected),action,resolvedBy:null});
      result={status:'conflict',item_id:itemId,version:known?.operation_id??requestId,candidate_id:requestId};
    } else {
      if(candidateId) {
        const candidate=own(state.inboxCandidates,candidateId);
        requireThat(candidate && !candidate.resolvedBy && candidate.itemId===itemId,'invalid_inbox_candidate');
      }
      const operation=buildOperation(state,'inbox_item',itemId,payload??{},
        {action,restore,resolutionOf,operationId:requestId});
      enqueue(state,operation);
      if(candidateId)state.inboxCandidates[candidateId].resolvedBy=requestId;
      result={status:'saved',item_id:itemId,version:operation.operation_id,candidate_id:null};
      if(state.inboxDrafts?.[draftSlot]?.requestId===requestId) delete state.inboxDrafts[draftSlot];
    }
    put(state.inboxRequests,requestId,{fingerprint,result:copy(result)});
    return result;
  });
  if(notify)engine.onChange(result.status==='conflict'?'conflict':'saved_locally');return result;
}
export async function draftInbox(engine,captured,draft,{slot='capture',current=()=>true}={}) {
  requireThat(typeof slot==='string' && (slot==='capture'||/^[0-9a-f-]{36}$/.test(slot)),'invalid_inbox_draft');
  requireThat(draft && typeof draft==='object' && !Array.isArray(draft),'invalid_inbox_draft');
  const required=['itemId','requestId','kind','text','state'],optional=['createdAt','updatedAt','observed','active','restore','candidateId','action'];
  requireThat(required.every(key=>Object.hasOwn(draft,key)) && Object.keys(draft).every(key=>[...required,...optional].includes(key)),'invalid_inbox_draft');
  inboxUUID(draft.itemId);inboxUUID(draft.requestId);
  requireThat(INBOX_KINDS.includes(draft.kind) && INBOX_STATES.includes(draft.state) &&
    typeof draft.text==='string' && [...draft.text].length<=2048 && new TextEncoder().encode(draft.text).length<=8192,'invalid_inbox_draft');
  if(draft.candidateId!==undefined)inboxUUID(draft.candidateId);
  for(const key of ['active','restore'])if(Object.hasOwn(draft,key))requireThat(typeof draft[key]==='boolean','invalid_inbox_draft');
  if(Object.hasOwn(draft,'action'))requireThat(['put','delete'].includes(draft.action),'invalid_inbox_draft');
  draft=copy(draft);
  await engine.store.update(state=>{
    scope(engine,state,captured,current);state.inboxDrafts??={};
    requireThat(Object.keys(state.inboxDrafts).length<256 || Object.hasOwn(state.inboxDrafts,slot),'inbox_draft_limit');
    put(state.inboxDrafts,slot,copy(draft));
  });
}
export async function resolveInbox(engine,conflictId,{scope:captured,current=()=>true,requestId,
  choice='canonical',payload=null,restore=false,notify=true,observed=null}={}) {
  const state=await engine.store.read();scope(engine,state,captured,current);
  const candidate=own(state.inboxCandidates??{},conflictId);
  if(candidate) {
    requireThat((!candidate.resolvedBy || candidate.resolvedBy===requestId) && ['incoming','canonical'].includes(choice),'unknown_inbox_conflict');
    inboxUUID(candidate.itemId);inboxUUID(requestId);
    const expected=copy(observed??observeInbox(state,candidate.itemId));
    requireThat(own(state.inboxRequests??{},requestId) || stable(observeInbox(state,candidate.itemId))===stable(expected),'stale_inbox_resolution');
    if(choice==='incoming')return saveInbox(engine,{scope:captured,current,requestId,itemId:candidate.itemId,
      action:candidate.action,payload:candidate.action==='put'?(payload??candidate.payload):null,
      observed:expected,restore,candidateId:conflictId,notify});
    requireThat(payload===null&&!restore,'invalid_inbox_choice');
    const fingerprint=await sha256(new TextEncoder().encode(stable({conflictId,choice,observed:expected})));
    return engine.store.update(next=>{
      scope(engine,next,captured,current);next.inboxRequests??={};
      const prior=own(next.inboxRequests,requestId);
      if(prior){requireThat(prior.fingerprint===fingerprint,'changed_inbox_retry');return prior.result;}
      const selected=own(next.inboxCandidates??{},conflictId);
      requireThat(selected&&!selected.resolvedBy&&selected.itemId===candidate.itemId&&stable(observeInbox(next,candidate.itemId))===stable(expected),'stale_inbox_resolution');
      selected.resolvedBy=requestId;
      const result={status:'resolved',item_id:candidate.itemId,version:requestId,candidate_id:conflictId};
      put(next.inboxRequests,requestId,{fingerprint,result:copy(result)});return result;
    });
  }
  const conflict=own(state.conflicts,conflictId);
  requireThat(conflict && (!conflict.resolvedBy || conflict.resolvedBy===requestId) && conflict.event.operation.entity_type==='inbox_item','unknown_inbox_conflict');
  const incoming=conflict.event.operation,id=incoming.entity_id;
  const expected=copy(observed??observeInbox(state,id));
  requireThat(own(state.inboxRequests??{},requestId) || stable(observeInbox(state,id))===stable(expected),'stale_inbox_resolution');
  requireThat(['incoming','canonical'].includes(choice),'invalid_inbox_choice');
  const selected=choice==='incoming'?incoming:state.entities[keyOf('inbox_item',id)]?.operation;
  const action=selected?.action??'delete';
  return saveInbox(engine,{scope:captured,current,requestId,itemId:id,action,
    payload:action==='put'?(payload??selected.payload):null,restore,resolutionOf:conflictId,notify,
    observed:expected});
}
function retainedInboxText(state,id) {
  const pending=[...state.outbox].reverse().find(row=>row.operation.entity_type==='inbox_item' && row.operation.entity_id===id && row.operation.action==='put');
  if(pending)return copy(pending.operation.payload);
  let selected=null;
  for(const event of Object.values(state.receipts))if(event.outcome==='accepted' && event.operation.entity_type==='inbox_item' && event.operation.entity_id===id && event.operation.action==='put' && (!selected||event.sequence>selected.sequence))selected=event;
  return selected?copy(selected.operation.payload):null;
}
export function inboxReport(state) {
  const view=optimistic(state),saved=projection(state).inbox?.items??[];
  const items=saved.map(row=>({...copy(row),status:row.editable?statusFor(state,'inbox_item',row.id):'read_only'}));
  const local=Object.entries(state.inboxCandidates??{}).filter(([,value])=>!value.resolvedBy)
    .map(([id,value])=>({id,source:'local',...copy(value)}));
  const remote=Object.entries(state.conflicts).filter(([,value])=>!value.resolvedBy && value.event.operation.entity_type==='inbox_item')
    .map(([id,value])=>({id,source:'server',itemId:value.event.operation.entity_id,
      action:value.event.operation.action,payload:value.event.operation.action==='put'?copy(value.event.operation.payload):null}));
  const deleted=Object.values(view.entities).filter(row=>row.operation.entity_type==='inbox_item' && row.operation.action==='delete')
    .map(row=>({id:row.operation.entity_id,active:false,payload:retainedInboxText(state,row.operation.entity_id),editable:true,version:row.operation.operation_id,incarnation:row.operation.incarnation,status:statusFor(state,'inbox_item',row.operation.entity_id)}));
  return {items:[...items,...deleted],retained:[...local,...remote],drafts:copy(state.inboxDrafts??{})};
}
