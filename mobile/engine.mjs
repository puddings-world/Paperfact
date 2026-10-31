import { downloadArtifact, readArtifact } from './artifact-engine.mjs';
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
    const generation = this.generation,
    signal = this.controller.signal;
    const identity = await this.transport.session_info(token, signal),
    state = await this.store.read();
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
      if(current?.action === 'put') requireThat(Object.keys(current.payload).length === 2, 'rich_note_read_only');
      if(! options.resolutionOf && current?.action === 'put' && current.payload.body === body && current.payload.paper_id === paperId) {
        delete state.drafts[id];
        return current;
      }
      const observed = options.observed ?? own(state.draftBases ?? {}, id);
      if(current || observed) assertObserved(state, id, paperId, observed);
      const op = buildOperation(state, 'note', id, {
        paper_id: paperId,
        body
      }, options);
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
    if((await this.store.read()).positionIntents || (await this.store.read()).positionRetentions)
      await this.store.update(state=>{this.check(generation);reconcilePositionIntents(state);});
    const queued =(await this.store.read()).outbox.slice(0, 100);
    for(const item of queued) {
      this.check(generation);
      if(item.acknowledged) continue;
      if(!await preparePositionPush(this,item.operation,this.#token,generation))continue;
      const event = await this.transport.push(this.#token, copy(item.operation), this.controller.signal);
      this.check(generation);
      validateEvent(event, item.operation.workspace_id);
      requireThat(stable(event.operation) === stable(item.operation), 'changed_retry');
      await this.store.update(state => {
        this.check(generation);
        const pending = state.outbox.find(x => x.operation.operation_id === item.operation.operation_id);
        if(pending) pending.acknowledged = copy(event);
      });
    }
    // Bound a foreground run; another foreground/retry continues from durable cursor.
    let exhausted = false;
    for(let page = 0; page < 25; page++) {
      const state = await this.store.read();
      this.check(generation);
      const events = await this.transport.pull(this.#token, state.cursor, 100, this.controller.signal);
      this.check(generation);
      if(! events.length) {
        exhausted = true;
        break;
      }
      await this.store.update(next => {
        this.check(generation);
        receive(next, events);
        reconcilePositionIntents(next);
      });
    }
    this.check(generation);
    const final = await this.store.read();
    this.onChange(exhausted && ! final.outbox.length ? 'synced': 'more_pending');
    return final;
  }
  download(paperId) {
    if(this.downloads.has(paperId)) return this.downloads.get(paperId);
    const generation = this.generation,
    promise = this.downloadRun(paperId, generation).finally(() => this.downloads.delete(paperId));
    this.downloads.set(paperId, promise);
    return promise;
  }
  async downloadRun(paperId, generation) {
    await this.authenticated(generation);
    const state = await this.store.read(),
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
      this.check(generation);
      const bytes = await this.transport.blob_read(this.#token, hash, size, offset, CHUNK, this.controller.signal);
      this.check(generation);
      requireThat(bytes instanceof Uint8Array && bytes.length === Math.min(CHUNK, size - offset), 'invalid_file');
      chunks.push(bytes);
      offset += bytes.length;
      await this.store.update(next => {
        this.check(generation);
        requireThat(stable(documentTarget(next, paperId)) === stable(target), 'stale_document');
        next.files[hash] = {
          size,
          chunks: copy(chunks),
          verified: false
        };
      });
      this.onChange('downloading', Math.floor(offset / size * 100));
    }
    const bytes = join(chunks, size);
    if(await sha256(bytes) !== hash) {
      await this.store.update(next => {
        this.check(generation);
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
    this.check(generation);
    await this.store.update(next => {
      this.check(generation);
      requireThat(stable(documentTarget(next, paperId)) === stable(target), 'stale_document');
      next.files[hash] = {
        size,
        chunks: copy(chunks),
        verified: true
      };
    });
    this.onChange('file_ready');
    return hash;
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
