import {editableTextNote} from './content.mjs';
import { artifactTarget, ARTIFACT_CACHE_BYTES, downloadArtifact, readArtifact } from './artifact-engine.mjs';
import {artifactJSON,sourceFileId, validateArtifact} from './artifacts.mjs';
import {parsePositionJSON} from './position-json.mjs';
import {validateLineageOperation} from './lineage-ops.mjs';
import {preparePositionPush,reconcilePositionIntents} from './primary-source-retention.mjs';
import {exportPositionRecovery} from './position-recovery.mjs';
import {
  copy,
  own,
  put
} from './store.mjs';
import {
  active,
  assertObserved,
  buildOperation,
  enqueue,
  keyOf,
  observeNote,
  optimistic,
  receive,
  requireThat,
  stable,
  validateOperation,
  validateEvent,
  validateProjection
} from './domain.mjs';
import {
  CHUNK
} from './transport.mjs';
export const MAX_LOCAL_PDF = 32 * 1024 * 1024;
export async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2,
  '0')).join('');
}

const historyEncoder=new TextEncoder(), HISTORY_ERROR='sync_history_unavailable';
export function historyPoint(value) {
  requireThat(value && typeof value==='object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(',')==='sequence,sha256' && Number.isSafeInteger(value.sequence) &&
    value.sequence>=0 && typeof value.sha256==='string' && /^[0-9a-f]{64}$/.test(value.sha256),HISTORY_ERROR);
  return value;
}
export async function historySeed(workspace) {
  return sha256(historyEncoder.encode('paperfact.sync-history.v1\0'+workspace));
}
export async function historyStep(previous,record) {
  historyPoint({sequence:0,sha256:previous});
  requireThat(typeof record==='string' && record.length<=2*256*1024+8192,HISTORY_ERROR);
  const bytes=historyEncoder.encode(record);
  requireThat(bytes.length<=2*256*1024+8192,HISTORY_ERROR);
  const linked=new Uint8Array(40+bytes.length);
  for(let at=0;at<32;at++)linked[at]=Number.parseInt(previous.slice(at*2,at*2+2),16);
  new DataView(linked.buffer).setUint32(36,bytes.length,false);
  linked.set(bytes,40);return sha256(linked);
}
function historyRecord(record,workspace,expectedSequence=null) {
  try {
    const bytes=historyEncoder.encode(record),event=artifactJSON(bytes);
    if(expectedSequence!==null)requireThat(Number.isSafeInteger(event?.sequence) &&
      event.sequence===expectedSequence,HISTORY_ERROR);
    parsePositionJSON(record,{strict:true,maxBytes:2*256*1024+8192});
    validateEvent(event,workspace);return event;
  } catch(error) {
    const unreadable=['unsupported_version','unsupported_operation','unsupported_research_content'];
    throw new Error(unreadable.includes(error?.message)?'sync_format_unsupported':HISTORY_ERROR);
  }
}
async function historyPage(page,workspace,before,limit=100) {
  requireThat(page && typeof page==='object' && !Array.isArray(page) &&
    Object.keys(page).sort().join(',')==='after,caught_up,checkpoint,events,version,workspace_id' &&
    page.version===1 && page.workspace_id===workspace && typeof page.caught_up==='boolean' &&
    Array.isArray(page.events) && page.events.length<=limit && page.events.length<=1000 &&
    historyEncoder.encode(JSON.stringify(page)).length<=2*1024**2,HISTORY_ERROR);
  historyPoint(page.after);historyPoint(page.checkpoint);
  requireThat(stable(page.after)===stable(before),HISTORY_ERROR);
  let sequence=before.sequence,digest=before.sha256;
  const events=[],points=new Map();
  // Verify the bounded byte chain before classifying an unreadable research format.
  for(const record of page.events) {
    requireThat(typeof record==='string' && record.length<=2*256*1024+8192,HISTORY_ERROR);
    digest=await historyStep(digest,record);sequence++;
    points.set(sequence,digest);
  }
  const checkpoint={sequence,sha256:digest};
  requireThat(stable(checkpoint)===stable(page.checkpoint) &&
    (page.events.length>0 || page.caught_up),HISTORY_ERROR);
  sequence=before.sequence;
  for(const record of page.events) {
    const event=historyRecord(record,workspace,sequence+1);
    requireThat(Number.isSafeInteger(event.sequence) && event.sequence===sequence+1,HISTORY_ERROR);
    sequence=event.sequence;events.push(event);
  }
  return {events,points,before:copy(before),checkpoint,caught_up:page.caught_up};
}
function retainedHistory(state,seed) {
  const value=state.history??{received:{sequence:0,sha256:seed},acknowledged:{sequence:0,sha256:seed}};
  requireThat(value && typeof value==='object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(',')==='acknowledged,received',HISTORY_ERROR);
  for(const point of [value.received,value.acknowledged]) {
    historyPoint(point);requireThat(point.sequence!==0 || point.sha256===seed,HISTORY_ERROR);
  }
  requireThat(value.received.sequence<=state.cursor &&
    (value.received.sequence!==value.acknowledged.sequence ||
      value.received.sha256===value.acknowledged.sha256),HISTORY_ERROR);
  return value;
}
function historyAnchor(history) {
  return history.acknowledged.sequence>history.received.sequence?history.acknowledged:history.received;
}

export function documentTarget(state, paperId) {
  const item = state.entities[keyOf('paper_document', paperId)];
  return item && active(state, 'paper_document', paperId) ? copy(item.operation): null;
}
export class Engine {
  #token = null;
  constructor(store, {
    transport = null,
    onChange =() => {}
  } = {}) {
    this.store = store;
    this.transport = transport;
    this.onChange = onChange;
    this.generation = 0;
    this.controller = new AbortController();
    this.running = null;
    this.downloads = new Map();
  }
  disconnect() {
    this.generation++;
    this.controller.abort();
    this.controller = new AbortController();
    this.#token = null;
    this.onChange('disconnected');
  }
  async connect(token) {
    this.disconnect();
    this.transport?.begin_session?.();
    const generation = this.generation,
    signal = this.controller.signal;
    const state = await this.store.read();
    this.check(generation);
    const known=this.store.readControlCheckpoint?await this.store.readControlCheckpoint():null;
    this.check(generation);
    requireThat(known===null || typeof this.transport.bind_control_checkpoint==='function','sync_history_unavailable');
    if(this.transport.bind_control_checkpoint && this.store.readControlCheckpoint) {
      const store=this.store,identity={workspace_id:state.workspace,device_id:state.device};
      this.transport.bind_control_checkpoint(async()=>{
        this.check(generation);const point=await store.readControlCheckpoint();this.check(generation);return point;
      },async(point,previous)=>{
        this.check(generation);await store.writeControlCheckpoint(point,previous);this.check(generation);
      },identity);
    }
    const identity = await this.transport.session_info(token, signal);
    this.check(generation);
    requireThat(identity.workspace_id === state.workspace && identity.device_id === state.device, 'wrong_session');
    this.#token = token;
    this.onChange('connected');
  }
  check(generation) {
    requireThat(this.generation === generation && ! this.controller.signal.aborted, 'cancelled');
  }
  async authenticated(generation) {
    this.check(generation);
    requireThat(this.#token && this.transport, 'not_connected');
    const identity = await this.transport.session_info(this.#token, this.controller.signal),
    state = await this.store.read();
    this.check(generation);
    requireThat(identity.workspace_id === state.workspace && identity.device_id === state.device, 'wrong_session');
  }
  async importProjection(value) {
    await this.store.update(state => {
      state.readProjection = validateProjection(value, state.workspace);
    });
    this.onChange('projection_loaded');
  }
  async observeNote(id, paperId) {
    return observeNote(await this.store.read(), id, paperId);
  }
  async draft(id, body, observation = null) {
    await this.store.update(state => {
      put(state.drafts, id, body);
      if(observation) {
        state.draftBases ??= {};
        put(state.draftBases, id, copy(observation));
      }
    });
  }
  async saveNote(id, paperId, body, options = {}) {
    const result = await this.store.update(state => {
      const current = optimistic(state).entities[keyOf('note', id)]?.operation;
      if(current?.action === 'put') requireThat(editableTextNote(current.payload), 'rich_note_read_only');
      if(! options.resolutionOf && current?.action === 'put' && current.payload.body === body && current.payload.paper_id === paperId) {
        delete state.drafts[id];
        return current;
      }
      const observed = options.observed ?? own(state.draftBases ?? {}, id);
      if(current || observed) assertObserved(state, id, paperId, observed);
      const payload = current?.action === 'put' ? {...copy(current.payload), body} : {paper_id:paperId, body};
      requireThat(payload.paper_id === paperId, 'cannot_reparent');
      const op = buildOperation(state, 'note', id, payload, options);
      enqueue(state, op);
      delete state.drafts[id];
      delete state.draftBases?.[id];
      return op;
    });
    this.onChange('saved_locally');
    return result;
  }
  async deleteNote(id, options = {}) {
    const result = await this.store.update(state => {
      const previous = optimistic(state).entities[keyOf('note', id)]?.operation;
      const paperId = previous?.payload.paper_id ?? previous?.parents.find(p => p.kind === 'paper')?.id;
      assertObserved(state, id, paperId, options.observed ?? own(state.draftBases ?? {}, id));
      if(! options.resolutionOf && previous?.entity_type === 'note' && previous.entity_id === id && previous.action === 'delete') return previous;
      return enqueue(
      state,
      buildOperation(state, 'note', id, {}, {
        ...options,
        action: 'delete'
      })
      );
    });
    this.onChange('saved_locally');
    return result;
  }
  async reading(memberId, listId, paperId, value) {
    const result = await this.store.update(state => {
      const old = optimistic(state).entities[keyOf('reading_state', memberId)]?.operation.payload;
      if(old?.state === value) return null;
      const now = new Date().toISOString();
      return enqueue(
      state,
      buildOperation(
      state,
      'reading_state',
      memberId,
      {
        list_id: listId,
        paper_id: paperId,
        state: value,
        delivered_at: old?.delivered_at ??(value === 'delivered' ? now: null),
        read_at: value === 'read' ?(old?.read_at ?? now): null
      }
      )
      );
    });
    this.onChange('saved_locally');
    return result;
  }
  async resolve(conflictId, {
    body = null,
    discard = false,
    restore = false
  } = {}) {
    const state = await this.store.read(),
    conflict = own(state.conflicts, conflictId);
    requireThat(conflict && ! conflict.resolvedBy, 'unknown_conflict');
    const op = conflict.event.operation;
    requireThat(op.entity_type === 'note', 'unsupported_resolution');
    if(discard) {
      const canonical = state.entities[keyOf('note', op.entity_id)]?.operation;
      if(canonical?.action === 'put' && active(state, 'note', op.entity_id)) return this.saveNote(
      op.entity_id,
      canonical.payload.paper_id,
      canonical.payload.body,
      {
        resolutionOf: conflictId,
        observed: observeNote(state, op.entity_id, canonical.payload.paper_id)
      }
      );
      return this.deleteNote(
      op.entity_id,
      {
        resolutionOf: conflictId,
        observed: observeNote(state, op.entity_id, op.parents.find(p => p.kind === 'paper').id)
      }
      );
    }
    return this.saveNote(
    op.entity_id,
    op.payload.paper_id,
    body ?? op.payload.body,
    {
      resolutionOf: conflictId,
      restore,
      observed: observeNote(state, op.entity_id, op.payload.paper_id)
    }
    );
  }
  sync() {
    if(this.running) return this.running;
    const generation = this.generation;
    this.running = this.syncRun(generation).finally(() => {
      this.running = null;
    });
    return this.running;
  }
  async syncRun(generation) {
    await this.authenticated(generation);
    this.onChange('syncing');
    // Validate the retained frontier before upload or local reconciliation.
    const retained = await this.store.read();this.check(generation);
    const proofs=[];
    if(retained.cursor) {
      proofs.push({sequence:retained.cursor});
    }
    let acknowledged=null;
    for(const item of retained.outbox) {
      if(!item.acknowledged)continue;
      const event=item.acknowledged;
      validateEvent(event,retained.workspace);
      requireThat(stable(event.operation)===stable(item.operation),'sync_history_unavailable');
      if(acknowledged?.sequence===event.sequence)
        requireThat(stable(acknowledged)===stable(event),'sync_history_unavailable');
      if(!acknowledged || event.sequence>acknowledged.sequence)acknowledged=event;
    }
    if(acknowledged && acknowledged.sequence>retained.cursor)proofs.push(acknowledged);
    for(const proof of proofs) {
      this.check(generation);
      const frontier = await this.transport.pull(this.#token, proof.sequence - 1, 1,
        this.controller.signal);
      this.check(generation);
      requireThat(Array.isArray(frontier) && frontier.length === 1 &&
        frontier[0]?.sequence === proof.sequence, 'sync_history_unavailable');
      validateEvent(frontier[0], retained.workspace);
      const previous=proof.operation?proof:own(retained.receipts,frontier[0].operation.operation_id);
      requireThat(previous?.sequence===proof.sequence && stable(previous) === stable(frontier[0]), 'sync_history_unavailable');
    }
    requireThat(typeof this.transport.history_page==='function' &&
      typeof this.transport.push_verified==='function',HISTORY_ERROR);
    const seed=await historySeed(retained.workspace);this.check(generation);
    let remaining=25;
    const fetchPage=async(state,limit=100)=>{
      this.check(generation);
      requireThat(state.workspace===retained.workspace && state.device===retained.device,HISTORY_ERROR);
      const before=copy(retainedHistory(state,seed).received);
      const raw=await this.transport.history_page(this.#token,before.sequence,limit,before,this.controller.signal);
      this.check(generation);
      const page=await historyPage(raw,retained.workspace,before,limit);this.check(generation);
      return page;
    };
    // Replay retained inbox records before adopting a proof. Never seed a higher remote digest.
    for(;;) {
      const state=await this.store.read(),history=retainedHistory(state,seed);this.check(generation);
      if(history.received.sequence===state.cursor)break;
      if(!remaining--) {this.onChange('more_pending');return state;}
      const page=await fetchPage(state,Math.min(100,state.cursor-history.received.sequence));
      await this.store.update(next=>{
        this.check(generation);
        const current=retainedHistory(next,seed);
        requireThat(next.workspace===retained.workspace && next.device===retained.device &&
          next.cursor===state.cursor && stable(current)===stable(history),HISTORY_ERROR);
        requireThat(page.events.length>0,HISTORY_ERROR);
        for(const event of page.events) {
          const previous=own(next.receipts,event.operation.operation_id);
          requireThat(previous?.sequence===event.sequence && stable(previous)===stable(event),HISTORY_ERROR);
        }
        requireThat(page.checkpoint.sequence<=next.cursor,HISTORY_ERROR);
        current.received=copy(page.checkpoint);next.history=current;
      });
    }
    const applyPage=async(state,page)=>this.store.update(next=>{
      this.check(generation);
      const history=retainedHistory(next,seed),prior=retainedHistory(state,seed);
      requireThat(next.workspace===retained.workspace && next.device===retained.device &&
        next.cursor===state.cursor && stable(history)===stable(prior) &&
        next.cursor===page.before.sequence,HISTORY_ERROR);
      const ack=history.acknowledged;
      requireThat(!page.caught_up || page.checkpoint.sequence>=ack.sequence,HISTORY_ERROR);
      if(page.before.sequence<ack.sequence && ack.sequence<=page.checkpoint.sequence)
        requireThat(page.points.get(ack.sequence)===ack.sha256,HISTORY_ERROR);
      for(const event of page.events) {
        const pending=next.outbox.find(item=>item.operation.operation_id===event.operation.operation_id);
        if(pending?.acknowledged)requireThat(stable(pending.acknowledged)===stable(event),HISTORY_ERROR);
      }
      receive(next,page.events);reconcilePositionIntents(next);
      history.received=copy(page.checkpoint);next.history=history;
    });
    const catchUp=async()=>{
      while(remaining>0) {
        remaining--;
        const state=await this.store.read(),page=await fetchPage(state);
        await applyPage(state,page);
        if(page.caught_up)return true;
      }
      return false;
    };
    // Receive first: uploads require the complete observed prefix and an unchanged authority tip.
    if(!await catchUp()) {const state=await this.store.read();this.check(generation);this.onChange('more_pending');return state;}
    const queued=(await this.store.read()).outbox.slice(0,100);
    for(const item of queued) {
      this.check(generation);
      if(item.acknowledged)continue;
      if(!await preparePositionPush(this,item.operation,this.#token,generation))continue;
      const state=await this.store.read(),anchor=copy(historyAnchor(retainedHistory(state,seed)));
      this.check(generation);
      requireThat(state.workspace===retained.workspace && state.device===retained.device,HISTORY_ERROR);
      const response=await this.transport.push_verified(this.#token,copy(item.operation),anchor,this.controller.signal);
      this.check(generation);
      requireThat(response && typeof response==='object' && !Array.isArray(response) &&
        Object.keys(response).sort().join(',')==='checkpoint,record',HISTORY_ERROR);
      historyPoint(response.checkpoint);
      const event=historyRecord(response.record,retained.workspace,anchor.sequence+1);
      requireThat(stable(event.operation)===stable(item.operation) && event.sequence===anchor.sequence+1 &&
        response.checkpoint.sequence===event.sequence,HISTORY_ERROR);
      const digest=await historyStep(anchor.sha256,response.record);this.check(generation);
      requireThat(digest===response.checkpoint.sha256,HISTORY_ERROR);
      await this.store.update(next=>{
        this.check(generation);
        const history=retainedHistory(next,seed);
        requireThat(next.workspace===retained.workspace && next.device===retained.device &&
          stable(historyAnchor(history))===stable(anchor),HISTORY_ERROR);
        const pending=next.outbox.find(x=>x.operation.operation_id===item.operation.operation_id);
        requireThat(pending && !pending.acknowledged && stable(pending.operation)===stable(item.operation),HISTORY_ERROR);
        pending.acknowledged=copy(event);history.acknowledged=copy(response.checkpoint);
      });
    }
    const exhausted=await catchUp();this.check(generation);
    const final=await this.store.read();this.check(generation);
    this.onChange(exhausted && !final.outbox.length?'synced':'more_pending');return final;
  }
  async historyCheckpoint(generation=this.generation) {
    const state=await this.store.read();this.check(generation);
    const seed=await historySeed(state.workspace);this.check(generation);
    const history=retainedHistory(state,seed);
    requireThat(history.received.sequence===state.cursor,HISTORY_ERROR);
    return copy(historyAnchor(history));
  }
  download(paperId) {
    if(this.downloads.has(paperId)) return this.downloads.get(paperId);
    const generation = this.generation,
    promise = this.downloadRun(paperId, generation).finally(() => this.downloads.delete(paperId));
    this.downloads.set(paperId, promise);
    return promise;
  }
  async downloadRun(paperId, generation) {
    return downloadDocument(this,paperId,this.#token,generation);
  }
  prepareOffline(paperId,{current=()=>true,signal}={}) {
    const key='reading:'+paperId;
    if(this.downloads.has(key))return this.downloads.get(key);
    const generation=this.generation;
    const job=prepareReading(this,paperId,this.#token,generation,{current,signal})
      .finally(()=>this.downloads.delete(key));
    this.downloads.set(key,job);return job;
  }
  async pdf(paperId) {
    const state = await this.store.read(),
    target = documentTarget(state, paperId);
    requireThat(target, 'file_unavailable');
    const file = state.files[target.payload.sha256];
    requireThat(file?.verified, 'file_unavailable');
    const bytes = join(file.chunks, file.size);
    requireThat(await sha256(bytes) === target.payload.sha256, 'corrupt_file');
    requireThat(stable(documentTarget(await this.store.read(), paperId)) === stable(target), 'stale_document');
    return {
      bytes,
      sha256: target.payload.sha256
    };
  }
  downloadArtifact(id) {
    const key = 'artifact:' + id;
    if(this.downloads.has(key)) return this.downloads.get(key);
    const generation = this.generation;
    const job = downloadArtifact(this,id,this.#token,generation).finally(() => this.downloads.delete(key));
    this.downloads.set(key,job);
    return job;
  }
  async deck(id) { return readArtifact(this,id,'deck'); }
  async originalSource(id) { return readArtifact(this,id,'original_source'); }
  async legacyBrief(id) { return readArtifact(this,id,'legacy_brief'); }
  async survey(id) { return readArtifact(this,id,'survey'); }
  async exportLocal({drafts={}}={}) {
    const state = await this.store.read();
    state.drafts={...state.drafts,...drafts};
    return exportPositionRecovery(state);
  }
}
function join(chunks, size) {
  const bytes = new Uint8Array(size);
  let offset = 0;
  for(const chunk of chunks) {
    requireThat(chunk instanceof Uint8Array && offset + chunk.length <= size, 'invalid_file');
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  requireThat(offset === size, 'invalid_file');
  return bytes;
}

async function downloadDocument(engine,paperId,token,generation) {
    await engine.authenticated(generation);
    const state = await engine.store.read(),
    target = documentTarget(state, paperId);
    requireThat(target, 'file_unavailable');
    const {
      sha256: hash,
      size
    } = target.payload;
    requireThat(size <= MAX_LOCAL_PDF, 'file_too_large');
    const existing = state.files[hash],
    chunks = existing?.size === size ? copy(existing.chunks): [];
    let offset = chunks.reduce((total, c) => total + c.byteLength, 0);
    requireThat(offset <= size, 'invalid_file');
    while(offset < size) {
      engine.check(generation);
      const bytes = await engine.transport.blob_read(token, hash, size, offset, CHUNK, engine.controller.signal);
      engine.check(generation);
      requireThat(bytes instanceof Uint8Array && bytes.length === Math.min(CHUNK, size - offset), 'invalid_file');
      chunks.push(bytes);
      offset += bytes.length;
      await engine.store.update(next => {
        engine.check(generation);
        requireThat(stable(documentTarget(next, paperId)) === stable(target), 'stale_document');
        next.files[hash] = {
          size,
          chunks: copy(chunks),
          verified: false
        };
      });
      engine.onChange('downloading', Math.floor(offset / size * 100));
    }
    const bytes = join(chunks, size);
    if(await sha256(bytes) !== hash) {
      await engine.store.update(next => {
        engine.check(generation);
        next.files[hash] = {
          size,
          chunks: [],
          verified: false
        };
      });
      throw new Error('corrupt_file');
    }
    requireThat(
    new TextDecoder().decode(bytes.slice(0, 5)) === '%PDF-' && new TextDecoder().decode(bytes.slice(- 1024)).includes('%%EOF'),
    'invalid_pdf'
    );
    engine.check(generation);
    await engine.store.update(next => {
      engine.check(generation);
      requireThat(stable(documentTarget(next, paperId)) === stable(target), 'stale_document');
      next.files[hash] = {
        size,
        chunks: copy(chunks),
        verified: true
      };
    });
    engine.onChange('file_ready');
    return hash;
  }

const READING_METADATA_BYTES=64*1024**2;
const READING_ARTIFACTS=258;
function readingView(state) {
  // Cache bytes and drafts are not graph input: never clone them to plan a transfer.
  const outbox=state.outbox.filter(({operation:op})=>op.entity_type!=='reading_state' &&
    (op.entity_type!=='note'||op.payload.anchor||
      state.entities[keyOf('note',op.entity_id)]?.operation.payload.anchor));
  const metadata={...state,outbox,files:{},artifactFiles:{},appliedArtifacts:{},
    drafts:{},draftBases:{},readProjection:null};
  return outbox.length?optimistic(metadata):metadata;
}
function readingRows(view,paper) {
  return Object.values(view.entities).map(row=>row.operation).filter(op=>
    op.action==='put' && active(view,op.entity_type,op.entity_id) &&
    ((op.entity_type==='research_content'&&op.payload.scope?.kind==='paper'&&
       op.payload.scope.id===paper) ||
     (op.entity_type==='note'&&op.payload.paper_id===paper&&op.payload.anchor) ||
     (op.entity_type==='research_file'&&op.payload.paper_id===paper&&op.payload.feature==='deck')))
    .sort((a,b)=>keyOf(a.entity_type,a.entity_id).localeCompare(keyOf(b.entity_type,b.entity_id)));
}
export function readingTargets(state,paperId) {
  const view=readingView(state),primary=documentTarget(view,paperId);
  requireThat(active(view,'paper',paperId)&&primary,'file_unavailable');
  validateOperation(primary,state.workspace);
  requireThat(primary.payload.size<=MAX_LOCAL_PDF,'file_too_large');
  requireThat(stable(documentTarget(state,paperId))===stable(primary),'stale_reading');
  const rows=readingRows(view,paperId),artifacts=new Map(),references=new Map(),warnings=[];
  let metadataBytes=0;
  const warningKeys=new Set();
  const warn=(id,reason)=>{const key=stable([id,reason]);
    if(!warningKeys.has(key)){warningKeys.add(key);warnings.push({id,reason});}};
  function source(owner,hash,pin=null,parent=null) {
    const id=sourceFileId(owner,hash),target=artifactTarget(view,id);
    references.set(id,target);
    if(!target){warn(id,'missing_source');return;}
    validateOperation(target,state.workspace);validateArtifact(target.payload,id,target.parents);
    if(target.payload.feature!=='original_source'||target.payload.paper_id!==owner||
      target.payload.slot!==hash||target.payload.source_document_hash!==hash ||
      (pin&&(target.incarnation!==pin.incarnation||stable(target.parents)!==stable([parent])))) {
      warn(id,'stale_source');return;
    }
    artifacts.set(id,target);
  }
  for(const op of rows) {
    validateOperation(op,state.workspace);
    metadataBytes+=new TextEncoder().encode(stable(op)).length;
    requireThat(metadataBytes<=READING_METADATA_BYTES,'reading_too_large');
    const payload=op.payload;
    if(op.entity_type==='research_file') {
      validateArtifact(payload,op.entity_id,op.parents);artifacts.set(op.entity_id,op);
      if(payload.source_document_hash!==primary.payload.sha256)warn(op.entity_id,'unverified_deck_source');
    } else if(op.entity_type==='research_content'&&payload.feature==='lineage') {
      validateLineageOperation(op);
      for(const declared of payload.data.body_json.report.sources) {
        if(declared.availability!=='available'){warn(declared.id,'unavailable_source');continue;}
        const pin=op.source_dependencies.find(item=>item.source_id===declared.id);
        requireThat(pin,'reading_sources_unavailable');
        source(pin.paper_id,declared.document_hash,pin,op.parents.find(item=>item.id===pin.paper_id));
      }
    } else {
      const hash=op.entity_type==='note'?payload.anchor.document_hash:payload.source_document_hash;
      if(hash&&hash!==primary.payload.sha256)source(paperId,hash);
    }
    requireThat(artifacts.size<=READING_ARTIFACTS&&references.size<=READING_ARTIFACTS,'reading_too_large');
  }
  // Read-only mirrors may be readable but cannot grant original-file access.
  const snapshot=state.readProjection?.papers?.find(paper=>paper.id===paperId);
  for(const row of snapshot?.lineage??[]) {
    requireThat(typeof row?.body?.corpus_id==='string','reading_sources_unavailable');
    if(!rows.some(op=>op.payload.feature==='lineage'&&op.payload.key===row.body.corpus_id))
      warn(row.body.corpus_id,'unverified_snapshot_source');
  }
  for(const item of snapshot?.research_content??[]) {
    const hash=item.source_document_hash??item.data?.document_hash;
    if((hash&&hash!==primary.payload.sha256||
        ['claims','highlight_analysis','reading_links','research_questions'].includes(item.feature))&&
        !rows.some(op=>op.entity_type==='research_content'&&op.payload.feature===item.feature&&
          op.payload.key===item.key))warn(item.feature+':'+item.key,'unverified_snapshot_source');
  }
  const sizes=new Map();
  for(const op of artifacts.values())for(const item of [op.payload.body,...op.payload.assets]) {
    const prior=sizes.get(item.sha256);
    requireThat(prior===undefined||prior===item.size,'invalid_artifact');sizes.set(item.sha256,item.size);
  }
  requireThat([...sizes.values()].reduce((sum,size)=>sum+size,0)<=ARTIFACT_CACHE_BYTES,'storage_quota');
  return {paper_id:paperId,primary,contexts:rows,artifacts:[...artifacts.values()]
    .sort((a,b)=>a.entity_id.localeCompare(b.entity_id)),references:[...references.entries()]
    .sort(([a],[b])=>a.localeCompare(b)),warnings};
}
async function prepareReading(engine,paperId,token,generation,{current,signal}) {
  requireThat(typeof current==='function','stale_reading');
  const live=()=>{engine.check(generation);requireThat(current()===true&&!signal?.aborted,'stale_reading');};
  live();const initial=await engine.store.read();live();
  const plan=readingTargets(initial,paperId),signature=stable(plan),total=1+plan.artifacts.length;
  const keys=plan.contexts.map(op=>[keyOf(op.entity_type,op.entity_id),op.operation_id,op.incarnation]);
  let completed=0;
  const progress=()=>{live();engine.onChange('reading_preparing',{completed,total});};
  function checkState(state) {
    live();const view=readingView(state);
    requireThat(stable(documentTarget(view,paperId))===stable(plan.primary),'stale_reading');
    const now=readingRows(view,paperId).map(op=>[keyOf(op.entity_type,op.entity_id),op.operation_id,op.incarnation]);
    requireThat(stable(now)===stable(keys),'stale_reading');
    for(const op of plan.contexts)if(op.source_dependencies)requireThat(
      stable(view.entities[keyOf(op.entity_type,op.entity_id)]?.operation.source_dependencies)===
      stable(op.source_dependencies),'stale_reading');
    for(const [id,target] of plan.references)requireThat(stable(artifactTarget(view,id))===stable(target),'stale_reading');
    for(const target of plan.artifacts)requireThat(stable(artifactTarget(view,target.entity_id))===stable(target),'stale_reading');
  }
  const scope={transport:engine.transport,controller:engine.controller,
    check:()=>live(),authenticated:async()=>{live();await engine.authenticated(generation);live();},
    onChange:(code,percent)=>{live();engine.onChange('reading_preparing',{completed,total,
      ...(code==='downloading'&&Number.isInteger(percent)?{currentPercent:percent}:{})});},store:{
      read:async()=>{const state=await engine.store.read();checkState(state);return state;},
      update:change=>engine.store.update(state=>{checkState(state);return change(state);})}};
  progress();
  try {const cached=await engine.pdf(paperId);live();
    requireThat(cached.sha256===plan.primary.payload.sha256,'stale_reading');}
  catch(error){live();if(error.message!=='file_unavailable')throw error;
    await downloadDocument(scope,paperId,token,generation);}
  checkState(await engine.store.read());completed++;progress();
  for(const target of plan.artifacts) {
    let cached;
    try {cached=await readArtifact(scope,target.entity_id,target.payload.feature);}
    catch(error){if(error.message!=='artifact_unavailable')throw error;}
    if(!cached||cached.awaiting)await downloadArtifact(scope,target.entity_id,token,generation);
    const verified=await readArtifact(scope,target.entity_id,target.payload.feature);
    requireThat(!verified.awaiting&&stable(verified.operation)===stable(target),'stale_reading');
    checkState(await engine.store.read());completed++;progress();
  }
  const final=await engine.store.read();checkState(final);
  requireThat(stable(readingTargets(final,paperId))===signature,'stale_reading');
  const ready=plan.warnings.length===0;
  live();engine.onChange(ready?'reading_ready':'reading_partial',{completed,total});
  return {scope:'selected_current_manifests',paper_id:paperId,ready,
    verified_targets:completed,total_targets:total,warnings:copy(plan.warnings),
    whole_workspace_offline_verified:false};
}
